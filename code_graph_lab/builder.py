"""Build a code graph from Python source text, using only the ast module.

The code is never run or imported. Names are matched by reading the syntax.

Trust labels on every edge:
  proven   the target was found exactly (for example a call to a name that is
           defined in the same module, or an import that names a module).
  inferred a name match that could be wrong. Every candidate gets its own edge.
  unknown  the target could not be found inside the graph.
"""
from __future__ import annotations

import ast
import builtins
import os
import re
from pathlib import Path
from typing import NamedTuple

from .model import Graph, Node

BUILTIN_NAMES = frozenset(dir(builtins))
MAX_REEXPORT_HOPS = 8
SKIP_DIRS = frozenset({"__pycache__", ".git", ".venv", "venv", "node_modules"})
_LINE_BREAK = re.compile(r"\r\n|\r|\n")


def split_lines(text):
    """Split text into lines the way the ast module counts them.

    Only a newline, a carriage return, or both together end a line.
    str.splitlines() also splits on form feed and a few other characters,
    which would make line numbers drift.
    """
    if not text:
        return []
    lines = _LINE_BREAK.split(text)
    if lines[-1] == "":
        lines.pop()
    return lines


class SourceFile(NamedTuple):
    module: str  # dotted module name, for example "json.decoder"
    path: str  # path shown to users, for example "json/decoder.py"
    text: str
    is_package: bool  # True for __init__.py


def collect_sources(roots):
    """Read every .py file under each package folder in roots.

    Each root must be a folder that is a Python package. The folder name is
    the package name. Files are read in sorted order, but the builder sorts
    again, so the order does not matter. A relative root such as "." is turned
    into a full path first, so the real folder name is used.
    """
    files = []
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            raise FileNotFoundError("not a folder: %s" % root)
        root = root.resolve()
        pkg = root.name
        if not pkg.isidentifier():
            raise FileNotFoundError("root must be a named package folder: %s" % root)
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
            for fn in sorted(filenames):
                if not fn.endswith(".py"):
                    continue
                full = Path(dirpath) / fn
                rel = full.relative_to(root)
                parts = list(rel.with_suffix("").parts)
                is_pkg = parts[-1] == "__init__"
                if is_pkg:
                    parts = parts[:-1]
                module = ".".join([pkg] + parts)
                shown = "/".join([pkg] + list(rel.parts))
                # utf-8-sig drops a leading byte order mark and reads plain UTF-8 too.
                with open(full, "r", encoding="utf-8-sig", errors="replace") as fh:
                    text = fh.read()
                files.append(SourceFile(module, shown, text, is_pkg))
    return files


def build_graph(roots):
    return build_graph_from_sources(collect_sources(roots))


def build_graph_from_sources(files):
    return _Builder(files).build()


class _Scope:
    """A module, class or function body that is being walked."""

    __slots__ = ("id", "kind", "params", "defs", "cls")

    def __init__(self, node_id, kind, params=(), defs=None, cls=""):
        self.id = node_id
        self.kind = kind
        self.params = frozenset(params)
        self.defs = defs if defs is not None else {}
        self.cls = cls


class _Mod:
    def __init__(self, source):
        self.name = source.module
        self.path = source.path
        self.is_package = source.is_package
        self.text = source.text
        self.defs = {}  # module-level name -> list of node ids
        self.bindings = {}  # local name -> absolute dotted target
        self.imports = []  # (candidate modules, external name, line)
        self.pending = []  # (scope chain, func expression, line)
        self.tree = None


def _params(args):
    names = [a.arg for a in args.posonlyargs + args.args + args.kwonlyargs]
    if args.vararg:
        names.append(args.vararg.arg)
    if args.kwarg:
        names.append(args.kwarg.arg)
    return names


