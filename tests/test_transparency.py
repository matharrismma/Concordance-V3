"""Transparency layer: COSE_Sign1 envelopes, the independent reference verifier, seal_fetch wiring.

Rekor itself is not hit here (network); the publish path is exercised against a stub, and the live
proof is recorded in MEASURED.md.
"""
from __future__ import annotations

import base64
import importlib.util
import json
import pathlib
import subprocess
import sys
import types

import pytest

pytest.importorskip("cbor2")
pytest.importorskip("cryptography")

from concordance import cas, signing, transparency as T  # noqa: E402
from concordance.config import EngineConfig  # noqa: E402
from concordance.mcp import server as S  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
STEP = {"id": "m", "domain": "real_estate", "spec": {"RE_VERIFY": {
    "loan_principal": 12_000_000, "annual_rate": 0.045, "loan_term_months": 240, "claimed_monthly_payment": 75917.93}}}


@pytest.fixture
def issuer(monkeypatch, tmp_path):
    priv, pub = signing.generate_keypair()
    monkeypatch.setenv("CONCORDANCE_ISSUER_KEY", priv)
    monkeypatch.delenv("CONCORDANCE_PUBLISH", raising=False)
    monkeypatch.setenv("CONCORDANCE_DATA_DIR", str(tmp_path))
    return priv, pub


def _seal(config=None):
    r = S._call_tool("verify", {"steps": [STEP]}, config or EngineConfig())
    assert r["verdict"] == "HOLDS"
    return r["seal"]["content_hash"]


def test_envelope_round_trip_and_wrong_key(issuer):
    _, pub = issuer
    h = _seal()
    env = T.envelope(cas.fetch(h))
    assert env["content_hash"] == h and env["kid"].startswith("ed25519:")
    v = T.verify_envelope(env["cose_sign1_b64"], pub)
    assert v["signature_ok"] and v["hash_matches_header"]
    assert v["claims"] == {"content_hash": h, "kind": "seal", "verdict": "PASS"}
    assert "content_hash" not in v["record"] and v["payload_hash"] == h  # payload is the record minus its hash
    other = signing.generate_keypair()[1]
    assert T.verify_envelope(env["cose_sign1_b64"], other)["signature_ok"] is False


def test_envelope_is_standard_cose_sign1(issuer):
    import cbor2
    h = _seal()
    env = T.envelope(cas.fetch(h))
    tagged = cbor2.loads(base64.b64decode(env["cose_sign1_b64"]))
    assert tagged.tag == 18
    protected, unprotected, payload, sig = list(tagged.value)
    hdr = cbor2.loads(protected)
    assert hdr[1] == -8 and hdr[3] == T.CONTENT_TYPE and len(sig) == 64
    assert (json.loads(payload).get("overall") or json.loads(payload).get("verdict")) == "PASS"


def test_no_issuer_key_means_self_attested(monkeypatch, tmp_path):
    monkeypatch.delenv("CONCORDANCE_ISSUER_KEY", raising=False)
    monkeypatch.setenv("CONCORDANCE_DATA_DIR", str(tmp_path))
    h = _seal()
    assert T.envelope(cas.fetch(h)) is None
    assert T.status()["issuer_key_configured"] is False
    fetched = S._call_tool("seal_fetch", {"hash": h}, EngineConfig())
    assert "attest" not in fetched and fetched["content_hash"] == h


def test_seal_fetch_carries_attest_beside_an_intact_record(issuer):
    h = _seal()
    fetched = S._call_tool("seal_fetch", {"hash": h}, EngineConfig())
    att = fetched["attest"]
    assert att["envelope"]["content_hash"] == h
    assert att["log"]["pending"] is True  # CONCORDANCE_PUBLISH unset
    rec = {k: v for k, v in fetched.items() if k != "attest"}
    assert T._record_bytes(rec)[1] == h  # the record itself is untouched
    # idempotent: second fetch reads the sidecar
    assert S._call_tool("seal_fetch", {"hash": h}, EngineConfig())["attest"]["envelope"] == att["envelope"]


