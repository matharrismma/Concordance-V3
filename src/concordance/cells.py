"""Cells — a read runs in a worker process the front can kill.

A verifier on a thread of the HTTP process shares Python's global lock with every thread there. A read that holds the
lock stops them all at once, so the window around it never wakes and nothing answers; no false verdict comes of it, the
engine just stops. A process is the wall that lock cannot cross, and a process can be killed from outside whatever it
is doing, so a stuck read costs one cell and the rest of the engine keeps answering.

A cell has a life, and on every way out it is gone before its slot is free:

    stuck   killed at the window; the read sheds as it always has
    used    retired after CONCORDANCE_CELL_READS reads, so the caches a read fills do not grow without end
    idle    retired after CONCORDANCE_CELL_IDLE_S seconds unused, so its memory goes back to the machine
    dead    it ended by itself, or sent what cannot be read; the read is ERROR, never a verdict

New cells start on demand and fill the space, and never more are alive than the pool's size. A hand-held pool, because
concurrent.futures.ProcessPoolExecutor cannot kill one stuck worker alone.

A cell is pure: it reads and writes nothing, so seals, the ledger, the CAS and every other write stay in the front and
keep their order. What it returns crosses a filter (_plain) and a reader that refuses all but plain data (_Reader), so
a sympy value leaves as the string JSON prints for it and sympy never enters the front; a numpy value leaves as it is.

The memory wall stands outside the cell, in the unit, and each cell raises its own oom_score_adj so the kernel ends the
cell first and the front reads a dead pipe. No limit is set in process: that raises a MemoryError, which verifier code
can catch and read as an answer.

Nothing here spawns on import. serve() turns cells on through derivation.use_cells(); library use stays on its threads.
On Linux cells fork from a forkserver that preloaded the heavy libraries, so they share its pages and start in
milliseconds; where there is no forkserver they spawn, and each pays the imports before it says it is ready, outside
any window.
"""
from __future__ import annotations

import collections
import concurrent.futures as _futures
import importlib
import io
import logging
import os
import pickle
import signal
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Set

from .verifiers.base import VerifierResult

_log = logging.getLogger("concordance")

_READS = max(1, int(os.environ.get("CONCORDANCE_CELL_READS", "1000") or 1000))
_IDLE_S = float(os.environ.get("CONCORDANCE_CELL_IDLE_S", "120") or 120)
_START_S = float(os.environ.get("CONCORDANCE_CELL_START_S", "60") or 60)
_GONE_S = 5.0                                   # how long a killed cell is given to be gone
_OOM_SCORE_ADJ = "/proc/self/oom_score_adj"
_NAME = "concordance-cell"


class Saturated(Exception):
    """All verify slots are busy — shed load rather than queue unbounded work."""


class CellFailed(Exception):
    """A cell died, could not start, or sent what cannot be read. The read is ERROR, never a verdict."""


class Raised(Exception):
    """A verifier raised inside a cell. `kind` names its type and str() is its message, which is all a read in
    process would have reported of it."""

    def __init__(self, kind: str, text: str) -> None:
        super().__init__(text)
        self.kind = kind


# ── what crosses the wall ────────────────────────────────────────────────────────────────────────────
_NUMPY_NAMES = frozenset({"scalar", "dtype", "ndarray", "_reconstruct", "_frombuffer"})
_CROSSES = frozenset({("builtins", "complex"), ("fractions", "Fraction"), ("decimal", "Decimal"),
                      ("concordance.verifiers.base", "VerifierResult")})


def _plain(value: Any) -> Any:
    """A verifier's result as it may leave a cell. Plain data stays what it is, a numpy value stays what it is, and
    anything else, a sympy value above all, becomes the string json.dumps(default=str) prints for it today."""
    kind = type(value)
    if value is None or kind in (bool, int, float, str, bytes):
        return value
    if kind.__module__.partition(".")[0] == "numpy":
        import numpy
        whole = isinstance(value, numpy.generic) or (kind is numpy.ndarray and not value.dtype.hasobject)
        return value if whole else str(value)
    if isinstance(value, VerifierResult):
        return VerifierResult(_plain(value.name), _plain(value.status), _plain(value.detail), _plain(value.data))
    if isinstance(value, dict):
        return {_plain(k): _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_plain(v) for v in value)
    if kind in (set, frozenset):
        return value if all(_plain(v) is v for v in value) else str(value)
    if (kind.__module__, kind.__name__) in _CROSSES:
        return value
    for base in (int, float):                   # what JSON prints for a subclass is the number
        if isinstance(value, base):
            return base(value)
    return str(value)


