"""Tests for edge cases: depth boundaries, odd text, bad input, name rules."""
import os
import tempfile
import time
import unittest
from unittest import mock

from helpers import synthetic_source  # noqa: E402

from code_graph_lab import (
    SourceFile,
    build_graph_from_sources,
    collect_sources,
    get_source,
    search_text,
    trace_flow,
)
from code_graph_lab.builder import split_lines


def build(text, module="m"):
    return build_graph_from_sources([synthetic_source(module, text)])


def call_edges(graph, src=None):
    return {
        (e.src, e.dst, e.trust, e.note)
        for e in graph.edges
        if e.kind == "calls" and (src is None or e.src == src)
    }


def trace_edges(result):
    return {(e["src"], e["dst"]) for e in result["edges"]}


class DepthBoundaryTests(unittest.TestCase):
    def test_cycle_keeps_the_edge_back_at_the_limit(self):
        g = build("def a():\n    b()\n\ndef b():\n    a()\n")
        r = trace_flow(g, "m.a", 1, 50)
        self.assertEqual({("m.a", "m.b"), ("m.b", "m.a")}, trace_edges(r))
        self.assertEqual("complete", r["stop_reason"])

    def test_diamond_keeps_the_edge_between_nodes_at_the_limit(self):
        g = build("def a():\n    b()\n    c()\n\ndef b():\n    c()\n\ndef c():\n    return 1\n")
        r = trace_flow(g, "m.a", 1, 50)
        self.assertEqual(3, r["counts"]["nodes"])
        self.assertEqual({("m.a", "m.b"), ("m.a", "m.c"), ("m.b", "m.c")}, trace_edges(r))
        self.assertEqual("complete", r["stop_reason"])

    def test_edge_set_does_not_depend_on_the_depth_setting(self):
        g = build("def a():\n    a()\n")
        for depth in (0, 1, 3):
            r = trace_flow(g, "m.a", depth, 50)
            self.assertEqual({("m.a", "m.a")}, trace_edges(r), depth)
            self.assertEqual("complete", r["stop_reason"], depth)

    def test_edge_to_a_new_node_is_still_cut(self):
        g = build("def a():\n    b()\n\ndef b():\n    c()\n\ndef c():\n    return 1\n")
        r = trace_flow(g, "m.a", 1, 50)
        self.assertEqual({("m.a", "m.b")}, trace_edges(r))
        self.assertEqual("depth_cap", r["stop_reason"])


class DeepExpressionTests(unittest.TestCase):
    def test_long_expression_does_not_crash_the_build(self):
        for terms in (700, 2000):
            text = "def f():\n    return 1\n\ndef g():\n    return " + " + ".join(["f()"] * terms) + "\n"
            g = build(text)
            if g.skipped:
                self.assertEqual(["m.py: too deeply nested to read"], g.skipped)
            else:
                (edge,) = [e for e in g.edges if e.kind == "calls"]
                self.assertEqual(("m.g", "m.f", terms), (edge.src, edge.dst, edge.count))

    def test_parser_running_out_of_stack_skips_the_module(self):
        # Some Python versions give up on very deep input inside ast.parse.
        # Simulate that, so this path is tested on every version.
        with mock.patch("code_graph_lab.builder.ast.parse", side_effect=RecursionError("too deep")):
            g = build("x = 1\n")
        self.assertEqual(["m.py: too deeply nested to read"], g.skipped)
        self.assertIn("m", g.nodes)

    def test_long_expression_leaves_other_modules_alone(self):
        big = "def g():\n    return " + " + ".join(["1"] * 3000) + "\n"
        g = build_graph_from_sources(
            [synthetic_source("big", big), synthetic_source("ok", "def f():\n    return 1\n")]
        )
        self.assertIn("ok.f", g.nodes)


