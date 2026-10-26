"""transparency — a receipt that outlives this server.

T1 ENVELOPE: every sealed record can be wrapped as a COSE_Sign1 signed statement (the SCITT shape):
    payload  = the canonical JSON bytes of the record (SHA-256 of these bytes IS the content_hash)
    protected header = {alg: EdDSA, kid: <issuer key id>, content-type: application/concordance-record+json,
                        "concordance": {"content_hash": ..., "kind": "seal"|"document", "verdict": ...}}
    signature = Ed25519 over the COSE Sig_structure, with the engine's issuer key.
Anyone with pycose (or any COSE library) and the issuer's public key verifies it without this code.

T2 LOG: the signed statement is registered on a public transparency log (Sigstore's Rekor, as a
`rekord`: the statement bytes are the artifact and Rekor verifies the signature before admitting, so a
logged entry is itself a check (`hashedrekord` is not used — see publish()). The log answers with the entry's index, its
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
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

from . import cas, signing
from .validate import canonical_json_bytes, sha256_bytes

REKOR = os.environ.get("CONCORDANCE_REKOR_URL", "https://rekor.sigstore.dev").rstrip("/")
CONTENT_TYPE = "application/concordance-record+json"
# The receipt-format version, carried in the attestation (unhashed) so a consumer knows which rules
# apply (RECEIPT_SPEC.md). Bump on any change to the envelope/attestation shape; the record's own
# content_hash is unaffected — SEAL_SPEC.md: a record hashes the same with or without attestation.
SPEC_VERSION = "concordance-receipt/3.1"   # 3.1: optional post-quantum signature (attest.pq), additive


# ── keys ──────────────────────────────────────────────────────────────────────────────────────────
def issuer_private_key() -> Optional[str]:
    k = os.environ.get("CONCORDANCE_ISSUER_KEY", "").strip()
    return k or None


def pq_issuer_private_key() -> Optional[str]:
    """The ML-DSA-65 issuer seed (b64u). Independent of the Ed25519 key — a receipt can carry one,
    both, or neither; both is the durable path (Ed25519 for today's tooling, ML-DSA for permanence)."""
    k = os.environ.get("CONCORDANCE_PQ_ISSUER_KEY", "").strip()
    return k or None


def pq_issuer_public_key() -> Optional[str]:
    k = pq_issuer_private_key()
    return signing.pq_public_from_seed(k) if k else None


def pq_issuer_kid() -> Optional[str]:
    pub = pq_issuer_public_key()
    return ("ml-dsa-65:" + hashlib.sha256(signing._b64u_decode(pub)).hexdigest()[:16]) if pub else None


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
# SCITT signed-statement conformance: the CWT Claims header (RFC 9597, COSE header label 15) carries
# registered CWT claims (RFC 8392) — iss (1) = issuer kid, sub (2) = content_hash (the subject),
# iat (6) = issuance time. Protected-header only (RFC 9597 §5, to avoid malleability). The richer
# concordance claim set stays under the private-use label above, beside it.
CWT_CLAIMS, CWT_ISS, CWT_SUB, CWT_IAT = 15, 1, 2, 6
# The same verdict, also emitted as an in-toto Statement v1 in a DSSE envelope (for SLSA / in-toto
# consumers). The predicateType is this engine's own, versioned.
PREDICATE_TYPE = "https://github.com/matharrismma/Concordance-V3/attestations/verdict/v1"
DSSE_PAYLOAD_TYPE = "application/vnd.in-toto+json"


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
                             CWT_CLAIMS: {CWT_ISS: issuer_kid(), CWT_SUB: content_hash, CWT_IAT: int(time.time())},
                             LABEL_CLAIMS: {"content_hash": content_hash, "kind": kind, "verdict": verdict}})
    sig = signing._b64u_decode(signing.sign_bytes(_sig_structure(protected, payload), priv))
    encoded = cbor2.dumps(cbor2.CBORTag(18, [protected, {}, payload, sig]))
    return {"format": "COSE_Sign1", "spec": SPEC_VERSION, "cose_sign1_b64": base64.b64encode(encoded).decode(),
            "content_hash": content_hash, "kid": issuer_kid(), "public_key": signing.public_from_private(priv),
            "means": "payload = canonical record bytes (SHA-256 = content_hash); protected header: alg EdDSA (-8), "
                     "content type, kid, the CWT Claims header (15: iss, sub = content_hash, iat — the SCITT "
                     "signed-statement shape), and the concordance claim set under label -70001; verify with any "
                     "COSE library or docs/verify_receipt.py"}


