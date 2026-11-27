#!/usr/bin/env python3
"""verify_receipt.py — check a Concordance receipt with nothing but this file.

    python3 verify_receipt.py receipt.json [--public-key <b64url Ed25519 raw key>] [--offline] [--spec spec.json ...]

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
A step that carries a CERTIFICATE (data.certificate: a primality, polynomial-root or linear-system proof) is
re-checked here by arithmetic alone, so the stranger re-confirms the verdict itself, not only that the record is the
one sealed. Give the spec a step checked with --spec (the packet you submitted, or the one the receipt page shows):
when it re-hashes to the step's spec_hash, the certificate must state exactly its inputs, and a step that reads
CONFIRMED must claim what the certificate proves (BIND).
A document root is walked: every step's spec_hash and the derivation seal are listed so you can fetch
and re-check each one the same way.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
import math
import re
import urllib.request
from fractions import Fraction

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


# ── certificates: re-check the verdict itself, by arithmetic alone ─────────────────────────────────────────────────
# A copy of the engine's certificate checker (verifiers/certificate.py), kept here so this file needs nothing of it.
# Every number is read exactly: an integer is a JSON integer, a rational the text "p" or "p/q"; nothing else reads.
CERT_MAX_N_BITS, CERT_MAX_DEGREE, CERT_MAX_DIM, CERT_MAX_DIGITS, CERT_MAX_INT_BITS = 64, 64, 32, 600, 2000
_CERT_RATIONAL = re.compile(r"-?[0-9]{1,600}(/[0-9]{1,600})?")


def _c_int(v):
    if type(v) is not int or v.bit_length() > CERT_MAX_INT_BITS:
        raise ValueError(f"not an integer a certificate holds: {v!r}"[:120])
    return v


def _c_rational(v):
    if not isinstance(v, str) or not _CERT_RATIONAL.fullmatch(v):
        raise ValueError(f"not a rational a certificate holds: {v!r}"[:120])
    try:
        return Fraction(v)
    except ZeroDivisionError:
        raise ValueError("a zero denominator") from None


def _c_horner(coeffs, x):
    acc = Fraction(0)
    for c in coeffs:
        acc = acc * x + c
    return acc


def _c_primality(c, depth=0):
    if depth > CERT_MAX_N_BITS:
        return False, "the proof nests deeper than its n allows"
    try:
        n, verdict, proof = _c_int(c["claim"]["n"]), c["claim"]["verdict"], c["proof"]
    except (KeyError, TypeError, ValueError) as e:
        return False, f"malformed claim: {e}"[:160]
    if n < 2:
        return False, "n < 2 is neither prime nor composite"
    if n.bit_length() > CERT_MAX_N_BITS:
        return False, f"n has {n.bit_length()} bits; this checker reads primality certificates up to {CERT_MAX_N_BITS}"
    if verdict == "composite":
        try:
            d = _c_int(proof["factor"])
        except (KeyError, TypeError, ValueError) as e:
            return False, f"malformed factor: {e}"[:160]
        return (True, f"{n} = {d} x {n // d}, composite") if 1 < d < n and n % d == 0 else \
            (False, f"{d} is not a factor of {n} strictly between 1 and {n}")
    if verdict != "prime":
        return False, f"unknown verdict {verdict!r}"[:120]
    if n == 2:
        return True, "2 is prime"
    try:
        a, factors = _c_int(proof["base"]), proof["factors"]
        if not isinstance(factors, list) or len(factors) > CERT_MAX_N_BITS:
            raise ValueError("factors must be a list of at most 64 entries")
        qs = []
        for item in factors:
            if not isinstance(item, list) or len(item) != 2 or not isinstance(item[1], dict):
                raise ValueError("a factor entry is [q, its own primality certificate]")
            q, sub = _c_int(item[0]), item[1]
            if not 1 < q < n:
                return False, f"listed factor {q} is not between 1 and {n}"
            ok, why = _c_primality(sub, depth + 1)
            if not ok:
                return False, f"factor {q} is not certified prime: {why}"[:200]
            if sub.get("kind") != "primality" or sub["claim"]["n"] != q or sub["claim"]["verdict"] != "prime":
                return False, f"the entry for {q} does not certify {q} prime"
            qs.append(q)
    except (KeyError, TypeError, ValueError) as e:
        return False, f"malformed proof: {e}"[:160]
    m = n - 1
    for q in qs:
        if m % q:
            return False, f"{q} does not divide what is left of n - 1"
        while m % q == 0:
            m //= q
    if m != 1:
        return False, "the listed primes do not generate n - 1: a prime factor is missing"
    if not 1 < a < n or pow(a, n - 1, n) != 1:
        return False, "the base does not satisfy a^(n-1) = 1 (mod n)"
    for q in qs:
        if pow(a, (n - 1) // q, n) == 1:
            return False, f"a^((n-1)/{q}) = 1 (mod n): the base's order is not n - 1"
    return True, f"{n} is prime by Lucas (base {a}; n - 1 has prime factors {sorted(qs)})"


def check_certificate(cert):
    """Re-confirm a certificate from the certificate alone. Returns (ok, why)."""
    if not isinstance(cert, dict) or cert.get("schema") != 1:
        return False, "not a certificate of schema 1"
    kind, claim, proof = cert.get("kind"), cert.get("claim"), cert.get("proof")
    if not isinstance(claim, dict) or not isinstance(proof, dict):
        return False, "a certificate holds a claim and a proof"
    if kind == "primality":
        return _c_primality(cert)
    try:
        if kind == "polynomial_root":
            coeffs = claim["coeffs"]
            if claim["verdict"] != "root" or not isinstance(coeffs, list) or not 2 <= len(coeffs) <= CERT_MAX_DEGREE + 1:
                raise ValueError("a root certificate holds a verdict of root and 2 to 65 coefficients")
            cf = [_c_int(v) for v in coeffs]
            if cf[0] == 0:
                raise ValueError("the leading coefficient is 0")
            r = _c_rational(proof["root"])
            v = _c_horner(cf, r)
            return (True, f"p({proof['root']}) = 0 exactly (degree {len(cf) - 1})") if v == 0 else (False, f"p(root) = {v}, not 0")
        if kind == "linear_system":
            rows, b, x = claim["A"], claim["b"], proof["x"]
            if claim["verdict"] != "solves" or not (isinstance(rows, list) and isinstance(b, list) and isinstance(x, list)) \
                    or not rows or len(rows) > CERT_MAX_DIM or not 1 <= len(x) <= CERT_MAX_DIM or len(rows) != len(b) \
                    or any(not isinstance(row, list) or len(row) != len(x) for row in rows):
                raise ValueError("A must be m x n, b of length m and x of length n, each at most 32")
            A = [[_c_rational(v) for v in row] for row in rows]
            bF, xF = [_c_rational(v) for v in b], [_c_rational(v) for v in x]
            ok = all(sum((row[j] * xF[j] for j in range(len(xF))), Fraction(0)) == bF[i] for i, row in enumerate(A))
            return (True, f"A x = b exactly ({len(A)} x {len(xF)})") if ok else (False, "A x is not b")
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as e:
        return False, f"malformed {kind} certificate: {e}"[:160]
    return False, f"unknown certificate kind {kind!r}"[:120]


def _in_integer(v):
    """An integer as a verifier reads its input: an int, a finite float with no fraction, or a text of one; no bool."""
    if isinstance(v, bool) or not isinstance(v, (int, float, str)) or \
            (isinstance(v, float) and not (math.isfinite(v) and v.is_integer())):
        raise ValueError(f"not a whole number: {v!r}"[:120])
    return int(v)


def _in_root(v):
    """A claimed root as polynomial.root reads it: text by Fraction, an int exactly, a float to the nearest fraction
    with a denominator up to 10**9; no bool."""
    if isinstance(v, str):
        return Fraction(v)
    if isinstance(v, bool):
        raise ValueError("a boolean is not a number")
    return Fraction(v).limit_denominator(10 ** 9) if isinstance(v, float) else Fraction(v)


def _in_exact(v):
    """A matrix or vector entry read exactly: an int, a finite float's exact binary value, or a rational text."""
    if isinstance(v, bool):
        raise ValueError("a boolean is not a number")
    if isinstance(v, int):
        return Fraction(v)
    if isinstance(v, float):
        if not math.isfinite(v):
            raise ValueError("not finite")
        return Fraction(v)
    if isinstance(v, str):
        return _c_rational(v.strip())
    raise ValueError(f"not a number: {v!r}"[:120])


