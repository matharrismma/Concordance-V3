"""Receipt envelopes: in-toto statement subject = SHA-256 of the sealed record; DSSE signatures verify; a
tampered payload fails; a record that does not hash to its claimed hash is refused."""
import json, base64
import pytest
from concordance import envelope
from concordance.config import EngineConfig
from concordance.mcp.server import _call_tool


def _seal():
    r = _call_tool("verify", {"steps": [{"id": "m", "domain": "real_estate", "spec": {"RE_VERIFY": {
        "loan_principal": 12_000_000, "annual_rate": 0.045, "loan_term_months": 240,
        "claimed_monthly_payment": 75917.93}}}]}, EngineConfig())
    return r["seal"]["content_hash"]


def test_statement_subject_is_the_record_hash():
    h = _seal()
    st = envelope.statement(h, engine_version="test")
    assert st["subject"][0]["digest"]["sha256"] == h
    assert st["predicate"]["verdict"] == "PASS" and st["predicate"]["domain"] == "real_estate"
    assert st["predicate"]["checks"] >= 1


def test_statement_refuses_a_record_that_does_not_hash():
    h = _seal()
    from concordance import cas
    rec = dict(cas.fetch(h)); rec["anchors"] = ["tampered"]
    with pytest.raises(ValueError):
        envelope.statement(h, record=rec)


def test_dsse_signs_and_verifies_and_detects_tampering():
    pytest.importorskip("cryptography")
    from concordance import signing
    h = _seal()
    priv, pub = signing.generate_keypair()
    env = envelope.dsse(envelope.statement(h), priv)
    v = envelope.verify_dsse(env)
    assert v["well_formed"] and v["signatures"] == [{"keyid": pub, "ok": True}]
    payload = json.loads(base64.b64decode(env["payload"]))
    payload["predicate"]["verdict"] = "FAIL"
    env["payload"] = base64.b64encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).decode()
    assert envelope.verify_dsse(env)["signatures"][0]["ok"] is False


def test_unsigned_envelope_says_so():
    env = envelope.dsse(envelope.statement(_seal()))
    assert env["signatures"] == [] and "unsigned" in env["note"]


def test_scitt_receipt_mirrors_the_hash_and_disclaims_correctness():
    h = _seal()
    rc = envelope.scitt_receipt(h, prev_hash="0" * 64)
    assert rc["artifact"]["sha256"] == h and rc["prev"] == "0" * 64
    assert "does not claim the agent" in rc["note"]
