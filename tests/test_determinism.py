import json
import random
import unittest

from helpers import DEMO, FIXTURE  # noqa: E402

from code_graph_lab import build_graph, build_graph_from_sources, collect_sources, trace_flow


def dump(graph):
    return json.dumps(graph.to_dict(), sort_keys=False)


class DeterminismTests(unittest.TestCase):
    def test_file_order_does_not_change_the_graph(self):
        files = collect_sources([FIXTURE, DEMO])
        base = dump(build_graph_from_sources(files))
        self.assertGreater(len(files), 4)
        self.assertEqual(base, dump(build_graph_from_sources(list(reversed(files)))))
        for seed in range(5):
            shuffled = list(files)
            random.Random(seed).shuffle(shuffled)
            self.assertEqual(base, dump(build_graph_from_sources(shuffled)))

    def test_root_order_does_not_change_the_graph(self):
        self.assertEqual(dump(build_graph([FIXTURE, DEMO])), dump(build_graph([DEMO, FIXTURE])))

    def test_stdlib_json_package_is_stable(self):
        import json as stdlib_json
        from pathlib import Path

        root = Path(stdlib_json.__file__).resolve().parent
        files = collect_sources([root])
        self.assertGreater(len(files), 3)
        self.assertEqual(dump(build_graph_from_sources(files)), dump(build_graph_from_sources(files[::-1])))

    def test_query_output_is_stable(self):
        files = collect_sources([FIXTURE])
        a = build_graph_from_sources(files)
        b = build_graph_from_sources(list(reversed(files)))
        self.assertEqual(
            json.dumps(trace_flow(a, "tinypkg.app.main", 5, 100)),
            json.dumps(trace_flow(b, "tinypkg.app.main", 5, 100)),
        )

    def test_repeat_builds_match(self):
        self.assertEqual(dump(build_graph([FIXTURE])), dump(build_graph([FIXTURE])))


if __name__ == "__main__":
    unittest.main()
