"""Plain data model for the code graph.

A graph has nodes (modules, classes, functions) and edges (defines, imports,
calls). Every edge has a trust label: proven, inferred or unknown.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

# Lower number = stronger. The weakest label on a path is the largest number.
TRUST_RANK = {"proven": 0, "inferred": 1, "unknown": 2}
TRUST_BY_RANK = {v: k for k, v in TRUST_RANK.items()}

EDGE_KINDS = ("defines", "imports", "calls")
NODE_KINDS = ("module", "class", "function", "external", "unresolved")


class ToolError(Exception):
    """Raised when a caller asks for something that cannot be answered."""


@dataclass
class Node:
    id: str
    kind: str
    name: str
    module: str = ""
    file: str = ""
    line: int = 0
    end_line: int = 0
    parent: str = ""


@dataclass
class Edge:
    src: str
    dst: str
    kind: str
    trust: str
    name: str = ""
    line: int = 0
    count: int = 1
    note: str = ""


class Graph:
    """Holds nodes, edges and the source text of every module."""

    def __init__(self):
        self.nodes = {}
        self.sources = {}
        self.skipped = []
        self.edges = []
        self.variants = {}
        self._edge_map = {}
        self._out = {}
        self._in = {}
        self._module_nodes = {}

    # -- building -------------------------------------------------------
    def alloc(self, qualname):
        """Return a unique node id for a qualified name.

        The first definition keeps the plain name. A second definition with
        the same name gets the suffix ~2, then ~3, and so on.
        """
        used = self.variants.setdefault(qualname, [])
        node_id = qualname if not used else "%s~%d" % (qualname, len(used) + 1)
        used.append(node_id)
        return node_id

    def add_node(self, node):
        self.nodes[node.id] = node

    def add_edge(self, src, dst, kind, trust, name="", line=0, note=""):
        key = (src, kind, dst, trust)
        old = self._edge_map.get(key)
        if old is None:
            self._edge_map[key] = Edge(src, dst, kind, trust, name, line, 1, note)
        else:
            old.count += 1
            if line and (old.line == 0 or line < old.line):
                old.line = line
                old.name = name

    def finalize(self):
        """Sort everything so the output never depends on input order."""
        self.edges = sorted(
            self._edge_map.values(),
            key=lambda e: (e.src, e.kind, e.dst, e.trust, e.line),
        )
        self._out = {}
        self._in = {}
        for e in self.edges:
            self._out.setdefault((e.src, e.kind), []).append(e)
            self._in.setdefault((e.dst, e.kind), []).append(e)
        self.skipped = sorted(self.skipped)
        by_module = {}
        for n in self.nodes.values():
            if n.kind in ("class", "function"):
                by_module.setdefault(n.module, []).append(n)
        for lst in by_module.values():
            lst.sort(key=lambda n: (n.line, n.id))
        self._module_nodes = by_module

    # -- reading --------------------------------------------------------
    def out_edges(self, node_id, kind):
        return self._out.get((node_id, kind), [])

    def in_edges(self, node_id, kind):
        return self._in.get((node_id, kind), [])

    def defs_in_module(self, module):
        return self._module_nodes.get(module, [])

    def resolve(self, name):
        """Find one node from an exact id or a unique dotted suffix."""
        if name in self.nodes:
            return name
        real = [n for n in self.nodes.values() if n.kind in ("module", "class", "function")]
        tail = "." + name
        matches = sorted(n.id for n in real if n.id.endswith(tail))
        if len(matches) == 1:
            return matches[0]
        if not matches:
            near = sorted(n.id for n in real if name in n.id)[:5]
            hint = " Did you mean: %s" % ", ".join(near) if near else ""
            raise ToolError("no node named %r.%s" % (name, hint))
        shown = ", ".join(matches[:10])
        more = "" if len(matches) <= 10 else " (and %d more)" % (len(matches) - 10)
        raise ToolError("name %r is ambiguous: %s%s" % (name, shown, more))

    def to_dict(self):
        return {
            "schema": 1,
            "nodes": [asdict(self.nodes[k]) for k in sorted(self.nodes)],
            "edges": [asdict(e) for e in self.edges],
            "skipped": list(self.skipped),
        }
