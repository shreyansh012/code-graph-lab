import unittest

from helpers import FIXTURE, synthetic_source  # noqa: E402

from code_graph_lab import (
    ToolError,
    build_graph,
    build_graph_from_sources,
    find_reach,
    get_source,
    list_nodes,
    search_text,
    trace_flow,
)
from code_graph_lab import tools


def fan_out_graph(n):
    """root() calls f0() ... f(n-1)(). All calls are proven."""
    lines = ["def f%d():\n    return %d\n" % (i, i) for i in range(n)]
    lines.append("def root():\n" + "".join("    f%d()\n" % i for i in range(n)))
    return build_graph_from_sources([synthetic_source("fan", "\n".join(lines))])


def chain_graph(n):
    """c0 calls c1, c1 calls c2, and so on."""
    lines = ["def c%d():\n    c%d()\n" % (i, i + 1) for i in range(n)]
    lines.append("def c%d():\n    return 0\n" % n)
    return build_graph_from_sources([synthetic_source("chain", "\n".join(lines))])


class NodeCapTests(unittest.TestCase):
    def test_trace_stops_at_node_cap(self):
        g = fan_out_graph(30)
        r = trace_flow(g, "fan.root", 5, 10)
        self.assertEqual("node_cap", r["stop_reason"])
        self.assertEqual(10, len(r["nodes"]))
        self.assertEqual(10, r["counts"]["nodes"])

    def test_exact_fit_is_complete(self):
        g = fan_out_graph(30)
        r = trace_flow(g, "fan.root", 5, 31)
        self.assertEqual("complete", r["stop_reason"])
        self.assertEqual(31, len(r["nodes"]))
        r = trace_flow(g, "fan.root", 5, 30)
        self.assertEqual("node_cap", r["stop_reason"])

    def test_find_reach_node_cap(self):
        lines = ["def target():\n    return 0\n"]
        lines += ["def caller%d():\n    target()\n" % i for i in range(20)]
        g = build_graph_from_sources([synthetic_source("reach", "\n".join(lines))])
        r = find_reach(g, "reach.target", 5)
        self.assertEqual("node_cap", r["stop_reason"])
        self.assertEqual(5, len(r["nodes"]))
        r = find_reach(g, "reach.target", 21)
        self.assertEqual("complete", r["stop_reason"])
        self.assertEqual(21, len(r["nodes"]))

    def test_edges_only_join_returned_nodes(self):
        g = fan_out_graph(30)
        r = trace_flow(g, "fan.root", 5, 7)
        ids = {n["id"] for n in r["nodes"]}
        for e in r["edges"]:
            self.assertIn(e["src"], ids)
            self.assertIn(e["dst"], ids)

    def test_hard_node_cap_cannot_be_raised(self):
        g = fan_out_graph(600)
        r = trace_flow(g, "fan.root", 5, 10 ** 9)
        self.assertEqual("node_cap", r["stop_reason"])
        self.assertEqual(tools.HARD_MAX_NODES, len(r["nodes"]))
        self.assertEqual(tools.HARD_MAX_NODES, r["limits"]["max_nodes"])
        self.assertEqual(["max_nodes"], r["limits"]["clamped"])


class DepthCapTests(unittest.TestCase):
    def test_depth_cap(self):
        g = chain_graph(20)
        r = trace_flow(g, "chain.c0", 3, 100)
        self.assertEqual("depth_cap", r["stop_reason"])
        self.assertEqual(4, len(r["nodes"]))
        self.assertEqual(3, max(n["depth"] for n in r["nodes"]))

    def test_depth_zero_returns_only_start(self):
        g = chain_graph(5)
        r = trace_flow(g, "chain.c0", 0, 100)
        self.assertEqual("depth_cap", r["stop_reason"])
        self.assertEqual(["chain.c0"], [n["id"] for n in r["nodes"]])

    def test_exact_depth_is_complete(self):
        g = chain_graph(3)
        r = trace_flow(g, "chain.c0", 3, 100)
        self.assertEqual("complete", r["stop_reason"])
        self.assertEqual(4, len(r["nodes"]))

    def test_hard_depth_cap_cannot_be_raised(self):
        g = chain_graph(60)
        r = trace_flow(g, "chain.c0", 10 ** 6, 500)
        self.assertEqual("depth_cap", r["stop_reason"])
        self.assertEqual(tools.HARD_MAX_DEPTH, max(n["depth"] for n in r["nodes"]))
        self.assertEqual(tools.HARD_MAX_DEPTH + 1, len(r["nodes"]))
        self.assertIn("max_depth", r["limits"]["clamped"])


