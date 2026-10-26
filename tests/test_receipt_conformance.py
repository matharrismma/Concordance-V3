"""Conformance: the committed golden receipt validates under the reference verifier a stranger runs,
and any tamper breaks it. This pins the receipt format as a standard and proves the independent check
(docs/verify_receipt.py) actually checks. Regenerate the golden with tools/mint_golden_receipt.py after
any envelope/attestation change.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import pathlib

import pytest

pytest.importorskip("cbor2")
pytest.importorskip("cryptography")

ROOT = pathlib.Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests" / "fixtures" / "receipt_golden.json"

pytestmark = pytest.mark.skipif(not GOLDEN.exists(),
                                reason="run tools/mint_golden_receipt.py to create the golden receipt")


def _verify_receipt():
    """Import docs/verify_receipt.py — the stranger's check, which imports nothing from this repo."""
    spec = importlib.util.spec_from_file_location("verify_receipt", ROOT / "docs" / "verify_receipt.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _golden() -> dict:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_the_receipt_carries_its_format_version():
    assert _golden()["attest"]["envelope"]["spec"] == "concordance-receipt/3.1"


def test_the_hash_checks_with_pure_stdlib():
    ok, why = _verify_receipt().check_hash(_golden())
    assert ok, why


def test_the_signature_checks_under_the_carried_public_key():
    vr, env = _verify_receipt(), _golden()["attest"]["envelope"]
    ok, why, claims = vr.check_signature(env["cose_sign1_b64"], env["public_key"])
    assert ok, why
    assert claims["content_hash"] == _golden()["content_hash"]


def test_a_tampered_record_breaks_the_hash():
    vr, r = _verify_receipt(), _golden()
    r2 = copy.deepcopy(r)
    r2["tampered_field"] = "someone changed the record"   # any change to the covered bytes must show
    ok, _why = vr.check_hash(r2)
    assert not ok


def test_a_tampered_signature_does_not_verify():
    vr, env = _verify_receipt(), _golden()["attest"]["envelope"]
    b64 = env["cose_sign1_b64"]
    bad = b64[:-6] + ("AAAAAA" if not b64.endswith("AAAAAA") else "BBBBBB")
    ok, _why, _claims = vr.check_signature(bad, env["public_key"])
    assert not ok


def test_a_different_key_does_not_verify():
    import concordance.signing as signing  # only to make a wrong key; not what a stranger does
    vr, env = _verify_receipt(), _golden()["attest"]["envelope"]
    other_pub = signing.generate_keypair()[1]
    ok, _why, _claims = vr.check_signature(env["cose_sign1_b64"], other_pub)
    assert not ok


def test_the_scitt_cwt_claims_bind_the_subject():
    """RFC 9597 CWT Claims header: sub = content_hash, iss present — the SCITT signed-statement shape."""
    vr, g = _verify_receipt(), _golden()
    env = g["attest"]["envelope"]
    ok, _why, claims = vr.check_signature(env["cose_sign1_b64"], env["public_key"])
    assert ok and claims["cwt_sub"] == g["content_hash"] and claims["cwt_iss"]


def _ed25519_verify(pub_b64u: str, sig: bytes, msg: bytes) -> bool:
    import base64 as _b
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    raw = _b.urlsafe_b64decode(pub_b64u + "=" * (-len(pub_b64u) % 4))
    try:
        Ed25519PublicKey.from_public_bytes(raw).verify(sig, msg)
        return True
    except (InvalidSignature, ValueError):
        return False


def test_the_in_toto_dsse_envelope_verifies_and_names_the_subject():
    """The in-toto Statement v1 in a DSSE envelope: the signature covers PAE(payloadType, body), the
    Statement's subject digest is the content_hash, and the predicateType is this engine's."""
    import base64
    import json as _json
    g = _golden()
    dsse = g["attest"]["in_toto"]
    assert dsse["payloadType"] == "application/vnd.in-toto+json"
    body = base64.b64decode(dsse["payload"])
    stmt = _json.loads(body)
    assert stmt["_type"] == "https://in-toto.io/Statement/v1"
    assert stmt["subject"][0]["digest"]["sha256"] == g["content_hash"]
    assert stmt["predicateType"].endswith("/verdict/v1")
    pt = dsse["payloadType"].encode()
    pae = b"DSSEv1 " + str(len(pt)).encode() + b" " + pt + b" " + str(len(body)).encode() + b" " + body
    sig = base64.b64decode(dsse["signatures"][0]["sig"])
    assert _ed25519_verify(dsse["public_key"], sig, pae)
    assert not _ed25519_verify(dsse["public_key"], sig, pae + b"x")   # tamper the body → fails


def test_the_post_quantum_signature_verifies_and_is_durable():
    """The ML-DSA-65 (FIPS 204, lattice) signature over the same canonical record bytes — the half that
    survives a quantum adversary. A stranger checks it with cryptography and nothing from this repo."""
    pytest.importorskip("cryptography")
    vr, g = _verify_receipt(), _golden()
    pq = g["attest"]["pq"]
    assert pq["alg"] == "ML-DSA-65"
    ok, why = vr.check_pq_signature(pq, g)
    assert ok, why


def test_a_tampered_post_quantum_signature_does_not_verify():
    vr, g = _verify_receipt(), _golden()
    pq = dict(g["attest"]["pq"])
    s = pq["signature"]
    pq["signature"] = s[:-6] + ("AAAAAA" if not s.endswith("AAAAAA") else "BBBBBB")
    ok, _why = vr.check_pq_signature(pq, g)
    assert not ok


def test_a_tampered_record_fails_the_post_quantum_check():
    vr, g = _verify_receipt(), _golden()
    g2 = copy.deepcopy(g)
    g2["verifier_results"] = []   # change the covered bytes
    ok, _why = vr.check_pq_signature(g2["attest"]["pq"], g2)
    assert not ok
