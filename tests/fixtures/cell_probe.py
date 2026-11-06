"""The child processes behind tests/test_cells.py. A read that holds the lock freezes the process it runs in, so
each mode runs apart from pytest, and its parent kills it at a bound whatever happens here. Every mode ends with one
line of JSON on stdout, except `thread`, which never ends by itself and streams what it saw until it is killed.

    python tests/fixtures/cell_probe.py thread              a held lock on a thread, as library use still runs it
    python tests/fixtures/cell_probe.py cells               a held lock in a cell, read over real HTTP
    python tests/fixtures/cell_probe.py flood               as many held locks as there are cells
    python tests/fixtures/cell_probe.py orphan              a held lock in a cell whose forkserver is killed (Linux)
    python tests/fixtures/cell_probe.py freeze              a held lock on a thread, with the watchdog on
    python tests/fixtures/cell_probe.py stuck               a held lock in a cell, with the watchdog on
    python tests/fixtures/cell_probe.py wall                every public route, then what entered the front
    python tests/fixtures/cell_probe.py library             what importing and verifying starts
    python tests/fixtures/cell_probe.py moat cells|process  the whole moat, one digest per case
    python tests/fixtures/cell_probe.py memory cells|thread what each process holds, idle and after reads
    python tests/fixtures/cell_probe.py growth              what one cell gains over the whole moat

Nothing here sends anything to any service but the one it starts on 127.0.0.1.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.dirname(os.path.abspath(__file__))
for _path in (HERE, os.path.join(ROOT, "src"), os.path.join(ROOT, "tools")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

WINDOW_S = float(os.environ.get("CELL_PROBE_WINDOW_S", "1.0"))
HOLD = {"mode": "hold", "params": {}}
QUICK = {"mode": "quick", "params": {}}


def _stand_ins():
    import lock_holder
    from concordance import derivation as D
    D._VERIFY_TIMEOUT_S = WINDOW_S
    D._MATH_MODES["hold"] = lock_holder.hold
    D._MATH_MODES["quick"] = lock_holder.quick
    return D


def _say(obj) -> None:
    print(json.dumps(obj, default=str), flush=True)


def thread_mode() -> None:
    D = _stand_ins()

    def beat():
        while True:
            print("beat", time.monotonic(), flush=True)
            time.sleep(0.02)

    threading.Thread(target=beat, daemon=True).start()
    time.sleep(0.3)
    print("read", time.monotonic(), flush=True)
    out = D.verify_step("mathematics", HOLD)
    print("shed", time.monotonic(), json.dumps(out), flush=True)


def _post(port: int, body: dict) -> dict:
    req = urllib.request.Request(f"http://127.0.0.1:{port}/verify?seal=0", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def _health(port: int):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=60) as r:
        return r.status, json.loads(r.read())


def cells_mode() -> None:
    D = _stand_ins()
    from concordance import cells, http_api
    pool = cells.enable(1, preload=("lock_holder",))
    srv = http_api.serve("127.0.0.1", 0, background=True)
    port = srv.server_address[1]
    first = _post(port, QUICK)                                  # the cell is up before the window is watched
    beats = []

    def beat():
        while True:
            beats.append(time.monotonic())
            time.sleep(0.02)

    threading.Thread(target=beat, daemon=True).start()
    time.sleep(0.2)
    got = {}

    def read():
        began = time.monotonic()
        got["body"] = _post(port, HOLD)
        got["began"], got["ended"] = began, time.monotonic()

    reader = threading.Thread(target=read)
    reader.start()
    health = []
    while reader.is_alive():
        began = time.monotonic()
        status, body = _health(port)
        health.append({"at": began, "status": status, "ok": body.get("ok"), "secs": time.monotonic() - began})
        time.sleep(0.05)
    reader.join()
    after = _post(port, QUICK)
    during = [b for b in beats if got["began"] <= b <= got["ended"]]
    gaps = [b - a for a, b in zip(during, during[1:])]
    health = [h for h in health if got["began"] <= h["at"] <= got["ended"]]
    held = got["body"]
    _say({"first": first["verdict"], "secs": got["ended"] - got["began"], "beats": len(during),
          "widest_gap": max(gaps or [0]), "health": health, "verdict": held["verdict"],
          "status": held["trail"][0]["status"], "detail": held["trail"][0]["detail"], "next": after["verdict"],
          "pool": pool.status(), "window": WINDOW_S})


def flood_mode() -> None:
    D = _stand_ins()
    from concordance import cells
    size = 2
    pool = cells.enable(size, preload=("lock_holder",))
    got = []

    def read():
        began = time.monotonic()
        out = D.verify_step("mathematics", HOLD)
        got.append({"out": out, "secs": time.monotonic() - began})

    readers = [threading.Thread(target=read) for _ in range(size)]
    for r in readers:
        r.start()
    while pool.status()["taken"] < size:
        time.sleep(0.005)
    began = time.monotonic()
    busy = D.verify_step("mathematics", QUICK)
    busy_secs = time.monotonic() - began
    for r in readers:
        r.join()
    during = pool.status()
    after = D.verify_step("mathematics", QUICK)
    _say({"stuck": got, "busy": busy, "busy_secs": busy_secs, "during": during, "after": after,
          "status": pool.status(), "window": WINDOW_S})


def orphan_mode() -> None:
    os.environ["CELL_PROBE_WINDOW_S"] = "30"
    global WINDOW_S
    WINDOW_S = 30.0
    D = _stand_ins()
    import signal
    from multiprocessing import forkserver
    from concordance import cells
    pool = cells.enable(1, preload=("lock_holder",))
    D.verify_step("mathematics", QUICK)
    cell = pool.status()["pids"][0]
    got = {}

    def read():
        began = time.monotonic()
        got["out"] = D.verify_step("mathematics", HOLD)
        got["secs"] = time.monotonic() - began

    reader = threading.Thread(target=read)
    reader.start()
    while pool.status()["taken"] < 1:
        time.sleep(0.005)
    time.sleep(0.2)
    os.kill(forkserver._forkserver._forkserver_pid, signal.SIGKILL)
    reader.join()
    end = time.monotonic() + 5
    while time.monotonic() < end and _running(cell):
        time.sleep(0.02)
    _say({**got, "gone": not _running(cell), "after": D.verify_step("mathematics", QUICK), "window": WINDOW_S})


def _running(pid: int) -> bool:
    """Is it running? A zombie is not: it holds no memory and is only waiting for init to read it."""
    try:
        with open(f"/proc/{pid}/stat", encoding="ascii") as fh:
            return fh.read().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return False


def _beating(cells_on: bool) -> None:
    """A real server and a real watchdog beating fast, with the notify printed instead of sent, then a held lock."""
    os.environ.update(NOTIFY_SOCKET="/run/not/used", WATCHDOG_USEC="200000")
    D = _stand_ins()
    from concordance import cells, http_api

    def told(message):
        print("notify", time.monotonic(), flush=True)
        return True

    http_api._notify = told
    if cells_on:
        cells.enable(1, preload=("lock_holder",))
        D.verify_step("mathematics", QUICK)
    else:
        http_api.use_cells = lambda: None               # as library use runs a read: on a thread
    http_api.serve("127.0.0.1", 0, background=True)
    time.sleep(0.5)
    print("read", time.monotonic(), flush=True)
    D.verify_step("mathematics", HOLD)
    time.sleep(60)                                      # the parent ends this


# ── the wall ─────────────────────────────────────────────────────────────────────────────────────────
def _golden(domain: str):
    with open(os.path.join(ROOT, "data", "domain_goldens.json"), encoding="utf-8") as fh:
        g = json.load(fh)[domain]
    return {"id": "a", "domain": domain, "spec": {g["packet_key"]: g["true"]}}


EQUALITY = {"mode": "equality", "params": {"expr_a": "(a+b)**2", "expr_b": "a**2+2*a*b+b**2", "variables": {}}}
DRAFTS = [{"writer": "a", "claims": [{"id": "pay", "value": 100.0}]}, {"writer": "b", "claims": [{"id": "pay", "value": 120.0}]}]
TOOL_ARGS = {
    "verify": {"mode": "equality", "params": EQUALITY["params"], "seal": False},
    "audit": {"text": "2 + 2 = 4", "seal": False},
    "discern": {"text": "The tank holds 2 + 2 = 4 litres."},
    "scribe": {"drafts": DRAFTS},
    "find_verifier": {"query": "compound interest"},
    "seal_fetch": {"hash": "0" * 64},
    "capabilities": {},
    "ledger_verify": {},
}


def wall_mode() -> None:
    os.environ["CONCORDANCE_MEMO"] = "1"                        # the memo is on in production, so it is on here
    from concordance import cells, http_api, tool_registry
    assert cells.active() is None
    http_api.serve("127.0.0.1", 0, background=True)             # serve() is what turns cells on
    pool = cells.active()
    seen = []

    def go(method, path, query=None, body=None, raw=b""):
        status, _headers, out = http_api.route(method, path, query or {}, body or {}, {}, raw)
        seen.append({"route": f"{method} {path}", "status": status, "sympy": "sympy" in sys.modules,
                     "numpy": "numpy" in sys.modules})
        return status, out

    def rpc(payload):
        return go("POST", "/mcp", raw=json.dumps(payload).encode())

    verdicts = {}
    _s, out = go("POST", "/verify", {"seal": ["1"]}, EQUALITY)
    sealed = json.loads(out)
    verdicts["equality"] = sealed["verdict"]
    h = sealed["seal"]["content_hash"]
    verdicts["steps"] = {}
    for domain in ("physics", "statistics", "formal_logic", "computer_science", "polynomial"):
        _s, out = go("POST", "/verify", {"seal": ["0"]}, {"steps": [_golden(domain)]})
        verdicts["steps"][domain] = json.loads(out)["verdict"]
    _s, out = go("POST", "/verify", {"seal": ["0"]}, {"claim": "2 + 2 = 4"})
    verdicts["claim"] = json.loads(out)["verdict"]
    doc = {"title": "Two steps", "steps": [{"id": "s1", "domain": "mathematics", "spec": EQUALITY}]}
    _s, out = go("POST", "/verify", {"seal": ["1"]}, {"document": doc})
    root = json.loads(out)["root"]
    _s, out = go("POST", "/audit", {"seal": ["0"]}, {"text": "The sum is 2 + 2 = 4, and 3 * 3 = 10."})
    verdicts["audit"] = json.loads(out)["verdict"]
    go("POST", "/discern", body={"text": "A wall of 4 m by 6 m is 24 m2."})
    go("POST", "/scribe", {"seal": ["0"]}, {"drafts": DRAFTS})
    for method, path, query in (("GET", "/", None), ("GET", "/health", None), ("GET", "/capabilities", None),
                                ("GET", "/ledger/verify", None), ("GET", "/seal", {"hash": [h]}),
                                ("GET", "/seals", {"limit": ["5"]}), ("GET", "/find", {"q": ["compound interest"]}),
                                ("GET", "/schema/mathematics", None), ("GET", "/schema/physics", None),
                                ("GET", f"/s/{h}", None), ("GET", f"/s/{h}", {"html": ["1"]}),
                                ("GET", f"/s/{root}", {"html": ["1"]}), ("GET", "/mcp", None),
                                ("DELETE", "/mcp", None)):
        go(method, path, query)
    rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
    rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    tools = sorted(t.name for t in tool_registry.REGISTRY)
    for n, name in enumerate(tools):
        rpc({"jsonrpc": "2.0", "id": 3 + n, "method": "tools/call", "params": {"name": name, "arguments": TOOL_ARGS[name]}})
    _say({"sympy": "sympy" in sys.modules, "numpy": "numpy" in sys.modules, "routes": seen, "verdicts": verdicts,
          "tools": tools, "pool": pool.status()})


def library_mode() -> None:
    from concordance import cells, derivation as D, http_api
    before = cells.active()
    out = D.verify_derivation([_golden("real_estate")])         # a claim with no heavy import: this runs in the suite
    import multiprocessing
    _say({"verdict": out["verdict"], "before": before, "after": cells.active(), "http_api": bool(http_api),
          "children": len(multiprocessing.active_children()),
          "threads": [t.name for t in threading.enumerate() if t.name.startswith("verify")]})


# ── the moat ─────────────────────────────────────────────────────────────────────────────────────────
def _cases():
    import benchmark as B
    return ([(label, spec, desc, spec["mode"]) for label, spec, desc in B.CLAIMS]
            + [(label, spec, desc, "domain") for label, spec, desc in B._domain_cases()]
            + [(label, spec, desc, "lighthouse") for label, spec, desc in B._lighthouse_cases()]
            + [(label, spec, desc, "check") for label, spec, desc in B._check_cases()])


def moat_mode(how: str) -> None:
    os.environ["CONCORDANCE_MEMO"] = "0"
    os.environ.setdefault("CONCORDANCE_DATA_DIR", os.path.join(ROOT, "data"))
    from concordance import cells, derivation as D
    if how == "cells":
        D.use_cells()
    began = time.monotonic()
    rows = []
    for label, spec, desc, mode in _cases():
        res = D.verify_derivation(spec) if mode in ("domain", "lighthouse", "check") else D.verify(spec)
        rows.append([desc, label, res["verdict"], hashlib.sha256(repr(res).encode("utf-8", "surrogatepass")).hexdigest()])
    pool = cells.active()
    _say({"rows": rows, "sympy": "sympy" in sys.modules, "numpy": "numpy" in sys.modules,
          "secs": time.monotonic() - began, "pool": pool.status() if pool else None})


# ── memory ───────────────────────────────────────────────────────────────────────────────────────────
def _held_kb(pid: int):
    """What a process holds in memory, in kB: PSS on Linux, where a page shared with others counts by its share; its
    working set elsewhere, where nothing here is shared and a cell costs all of what it holds."""
    if sys.platform.startswith("linux"):
        with open(f"/proc/{pid}/smaps_rollup", encoding="ascii") as fh:
            return next(int(ln.split()[1]) for ln in fh if ln.startswith("Pss:"))
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t), ("PrivateUsage", ctypes.c_size_t)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = k32.OpenProcess(0x1000 | 0x0010, False, pid)
    counters = Counters()
    counters.cb = ctypes.sizeof(Counters)
    k32.K32GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
    k32.CloseHandle(handle)
    return counters.WorkingSetSize // 1024


def memory_mode(how: str) -> None:
    os.environ["CONCORDANCE_MEMO"] = "0"
    os.environ.setdefault("CONCORDANCE_DATA_DIR", os.path.join(ROOT, "data"))
    from concurrent.futures import ThreadPoolExecutor
    from concordance import cells, derivation as D
    me = os.getpid()
    sample = _cases()[::20]
    report = {"how": how, "metric": "pss_kb" if sys.platform.startswith("linux") else "working_set_kb",
              "reads": len(sample), "front_at_import": _held_kb(me)}
    pool = None
    if how == "thread":
        D.warm()                                                # or a slow import sheds the reads this is here to count
    if how == "cells":
        D.use_cells()
        pool = cells.active()
        while pool.status()["idle"] < 1:                        # serve() warms one cell off the request path
            time.sleep(0.05)
        report["started_in_s"] = pool.status()["last_start_s"]
        report["front_idle"] = _held_kb(me)
        report["cells_idle"] = [_held_kb(p) for p in pool.status()["pids"]]
        report["forkserver_idle"] = _forkserver_kb()

    def read(case):
        _label, spec, _desc, mode = case
        return D.verify_derivation(spec) if mode in ("domain", "lighthouse", "check") else D.verify(spec)

    with ThreadPoolExecutor(D._MAX_WORKERS) as readers:         # as many reads at once as there are slots
        verdicts = [r["verdict"] for r in readers.map(read, sample)]
    report["system_errors"] = sum(v == "SYSTEM_ERROR" for v in verdicts)
    report["front_busy"] = _held_kb(me)
    if pool:
        report["cells_busy"] = [_held_kb(p) for p in pool.status()["pids"]]
        report["forkserver_busy"] = _forkserver_kb()
        report["cell_inherited"] = [n for n in pool.status()["cell_inherited"] if n in ("numpy", "scipy.stats", "sympy")]
        spare = cells.Cells(1, preload=pool._preload)           # a start on what is already warm
        spare.call(D._read_domain, ("real_estate", {}), 60)
        report["next_start_s"] = spare.status()["last_start_s"]
        spare.close()
    report["sympy_in_front"] = "sympy" in sys.modules
    _say(report)


def growth_mode() -> None:
    os.environ["CONCORDANCE_MEMO"] = "0"
    os.environ.setdefault("CONCORDANCE_DATA_DIR", os.path.join(ROOT, "data"))
    from concordance import cells, derivation as D
    pool = cells.enable(1, reads=10 ** 9, preload=D.cell_preload())
    D.verify_step("real_estate", {})
    cell = pool.status()["pids"][0]
    began = _held_kb(cell)
    cases = _cases()
    for _label, spec, _desc, mode in cases:
        D.verify_derivation(spec) if mode in ("domain", "lighthouse", "check") else D.verify(spec)
    assert pool.status()["pids"] == [cell]
    _say({"reads": len(cases), "began_kb": began, "ended_kb": _held_kb(cell)})


def _forkserver_kb():
    """The forkserver, where this platform has one."""
    try:
        from multiprocessing import forkserver
        pid = forkserver._forkserver._forkserver_pid
    except (ImportError, AttributeError):
        return None
    return _held_kb(pid) if pid else None


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "moat":
        moat_mode(sys.argv[2])
    elif mode == "memory":
        memory_mode(sys.argv[2])
    else:
        {"thread": thread_mode, "cells": cells_mode, "flood": flood_mode, "wall": wall_mode, "library": library_mode,
         "growth": growth_mode, "orphan": orphan_mode, "freeze": lambda: _beating(False),
         "stuck": lambda: _beating(True)}[mode]()
