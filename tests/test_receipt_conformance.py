"""Conformance: the committed golden receipt validates under the reference verifier a stranger runs,
and any tamper breaks it. This pins the receipt format as a standard and proves the independent check
(docs/verify_receipt.py) actually checks. Regenerate the golden with tools/mint_golden_receipt.py after
any envelope/attestation change.
"""
from __future__ import annotations

import builtins
import copy
import importlib.util
import json
import os
import pathlib
import sys
import types

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


def _require_pq():
    """Skip where the installed cryptography cannot do ML-DSA-65 — the package is too old, or (as on
    cryptography 47.0.0 for Windows) the mldsa module imports but its backend does not support it. Under
    GitHub's Linux CI (CI set, sys.platform linux) the backend supports it, so a skip there would hide the
    three tests that must run: it fails instead, and a green CI shows they ran."""
    import concordance.signing as signing  # only to probe the backend; not what a stranger does
    try:
        signing._require_mldsa()
    except ImportError as e:
        if os.environ.get("CI") and sys.platform == "linux":
            pytest.fail(f"ML-DSA-65 not available on GitHub's Linux CI, where these tests must run: {e}")
        pytest.skip(f"ML-DSA-65 not available: {e}")


def test_the_post_quantum_signature_verifies_and_is_durable():
    """The ML-DSA-65 (FIPS 204, lattice) signature over the same canonical record bytes — the half that
    survives a quantum adversary. A stranger checks it with cryptography and nothing from this repo."""
    _require_pq()
    vr, g = _verify_receipt(), _golden()
    pq = g["attest"]["pq"]
    assert pq["alg"] == "ML-DSA-65"
    ok, why = vr.check_pq_signature(pq, g)
    assert ok, why


def test_a_tampered_post_quantum_signature_does_not_verify():
    _require_pq()
    vr, g = _verify_receipt(), _golden()
    pq = dict(g["attest"]["pq"])
    s = pq["signature"]
    pq["signature"] = s[:-6] + ("AAAAAA" if not s.endswith("AAAAAA") else "BBBBBB")
    ok, _why = vr.check_pq_signature(pq, g)
    assert not ok


def test_a_tampered_record_fails_the_post_quantum_check():
    _require_pq()
    vr, g = _verify_receipt(), _golden()
    g2 = copy.deepcopy(g)
    g2["verifier_results"] = []   # change the covered bytes
    ok, _why = vr.check_pq_signature(g2["attest"]["pq"], g2)
    assert not ok


# ── The backend probe, stubbed: these run on any machine, whatever its cryptography can do ────────────────

_ASYM = "cryptography.hazmat.primitives.asymmetric"
_D47D692_MISSING = ("post-quantum (ML-DSA) signing requires a recent `cryptography` package "
                    "(>=45, OpenSSL 3.5+ / its bundled provider). Install with: "
                    "pip install 'concordance[signing]'")   # the missing-package message at d47d692, frozen
_REFUSAL = "ML-DSA-65 is not supported by this backend."     # what cryptography 47.0.0's Windows backend raises


