"""Blast Radius selector: pick the tests a patch can break from a per-test line/open map
built at the pinned sqlglot commit, then split them across workers to minimise cost."""
import gzip
import json
import os
import re
import sys

DATA = os.environ.get("DATA_DIR", "/data")
HERE = os.path.dirname(os.path.abspath(__file__))
WORKER_MS = 2000


def log(*a):
    print(*a, file=sys.stderr)


def load():
    m = json.load(gzip.open(os.path.join(HERE, "map.json.gz"), "rt"))
    st = json.load(gzip.open(os.path.join(HERE, "stmts.json.gz"), "rt"))
    lines = {f: {int(l): int(b, 16) for l, b in d.items()} for f, d in m["lines"].items()}
    opens = {f: int(b, 16) for f, b in m["opens"].items()}
    nontest = {f: set(v) for f, v in m["nontest"].items()}
    return lines, opens, nontest, st


HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def parse_patch(text):
    """-> {path: [(old_line, kind, text)]}; kind '-' removed line, '+' inserted before old_line."""
    files = {}
    cur = None
    old = 0
    for raw in text.split("\n"):
        if raw.startswith("diff --git "):
            parts = raw.split(" ")
            cur = parts[2][2:] if parts[2].startswith("a/") else parts[2]
            files.setdefault(cur, [])
            continue
        if cur is None:
            continue
        if raw.startswith("--- ") or raw.startswith("+++ "):
            if raw.startswith("+++ ") and raw[4:].strip() != "/dev/null":
                newp = raw[4:].strip()
                newp = newp[2:] if newp.startswith("b/") else newp
                if newp != cur:
                    files.setdefault(newp, []).append((0, "new", ""))
            continue
        m = HUNK.match(raw)
        if m:
            old = int(m.group(1))
            if m.group(2) == "0":
                old += 1   # pure insertion after line N is reported as -N,0
            continue
        if raw.startswith("-"):
            files[cur].append((old, "-", raw[1:]))
            old += 1
        elif raw.startswith("+"):
            files[cur].append((old, "+", raw[1:]))
        elif raw.startswith(" "):
            old += 1
    return files


