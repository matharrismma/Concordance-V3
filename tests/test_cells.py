"""A stuck read costs one cell, never the body.

A verifier on a thread of the HTTP process shares one lock with every other thread, so a read that holds it stops them
all and the window around it never wakes. These tests show that with a neutral stand-in, tests/fixtures/lock_holder.py
(a plain integer power, reached by no verifier), and pin what src/concordance/cells.py does about it.

The suite has no time to give: it sits at its 60 s budget. So the tests here are the ones a pool can answer in
milliseconds, and whatever needs a child process, a heavy import or a second window is behind `-m slow`, which CI runs
on Linux on every push: the defect itself over real HTTP, as many stuck reads as cells, the wall, the moat, the memory.
Whatever holds the lock runs in a cell a pool kills, or in a child its parent kills (tests/fixtures/cell_probe.py).
"""
from __future__ import annotations

import importlib
import io
import json
import multiprocessing
import os
import pickle
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
PROBE = FIXTURES / "cell_probe.py"
sys.path.insert(0, str(ROOT / "src"))
if str(FIXTURES) not in sys.path:
    sys.path.insert(0, str(FIXTURES))

import lock_holder  # noqa: E402
from concordance import derivation as D, http_api  # noqa: E402

TIMED_OUT = "verification timed out (> {}s)"
BUSY = "verifier busy (too many concurrent verifications) — retry shortly"
LEAN = ("concordance.cells", "lock_holder")     # what a cell in these tests loads: no heavy library, so it starts fast
BOUND_S = 120                                   # no child outlives this, whatever it is doing


def probe(*args, tmp_path, env=None):
    """One mode of the probe, its last line of stdout as JSON, killed at the bound whatever it is doing."""
    full = dict(os.environ, CONCORDANCE_DATA_DIR=str(tmp_path), PYTHONIOENCODING="utf-8", **(env or {}))
    p = subprocess.Popen([sys.executable, str(PROBE), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, encoding="utf-8", env=full)
    try:
        out, err = p.communicate(timeout=BOUND_S)
    except subprocess.TimeoutExpired:
        p.kill()
        out, err = p.communicate()
        pytest.fail(f"{args} did not finish in {BOUND_S}s: {err[-2000:]}")
    assert p.returncode == 0, err[-4000:]
    return json.loads(out.strip().splitlines()[-1])


@pytest.fixture
def cells():
    return importlib.import_module("concordance.cells")


@pytest.fixture
def pool_of(cells):
    """Pools for one test, each closed at the end whatever the test did."""
    made = []

    def make(size=1, **options):
        options.setdefault("preload", LEAN)
        made.append(cells.Cells(size, **options))
        return made[-1]

    yield make
    for pool in made:
        pool.close()


@pytest.fixture
def cells_on(cells, monkeypatch):
    """Cells on for derivation itself, the way serve() turns them on, with the stand-ins under made-up math modes."""
    for name in ("hold", "quick", "pid", "die"):
        monkeypatch.setitem(D._MATH_MODES, name, getattr(lock_holder, name))
    yield cells.enable(1, preload=LEAN)
    cells.disable()


def step(mode):
    return D.verify_step("mathematics", {"mode": mode, "params": {}})


def alive(pid: int) -> bool:
    return pid in {p.pid for p in multiprocessing.active_children()}


def wait_until(check, secs=30.0):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.005)
    return False


def pid_of(pool) -> int:
    return pool.call(lock_holder.pid, ({},), 30).data["pid"]


