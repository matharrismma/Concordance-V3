#!/usr/bin/env python3
"""V3's gates, the one list: what CI's gates job runs (it calls this file) and what a contributor runs.

    python tools/check.py            # exit 0 only when every gate passes; 2 when another heavy job holds the floor

Every gate below runs, in order, even after one fails, so one run names every failure. Each is a command
run through this interpreter (sys.executable) with PYTHONPATH=src: no shell syntax, so it runs the same
on Windows and Linux, and no pip install (installs stay in CI's setup step: `pip install -e
".[math,scribe,signing,dev]"`). It loads no pytest plugin and enforces no threshold V3 does not state.

  suite integrity     tests/MANIFEST.txt lists every tests/test_*.py, and every listed file is present
  suite               python -m pytest -q
  benchmark           tools/benchmark.py: exits 1 unless every case is correct (0 false positives AND
                      0 false negatives)
  benchmark --check   every registered domain has a golden pair
  benchmark --json    writes benchmark.json, the package CI uploads (exits 1 on a false positive)
  schema_gen --check  every domain's packet schema is generated and current
  vocab_gate          no .org application vocabulary in user-visible strings or docs
  unreached           every verify_* function runs under the benchmark or has a stated reason (a run that
                      measured no verify_* function fails: it checked nothing)
  closure             the lazy import closure of ENTRYPOINTS stays within CORE_MODULES.txt
  ruff                ruff check src tools tests (the rules pyproject.toml selects)

It takes the floor first: .gate.lock in the checkout, the same lock concordance-2's tools/harness.py takes
(the_floor), so a gate and a harness run never contend for this machine.
"""
from __future__ import annotations

import glob
import os
import re
import subprocess
import sys
from typing import Callable, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
ENV = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "src"))
LOCK = os.path.join(ROOT, ".gate.lock")

# The modules the 8 tools and the HTTP/MCP servers enter through. Their lazy import closure must stay
# within CORE_MODULES.txt; adding a module to the core means adding it here and regenerating that file.
ENTRYPOINTS = ["derivation", "audit", "receipts", "cas", "ledger", "discern", "capabilities", "redact",
               "airlock", "tool_registry", "verifiers", "mcp.server", "engine", "http_api", "__main__",
               "schema", "text", "scribe", "compose", "transparency", "bucket"]


def _modules(lines) -> set:
    return {ln.split()[0] for ln in lines if ln.strip() and not ln.startswith("#")}


def _within_core(stdout: str) -> Tuple[bool, str]:
    with open(os.path.join(ROOT, "CORE_MODULES.txt"), encoding="utf-8") as fh:
        core = _modules(fh)
    extra = sorted(_modules(stdout.splitlines()) - core)
    return (not extra), (f"modules reached but not in CORE_MODULES.txt: {extra}" if extra
                         else "the closure is within CORE_MODULES.txt")


def _measured_something(stdout: str) -> Tuple[bool, str]:
    """unreached.py exits 0 when it finds no gap, including when it found no verify_* function at all (a
    path filter that matched nothing). A coverage gate that measured nothing checked nothing, so it fails."""
    m = re.search(r"^(\d+) verify_\* functions.*$", stdout, re.M)
    line = m.group(0) if m else "(no summary line)"
    if m and int(m.group(1)) > 0:
        return True, line
    return False, f"{line}: the coverage gate measured no verify_* function, so it checked nothing"


class Gate:
    """One gate: a command, where its stdout goes (None: the console; a file name: written there;
    a check: captured and judged), what it means, and any variables it needs beyond ENV."""

    def __init__(self, name: str, argv: List[str], means: str, *, stdout_file: Optional[str] = None,
                 judge: Optional[Callable[[str], Tuple[bool, str]]] = None, env: Optional[dict] = None):
        self.name, self.argv, self.means, self.stdout_file, self.judge = name, argv, means, stdout_file, judge
        self.env = dict(ENV, **(env or {}))

    def run(self) -> bool:
        print(f"\n$ {' '.join(self.argv)}" + (f"  > {self.stdout_file}" if self.stdout_file else ""), flush=True)
        if self.stdout_file:
            with open(os.path.join(ROOT, self.stdout_file), "w", encoding="utf-8") as out:
                return subprocess.call(self.argv, cwd=ROOT, env=self.env, stdout=out) == 0
        if self.judge:
            p = subprocess.run(self.argv, cwd=ROOT, env=self.env, capture_output=True, text=True, encoding="utf-8")
            if p.returncode != 0:
                print(p.stdout[-4000:] + p.stderr[-2000:], flush=True)
                return False
            ok, why = self.judge(p.stdout)
            if not ok:
                print(p.stdout[-4000:], flush=True)
            print(why, flush=True)
            return ok
        return subprocess.call(self.argv, cwd=ROOT, env=self.env) == 0


