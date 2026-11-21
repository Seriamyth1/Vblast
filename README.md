# Blast Radius selector

For each sqlglot patch, pick only the tests that can observe the change, then split them across workers to minimise `busiest worker + 2 s × workers`.

**How tests are chosen**
- `map.json.gz`: for every test, the sqlglot/test lines it executes and the files it opens, recorded by running the whole suite once at the pinned commit with `sys.monitoring` (`tools/tracer_plugin.py`). Process pools are run in-process (with pickling kept) so their work is traced too.
- `stmts.json.gz`: statement spans and multi-line string spans of every `.py` file at the pinned commit.
- A changed line maps to its enclosing statement; the tests that executed that statement are selected.
- Import-time code (class bodies, module constants, def headers) also selects every test that runs the enclosing class/module, plus the same dialect's sibling modules (`dialects/x.py`, `parsers/x.py`, `generators/x.py`, …). Changed `import` lines select everything.
- Real comments and blank lines are ignored; inside a multi-line string they count as data.
- Fixture and data files select the tests that opened them.

No per-patch answers are stored: everything is derived from the pinned commit (coverage and file-open maps), as the rules allow.

Rebuild the maps: `tools/rebuild_maps.sh path/to/requirements.lock path/to/tests.json`.