def _dotted(node):
    """Return ['a', 'b', 'c'] for a.b.c, or None if it is not a plain chain."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        parts.reverse()
        return parts
    return None


def _label(node):
    try:
        text = " ".join(ast.unparse(node).split())
    except Exception:  # pragma: no cover - defensive, ast.unparse rarely fails
        text = "<expression>"
    return text if len(text) <= 80 else text[:77] + "..."


class _Builder:
    def __init__(self, files):
        self.graph = Graph()
        self.mods = {}
        for f in sorted(files, key=lambda f: (f.module, f.path)):
            if f.module in self.mods:
                self.graph.skipped.append("%s: duplicate module name %s" % (f.path, f.module))
                continue
            self.mods[f.module] = _Mod(f)
        self.methods_by_name = {}

    # -- phase 1: nodes, defines edges, imports, call sites ---------------
    def build(self):
        g = self.graph
        order = sorted(self.mods)
        for name in order:
            mod = self.mods[name]
            node_id = g.alloc(name)
            lines = split_lines(mod.text)
            g.sources[name] = lines
            g.add_node(Node(node_id, "module", name.rsplit(".", 1)[-1], name, mod.path, 1, max(len(lines), 1)))
        for name in order:
            mod = self.mods[name]
            try:
                mod.tree = ast.parse(mod.text, filename=mod.path)
            except (SyntaxError, ValueError) as exc:
                g.skipped.append("%s: could not parse (%s)" % (mod.path, type(exc).__name__))
                continue
            except (RecursionError, MemoryError):
                g.skipped.append("%s: too deeply nested to read" % mod.path)
                continue
            scope = _Scope(name, "module", defs=mod.defs)
            self._walk(mod, mod.tree, (scope,))
        for n in g.nodes.values():
            if n.kind == "function" and n.parent in g.nodes and g.nodes[n.parent].kind == "class":
                self.methods_by_name.setdefault(n.name, []).append(n.id)
        for lst in self.methods_by_name.values():
            lst.sort()
        # -- phase 2: needs every module to be known ----------------------
        for name in order:
            mod = self.mods[name]
            self._add_import_edges(mod)
            self._add_call_edges(mod)
        g.finalize()
        return g

    def _walk(self, mod, node, chain):
        """Visit every child of node. Uses a stack, not recursion, so a very
        long expression cannot overflow the Python call stack."""
        stack = [(child, chain) for child in reversed(list(ast.iter_child_nodes(node)))]
        while stack:
            node, chain = stack.pop()
            for item in reversed(self._visit(mod, node, chain)):
                stack.append(item)

    def _visit(self, mod, node, chain):
        """Handle one node. Returns the (node, chain) pairs to visit next, in order."""
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            nxt = []
            for expr in list(node.decorator_list) + list(node.args.defaults):
                nxt.append((expr, chain))
            for expr in node.args.kw_defaults:
                if expr is not None:
                    nxt.append((expr, chain))
            if node.returns is not None:
                nxt.append((node.returns, chain))
            parent = chain[-1]
            cls = parent.id if parent.kind == "class" else parent.cls
            node_id = self._define(mod, node, parent, "function")
            scope = _Scope(node_id, "function", _params(node.args), cls=cls)
            inner = chain + (scope,)
            nxt.extend((stmt, inner) for stmt in node.body)
            return nxt
        if isinstance(node, ast.ClassDef):
            nxt = []
            for expr in list(node.decorator_list) + list(node.bases):
                nxt.append((expr, chain))
            for kw in node.keywords:
                nxt.append((kw.value, chain))
            parent = chain[-1]
            node_id = self._define(mod, node, parent, "class")
            scope = _Scope(node_id, "class", cls=node_id)
            inner = chain + (scope,)
            nxt.extend((stmt, inner) for stmt in node.body)
            return nxt
        if isinstance(node, ast.Call):
            mod.pending.append((chain, node.func, node.lineno))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    mod.bindings[alias.asname] = alias.name
                else:
                    first = alias.name.split(".")[0]
                    mod.bindings[first] = first
                mod.imports.append(([alias.name], alias.name, node.lineno))
            return []
        elif isinstance(node, ast.ImportFrom):
            base = self._absolute_base(mod, node.level, node.module)
            if base is not None:
                for alias in node.names:
                    if alias.name == "*":
                        mod.imports.append(([base], base, node.lineno))
                        continue
                    target = base + "." + alias.name
                    mod.bindings[alias.asname or alias.name] = target
                    mod.imports.append(([target, base], base, node.lineno))
            return []
        return [(child, chain) for child in ast.iter_child_nodes(node)]

    def _define(self, mod, node, parent, kind):
        node_id = self.graph.alloc(parent.id + "." + node.name)
        first = node.lineno
        if node.decorator_list:
            first = min([first] + [d.lineno for d in node.decorator_list])
        end = getattr(node, "end_lineno", None) or node.lineno
        self.graph.add_node(
            Node(node_id, kind, node.name, mod.name, mod.path, first, end, parent.id)
        )
        parent.defs.setdefault(node.name, []).append(node_id)
        self.graph.add_edge(parent.id, node_id, "defines", "proven", node.name, node.lineno)
        return node_id

    @staticmethod
    def _absolute_base(mod, level, module):
        if level == 0:
            return module
        pkg = mod.name.split(".") if mod.is_package else mod.name.split(".")[:-1]
        keep = len(pkg) - (level - 1)
        if keep < 1:
            return None
        parts = pkg[:keep] + (module.split(".") if module else [])
        return ".".join(parts)

    # -- phase 2: imports ---------------------------------------------------
    def _add_import_edges(self, mod):
        g = self.graph
        for candidates, external, line in mod.imports:
            dst = next((c for c in candidates if c in self.mods), None)
            if dst is None:
                dst = "ext:" + external
                if dst not in g.nodes:
                    g.add_node(Node(dst, "external", external))
            if dst != mod.name:
                g.add_edge(mod.name, dst, "imports", "proven", dst.replace("ext:", ""), line)

    # -- phase 2: calls -----------------------------------------------------
    def _add_call_edges(self, mod):
        g = self.graph
        for chain, func, line in mod.pending:
            src = chain[-1].id
            label = _label(func)
            for dst, trust, note in self._resolve(mod, chain, func):
                if dst is None:
                    dst = "?" + label
                    if dst not in g.nodes:
                        g.add_node(Node(dst, "unresolved", label))
                g.add_edge(src, dst, "calls", trust, label, line, note)

    def _resolve(self, mod, chain, func):
        if isinstance(func, ast.Name):
            return self._resolve_name(mod, chain, func.id)
        if isinstance(func, ast.Attribute):
            return self._resolve_attribute(mod, chain, func)
        return [(None, "unknown", "unresolved")]

    @staticmethod
    def _found(ids):
        """One exact definition is proven. Several same-name ones are inferred."""
        if len(ids) == 1:
            return [(ids[0], "proven", "")]
        note = "%d definitions share this name" % len(ids)
        return [(i, "inferred", note) for i in ids]

    def _resolve_name(self, mod, chain, name):
        if name in chain[-1].defs:
            return self._found(chain[-1].defs[name])
        for scope in reversed(chain):
            if scope.kind != "function":
                continue
            if name in scope.defs:
                return self._found(scope.defs[name])
            if name in scope.params:
                return [(None, "unknown", "local name or parameter")]
        if name in mod.defs:
            return self._found(mod.defs[name])
        target = mod.bindings.get(name)
        if target is not None:
            ids = self._lookup(target)
            if ids:
                return self._found(ids)
            if self._inside_graph(target):
                return [(None, "unknown", "imported name not found in its module")]
            return [(None, "unknown", "external")]
        if name in BUILTIN_NAMES:
            return [(None, "unknown", "builtin")]
        return [(None, "unknown", "unresolved")]

    def _resolve_attribute(self, mod, chain, func):
        attr = func.attr
        parts = _dotted(func)
        recv = func.value
        # self.method() and cls.method(): look in the enclosing class.
        if isinstance(recv, ast.Name) and recv.id in ("self", "cls"):
            cls_id = next((s.cls for s in reversed(chain) if s.cls), "")
            if cls_id:
                ids = self.graph.variants.get(cls_id + "." + attr, [])
                if ids:
                    return self._found(ids)
        if parts:
            first, rest = parts[0], parts[1:]
            # module.function(), Class.method() through an import.
            shadowed = any(first in s.params for s in chain)
            if first in mod.bindings and not shadowed:
                full = ".".join([mod.bindings[first]] + rest)
                ids = self._lookup(full)
                if ids:
                    return self._found(ids)
                if not self._inside_graph(full):
                    return [(None, "unknown", "external")]
            # Class.method() for a class in this module.
            elif first in mod.defs and len(mod.defs[first]) == 1:
                ids = self.graph.variants.get(mod.defs[first][0] + "." + ".".join(rest), [])
                if ids:
                    return self._found(ids)
        # Last resort: match by method name. Keep every candidate.
        cands = self.methods_by_name.get(attr, [])
        if cands:
            note = "method name match, %d candidate%s" % (len(cands), "" if len(cands) == 1 else "s")
            return [(c, "inferred", note) for c in cands]
        return [(None, "unknown", "unresolved")]

    # -- name lookup helpers ---------------------------------------------------
    def _inside_graph(self, dotted):
        parts = dotted.split(".")
        return any(".".join(parts[:i]) in self.mods for i in range(len(parts), 0, -1))

    def _lookup(self, dotted, hops=0):
        """Find node ids for a dotted name. Follows re-exports through imports."""
        if hops > MAX_REEXPORT_HOPS:
            return []
        parts = dotted.split(".")
        for i in range(len(parts), 0, -1):
            module = ".".join(parts[:i])
            if module not in self.mods:
                continue
            rest = parts[i:]
            if not rest:
                return [module]
            ids = self.graph.variants.get(module + "." + ".".join(rest), [])
            if ids:
                return list(ids)
            bound = self.mods[module].bindings.get(rest[0])
            if bound is not None and bound != dotted:
                return self._lookup(".".join([bound] + rest[1:]), hops + 1)
            return []
        return []