def _clock(monkeypatch, start):
    """Fix the clock transparency reads (time.time(), the envelope's iat); returns its setter."""
    now = [start]
    monkeypatch.setattr(T, "time", types.SimpleNamespace(time=lambda: now[0]))
    return now


def _iat(env):
    import cbor2
    protected = cbor2.loads(base64.b64decode(env["cose_sign1_b64"])).value[0]
    return cbor2.loads(protected)[T.CWT_CLAIMS][T.CWT_IAT]


def test_a_pending_envelope_is_minted_once_across_a_second_boundary(issuer, monkeypatch):
    """The contract above, with the clock held: two fetches that straddle a second boundary return the
    envelope saved at the first, so the second cannot differ in the protected header's iat."""
    h = _seal()
    now = _clock(monkeypatch, 1_800_000_000.999)
    first = S._call_tool("seal_fetch", {"hash": h}, EngineConfig())["attest"]
    assert first["log"]["pending"] is True
    now[0] = 1_800_000_001.0
    second = S._call_tool("seal_fetch", {"hash": h}, EngineConfig())["attest"]
    assert second["envelope"] == first["envelope"]          # the saved statement, not a re-signed one
    assert _iat(second["envelope"]) == 1_800_000_000        # issued at the first fetch
    assert {k: v for k, v in second.items() if k != "agentledger"} == \
        {k: v for k, v in first.items() if k != "agentledger"}
    # the AgentLedger view carries the record's own COSE_Sign1 (RECEIPT_SPEC §2c): the saved one
    assert second["agentledger"]["signature"]["cose_sign1_b64"] == first["envelope"]["cose_sign1_b64"]


