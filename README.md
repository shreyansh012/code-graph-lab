# code-graph-lab

## What this demo shows

It reads Python source with the `ast` module and builds a graph of modules, classes and functions, joined by defines, imports and calls edges. Every edge carries a trust label (proven, inferred or unknown) so a reader can see which links are solid and which are guesses. Four query tools with hard caps (`trace_flow`, `find_reach`, `get_source`, `search_text`) keep their output small and always say why they stopped.

AI-assisted, with tests and review gates.

## Trust labels

| Label | Meaning | Example |
|---|---|---|
| `proven` | The target was found exactly. | A call to a function defined in the same module. A call through `import` or `from ... import`. |
| `inferred` | A name match that could be wrong. Every candidate is kept, one edge each. | `obj.step()` matches every method called `step`. |
| `unknown` | The target could not be found inside the graph. | `len(x)`, `os.getcwd()`, or a call on a plain variable. The edge has a `note` that says why. |

Calls into libraries outside the graph are `unknown`. Their import line is still `proven`, because the source names the module exactly.

## How to run

You need Python 3.11 or newer. There is nothing to install.

```
python -m unittest discover -s tests -v
python -m code_graph_lab summary
python -m code_graph_lab list --contains decoder
python -m code_graph_lab trace minishop.report.render --max-depth 3
python -m code_graph_lab reach minishop.models.Item.cost
python -m code_graph_lab source minishop.pricing.total_price --max-lines 20
python -m code_graph_lab search "def raw_decode" --max-hits 5
python -m code_graph_lab search "raw_decode(" --literal
python -m code_graph_lab dump --out graph.json
```

By default the graph covers two things: the standard library `json` package (found through the running interpreter) and the small `examples/minishop` package in this repository. To read other packages, pass folders that are Python packages. The folder name becomes the package name, so it must be a valid Python name. A relative path such as `.` is fine; it is turned into the full path first:

```
python -m code_graph_lab summary --root path/to/package --root path/to/another
```

Names can be full ids (`json.decoder.JSONDecoder.decode`) or a short tail that is unique (`minishop.report.render`). An unknown or ambiguous name prints an `error` and exits with code 2.

### The caps

| Tool | Option | Default | Hard limit | Stop reasons |
|---|---|---|---|---|
| `trace_flow` | `--max-depth`, `--max-nodes` | 3, 50 | 12, 500 | `complete`, `node_cap`, `depth_cap` |
| `find_reach` | `--max-nodes` | 50 | 500 | `complete`, `node_cap` |
| `get_source` | `--max-lines` | 60 | 200 | `complete`, `line_cap` |
| `search_text` | `--max-hits` | 20 | 100 | `complete`, `hit_cap` |

Asking for more than the hard limit is not an error. The tool uses the hard limit and lists the option in `limits.clamped`. Every query result (`trace`, `reach`, `source`, `search`, `list`, `summary`) has `counts` and `stop_reason`. `dump` writes the whole graph with no caps.

The caps bound how much is returned. They do not bound run time. See the limits below for `search`.

### Sample output

`python -m code_graph_lab trace minishop.report.render --max-depth 3` finds 14 nodes and 24 edges: 3 proven, 12 inferred, 9 unknown, and it stops with `complete`. Part of the edge list:

```
minishop.report.render        -> minishop.pricing.total_price  proven
minishop.pricing.total_price  -> minishop.pricing.with_tax     proven
minishop.pricing.total_price  -> minishop.models.Item.cost     inferred (3 methods are called cost)
minishop.pricing.total_price  -> ?math.floor                   unknown  (external)
```

Nodes that start with `?` are calls that could not be resolved. Nodes that start with `ext:` are modules outside the graph.

## What it does NOT prove

- It does not run any code. Names that only exist at run time (set with `setattr`, built from strings, passed in as arguments) are `unknown` or wrongly `inferred`.
- `inferred` is a guess by method name. It has no type information. It can point at the wrong class and it can miss the right one.
- Inheritance is not followed. A call to a method that a parent class defines is matched by name, so it is `inferred`.
- Assigned names are not tracked (assignments, loop variables, `with` and `except` targets, lambda arguments). A call to such a name is matched against defs and imports of the same name, so it can be labelled `proven` when the real target is a different object. Only function and method parameters hide names.
- `search_text` (the `search` command) uses Python `re`. The pattern is limited to 200 characters but nothing stops a pattern that backtracks for a very long time, so a bad pattern can hang the command. Use `--literal` for plain text.
- Files are read as UTF-8 (a leading byte order mark is dropped). A coding comment for another encoding is ignored, and bytes that do not decode are replaced. A file that cannot be parsed is listed under `skipped` and has no calls or defines.
- Imports inside a function are treated as if the whole module had imported the name.
- When `trace` reaches the depth limit it still lists edges between nodes it already returned. It cuts only edges that lead to new nodes, and then says `depth_cap`. `complete` means no node was left out.
- `proven` means the syntax points at one definition. It does not mean the call runs, or that nothing rebinds the name later.
- It has been run on Windows with Python 3.15 and 3.11. The CI file also lists Linux and Python 3.12 and 3.13, which I have not run myself.
- The only real code it was tried on is the standard library `json` package and the small demo package. Nothing here says it works well on large code bases.
- The graph is rebuilt on every command. There is no cache.

## Files

- `code_graph_lab/builder.py` reads source and makes the graph.
- `code_graph_lab/tools.py` has the four capped tools, plus `list_nodes` and `summary`.
- `code_graph_lab/cli.py` is the command line.
- `examples/minishop/` is the demo package.
- `tests/` has golden tests on a tiny fixture package, plus order, cap and edge-case tests.
- `DECISIONS.md` explains the choices. `DATA.md` says where the data comes from.

If the golden files need to change after an intended edit, run the tests once with `UPDATE_GOLDEN=1` and read the diff before you keep it.

## Licence

MIT. See `LICENSE`.