# ── a stuck read ─────────────────────────────────────────────────────────────────────────────────────
def test_a_stuck_read_costs_its_cell_and_nothing_else(cells_on, monkeypatch):
    monkeypatch.setattr(D, "_VERIFY_TIMEOUT_S", 0.3)
    first = step("pid")["data"]["pid"]
    assert first != os.getpid()
    beats, stop, got = [], threading.Event(), {}

    def beat():
        while not stop.is_set():
            beats.append(time.monotonic())
            time.sleep(0.01)

    def read():
        got["began"] = time.monotonic()
        got["out"] = step("hold")
        got["ended"] = time.monotonic()

    heart, reader = threading.Thread(target=beat), threading.Thread(target=read)
    heart.start()
    reader.start()
    assert wait_until(lambda: cells_on.status()["taken"] == 1)
    began = time.monotonic()
    busy = step("quick")                                # the one cell is stuck: busy, at once, today's words
    busy_secs = time.monotonic() - began
    reader.join()
    stop.set()
    heart.join()
    assert busy == {"status": "ERROR", "detail": BUSY} and busy_secs < 0.3
    assert got["out"] == {"status": "ERROR", "detail": TIMED_OUT.format(0.3)}      # never a verdict
    assert 0.3 <= got["ended"] - got["began"] < 5
    assert len([b for b in beats if got["began"] <= b <= got["ended"]]) >= 5        # the front never stopped
    assert not alive(first)                             # no slot outlives its cell: it was gone before the slot came back
    assert cells_on.status()["ended"].get("stuck") == 1
    assert cells_on.status()["taken"] == 0 and cells_on.status()["live"] == 0
    assert step("pid")["data"]["pid"] != first          # and it came back by itself


# ── a read in a cell reads as it did ─────────────────────────────────────────────────────────────────
def test_both_call_sites_read_in_a_cell_and_nothing_runs_in_front(cells_on, monkeypatch):
    def not_here(*_a, **_k):
        raise AssertionError("a read ran in the front process")

    monkeypatch.setattr(D._verifiers, "run_for_domain", not_here)
    assert step("pid")["status"] == "CONFIRMED"
    domain = D.verify_step("real_estate", {"NOT_A_PACKET": {}})
    assert domain["status"] == "NOT_APPLICABLE"          # the front's run_for_domain was never called
    assert cells_on.status()["started"] == 1


def test_a_domain_read_is_a_named_function_a_cell_can_be_told_to_run():
    assert pickle.loads(pickle.dumps(D._read_domain)) is D._read_domain
    assert all(pickle.loads(pickle.dumps(fn)) is fn for fn in D._MATH_MODES.values())


def test_a_raise_in_a_cell_reads_as_a_raise_in_process(cells, monkeypatch):
    monkeypatch.setitem(D._MATH_MODES, "raises", lock_holder.raises)
    here = step("raises")
    cells.enable(1, preload=LEAN)
    try:
        there = step("raises")
    finally:
        cells.disable()
    assert there == here == {"status": "ERROR", "detail": "verifier raised: ValueError: a stand-in's own words"}


def test_serve_turns_cells_on_and_importing_does_not(cells, monkeypatch):
    assert cells.active() is None                       # importing the engine turned nothing on
    called = []

    class Server:
        def __init__(self, *_a):
            pass

        def serve_forever(self):
            pass

    monkeypatch.setattr(http_api, "use_cells", lambda: called.append(True))
    monkeypatch.setattr(http_api, "ThreadingHTTPServer", Server)
    http_api.serve("127.0.0.1", 0, background=True)
    assert called == [True]


def test_library_use_stays_on_threads_and_starts_no_process(tmp_path):
    seen = probe("library", tmp_path=tmp_path)
    assert seen["verdict"] == "HOLDS"
    assert seen["before"] is None and seen["after"] is None
    assert seen["children"] == 0 and seen["threads"]


# ── what a cell cannot do is ERROR, never a verdict ──────────────────────────────────────────────────
def test_a_cell_that_dies_is_error_and_the_next_read_stands(cells_on):
    out = step("die")
    assert out["status"] == "ERROR" and "verifier raised: CellFailed" in out["detail"]
    full = D.verify_derivation([{"id": "a", "domain": "mathematics", "spec": {"mode": "die", "params": {}}}])
    assert full["verdict"] == "SYSTEM_ERROR"
    assert cells_on.status()["ended"].get("dead") == 2 and cells_on.status()["taken"] == 0
    assert step("quick")["status"] == "CONFIRMED"