class LineNumberTests(unittest.TestCase):
    def test_split_lines_follows_the_ast_rules(self):
        self.assertEqual([], split_lines(""))
        self.assertEqual(["a", "b"], split_lines("a\nb\n"))
        self.assertEqual(["a", "b"], split_lines("a\r\nb"))
        self.assertEqual(["a", "", "b"], split_lines("a\r\rb\r"))
        self.assertEqual(["a\x0cb", "c\x85d e\x1cf"], split_lines("a\x0cb\nc\x85d e\x1cf\n"))

    def test_odd_line_breaks_do_not_shift_source_or_search(self):
        for odd in ("\x0c", "\x1c", "\x85", " ", " "):
            text = 'def a():\n    """doc %s here"""\n    return 1\n\n\ndef b():\n    return a()\n' % odd
            g = build(text)
            self.assertEqual("def b():\n    return a()", get_source(g, "m.b")["source"], repr(odd))
            hits = search_text(g, r"return a\(")["hits"]
            self.assertEqual(1, len(hits), repr(odd))
            self.assertEqual(7, hits[0]["line"], repr(odd))
            self.assertEqual("m.b", hits[0]["in"], repr(odd))

    def test_carriage_return_text_keeps_line_numbers(self):
        g = build("def a():\r\n    return 1\r\n\r\ndef b():\r\n    return a()\r\n")
        self.assertEqual("def b():\n    return a()", get_source(g, "m.b")["source"])
        g = build("def a():\r    return 1\r\rdef b():\r    return a()\r")
        self.assertEqual("def b():\n    return a()", get_source(g, "m.b")["source"])


class FileReadingTests(unittest.TestCase):
    def make_package(self, tmp, files):
        pkg = os.path.join(tmp, "pkg")
        os.mkdir(pkg)
        for name, data in files.items():
            with open(os.path.join(pkg, name), "wb") as fh:
                fh.write(data)
        return pkg

    def test_byte_order_mark_is_not_a_syntax_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = self.make_package(
                tmp,
                {"a.py": b"\xef\xbb\xbfdef a():\n    return 1\n", "b.py": b"def b():\n    return 2\n"},
            )
            g = build_graph_from_sources(collect_sources([pkg]))
        self.assertEqual([], g.skipped)
        self.assertIn("pkg.a.a", g.nodes)
        self.assertIn("pkg.b.b", g.nodes)

    def test_relative_root_uses_the_real_folder_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = self.make_package(tmp, {"__init__.py": b"", "a.py": b"x = 1\n"})
            here = os.getcwd()
            os.chdir(pkg)
            try:
                modules = sorted(f.module for f in collect_sources(["."]))
                try:
                    parent = [f.module for f in collect_sources([".."])]
                except FileNotFoundError:
                    parent = []  # the temporary parent folder is not a valid package name
            finally:
                os.chdir(here)
        self.assertEqual(["pkg", "pkg.a"], modules)
        for name in parent:
            self.assertFalse(name.startswith("."), name)
            self.assertNotIn("..", name)


class SearchModeTests(unittest.TestCase):
    def test_literal_mode_escapes_the_text(self):
        g = build("x = a.b(1)\ny = aXb(1)\n")
        self.assertEqual(2, search_text(g, r"a.b\(1\)")["counts"]["hits"])
        self.assertEqual(1, search_text(g, "a.b(1)", literal=True)["counts"]["hits"])

    def test_literal_mode_is_not_slow_for_a_nasty_pattern(self):
        g = build("x = '" + "a" * 40 + "!'\n")
        start = time.monotonic()
        r = search_text(g, "(a+)+$", literal=True)
        self.assertLess(time.monotonic() - start, 5)
        self.assertEqual(0, r["counts"]["hits"])

    def test_ignore_case(self):
        g = build("Step = 1\n")
        self.assertEqual(0, search_text(g, "STEP")["counts"]["hits"])
        self.assertEqual(1, search_text(g, "STEP", ignore_case=True)["counts"]["hits"])
        self.assertEqual(1, search_text(g, "STEP", ignore_case=True, literal=True)["counts"]["hits"])


class SkippedAndOrderTests(unittest.TestCase):
    def test_syntax_error_is_listed_and_the_module_node_stays(self):
        g = build_graph_from_sources(
            [synthetic_source("bad", "def broken(:\n"), synthetic_source("ok", "def f():\n    return 1\n")]
        )
        self.assertEqual(["bad.py: could not parse (SyntaxError)"], g.skipped)
        self.assertIn("bad", g.nodes)
        self.assertNotIn("bad.broken", g.nodes)
        self.assertIn("ok.f", g.nodes)

    def test_skipped_list_is_sorted(self):
        g = build_graph_from_sources(
            [
                SourceFile("z", "z1.py", "x = 1\n", False),
                SourceFile("z", "z2.py", "x = 2\n", False),
                SourceFile("a", "a.py", "def broken(:\n", False),
            ]
        )
        self.assertEqual(
            ["a.py: could not parse (SyntaxError)", "z2.py: duplicate module name z"],
            g.skipped,
        )

    def test_first_file_by_path_wins_whatever_the_input_order(self):
        one = SourceFile("m", "a.py", "def first():\n    return 1\n", False)
        two = SourceFile("m", "b.py", "def second():\n    return 2\n", False)
        for files in ([one, two], [two, one]):
            g = build_graph_from_sources(files)
            self.assertEqual("a.py", g.nodes["m"].file)
            self.assertIn("m.first", g.nodes)
            self.assertNotIn("m.second", g.nodes)
            self.assertEqual(["b.py: duplicate module name m"], g.skipped)