class _Reader(pickle.Unpickler):
    """How the front reads a cell. Only plain data crosses: naming a class outside this list is what unpickling would
    otherwise import, and sympy is what the wall keeps out."""

    def find_class(self, module: str, name: str) -> Any:
        if (module, name) in _CROSSES or (module.partition(".")[0] == "numpy" and name in _NUMPY_NAMES):
            return super().find_class(module, name)
        raise pickle.UnpicklingError(f"a cell may not send {module}.{name}")


def _read(raw: bytes) -> Any:
    return _Reader(io.BytesIO(raw)).load()


# ── inside a cell ────────────────────────────────────────────────────────────────────────────────────
def _raise_oom_score(path: str = _OOM_SCORE_ADJ) -> None:
    """Ask the kernel to end this cell first when memory runs out. Raising it needs no privilege; where the platform
    has no such file it does nothing."""
    try:
        with open(path, "w", encoding="ascii") as fh:
            fh.write("1000")
    except OSError:
        pass


def _answer(job: bytes) -> bytes:
    """One read. A raise is the verifier's own answer, told as the front would have seen it in process; a result that
    cannot be written is not an answer at all."""
    try:
        fn, args = pickle.loads(job)
        value = fn(*args)
    except Exception as exc:  # noqa: BLE001 — verify_step reads every raise as ERROR
        return pickle.dumps(("raised", type(exc).__name__, str(exc)))
    try:
        return pickle.dumps(("value", _plain(value)), protocol=pickle.HIGHEST_PROTOCOL)
    except Exception as exc:  # noqa: BLE001
        return pickle.dumps(("unreadable", type(exc).__name__))


def _heavy_loaded() -> List[str]:
    return sorted(n for n in ("numpy", "scipy", "sympy") if n in sys.modules)


def _cell_main(conn: Any, preload: Sequence[str]) -> None:
    """A cell's whole life: load what it needs, say it is ready, then answer until the front closes the pipe or kills
    it. It runs on a process's main thread, and nothing here touches a store. What it says is measured from inside,
    since multiprocessing tells a child the default start method and not the one that started it: `parent` shows who
    made it, and `inherited` what it had before it imported anything, which is what it shares with a forkserver."""
    _raise_oom_score()
    signal.signal(signal.SIGINT, signal.SIG_IGN)     # the front decides when a cell ends
    inherited = _heavy_loaded()
    for name in preload:
        try:
            importlib.import_module(name)
        except Exception:  # noqa: BLE001 — a sovereign install without a library still starts
            pass
    conn.send_bytes(pickle.dumps({"pid": os.getpid(), "parent": os.getppid(), "inherited": inherited,
                                  "loaded": _heavy_loaded()}))
    while True:
        try:
            conn.send_bytes(_answer(conn.recv_bytes()))
        except (EOFError, OSError):
            return


# ── the pool, in the front ───────────────────────────────────────────────────────────────────────────
class _Cell:
    __slots__ = ("proc", "conn", "reads", "since")

    def __init__(self, proc: Any, conn: Any) -> None:
        self.proc, self.conn, self.reads, self.since = proc, conn, 0, time.monotonic()

    def waiting(self) -> bool:
        """Is it alive, with nothing on the pipe? A closed pipe polls readable, and an idle cell has nothing to say."""
        try:
            return self.proc.is_alive() and not self.conn.poll()
        except (EOFError, OSError):
            return False


