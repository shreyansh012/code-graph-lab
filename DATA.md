# Data

This repository holds no downloaded data. The demo reads three kinds of source text.

## 1. The standard library `json` package (real, public)

- What: the Python files of the `json` package that ship with your Python installation. The demo finds the folder through the running interpreter (`json.__file__`). It reads them at run time. No copy is stored in this repository.
- Upstream home of this package: https://github.com/python/cpython/tree/main/Lib/json
- Documentation: https://docs.python.org/3/library/json.html
- Licence: Python Software Foundation licence. See https://docs.python.org/3/license.html and the licence file that comes with your Python.
- Version: whatever interpreter runs the demo. My own runs used Python 3.15.2 and 3.11 on Windows. The graph can differ between Python versions because the library code changes.
- Not fetched from the network. The files come from the local installation, so I have not checked them against the upstream URL above.

## 2. `examples/minishop` (synthetic)

A tiny shop pricing package that I wrote for this demo. It has no real data. Item names such as "pen" and "book" are made up. It is here so the graph has a few `proven`, `inferred` and `unknown` edges that are easy to read.

## 3. `tests/fixtures/tinypkg` (synthetic)

A tiny package written for the golden tests. It is small on purpose, so every expected edge can be checked by reading about 40 lines. The expected output is in `tests/golden/`.

The tests also build small packages as text in memory (long chains, wide fan-outs, many search hits) to check that the caps hold. That text is synthetic too.
