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
