"""Receipt envelopes — a seal in a format other people's tools verify.

A Concordance seal is a SHA-256 of a canonical record held in a local, self-signed ledger. That is
weaker than it sounds: the ledger's owner could rewrite it. The fix is to put the same hash in an
envelope a third-party transparency log accepts:

  * in-toto Statement v1 (https://in-toto.io/Statement/v1) with a `concordance.verdict/v1` predicate —
    the envelope Sigstore's `cosign`/`rekor-cli` log, so an inclusion proof lives outside this box.
  * DSSE (https://github.com/secure-systems-lab/dsse) signing with the engine's Ed25519 key, so the
    statement is authenticated even before it reaches a log.
  * A SCITT-shaped `agent_receipt` (draft-noa-scitt-ai-agent-receipt) carrying the same hash chain, for
    registries that speak that draft. COSE is not produced here (no CBOR dependency in the core); the
    JSON form carries the identical claims and is marked as such.

Nothing here changes a verdict. The envelope says WHO sealed WHAT and WHEN; the record says whether
the arithmetic held.
"""
from __future__ import annotations

import base64
import json
import time
from typing import Any, Dict, Optional

from . import cas
from .validate import canonical_json_bytes, sha256_bytes

PREDICATE_TYPE = "https://concordance.dev/verdict/v1"
STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
DSSE_PAYLOAD_TYPE = "application/vnd.in-toto+json"


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _pae(payload_type: str, payload: bytes) -> bytes:
    """DSSE pre-authentication encoding."""
    return b"DSSEv1 %d %s %d %s" % (len(payload_type), payload_type.encode(), len(payload), payload)


def statement(content_hash: str, *, record: Optional[Dict[str, Any]] = None,
              engine_version: str = "", public_base: str = "") -> Dict[str, Any]:
    """The in-toto Statement for one seal. The subject is the sealed record by its SHA-256; the predicate
    carries the verdict, the step trail digest, and where the record can be fetched."""
    rec = record if record is not None else cas.fetch(content_hash)
    if rec is None:
        raise KeyError(f"no sealed record for {content_hash}")
    body = dict(rec)
    body.pop("content_hash", None)
    recomputed = sha256_bytes(canonical_json_bytes(body))
    if recomputed != content_hash:
        raise ValueError(f"record does not hash to {content_hash} (got {recomputed})")
    overall = rec.get("overall")
    verdict = (overall.get("status") if isinstance(overall, dict) else overall) or rec.get("verdict") or rec.get("status")
    trail = rec.get("verifier_results") or rec.get("trail") or []
    domain = rec.get("domain") or next(((t.get("data") or {}).get("domain") or t.get("detail", "").split(".")[0]
                                        for t in trail if isinstance(t, dict)), None)
    return {
        "_type": STATEMENT_TYPE,
        "subject": [{"name": f"concordance:seal:{content_hash}", "digest": {"sha256": content_hash}}],
        "predicateType": PREDICATE_TYPE,
        "predicate": {
            "verdict": verdict,
            "domain": domain,
            "checks": len(trail),
            "trail_sha256": sha256_bytes(canonical_json_bytes(trail)),
            "sealed_at": rec.get("sealed_at") or rec.get("timestamp"),
            "engine": {"name": "concordance", "version": engine_version},
            "fetch": (public_base.rstrip("/") + "/s/" + content_hash) if public_base else "/s/" + content_hash,
            "means": "the subject digest is SHA-256 of the canonical sealed record; re-fetch it and re-hash. "
                     "The verdict is the engine's deterministic recompute, not an attestation of safety or suitability.",
        },
    }


def dsse(stmt: Dict[str, Any], private_key_b64u: Optional[str] = None) -> Dict[str, Any]:
    """Wrap a statement in a DSSE envelope. Signed with Ed25519 when a key is given (needs the `signing`
    extra); unsigned otherwise (the envelope then only carries the payload, and says so)."""
    payload = canonical_json_bytes(stmt)
    env: Dict[str, Any] = {"payloadType": DSSE_PAYLOAD_TYPE, "payload": _b64(payload), "signatures": []}
    if private_key_b64u:
        from . import signing
        sig = signing.sign_bytes(_pae(DSSE_PAYLOAD_TYPE, payload), private_key_b64u)
        env["signatures"].append({"keyid": signing.public_from_private(private_key_b64u), "sig": sig})
    else:
        env["note"] = "unsigned: pass an Ed25519 private key to sign (pip install 'concordance[signing]')"
    return env


def verify_dsse(env: Dict[str, Any]) -> Dict[str, Any]:
    """Check every signature on a DSSE envelope and that the payload is a well-formed statement."""
    payload = base64.b64decode(env["payload"])
    stmt = json.loads(payload)
    ok_sigs = []
    for s in env.get("signatures", []):
        try:
            from . import signing
            ok = signing.verify_bytes(_pae(env["payloadType"], payload), s["sig"], s["keyid"])
        except Exception as e:  # noqa: BLE001
            ok = False
        ok_sigs.append({"keyid": s.get("keyid"), "ok": bool(ok)})
    return {"statement": stmt, "signatures": ok_sigs, "well_formed": stmt.get("_type") == STATEMENT_TYPE}


def scitt_receipt(content_hash: str, *, prev_hash: Optional[str] = None, issuer: str = "concordance",
                  record: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """A JSON rendering of the SCITT agent-receipt draft's claim set. The draft's wire form is COSE; this
    carries the same claims so a registry adapter can re-encode it without re-deriving anything."""
    stmt = statement(content_hash, record=record)
    return {"receipt_version": "draft-noa-scitt-ai-agent-receipt-01",
            "encoding": "json (COSE claims mirrored; not a COSE_Sign1)",
            "iss": issuer, "iat": int(time.time()),
            "action": {"type": "verify", "verdict": stmt["predicate"]["verdict"], "domain": stmt["predicate"]["domain"]},
            "artifact": {"sha256": content_hash},
            "prev": prev_hash,
            "note": "attests that this issuer sealed this record; it does not claim the agent that submitted the "
                    "claim was correct — the verdict inside says whether the arithmetic held."}


__all__ = ["statement", "dsse", "verify_dsse", "scitt_receipt", "PREDICATE_TYPE", "STATEMENT_TYPE"]