GATES: List[Gate] = [
    Gate("suite", [PY, "-m", "pytest", "-q"], "the test suite"),
    Gate("benchmark", [PY, "tools/benchmark.py"], "every case correct: 0 false positives and 0 false negatives"),
    Gate("benchmark --check", [PY, "tools/benchmark.py", "--check"], "every registered domain has a golden pair"),
    Gate("benchmark --json", [PY, "tools/benchmark.py", "--json"], "the benchmark.json package CI uploads",
         stdout_file="benchmark.json", env={"PYTHONIOENCODING": "utf-8"}),   # JSON is UTF-8 on every platform
    Gate("schema_gen --check", [PY, "tools/schema_gen.py", "--check"], "every packet schema generated and current"),
    Gate("vocab_gate", [PY, "tools/vocab_gate.py"], "no .org application vocabulary in user-visible text"),
    Gate("unreached", [PY, "tools/unreached.py"], "every verify_* function reached or excused",
         judge=_measured_something),
    Gate("closure", [PY, "tools/closure.py", *ENTRYPOINTS, "--lazy", "--src", "src/concordance"],
         "the core's lazy import closure within CORE_MODULES.txt", judge=_within_core),
    Gate("ruff", [PY, "-m", "ruff", "check", "src", "tools", "tests"], "the lint rules pyproject.toml selects"),
]


def _suite_is_whole() -> bool:
    """tests/MANIFEST.txt says what the suite IS: a listed file that is absent never ran, and an unlisted
    one is outside the declared suite. Either fails the gate rather than quietly changing the suite."""
    man = os.path.join(ROOT, "tests", "MANIFEST.txt")
    if not os.path.exists(man):
        print("\nMISSING tests/MANIFEST.txt: cannot prove the suite is whole", flush=True)
        return False
    with open(man, encoding="utf-8") as fh:
        want = {ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")}
    have = {os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "tests", "test_*.py"))}
    missing, extra = sorted(want - have), sorted(have - want)
    print(f"\n$ suite integrity: {len(have)} test files present, {len(want)} listed", flush=True)
    for m in missing:
        print(f"  MISSING (listed, never ran): {m}", flush=True)
    for e in extra:
        print(f"  UNLISTED (add to tests/MANIFEST.txt): {e}", flush=True)
    return not (missing or extra)


# ── the floor: one heavy job at a time on this machine ───────────────────────────────────────────────
def _pid_alive(pid: int) -> bool:
    """Is `pid` running? Never os.kill(pid, 0) on Windows: there it sends CTRL_C_EVENT instead of probing.
    The same test concordance-2's tools/harness.py makes before it reclaims this lock."""
    if pid <= 0 or pid > 0xFFFFFFFF:
        return False
    if os.name == "nt":
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        hnd = k32.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
        if not hnd:
            return ctypes.get_last_error() == 5             # access denied: it exists under another account
        try:
            code = ctypes.c_ulong()
            return bool(k32.GetExitCodeProcess(hnd, ctypes.byref(code))) and code.value == 259   # STILL_ACTIVE
        finally:
            k32.CloseHandle(hnd)
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except (OSError, OverflowError):                    # no such process, or a pid beyond pid_t
        return False


def _take_the_floor() -> bool:
    """True when this process holds .gate.lock. Taken atomically (O_EXCL), as the harness takes it; a lock
    whose pid is dead is reclaimed, said out loud; a live holder is refused."""
    for _ in range(2):
        try:
            fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(f"{os.getpid()} check.py\n")
            return True
        except FileExistsError:
            try:
                with open(LOCK, encoding="utf-8") as fh:
                    pid = int((fh.read().split() or ["0"])[0])
            except (OSError, ValueError):
                pid = 0
            if _pid_alive(pid):
                print(f"ANOTHER HEAVY JOB HOLDS THE FLOOR (pid {pid}): the gate runs alone. Wait, or remove "
                      f"{LOCK} if you know it is dead.", flush=True)
                return False
            print(f"(reclaiming a stale lock from pid {pid or '?'})", flush=True)
            try:
                os.remove(LOCK)
            except OSError:
                pass
    print(f"could not take the floor at {LOCK}", flush=True)
    return False


def _yield_the_floor() -> None:
    """Release this process's lock, and only this process's."""
    try:
        with open(LOCK, encoding="utf-8") as fh:
            pid = int((fh.read().split() or ["0"])[0])
        if pid == os.getpid():
            os.remove(LOCK)
    except (OSError, ValueError):
        pass


def main() -> int:
    if not _take_the_floor():
        return 2
    try:
        failed = [] if _suite_is_whole() else ["suite integrity"]
        for gate in GATES:
            if not gate.run():
                failed.append(gate.name)
        print("\n=== GATE PASS ===" if not failed else f"\n=== GATE FAIL: {', '.join(failed)} ===", flush=True)
        return 1 if failed else 0
    finally:
        _yield_the_floor()


if __name__ == "__main__":
    sys.exit(main())