def test_an_answer_that_cannot_be_read_is_error(cells, pool_of):
    pool = pool_of()
    with pytest.raises(cells.CellFailed, match="could not be read"):
        pool.call(lock_holder.unprintable, ({},), 30)   # the cell could not write it, and is fine
    assert pool.status()["live"] == 1
    with pytest.raises(cells.CellFailed, match="could not be read"):
        pool.call(lock_holder.leak, ({},), 30)          # the front would not read it, so the cell goes
    assert pool.status()["ended"].get("dead") == 1 and pool.status()["taken"] == 0
    assert pool.call(lock_holder.quick, ({},), 30).status == "CONFIRMED"


def test_a_cell_that_cannot_start_is_error(cells, pool_of, monkeypatch):
    # the operating system refuses the process
    pool = pool_of()

    class Refused:
        def __init__(self, *_a, **_k):
            pass

        def start(self):
            raise OSError("no more processes")

    with monkeypatch.context() as m:
        m.setattr(pool._ctx, "Process", Refused)
        with pytest.raises(cells.CellFailed, match="could not start"):
            pool.call(lock_holder.quick, ({},), 5)
    assert pool.status()["taken"] == 0                  # the slot came back
    assert pool.call(lock_holder.quick, ({},), 30).status == "CONFIRMED"

    # it never says it is ready
    late = pool_of(start_s=0.0)
    with pytest.raises(cells.CellFailed, match="could not start"):
        late.call(lock_holder.quick, ({},), 5)
    assert late.status()["taken"] == 0 and late.status()["live"] == 0

    # it dies before it can say so
    monkeypatch.setattr(cells, "_cell_main", lock_holder.die_at_start)
    gone = pool_of()
    with pytest.raises(cells.CellFailed, match="could not start"):
        gone.call(lock_holder.quick, ({},), 5)
    assert gone.status()["taken"] == 0 and gone.status()["live"] == 0


def test_a_failed_cell_reaches_the_trail_as_error(cells, cells_on, monkeypatch):
    def refused(*_a, **_k):
        raise cells.CellFailed("a cell could not start")

    monkeypatch.setattr(cells_on, "call", refused)
    out = D.verify_derivation([{"id": "a", "domain": "mathematics", "spec": {"mode": "quick", "params": {}}}])
    assert out["verdict"] == "SYSTEM_ERROR" and out["trail"][0]["status"] == "ERROR"
    assert out["error_at"] == "a"


# ── what crosses the wall ────────────────────────────────────────────────────────────────────────────
def crossed(cells, value):
    """A value as the front receives it: through a cell's filter, onto the pipe, through the front's reader."""
    return cells._read(pickle.dumps(cells._plain(value), protocol=pickle.HIGHEST_PROTOCOL))


def test_sympy_leaves_as_the_string_json_prints_for_it(cells):
    pytest.importorskip("sympy")
    made = lock_holder.sympy_values()
    got = crossed(cells, made)
    assert json.dumps(got.data, sort_keys=True, default=str) == json.dumps(made.data, sort_keys=True, default=str)
    assert got.data["actual"] == "1/3" and got.data["whole"] == "5" and got.data["flag"] == "True"
    assert got.data["nested"] == [{"root": "sqrt(2)"}, ("x + 1", "kept")] and got.data["plain"] == 2.5
    assert got.data["members"] == "{5}"
    assert crossed(cells, lock_holder.sympy_key()).data == {"by_symbol": {"x": 1}}


def test_numpy_and_plain_python_leave_as_they_are(cells):
    numpy = pytest.importorskip("numpy")
    got = crossed(cells, lock_holder.numpy_values()).data
    assert type(got["inside"]) is numpy.bool_ and type(got["p"]) is numpy.float64 and type(got["count"]) is numpy.int64
    assert type(got["bands"][0]["inside"]) is numpy.bool_ and not got["bands"][0]["inside"]
    assert type(got["row"]) is numpy.ndarray and got["row"].tolist() == [1.0, 2.0]
    made = lock_holder.stdlib_values().data
    got = crossed(cells, lock_holder.stdlib_values()).data
    assert got == made and {k: type(v) for k, v in got.items()} == {k: type(v) for k, v in made.items()}


