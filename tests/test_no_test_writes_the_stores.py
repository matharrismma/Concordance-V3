"""No test writes the checkout's stores: the guard in tests/conftest.py (its docstring, part 3).

The defect: with no store variable set, the CAS, the ledger and the memo bucket fall back to data/...
relative to the working directory, the checkout's own store. A single-file run that sealed wrote there (in
the box's live checkout, the live store); a full run was spared only by tests/test_claim_grammar.py:8
setting CONCORDANCE_DATA_DIR at import. The pin runs a sealing test ALONE in a subprocess, on a record no
store holds yet (re-sealing a stored record writes nothing: cas.py:78, receipts.py:160), and compares the
checkout's data/cas and data/ledger by hash.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

from concordance import cas, ledger, telemetry

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CHILD = ROOT / "tests" / "fixtures" / "seal_a_fresh_record.py"
STORE_VARS = ("CONCORDANCE_DATA_DIR", "CONCORDANCE_CAS_DIR", "CONCORDANCE_LEDGER_DIR")


def _in_data(path) -> bool:
    d = os.path.normcase(os.path.realpath(str(DATA)))
    q = os.path.normcase(os.path.realpath(str(path)))
    return q == d or q.startswith(d + os.sep)


def _tree(d: Path) -> dict:
    """Every directory and file under d, files by sha256: a new empty directory counts as a change."""
    out = {}
    if d.exists():
        for p in sorted(d.rglob("*")):
            rel = p.relative_to(d).as_posix()
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "dir"
    return out


def test_a_single_file_run_that_seals_leaves_the_checkout_stores_unchanged(tmp_path):
    env = {k: v for k, v in os.environ.items() if k not in STORE_VARS and not k.startswith(("HARNESS_", "VACUITY_"))}
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "src")] + [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p])
    env["V3_FRESH_NONCE"] = uuid.uuid4().hex
    env["V3_FRESH_OUT"] = str(tmp_path / "sealed.json")
    before = _tree(DATA / "cas"), _tree(DATA / "ledger")
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(CHILD)],
                       cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=300)
    assert p.returncode == 0, (p.stdout[-3000:], p.stderr[-3000:])
    sealed = json.loads((tmp_path / "sealed.json").read_text(encoding="utf-8"))
    after = _tree(DATA / "cas"), _tree(DATA / "ledger")
    assert after[0] == before[0], f"the checkout's data/cas changed: {sorted(set(after[0]) ^ set(before[0]))[:6]}"
    assert after[1] == before[1], f"the checkout's data/ledger changed: {sorted(set(after[1]) ^ set(before[1]))[:6]}"
    assert f"{sealed['hash'][:2]}/{sealed['hash'][2:]}.json" not in after[0]     # fresh: never in this store
    assert not _in_data(sealed["cas"]) and not _in_data(sealed["ledger"])


def test_the_bare_fallback_goes_to_the_session_directory(monkeypatch):
    for var in STORE_VARS:
        monkeypatch.delenv(var, raising=False)
    got = {name: resolve() for resolve, name in ((cas._cas_dir, "cas"), (ledger._default_ledger_dir, "ledger"),
                                                 (telemetry._path, "activity.jsonl"))}
    session = {p.parent for p in got.values()}
    assert len(session) == 1 and all(p.name == name for name, p in got.items())     # one session directory
    (d,) = session
    assert d.is_absolute() and not _in_data(d)
    assert os.path.normcase(str(d.resolve())).startswith(os.path.normcase(str(Path(tempfile.gettempdir()).resolve())))


def test_a_store_resolving_inside_the_checkout_data_fails_hard(monkeypatch):
    monkeypatch.setenv("CONCORDANCE_DATA_DIR", str(DATA))       # how a test reads reference data
    for var in STORE_VARS[1:]:
        monkeypatch.delenv(var, raising=False)
    for resolve in (cas._cas_dir, ledger._default_ledger_dir, telemetry._path):
        with pytest.raises(pytest.fail.Exception, match="inside the checkout's data/"):
            resolve()
    rec = {"kind": "probe", "nonce": uuid.uuid4().hex}
    try:
        with pytest.raises(pytest.fail.Exception):              # a broad except cannot swallow it
            try:
                cas.store(rec)
            except Exception:  # noqa: BLE001
                pass
    finally:                                                    # if the guard failed, leave nothing behind
        cas.delete(cas.content_hash_of(rec), base_dir=DATA / "cas")


def test_a_write_into_the_checkout_data_fails_hard_by_any_route():
    base = DATA / "cas"
    rec = {"kind": "probe", "nonce": uuid.uuid4().hex}
    probe = DATA / ".no-test-writes-probe"
    try:
        with pytest.raises(pytest.fail.Exception, match="tried to write"):
            cas.store(rec, base_dir=base)                       # an explicit dir bypasses every resolver
        with pytest.raises(pytest.fail.Exception, match="tried to write"):
            probe.write_text("x", encoding="utf-8")
        with pytest.raises(pytest.fail.Exception, match="tried to write"):
            os.close(os.open(str(probe), os.O_CREAT | os.O_WRONLY))
    finally:                                                    # if the guard failed, leave nothing behind
        if probe.exists():
            probe.unlink()
        cas.delete(cas.content_hash_of(rec), base_dir=base)


def test_verifiers_still_read_the_tracked_reference_data(monkeypatch):
    """The guard sets no CONCORDANCE_DATA_DIR, so a verifier that reads data/ through it still finds the
    tracked files (an empty temporary data dir would make these NOT_APPLICABLE and still pass elsewhere)."""
    from concordance.verifiers import number_theory, pressure_fighting, statistics
    monkeypatch.delenv("CONCORDANCE_DATA_DIR", raising=False)
    monkeypatch.chdir(ROOT)
    assert number_theory._load_zeta_gammas()
    assert statistics._load_zeta_zeros()[0]
    monkeypatch.setattr(pressure_fighting, "_GRAMMAR", {})
    monkeypatch.setattr(pressure_fighting, "_HASH", "")
    assert pressure_fighting._load()


# ── a path given with a dir_fd is judged against that descriptor's directory ─────────────────────────
# CI run 41559635723 (066c530): 13 suite tests and 4 slow ones failed with "a test tried to write (os.rmdir)
# inside the checkout's data/ (data)". tools/halt_telemetry.py and order_replica.py copy data/ into a
# temporary directory and rmtree it; on Linux rmtree is fd-based and removes the copy as
# os.rmdir('data', dir_fd=<its parent>), and the guard judged that bare 'data' against the cwd.
_UNKNOWN_FD, _TMP_FD, _DATA_FD = 900007, 900008, 900009       # never open: resolution is injected or absent


def _conftest():
    """tests/conftest.py as pytest loaded it (importing it again would install a second hook)."""
    want = (ROOT / "tests" / "conftest.py").resolve()
    for m in list(sys.modules.values()):
        f = getattr(m, "__file__", None)
        if f and Path(f).resolve() == want:
            return m
    pytest.fail("tests/conftest.py is not loaded in this process")


def test_the_ci_false_positive_a_bare_data_through_a_dir_fd_is_not_the_checkouts(monkeypatch):
    monkeypatch.chdir(ROOT)                                   # where a bare 'data' is the checkout's data/
    _conftest()._refuse_writes_into_checkout_data("os.rmdir", ("data", _UNKNOWN_FD))


def test_rmtree_of_a_tree_holding_a_data_dir_does_not_trip_the_guard(tmp_path, monkeypatch):
    """The real route: on Linux (rmtree.avoids_symlink_attacks) this rmtree removes 'data' through a dir_fd.
    Windows rmtree passes full paths, so there it shows only that the guard leaves a tmp tree alone."""
    monkeypatch.chdir(ROOT)
    leaf = tmp_path / "copy" / "data" / "cas" / "ab"
    leaf.mkdir(parents=True)
    (leaf / "c.json").write_text("{}", encoding="utf-8")
    (tmp_path / "copy" / "data" / "ledger").mkdir()
    shutil.rmtree(tmp_path / "copy")
    assert not (tmp_path / "copy").exists()


def test_a_path_with_a_dir_fd_is_judged_against_that_directory(tmp_path, monkeypatch):
    C = _conftest()
    monkeypatch.chdir(ROOT)
    dirs = {_TMP_FD: str(tmp_path), _DATA_FD: str(DATA)}
    with monkeypatch.context() as m:
        m.setattr(C, "_fd_dir", dirs.get)
        assert C._judged_path("data", _TMP_FD) == os.path.join(str(tmp_path), "data")
        assert C._judged_path("cas", _DATA_FD) == os.path.join(str(DATA), "cas")
        assert C._judged_path("data", _UNKNOWN_FD) is None                    # unresolvable: not judged
        assert C._judged_path(str(tmp_path / "x"), _DATA_FD) == str(tmp_path / "x")   # absolute: fd ignored
        assert C._judged_path("data", -1) == "data" and C._judged_path("data", None) == "data"   # the cwd
        for event, args in (("os.rmdir", ("data", _TMP_FD)), ("os.remove", ("data", _TMP_FD)),
                            ("os.mkdir", ("data", 0o777, _TMP_FD)), ("os.rename", ("data", "data", _TMP_FD, _TMP_FD)),
                            ("shutil.rmtree", ("data", _TMP_FD))):
            C._refuse_writes_into_checkout_data(event, args)                 # a tmp tree's 'data': allowed
        for event, args in (("os.rmdir", ("cas", _DATA_FD)), ("os.remove", ("x.json", _DATA_FD)),
                            ("os.mkdir", ("cas", 0o777, _DATA_FD)), ("os.rename", ("t", "cas", _TMP_FD, _DATA_FD)),
                            ("shutil.rmtree", ("cas", _DATA_FD))):
            with pytest.raises(pytest.fail.Exception, match="tried to write"):
                C._refuse_writes_into_checkout_data(event, args)             # into the checkout's data/
    with pytest.raises(pytest.fail.Exception, match="tried to write"):
        C._refuse_writes_into_checkout_data("os.rmdir", ("data/cas", -1))   # no dir_fd: the cwd decides


@pytest.mark.skipif(os.mkdir not in os.supports_dir_fd, reason="os.mkdir takes no dir_fd on this platform (Windows)")
def test_a_write_through_a_dir_fd_into_the_checkout_data_fails_hard():
    probe = ".no-test-writes-dir-fd-probe"
    fd = os.open(str(DATA), os.O_RDONLY)
    try:
        with pytest.raises(pytest.fail.Exception, match="tried to write"):
            os.mkdir(probe, dir_fd=fd)
    finally:
        try:
            if (DATA / probe).exists():                          # the guard failed: leave nothing behind
                os.rmdir(probe, dir_fd=fd)
        finally:
            os.close(fd)