def _stub_mldsa(monkeypatch, generate=None, missing=None):
    """Stand in for `from cryptography.hazmat.primitives.asymmetric import mldsa` inside signing._require_mldsa:
    raise `missing` (the package is absent), or hand back a module whose MLDSA65PrivateKey.generate is
    `generate`. signing's probed-once flag is reset first, so a real probe earlier in the run cannot skip the
    stub's probe. Returns the stub module."""
    import concordance.signing as signing
    monkeypatch.setattr(signing, "_mldsa_probed", False, raising=False)
    mod = types.SimpleNamespace(MLDSA65PrivateKey=types.SimpleNamespace(generate=generate))
    real = builtins.__import__

    def stub(name, globals=None, locals=None, fromlist=(), level=0):
        if name == _ASYM and fromlist and "mldsa" in fromlist:
            if missing is not None:
                raise missing
            return types.SimpleNamespace(mldsa=mod)
        return real(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", stub)
    return mod


def _refusing(monkeypatch):
    """A backend that has the mldsa module and refuses ML-DSA-65; returns the refusal it raises."""
    from cryptography.exceptions import UnsupportedAlgorithm
    refusal = UnsupportedAlgorithm(_REFUSAL)

    def generate():
        raise refusal
    _stub_mldsa(monkeypatch, generate)
    return refusal


def _ending(fn):
    """How fn() ends, read rather than obeyed: ('returned', value), ('skipped', e), ('failed', e) or
    (exception type name, e) — so a skip or a fail raised inside it is seen, not taken as this test's outcome."""
    try:
        return "returned", fn()
    except pytest.skip.Exception as e:
        return "skipped", e
    except pytest.fail.Exception as e:
        return "failed", e
    except Exception as e:  # noqa: BLE001
        return type(e).__name__, e


def test_a_refusing_backend_is_a_clean_not_available_error_with_the_refusal_chained(monkeypatch):
    import concordance.signing as signing
    refusal = _refusing(monkeypatch)
    for _ in range(2):              # a refusal never marks the backend probed: every caller fails the same way
        with pytest.raises(ImportError) as ei:
            signing._require_mldsa()
        msg = str(ei.value)
        assert msg.startswith("post-quantum (ML-DSA) signing is not available: "), msg
        assert "does not support ML-DSA-65" in msg and _REFUSAL in msg, msg   # the backend's own reason
        assert "pip install" not in msg, msg     # the package is installed: installing it is not the remedy
        assert ei.value.__cause__ is refusal


def test_a_supported_backend_probes_once_and_returns_the_module(monkeypatch):
    import concordance.signing as signing
    calls = []
    mod = _stub_mldsa(monkeypatch, lambda: calls.append(1))
    assert signing._require_mldsa() is mod
    assert signing._require_mldsa() is mod
    assert len(calls) == 1


def test_a_missing_package_keeps_the_d47d692_message(monkeypatch):
    import concordance.signing as signing
    gone = ImportError(f"No module named '{_ASYM}.mldsa'")
    _stub_mldsa(monkeypatch, missing=gone)
    with pytest.raises(ImportError) as ei:
        signing._require_mldsa()
    assert str(ei.value) == _D47D692_MISSING
    assert ei.value.__cause__ is gone


def test_any_other_probe_error_propagates_and_is_never_a_skip(monkeypatch):
    import concordance.signing as signing
    boom = RuntimeError("the backend broke some other way")

    def generate():
        raise boom
    _stub_mldsa(monkeypatch, generate)
    with pytest.raises(RuntimeError) as ei:
        signing._require_mldsa()
    assert ei.value is boom
    kind, e = _ending(_require_pq)
    assert kind == "RuntimeError" and e is boom, (kind, e)    # the guard neither skips it nor recasts it


def test_on_githubs_linux_ci_an_unavailable_backend_fails_instead_of_skipping(monkeypatch):
    _refusing(monkeypatch)
    with monkeypatch.context() as m:
        m.setenv("CI", "true")
        m.setattr(sys, "platform", "linux")
        kind, e = _ending(_require_pq)
    assert kind == "failed", (kind, e)
    assert "ML-DSA-65 not available" in str(e) and "does not support ML-DSA-65" in str(e), str(e)


def test_off_ci_an_unavailable_backend_skips_with_the_not_available_reason(monkeypatch):
    _refusing(monkeypatch)
    with monkeypatch.context() as m:
        m.delenv("CI", raising=False)          # GitHub sets CI=true: unset, so this reads off-CI everywhere
        m.setattr(sys, "platform", "linux")    # and Linux, so the skip comes from CI being unset, not from Windows
        kind, e = _ending(_require_pq)
    assert kind == "skipped", (kind, e)
    assert str(e).startswith("ML-DSA-65 not available: post-quantum (ML-DSA) signing is not available: "), str(e)
    assert "does not support ML-DSA-65" in str(e) and _REFUSAL in str(e), str(e)
