#!/usr/bin/env python3
"""Check a notary receipt offline, from V3's public key alone. It imports nothing from this repository, so anyone can
run it as it stands; it needs only the `cryptography` package, for Ed25519.

    python docs/verify_notary.py RECEIPT.json --key <V3 public key>
    python docs/verify_notary.py RECEIPT.json --key <V3 public key> --store-key <the store's public key>

Each key is 43 characters of base64url: the 32 raw bytes of an Ed25519 public key. V3's is served at GET /notary/key
(publicly https://api.narrowhighway.com/v3/notary/key); take it once and keep it beside your receipts. RECEIPT.json is
one receipt as V3 answered it, or '-' for standard input; a byte-order mark a Windows editor or PowerShell 5.1 saved
before it is read past.

It rebuilds the bytes V3 signed from the receipt's own fields (docs/NOTARY.md) and checks, in order: that the receipt
holds exactly its twelve fields, each in its form; the format; the kid against the key given; the hash, the SHA-256 of
those bytes; and sig, V3's Ed25519 signature over them. With --store-key it also checks storekey against that key and
store_sig, the store's own signature over its request bytes, which proves what the store sent without trusting V3.
Base64url is read strictly: no padding, only the url-safe alphabet, and only text that re-encodes to itself, so a
signature with its last character changed is refused even where a lenient decoder reads the same 64 bytes.

Exit 0 when every check holds, 1 when one fails (each failure is printed), 2 on a usage error.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from typing import Any, List, Optional

FORMAT = "concordance-notary/v1"
REQUEST_FORMAT = "concordance-notary-request/v1"
FIELDS = ("format", "kid", "store", "storekey", "seq", "head", "at", "witnessed_at", "prev", "hash", "sig",
          "store_sig")
MAX_SEQ = 2 ** 53 - 1
_STORE = re.compile(r"[a-z0-9][a-z0-9-]{2,62}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_KID = re.compile(r"ed25519:[0-9a-f]{16}")
_TIME = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})Z")
_B64U = re.compile(r"[A-Za-z0-9_-]+")


def b64u(text: Any, nbytes: int) -> Optional[bytes]:
    """Strict base64url without padding, or None."""
    if not isinstance(text, str) or len(text) != -(-nbytes * 4 // 3) or _B64U.fullmatch(text) is None:
        return None
    raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    if len(raw) != nbytes or base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii") != text:
        return None
    return raw


def key_id(raw: bytes) -> str:
    return "ed25519:" + hashlib.sha256(raw).hexdigest()[:16]


def is_time(v: Any) -> bool:
    m = _TIME.fullmatch(v) if isinstance(v, str) else None
    if m is None:
        return False
    try:
        datetime(*(int(g) for g in m.groups()), tzinfo=timezone.utc)
    except ValueError:
        return False
    return True


def request_bytes(r: dict) -> bytes:
    return f"{REQUEST_FORMAT}\n{r['store']}\n{r['seq']}\n{r['head']}\n{r['at']}\n".encode("utf-8")


def receipt_bytes(r: dict) -> bytes:
    return (f"{FORMAT}\n{r['kid']}\n{r['store']}\n{r['storekey']}\n{r['seq']}\n{r['head']}\n{r['at']}\n"
            f"{r['witnessed_at']}\n{r['prev']}\n").encode("utf-8")


def _verifies(public_key: bytes, message: bytes, sig: bytes) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(sig, message)
        return True
    except (InvalidSignature, ValueError):
        return False


def check(receipt: Any, key: str, store_key: Optional[str] = None) -> List[str]:
    """Every problem with the receipt under V3's public key (and the store's, when given). Empty means it holds."""
    if not isinstance(receipt, dict) or sorted(receipt) != sorted(FIELDS):
        return [f"the receipt must hold exactly the fields {', '.join(FIELDS)}"]
    r = receipt
    problems = []
    forms = {"format": isinstance(r["format"], str), "kid": isinstance(r["kid"], str) and _KID.fullmatch(r["kid"]),
             "store": isinstance(r["store"], str) and _STORE.fullmatch(r["store"]),
             "storekey": isinstance(r["storekey"], str) and _KID.fullmatch(r["storekey"]),
             "seq": type(r["seq"]) is int and 1 <= r["seq"] <= MAX_SEQ,
             "head": isinstance(r["head"], str) and _HEX64.fullmatch(r["head"]),
             "at": is_time(r["at"]), "witnessed_at": is_time(r["witnessed_at"]),
             "prev": r["prev"] == "genesis" or (isinstance(r["prev"], str) and _HEX64.fullmatch(r["prev"])),
             "hash": isinstance(r["hash"], str) and _HEX64.fullmatch(r["hash"]),
             "sig": b64u(r["sig"], 64) is not None, "store_sig": b64u(r["store_sig"], 64) is not None}
    problems += [f"{name}: outside its form" for name, ok in forms.items() if not ok]
    if problems:
        return problems
    if r["format"] != FORMAT:
        problems.append(f"format: {r['format']!r}, not {FORMAT!r}")
    issuer = b64u(key, 32)
    if issuer is None:
        return problems + ["the key given is not 43 characters of strict base64url (32 bytes)"]
    if r["kid"] != key_id(issuer):
        problems.append(f"kid: {r['kid']}, and the key given is {key_id(issuer)}")
    signed = receipt_bytes(r)
    if hashlib.sha256(signed).hexdigest() != r["hash"]:
        problems.append("hash: not the SHA-256 of the bytes rebuilt from the receipt's fields")
    if not _verifies(issuer, signed, b64u(r["sig"], 64)):
        problems.append("sig: does not verify under the key given")
    if store_key is not None:
        raw = b64u(store_key, 32)
        if raw is None:
            problems.append("the store key given is not 43 characters of strict base64url (32 bytes)")
        else:
            if r["storekey"] != key_id(raw):
                problems.append(f"storekey: {r['storekey']}, and the store key given is {key_id(raw)}")
            if not _verifies(raw, request_bytes(r), b64u(r["store_sig"], 64)):
                problems.append("store_sig: does not verify under the store key given")
    return problems


def decode(raw: bytes) -> str:
    """A saved receipt's text. Windows PowerShell 5.1 writes UTF-16 with a byte-order mark from `>` and `Out-File`, and
    UTF-8 with one from `Out-File -Encoding utf8`; both read here as the plain UTF-8 V3 answered. The mark is not part
    of the receipt, and no field's value changes."""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig")


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Check a notary receipt offline from V3's public key.")
    p.add_argument("receipt", help="a receipt as V3 answered it (JSON), or - for standard input")
    p.add_argument("--key", required=True, help="V3's public key: 43 characters of base64url")
    p.add_argument("--store-key", help="the store's public key, to check storekey and store_sig too")
    a = p.parse_args(argv)
    try:
        raw = sys.stdin.buffer.read() if a.receipt == "-" else open(a.receipt, "rb").read()
        receipt = json.loads(decode(raw))
    except (OSError, ValueError) as e:
        print(f"FAIL: cannot read the receipt: {e}")
        return 1
    problems = check(receipt, a.key, a.store_key)
    if problems:
        for line in problems:
            print(f"FAIL: {line}")
        return 1
    print(f"OK: {receipt['kid']} saw head {receipt['head']} at seq {receipt['seq']} of store {receipt['store']} "
          f"at {receipt['witnessed_at']}" + ("; the store's own signature holds too" if a.store_key else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
