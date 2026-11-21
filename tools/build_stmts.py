"""Statement spans for every .py file at the pinned commit (so the selector needs no checkout)."""
import ast, gzip, json, os, sys

root, out = sys.argv[1], sys.argv[2]
COMPOUND = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.If, ast.For, ast.AsyncFor,
            ast.While, ast.With, ast.AsyncWith, ast.Try, ast.Match) + ((ast.TryStar,) if hasattr(ast, "TryStar") else ())
res = {}
for d in ("sqlglot", "tests"):
    for dp, _, fs in os.walk(os.path.join(root, d)):
        for f in fs:
            if not f.endswith(".py"):
                continue
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, root)
            src = open(p, encoding="utf-8").read()
            try:
                tree = ast.parse(src)
            except SyntaxError:
                continue
            stmts = []   # [start, end, header_end, kind, scope]  kind: s=simple c=compound d=def k=class x=docstring
            def walk(node, scope):
                for ch in ast.iter_child_nodes(node):
                    if isinstance(ch, ast.stmt):
                        start = min([ch.lineno] + [x.lineno for x in getattr(ch, "decorator_list", [])])
                        if isinstance(ch, COMPOUND):
                            body = getattr(ch, "body", None) or []
                            hend = body[0].lineno - 1 if body else ch.end_lineno
                            kind = "k" if isinstance(ch, ast.ClassDef) else ("d" if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)) else "c")
                            stmts.append([start, ch.end_lineno, max(start, hend), kind, scope])
                            walk(ch, scope + 1 if kind in "kd" else scope)
                        else:
                            kind = "x" if isinstance(ch, ast.Expr) and isinstance(ch.value, ast.Constant) and isinstance(ch.value.value, str) else "s"
                            stmts.append([start, ch.end_lineno, ch.end_lineno, kind, scope])
                    elif isinstance(ch, (ast.ExceptHandler, ast.match_case)) or not isinstance(ch, ast.expr):
                        walk(ch, scope)
            walk(tree, 0)
            import io, tokenize
            strings = []
            try:
                for tok in tokenize.generate_tokens(io.StringIO(src).readline):
                    if tok.type in (tokenize.STRING, getattr(tokenize, "FSTRING_START", -1)) and tok.end[0] > tok.start[0]:
                        strings.append([tok.start[0], tok.end[0]])
                    if tok.type == getattr(tokenize, "FSTRING_START", -1):
                        pass
            except (tokenize.TokenError, SyntaxError):
                pass
            # f-strings tokenize in pieces: fall back to ast for their spans
            for node in ast.walk(tree):
                if isinstance(node, ast.JoinedStr) and node.end_lineno > node.lineno:
                    strings.append([node.lineno, node.end_lineno])
            res[rel] = {"stmts": stmts, "nlines": src.count("\n") + 1, "strings": strings}
with gzip.open(out, "wt") as fh:
    json.dump(res, fh, separators=(",", ":"))
print(len(res), "files", file=sys.stderr)
