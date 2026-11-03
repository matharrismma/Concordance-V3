"""What every test in V3's suite runs under.

1. Caller code runs. The computer_science verifier executes submitted code; production refuses unless
   CONCORDANCE_ALLOW_CODE_EXEC=1 (verifiers/computer_science.py:141-155). The suite runs only its own
   fixtures, so it opts in; tests/test_review_fixes.py::test_computer_science_refuses_code_exec_by_default
   clears the variable and proves the refusal still holds.

2. The memo is off (CONCORDANCE_MEMO=0). Tests measure verifiers; a verdict served from the bucket
   (bucket.py) would hide a regression. tests/test_bucket.py turns it on for itself.

3. No test writes the checkout's stores. With no variable naming a store, the CAS (cas.py:27-34, which
   also holds the memo bucket, the attest and spec sidecars), the ledger (ledger.py:33-40) and the activity
   log (telemetry.py:20-22) fall back to a path relative to the working directory, data/..., which is the
   checkout's own store, and on the box the live one. A subset run that sealed wrote there; a full run
   was spared only because tests/test_claim_grammar.py:8 sets CONCORDANCE_DATA_DIR at import. So:
     * that bare fallback, and only it, is redirected to a temporary directory for the session;
     * a store that still resolves inside the checkout's data/ (a test that points CONCORDANCE_DATA_DIR
       at the real data to read reference files, as tests/test_benchmark.py and test_domain_goldens.py do)
       is a hard test failure;
     * any write into the checkout's data/ by any route is a hard test failure (an audit hook): an
       explicit base_dir or ledger_dir, verifiers/spec.py:364-377 (verifier_specs.jsonl), and
       verifiers/riemann_accel.py:49-55 (its compiled cache, under CONCORDANCE_DATA_DIR/cache when set).
   The failure is pytest's Failed, a BaseException, so no `except Exception` or `except OSError` in the
   code under test can swallow it. No variable is set: CONCORDANCE_CAS_DIR and CONCORDANCE_LEDGER_DIR
   outrank CONCORDANCE_DATA_DIR, so setting them here would override every test's own isolation, and an
   empty CONCORDANCE_DATA_DIR would hide the tracked reference data verifiers read through it
   (number_theory, statistics, pressure_fighting, spec, thesaurus). tests/test_no_test_writes_the_stores.py
   pins all of this.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

os.environ["CONCORDANCE_ALLOW_CODE_EXEC"] = "1"
os.environ["CONCORDANCE_MEMO"] = "0"


# ── 3. no test writes the checkout's stores ──────────────────────────────────────────────────────────
STORE_TMP = Path(tempfile.mkdtemp(prefix="v3-test-stores-"))   # where the bare fallback goes this session
_DATA_PREFIXES = tuple(sorted({os.path.normcase(os.path.abspath(str(DATA))),
                               os.path.normcase(os.path.realpath(str(DATA)))}))


def in_checkout_data(path) -> bool:
    """True when `path` is the checkout's data/ or lies inside it (symlinks resolved)."""
    for p in (os.path.abspath(path), os.path.realpath(path)):
        q = os.path.normcase(p)
        if any(q == d or q.startswith(d + os.sep) for d in _DATA_PREFIXES):
            return True
    return False


def _refuse(what: str, path) -> None:
    pytest.fail(f"{what} inside the checkout's data/ ({path}): a test must keep its stores in a temporary "
                "directory (CONCORDANCE_DATA_DIR, CONCORDANCE_CAS_DIR or CONCORDANCE_LEDGER_DIR, or tmp_path)")


def _guard_resolver(module, attr: str, bare: Path, what: str) -> None:
    resolve = getattr(module, attr)

    def guarded() -> Path:
        p = resolve()
        if p == bare:                         # no variable named it: the cwd-relative fallback
            p = STORE_TMP / bare.relative_to("data")
        if in_checkout_data(p):
            _refuse(f"a test resolved {what}", p)
        return p

    guarded.__wrapped__ = resolve
    guarded.__doc__ = f"{resolve.__doc__ or ''} (guarded by tests/conftest.py)"
    setattr(module, attr, guarded)


_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC


def _paths_written(event: str, args) -> tuple:
    """The paths an audited operation would create, change or remove; () for anything else."""
    if event == "open":
        path, mode, flags = args
        writes = (any(c in mode for c in "wax+") if isinstance(mode, str)
                  else bool(isinstance(flags, int) and flags & _WRITE_FLAGS))
        return (path,) if writes else ()
    if event in ("os.mkdir", "os.remove", "os.rmdir", "os.truncate", "shutil.rmtree"):
        return (args[0],)
    if event == "os.rename":
        return (args[0], args[1])
    if event in ("shutil.copyfile", "shutil.copytree", "shutil.move"):
        return (args[1],)
    return ()


def _refuse_writes_into_checkout_data(event: str, args) -> None:
    for p in _paths_written(event, args):
        if isinstance(p, (str, bytes, os.PathLike)):
            p = os.fsdecode(p)
            if "data" in p or not os.path.isabs(p):    # cheap first: a path into data/ names it, or is relative
                if in_checkout_data(p):
                    _refuse(f"a test tried to write ({event})", p)


def _install_store_guards() -> None:
    src = str(ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    from concordance import cas, ledger, telemetry
    _guard_resolver(cas, "_cas_dir", Path("data") / "cas", "the CAS store")
    _guard_resolver(ledger, "_default_ledger_dir", Path("data") / "ledger", "the ledger")
    _guard_resolver(telemetry, "_path", Path("data") / "activity.jsonl", "the activity log")
    sys.addaudithook(_refuse_writes_into_checkout_data)


_install_store_guards()


def pytest_unconfigure(config):
    shutil.rmtree(STORE_TMP, ignore_errors=True)
