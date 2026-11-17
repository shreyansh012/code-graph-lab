"""Command line front end. Every command prints one JSON document."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import tools
from .builder import build_graph
from .model import ToolError

REPO_ROOT = Path(__file__).resolve().parent.parent
DEMO_PACKAGE = REPO_ROOT / "examples" / "minishop"


def default_roots():
    """The standard library json package (found through the running interpreter)
    plus the demo package that ships with this repository."""
    import json as stdlib_json

    roots = [Path(stdlib_json.__file__).resolve().parent]
    if DEMO_PACKAGE.is_dir():
        roots.append(DEMO_PACKAGE)
    return roots


def _parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--root",
        action="append",
        metavar="DIR",
        help="a Python package folder to read (repeat for more). "
        "Default: the standard library json package and examples/minishop.",
    )
    p = argparse.ArgumentParser(
        prog="code_graph_lab",
        description="Build a code graph with trust labels and query it with capped tools.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("summary", parents=[common], help="count nodes and edges by trust label")

    s = sub.add_parser("list", parents=[common], help="list node ids")
    s.add_argument("--contains", default="", help="keep ids that contain this text")
    s.add_argument("--kind", default="", choices=["", "module", "class", "function", "external", "unresolved"])
    s.add_argument("--limit", type=int, default=tools.DEFAULT_NODES)

    s = sub.add_parser("trace", parents=[common], help="trace_flow: follow calls forward")
    s.add_argument("start")
    s.add_argument("--max-depth", type=int, default=tools.DEFAULT_DEPTH)
    s.add_argument("--max-nodes", type=int, default=tools.DEFAULT_NODES)

    s = sub.add_parser("reach", parents=[common], help="find_reach: who can reach this node")
    s.add_argument("node")
    s.add_argument("--max-nodes", type=int, default=tools.DEFAULT_NODES)

    s = sub.add_parser("source", parents=[common], help="get_source: print a node's code")
    s.add_argument("node")
    s.add_argument("--max-lines", type=int, default=tools.DEFAULT_LINES)

    s = sub.add_parser("search", parents=[common], help="search_text: regex search of the source (no time limit on the pattern)")
    s.add_argument("pattern")
    s.add_argument("--max-hits", type=int, default=tools.DEFAULT_HITS)
    s.add_argument("-i", "--ignore-case", action="store_true")
    s.add_argument(
        "--literal",
        action="store_true",
        help="match the text as it is, not as a regular expression. "
        "Regular expression mode has no time limit.",
    )

    s = sub.add_parser("dump", parents=[common], help="write the whole graph as JSON")
    s.add_argument("--out", metavar="FILE", help="write to a file instead of the screen")
    return p


def _run(args, graph):
    cmd = args.command
    if cmd == "summary":
        return tools.summary(graph)
    if cmd == "list":
        return tools.list_nodes(graph, args.contains, args.kind, args.limit)
    if cmd == "trace":
        return tools.trace_flow(graph, args.start, args.max_depth, args.max_nodes)
    if cmd == "reach":
        return tools.find_reach(graph, args.node, args.max_nodes)
    if cmd == "source":
        return tools.get_source(graph, args.node, args.max_lines)
    if cmd == "search":
        return tools.search_text(graph, args.pattern, args.max_hits, args.ignore_case, args.literal)
    return graph.to_dict()


def main(argv=None):
    args = _parser().parse_args(argv)
    out = getattr(args, "out", None)
    try:
        roots = [Path(r) for r in args.root] if args.root else default_roots()
        graph = build_graph(roots)
        result = _run(args, graph)
        text = json.dumps(result, indent=2)
        if out:
            with open(out, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text + "\n")
    except (ToolError, OSError) as exc:
        print(json.dumps({"error": str(exc)}, indent=2))
        return 2
    if out:
        print(json.dumps({"wrote": out, "bytes": len(text) + 1}))
    else:
        print(text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
