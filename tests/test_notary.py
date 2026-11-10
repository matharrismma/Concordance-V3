"""The notary service (docs/NOTARY.md): a registered store's signed checkpoint in, a receipt signed by V3's issuer key out.

Every test keeps its stores in a temporary data directory and makes its own keys: the issuer key here is generated per
test, never a real one. Time comes from an injected clock, never a sleep. The server, where a test needs one, is this
process's own on 127.0.0.1. "Writes nothing" is checked on the whole data tree, every path with its size and hash.
"""
from __future__ import annotations

import base64
import hashlib
import http.client
import importlib.util
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from concordance import capabilities, http_api, transparency, notary

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
T0 = 1_800_000_000                     # 2027-01-15T08:00:00Z
AT = "2027-01-15T07:59:30Z"
RECEIPT_KEYS = ["format", "kid", "store", "storekey", "seq", "head", "at", "witnessed_at", "prev", "hash", "sig",
                "store_sig"]
NOT_FOUND = b'{"error": "not found"}'


# ── helpers ──────────────────────────────────────────────────────────────────────────────────────────
def b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def raw_public(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def sha(text) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def request_bytes(store: str, seq, head: str, at: str) -> bytes:
    """The store's bytes, built here by hand (docs/NOTARY.md), never through the service's code."""
    return ("concordance-notary-request/v1\n" + store + "\n" + str(seq) + "\n" + head + "\n" + at + "\n").encode("utf-8")


class Store:
    """A store with its own key, which signs its checkpoints as docs/NOTARY.md says."""

    def __init__(self, name: str):
        self.name = name
        self.key = Ed25519PrivateKey.generate()
        self.public = b64u(raw_public(self.key))

    def request(self, seq: int, head: str = None, at: str = AT, signer: Ed25519PrivateKey = None) -> dict:
        head = head or sha(f"{self.name} record {seq}")
        sig = (signer or self.key).sign(request_bytes(self.name, seq, head, at))
        return {"store": self.name, "seq": seq, "head": head, "at": at, "sig": b64u(sig)}

    def body(self, seq: int, **kw) -> bytes:
        return json.dumps(self.request(seq, **kw)).encode("utf-8")


class Clock:
    def __init__(self, now: float = T0):
        self.now = float(now)

    def __call__(self) -> float:
        return self.now


def tree(root: Path) -> dict:
    """Every path under root: a folder, or a file's size and SHA-256."""
    if not root.exists():
        return {}
    return {p.relative_to(root).as_posix(): ("dir" if p.is_dir() else (p.stat().st_size, sha256_file(p)))
            for p in sorted(root.rglob("*"))}


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def changed(before: dict, after: dict) -> list:
    return sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))


def get(path: str, query: str = ""):
    return notary.route("GET", path, query, b"")


def body_of(answer) -> dict:
    return json.loads(answer[2])


def checker():
    spec = importlib.util.spec_from_file_location("verify_notary", ROOT / "docs" / "verify_notary.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def rows(data: Path, store: str) -> int:
    con = sqlite3.connect((data / "notary" / "notary.db").resolve().as_uri() + "?mode=ro", uri=True)
    try:
        return con.execute("SELECT count(*) FROM receipts WHERE store = ?", (store,)).fetchone()[0]
    finally:
        con.close()


def kept_conflicts(data: Path, store: str) -> list:
    con = sqlite3.connect((data / "notary" / "notary.db").resolve().as_uri() + "?mode=ro", uri=True)
    try:
        return [json.loads(r[0]) for r in con.execute("SELECT request FROM conflicts WHERE store = ? ORDER BY k",
                                                      (store,))]
    finally:
        con.close()


# ── fixtures ─────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def data(tmp_path, monkeypatch) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setenv("CONCORDANCE_DATA_DIR", str(d))
    return d


class Issuer:
    def __init__(self):
        self.key = Ed25519PrivateKey.generate()
        self.seed = b64u(self.key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                                serialization.NoEncryption()))
        self.public = b64u(raw_public(self.key))
        self.kid = "ed25519:" + hashlib.sha256(raw_public(self.key)).hexdigest()[:16]


@pytest.fixture
def issuer(monkeypatch) -> Issuer:
    i = Issuer()
    monkeypatch.setenv("CONCORDANCE_ISSUER_KEY", i.seed)            # generated for this test, never a real key
    return i


@pytest.fixture
def clock(monkeypatch) -> Clock:
    c = Clock()
    monkeypatch.setattr(notary, "clock", c)
    return c


