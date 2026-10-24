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
    assert _golden()["attest"]["envelope"]["spec"] == "concordance-receipt/3.0"


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
