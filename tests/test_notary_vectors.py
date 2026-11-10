"""docs/notary_vectors.json: the exact bytes, built here by hand and checked with the cryptography library alone.

The keys are RFC 8032 section 7.1 TEST 1 (the store) and TEST 2 (V3's issuer key), published test keys. Each test below
builds the bytes literally, never through the service's code, then checks that the service builds the same bytes,
answers the same receipts, and that docs/verify_notary.py accepts them and refuses any one changed.
"""
from __future__ import annotations

import base64
import calendar
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from concordance import notary

ROOT = Path(__file__).resolve().parents[1]
VECTORS = json.loads((ROOT / "docs" / "notary_vectors.json").read_text(encoding="utf-8"))
RECEIPT_KEYS = ["format", "kid", "store", "storekey", "seq", "head", "at", "witnessed_at", "prev", "hash", "sig",
                "store_sig"]


def checker():
    """docs/verify_notary.py, loaded from its path as a stranger would run it."""
    spec = importlib.util.spec_from_file_location("verify_notary", ROOT / "docs" / "verify_notary.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def seed(name: str) -> bytes:
    return bytes.fromhex(VECTORS["keys"][name]["private_seed_hex"])


def public(name: str) -> bytes:
    return bytes.fromhex(VECTORS["keys"][name]["public_key_hex"])


def b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def unb64u(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def literal_request(r: dict) -> bytes:
    return ("concordance-notary-request/v1" + "\n" + r["store"] + "\n" + str(r["seq"]) + "\n" + r["head"] + "\n"
            + r["at"] + "\n").encode("utf-8")


def literal_receipt(r: dict) -> bytes:
    return ("concordance-notary/v1" + "\n" + r["kid"] + "\n" + r["store"] + "\n" + r["storekey"] + "\n" + str(r["seq"])
            + "\n" + r["head"] + "\n" + r["at"] + "\n" + r["witnessed_at"] + "\n" + r["prev"] + "\n").encode("utf-8")


def test_the_keys_are_rfc_8032s_and_sign_its_messages():
    for row in VECTORS["rfc8032_signatures"]:
        k = Ed25519PrivateKey.from_private_bytes(seed(row["key"]))
        raw = k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        assert raw == public(row["key"])
        assert k.sign(bytes.fromhex(row["message_hex"])).hex() == row["signature_hex"]
    for name in ("store", "issuer"):
        assert VECTORS["keys"][name]["public_key"] == b64u(public(name))
    assert VECTORS["keys"]["store"]["storekey"] == "ed25519:" + hashlib.sha256(public("store")).hexdigest()[:16]
    assert VECTORS["keys"]["issuer"]["kid"] == "ed25519:" + hashlib.sha256(public("issuer")).hexdigest()[:16]
    assert "secret" not in json.dumps(VECTORS).lower()


def test_the_store_signs_the_request_bytes_built_literally():
    store_key = Ed25519PublicKey.from_public_bytes(public("store"))
    for case in VECTORS["cases"]:
        req = case["request"]
        assert sorted(req) == ["at", "head", "seq", "sig", "store"]
        assert literal_request(req) == bytes.fromhex(case["request_bytes_hex"])
        assert len(req["sig"]) == 86 and b64u(unb64u(req["sig"])) == req["sig"]
        store_key.verify(unb64u(req["sig"]), literal_request(req))             # raises when it does not verify
        assert Ed25519PrivateKey.from_private_bytes(seed("store")).sign(literal_request(req)) == unb64u(req["sig"])


def test_v3_signs_the_receipt_bytes_built_literally_and_the_chain_links():
    issuer_key = Ed25519PublicKey.from_public_bytes(public("issuer"))
    prev = "genesis"
    for case in VECTORS["cases"]:
        r = case["receipt"]
        assert list(r) == RECEIPT_KEYS
        assert r["format"] == "concordance-notary/v1"
        assert (r["store"], r["seq"], r["head"], r["at"], r["store_sig"]) == tuple(
            case["request"][k] for k in ("store", "seq", "head", "at", "sig"))
        assert r["kid"] == VECTORS["keys"]["issuer"]["kid"] and r["storekey"] == VECTORS["keys"]["store"]["storekey"]
        assert r["witnessed_at"] == case["witnessed_at"]
        assert r["prev"] == prev                              # the previous receipt's hash, in the order V3 witnessed
        assert literal_receipt(r) == bytes.fromhex(case["receipt_bytes_hex"])
        assert r["hash"] == hashlib.sha256(literal_receipt(r)).hexdigest()
        issuer_key.verify(unb64u(r["sig"]), literal_receipt(r))
        assert Ed25519PrivateKey.from_private_bytes(seed("issuer")).sign(literal_receipt(r)) == unb64u(r["sig"])
        prev = r["hash"]
    assert [c["request"]["seq"] for c in VECTORS["cases"]] == [1, 7, 4]       # an older seq after a newer one


def test_the_service_code_builds_the_same_bytes():
    for case in VECTORS["cases"]:
        req, r = case["request"], case["receipt"]
        assert notary.request_bytes(req["store"], req["seq"], req["head"], req["at"]) == bytes.fromhex(
            case["request_bytes_hex"])
        assert notary.receipt_bytes(r["kid"], r["store"], r["storekey"], r["seq"], r["head"], r["at"],
                                     r["witnessed_at"], r["prev"]) == bytes.fromhex(case["receipt_bytes_hex"])
    assert notary.key_id(public("store")) == VECTORS["keys"]["store"]["storekey"]


class FixedClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_the_service_answers_exactly_the_vector_receipts(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("CONCORDANCE_ISSUER_KEY", b64u(seed("issuer")))       # RFC 8032's published test key
    clock = FixedClock()
    monkeypatch.setattr(notary, "clock", clock)
    first = VECTORS["cases"][0]["request"]["store"]
    notary.register(first, VECTORS["keys"]["store"]["public_key"], data)
    for case in VECTORS["cases"]:
        clock.now = float(calendar.timegm(time.strptime(case["witnessed_at"], "%Y-%m-%dT%H:%M:%SZ")))
        status, _headers, body = notary.post(json.dumps(case["request"]).encode("utf-8"), data)
        assert status == 200, body
        assert json.loads(body) == case["receipt"]
        assert list(json.loads(body)) == RECEIPT_KEYS


def test_verify_notary_accepts_every_vector_receipt():
    vw = checker()
    for case in VECTORS["cases"]:
        assert vw.check(case["receipt"], VECTORS["keys"]["issuer"]["public_key"]) == []
        assert vw.check(case["receipt"], VECTORS["keys"]["issuer"]["public_key"],
                        VECTORS["keys"]["store"]["public_key"]) == []


def _changed(text: str) -> str:
    """The same text with its first character replaced by another of the same kind."""
    c = text[0]
    alt = {"0": "1", "e": "f", "c": "d", "g": "h", "2": "3"}.get(c) or ("b" if c != "b" else "c")
    return alt + text[1:]


@pytest.mark.parametrize("field", ["format", "kid", "store", "storekey", "head", "at", "witnessed_at", "prev", "hash",
                                   "sig", "store_sig"])
def test_verify_notary_refuses_a_receipt_with_any_field_changed(field):
    vw = checker()
    r = dict(VECTORS["cases"][1]["receipt"])
    r[field] = _changed(r[field])
    assert vw.check(r, VECTORS["keys"]["issuer"]["public_key"], VECTORS["keys"]["store"]["public_key"]) != []


def test_verify_notary_refuses_seq_changed_or_of_another_type():
    vw = checker()
    key = VECTORS["keys"]["issuer"]["public_key"]
    for seq in (8, "7", 7.0, True, 0, 2 ** 53):
        r = dict(VECTORS["cases"][1]["receipt"], seq=seq)
        assert vw.check(r, key) != [], seq


def test_verify_notary_refuses_a_signature_whose_last_character_a_lenient_decoder_reads_the_same():
    vw = checker()
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    r = dict(VECTORS["cases"][0]["receipt"])
    last = r["sig"][-1]
    other = alphabet[alphabet.index(last) ^ 1]               # differs only in bits a 64-byte value never uses
    lenient = r["sig"][:-1] + other
    assert unb64u(lenient) == unb64u(r["sig"])               # a lenient decoder reads the same 64 bytes
    problems = vw.check(dict(r, sig=lenient), VECTORS["keys"]["issuer"]["public_key"])
    assert problems and any("sig" in p for p in problems)
    assert vw.check(dict(r, sig=r["sig"] + "=="), VECTORS["keys"]["issuer"]["public_key"]) != []   # padding refused
    assert vw.b64u("A" * 43 + "=", 32) is None and vw.b64u(VECTORS["keys"]["issuer"]["public_key"], 32) == public("issuer")


def test_verify_notary_refuses_another_key_a_missing_field_and_an_extra_one():
    vw = checker()
    r = VECTORS["cases"][0]["receipt"]
    assert any("kid" in p for p in vw.check(r, VECTORS["keys"]["store"]["public_key"]))     # not V3's key
    assert vw.check({k: v for k, v in r.items() if k != "prev"}, VECTORS["keys"]["issuer"]["public_key"]) != []
    assert vw.check(dict(r, extra=1), VECTORS["keys"]["issuer"]["public_key"]) != []
    assert vw.check(r, VECTORS["keys"]["issuer"]["public_key"], VECTORS["keys"]["issuer"]["public_key"]) != []


def test_verify_notary_reads_a_receipt_saved_with_a_byte_order_mark(tmp_path, capsys):
    """Windows PowerShell 5.1 saves with a byte-order mark: UTF-16 from `>` and Out-File, UTF-8 from Out-File -Encoding
    utf8, with CRLF line ends. The receipt still verifies, and a changed one still fails."""
    vw = checker()
    key = VECTORS["keys"]["issuer"]["public_key"]
    text = json.dumps(VECTORS["cases"][0]["receipt"], indent=2).replace("\n", "\r\n") + "\r\n"
    saved = {"utf-8 with a mark": b"\xef\xbb\xbf" + text.encode("utf-8"), "utf-16 with a mark": text.encode("utf-16"),
             "utf-16 big-endian with a mark": b"\xfe\xff" + text.encode("utf-16-be"), "plain utf-8": text.encode()}
    for name, raw in saved.items():
        p = tmp_path / "receipt.json"
        p.write_bytes(raw)
        assert vw.main([str(p), "--key", key]) == 0, name
        assert capsys.readouterr().out.startswith("OK"), name
    changed = json.dumps(dict(VECTORS["cases"][0]["receipt"], head="0" * 64))
    p.write_bytes(b"\xef\xbb\xbf" + changed.encode("utf-8"))
    assert vw.main([str(p), "--key", key]) == 1


def test_verify_notary_runs_as_it_stands_without_concordance(tmp_path):
    src = (ROOT / "docs" / "verify_notary.py").read_text(encoding="utf-8")
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")):
            assert "concordance" not in stripped, line
    good = tmp_path / "receipt.json"
    good.write_text(json.dumps(VECTORS["cases"][0]["receipt"]), encoding="utf-8")
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(dict(VECTORS["cases"][0]["receipt"], head="0" * 64)), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    run = lambda p: subprocess.run([sys.executable, str(ROOT / "docs" / "verify_notary.py"), str(p), "--key",  # noqa: E731
                                    VECTORS["keys"]["issuer"]["public_key"]], cwd=str(tmp_path), env=env,
                                   capture_output=True, text=True, timeout=60)
    ok, no = run(good), run(bad)
    assert ok.returncode == 0 and ok.stdout.startswith("OK"), ok.stdout + ok.stderr
    assert no.returncode == 1 and "FAIL" in no.stdout, no.stdout + no.stderr