def _publish_seals():
    spec = importlib.util.spec_from_file_location("publish_seals", ROOT / "tools" / "publish_seals.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_retry_of_a_pending_seal_publishes_the_saved_statement(issuer, monkeypatch):
    """tools/publish_seals.py retries a pending entry with attest(h, publish_log=True). Each retry posts
    the statement saved at the first fetch: never a fresh one, and never skipped because a sidecar exists."""
    h = _seal()
    now = _clock(monkeypatch, 1_800_000_000.999)
    saved = S._call_tool("seal_fetch", {"hash": h}, EngineConfig())["attest"]["envelope"]
    now[0] = 1_800_000_001.0
    posts = []
    replies = [(503, {"error": "unavailable"}),
               (201, {"u1": {"logIndex": 9, "integratedTime": 2, "logID": "x", "verification": {
                   "inclusionProof": {"hashes": [], "rootHash": "r", "treeSize": 1, "logIndex": 0}}}})]

    def fake_post(url, body, timeout=20.0):
        posts.append(base64.b64decode(body["spec"]["data"]["content"]))
        return replies[len(posts) - 1]

    monkeypatch.setattr(T, "_post", fake_post)
    monkeypatch.setattr(sys, "argv", ["publish_seals.py", "--hash", h])
    tool = _publish_seals()
    assert tool.main() == 2                                  # the log is down: still pending
    assert T._sidecar(h)["envelope"] == saved and T._sidecar(h)["log"]["pending"] is True
    assert tool.main() == 0                                  # retried: published
    assert posts == [base64.b64decode(saved["cose_sign1_b64"])] * 2
    side = T._sidecar(h)
    assert side["envelope"] == saved and side["log"]["index"] == 9 and not side["log"].get("pending")
    assert tool.main() == 0 and len(posts) == 2              # logged: skipped, nothing re-posted


def test_a_new_issuer_key_signs_a_pending_seal_afresh(issuer, monkeypatch):
    """The saved envelope is reused only under the key that signed it: after a key change a pending seal
    is signed under the new key, so the statement and the log entry (signed with the current key) agree."""
    h = _seal()
    old = T.attest(h)["envelope"]
    priv2, pub2 = signing.generate_keypair()
    monkeypatch.setenv("CONCORDANCE_ISSUER_KEY", priv2)
    new = T.attest(h)["envelope"]
    assert new["kid"] != old["kid"] and new["kid"] == T.issuer_kid()
    assert T.verify_envelope(new["cose_sign1_b64"], pub2)["signature_ok"] is True
    assert T._sidecar(h)["envelope"] == new


def test_publish_builds_a_rekord_entry_and_handles_409(issuer, monkeypatch):
    h = _seal()
    env = T.envelope(cas.fetch(h))
    posted = {}

    def fake_post(url, body, timeout=20.0):
        posted.update(body)
        return 409, {"Location": f"{T.REKOR}/api/v1/log/entries/abc123"}

    def fake_get(url, timeout=20.0):
        assert url.endswith("/abc123")
        return 200, {"abc123": {"logIndex": 7, "integratedTime": 1, "logID": "x", "body": "e30=",
                                "verification": {"inclusionProof": {"hashes": ["00"], "rootHash": "r", "treeSize": 2, "logIndex": 0}}}}

    monkeypatch.setattr(T, "_post", fake_post)
    monkeypatch.setattr(T, "_get", fake_get)
    log = T.publish(h, statement_b64=env["cose_sign1_b64"])
    assert posted["kind"] == "rekord" and posted["spec"]["signature"]["format"] == "x509"
    assert base64.b64decode(posted["spec"]["data"]["content"]) == base64.b64decode(env["cose_sign1_b64"])
    # Rekor would verify this signature on admission; so do we
    sig = base64.b64decode(posted["spec"]["signature"]["content"])
    assert signing.verify_bytes(base64.b64decode(env["cose_sign1_b64"]), signing._b64u_encode(sig), issuer[1])
    assert log["uuid"] == "abc123" and log["index"] == 7 and not log.get("pending")


def test_reference_verifier_is_independent_and_catches_tampering(issuer, tmp_path):
    h = _seal()
    fetched = S._call_tool("seal_fetch", {"hash": h}, EngineConfig())
    script = ROOT / "docs" / "verify_receipt.py"
    assert "concordance" not in script.read_text().replace("Concordance", "").replace("concordance.", "")  # no import
    good = tmp_path / "good.json"
    good.write_text(json.dumps(fetched))
    r = subprocess.run([sys.executable, "-I", str(script), str(good), "--offline"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "HASH       ok" in r.stdout and "SIGNATURE  ok" in r.stdout and "LOG        —" in r.stdout
    bad = dict(fetched)
    bad["verdict"] = "BROKEN"
    (tmp_path / "bad.json").write_text(json.dumps(bad))
    r = subprocess.run([sys.executable, "-I", str(script), str(tmp_path / "bad.json"), "--offline"], capture_output=True, text=True)
    assert r.returncode == 1 and "HASH       FAIL" in r.stdout


def test_reference_verifier_inclusion_proof_math():
    """A 4-leaf tree built by hand (RFC 6962) — the verifier must reproduce its root from a proof."""
    import hashlib
    import importlib.util
    spec = importlib.util.spec_from_file_location("vr", ROOT / "docs" / "verify_receipt.py")
    vr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vr)
    bodies = [base64.b64encode(json.dumps({"i": i}).encode()).decode() for i in range(4)]
    leaf = [hashlib.sha256(b"\x00" + base64.b64decode(b)).digest() for b in bodies]
    n = lambda a, b: hashlib.sha256(b"\x01" + a + b).digest()  # noqa: E731
    root = n(n(leaf[0], leaf[1]), n(leaf[2], leaf[3]))
    entry = {"body": bodies[2], "verification": {"inclusionProof": {
        "logIndex": 2, "treeSize": 4, "rootHash": root.hex(), "hashes": [leaf[3].hex(), n(leaf[0], leaf[1]).hex()]}}}
    ok, why = vr.check_inclusion(entry)
    assert ok, why
    entry["verification"]["inclusionProof"]["rootHash"] = "00" * 32
    assert vr.check_inclusion(entry)[0] is False


def test_document_root_gets_an_envelope_too(issuer):
    from concordance import compose
    doc = {"title": "t", "steps": [STEP]}
    out = compose.seal_document(doc, EngineConfig())
    fetched = S._call_tool("seal_fetch", {"hash": out["root"]}, EngineConfig())
    assert fetched["attest"]["envelope"]["content_hash"] == out["root"]
    v = T.verify_envelope(fetched["attest"]["envelope"]["cose_sign1_b64"], issuer[1])
    assert v["claims"]["kind"] == "document" and v["signature_ok"]