def test_the_front_reads_plain_data_and_refuses_everything_else(cells):
    numpy = pytest.importorskip("numpy")
    sympy = pytest.importorskip("sympy")

    def read(value):
        return cells._Reader(io.BytesIO(pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL))).load()

    assert read(lock_holder.quick()).status == "CONFIRMED"
    assert read(numpy.array([[1.0, 2.0]]).T).tolist() == [[1.0], [2.0]]
    for refused in (sympy.Integer(5), print, os.system, threading.Lock, numpy.load):
        with pytest.raises(pickle.UnpicklingError):
            read(refused)


# ── a cell has a life ────────────────────────────────────────────────────────────────────────────────
def test_a_used_cell_retires_after_its_reads_and_its_slot_is_used_again(pool_of):
    pool = pool_of(reads=3)
    pids = [pid_of(pool) for _ in range(3)]
    assert len(set(pids)) == 1
    assert pool.status()["ended"].get("used") == 1 and pool.status()["live"] == 0
    assert not alive(pids[0])
    assert pid_of(pool) != pids[0] and pool.status()["started"] == 2


def test_an_idle_cell_retires_by_itself_and_a_new_read_fills_the_space(pool_of):
    pool = pool_of(idle_s=0.05)
    first = pid_of(pool)
    assert wait_until(lambda: pool.status()["live"] == 0)
    assert pool.status()["ended"].get("idle") == 1 and pool.status()["taken"] == 0
    assert not alive(first)
    assert pid_of(pool) != first


def test_a_cell_that_died_while_idle_costs_no_read(pool_of):
    pool = pool_of()
    first = pid_of(pool)
    next(p for p in multiprocessing.active_children() if p.pid == first).kill()
    assert wait_until(lambda: not alive(first))
    assert pid_of(pool) != first
    assert pool.status()["ended"].get("dead") == 1


def test_the_count_of_live_cells_never_passes_the_size(pool_of):
    size = 2
    pool = pool_of(size, reads=2)
    stop, widest, outcomes = threading.Event(), [0], []

    def watch():
        while not stop.is_set():
            named = [p for p in multiprocessing.active_children() if p.name == "concordance-cell"]
            widest[0] = max(widest[0], len(named), pool.status()["live"])
            time.sleep(0.001)

    def read():
        for _ in range(3):
            try:
                outcomes.append(pool.call(lock_holder.quick, ({},), 30).status)
            except Exception as exc:  # noqa: BLE001 — busy is an answer here
                outcomes.append(type(exc).__name__)

    watcher = threading.Thread(target=watch)
    readers = [threading.Thread(target=read) for _ in range(4)]
    watcher.start()
    for r in readers:
        r.start()
    for r in readers:
        r.join()
    stop.set()
    watcher.join()
    assert 1 <= widest[0] <= size
    assert set(outcomes) <= {"CONFIRMED", "Saturated"} and "CONFIRMED" in outcomes
    assert pool.status()["taken"] == 0


def test_the_cell_says_how_it_was_made(pool_of):
    pool = pool_of()
    pool.call(lock_holder.quick, ({},), 30)
    assert pool.method == ("spawn" if os.name == "nt" else "forkserver")
    assert pool.status()["made_by_front"] is (os.name == "nt")          # told by the cell, not assumed by the pool


def test_no_in_process_memory_limit_is_set(cells, pool_of):
    source = Path(cells.__file__).read_text(encoding="utf-8")
    assert "setrlimit" not in source and "RLIMIT" not in source
    assert pool_of().call(lock_holder.limits, ({},), 30).data == lock_holder.limits().data


def test_each_cell_raises_its_own_oom_score(cells, pool_of, tmp_path):
    held = tmp_path / "oom_score_adj"
    held.write_text("0", encoding="ascii")
    cells._raise_oom_score(str(held))
    assert held.read_text(encoding="ascii") == "1000"
    cells._raise_oom_score(str(tmp_path / "no" / "such" / "file"))      # where the platform has none, it does nothing
    if sys.platform.startswith("linux"):
        assert pool_of().call(lock_holder.oom_score, ({},), 30).data["oom_score_adj"] == "1000"