class Cells:
    """At most `size` cells. `_taken` counts the slots in use: a read holds one from before it has a cell until its
    cell is back or gone, and so does an idle cell on its way out, so a slot is free only when no process is on it."""

    def __init__(self, size: int, *, preload: Sequence[str] = (), reads: Optional[int] = None,
                 idle_s: Optional[float] = None, start_s: Optional[float] = None) -> None:
        import multiprocessing
        self.method = "forkserver" if "forkserver" in multiprocessing.get_all_start_methods() else "spawn"
        self._ctx = multiprocessing.get_context(self.method)
        if self.method == "forkserver":
            self._ctx.set_forkserver_preload(list(preload))
        self._size, self._preload = max(1, int(size)), tuple(preload)
        self._reads = _READS if reads is None else max(1, int(reads))
        self._idle_s = _IDLE_S if idle_s is None else float(idle_s)
        self._start_s = _START_S if start_s is None else float(start_s)
        self._lock = threading.Lock()
        self._starting = threading.Lock()       # one Process.start() at a time: it polls every other child
        self._idle: List[_Cell] = []
        self._live: Set[_Cell] = set()
        self._taken = 0
        self._closed = False
        self._started = 0
        self._ended: collections.Counter = collections.Counter()
        self._hello: Dict[str, Any] = {}
        self._last_start_s: Optional[float] = None
        self._stop = threading.Event()
        threading.Thread(target=self._keep, name="cells-keeper", daemon=True).start()

    # a read
    def call(self, fn: Callable[..., Any], args: tuple, window: float) -> Any:
        """Run fn(*args) in a cell. Busy raises Saturated at once; past `window` the cell is killed and TimeoutError
        raised; a cell that fails raises CellFailed; a raise inside raises Raised. The window starts when the cell
        has the read, so a start is never charged to it."""
        job = pickle.dumps((fn, args), protocol=pickle.HIGHEST_PROTOCOL)
        with self._lock:
            if self._closed or self._taken >= self._size:
                raise Saturated()
            self._taken += 1
            cell = self._idle.pop() if self._idle else None     # newest first, so the others can go idle
        try:
            if cell is not None and not cell.waiting():
                self._end(cell, "dead")
                cell = None
            cell = cell or self._start()
            raw = self._ask(cell, job, window)
            answer = self._take_answer(cell, raw)
            self._rest(cell)
        finally:
            self._free()
        if answer[0] == "value":
            return answer[1]
        if answer[0] == "raised":
            raise Raised(answer[1], answer[2])
        raise CellFailed("the answer from a cell could not be read")

    def _ask(self, cell: _Cell, job: bytes, window: float) -> bytes:
        try:
            cell.conn.send_bytes(job)
            if cell.conn.poll(window):
                return cell.conn.recv_bytes()
        except (EOFError, OSError) as exc:
            self._end(cell, "dead")
            raise CellFailed("the cell ended before it answered") from exc
        self._end(cell, "stuck")
        raise _futures.TimeoutError()           # outside the try: on 3.11+ this is an OSError

    def _take_answer(self, cell: _Cell, raw: bytes) -> tuple:
        try:
            answer = _read(raw)
            if not isinstance(answer, tuple) or answer[0] not in ("value", "raised", "unreadable"):
                raise pickle.UnpicklingError("not an answer")
        except Exception as exc:  # noqa: BLE001 — anything unreadable is ERROR
            self._end(cell, "dead")
            raise CellFailed("the answer from a cell could not be read") from exc
        cell.reads += 1
        return answer

    def _rest(self, cell: _Cell) -> None:
        with self._lock:
            keep = not self._closed and cell.reads < self._reads
            if keep:
                cell.since = time.monotonic()
                self._idle.append(cell)
        if not keep:
            self._end(cell, "used")

    def _free(self) -> None:
        with self._lock:
            self._taken -= 1

    # a start and an end
    def _start(self) -> _Cell:
        from multiprocessing import connection
        began = time.monotonic()
        parent, child = self._ctx.Pipe(duplex=True)
        proc = self._ctx.Process(target=_cell_main, args=(child, self._preload), name=_NAME, daemon=True)
        if not self._starting.acquire(timeout=self._start_s):
            parent.close()
            child.close()
            raise CellFailed("a cell could not start: another start has not finished")
        try:
            proc.start()
        except Exception as exc:  # noqa: BLE001 — a cell that cannot start is ERROR
            parent.close()
            child.close()
            raise CellFailed(f"a cell could not start: {type(exc).__name__}") from exc
        finally:
            self._starting.release()
        child.close()
        cell = _Cell(proc, parent)
        with self._lock:
            self._live.add(cell)
            self._started += 1
        try:
            up = connection.wait([parent, proc.sentinel], self._start_s)
            hello = _read(parent.recv_bytes()) if parent in up else None
        except Exception:  # noqa: BLE001 — what it said could not be read, or it died saying it
            hello = None
        if not isinstance(hello, dict):
            self._end(cell, "dead")
            raise CellFailed("a cell could not start")
        with self._lock:
            self._hello, self._last_start_s = hello, time.monotonic() - began
        return cell

    def _end(self, cell: _Cell, why: str) -> None:
        """The only way out for a cell, and it is gone before this returns. It holds nothing worth saving, so every
        end is a kill: a cell that has answered has nothing left to do, and a stuck one can do nothing else."""
        try:
            cell.proc.kill()
            cell.proc.join(_GONE_S)
        except (OSError, ValueError, AttributeError) as exc:
            _log.warning("ending a cell: %s", exc)
        if why == "dead":
            _log.warning("a cell ended by itself or sent nonsense (pid %s, exit %s)", cell.proc.pid, cell.proc.exitcode)
        cell.conn.close()
        with self._lock:
            self._live.discard(cell)
            self._ended[why] += 1

    # the idle bound
    def _keep(self) -> None:
        tick = min(max(self._idle_s / 4, 0.02), 5.0)
        while not self._stop.wait(tick):
            self._retire_idle()

    def _retire_idle(self) -> None:
        now = time.monotonic()
        with self._lock:
            old = [c for c in self._idle if now - c.since >= self._idle_s]
            self._idle = [c for c in self._idle if c not in old]
            self._taken += len(old)
        for cell in old:
            self._end(cell, "idle")
            self._free()

    def warm(self) -> None:
        """Start one cell now, off any request, so the first read does not wait for the forkserver's imports."""
        threading.Thread(target=self._warm_one, name="cells-warm", daemon=True).start()

    def _warm_one(self) -> None:
        with self._lock:
            if self._closed or self._idle or self._taken >= self._size:
                return
            self._taken += 1
        try:
            self._rest(self._start())
        except CellFailed as exc:
            _log.warning("warming a cell: %s", exc)
        finally:
            self._free()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            idle, self._idle = self._idle, []
        self._stop.set()
        for cell in idle:
            self._end(cell, "closed")

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {"method": self.method, "size": self._size, "live": len(self._live), "taken": self._taken,
                    "idle": len(self._idle), "started": self._started, "ended": dict(self._ended),
                    "pids": sorted(c.proc.pid for c in self._live if c.proc.pid), "last_start_s": self._last_start_s,
                    "made_by_front": self._hello.get("parent") == os.getpid() if self._hello else None,
                    "cell_inherited": list(self._hello.get("inherited") or ()),
                    "cell_loaded": list(self._hello.get("loaded") or ())}


# ── on and off ───────────────────────────────────────────────────────────────────────────────────────
_active: Optional[Cells] = None
_switch = threading.Lock()


def enable(size: int, *, warm: bool = False, **options: Any) -> Cells:
    """Turn cells on for this process. Once on they stay as they are: a second call changes nothing."""
    global _active
    with _switch:
        if _active is None:
            _active = Cells(size, **options)
            if warm:
                _active.warm()
        return _active


def disable() -> None:
    """Back to threads, and every idle cell ended. A read in progress finishes in its cell, which then goes."""
    global _active
    with _switch:
        pool, _active = _active, None
    if pool is not None:
        pool.close()


def active() -> Optional[Cells]:
    return _active


__all__ = ["CellFailed", "Cells", "Raised", "Saturated", "active", "disable", "enable"]
