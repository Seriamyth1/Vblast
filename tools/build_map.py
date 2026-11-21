"""Turn per-test traces into map.json.gz: file -> line -> tests, file -> openers, import-only lines."""
import glob, gzip, json, sys
from collections import defaultdict

trace_dir, tests_json, out = sys.argv[1], sys.argv[2], sys.argv[3]
tests = json.load(open(tests_json))["tests"]
num = {t["id"]: t["number"] for t in tests}
lines = defaultdict(lambda: defaultdict(int))   # file -> line -> bitset
nontest = defaultdict(set)                         # lines run outside any test (import/collection)
opens = defaultdict(int)
unknown = 0
for fn in glob.glob(trace_dir + "/*.jsonl"):
    for row in open(fn):
        r = json.loads(row)
        name = r["test"]
        if name.startswith("SETUP::"):
            nid = name[7:]
            scope = nid.rsplit("::", 1)[0] + "::"
            bit = 0
            for tid, k in num.items():
                if tid.startswith(scope):
                    bit |= 1 << k
            if nid in num:
                bit |= 1 << num[nid]
            for f, ls in r["lines"].items():
                d = lines[f]
                for l in ls:
                    d[l] |= bit
            for f in r["opens"]:
                opens[f] |= bit
            continue
        n = num.get(name)
        if n is None:
            if r["test"].startswith("<"):
                for f, ls in r["lines"].items():
                    nontest[f].update(ls)
            else:
                unknown += 1
            continue
        bit = 1 << n
        for f, ls in r["lines"].items():
            d = lines[f]
            for l in ls:
                d[l] |= bit
        for f in r["opens"]:
            opens[f] |= bit
print("unknown test ids:", unknown, file=sys.stderr)
m = {"lines": {f: {str(l): format(b, "x") for l, b in d.items()} for f, d in lines.items()},
     "opens": {f: format(b, "x") for f, b in opens.items()},
     "nontest": {f: sorted(v) for f, v in nontest.items()}}
with gzip.open(out, "wt") as fh:
    json.dump(m, fh, separators=(",", ":"))
