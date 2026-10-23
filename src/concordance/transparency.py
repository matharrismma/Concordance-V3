"""transparency — a receipt that outlives this server.

T1 ENVELOPE: every sealed record can be wrapped as a COSE_Sign1 signed statement (the SCITT shape):
    payload  = the canonical JSON bytes of the record (SHA-256 of these bytes IS the content_hash)
    protected header = {alg: EdDSA, kid: <issuer key id>, content-type: application/concordance-record+json,
                        "concordance": {"content_hash": ..., "kind": "seal"|"document", "verdict": ...}}
    signature = Ed25519 over the COSE Sig_structure, with the engine's issuer key.
Anyone with pycose (or any COSE library) and the issuer's public key verifies it without this code.

T2 LOG: the statement's hash is registered on a public transparency log (Sigstore's Rekor, as a
`hashedrekord`: SHA-256 digest + signature + public key). The log answers with the entry's index, its
integrated time, and a Merkle inclusion proof against a signed tree head. The seal gains
    log = {"service": "rekor", "index": ..., "uuid": ..., "integrated_time": ..., "inclusion_proof": {...}}
and `rekor-cli verify --rekor-server https://rekor.sigstore.dev --uuid <uuid>` confirms it from anywhere.

Issuer key: CONCORDANCE_ISSUER_KEY (base64url Ed25519 private key; `generate_keypair()` makes one). Without
it, envelopes are not minted and the engine says so in `transparency.status()` — never a silent omission.
Publication is opt-in per call (`publish=True`) or by CONCORDANCE_PUBLISH=1; a failed publish records
`log: {"service": "rekor", "pending": true, "error": ...}` so a later flush (tools/publish_seals.py) can retry.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

from . import cas, signing
from .validate import canonical_json_bytes, sha256_bytes

REKOR = os.environ.get("CONCORDANCE_REKOR_URL", "https://rekor.sigstore.dev").rstrip("/")
CONTENT_TYPE = "application/concordance-record+json"


# ── keys ──────────────────────────────────────────────────────────────────────────────────────────
def issuer_private_key() -> Optional[str]:
    k = os.environ.get("CONCORDANCE_ISSUER_KEY", "").strip()
    return k or None


def issuer_public_key() -> Optional[str]:
    k = issuer_private_key()
    return signing.public_from_private(k) if k else None


def issuer_kid() -> Optional[str]:
    pub = issuer_public_key()
    return ("ed25519:" + hashlib.sha256(signing._b64u_decode(pub)).hexdigest()[:16]) if pub else None


def public_key_pem() -> Optional[str]:
    """The issuer public key as PKIX PEM — what the Rekor entry carries, what rekor-cli verifies."""
    pub = issuer_public_key()
    if not pub:
        return None
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    key = Ed25519PublicKey.from_public_bytes(signing._b64u_decode(pub))
    return key.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()


# ── T1: the COSE_Sign1 envelope ───────────────────────────────────────────────────────────────────
def _record_bytes(record: Dict[str, Any]) -> Tuple[bytes, str]:
    rec = {k: v for k, v in record.items() if k != "content_hash"}
    b = canonical_json_bytes(rec)
    return b, sha256_bytes(b)


# COSE_Sign1 (RFC 9052 §4.2), written out so the only dependencies are cbor2 and cryptography — the same
# two the reference verifier needs. Header labels: 1 alg (-8 = EdDSA), 3 content type, 4 kid; the
# concordance claim set rides under the private-use label -70001 as a CBOR map.
ALG_EDDSA = -8
LABEL_CLAIMS = -70001


def _sig_structure(protected: bytes, payload: bytes) -> bytes:
    import cbor2
    return cbor2.dumps(["Signature1", protected, b"", payload])


def envelope(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Wrap a sealed record as a COSE_Sign1 statement. Returns {cose_sign1_b64, content_hash, kid,
    public_key} or None when no issuer key is configured."""
    priv = issuer_private_key()
    if not priv:
        return None
    import cbor2
    payload, content_hash = _record_bytes(record)
    if record.get("content_hash") and record["content_hash"] != content_hash:
        raise ValueError("record does not re-hash to its content_hash; refusing to sign a mismatched record")
    kind = "document" if record.get("kind") == "document" else "seal"
    verdict = record.get("verdict") or record.get("overall")
    protected = cbor2.dumps({1: ALG_EDDSA, 3: CONTENT_TYPE, 4: issuer_kid().encode(),
                             LABEL_CLAIMS: {"content_hash": content_hash, "kind": kind, "verdict": verdict}})
    sig = signing._b64u_decode(signing.sign_bytes(_sig_structure(protected, payload), priv))
    encoded = cbor2.dumps(cbor2.CBORTag(18, [protected, {}, payload, sig]))
    return {"format": "COSE_Sign1", "cose_sign1_b64": base64.b64encode(encoded).decode(),
            "content_hash": content_hash, "kid": issuer_kid(), "public_key": signing.public_from_private(priv),
            "means": "payload = canonical record bytes (SHA-256 = content_hash); protected header: alg EdDSA (-8), "
                     "content type, kid, and the concordance claim set under label -70001; verify with any COSE "
                     "library or docs/verify_receipt.py"}