# ── behind -m slow: run on Linux by CI on every push ─────────────────────────────────────────────────
@pytest.mark.slow
def test_a_held_lock_stops_a_thread_and_costs_only_a_cell(tmp_path):
    # as library use still runs it: the heartbeat stops and the window never fires
    env = dict(os.environ, CONCORDANCE_DATA_DIR=str(tmp_path), CELL_PROBE_WINDOW_S="0.3", PYTHONUNBUFFERED="1")
    p = subprocess.Popen([sys.executable, str(PROBE), "thread"], stdout=subprocess.PIPE, text=True, env=env)
    lines, read_seen = [], threading.Event()

    def pump():
        for line in p.stdout:
            lines.append(line.split())
            if line.startswith("read"):
                read_seen.set()

    threading.Thread(target=pump, daemon=True).start()
    try:
        assert read_seen.wait(60), "the child never reached the read"
        time.sleep(1.8)                                 # six windows
    finally:
        p.kill()
        p.wait()
    read_at = next(float(ln[1]) for ln in lines if ln[0] == "read")
    before = [ln for ln in lines if ln[0] == "beat" and float(ln[1]) <= read_at]
    after = [ln for ln in lines if ln[0] == "beat" and float(ln[1]) > read_at + 0.25]
    assert len(before) >= 3                             # it was beating
    assert not after                                    # the lock stopped it
    assert not [ln for ln in lines if ln[0] == "shed"]  # the window never fired

    # in a cell: the same read costs the cell and nothing else
    seen = probe("cells", tmp_path=tmp_path)
    assert seen["first"] == "HOLDS"
    assert seen["beats"] >= 5 and seen["widest_gap"] < seen["window"]
    assert len(seen["health"]) >= 3
    assert all(h["status"] == 200 and h["ok"] is True and h["secs"] < seen["window"] for h in seen["health"])
    assert seen["verdict"] == "SYSTEM_ERROR" and seen["status"] == "ERROR"
    assert seen["detail"] == TIMED_OUT.format(seen["window"])
    assert seen["window"] <= seen["secs"] < seen["window"] + 10
    assert seen["next"] == "HOLDS"
    assert seen["pool"]["ended"].get("stuck") == 1 and seen["pool"]["taken"] == 0


@pytest.mark.slow
def test_as_many_stuck_reads_as_cells_shed_alone_and_the_service_comes_back(tmp_path):
    seen = probe("flood", tmp_path=tmp_path)
    assert [s["out"]["status"] for s in seen["stuck"]] == ["ERROR", "ERROR"]
    assert [s["out"]["detail"] for s in seen["stuck"]] == [TIMED_OUT.format(seen["window"])] * 2
    assert all(s["secs"] >= seen["window"] for s in seen["stuck"])
    assert seen["busy"]["status"] == "ERROR" and seen["busy"]["detail"] == BUSY
    assert seen["busy_secs"] < seen["window"]           # at once, not at a window
    assert seen["during"]["ended"].get("stuck") == 2
    assert seen["after"]["status"] == "CONFIRMED"       # no restart: a new cell filled the space
    assert seen["status"]["live"] == 1 and seen["status"]["taken"] == 0


@pytest.mark.slow
def test_real_values_cross_a_real_cell(cells, monkeypatch):
    monkeypatch.setitem(D._MATH_MODES, "sympy_values", lock_holder.sympy_values)
    monkeypatch.setitem(D._MATH_MODES, "numpy_values", lock_holder.numpy_values)
    modes = ("sympy_values", "numpy_values")
    here = {m: step(m) for m in modes}
    cells.enable(1, preload=(*LEAN, "sympy", "numpy"))
    try:
        there = {m: step(m) for m in modes}
    finally:
        cells.disable()
    for mode in modes:
        assert json.dumps(there[mode], sort_keys=True, default=str) == json.dumps(here[mode], sort_keys=True, default=str)