class Selector:
    def __init__(self, tests):
        self.lines, self.opens, self.nontest, self.st = load()
        self.tests = tests
        self.all = 0
        self.by_file = {}
        for t in tests:
            self.all |= 1 << t["number"]
            self.by_file[t["file"]] = self.by_file.get(t["file"], 0) | (1 << t["number"])
        self.why = []

    def stmt_at(self, f, line):
        best = None
        for s in self.st.get(f, {}).get("stmts", []):
            if s[0] <= line <= s[1]:
                if best is None or (s[1] - s[0]) <= (best[1] - best[0]):
                    best = s
        return best

    def enclosing(self, f, line, kinds):
        best = None
        for s in self.st.get(f, {}).get("stmts", []):
            if s[3] in kinds and s[0] <= line <= s[1]:
                if best is None or (s[1] - s[0]) <= (best[1] - best[0]):
                    best = s
        return best

    def span_tests(self, f, a, b):
        d = self.lines.get(f, {})
        r = 0
        for l in range(a, b + 1):
            r |= d.get(l, 0)
        return r

    def sibling_tests(self, f):
        """Import-time data of one dialect (dialects/x.py, parsers/x.py, ...) reaches every
        test that runs any of that dialect's modules."""
        parts = f.split("/")
        if len(parts) != 3 or parts[0] != "sqlglot" or parts[2] in ("__init__.py", "dialect.py"):
            return 0
        base = parts[2]
        r = 0
        for g, d in self.lines.items():
            if g.startswith("sqlglot/") and g.endswith("/" + base) and g.count("/") == 2:
                for b in d.values():
                    r |= b
        return r

    def py_line(self, f, line, is_import_stmt):
        """Tests that can observe a change at `line` of python file f."""
        s = self.stmt_at(f, line)
        if s is None:
            return 0
        start, end, hend, kind, scope = s
        if kind == "x":
            return 0  # docstring
        a, b = (start, end) if kind in "sx" else (start, hend)
        direct = self.span_tests(f, a, b)
        # import-time code: anything not inside a function body (def headers included)
        enc_def = self.enclosing(f, line, "d")
        in_body = enc_def is not None and not (enc_def[0] <= line <= enc_def[2])
        ran_at_import = not in_body
        if not ran_at_import:
            return direct  # 0 when no test ever runs it
        return direct | self.import_time(f, line, s, is_import_stmt)

    def import_time(self, f, line, s, is_import_stmt):
        kind = s[3]
        if is_import_stmt:
            self.why.append(f"import-stmt {f}:{line}")
            return self.all
        # import-time code (class attributes, def headers, module constants)
        enc = self.enclosing(f, line, "dk") if kind not in "dk" else s
        while enc is not None:
            r = self.span_tests(f, enc[0], enc[1])
            if r:
                self.why.append(f"scope {f}:{line} -> {enc[3]}{enc[0]}-{enc[1]}")
                return r | self.sibling_tests(f)
            enc = self.enclosing(f, enc[0] - 1, "dk") if enc[0] > 1 else None
            if enc is not None and enc[0] >= s[0]:
                break
        r = self.span_tests(f, 1, self.st.get(f, {}).get("nlines", 100000))
        if r:
            self.why.append(f"file {f}:{line}")
            return r | self.sibling_tests(f)
        self.why.append(f"all {f}:{line}")
        return self.all

    def select(self, patch_text):
        self.why = []
        need = 0
        for f, changes in parse_patch(patch_text).items():
            if f.endswith(".py"):
                if f not in self.st:
                    if f.startswith("tests/") and f in self.by_file:
                        need |= self.by_file[f]
                    elif any(c[1] != "new" or True for c in changes):
                        self.why.append(f"unknown py {f}")
                        need |= self.all if f.startswith("sqlglot/") else self.by_file.get(f, 0)
                    continue
                spans = self.st[f].get("strings", [])

                def in_string(l, spans=spans):
                    return any(a < l < b or (a <= l <= b and a != b) for a, b in spans)

                for old, kind, text in changes:
                    if kind == "new":
                        continue
                    s = text.strip()
                    if not s or s.startswith("#"):
                        # a real comment or blank line changes nothing; inside a string it is data
                        if kind == "-" and not in_string(old):
                            continue
                        if kind == "+" and not (in_string(old - 1) and in_string(old)):
                            continue
                    is_imp = s.startswith("import ") or s.startswith("from ")
                    if kind == "-":
                        need |= self.py_line(f, old, is_imp)
                    else:
                        # inserted before `old`: the statements on both sides of the gap
                        need |= self.py_line(f, old - 1, is_imp) | self.py_line(f, old, is_imp)
                if f.startswith("tests/") and f in self.by_file:
                    # a test file's own import-time code feeds every test in it
                    pass
            else:
                r = self.opens.get(f, 0)
                if not r and changes:
                    base = os.path.basename(f)
                    self.why.append(f"no opener {f}")
                    r = self.all if f.startswith("sqlglot/") else 0
                    if not r:
                        for tf, bits in self.by_file.items():
                            if base.split(".")[0] in tf:
                                r |= bits
                need |= r
        return need

    def split(self, need):
        ts = [t for t in self.tests if need >> t["number"] & 1]
        if not ts:
            return []
        ts.sort(key=lambda t: -round(t["seconds"] * 1000))
        best = None
        for k in range(1, 9):
            loads = [0] * k
            ws = [[] for _ in range(k)]
            for t in ts:
                i = loads.index(min(loads))
                ws[i].append(t["number"])
                loads[i] += round(t["seconds"] * 1000)
            ws = [w for w in ws if w]
            cost = max(loads) + WORKER_MS * len(ws)
            if best is None or cost < best[0]:
                best = (cost, ws)
        return best[1]


def main():
    tests = json.load(open(os.path.join(DATA, "tests.json")))["tests"]
    sel = Selector(tests)
    cdir = os.path.join(DATA, "commits")
    for fn in sorted(os.listdir(cdir)):
        if not fn.endswith(".patch"):
            continue
        cid = fn[:-6]
        try:
            with open(os.path.join(cdir, fn), encoding="utf-8", errors="replace") as fh:
                need = sel.select(fh.read())
        except Exception as e:  # never risk a crash: run everything
            log(f"{cid}: error {e!r}, running all")
            need = sel.all
        ws = sel.split(need)
        print(json.dumps({"commit": cid, "workers": ws}))
        log(cid, sum(len(w) for w in ws), "tests", "; ".join(sel.why[:4]))


if __name__ == "__main__":
    main()
