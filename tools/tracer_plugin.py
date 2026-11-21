"""pytest plugin: per test, record executed sqlglot lines and opened files (pinned commit map)."""
import json
import os
import sys

ROOT = os.path.realpath(os.environ.get("TRACE_ROOT", os.getcwd())) + os.sep
OUT = os.environ.get("TRACE_OUT", "/tmp/trace")
TOOL = 4
mon = sys.monitoring
_hits = set()
_opens = set()
_cur = ["<import>"]


def _line(code, line):
    fn = code.co_filename
    if fn and fn.startswith(ROOT):
        _hits.add((fn[len(ROOT):], line))
    return mon.DISABLE


def _audit(ev, args):
    if ev == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
        try:
            p = os.path.realpath(os.fsdecode(args[0]))
        except Exception:
            return
        if p.startswith(ROOT):
            _opens.add(p[len(ROOT):])


# Tests farm work out to spawned process pools; run it in-process so it is traced
import concurrent.futures as _cf


class _SyncExecutor(_cf.Executor):
    def __init__(self, max_workers=None, mp_context=None, initializer=None, initargs=(), **kw):
        if initializer is not None:
            initializer(*initargs)

    def submit(self, fn, /, *args, **kwargs):
        import pickle
        f = _cf.Future()
        try:
            # spawn pools pickle arguments and results; keep that code path traced
            fn, args, kwargs = pickle.loads(pickle.dumps((fn, args, kwargs)))
            f.set_result(pickle.loads(pickle.dumps(fn(*args, **kwargs))))
        except BaseException as e:
            f.set_exception(e)
        return f


_cf.ProcessPoolExecutor = _SyncExecutor

mon.use_tool_id(TOOL, "tracer")
mon.register_callback(TOOL, mon.events.LINE, _line)
mon.set_events(TOOL, mon.events.LINE)
sys.addaudithook(_audit)
_fh = None


def _flush(name):
    global _fh
    if _fh is None:
        os.makedirs(OUT, exist_ok=True)
        _fh = open(os.path.join(OUT, f"{os.environ.get('PYTEST_XDIST_WORKER', 'main')}.jsonl"), "w")
    files = {}
    for f, l in _hits:
        files.setdefault(f, []).append(l)
    _fh.write(json.dumps({"test": name, "lines": files, "opens": sorted(_opens)}) + "\n")
    _fh.flush()
    _hits.clear()
    _opens.clear()
    mon.restart_events()


import pytest


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_setup(item):
    yield
    # setup can run class/module-scoped setup (setUpClass, fixtures) once for many tests
    _flush("SETUP::" + item.nodeid)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    _flush("<between>")
    yield
    _flush(item.nodeid)


def pytest_sessionfinish(session):
    _flush("<end>")