class NameRuleTests(unittest.TestCase):
    def test_two_definitions_with_one_name_give_two_inferred_edges(self):
        g = build("def f():\n    return 1\n\ndef f():\n    return 2\n\ndef g():\n    return f()\n")
        note = "2 definitions share this name"
        self.assertEqual(
            {("m.g", "m.f", "inferred", note), ("m.g", "m.f~2", "inferred", note)},
            call_edges(g, "m.g"),
        )

    def test_one_definition_is_proven(self):
        g = build("def f():\n    return 1\n\ndef g():\n    return f()\n")
        self.assertEqual({("m.g", "m.f", "proven", "")}, call_edges(g, "m.g"))

    def test_parameter_hides_a_module_name_in_a_call(self):
        g = build("def helper():\n    return 1\n\ndef k(helper):\n    return helper()\n")
        self.assertEqual({("m.k", "?helper", "unknown", "local name or parameter")}, call_edges(g, "m.k"))

    def test_parameter_hides_an_imported_module(self):
        util = synthetic_source("p.util", "def helper():\n    return 1\n")
        app = synthetic_source(
            "p.app",
            "from p import util\n\ndef f(util):\n    return util.helper()\n\ndef g():\n    return util.helper()\n",
        )
        g = build_graph_from_sources([util, app])
        self.assertEqual({("p.app.g", "p.util.helper", "proven", "")}, call_edges(g, "p.app.g"))
        self.assertEqual({("p.app.f", "?util.helper", "unknown", "unresolved")}, call_edges(g, "p.app.f"))

    def test_assigned_name_is_not_tracked_known_limit(self):
        # A documented limit: an assignment does not hide a module name, so the
        # call below is labelled proven although the real target is another object.
        g = build("def helper():\n    return 1\n\ndef f(other):\n    helper = other.make()\n    return helper()\n")
        self.assertIn(("m.f", "m.helper", "proven", ""), call_edges(g, "m.f"))

    def test_async_def_is_a_function_node(self):
        g = build("async def a():\n    return 1\n\nasync def b():\n    return await a()\n")
        self.assertEqual("function", g.nodes["m.a"].kind)
        self.assertEqual({("m.b", "m.a", "proven", "")}, call_edges(g, "m.b"))


class ImportRuleTests(unittest.TestCase):
    def test_package_does_not_import_itself(self):
        init = SourceFile("p", "p/__init__.py", "from . import thing\n\ndef thing():\n    return 1\n", True)
        g = build_graph_from_sources([init])
        self.assertEqual([], [e for e in g.edges if e.kind == "imports"])
        self.assertNotIn("ext:p", g.nodes)

    def test_relative_import_beyond_the_package_is_ignored(self):
        mod = synthetic_source("p.m", "from ... import x\n\ndef f():\n    return x()\n")
        g = build_graph_from_sources([mod])
        self.assertEqual([], g.skipped)
        self.assertEqual([], [e for e in g.edges if e.kind == "imports"])
        self.assertEqual({("p.m.f", "?x", "unknown", "unresolved")}, call_edges(g, "p.m.f"))

    def test_star_import_gives_an_import_edge_but_no_call_edges(self):
        other = synthetic_source("p.other", "def thing():\n    return 1\n")
        mod = synthetic_source("p.m", "from p.other import *\n\ndef f():\n    return thing()\n")
        g = build_graph_from_sources([other, mod])
        imports = [(e.src, e.dst, e.trust) for e in g.edges if e.kind == "imports"]
        self.assertEqual([("p.m", "p.other", "proven")], imports)
        self.assertEqual({("p.m.f", "?thing", "unknown", "unresolved")}, call_edges(g, "p.m.f"))


if __name__ == "__main__":
    unittest.main()