class LineCapTests(unittest.TestCase):
    def setUp(self):
        body = "".join("    x%d = %d\n" % (i, i) for i in range(300))
        self.graph = build_graph_from_sources([synthetic_source("big", "def long_one():\n" + body)])

    def test_line_cap(self):
        r = get_source(self.graph, "big.long_one", 5)
        self.assertEqual("line_cap", r["stop_reason"])
        self.assertEqual(5, r["counts"]["lines_returned"])
        self.assertEqual(301, r["counts"]["lines_total"])
        self.assertEqual(5, len(r["source"].splitlines()))

    def test_complete_when_it_fits(self):
        g = build_graph([FIXTURE])
        r = get_source(g, "tinypkg.util.helper", 10)
        self.assertEqual("complete", r["stop_reason"])
        self.assertEqual("def helper(x):\n    return x + 1", r["source"])
        r = get_source(g, "tinypkg.util.helper", 2)
        self.assertEqual("complete", r["stop_reason"])
        r = get_source(g, "tinypkg.util.helper", 1)
        self.assertEqual("line_cap", r["stop_reason"])

    def test_hard_line_cap_cannot_be_raised(self):
        r = get_source(self.graph, "big.long_one", 10 ** 9)
        self.assertEqual(tools.HARD_MAX_LINES, len(r["source"].splitlines()))
        self.assertEqual("line_cap", r["stop_reason"])
        self.assertEqual(["max_lines"], r["limits"]["clamped"])


class HitCapTests(unittest.TestCase):
    def setUp(self):
        text = "".join("# needle %d\n" % i for i in range(300))
        self.graph = build_graph_from_sources([synthetic_source("hay", text)])

    def test_hit_cap(self):
        r = search_text(self.graph, "needle", 7)
        self.assertEqual("hit_cap", r["stop_reason"])
        self.assertEqual(7, len(r["hits"]))
        self.assertEqual(7, r["counts"]["hits"])

    def test_exact_fit_is_complete(self):
        r = search_text(self.graph, r"needle 1\d\b", 10)
        self.assertEqual("complete", r["stop_reason"])
        self.assertEqual(10, len(r["hits"]))
        r = search_text(self.graph, r"needle 1\d\b", 9)
        self.assertEqual("hit_cap", r["stop_reason"])

    def test_hard_hit_cap_cannot_be_raised(self):
        r = search_text(self.graph, "needle", 10 ** 9)
        self.assertEqual(tools.HARD_MAX_HITS, len(r["hits"]))
        self.assertEqual("hit_cap", r["stop_reason"])

    def test_list_nodes_cap(self):
        g = fan_out_graph(30)
        r = list_nodes(g, "", "", 5)
        self.assertEqual("hit_cap", r["stop_reason"])
        self.assertEqual(5, len(r["nodes"]))
        self.assertEqual(32, r["counts"]["matching"])  # 30 functions, root, and the module


class InputChecks(unittest.TestCase):
    def setUp(self):
        self.graph = build_graph([FIXTURE])

    def test_bad_numbers_are_rejected(self):
        for bad in (-1, "5", 2.5, None, True):
            with self.assertRaises(ToolError):
                trace_flow(self.graph, "tinypkg.app.main", bad, 10)
        with self.assertRaises(ToolError):
            trace_flow(self.graph, "tinypkg.app.main", 2, 0)

    def test_unknown_and_ambiguous_names(self):
        with self.assertRaises(ToolError):
            trace_flow(self.graph, "nope.nothing")
        with self.assertRaises(ToolError):
            trace_flow(self.graph, "step")  # three methods share this name

    def test_unique_suffix_is_accepted(self):
        r = trace_flow(self.graph, "app.main", 1, 5)
        self.assertEqual("tinypkg.app.main", r["start"])

    def test_bad_patterns_are_rejected(self):
        for bad in ("", "(", "x" * 201):
            with self.assertRaises(ToolError):
                search_text(self.graph, bad)

    def test_unresolved_node_has_no_source(self):
        with self.assertRaises(ToolError):
            get_source(self.graph, "?len")

    def test_stop_reasons_are_from_the_fixed_set(self):
        cases = [
            (trace_flow(self.graph, "tinypkg.app.main", 1, 50), "depth_cap"),
            (trace_flow(self.graph, "tinypkg.app.main", 9, 2), "node_cap"),
            (trace_flow(self.graph, "tinypkg.app.main", 9, 50), "complete"),
            (find_reach(self.graph, "tinypkg.util.helper", 2), "node_cap"),
            (find_reach(self.graph, "tinypkg.util.helper", 50), "complete"),
            (get_source(self.graph, "tinypkg.core.drive", 2), "line_cap"),
            (get_source(self.graph, "tinypkg.core.drive", 50), "complete"),
            (search_text(self.graph, "def", 2), "hit_cap"),
            (search_text(self.graph, "def", 50), "complete"),
            (list_nodes(self.graph, "", "", 2), "hit_cap"),
            (list_nodes(self.graph, "", "", 50), "complete"),
        ]
        for r, expected in cases:
            self.assertEqual(expected, r["stop_reason"], r["tool"])
            self.assertIn(r["stop_reason"], tools.STOP_REASONS)
            self.assertIn("counts", r)


if __name__ == "__main__":
    unittest.main()
