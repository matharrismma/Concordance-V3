#!/usr/bin/env python3
"""verify_receipt.py — check a Concordance receipt with nothing but this file.

    python3 verify_receipt.py receipt.json [--public-key <b64url Ed25519 raw key>] [--offline]

Dependencies: Python 3.9+, `cbor2`, `cryptography` (pip install cbor2 cryptography). Nothing from
Concordance is imported; the point is that a stranger can run this.

A receipt is the JSON you get from `seal_fetch` / GET /s/<hash>: the sealed record itself, with the
provenance beside it under "attest": {"envelope": {...}, "log": {...}}. ({"record": {...}, "attest": {...}}
is also accepted.) `attest` is never part of what is hashed.

Four independent checks, each printed with its own verdict:
  1. HASH      the record (minus content_hash and attest) in canonical JSON (sorted keys, tight separators,
               ensure_ascii=False, UTF-8) re-hashes with SHA-256 to its content_hash.
  2. SIGNATURE the COSE_Sign1 statement verifies under the issuer's Ed25519 public key over
               Sig_structure = ["Signature1", protected, b"", payload] (RFC 9052 §4.4), its payload
               hashes to the content_hash, and the header's claim set names the same hash.
  3. LOG       the Rekor entry (fetched live, unless --offline) is a `rekord` whose data is exactly the
               statement bytes and whose public key is the issuer key.
  4. INCLUSION the entry's Merkle inclusion proof (RFC 6962 hashing) reproduces the log root hash.
A document root is walked: every step's spec_hash and the derivation seal are listed so you can fetch
and re-check each one the same way.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
import urllib.request

ALG_EDDSA = -8
LABEL_CLAIMS = -70001
CWT_CLAIMS, CWT_ISS, CWT_SUB = 15, 1, 2   # SCITT CWT Claims header (RFC 9597) and CWT claims (RFC 8392)


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8", "surrogatepass")


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def b64u_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def check_hash(record: dict) -> tuple[bool, str]:
    claimed = record.get("content_hash")
    if not claimed:
        return False, "record has no content_hash"
    got = sha256(canonical({k: v for k, v in record.items() if k not in ("content_hash", "attest")}))
    return got == claimed, f"sha256(canonical record) = {got[:16]}… claimed {str(claimed)[:16]}…"


def check_signature(statement_b64: str, public_key_b64u: str) -> tuple[bool, str, dict]:
    import cbor2
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.exceptions import InvalidSignature
    raw = base64.b64decode(statement_b64)
    tagged = cbor2.loads(raw)
    if getattr(tagged, "tag", None) != 18:
        return False, "statement is not a COSE_Sign1 (CBOR tag 18)", {}
    protected, _unprotected, payload, sig = list(tagged.value)
    hdr = cbor2.loads(protected)
    if hdr.get(1) != ALG_EDDSA:
        return False, f"unexpected alg {hdr.get(1)} (want EdDSA = -8)", {}
    sig_structure = cbor2.dumps(["Signature1", protected, b"", payload])
    try:
        Ed25519PublicKey.from_public_bytes(b64u_decode(public_key_b64u)).verify(sig, sig_structure)
    except (InvalidSignature, ValueError) as e:
        return False, f"signature does not verify under the given key ({e.__class__.__name__})", {}
    claims = dict(hdr.get(LABEL_CLAIMS) or {})
    payload_hash = sha256(payload)
    if payload_hash != claims.get("content_hash"):
        return False, f"payload hashes to {payload_hash[:16]}… but header claims {str(claims.get('content_hash'))[:16]}…", claims
    # SCITT CWT Claims header (RFC 9597), when present: the subject must be this content_hash.
    cwt = dict(hdr.get(CWT_CLAIMS) or {})
    if cwt and cwt.get(CWT_SUB) != payload_hash:
        return False, f"CWT sub {str(cwt.get(CWT_SUB))[:16]}… does not match the payload hash {payload_hash[:16]}…", claims
    scitt = f"; SCITT sub ok, iss {cwt.get(CWT_ISS)}" if cwt else ""
    return True, f"EdDSA ok; kid {(hdr.get(4) or b'').decode(errors='replace')}; payload sha256 = {payload_hash[:16]}…{scitt}", {
        **claims, "payload_hash": payload_hash, "statement_bytes": raw, "cwt_iss": cwt.get(CWT_ISS), "cwt_sub": cwt.get(CWT_SUB)}


def check_pq_signature(pq: dict, record: dict) -> tuple[bool, str]:
    """Verify the post-quantum (ML-DSA-65, FIPS 204) signature over the canonical record bytes — the
    durable half of the receipt, whose hardness survives the quantum attack that breaks the Ed25519
    statement. Signed over canonical(record minus content_hash and attest), the same bytes the Ed25519
    statement covers, so it binds the same content_hash. Needs a recent `cryptography` (ML-DSA)."""
    from cryptography.hazmat.primitives.asymmetric import mldsa
    from cryptography.exceptions import InvalidSignature
    payload = canonical({k: v for k, v in record.items() if k not in ("content_hash", "attest")})
    ph = sha256(payload)
    try:
        pub = mldsa.MLDSA65PublicKey.from_public_bytes(b64u_decode(pq["public_key"]))
        pub.verify(b64u_decode(pq["signature"]), payload)
    except (InvalidSignature, ValueError) as e:
        return False, f"ML-DSA signature does not verify ({e.__class__.__name__})"
    if pq.get("content_hash") not in (None, ph):
        return False, f"pq content_hash {str(pq.get('content_hash'))[:16]}… != record hash {ph[:16]}…"
    if record.get("content_hash") not in (None, ph):
        return False, "the signature is about a different record than the one supplied"
    return True, f"ML-DSA-65 ok; kid {pq.get('kid')}; payload sha256 = {ph[:16]}… (post-quantum durable)"


def fetch_entry(rekor: str, uuid: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(f"{rekor}/api/v1/log/entries/{uuid}",
                                                       headers={"Accept": "application/json"}), timeout=20) as r:
        return json.loads(r.read().decode())


def check_log(entry: dict, statement_bytes: bytes, public_key_b64u: str) -> tuple[bool, str]:
    from cryptography.hazmat.primitives import serialization
    body = json.loads(base64.b64decode(entry["body"]))
    if body.get("kind") != "rekord":
        return False, f"entry kind is {body.get('kind')}, not rekord"
    spec = body["spec"]
    logged = base64.b64decode(spec["data"]["content"]) if spec["data"].get("content") else None
    if logged is None:
        # rekord entries fetched back carry only the hash of the data, not the bytes
        h = (spec["data"].get("hash") or {}).get("value")
        same = h == sha256(statement_bytes)
        detail = f"logged data sha256 {str(h)[:16]}… vs statement {sha256(statement_bytes)[:16]}…"
    else:
        same = logged == statement_bytes
        detail = "logged data bytes == statement bytes" if same else "logged data differs from statement"
    pem = base64.b64decode(spec["signature"]["publicKey"]["content"])
    pub = serialization.load_pem_public_key(pem)
    raw = pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    key_same = raw == b64u_decode(public_key_b64u)
    return same and key_same, detail + ("; issuer key matches" if key_same else "; LOGGED KEY IS NOT THE ISSUER KEY")


def check_inclusion(entry: dict) -> tuple[bool, str]:
    """RFC 6962: leaf = sha256(0x00 || body), node = sha256(0x01 || left || right)."""
    proof = (entry.get("verification") or {}).get("inclusionProof") or {}
    hashes = [bytes.fromhex(h) for h in proof.get("hashes") or []]
    index, size = int(proof.get("logIndex", -1)), int(proof.get("treeSize", 0))
    root = proof.get("rootHash")
    if not hashes or index < 0 or not size or not root:
        return False, "no inclusion proof in the entry (log may not have integrated it yet)"
    node = hashlib.sha256(b"\x00" + base64.b64decode(entry["body"])).digest()
    i, n = index, size - 1
    for h in hashes:
        if i % 2 == 1 or i == n:
            node = hashlib.sha256(b"\x01" + h + node).digest()
            while i % 2 == 0 and i != 0:
                i //= 2
                n //= 2
        else:
            node = hashlib.sha256(b"\x01" + node + h).digest()
        i //= 2
        n //= 2
    ok = node.hex() == root
    return ok, f"{len(hashes)} proof hashes, tree size {size}, leaf index {index}; root {'reproduced' if ok else 'MISMATCH'}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("receipt")
    ap.add_argument("--public-key", help="issuer Ed25519 public key, base64url raw (defaults to the one in the envelope)")
    ap.add_argument("--offline", action="store_true", help="skip the live Rekor fetch; use the log claim as held")
    a = ap.parse_args()
    data = json.load(open(a.receipt, encoding="utf-8"))
    record = data.get("record") or data
    att = data.get("attest") or data
    env, log = att.get("envelope"), att.get("log")
    results = []

    ok, why = check_hash(record)
    results.append(("HASH", ok, why))

    stmt = {}
    if env and env.get("cose_sign1_b64"):
        pub = a.public_key or env.get("public_key")
        ok, why, stmt = check_signature(env["cose_sign1_b64"], pub)
        results.append(("SIGNATURE", ok, why))
        if ok and stmt.get("content_hash") != record.get("content_hash"):
            results.append(("SIGNATURE", False, "the statement is about a different record than the one supplied"))
    else:
        results.append(("SIGNATURE", None, "no envelope: the record is self-attested (content-addressed only)"))

    pq = att.get("pq")
    if pq and pq.get("signature"):
        ok, why = check_pq_signature(pq, record)
        results.append(("PQ-SIG", ok, why))
    else:
        results.append(("PQ-SIG", None, "no post-quantum signature (Ed25519 only — not durable past a quantum adversary)"))

    if log and not log.get("pending") and log.get("uuid") and stmt.get("statement_bytes"):
        try:
            entry = log.get("entry") if a.offline else next(iter(fetch_entry(log.get("url", "https://rekor.sigstore.dev"), log["uuid"]).values()))
            if not entry:
                raise ValueError("no entry held offline")
            ok, why = check_log(entry, stmt["statement_bytes"], a.public_key or env.get("public_key"))
            results.append(("LOG", ok, f"rekor index {entry.get('logIndex')}; {why}"))
            ok, why = check_inclusion(entry)
            results.append(("INCLUSION", ok, why))
        except Exception as e:  # noqa: BLE001
            results.append(("LOG", False, f"could not check the log entry: {e}"))
    else:
        results.append(("LOG", None, (log or {}).get("error") or "no log claim"))

    for name, ok, why in results:
        print(f"{name:<10} {'ok' if ok else ('—' if ok is None else 'FAIL'):<5} {why}")
    if record.get("kind") == "document":
        print(f"DOCUMENT   {record.get('verdict')}  {len(record.get('steps') or [])} steps; derivation seal {str(record.get('derivation_seal'))[:16]}…")
        for s in record.get("steps") or []:
            print(f"  step {s.get('id')!s:<12} {s.get('domain')!s:<16} {s.get('status')!s:<10} spec {str(s.get('spec_hash'))[:16]}…  uses {s.get('uses') or []}")
        for p in record.get("parents") or []:
            print(f"  parent {p}")
        print("  re-check each spec_hash and the derivation seal with this tool to walk the tree.")
    # the link budget — the worst event on the chain — then the trace step by step
    for g in record.get("gate_results") or []:
        b = (g.get("details") or {}).get("budget")
        if b and b.get("read"):
            print(f"BUDGET     {b['read']}")
    # the inverted reading: what was attempted, what survived, and any counterexample (the finding)
    for vr in record.get("verifier_results") or []:
        ref = (vr.get("data") or {}).get("refutations")
        if not ref:
            continue
        print(f"STEP {vr.get('name')!s:<8} {vr.get('status')!s:<10} attempted {len(ref.get('attempted') or [])}, "
              f"survived {len(ref.get('survived') or [])}, counterexamples {len(ref.get('counterexamples') or [])}, "
              f"not attempted {len(ref.get('not_applicable') or [])}")
        for b in ref.get("bands") or []:
            u = b.get("used")
            print(f"    {b.get('what')}: claim {b.get('claimed')} {'inside' if b.get('inside') else 'OUTSIDE'} "
                  f"[{b.get('low')}, {b.get('high')}]" + (f"  used {u:.0%}" if isinstance(u, (int, float)) and u != float('inf') else ""))
        for c in ref.get("counterexamples") or []:
            print(f"    COUNTEREXAMPLE {c.get('what')}: claimed {c.get('claimed')}, recomputed {c.get('recomputed')}, off by {c.get('off_by')}")
    hard = [r for r in results if r[1] is False]
    print("RESULT    ", "FAIL" if hard else "ok", "— every independent check that could run passed" if not hard else "")
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main())
