#!/bin/sh
# Rebuild map.json.gz and stmts.json.gz from sqlglot at the pinned commit.
# Needs Python 3.13, the kit's requirements.lock, and coverage-free tracing via sys.monitoring.
set -e
HERE=$(cd "$(dirname "$0")/.." && pwd)
WORK=${WORK:-/tmp/br-maps}
rm -rf "$WORK" && mkdir -p "$WORK"
git clone -q https://github.com/tobymao/sqlglot.git "$WORK/sqlglot"
git -C "$WORK/sqlglot" checkout -q eb11aec4be8cb2122afe713a4816662c3f0fb2fa
pip install -q -r "$1"      # path to requirements.lock from the kit
cd "$WORK/sqlglot"
SKIP_INTEGRATION=0 TRACE_ROOT="$PWD" TRACE_OUT="$WORK/trace" PYTHONPATH="$PWD:$HERE/tools" \
  python -m pytest -q -p tracer_plugin -n 4 tests
python "$HERE/tools/build_map.py" "$WORK/trace" "$2" "$HERE/map.json.gz"   # $2: tests.json
python "$HERE/tools/build_stmts.py" "$WORK/sqlglot" "$HERE/stmts.json.gz"
