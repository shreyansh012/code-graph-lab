"""Shared test helpers. Standard library only."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURE = ROOT / "tests" / "fixtures" / "tinypkg"
DEMO = ROOT / "examples" / "minishop"
GOLDEN = ROOT / "tests" / "golden"


def check_golden(case, name, actual):
    """Compare actual with a stored JSON file.

    To rewrite the stored files after an intended change, run the tests with
    the environment variable UPDATE_GOLDEN=1 and then read the diff.
    """
    path = GOLDEN / name
    if os.environ.get("UPDATE_GOLDEN") == "1":
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(actual, fh, indent=2)
            fh.write("\n")
    with open(path, "r", encoding="utf-8") as fh:
        expected = json.load(fh)
    case.assertEqual(expected, json.loads(json.dumps(actual)))


def synthetic_source(module, text, path=None):
    from code_graph_lab import SourceFile

    return SourceFile(module, path or module + ".py", text, False)