def _in_bool(v):
    """A true/false as a verifier reads it: a JSON true or false, or the text true, false, yes or no; nothing else."""
    if isinstance(v, bool):
        return v
    t = v.strip().lower() if isinstance(v, str) else None
    if t in ("true", "yes"):
        return True
    if t in ("false", "no"):
        return False
    raise ValueError(f"not true or false: {v!r}"[:120])


_CERT_FIELDS = {"primality": ("n_prime", "claimed_prime"), "polynomial_root": ("coeffs", "claimed_root"),
                "linear_system": ("matrix", "vec_b", "claimed_solution")}


def bind_certificate(cert, spec, status=None):
    """Whether the certificate states exactly the inputs this spec gave its check, and whether a step that reads
    CONFIRMED claims what the certificate proves. Returns (ok, why)."""
    kind = cert.get("kind") if isinstance(cert, dict) else None
    fields = _CERT_FIELDS.get(kind)
    if fields is None:
        return False, f"unknown certificate kind {kind!r}"[:120]
    candidates = ([spec] + [v for v in spec.values() if isinstance(v, dict)]) if isinstance(spec, dict) else []
    pk = next((d for d in candidates if all(f in d for f in fields)), None)
    if pk is None:
        return False, f"the spec holds no packet with {', '.join(fields)}"
    try:
        claim, proof = cert["claim"], cert["proof"]
        agrees = True
        if kind == "primality":
            same = _in_integer(pk["n_prime"]) == claim["n"]
            agrees = _in_bool(pk["claimed_prime"]) == (claim["verdict"] == "prime")
        elif kind == "polynomial_root":
            same = [_in_integer(v) for v in pk["coeffs"]] == claim["coeffs"] and _in_root(pk["claimed_root"]) == _c_rational(proof["root"])
        else:
            same = ([[_in_exact(v) for v in row] for row in pk["matrix"]] == [[_c_rational(v) for v in row] for row in claim["A"]]
                    and [_in_exact(v) for v in pk["vec_b"]] == [_c_rational(v) for v in claim["b"]]
                    and [_in_exact(v) for v in pk["claimed_solution"]] == [_c_rational(v) for v in proof["x"]])
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as e:
        return False, f"the spec or the certificate does not read: {e}"[:160]
    if not same:
        return False, "the certificate is about other inputs than the ones checked"
    if status == "CONFIRMED" and not agrees:
        return False, (f"the certificate proves {claim['n']} {claim['verdict']}, the step claims the opposite, and it reads "
                       f"CONFIRMED")
    return True, "the certificate states the checked inputs" + ("" if agrees else ", and refutes the claim")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("receipt")
    ap.add_argument("--public-key", help="issuer Ed25519 public key, base64url raw (defaults to the one in the envelope)")
    ap.add_argument("--offline", action="store_true", help="skip the live Rekor fetch; use the log claim as held")
    ap.add_argument("--spec", action="append", default=[], help="a spec a step checked (JSON); binds that step's certificate")
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

    # certificates: the verdict re-checked by arithmetic, and bound to the spec it was about when that spec is given
    specs = {}
    for path in a.spec:
        sp = json.load(open(path, encoding="utf-8"))
        specs[sha256(canonical(sp))] = sp
    for vr in record.get("verifier_results") or []:
        d = vr.get("data") or {}
        cert = d.get("certificate")
        if not isinstance(cert, dict):
            continue
        ok, why = check_certificate(cert)
        results.append(("CERT", ok, f"{vr.get('name')}: {why}"))
        sp = specs.get(d.get("spec_hash"))
        if sp is not None:
            ok, why = bind_certificate(cert, sp, vr.get("status"))
            results.append(("BIND", ok, f"{vr.get('name')}: {why}"))
        elif a.spec:
            results.append(("BIND", None, f"{vr.get('name')}: no --spec re-hashes to this step's spec_hash"))

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
