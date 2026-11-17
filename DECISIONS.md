# Decision log

Each entry has the decision, why, and the alternative that was rejected.

## 1. Read syntax only. Never run or import the code.

- Why: Importing a package runs its code. That can be slow, unsafe or impossible. The `ast` module only reads text.
- Rejected: Importing modules and using `inspect`. It would resolve more names, but it runs unknown code and needs the package to be installed.

## 2. Three trust labels: proven, inferred, unknown.

- Why: A reader needs to know which links to believe. Plain words are easier to use than a number.
- Rejected: A confidence score from 0 to 1. The numbers would look exact but nothing backs them.

## 3. Keep every candidate for an inferred call.

- Why: If a call matches three methods, dropping two would hide the real target some of the time. The reader can see the count in the `note`.
- Rejected: Picking the "best" match. It would turn a guess into something that looks like a fact.

## 4. A call that cannot be resolved becomes a leaf node that starts with `?`.

- Why: Every edge then has two real ends, so the walk code and the caps stay simple. The leaf also counts toward the node cap, so unknown calls cannot flood the output.
- Rejected: Leaving the target empty, or dropping unknown edges. Dropping them would make the graph look more complete than it is.

## 5. Calls into code outside the graph are `unknown`. Imports of it are `proven`.

- Why: An import line names its module exactly, so that edge is solid. A call into that module points at code the graph does not hold, so the graph cannot prove where it lands. The `note` says `external` or `builtin`.
- Rejected: Marking external calls `proven`. It would blur what the label means.

## 6. A name defined twice in one scope gives several ids and `inferred` edges.

- Why: Code such as a `try` and `except` fallback can define one name twice. The first keeps the plain id and later ones get `~2`, `~3`. A call to the name cannot be pinned to one of them.
- Rejected: Last definition wins. It is a common runtime result but not always true.

## 7. Follow re-exports through imports.

- Why: A package often imports a name in `__init__.py` so callers can import it from the package. Following that link keeps those calls `proven`. The walk stops after 8 hops to avoid loops.
- Rejected: Treating a re-exported name as unresolved. It would fill the graph with false unknowns.

## 8. Hard caps that the caller cannot raise, with a fixed set of stop reasons.

- Why: The caller is an AI agent. It can ask for huge limits by mistake. Output size must stay bounded whatever it asks. Values above the hard limit are lowered and reported in `limits.clamped`.
- Rejected: Returning an error when a cap is too large. It wastes a turn. Having no cap at all was never an option.

## 9. The node cap stops the walk at once.

- Why: It is simple to test: the result never has more than `max_nodes` nodes, and `node_cap` means something was left out.
- Rejected: Finishing the current level. The output would be larger than the cap.

## 10. `depth_cap` is reported only if the cut left new nodes out.

- Why: If the nodes at the depth limit lead only to nodes already seen, no node is missing. Saying `complete` is then true. `complete` is about nodes. At the limit the walk still lists edges that join two nodes it already returned, so the edge list is the same for any depth that returns the same nodes. It cuts only edges to new nodes.
- Rejected: Always reporting `depth_cap` when the limit is reached. It would be a false alarm.

## 11. Caller mistakes raise an error. They are not stop reasons.

- Why: An unknown name, a bad regex or a non-number is not the same as "I ran out of room". The CLI prints `{"error": ...}` and exits with code 2.
- Rejected: Adding extra stop reasons such as `not_found`. The five stop reasons stay about caps.

## 12. Node ids are dotted names. A short unique tail is accepted.

- Why: Dotted names are easy to read and easy to type. A tail such as `app.main` saves typing when it is unique. If it is not unique, the error lists the choices.
- Rejected: Numeric ids. They are stable but unreadable.

## 13. Sort everything before output.

- Why: The same source must give the same graph, whatever order the files are read in. Files, edges and nodes are sorted by name. A test shuffles the file order and compares the output.
- Rejected: Relying on the order of the file system. It differs between Windows and Linux.

## 14. `path_trust` is the weakest label on the path the walk found first.

- Why: One weak link makes the whole path weak. The walk is breadth first, so it reports the shortest path. A longer path with stronger labels may exist.
- Rejected: Searching for the strongest path. It costs more and the demo does not need it.

## 15. Parameters hide names, but other assignments do not.

- Why: A call to a parameter, such as `cls(...)`, cannot be a module function, so it is `unknown`. Tracking every local assignment would need a real scope analysis. The cost: a call to a local variable, loop variable or `with` target that shares a name with a module-level def or import is matched to that def or import. It can be labelled `proven` when the real target is another object. The README lists this as a limit.
- Rejected: Full data-flow analysis. It is out of scope for a small demo.

## 16. Standard library only.

- Why: The demo must run on Windows and Linux with no install step. `ast`, `argparse`, `unittest` and `json` are enough. There is no `requirements.txt` because there is nothing to list.
- Rejected: Using a graph library or a parser library. Neither is needed at this size.

## 17. Rebuild the graph on every command.

- Why: It takes a fraction of a second for the sample packages. A cache would add stale-data bugs.
- Rejected: Saving the graph to disk and reloading it.

## 18. Search uses regular expressions, with a length limit on the pattern.

- Why: Regular expressions are what an agent expects. The limit on the pattern length and on the number of hits keeps the work small.
- Rejected: Plain text search only. The regex form is more useful. A full guard against slow patterns is not built, and it is listed as a limit: a short pattern such as `(a+)+$` can run for a very long time on one line. The `--literal` option escapes the text, so plain text can be searched with no such risk.

## 19. Golden tests are paired with label tests that state the expected result.

- Why: A stored output file only proves the code did not change. The label tests state what the fixture should give, written from reading the fixture, so a wrong golden file would be caught.
- Rejected: Golden files alone.

## 20. Add `--literal` to search. Do not try to time-limit regular expressions.

- Why: Python's `re` cannot be stopped from outside once it starts. A time limit would need a second process or a different engine. A literal mode removes the risk for plain text, and the README says that pattern mode has no time limit.
- Rejected: Rejecting nested quantifiers with a check on the pattern. The check would miss other slow patterns and would give a false feeling of safety.

## 21. Walk the syntax tree with a stack, not with recursion.

- Why: A long expression, such as 2000 terms added together, makes a recursive walk run out of call stack, and one such file would stop a build over a whole package. The stack version has no depth limit of its own. If the parser itself gives up on a file, the file is listed under `skipped`.
- Rejected: Catching the error around a recursive walk. It would leave half of a module in the graph.

## 22. Split source lines the way the `ast` module counts them.

- Why: `str.splitlines()` also splits on form feed and a few other characters. The `ast` module does not. The two then disagree on line numbers, and `get_source` and `search` would serve the wrong lines with no error.
- Rejected: Keeping `splitlines()`. It is shorter but gives wrong output for real files, such as some standard library modules.

## 23. A relative root is turned into a full path. A root that is not a valid package name is an error.

- Why: `--root .` has no folder name of its own. Without this step the module names came out as empty or as `...pkg`. Failing with a clear message is better than building a graph with names that do not match the documented ids.
- Rejected: Guessing a name for the folder. A guess would hide the problem.

## 24. Read files as `utf-8-sig`.

- Why: Windows editors often add a byte order mark. With plain UTF-8 it stays in the text and the parser fails, so the whole module would be skipped.
- Rejected: Honouring coding comments for other encodings. It is more code and the demo targets UTF-8 sources. It is listed as a limit in the README.