def pq_envelope(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """A post-quantum signature beside the COSE envelope: ML-DSA-65 (FIPS 204) over the SAME canonical
    record bytes the Ed25519 statement signs, so it binds the same `content_hash`. A self-describing
    block (not COSE-wrapped — the RFC 9964 COSE encoding of ML-DSA is the standards path once its alg
    ids are pinned). Returns None when no PQ issuer key is set.

    This is the durable half of the receipt: Ed25519 rests on a problem quantum computers break, so a
    receipt meant to prove something permanently carries a lattice (Regev/LWE) signature whose hardness
    survives that transition. Verification needs only the ML-DSA public key.
    """
    seed = pq_issuer_private_key()
    if not seed:
        return None
    payload, content_hash = _record_bytes(record)
    if record.get("content_hash") and record["content_hash"] != content_hash:
        raise ValueError("record does not re-hash to its content_hash; refusing to sign a mismatched record")
    return {"format": "pq-detached", "alg": signing.PQ_ALG, "spec": SPEC_VERSION,
            "signature": signing.pq_sign_bytes(payload, seed), "content_hash": content_hash,
            "kid": pq_issuer_kid(), "public_key": pq_issuer_public_key(),
            "means": "ML-DSA-65 (FIPS 204, module-lattice) over the canonical record bytes "
                     "(SHA-256 = content_hash). Verify: check the signature under the ML-DSA public key, "
                     "then that sha256(payload) equals content_hash. Durable against the quantum attack "
                     "that breaks the Ed25519 statement; carry both during the transition."}


def in_toto_statement(record: Dict[str, Any]) -> Dict[str, Any]:
    """The record as an in-toto Statement v1 (https://in-toto.io/Statement/v1): the subject is the
    content-addressed record, the predicate is the verdict. Deterministic and key-independent — the
    same record always yields the same Statement."""
    _payload, content_hash = _record_bytes(record)
    kind = "document" if record.get("kind") == "document" else "seal"
    verdict = record.get("verdict") or record.get("overall")
    return {"_type": "https://in-toto.io/Statement/v1",
            "subject": [{"name": f"concordance:{kind}:{content_hash}", "digest": {"sha256": content_hash}}],
            "predicateType": PREDICATE_TYPE,
            "predicate": {"verdict": verdict, "kind": kind, "content_hash": content_hash, "spec": SPEC_VERSION}}


def _dsse_pae(payload_type: str, body: bytes) -> bytes:
    """DSSE Pre-Authentication Encoding (secure-systems-lab/dsse): binds the payload type into the
    signed bytes, so a signature minted for one type cannot be replayed as another (CVE-2022-35929)."""
    pt = payload_type.encode()
    return b"DSSEv1 " + str(len(pt)).encode() + b" " + pt + b" " + str(len(body)).encode() + b" " + body


def dsse_envelope(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The in-toto Statement in a DSSE envelope, signed with the issuer key; None when no key is set.
    The signature is Ed25519 over PAE(payloadType, statement bytes)."""
    priv = issuer_private_key()
    if not priv:
        return None
    body = canonical_json_bytes(in_toto_statement(record))
    sig_raw = signing._b64u_decode(signing.sign_bytes(_dsse_pae(DSSE_PAYLOAD_TYPE, body), priv))
    return {"payloadType": DSSE_PAYLOAD_TYPE, "payload": base64.b64encode(body).decode(),
            "signatures": [{"keyid": issuer_kid(), "sig": base64.b64encode(sig_raw).decode()}],
            "public_key": signing.public_from_private(priv),
            "means": "DSSE: verify Ed25519 over PAE(payloadType, base64-decoded payload); the payload is an "
                     "in-toto Statement v1 whose subject.digest.sha256 is the content_hash"}


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
    out: Dict[str, Any] = {"content_hash": content_hash, "envelope": env, "in_toto": dsse_envelope(rec),
                           "pq": pq_envelope(rec)}
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
            "pq_key_configured": bool(pq_issuer_private_key()), "pq_alg": signing.PQ_ALG,
            "pq_kid": pq_issuer_kid(),
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


AGENTLEDGER_SPEC = "draft-dembowski-agentledger-proof-of-behavior-00"


def _payload_hash(record: Dict[str, Any]) -> Optional[str]:
    """The hash of the verified input(s): the one `spec_hash` the record bound, or a SHA-256 over the
    sorted set when a document bound several. None when the record carries no input hash."""
    import hashlib
    hashes: list = []
    for vr in record.get("verifier_results") or []:
        sh = (vr.get("data") or {}).get("spec_hash")
        if sh and sh not in hashes:
            hashes.append(sh)
    if not hashes:
        return None
    if len(hashes) == 1:
        return hashes[0]
    return hashlib.sha256(json.dumps(sorted(hashes), separators=(",", ":")).encode("utf-8")).hexdigest()


def agentledger_pob(content_hash: str) -> Optional[Dict[str, Any]]:
    """Map a sealed receipt to an AgentLedger proof-of-behavior entry (draft-dembowski-…): the signed,
    hash-chained, per-tool_call shape — `payload_hash` (the verified input), `result_hash` (the sealed
    verdict record), `prev_hash` (the prior node in this engine's ledger). It is a VIEW of the receipt,
    not a second attestation: the signature is the record's own COSE_Sign1 (Ed25519) over `result_hash`,
    and the chain is the engine's ledger (`ledger.precedent_for_record`). PoB records behaviour, not
    correctness — the `verdict` says what was checked. None when the record is not found."""
    from . import cas, ledger
    rec = cas.fetch(content_hash)
    if rec is None:
        return None
    prec = ledger.precedent_for_record(content_hash)
    env = envelope(rec)
    sealed_at = prec.get("sealed_at") if prec else None
    return {
        "format": "agentledger-pob", "spec": AGENTLEDGER_SPEC, "mapped_from": SPEC_VERSION,
        "entry_type": "tool_call", "tool": "concordance.verify",
        "payload_hash": _payload_hash(rec),
        "result_hash": content_hash,
        "prev_hash": (prec.get("prev_hash") if prec else None),
        "ledger_node": (prec.get("content_hash") if prec else None),
        "chained": prec is not None,
        "verdict": rec.get("verdict") or rec.get("overall"),
        "iat": int(sealed_at) if isinstance(sealed_at, (int, float)) else None,
        "issuer": issuer_kid(),
        "signature": ({"alg": "ed25519", "cose_sign1_b64": env["cose_sign1_b64"],
                       "public_key": env["public_key"]} if env else None),
        "means": ("a view of the receipt in the AgentLedger proof-of-behavior shape: payload_hash is the "
                  "verified input's spec_hash, result_hash is the sealed record's content_hash, prev_hash is "
                  "the prior node in this engine's hash-chained ledger (GENESIS at the root); the signature "
                  "is the record's COSE_Sign1 over result_hash. It records behaviour, not correctness."),
    }


__all__ = ["envelope", "verify_envelope", "pq_envelope", "in_toto_statement", "dsse_envelope",
           "agentledger_pob", "publish", "lookup", "attest", "status", "issuer_public_key",
           "public_key_pem", "issuer_kid", "pq_issuer_public_key", "pq_issuer_kid"]