def verify_envelope(cose_sign1_b64: str, public_key_b64u: str) -> Dict[str, Any]:
    """Verify a statement with only the public key: signature, and that the payload re-hashes to the
    content_hash the header claims. Independent of the CAS."""
    import cbor2
    raw = base64.b64decode(cose_sign1_b64)
    tagged = cbor2.loads(raw)
    if getattr(tagged, "tag", None) != 18:
        return {"signature_ok": False, "error": "not a COSE_Sign1 (tag 18)"}
    protected, _unprotected, payload, sig = list(tagged.value)
    hdr = cbor2.loads(protected)
    if hdr.get(1) != ALG_EDDSA:
        return {"signature_ok": False, "error": f"unexpected alg {hdr.get(1)}"}
    ok = signing.verify_bytes(_sig_structure(protected, payload), signing._b64u_encode(sig), public_key_b64u)
    claims = dict(hdr.get(LABEL_CLAIMS) or {})
    payload_hash = sha256_bytes(payload)
    return {"signature_ok": bool(ok), "payload_hash": payload_hash,
            "hash_matches_header": payload_hash == claims.get("content_hash"), "claims": claims,
            "kid": (hdr.get(4) or b"").decode(errors="replace"),
            "record": json.loads(payload.decode("utf-8")) if ok else None}


# ── T2: the public log ────────────────────────────────────────────────────────────────────────────
def _post(url: str, body: Dict[str, Any], timeout: float = 20.0) -> Tuple[int, Any]:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode() or "{}")
        except Exception:  # noqa: BLE001
            payload = {"error": str(e)}
        if isinstance(payload, dict) and e.headers.get("Location"):
            payload["Location"] = e.headers.get("Location")
        return e.code, payload


