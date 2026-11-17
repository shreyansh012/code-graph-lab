import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

from helpers import DEMO, FIXTURE  # noqa: E402

from code_graph_lab import cli


def run(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli.main(list(argv))
    return code, json.loads(buf.getvalue())


class CliTests(unittest.TestCase):
    def test_trace(self):
        code, out = run("trace", "tinypkg.app.main", "--max-depth", "2", "--root", str(FIXTURE))
        self.assertEqual(0, code)
        self.assertEqual("trace_flow", out["tool"])
        self.assertEqual("complete", out["stop_reason"])
        self.assertEqual(14, out["counts"]["nodes"])
        self.assertEqual(17, out["counts"]["edges"])

    def test_trace_depth_one_stops_with_depth_cap(self):
        code, out = run("trace", "tinypkg.app.main", "--max-depth", "1", "--root", str(FIXTURE))
        self.assertEqual(0, code)
        self.assertEqual("depth_cap", out["stop_reason"])
        self.assertEqual(4, out["counts"]["nodes"])

    def test_every_command_prints_stop_reason_and_counts(self):
        root = ("--root", str(FIXTURE))
        for argv in (
            ("reach", "tinypkg.util.helper"),
            ("source", "tinypkg.core.drive", "--max-lines", "3"),
            ("search", "step", "--max-hits", "2"),
            ("list", "--contains", "core"),
            ("summary",),
        ):
            code, out = run(*(argv + root))
            self.assertEqual(0, code, argv)
            self.assertIn("stop_reason", out)
            self.assertIn("counts", out)

    def test_ignore_case_changes_the_result(self):
        root = ("--root", str(FIXTURE))
        code, out = run("search", "STEP", "-i", *root)
        self.assertEqual(0, code)
        self.assertEqual(5, out["counts"]["hits"])
        code, out = run("search", "STEP", *root)
        self.assertEqual(0, code)
        self.assertEqual(0, out["counts"]["hits"])

    def test_literal_search_does_not_read_a_pattern(self):
        root = ("--root", str(FIXTURE))
        code, out = run("search", "items.append(1)", "--literal", *root)
        self.assertEqual(0, code)
        self.assertEqual(1, out["counts"]["hits"])
        # As a pattern, the dot matches any character and the brackets make a group.
        code, out = run("search", "items.append(1)", *root)
        self.assertEqual(0, out["counts"]["hits"])

    def test_error_exit_code(self):
        code, out = run("trace", "no.such.node", "--root", str(FIXTURE))
        self.assertEqual(2, code)
        self.assertIn("error", out)

    def test_missing_folder(self):
        code, out = run("summary", "--root", str(FIXTURE / "does-not-exist"))
        self.assertEqual(2, code)
        self.assertIn("error", out)

    def test_dump_to_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "graph.json")
            code, out = run("dump", "--root", str(FIXTURE), "--out", target)
            self.assertEqual(0, code)
            with open(target, encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertEqual(1, data["schema"])
            self.assertTrue(data["edges"])

    def test_dump_to_a_bad_path_is_an_error_not_a_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            for target in (os.path.join(tmp, "no_such_dir", "x.json"), tmp):
                code, out = run("dump", "--root", str(FIXTURE), "--out", target)
                self.assertEqual(2, code, target)
                self.assertIn("error", out)

    def test_unreadable_source_file_is_an_error_not_a_traceback(self):
        with mock.patch("code_graph_lab.builder.open", create=True, side_effect=PermissionError("denied")):
            code, out = run("summary", "--root", str(FIXTURE))
        self.assertEqual(2, code)
        self.assertIn("denied", out["error"])

    def test_relative_dot_root_uses_the_real_folder_name(self):
        here = os.getcwd()
        os.chdir(DEMO)
        try:
            code, out = run("list", "--root", ".", "--kind", "module")
        finally:
            os.chdir(here)
        self.assertEqual(0, code)
        ids = [n["id"] for n in out["nodes"]]
        self.assertEqual(["minishop", "minishop.models", "minishop.pricing", "minishop.report"], ids)

    def test_root_that_is_not_a_named_package_folder_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = os.path.join(tmp, "not-a-name")
            os.mkdir(bad)
            code, out = run("summary", "--root", bad)
        self.assertEqual(2, code)
        self.assertIn("named package folder", out["error"])

    def test_default_roots_include_stdlib_json(self):
        code, out = run("list", "--contains", "json.decoder", "--kind", "module")
        self.assertEqual(0, code)
        self.assertEqual(["json.decoder"], [n["id"] for n in out["nodes"]])


if __name__ == "__main__":
    unittest.main()