@pytest.fixture(scope="module")
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), http_api.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def ask(port: int, method: str, path: str, body: bytes = None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    try:
        conn.request(method, path, body=body, headers={"Content-Type": "application/json"} if body is not None else {})
        answer = conn.getresponse()
        return answer.status, dict(answer.getheaders()), answer.read()
    finally:
        conn.close()


def registered(data: Path, name: str = "store-a") -> Store:
    s = Store(name)
    notary.register(name, s.public, data)
    return s


# ── the receipt ──────────────────────────────────────────────────────────────────────────────────────
def test_a_checkpoint_is_notaryed_and_its_receipt_checks_offline(data, issuer, clock, server):
    s = registered(data)
    before = tree(data)
    status, headers, body = ask(server, "POST", "/notary", s.body(1))
    assert status == 200, body
    assert headers["Content-Type"].startswith("application/json") and headers["Server"].startswith("concordance/3")
    r = json.loads(body)
    assert list(r) == RECEIPT_KEYS
    assert r["format"] == "concordance-notary/v1" and r["prev"] == "genesis"
    assert r["kid"] == issuer.kid == transparency.issuer_kid()
    assert r["storekey"] == "ed25519:" + hashlib.sha256(raw_public(s.key)).hexdigest()[:16]
    assert r["witnessed_at"] == "2027-01-15T08:00:00Z" and r["store_sig"] == s.request(1)["sig"]
    assert checker().check(r, issuer.public, s.public) == []
    assert changed(before, tree(data)) == ["notary/notary.db"]           # no journal, no -wal, no -shm, nothing else
    clock.now += 60
    second = json.loads(ask(server, "POST", "/notary", s.body(2))[2])
    assert second["prev"] == r["hash"] and checker().check(second, issuer.public, s.public) == []
    status, _, key = ask(server, "GET", "/notary/key")
    assert status == 200 and json.loads(key) == {"alg": "Ed25519", "kid": issuer.kid, "public_key": issuer.public,
                                                 "format": "concordance-notary/v1",
                                                 "request_format": "concordance-notary-request/v1"}


def test_a_retry_returns_the_stored_receipt_unchanged_and_is_never_counted(data, issuer, clock):
    s = registered(data)
    status, _, first = notary.post(s.body(1))
    assert status == 200
    clock.now = T0 + 10
    before = tree(data)
    status, _, again = notary.post(s.body(1))
    assert status == 200 and again == first                              # the same bytes
    assert tree(data) == before                                         # a retry writes nothing
    clock.now = T0 + 60                                                 # a minute after the first, 50 s after the retry
    assert notary.post(s.body(2))[0] == 200


def test_a_conflict_by_head_or_by_at_is_409_the_first_receipt_stands_and_the_conflict_is_kept(data, issuer, clock):
    s = registered(data)
    first = notary.post(s.body(1))[2]
    clock.now += 60
    by_head = s.request(1, head=sha("a rewritten record 1"))
    status, _, out = notary.post(json.dumps(by_head).encode())
    assert status == 409 and json.loads(out)["receipt"] == json.loads(first) and json.loads(out)["kept"] is True
    clock.now += 60
    by_at = s.request(1, at="2027-01-15T07:59:31Z")
    status, _, out = notary.post(json.dumps(by_at).encode())
    assert status == 409 and json.loads(out)["receipt"] == json.loads(first)
    assert get("/notary/stores/store-a/1")[2] == first                   # never replaced
    st = body_of(get("/notary/stores/store-a"))
    assert (st["receipts"], st["conflicts_total"]) == (1, 2)
    kept = kept_conflicts(data, "store-a")
    assert kept == [by_head, by_at]                                     # with the store's own signature
    for req in kept:                                                    # proof that needs no trust in V3
        Ed25519PublicKey.from_public_bytes(raw_public(s.key)).verify(
            base64.urlsafe_b64decode(req["sig"] + "=="), request_bytes(req["store"], req["seq"], req["head"], req["at"]))


def test_the_101st_conflict_is_counted_not_kept_and_past_the_cap_the_rate_still_holds(data, issuer, clock):
    s = registered(data)
    notary.post(s.body(1))
    for i in range(1, 102):
        clock.now += 60
        status, _, out = notary.post(s.body(1, head=sha(i)))
        assert status == 409 and json.loads(out)["kept"] is (i <= 100), (i, out)
    assert len(kept_conflicts(data, "store-a")) == 100
    assert body_of(get("/notary/stores/store-a"))["conflicts_total"] == 101
    clock.now += 30                                                     # inside the minute: refused, and no byte moves
    before = tree(data)
    status, headers, _ = notary.post(s.body(1, head=sha(999)))
    assert status == 429 and headers["Retry-After"] == "30" and tree(data) == before
    clock.now += 30
    assert notary.post(s.body(1, head=sha(1000)))[0] == 409
    assert len(kept_conflicts(data, "store-a")) == 100
    assert body_of(get("/notary/stores/store-a"))["conflicts_total"] == 102


# ── the rules, in order ──────────────────────────────────────────────────────────────────────────────
def test_each_refusal_in_the_rule_order_writes_nothing(data, issuer, clock):
    s = registered(data)
    retired = registered(data, "store-retired")
    notary.retire("store-retired", data)
    stranger = Store("store-never-registered")
    notary.post(s.body(1))
    good = s.request(2)
    raw = lambda d: json.dumps(d).encode()                                  # noqa: E731
    lenient = good["sig"][:-1] + "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"[
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_".index(good["sig"][-1]) ^ 1]
    assert base64.urlsafe_b64decode(lenient + "==") == base64.urlsafe_b64decode(good["sig"] + "==")
    text = raw(good).decode()
    cases = [
        # 1. a body over 4 KB, whatever else is wrong with it
        ("over 4 KB", raw(dict(good, pad="x" * 5000)), 413, "4096"),
        ("over 4 KB and not JSON", b"{" * 5000, 413, "4096"),
        # 2. not that exact JSON shape
        ("not JSON", b"{", 400, "exactly the keys"),
        ("empty", b"", 400, "exactly the keys"),
        ("not UTF-8", b'{"store": "\xff"}', 400, "exactly the keys"),
        ("a list", b"[]", 400, "exactly the keys"),
        ("a missing key", raw({k: v for k, v in good.items() if k != "at"}), 400, "exactly the keys"),
        ("an extra key", raw(dict(good, note="x")), 400, "exactly the keys"),
        ("a key twice", text.replace('{"store"', '{"seq": 2, "store"', 1).encode(), 400, "exactly the keys"),
        ("NaN", text.replace('"seq": 2', '"seq": NaN').encode(), 400, "exactly the keys"),
        ("a bad shape before a bad field", raw(dict(good, seq=True, note="x")), 400, "exactly the keys"),
        # 3. a field outside its form
        ("seq true", raw(dict(good, seq=True)), 400, "seq:"),
        ("seq 2.0", text.replace('"seq": 2', '"seq": 2.0').encode(), 400, "seq:"),
        ("seq 2e0", text.replace('"seq": 2', '"seq": 2e0').encode(), 400, "seq:"),
        ("seq a string", raw(dict(good, seq="2")), 400, "seq:"),
        ("seq 0", raw(dict(good, seq=0)), 400, "seq:"),
        ("seq -1", raw(dict(good, seq=-1)), 400, "seq:"),
        ("seq 2**53", raw(dict(good, seq=2 ** 53)), 400, "seq:"),
        ("store with capitals", raw(dict(good, store="Store-a")), 400, "store:"),
        ("store too short", raw(dict(good, store="ab")), 400, "store:"),
        ("store 64 characters", raw(dict(good, store="s" * 64)), 400, "store:"),
        ("store starting with a dash", raw(dict(good, store="-store-a")), 400, "store:"),
        ("store with an underscore", raw(dict(good, store="store_a")), 400, "store:"),
        ("store with a trailing LF", raw(dict(good, store="store-a\n")), 400, "store:"),
        ("head in capitals", raw(dict(good, head=good["head"].upper())), 400, "head:"),
        ("head 63 digits", raw(dict(good, head=good["head"][:63])), 400, "head:"),
        ("head with a trailing LF", raw(dict(good, head=good["head"] + "\n")), 400, "head:"),
        ("head in Arabic-Indic digits", raw(dict(good, head="٠" * 64)), 400, "head:"),
        ("at with no Z", raw(dict(good, at=AT[:-1])), 400, "at:"),
        ("at with an offset", raw(dict(good, at=AT[:-1] + "+00:00")), 400, "at:"),
        ("at on 30 February", raw(dict(good, at="2027-02-30T00:00:00Z")), 400, "at:"),
        ("at at second 60", raw(dict(good, at="2027-01-15T07:59:60Z")), 400, "at:"),
        ("at with a trailing LF", raw(dict(good, at=AT + "\n")), 400, "at:"),
        ("sig padded", raw(dict(good, sig=good["sig"] + "==")), 400, "sig:"),
        ("sig 85 characters", raw(dict(good, sig=good["sig"][:85])), 400, "sig:"),
        ("sig in the standard alphabet", raw(dict(good, sig=good["sig"][:-1] + "+")), 400, "sig:"),
        ("sig whose last character a lenient decoder reads the same", raw(dict(good, sig=lenient)), 400, "sig:"),
        ("a bad field before an unknown store", raw(dict(stranger.request(1), seq=0)), 400, "seq:"),
        # 4. a store not registered, or retired
        ("a store never registered", raw(stranger.request(1)), 403, "not registered"),
        ("an unknown store before a bad signature", raw(stranger.request(1, signer=s.key)), 403, "not registered"),
        ("a retired store", raw(retired.request(1)), 403, "not registered"),
        # 5. a signature that does not verify
        ("signed by another key", raw(s.request(2, signer=stranger.key)), 403, "signature does not verify"),
        ("signed over other bytes", raw(dict(good, head=sha("other"))), 403, "signature does not verify"),
        ("a bad signature before the rate", raw(s.request(2, signer=stranger.key)), 403, "signature does not verify"),
    ]
    before = tree(data)
    wrong = []
    for name, body, want, says in cases:
        status, _, out = notary.post(body)
        if status != want or says not in json.loads(out)["error"] or tree(data) != before:
            wrong.append((name, status, out[:200], changed(before, tree(data))))
    assert wrong == []


def test_malformed_bodies_through_the_server_get_their_stated_status_and_write_nothing(data, issuer, clock, server):
    """Through the real handler on 127.0.0.1, whose own body parse once ran first: 200,000 '[' made json.loads raise
    RecursionError there (16,910 on Python 3.14; about 1,001 on 3.11 and earlier), and the request got no answer."""
    s = registered(data)
    assert notary.post(s.body(1))[0] == 200
    good = s.request(2)
    cases = [
        ("200,000 '[', too deep for json and over 4 KB", b"[" * 200_000, 413),
        ("16,910 '[', the depth that broke the handler's parse on Python 3.14", b"[" * 16_910, 413),
        ("an oversized request that is valid JSON", json.dumps(dict(good, pad="x" * 5000)).encode(), 413),
        ("4,000 '[', under 4 KB", b"[" * 4000, 400),
        ("1,001 nested lists, valid JSON under 4 KB", b"[" * 1001 + b"]" * 1001, 400),
        ("2,000 nested lists, valid JSON under 4 KB", b"[" * 2000 + b"]" * 2000, 400),
        ("not JSON", b"not json at all", 400),
        ("an empty body", b"", 400),
        ("not UTF-8", b'{"store": "\xff"}', 400),
    ]
    before = tree(data)
    for name, body, want in cases:
        status, headers, out = ask(server, "POST", "/notary", body)
        assert (status, headers["Content-Type"]) == (want, "application/json; charset=utf-8"), (name, out[:200])
        assert "nothing was written" in json.loads(out)["error"], name
        assert tree(data) == before, name
    assert ask(server, "GET", "/notary/key")[0] == 200                      # and the server still answers
    assert ask(server, "POST", "/notary", s.body(2))[0] == 429               # by the rules, in their order


def test_a_retirement_committed_while_a_post_waits_for_the_lock_is_seen(data, issuer, clock, monkeypatch):
    """The store's status is read inside the POST's BEGIN IMMEDIATE, never before it: a retirement that holds the write
    lock when the POST asks for it, and commits while the POST waits, refuses that POST."""
    s = registered(data)
    assert notary.post(s.body(1))[0] == 200
    clock.now += 60
    retiring = sqlite3.connect(str(data / "notary" / "notary.db"), isolation_level=None, timeout=5)
    retiring.execute("BEGIN IMMEDIATE")                                  # the retirement, as the CLI writes it
    retiring.execute("UPDATE stores SET status = 'retired', retired_at = ? WHERE name = 'store-a'",
                     (notary.utc(clock()),))
    asking, real = threading.Event(), sqlite3.connect

    class Asks(sqlite3.Connection):
        def execute(self, sql, *a):
            if sql.strip() == "BEGIN IMMEDIATE":
                asking.set()
            return super().execute(sql, *a)
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: real(*a, **dict(k, factory=Asks)))
    answers = []
    post = threading.Thread(target=lambda: answers.append(notary.post(s.body(2))))
    post.start()
    try:
        assert asking.wait(30)                               # the POST asks for the lock the retirement holds
        assert post.is_alive()                               # and waits for it
    finally:
        retiring.execute("COMMIT")
        retiring.close()
    post.join(30)
    status, _, out = answers[0]
    assert status == 403 and "not registered" in json.loads(out)["error"]
    assert rows(data, "store-a") == 1


def test_the_rate_is_one_new_checkpoint_a_minute_counted_after_the_signature(data, issuer, clock, server):
    s = registered(data)
    forger = Ed25519PrivateKey.generate()
    assert notary.post(s.body(1))[0] == 200
    clock.now = T0 + 59
    before = tree(data)
    status, headers, body = ask(server, "POST", "/notary", s.body(2))
    assert status == 429 and headers["Retry-After"] == "1" and json.loads(body)["retry_after"] == 1
    assert tree(data) == before
    for _ in range(5):                                       # a stranger who knows the name, signing with another key
        assert notary.post(s.body(3, signer=forger))[0] == 403
    assert notary.post(s.body(1))[0] == 200                 # a retry inside the minute is answered, not limited
    assert tree(data) == before
    clock.now = T0 + 60
    assert notary.post(s.body(2))[0] == 200
    clock.now = T0 + 180
    for _ in range(5):
        assert notary.post(s.body(3, signer=forger))[0] == 403
    assert notary.post(s.body(3))[0] == 200                 # the forged requests counted for nothing
    clock.now = T0 + 200                                     # conflicts share the rate
    assert notary.post(s.body(3, head=sha("rewritten")))[0] == 429
    clock.now = T0 + 240
    assert notary.post(s.body(3, head=sha("rewritten")))[0] == 409
    clock.now = T0 + 299
    assert notary.post(s.body(4))[0] == 429                 # the conflict at 240 holds the next new one to 300
    clock.now = T0 + 300
    assert notary.post(s.body(4))[0] == 200


# ── at once ──────────────────────────────────────────────────────────────────────────────────────────
CHILD = r'''
import json, os, sys, time
from concordance import notary
go, body = sys.argv[1], sys.argv[2].encode("utf-8")
print("ready", flush=True)
while not os.path.exists(go):
    time.sleep(0.001)
status, headers, out = notary.post(body)
print(json.dumps({"status": status, "body": out.decode("utf-8")}), flush=True)
'''


def child_env(data: Path, issuer: Issuer) -> dict:
    return dict(os.environ, PYTHONPATH=str(SRC), CONCORDANCE_DATA_DIR=str(data), CONCORDANCE_ISSUER_KEY=issuer.seed)


def at_once(how: str, bodies: list, server_port: int, data: Path, issuer: Issuer, tmp_path: Path) -> list:
    """Send every body at the same moment: from threads through the server, or from processes of their own."""
    if how == "threads":
        barrier, answers = threading.Barrier(len(bodies)), [None] * len(bodies)

        def send(i):
            barrier.wait()
            status, _, out = ask(server_port, "POST", "/notary", bodies[i])
            answers[i] = (status, out)
        threads = [threading.Thread(target=send, args=(i,)) for i in range(len(bodies))]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        return answers
    go = tmp_path / "go"
    procs = [subprocess.Popen([sys.executable, "-c", CHILD, str(go), b.decode("utf-8")], env=child_env(data, issuer),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for b in bodies]
    for p in procs:
        assert p.stdout.readline().strip() == "ready"
    go.write_text("go", encoding="utf-8")
    answers = []
    for p in procs:
        out, err = p.communicate(timeout=60)
        assert p.returncode == 0, err
        line = json.loads(out.strip().splitlines()[-1])
        answers.append((line["status"], line["body"].encode("utf-8")))
    return answers


@pytest.mark.parametrize("how", ["threads", "processes"])
def test_the_same_seq_sent_at_once_gives_one_receipt(how, data, issuer, server, tmp_path):
    s = registered(data)
    answers = at_once(how, [s.body(1), s.body(1)], server, data, issuer, tmp_path)
    assert [a[0] for a in answers] == [200, 200] and answers[0][1] == answers[1][1]
    assert rows(data, "store-a") == 1


@pytest.mark.parametrize("how", ["threads", "processes"])
def test_two_new_seqs_sent_at_once_give_one_200_one_429_and_one_row(how, data, issuer, server, tmp_path, monkeypatch):
    monkeypatch.setattr(notary, "clock", Clock())            # the processes use real time, inside one second
    s = registered(data)
    answers = at_once(how, [s.body(1), s.body(2)], server, data, issuer, tmp_path)
    assert sorted(a[0] for a in answers) == [200, 429], answers
    assert rows(data, "store-a") == 1


# ── crashes ──────────────────────────────────────────────────────────────────────────────────────────
KILLED = r'''
import sys, time
from pathlib import Path
from concordance import notary
con = notary._writer(Path(sys.argv[1]))
con.execute("PRAGMA cache_size=-16")
con.execute("BEGIN IMMEDIATE")
con.execute("UPDATE stores SET receipts = receipts + 400, conflicts_total = 77 WHERE name = ?", (sys.argv[2],))
for n in range(2, 402):
    con.execute("INSERT INTO receipts (store, n, seq, receipt, hash, store_sig) VALUES (?, ?, ?, ?, ?, ?)",
                (sys.argv[2], n, n + 1000, "x" * 3000, "0" * 64, "s"))
print("inside", flush=True)
time.sleep(300)
'''


class _Server:
    """Stands in for the HTTP server, so serve() runs its start without binding."""
    server_address = ("127.0.0.1", 0)

    def __init__(self, *_a):
        pass

    def serve_forever(self):
        pass


def start_the_server(monkeypatch) -> None:
    monkeypatch.setattr(http_api, "use_cells", lambda: None)
    monkeypatch.setattr(http_api, "ThreadingHTTPServer", _Server)
    monkeypatch.setattr(http_api, "_start_watchdog", lambda address: None)
    http_api.serve("127.0.0.1", 0, background=True)


def test_a_process_killed_inside_a_write_leaves_reads_503_until_the_server_starts(data, issuer, clock, monkeypatch):
    s = registered(data)
    notary.post(s.body(1))
    db = data / "notary" / "notary.db"
    status, receipt, page = get("/notary/stores/store-a"), get("/notary/stores/store-a/1"), \
        get("/notary/stores/store-a", "after=0")
    proc = subprocess.Popen([sys.executable, "-c", KILLED, str(db), "store-a"], env=child_env(data, issuer),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip() == "inside", proc.stderr.read()
    finally:
        proc.kill()
        proc.wait(60)
    journal = db.with_name("notary.db-journal")
    assert journal.exists()                                  # left hot by the kill
    before = tree(data)
    for path, query in (("/notary/stores/store-a", ""), ("/notary/stores/store-a/1", ""),
                        ("/notary/stores/store-a", "after=0"), ("/notary/stores/store-a/402", "")):
        answer = get(path, query)
        assert answer[0] == 503, (path, answer)              # never 404, never a half-written read
    assert tree(data) == before                              # a read rolls nothing back and creates nothing
    start_the_server(monkeypatch)                            # its one read-write open rolls the journal back
    assert not journal.exists()
    assert get("/notary/stores/store-a") == status
    assert get("/notary/stores/store-a/1") == receipt
    assert get("/notary/stores/store-a", "after=0") == page
    assert body_of(status)["receipts"] == 1 and body_of(status)["conflicts_total"] == 0


CRASH = r'''
import os, sys
from concordance import notary
answer = notary._answer
def crash(status, text, headers=None):
    if status == 200:
        os._exit(9)
    return answer(status, text, headers)
notary._answer = crash
notary.post(sys.argv[1].encode("utf-8"))
'''


def test_a_crash_between_the_commit_and_the_answer_keeps_the_receipt_and_the_retry_returns_it(data, issuer, clock):
    s = registered(data)
    body = s.body(1)
    done = subprocess.run([sys.executable, "-c", CRASH, body.decode("utf-8")], env=child_env(data, issuer),
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 9, done.stderr
    assert sorted(tree(data)) == ["notary", "notary/notary.db"]          # committed whole: no journal left
    kept = get("/notary/stores/store-a/1")
    assert kept[0] == 200 and checker().check(json.loads(kept[2]), issuer.public, s.public) == []
    status, _, again = notary.post(body)
    assert status == 200 and again == kept[2]
    assert body_of(get("/notary/stores/store-a"))["receipts"] == 1


# ── reads ────────────────────────────────────────────────────────────────────────────────────────────
def test_reads_and_refusals_with_no_notary_folder_or_no_file_create_nothing(data, issuer, clock, server, monkeypatch):
    stranger = Store("store-a")
    for setup in ("no folder", "a folder and no file"):
        if setup == "a folder and no file":
            (data / "notary").mkdir()
        before = tree(data)
        for path in ("/notary/stores/store-a", "/notary/stores/store-a/1", "/notary/stores/store-a?after=0&limit=5"):
            status, _, out = ask(server, "GET", path)
            assert (status, out) == (404, NOT_FOUND), (setup, path)
        assert ask(server, "GET", "/notary/key")[0] == 200
        assert ask(server, "POST", "/notary", stranger.body(1))[0] == 403
        start_the_server(monkeypatch)                        # the start-time open is skipped, and the server starts
        assert tree(data) == before, setup
    assert not (data / "notary" / "notary.db").exists()


def test_every_read_opens_the_file_read_only_and_changes_nothing(data, issuer, clock, monkeypatch):
    s = registered(data)
    notary.post(s.body(1))
    uris, real = [], sqlite3.connect

    def spy(*a, **k):
        uris.append(a[0])
        return real(*a, **k)
    monkeypatch.setattr(sqlite3, "connect", spy)
    before = tree(data)
    for path, query in (("/notary/stores/store-a", ""), ("/notary/stores/store-a/1", ""),
                        ("/notary/stores/store-a/2", ""), ("/notary/stores/store-a", "after=0&limit=1"),
                        ("/notary/stores/store-b", ""), ("/notary/key", "")):
        get(path, query)
    assert uris and all(u.startswith("file:") and u.endswith("?mode=ro") for u in uris), uris
    assert tree(data) == before


def test_status_and_reading_back_in_the_order_notaryed(data, issuer, clock, server):
    s = registered(data)
    for seq in (5, 2, 9):                                    # any order: n counts in the order V3 witnessed them
        assert notary.post(s.body(seq))[0] == 200
        clock.now += 60
    receipts = [json.loads(get(f"/notary/stores/store-a/{seq}")[2]) for seq in (5, 2, 9)]
    st = body_of(get("/notary/stores/store-a"))
    assert st == {"store": "store-a", "status": "registered", "receipts": 3, "last_n": 3,
                  "last_hash": receipts[2]["hash"], "conflicts_total": 0}
    page = body_of(get("/notary/stores/store-a", "after=0&limit=2"))
    assert page["receipts"] == receipts[:2] and page["next_after"] == 2 and (page["after"], page["limit"]) == (0, 2)
    assert body_of(get("/notary/stores/store-a", "after=2"))["receipts"] == receipts[2:]
    assert body_of(get("/notary/stores/store-a", "after=2"))["limit"] == 100            # after alone: limit 100
    alone = body_of(get("/notary/stores/store-a", "limit=500"))
    assert alone["after"] == 0 and alone["receipts"] == receipts                        # limit alone: after 0
    assert body_of(get("/notary/stores/store-a", "after=3"))["receipts"] == []
    status, _, out = ask(server, "GET", "/notary/stores/store-a?after=1&limit=1")
    assert status == 200 and json.loads(out)["receipts"] == receipts[1:2]
    for query in ("limit=0", "limit=501", "after=-1", "after=x", "limit=x", "after=", "limit=", "after=1.5",
                  "after=01", "limit=+5", "after=0&after=1", "after=0&other=1", "other=1", "after"):
        status, _, out = get("/notary/stores/store-a", query)
        assert status == 400, (query, out)
        assert ask(server, "GET", "/notary/stores/store-a?" + query)[0] == 400, query
    for path in ("/notary/stores/store-b", "/notary/stores/store-b/1", "/notary/stores/store-a/4",
                 "/notary/stores/store-a/0", "/notary/stores/store-a/01", "/notary/stores/store-a/x",
                 "/notary/stores/Store-a", "/notary/stores/store-a/1/2", "/notary/stores/"):
        assert get(path)[1:] == ({"Content-Type": "application/json; charset=utf-8"}, NOT_FOUND)
        assert get(path)[0] == 404, path
    assert get("/notary/stores/store-b", "after=0") == get("/notary/stores/store-a/4")   # unknown store = unknown seq


def test_every_read_uses_a_unique_index(data, issuer, clock):
    s = registered(data)
    notary.post(s.body(1))
    want = {"store": "SEARCH stores USING INDEX sqlite_autoindex_stores_1 (name=?)",
            "by_seq": "SEARCH receipts USING INDEX receipts_by_seq (store=? AND seq=?)",
            "hash_at": "SEARCH receipts USING INDEX receipts_by_n (store=? AND n=?)",
            "page": "SEARCH receipts USING INDEX receipts_by_n (store=? AND n>?)",
            "walk": "SEARCH receipts USING INDEX receipts_by_n (store=?)",
            "kept": "SEARCH conflicts USING COVERING INDEX conflicts_by_k (store=?)"}
    assert sorted(notary.QUERIES) == sorted(want)
    con = sqlite3.connect((data / "notary" / "notary.db").resolve().as_uri() + "?mode=ro", uri=True)
    try:
        for name, sql in notary.QUERIES.items():
            params = (1,) * sql.count("?")
            plan = " | ".join(row[-1] for row in con.execute("EXPLAIN QUERY PLAN " + sql, params))
            plan = re.sub(r"\b(SEARCH|SCAN) TABLE ", r"\1 ", plan)      # SQLite before 3.36 wrote SEARCH TABLE x
            assert plan == want[name], (name, plan)
    finally:
        con.close()


# ── durability ───────────────────────────────────────────────────────────────────────────────────────
def spy_on_commits(monkeypatch) -> tuple:
    """Every statement any connection runs, as (how it was opened, statement), and each committing connection's
    journal mode and synchronous level at its commit."""
    commits, statements, real = [], [], sqlite3.connect

    class Spy(sqlite3.Connection):
        opened = "?"

        def execute(self, sql, *a):
            statements.append((self.opened, sql.strip()))
            if sql.strip().upper() == "COMMIT":
                commits.append((super().execute("PRAGMA journal_mode").fetchone()[0],
                                super().execute("PRAGMA synchronous").fetchone()[0]))
            return super().execute(sql, *a)

    def connect(*a, **k):
        k["factory"] = Spy
        con = real(*a, **k)
        con.opened = "read-only" if str(a[0]).endswith("?mode=ro") else "writing"
        return con
    monkeypatch.setattr(sqlite3, "connect", connect)
    return commits, statements


def test_every_writing_connection_runs_in_journal_mode_delete_with_synchronous_extra(data, issuer, clock, monkeypatch,
                                                                                      capsys):
    from concordance.__main__ import main
    commits, statements = spy_on_commits(monkeypatch)
    s = Store("store-a")
    assert main(["notary", "register", "store-a", s.public, "--data-dir", str(data)]) == 0      # the CLI's
    assert commits == [("delete", 3)]
    del statements[:]
    assert notary.post(s.body(1))[0] == 200                                                   # the service's
    assert [sql for how, sql in statements if sql.upper().startswith("BEGIN")] == ["BEGIN IMMEDIATE"]
    clock.now += 60
    assert notary.post(s.body(1, head=sha("other")))[0] == 409
    assert notary.post(s.body(2))[0] == 429
    assert main(["notary", "retire", "store-a", "--data-dir", str(data)]) == 0
    assert notary.route("GET", "/notary/stores/store-a", "", b"")[0] == 200
    assert commits == [("delete", 3)] * 4
    begins = [(how, sql) for how, sql in statements if sql.upper().startswith("BEGIN")]
    assert ("writing", "BEGIN IMMEDIATE") in begins and ("read-only", "BEGIN") in begins
    assert all(sql == "BEGIN IMMEDIATE" for how, sql in begins if how == "writing"), begins   # the lock before any read
    reads = {sql for how, sql in statements if sql.upper().startswith("SELECT")}
    assert reads <= set(notary.QUERIES.values()), reads - set(notary.QUERIES.values())
    assert sorted(p.name for p in (data / "notary").iterdir()) == ["notary.db"]                # no -wal, no -shm


# ── no key, no public log, the capability statement ─────────────────────────────────────────────────
def test_with_no_issuer_key_every_route_answers_503_and_writes_nothing(data, clock, monkeypatch, server):
    monkeypatch.delenv("CONCORDANCE_ISSUER_KEY", raising=False)
    s = registered(data)
    before = tree(data)
    for bad_key in (None, "not-a-key"):
        if bad_key:
            monkeypatch.setenv("CONCORDANCE_ISSUER_KEY", bad_key)
        for method, path, body in (("POST", "/notary", s.body(1)), ("GET", "/notary/key", None),
                                   ("GET", "/notary/stores/store-a", None), ("GET", "/notary/stores/store-a/1", None),
                                   ("GET", "/notary/stores/store-a?after=0", None), ("GET", "/notary/other", None)):
            status, _, out = ask(server, method, path, body)
            assert status == 503 and "issuer key" in json.loads(out)["error"], (bad_key, path, out)
    assert tree(data) == before
    assert capabilities._notary_entry()["kid"] is None


def test_with_publish_on_nothing_reaches_rekor_or_any_seal_store(data, issuer, clock, monkeypatch, server):
    from concordance import cas, ledger
    monkeypatch.setenv("CONCORDANCE_PUBLISH", "1")                    # the box publishes seals by default
    reached = []

    def tripwire(name):
        def tripped(*a, **k):
            reached.append(name)
            raise AssertionError(f"{name} was reached")
        return tripped
    for name in ("attest", "publish", "_post", "_get", "lookup", "envelope", "dsse_envelope", "pq_envelope"):
        monkeypatch.setattr(transparency, name, tripwire("transparency." + name))
    monkeypatch.setattr(urllib.request, "urlopen", tripwire("urlopen"))
    for name in ("store", "store_spec", "_mint_receipt_card"):
        monkeypatch.setattr(cas, name, tripwire("cas." + name))
    for name in ("seal_to_ledger", "seal_record", "_write_head"):
        monkeypatch.setattr(ledger, name, tripwire("ledger." + name))
    s = registered(data)
    assert ask(server, "POST", "/notary", s.body(1))[0] == 200
    assert ask(server, "POST", "/notary", s.body(1))[0] == 200
    clock.now += 60
    assert ask(server, "POST", "/notary", s.body(1, head=sha("other")))[0] == 409
    for path in ("/notary/key", "/notary/stores/store-a", "/notary/stores/store-a/1", "/notary/stores/store-a?after=0"):
        assert ask(server, "GET", path)[0] == 200
    assert reached == []
    assert sorted(tree(data)) == ["notary", "notary/notary.db"]      # no CAS, no ledger, no sidecar


def test_capabilities_names_the_routes_and_the_kid_and_no_store(data, issuer, clock):
    registered(data, "store-opaque-q7x2")
    stated = capabilities.statement()
    assert stated["notary"]["routes"] == notary.ROUTES
    assert stated["notary"]["kid"] == stated["transparency"]["kid"] == issuer.kid
    assert "store-opaque-q7x2" not in json.dumps(stated)
    assert notary.ROUTES == ["POST /notary", "GET /notary/key", "GET /notary/stores/<store>",
                              "GET /notary/stores/<store>/<seq>",
                              "GET /notary/stores/<store>?after=<n>&limit=<1..500>"]


# ── the bound: a year at the rate limit ──────────────────────────────────────────────────────────────
YEAR = 525_600                                                         # one checkpoint a minute for 365 days


@pytest.mark.slow
def test_a_year_at_the_rate_limit_reads_by_index_and_the_file_is_deleted(data, issuer, clock):
    """525,600 rows for one store, at the size a real receipt has. checker-96 measured 579 MB, built in 12.2 s, a read
    by seq in 0.05 ms and a page of 500 in 2 ms (2026-11-09). This prints what it measures and deletes its file."""
    s = registered(data)
    template = json.loads(notary.post(s.body(1))[2])
    db = data / "notary" / "notary.db"
    try:
        began = time.perf_counter()
        con = notary._writer(db)
        con.execute("BEGIN IMMEDIATE")

        def rows_of_a_year():
            prev = template["hash"]
            for n in range(2, YEAR + 1):
                h = sha(f"receipt {n}")
                r = dict(template, seq=n, head=sha(f"head {n}"), prev=prev, hash=h)
                prev = h
                yield ("store-a", n, n, json.dumps(r, separators=(",", ":")), h, template["store_sig"])
        con.executemany("INSERT INTO receipts (store, n, seq, receipt, hash, store_sig) VALUES (?, ?, ?, ?, ?, ?)",
                        rows_of_a_year())
        con.execute("UPDATE stores SET receipts = ? WHERE name = 'store-a'", (YEAR,))
        con.execute("COMMIT")
        con.close()
        built = time.perf_counter() - began
        size = db.stat().st_size
        by_seq, pages = [], []
        for i in range(200):
            seq = 1 + (i * 2_654_435_761) % YEAR
            t = time.perf_counter()
            answer = get(f"/notary/stores/store-a/{seq}")
            by_seq.append(time.perf_counter() - t)
            assert answer[0] == 200 and json.loads(answer[2])["seq"] == seq
        for after in (0, YEAR // 2, YEAR - 500):
            t = time.perf_counter()
            page = body_of(get("/notary/stores/store-a", f"after={after}&limit=500"))
            pages.append(time.perf_counter() - t)
            assert len(page["receipts"]) == 500 and page["next_after"] == after + 500
        st = body_of(get("/notary/stores/store-a"))
        assert (st["receipts"], st["last_n"]) == (YEAR, YEAR)
        by_seq.sort()
        print(f"\na year at the rate limit: {YEAR:,} rows, {size / 1e6:.0f} MB, built in {built:.1f} s; "
              f"a read by seq (median of 200) {by_seq[100] * 1000:.2f} ms; a page of 500 at most {max(pages) * 1000:.1f} ms")
        assert size < 1_000_000_000
        assert by_seq[100] < 0.1 and max(pages) < 1.0        # three orders above the measure: a bound, not a race
    finally:
        for p in (db, db.with_name("notary.db-journal")):
            p.unlink(missing_ok=True)
    assert not db.exists()
