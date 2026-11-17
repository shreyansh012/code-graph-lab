import unittest

from helpers import FIXTURE, check_golden  # noqa: E402

from code_graph_lab import build_graph, find_reach, get_source, search_text, trace_flow


def edge_map(graph):
    return {(e.src, e.kind, e.dst): e for e in graph.edges}


class GoldenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = build_graph([FIXTURE])

    def test_full_graph(self):
        check_golden(self, "tinypkg_graph.json", self.graph.to_dict())

    def test_trace_flow(self):
        check_golden(self, "trace_main.json", trace_flow(self.graph, "tinypkg.app.main", 4, 50))

    def test_find_reach(self):
        check_golden(self, "reach_helper.json", find_reach(self.graph, "tinypkg.util.helper", 50))

    def test_search_text(self):
        check_golden(self, "search_step.json", search_text(self.graph, r"def step", 10))

    def test_get_source(self):
        check_golden(self, "source_drive.json", get_source(self.graph, "tinypkg.core.drive", 60))


class TrustLabelTests(unittest.TestCase):
    """Expected labels written out by reading the fixture, not copied from output."""

    @classmethod
    def setUpClass(cls):
        cls.graph = build_graph([FIXTURE])
        cls.edges = edge_map(cls.graph)

    def trust(self, src, kind, dst):
        return self.edges[(src, kind, dst)].trust

    def test_same_module_call_is_proven(self):
        self.assertEqual("proven", self.trust("tinypkg.core.Base.run", "calls", "tinypkg.core.Base.step"))

    def test_class_call_is_proven(self):
        self.assertEqual("proven", self.trust("tinypkg.core.drive", "calls", "tinypkg.core.Child"))

    def test_nested_function_call_is_proven(self):
        self.assertEqual("proven", self.trust("tinypkg.core.outer", "calls", "tinypkg.core.outer.inner"))

    def test_import_alias_call_is_proven(self):
        self.assertEqual("proven", self.trust("tinypkg.core.Child.step", "calls", "tinypkg.util.helper"))

    def test_module_attribute_call_is_proven(self):
        self.assertEqual("proven", self.trust("tinypkg.core.Other.step", "calls", "tinypkg.util.helper"))

    def test_reexported_name_is_proven(self):
        # app imports helper from the package, which re-exports it from util.
        self.assertEqual("proven", self.trust("tinypkg.app.main", "calls", "tinypkg.util.helper"))

    def test_method_name_match_keeps_all_candidates(self):
        for cls in ("Base", "Child", "Other"):
            dst = "tinypkg.core.%s.step" % cls
            self.assertEqual("inferred", self.trust("tinypkg.core.drive", "calls", dst))

    def test_unknown_calls(self):
        for label in ("items.append", "len", "os.getcwd", "items.mystery"):
            self.assertEqual("unknown", self.trust("tinypkg.core.drive", "calls", "?" + label))

    def test_unknown_notes_say_why(self):
        e = self.edges
        self.assertEqual("builtin", e[("tinypkg.core.drive", "calls", "?len")].note)
        self.assertEqual("external", e[("tinypkg.core.drive", "calls", "?os.getcwd")].note)

    def test_imports_and_defines_are_proven(self):
        self.assertEqual("proven", self.trust("tinypkg.core", "imports", "tinypkg.util"))
        self.assertEqual("proven", self.trust("tinypkg.core", "imports", "ext:os"))
        self.assertEqual("proven", self.trust("tinypkg.core.Child", "defines", "tinypkg.core.Child.step"))

    def test_label_rules_hold_for_every_edge(self):
        real = ("module", "class", "function")
        counts = {"proven": 0, "inferred": 0, "unknown": 0}
        for e in self.edges.values():
            counts[e.trust] += 1
            dst_kind = self.graph.nodes[e.dst].kind
            if e.kind in ("defines", "imports"):
                self.assertEqual("proven", e.trust, e)
            elif e.trust == "unknown":
                self.assertEqual("unresolved", dst_kind, e)
                self.assertTrue(e.note, e)
            elif e.trust == "inferred":
                self.assertIn(dst_kind, real, e)
                self.assertTrue("share this name" in e.note or "candidate" in e.note, e)
            else:
                self.assertIn(dst_kind, real, e)
                self.assertEqual("", e.note, e)
        self.assertEqual({"proven": 28, "inferred": 4, "unknown": 4}, counts)


if __name__ == "__main__":
    unittest.main()
