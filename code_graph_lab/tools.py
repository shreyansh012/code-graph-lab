"""Bounded query tools for an AI-agent style caller.

Every tool has hard caps that the caller cannot raise. The caps bound how much
is returned. They do not bound run time: a regular expression that backtracks
a lot can run for a very long time (see search_text). Every query result has:
  stop_reason  why the tool stopped: complete, node_cap, depth_cap,
               line_cap or hit_cap
  counts       how much was returned
  limits       the caps that were really used (after clamping)

Bad input (unknown node, bad pattern, wrong type) raises ToolError. That is a
caller mistake, not a stop reason.
"""
from __future__ import annotations

import re
from collections import deque

from .model import TRUST_BY_RANK, TRUST_RANK, ToolError

HARD_MAX_DEPTH = 12
HARD_MAX_NODES = 500
HARD_MAX_LINES = 200
HARD_MAX_HITS = 100
HARD_MAX_LIST = 200
MAX_PATTERN_LENGTH = 200
MAX_HIT_TEXT = 160

DEFAULT_DEPTH = 3
DEFAULT_NODES = 50
DEFAULT_LINES = 60
DEFAULT_HITS = 20

STOP_REASONS = ("complete", "node_cap", "depth_cap", "line_cap", "hit_cap")


def _limit(name, value, hard, low):
    """Check one cap. Returns (effective value, was it clamped)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError("%s must be a whole number, got %r" % (name, value))
    if value < low:
        raise ToolError("%s must be at least %d, got %d" % (name, low, value))
    if value > hard:
        return hard, True
    return value, False


def _limits(**spec):
    """spec: name=(value, hard, low). Returns the limits block."""
    out = {}
    clamped = []
    for name, (value, hard, low) in spec.items():
        eff, was = _limit(name, value, hard, low)
        out[name] = eff
        if was:
            clamped.append(name)
    out["hard"] = {name: spec[name][1] for name in spec}
    out["clamped"] = clamped
    return out


def _edge_dict(e):
    d = {
        "src": e.src,
        "dst": e.dst,
        "kind": e.kind,
        "trust": e.trust,
        "name": e.name,
        "line": e.line,
        "count": e.count,
    }
    if e.note:
        d["note"] = e.note
    return d


def _node_dict(graph, node_id, depth, rank):
    n = graph.nodes[node_id]
    d = {"id": n.id, "kind": n.kind, "depth": depth, "path_trust": TRUST_BY_RANK[rank]}
    if n.file:
        d["file"] = n.file
        d["line"] = n.line
    return d


def _counts(nodes, edges):
    c = {"nodes": len(nodes), "edges": len(edges), "proven": 0, "inferred": 0, "unknown": 0}
    for e in edges:
        c[e["trust"]] += 1
    return c


def _walk(graph, start, limits, forward, max_depth):
    """Breadth-first walk over calls edges. Shared by trace_flow and find_reach."""
    start_id = graph.resolve(start)
    max_nodes = limits["max_nodes"]
    seen = {start_id: (0, 0)}  # id -> (depth, weakest trust rank on the path)
    order = [start_id]
    edges = []
    stop = "complete"
    depth_cut = False
    frontier = [start_id]
    depth = 0
    while frontier and stop == "complete":
        nxt = []
        for cur in frontier:
            outs = graph.out_edges(cur, "calls") if forward else graph.in_edges(cur, "calls")
            if max_depth is not None and depth >= max_depth:
                # At the limit, keep edges between nodes that are already in
                # the result. Edges to new nodes are cut.
                for e in outs:
                    if (e.dst if forward else e.src) in seen:
                        edges.append(e)
                    else:
                        depth_cut = True
                continue
            for e in outs:
                other = e.dst if forward else e.src
                if other not in seen:
                    if len(seen) >= max_nodes:
                        stop = "node_cap"
                        break
                    rank = max(seen[cur][1], TRUST_RANK[e.trust])
                    seen[other] = (depth + 1, rank)
                    order.append(other)
                    nxt.append(other)
                edges.append(e)
            if stop != "complete":
                break
        frontier = nxt
        depth += 1
    if stop == "complete" and depth_cut:
        stop = "depth_cap"
    nodes = [_node_dict(graph, i, seen[i][0], seen[i][1]) for i in order]
    edge_list = [_edge_dict(e) for e in edges]
    return start_id, stop, nodes, edge_list


def trace_flow(graph, start, max_depth=DEFAULT_DEPTH, max_nodes=DEFAULT_NODES):
    """Follow calls forward from start, level by level (breadth first)."""
    limits = _limits(max_depth=(max_depth, HARD_MAX_DEPTH, 0), max_nodes=(max_nodes, HARD_MAX_NODES, 1))
    start_id, stop, nodes, edges = _walk(graph, start, limits, True, limits["max_depth"])
    return {
        "tool": "trace_flow",
        "start": start_id,
        "stop_reason": stop,
        "counts": _counts(nodes, edges),
        "limits": limits,
        "nodes": nodes,
        "edges": edges,
    }


def find_reach(graph, node, max_nodes=DEFAULT_NODES):
    """Find everything that can reach node through calls (its callers, and theirs)."""
    limits = _limits(max_nodes=(max_nodes, HARD_MAX_NODES, 1))
    start_id, stop, nodes, edges = _walk(graph, node, limits, False, None)
    return {
        "tool": "find_reach",
        "node": start_id,
        "stop_reason": stop,
        "counts": _counts(nodes, edges),
        "limits": limits,
        "nodes": nodes,
        "edges": edges,
    }


def get_source(graph, node, max_lines=DEFAULT_LINES):
    """Return the source lines of a module, class or function."""
    limits = _limits(max_lines=(max_lines, HARD_MAX_LINES, 1))
    node_id = graph.resolve(node)
    n = graph.nodes[node_id]
    lines = graph.sources.get(n.module)
    if lines is None or n.kind not in ("module", "class", "function"):
        raise ToolError("node %r has no source text" % node_id)
    chunk = lines[n.line - 1 : n.end_line]
    total = len(chunk)
    cap = limits["max_lines"]
    shown = chunk[:cap]
    return {
        "tool": "get_source",
        "node": node_id,
        "file": n.file,
        "start_line": n.line,
        "end_line": n.line + len(shown) - 1,
        "stop_reason": "line_cap" if total > cap else "complete",
        "counts": {"lines_returned": len(shown), "lines_total": total},
        "limits": limits,
        "source": "\n".join(shown),
    }


def _innermost(graph, module, line):
    best = None
    for n in graph.defs_in_module(module):
        if n.line <= line <= n.end_line:
            if best is None or (n.end_line - n.line) <= (best.end_line - best.line):
                best = n
    return best.id if best else module


def search_text(graph, pattern, max_hits=DEFAULT_HITS, ignore_case=False, literal=False):
    """Search source lines with a regular expression, or with plain text if
    literal is True.

    Run time is NOT capped in regular expression mode. The pattern length
    limit does not stop a pattern that backtracks for a very long time. Use
    literal=True for text that is not meant to be a pattern.
    """
    limits = _limits(max_hits=(max_hits, HARD_MAX_HITS, 1))
    if not isinstance(pattern, str) or not pattern:
        raise ToolError("pattern must be a non-empty string")
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise ToolError("pattern is longer than %d characters" % MAX_PATTERN_LENGTH)
    try:
        rx = re.compile(re.escape(pattern) if literal else pattern, re.IGNORECASE if ignore_case else 0)
    except re.error as exc:
        raise ToolError("bad pattern: %s" % exc)
    cap = limits["max_hits"]
    hits = []
    stop = "complete"
    modules = sorted(graph.sources)
    scanned = 0
    for module in modules:
        scanned += 1
        for number, text in enumerate(graph.sources[module], start=1):
            if rx.search(text):
                if len(hits) >= cap:
                    stop = "hit_cap"
                    break
                shown = text.strip()
                if len(shown) > MAX_HIT_TEXT:
                    shown = shown[: MAX_HIT_TEXT - 3] + "..."
                hits.append(
                    {
                        "module": module,
                        "file": graph.nodes[module].file,
                        "line": number,
                        "in": _innermost(graph, module, number),
                        "text": shown,
                    }
                )
        if stop != "complete":
            break
    return {
        "tool": "search_text",
        "pattern": pattern,
        "stop_reason": stop,
        "counts": {"hits": len(hits), "files_scanned": scanned, "files_total": len(modules)},
        "limits": limits,
        "hits": hits,
    }


def list_nodes(graph, contains="", kind="", limit=DEFAULT_NODES):
    """List node ids so a caller can find a name to trace."""
    limits = _limits(limit=(limit, HARD_MAX_LIST, 1))
    wanted = (kind,) if kind else ("module", "class", "function")
    ids = [i for i in sorted(graph.nodes) if graph.nodes[i].kind in wanted and contains in i]
    shown = ids[: limits["limit"]]
    return {
        "tool": "list_nodes",
        "stop_reason": "hit_cap" if len(ids) > len(shown) else "complete",
        "counts": {"returned": len(shown), "matching": len(ids)},
        "limits": limits,
        "nodes": [
            {"id": i, "kind": graph.nodes[i].kind, "file": graph.nodes[i].file, "line": graph.nodes[i].line}
            for i in shown
        ],
    }


def summary(graph):
    """Counts by node kind and by edge kind and trust label."""
    node_counts = {}
    for n in graph.nodes.values():
        node_counts[n.kind] = node_counts.get(n.kind, 0) + 1
    edge_counts = {}
    for e in graph.edges:
        row = edge_counts.setdefault(e.kind, {"proven": 0, "inferred": 0, "unknown": 0})
        row[e.trust] += 1
    return {
        "tool": "summary",
        "stop_reason": "complete",
        "counts": {"nodes": len(graph.nodes), "edges": len(graph.edges), "modules": len(graph.sources)},
        "nodes_by_kind": dict(sorted(node_counts.items())),
        "edges_by_kind_and_trust": dict(sorted(edge_counts.items())),
        "skipped": list(graph.skipped),
    }