@pytest.mark.slow
def test_the_front_never_imports_sympy_on_any_public_route(tmp_path):
    seen = probe("wall", tmp_path=tmp_path)
    assert not [r for r in seen["routes"] if r["sympy"]], "sympy entered the front"
    assert seen["sympy"] is False
    assert seen["verdicts"]["equality"] == "HOLDS"      # real reads ran, in cells: the wall was not vacuous
    assert seen["verdicts"]["steps"] == dict.fromkeys(("physics", "statistics", "formal_logic", "computer_science",
                                                       "polynomial"), "HOLDS")
    assert seen["verdicts"]["claim"] == "HOLDS"
    assert seen["verdicts"]["audit"] == "BROKEN"
    assert seen["pool"]["started"] >= 1 and seen["pool"]["ended"].get("dead") is None
    routes = {r["route"] for r in seen["routes"]}
    assert {"POST /verify", "POST /audit", "POST /discern", "POST /scribe", "POST /mcp", "GET /mcp", "DELETE /mcp",
            "GET /find", "GET /schema/mathematics", "GET /capabilities", "GET /seal", "GET /seals", "GET /ledger/verify",
            "GET /health", "GET /"} <= routes
    assert sum(r.startswith("GET /s/") for r in routes) >= 2
    from concordance import tool_registry
    assert seen["tools"] == sorted(t.name for t in tool_registry.REGISTRY)
    assert all(r["status"] < 500 for r in seen["routes"])
    assert "sympy" in seen["pool"]["cell_loaded"]       # it had it before its first read, outside any window
    if os.name != "nt":                                 # and shares it: it inherited it from the forkserver
        assert seen["pool"]["made_by_front"] is False and "sympy" in seen["pool"]["cell_inherited"]


@pytest.mark.slow
def test_the_moat_reads_the_same_through_cells():
    full = dict(os.environ, PYTHONIOENCODING="utf-8", CONCORDANCE_DATA_DIR=str(ROOT / "data"))

    def run(how):
        p = subprocess.run([sys.executable, str(PROBE), "moat", how], capture_output=True, text=True, encoding="utf-8",
                           env=full, timeout=1500)
        assert p.returncode == 0, p.stderr[-4000:]
        return json.loads(p.stdout.strip().splitlines()[-1])

    here, there = run("process"), run("cells")
    assert len(here["rows"]) == len(there["rows"]) == 1796
    assert there["sympy"] is False                      # the whole moat, and sympy never entered the front
    differ = [a[0] for a, b in zip(here["rows"], there["rows"]) if a != b]
    assert not differ, differ[:10]                      # the verdict and the repr of every field, types included
    assert not [d for d, label, verdict, _ in there["rows"] if not label and verdict == "HOLDS"]
    assert not [d for d, label, verdict, _ in there["rows"] if label and verdict != "HOLDS"]
    assert not there["pool"]["ended"].get("dead") and not there["pool"]["ended"].get("stuck")


@pytest.mark.slow
def test_memory_of_each_process_idle_and_busy(capsys):
    """Not a bound: the measure MEASURED.md quotes, printed past pytest's capture so a CI log carries it."""
    full = dict(os.environ, PYTHONIOENCODING="utf-8", CONCORDANCE_DATA_DIR=str(ROOT / "data"))
    seen = {}
    for how in ("thread", "cells"):
        p = subprocess.run([sys.executable, str(PROBE), "memory", how], capture_output=True, text=True, encoding="utf-8",
                           env=full, timeout=600)
        assert p.returncode == 0, p.stderr[-4000:]
        seen[how] = json.loads(p.stdout.strip().splitlines()[-1])
    p = subprocess.run([sys.executable, str(PROBE), "growth"], capture_output=True, text=True, encoding="utf-8",
                       env=full, timeout=600)
    assert p.returncode == 0, p.stderr[-4000:]
    seen["growth"] = json.loads(p.stdout.strip().splitlines()[-1])
    with capsys.disabled():
        print("\nCELL MEMORY", json.dumps(seen))
    assert seen["cells"]["sympy_in_front"] is False and seen["thread"]["sympy_in_front"] is True
    assert seen["cells"]["system_errors"] == seen["thread"]["system_errors"] == 0       # it measured reads, not sheds