def _get(url: str, timeout: float = 20.0) -> Tuple[int, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, {"error": str(e)}


def publish(content_hash: str, *, statement_b64: Optional[str] = None) -> Dict[str, Any]:
    """Register the receipt on Rekor as a `rekord` entry: the artifact IS the signed statement bytes
    (COSE_Sign1; or the canonical record when no envelope exists), with the issuer's pure-Ed25519
    signature over those bytes and the issuer public key (PKIX PEM). Rekor re-verifies the signature
    before admitting the entry, so a logged entry is itself a check. (hashedrekord is not used: Rekor
    only admits Ed25519 there in its pre-hashed SHA-512 form.) Never raises: a failure is a pending claim."""
    priv = issuer_private_key()
    if not priv:
        return {"service": "rekor", "pending": True, "error": "no CONCORDANCE_ISSUER_KEY configured"}
    if statement_b64:
        artifact = base64.b64decode(statement_b64)
    else:
        rec = cas.fetch(content_hash)
        if rec is None:
            return {"service": "rekor", "pending": True, "error": "record not held"}
        artifact, _ = _record_bytes(rec)
    digest = hashlib.sha256(artifact).hexdigest()
    sig_b64 = base64.b64encode(signing._b64u_decode(signing.sign_bytes(artifact, priv))).decode()
    pem_b64 = base64.b64encode(public_key_pem().encode()).decode()
    body = {"apiVersion": "0.0.1", "kind": "rekord", "spec": {
        "data": {"content": base64.b64encode(artifact).decode()},
        "signature": {"format": "x509", "content": sig_b64, "publicKey": {"content": pem_b64}}}}
    status, resp = _post(f"{REKOR}/api/v1/log/entries", body)
    if status == 409:
        # already logged: the response carries the existing entry's location
        loc = (resp.get("Location") or "") if isinstance(resp, dict) else ""
        uuid = loc.rsplit("/", 1)[-1] if loc else None
        if uuid:
            status, resp = _get(f"{REKOR}/api/v1/log/entries/{uuid}")
    if status not in (200, 201) or not isinstance(resp, dict) or not resp:
        return {"service": "rekor", "pending": True, "error": f"HTTP {status}: {str(resp)[:200]}", "digest": digest}
    uuid, entry = next(iter(resp.items()))
    ver = entry.get("verification") or {}
    return {"service": "rekor", "kind": "rekord", "url": REKOR, "uuid": uuid, "index": entry.get("logIndex"),
            "integrated_time": entry.get("integratedTime"), "log_id": entry.get("logID"),
            "digest": digest, "inclusion_proof": ver.get("inclusionProof"),
            "signed_entry_timestamp": ver.get("signedEntryTimestamp"),
            "verify": f"rekor-cli get --rekor_server {REKOR} --uuid {uuid}",
            "means": "the log entry holds the statement bytes (sha256 = digest), the issuer signature over them and "
                     "the issuer public key; Rekor verified the signature on admission; the inclusion proof ties the "
                     "entry to a signed tree head anyone can audit"}


def lookup(uuid: str) -> Dict[str, Any]:
    status, resp = _get(f"{REKOR}/api/v1/log/entries/{uuid}")
    return {"status": status, "entry": resp}


# ── attach to a seal ──────────────────────────────────────────────────────────────────────────────
def attest(content_hash: str, *, publish_log: Optional[bool] = None) -> Dict[str, Any]:
    """Envelope (+ log) for a held record. Idempotent; stores the envelope and log claim beside the record
    as sidecars (data/cas/attest/<hash>.json) so seal_fetch can return them."""
    rec = cas.fetch(content_hash)
    if rec is None:
        return {"error": "seal not found"}
    side = _sidecar(content_hash)
    if side and side.get("log") and not side["log"].get("pending"):
        return side
    env = envelope(rec)
    out: Dict[str, Any] = {"content_hash": content_hash, "envelope": env}
    want = (os.environ.get("CONCORDANCE_PUBLISH", "").strip() in ("1", "true", "yes")) if publish_log is None else publish_log
    if env and want:
        out["log"] = publish(content_hash, statement_b64=env["cose_sign1_b64"])
    elif env:
        out["log"] = {"service": "rekor", "pending": True, "error": "publication not requested"}
    else:
        out["log"] = {"service": "rekor", "pending": True, "error": "no issuer key; no envelope to log"}
    _write_sidecar(content_hash, out)
    return out


def status() -> Dict[str, Any]:
    return {"issuer_key_configured": bool(issuer_private_key()), "kid": issuer_kid(),
            "public_key": issuer_public_key(), "rekor": REKOR,
            "publish_by_default": os.environ.get("CONCORDANCE_PUBLISH", "").strip() in ("1", "true", "yes"),
            "means": "without an issuer key no envelopes are minted and no entries are logged; the seal is then "
                     "self-attested (content-addressed only) and says so"}


def _sidecar_path(content_hash: str):
    d = cas._cas_dir() / "attest"
    d.mkdir(parents=True, exist_ok=True)
    return d / (content_hash + ".json")


def _sidecar(content_hash: str) -> Optional[Dict[str, Any]]:
    p = _sidecar_path(content_hash)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
    return None


def _write_sidecar(content_hash: str, data: Dict[str, Any]) -> None:
    try:
        _sidecar_path(content_hash).write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
    except OSError:
        pass


__all__ = ["envelope", "verify_envelope", "publish", "lookup", "attest", "status", "issuer_public_key",
           "public_key_pem", "issuer_kid"]
