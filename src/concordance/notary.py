"""notary: V3 keeps a copy of another log's chain head and answers with a receipt signed by its issuer key.

A store is a name registered with an Ed25519 public key. It sends a checkpoint, its chain's head at a sequence number,
signed over the request bytes. V3 checks the signature, keeps the checkpoint, and answers with a receipt over the
receipt bytes, signed with the issuer key (CONCORDANCE_ISSUER_KEY). Anyone holding the receipt and V3's public key can
then prove V3 saw that head at that seq at that time, with no call to V3. docs/NOTARY.md is the specification,
docs/notary_vectors.json holds the exact bytes, and docs/verify_notary.py checks a receipt offline.

It belongs in the core, not the .org application, because it signs with the issuer key, which never leaves V3. A
receipt is not a seal: it enters no CAS, no ledger and no public log, and nothing here calls transparency.attest,
transparency.publish or anything else that reaches Rekor, whatever CONCORDANCE_PUBLISH says.

The store on disk is one SQLite file, <data dir>/notary/notary.db, in rollback-journal mode. Every connection that
writes sets synchronous EXTRA when it opens: a commit in that mode is the journal's deletion, and only EXTRA syncs the
directory after it, so a receipt V3 has answered is one it has kept. Every write is one BEGIN IMMEDIATE transaction
that holds the write lock from before the store's status, rate, seq and prev reads until the commit. Reads open the
file read-only by URI, take no lock file and create nothing. Only registration creates the folder and the file.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import parse_qsl

PREFIX = "/notary"
REQUEST_FORMAT = "concordance-notary-request/v1"
FORMAT = "concordance-notary/v1"
GENESIS = "genesis"
MAX_BODY = 4096                 # bytes in a POST body
MAX_SEQ = 2 ** 53 - 1           # the largest integer a double holds exactly
RATE_S = 60                     # one newly witnessed checkpoint, or one conflict, per store per minute
CONFLICTS_KEPT = 100            # conflicting requests kept per store; past that they are counted
PAGE_DEFAULT, PAGE_MAX = 100, 500
BUSY_S = 5.0                    # how long a request waits for another writer's lock
FIELDS = ("store", "seq", "head", "at", "sig")
RECEIPT_FIELDS = ("format", "kid", "store", "storekey", "seq", "head", "at", "witnessed_at", "prev", "hash", "sig",
                  "store_sig")
ROUTES = ["POST /notary", "GET /notary/key", "GET /notary/stores/<store>", "GET /notary/stores/<store>/<seq>",
          "GET /notary/stores/<store>?after=<n>&limit=<1..500>"]

_STORE = re.compile(r"[a-z0-9][a-z0-9-]{2,62}")
_HEAD = re.compile(r"[0-9a-f]{64}")
_TIME = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})Z")
_B64U = re.compile(r"[A-Za-z0-9_-]+")
_DECIMAL = re.compile(r"0|[1-9][0-9]{0,15}")

clock = time.time               # where "now" comes from; a test puts its own clock here

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS stores (name TEXT PRIMARY KEY, public_key TEXT NOT NULL,"
    " status TEXT NOT NULL CHECK (status IN ('registered', 'retired')), registered_at TEXT NOT NULL,"
    " retired_at TEXT, receipts INTEGER NOT NULL DEFAULT 0, conflicts_total INTEGER NOT NULL DEFAULT 0,"
    " last_event_at INTEGER)",
    "CREATE TABLE IF NOT EXISTS receipts (store TEXT NOT NULL, n INTEGER NOT NULL, seq INTEGER NOT NULL,"
    " receipt TEXT NOT NULL, hash TEXT NOT NULL, store_sig TEXT NOT NULL)",
    "CREATE UNIQUE INDEX IF NOT EXISTS receipts_by_n ON receipts (store, n)",
    "CREATE UNIQUE INDEX IF NOT EXISTS receipts_by_seq ON receipts (store, seq)",
    "CREATE TABLE IF NOT EXISTS conflicts (store TEXT NOT NULL, k INTEGER NOT NULL, seq INTEGER NOT NULL,"
    " request TEXT NOT NULL, received_at TEXT NOT NULL)",
    "CREATE UNIQUE INDEX IF NOT EXISTS conflicts_by_k ON conflicts (store, k)",
)

# Every read this module makes. Each goes through a unique index (tests/test_notary.py reads their query plans).
QUERIES = {
    "store": "SELECT public_key, status, receipts, conflicts_total, last_event_at FROM stores WHERE name = ?",
    "by_seq": "SELECT receipt FROM receipts WHERE store = ? AND seq = ?",
    "hash_at": "SELECT hash FROM receipts WHERE store = ? AND n = ?",
    "page": "SELECT receipt FROM receipts WHERE store = ? AND n > ? ORDER BY n LIMIT ?",
    "walk": "SELECT n, seq, receipt, hash, store_sig FROM receipts WHERE store = ? ORDER BY n",
    "kept": "SELECT count(*) FROM conflicts WHERE store = ?",
}
# The CLI's listing reads the whole stores table, a row per store, by its primary key.
LIST_STORES = ("SELECT name, status, public_key, receipts, conflicts_total, registered_at, retired_at FROM stores"
               " ORDER BY name")

_JSON = {"Content-Type": "application/json; charset=utf-8"}
NOT_FOUND = '{"error": "not found"}'
NOT_REGISTERED = "store: not registered, or retired; nothing was written"


# ── forms ────────────────────────────────────────────────────────────────────────────────────────────
def store_ok(v: Any) -> bool:
    return isinstance(v, str) and _STORE.fullmatch(v) is not None


def seq_ok(v: Any) -> bool:
    return type(v) is int and 1 <= v <= MAX_SEQ           # type, not isinstance: True is an int to Python


def head_ok(v: Any) -> bool:
    return isinstance(v, str) and _HEAD.fullmatch(v) is not None


def time_ok(v: Any) -> bool:
    """YYYY-MM-DDTHH:MM:SSZ, and a real UTC time: no 30 February, no second 60."""
    m = _TIME.fullmatch(v) if isinstance(v, str) else None
    if m is None:
        return False
    try:
        datetime(*(int(g) for g in m.groups()), tzinfo=timezone.utc)
    except ValueError:
        return False
    return True


def b64u_text(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def b64u(text: Any, nbytes: int) -> Optional[bytes]:
    """Strict base64url: exactly the length nbytes encodes to without padding, only the url-safe alphabet, and text
    that re-encodes to itself, so no two texts decode to the same bytes. None for anything else."""
    if not isinstance(text, str) or len(text) != -(-nbytes * 4 // 3) or _B64U.fullmatch(text) is None:
        return None
    raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    if len(raw) != nbytes or b64u_text(raw) != text:
        return None
    return raw


def key_id(raw_public_key: bytes) -> str:
    """'ed25519:' and the first 16 hex of the SHA-256 of the 32 raw key bytes, as transparency.issuer_kid computes."""
    return "ed25519:" + hashlib.sha256(raw_public_key).hexdigest()[:16]


def utc(seconds: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(seconds)))


def request_bytes(store: str, seq: int, head: str, at: str) -> bytes:
    """What a store signs: the format line, then store, seq, head and at, each ended by LF."""
    return f"{REQUEST_FORMAT}\n{store}\n{seq}\n{head}\n{at}\n".encode("utf-8")


def receipt_bytes(kid: str, store: str, storekey: str, seq: int, head: str, at: str, witnessed_at: str,
                  prev: str) -> bytes:
    """What V3 signs: the format line, then kid, store, storekey, seq, head, at, witnessed_at and prev, each ended by LF."""
    return f"{FORMAT}\n{kid}\n{store}\n{storekey}\n{seq}\n{head}\n{at}\n{witnessed_at}\n{prev}\n".encode("utf-8")


def _verifies(public_key: bytes, message: bytes, sig: bytes) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(sig, message)
        return True
    except (InvalidSignature, ValueError):
        return False


# ── the file ─────────────────────────────────────────────────────────────────────────────────────────
def data_dir(explicit: Any = None) -> Path:
    if explicit is not None:
        return Path(explicit)
    return Path(os.environ.get("CONCORDANCE_DATA_DIR", "").strip() or "data")


def db_path(data: Any = None) -> Path:
    return data_dir(data) / "notary" / "notary.db"


def _uri(db: Path, mode: str) -> str:
    return db.resolve().as_uri() + "?mode=" + mode


def _writer(db: Path, create: bool = False) -> sqlite3.Connection:
    """The one way this module opens the file to write: rollback journal, synchronous EXTRA, a 5 s busy timeout and
    transactions begun by hand. mode=rw never creates a missing file; only registration asks for rwc."""
    con = sqlite3.connect(_uri(db, "rwc" if create else "rw"), uri=True, timeout=BUSY_S, isolation_level=None)
    try:
        con.execute("PRAGMA journal_mode=DELETE")
        con.execute("PRAGMA synchronous=EXTRA")
    except BaseException:
        con.close()
        raise
    return con


def _reader(db: Path) -> sqlite3.Connection:
    """Read-only by URI: never creates the file, never rolls a journal back, takes no lock file."""
    return sqlite3.connect(_uri(db, "ro"), uri=True, timeout=BUSY_S, isolation_level=None)


def _close(con: sqlite3.Connection) -> None:
    try:
        if con.in_transaction:
            con.execute("ROLLBACK")
    finally:
        con.close()


def recover(data: Any = None) -> Optional[str]:
    """The server's one read-write open at start. A journal a crash left behind is rolled back here, before any read
    meets it (a read-only open cannot roll it back, and answers 503 until then). With no folder or no file there is
    nothing to open, and nothing is created. Returns a line to print, or None."""
    db = db_path(data)
    if not db.is_file():
        return None
    journal = db.with_name(db.name + "-journal")
    had = journal.exists()
    try:
        _close(_writer(db))
    except sqlite3.Error as e:
        return f"{db}: could not be opened to roll back an interrupted write ({e}); its reads answer 503"
    if had and not journal.exists():
        return f"{db}: rolled back a write that a crash interrupted"
    return None


# ── answers ──────────────────────────────────────────────────────────────────────────────────────────
def _answer(status: int, text: str, headers: Optional[Dict[str, str]] = None) -> Tuple[int, Dict[str, str], bytes]:
    return status, dict(_JSON, **(headers or {})), text.encode("utf-8")


def _error(status: int, message: str, extra: Optional[Dict[str, Any]] = None,
           headers: Optional[Dict[str, str]] = None) -> Tuple[int, Dict[str, str], bytes]:
    return _answer(status, json.dumps({"error": message, **(extra or {})}), headers)


def _not_found() -> Tuple[int, Dict[str, str], bytes]:
    return _answer(404, NOT_FOUND)


class Unavailable(Exception):
    """No usable issuer key: nothing can be signed, so nothing is served."""


def _issuer() -> Tuple[str, str, str]:
    """(private key, public key, kid) from CONCORDANCE_ISSUER_KEY, through the functions /capabilities uses."""
    from . import transparency
    priv = transparency.issuer_private_key()
    if not priv:
        raise Unavailable("no issuer key is configured (CONCORDANCE_ISSUER_KEY), so no receipt can be signed; "
                          "nothing was read or written")
    try:
        return priv, transparency.issuer_public_key(), transparency.issuer_kid()
    except Exception as e:  # noqa: BLE001
        raise Unavailable(f"the issuer key (CONCORDANCE_ISSUER_KEY) is not a usable Ed25519 key "
                          f"({type(e).__name__}); nothing was read or written") from None


def _unreadable(e: sqlite3.Error) -> Tuple[int, Dict[str, str], bytes]:
    return _error(503, "the store file cannot be read now (busy, or a write a crash interrupted waits for the "
                       f"server's restart to roll it back): {e}", headers={"Retry-After": "5"})


# ── the routes ───────────────────────────────────────────────────────────────────────────────────────
def route(method: str, path: str, raw_query: str, raw: bytes, data: Any = None):
    """Every /notary request. With no usable issuer key every route answers 503 and nothing is read or written."""
    try:
        _issuer()
    except Unavailable as e:
        return _error(503, str(e))
    parts = path.split("/")
    if path == PREFIX:
        return post(raw, data) if method == "POST" else _answer(405, '{"error": "POST only"}', {"Allow": "POST"})
    if method != "GET":
        return _answer(405, '{"error": "GET only"}', {"Allow": "GET"})
    if path == PREFIX + "/key":
        return key()
    if len(parts) == 4 and parts[2] == "stores":
        return status(parts[3], data) if raw_query == "" else page(parts[3], raw_query, data)
    if len(parts) == 5 and parts[2] == "stores":
        return receipt(parts[3], parts[4], data)
    return _not_found()


def key():
    priv, public, kid = _issuer()
    return _answer(200, json.dumps({"alg": "Ed25519", "kid": kid, "public_key": public, "format": FORMAT,
                                    "request_format": REQUEST_FORMAT}))


def _no_duplicates(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    if len({k for k, _ in pairs}) != len(pairs):
        raise ValueError("a key appears twice")
    return dict(pairs)


def _not_json(name: str):
    raise ValueError(f"{name} is not JSON")


def _parse(raw: bytes) -> Optional[Dict[str, Any]]:
    try:
        obj = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates, parse_constant=_not_json)
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    if not isinstance(obj, dict) or sorted(obj) != sorted(FIELDS):
        return None
    return obj


def _form(req: Dict[str, Any]) -> Optional[str]:
    """The first field outside its form, named, or None."""
    if not store_ok(req["store"]):
        return "store: must be a string matching [a-z0-9][a-z0-9-]{2,62}, nothing after it"
    if not seq_ok(req["seq"]):
        return "seq: must be a JSON integer from 1 to 2**53-1, never a boolean, a fraction or a string"
    if not head_ok(req["head"]):
        return "head: must be 64 lowercase hex digits, nothing after them"
    if not time_ok(req["at"]):
        return "at: must be a real UTC time written YYYY-MM-DDTHH:MM:SSZ, nothing after it"
    if b64u(req["sig"], 64) is None:
        return "sig: must be 86 characters of base64url without padding that re-encode to themselves (64 bytes)"
    return None


def post(raw: bytes, data: Any = None):
    """One checkpoint, by the rules in their order: the body's size, its shape, each field's form, the store's
    registration, its signature; then the rate, then the state. Every refusal writes nothing."""
    try:
        priv, _public, kid = _issuer()
    except Unavailable as e:
        return _error(503, str(e))
    if len(raw) > MAX_BODY:
        return _error(413, f"the body is over {MAX_BODY} bytes; nothing was written")
    req = _parse(raw)
    if req is None:
        return _error(400, "the body must be one JSON object with exactly the keys store, seq, head, at, sig; "
                           "nothing was written")
    bad = _form(req)
    if bad:
        return _error(400, bad)
    store, seq, head, at, sig_text = (req[k] for k in FIELDS)
    db = db_path(data)
    if not db.is_file():                                  # nothing is registered: a POST never creates the file
        return _error(403, NOT_REGISTERED)
    try:
        con = _writer(db)
    except sqlite3.Error as e:
        return _unreadable(e)
    try:
        try:
            con.execute("BEGIN IMMEDIATE")                # the write lock, held from before every read below
        except sqlite3.OperationalError as e:
            return _error(503, f"the store file is busy ({e}); nothing was written", headers={"Retry-After": "1"})
        row = con.execute(QUERIES["store"], (store,)).fetchone()
        if row is None or row[1] != "registered":
            return _error(403, NOT_REGISTERED)
        public_key, _status, count, _conflicts, last_event = row
        store_key = b64u(public_key, 32)
        if store_key is None or not _verifies(store_key, request_bytes(store, seq, head, at), b64u(sig_text, 64)):
            return _error(403, "the store signature does not verify over the request bytes; nothing was written")
        now = int(clock())
        old = con.execute(QUERIES["by_seq"], (store, seq)).fetchone()
        if old is not None:
            given = json.loads(old[0])
            if given["head"] == head and given["at"] == at:
                return _answer(200, old[0])               # a retry: the stored receipt, unchanged and uncounted
        wait = 0 if last_event is None else last_event + RATE_S - now
        if wait > 0:
            return _error(429, f"at most one new checkpoint or conflict per store per {RATE_S} s; nothing was "
                               f"written", {"retry_after": wait}, {"Retry-After": str(wait)})
        if old is not None:                               # the same seq with another head or at
            kept = con.execute(QUERIES["kept"], (store,)).fetchone()[0]
            keep = kept < CONFLICTS_KEPT
            if keep:
                con.execute("INSERT INTO conflicts (store, k, seq, request, received_at) VALUES (?, ?, ?, ?, ?)",
                            (store, kept + 1, seq, json.dumps({k: req[k] for k in FIELDS}), utc(now)))
            con.execute("UPDATE stores SET conflicts_total = conflicts_total + 1, last_event_at = ? WHERE name = ?",
                        (now, store))
            con.execute("COMMIT")
            message = (f"conflict: seq {seq} was witnessed with another head or at; the receipt given stands"
                       + ("" if keep else f"; past {CONFLICTS_KEPT} kept conflicts this one is counted, not kept"))
            return _answer(409, '{"error": ' + json.dumps(message) + ', "kept": ' + ("true" if keep else "false")
                           + ', "receipt": ' + old[0] + "}")
        n = count + 1
        prev = GENESIS
        if n > 1:
            got = con.execute(QUERIES["hash_at"], (store, n - 1)).fetchone()
            if got is None:
                return _error(503, f"the store's receipt n={n - 1} is missing; nothing was written")
            prev = got[0]
        witnessed_at = utc(now)
        storekey = key_id(store_key)
        signed = receipt_bytes(kid, store, storekey, seq, head, at, witnessed_at, prev)
        digest = hashlib.sha256(signed).hexdigest()
        from . import signing
        receipt_ = {"format": FORMAT, "kid": kid, "store": store, "storekey": storekey, "seq": seq, "head": head,
                    "at": at, "witnessed_at": witnessed_at, "prev": prev, "hash": digest,
                    "sig": signing.sign_bytes(signed, priv), "store_sig": sig_text}
        text = json.dumps(receipt_, separators=(",", ":"))
        con.execute("INSERT INTO receipts (store, n, seq, receipt, hash, store_sig) VALUES (?, ?, ?, ?, ?, ?)",
                    (store, n, seq, text, digest, sig_text))
        con.execute("UPDATE stores SET receipts = ?, last_event_at = ? WHERE name = ?", (n, now, store))
        con.execute("COMMIT")                             # kept before it is answered
        return _answer(200, text)
    except sqlite3.Error as e:
        return _error(503, f"the store file could not be written ({e}); nothing was written")
    finally:
        _close(con)


def _read(db: Path, work):
    """Run work(con) in one read transaction on a read-only connection. A missing file is the caller's 404; any SQLite
    error here (busy, or a journal a crash left) is 503, never a 404."""
    try:
        con = _reader(db)
    except sqlite3.Error as e:
        return _unreadable(e)
    try:
        con.execute("BEGIN")
        return work(con)
    except sqlite3.Error as e:
        return _unreadable(e)
    finally:
        try:
            _close(con)
        except sqlite3.Error:
            pass


def status(store: str, data: Any = None):
    db = db_path(data)
    if not store_ok(store) or not db.is_file():
        return _not_found()

    def work(con):
        row = con.execute(QUERIES["store"], (store,)).fetchone()
        if row is None:
            return _not_found()
        _key, state, count, conflicts, _last = row
        last = con.execute(QUERIES["hash_at"], (store, count)).fetchone() if count else None
        return _answer(200, json.dumps({"store": store, "status": state, "receipts": count,
                                        "last_n": count or None, "last_hash": last[0] if last else None,
                                        "conflicts_total": conflicts}))
    return _read(db, work)


def receipt(store: str, seq_text: str, data: Any = None):
    db = db_path(data)
    if not store_ok(store) or _DECIMAL.fullmatch(seq_text) is None or not 1 <= int(seq_text) <= MAX_SEQ \
            or not db.is_file():
        return _not_found()

    def work(con):
        row = con.execute(QUERIES["by_seq"], (store, int(seq_text))).fetchone()
        return _answer(200, row[0]) if row else _not_found()
    return _read(db, work)


def _page_args(raw_query: str):
    """(after, limit), or the reason the query is refused. after alone sets limit to 100; limit alone sets after to 0."""
    pairs = parse_qsl(raw_query, keep_blank_values=True)
    names = [k for k, _ in pairs]
    if not pairs or len(set(names)) != len(names) or not set(names) <= {"after", "limit"}:
        return "the query takes after=<n> and limit=<1..500>, each at most once, and nothing else"
    given = dict(pairs)
    after, limit = given.get("after", "0"), given.get("limit", str(PAGE_DEFAULT))
    if _DECIMAL.fullmatch(after) is None or int(after) > MAX_SEQ:
        return "after: must be a whole number from 0, written without sign or leading zero"
    if _DECIMAL.fullmatch(limit) is None or not 1 <= int(limit) <= PAGE_MAX:
        return f"limit: must be a whole number from 1 to {PAGE_MAX}, written without sign or leading zero"
    return int(after), int(limit)


def page(store: str, raw_query: str, data: Any = None):
    """The store's receipts with n greater than after, in the order V3 witnessed them. Each receipt is the exact
    text V3 answered when it witnessed it."""
    db = db_path(data)
    if not store_ok(store):
        return _not_found()
    args = _page_args(raw_query)
    if isinstance(args, str):
        return _error(400, args)
    after, limit = args
    if not db.is_file():
        return _not_found()

    def work(con):
        if con.execute(QUERIES["store"], (store,)).fetchone() is None:
            return _not_found()
        texts = [r[0] for r in con.execute(QUERIES["page"], (store, after, limit))]
        return _answer(200, '{"store": ' + json.dumps(store) + f', "after": {after}, "limit": {limit}, '
                            f'"next_after": {after + len(texts)}, "receipts": [' + ", ".join(texts) + "]}")
    return _read(db, work)


def capability() -> Dict[str, Any]:
    """The /capabilities entry: the routes and the kid that signs, and no store."""
    try:
        _priv, _public, kid = _issuer()
    except Unavailable:
        kid = None
    return {"routes": list(ROUTES), "kid": kid,
            "means": "a log's owner registers a key; its signed chain heads are checked, kept, and answered with "
                     "a receipt signed by the issuer key, which anyone can check offline (docs/NOTARY.md); "
                     "a receipt is not a seal and is never published"}


# ── registration (python -m concordance notary ...) ─────────────────────────────────────────────────
class Refused(Exception):
    """A command refused; nothing was written."""


def register(store: str, public_key: str, data: Any) -> Path:
    """Bind a new name to a store's key, in one transaction. Creates the folder and the file when they are missing,
    inside a data directory that must already exist. A name is never bound twice, even after it is retired."""
    if not store_ok(store):
        raise Refused("the name must match [a-z0-9][a-z0-9-]{2,62}, nothing after it")
    raw = b64u(public_key, 32)
    if raw is None:
        raise Refused("the key must be 43 characters of base64url without padding that re-encode to themselves "
                      "(32 bytes, a raw Ed25519 public key)")
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    try:
        Ed25519PublicKey.from_public_bytes(raw)
    except ValueError:
        raise Refused("the key is not an Ed25519 public key") from None
    base = data_dir(data)
    if not base.is_dir():
        raise Refused(f"the data directory {base.resolve()} does not exist")
    folder = base / "notary"
    if not folder.is_dir():
        folder.mkdir()
    db = folder / "notary.db"
    con = _writer(db, create=True)
    try:
        con.execute("BEGIN IMMEDIATE")
        for statement in SCHEMA:
            con.execute(statement)
        row = con.execute(QUERIES["store"], (store,)).fetchone()
        if row is not None:
            raise Refused(f"the name {store} is already used ({row[1]}): a name is never bound to a second key")
        con.execute("INSERT INTO stores (name, public_key, status, registered_at) VALUES (?, ?, 'registered', ?)",
                    (store, public_key, utc(clock())))
        con.execute("COMMIT")
    finally:
        _close(con)
    return db.resolve()


def retire(store: str, data: Any) -> Path:
    """Stop new checkpoints for a store, in one transaction. Its receipts stay readable and its name stays used."""
    if not store_ok(store):
        raise Refused("the name must match [a-z0-9][a-z0-9-]{2,62}, nothing after it")
    db = db_path(data)
    if not db.is_file():
        raise Refused(f"no store named {store}: there is no file at {db.resolve()}")
    con = _writer(db)
    try:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute(QUERIES["store"], (store,)).fetchone()
        if row is None:
            raise Refused(f"no store named {store}")
        if row[1] == "retired":
            raise Refused(f"{store} is already retired")
        con.execute("UPDATE stores SET status = 'retired', retired_at = ? WHERE name = ?", (utc(clock()), store))
        con.execute("COMMIT")
    finally:
        _close(con)
    return db.resolve()


def stores(data: Any) -> Tuple[Path, List[Tuple[Any, ...]]]:
    """Every store, read only. No file means no store, and nothing is created."""
    db = db_path(data)
    if not db.is_file():
        return db.resolve(), []
    con = _reader(db)
    try:
        return db.resolve(), con.execute(LIST_STORES).fetchall()
    finally:
        _close(con)


def verify(store: str, data: Any, issuer_public_key: str) -> Tuple[Path, int, Optional[str]]:
    """Walk a store's receipts in the order V3 witnessed them, read only: each receipt's fields and form, its row,
    its bytes' hash, V3's signature under the key given, the store's signature under its registered key, the prev
    link and the count. Returns (file, receipts walked, the first problem or None)."""
    db = db_path(data)
    issuer = b64u(issuer_public_key, 32)
    if issuer is None:
        raise Refused("the issuer key must be 43 characters of strict base64url (32 bytes)")
    if not store_ok(store) or not db.is_file():
        raise Refused(f"no store named {store} in {db.resolve()}")
    con = _reader(db)
    try:
        con.execute("BEGIN")
        row = con.execute(QUERIES["store"], (store,)).fetchone()
        if row is None:
            raise Refused(f"no store named {store} in {db.resolve()}")
        store_key = b64u(row[0], 32)
        count, kid, prev, walked = row[2], key_id(issuer), GENESIS, 0
        for n, seq, text, digest, store_sig in con.execute(QUERIES["walk"], (store,)):
            problem = _receipt_problem(n, walked + 1, seq, text, digest, store_sig, store, store_key, issuer, kid, prev)
            if problem:
                return db.resolve(), walked, f"n={walked + 1} (seq {seq}): {problem}"
            walked, prev = n, digest
    finally:
        _close(con)
    if walked != count:
        return db.resolve(), walked, f"the store's row counts {count} receipts and {walked} were found"
    return db.resolve(), walked, None


def _receipt_problem(n, expected_n, seq, text, digest, store_sig, store, store_key, issuer, kid, prev) -> Optional[str]:
    if n != expected_n:
        return f"receipt n={expected_n} is missing (the next is n={n})"
    try:
        r = json.loads(text)
    except ValueError:
        return "its JSON does not parse"
    if not isinstance(r, dict) or list(r) != list(RECEIPT_FIELDS):
        return "it does not hold exactly the receipt's fields, in order"
    if r["format"] != FORMAT or r["store"] != store or r["seq"] != seq or r["hash"] != digest \
            or r["store_sig"] != store_sig:
        return "its fields disagree with its row"
    if not (seq_ok(r["seq"]) and head_ok(r["head"]) and time_ok(r["at"]) and time_ok(r["witnessed_at"])):
        return "a field is outside its form"
    if r["kid"] != kid:
        return f"it was signed by kid {r['kid']}, not by the key given ({kid})"
    if store_key is None or r["storekey"] != key_id(store_key):
        return "its storekey is not the registered key's"
    if r["prev"] != prev:
        return f"its prev is {r['prev']}, and the receipt before it hashes to {prev}"
    signed = receipt_bytes(r["kid"], r["store"], r["storekey"], r["seq"], r["head"], r["at"], r["witnessed_at"],
                           r["prev"])
    if hashlib.sha256(signed).hexdigest() != r["hash"]:
        return "its hash is not the SHA-256 of its bytes"
    sig = b64u(r["sig"], 64)
    if sig is None or not _verifies(issuer, signed, sig):
        return "V3's signature does not verify"
    ssig = b64u(r["store_sig"], 64)
    if ssig is None or not _verifies(store_key, request_bytes(r["store"], r["seq"], r["head"], r["at"]), ssig):
        return "the store's signature does not verify"
    return None


USAGE = """python -m concordance notary register <store> <public_key> [--data-dir D]
python -m concordance notary retire <store> [--data-dir D]
python -m concordance notary list [--data-dir D]
python -m concordance notary verify <store> [--key <V3 public key>] [--data-dir D]
--data-dir defaults to CONCORDANCE_DATA_DIR; verify's key defaults to the public half of CONCORDANCE_ISSUER_KEY.
--env-file F, on any command and any number of times, loads a systemd environment file as the service's unit does.
Exit 0 done, 1 refused (nothing was written), 2 a usage error."""


def _option(args: List[str], name: str) -> Optional[str]:
    if name not in args:
        return None
    i = args.index(name)
    if i + 1 >= len(args):
        raise Refused(f"{name} needs a value")
    value = args[i + 1]
    del args[i:i + 2]
    return value


def load_env_file(path: str) -> List[str]:
    """Set the variables a systemd EnvironmentFile names, as the service's unit sets them for the service: NAME=VALUE
    lines, blank lines and # or ; comments skipped, one pair of matching quotes taken off a value. Returns the names
    set, never a value: the file holds the issuer key."""
    names = []
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line or line.startswith(("#", ";")):
                continue
            name, eq, value = line.partition("=")
            name = name.strip()
            if not eq or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                raise Refused(f"{path}:{n} is not a NAME=VALUE line")
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            os.environ[name] = value
            names.append(name)
    return names


def cli(argv: Sequence[str]) -> int:
    args = list(argv)
    try:
        data, given_key = _option(args, "--data-dir"), _option(args, "--key")
        env_files = []
        while "--env-file" in args:
            env_files.append(_option(args, "--env-file"))
        for path in env_files:
            loaded = load_env_file(path)
            if data is not None and "CONCORDANCE_DATA_DIR" in loaded \
                    and Path(os.environ["CONCORDANCE_DATA_DIR"]).resolve() != Path(data).resolve():
                raise Refused(f"{path} sets CONCORDANCE_DATA_DIR to another directory than --data-dir; refusing "
                              f"rather than guess which one the service reads")
    except (Refused, OSError, UnicodeDecodeError) as e:
        print(f"{e}; nothing was written\n{USAGE}")
        return 2
    data = data if data is not None else (os.environ.get("CONCORDANCE_DATA_DIR", "").strip() or None)
    shapes = {"register": 3, "retire": 2, "list": 1, "verify": 2}
    if not args or args[0] not in shapes or len(args) != shapes[args[0]]:
        print(USAGE)
        return 2
    if data is None:
        print("no data directory: pass --data-dir or set CONCORDANCE_DATA_DIR; nothing was written")
        return 2
    command = args[0]
    try:
        if command == "register":
            db = register(args[1], args[2], data)
            print(f"registered {args[1]} with storekey {key_id(b64u(args[2], 32))}; wrote {db}")
        elif command == "retire":
            db = retire(args[1], data)
            print(f"retired {args[1]}: it takes no new checkpoint, its receipts stay readable, and its name is never "
                  f"bound again; wrote {db}")
        elif command == "list":
            db, rows = stores(data)
            print(f"read {db}")
            if not rows:
                print("no store is registered")
            for name, state, public_key, receipts, conflicts, registered_at, retired_at in rows:
                raw = b64u(public_key, 32)
                print(f"{name}  {state}  storekey={key_id(raw) if raw else '?'}  public_key={public_key}  "
                      f"receipts={receipts}  conflicts={conflicts}  registered={registered_at}  "
                      f"retired={retired_at or '-'}")
        else:
            if given_key is None:
                try:
                    given_key = _issuer()[1]
                except Unavailable:
                    print("no key to check V3's signatures with: pass --key <V3 public key> or set "
                          "CONCORDANCE_ISSUER_KEY")
                    return 2
            db, walked, problem = verify(args[1], data, given_key)
            print(f"read {db}")
            if problem:
                print(f"{args[1]}: {problem}")
                return 1
            print(f"{args[1]}: {walked} receipts; every hash, signature and prev link holds")
    except Refused as e:
        print(f"refused: {e}; nothing was written")
        return 1
    except sqlite3.Error as e:
        print(f"the store file could not be used ({e}); nothing was written")
        return 1
    return 0


__all__ = ["route", "post", "key", "status", "receipt", "page", "recover", "capability", "register", "retire",
           "stores", "verify", "cli", "request_bytes", "receipt_bytes", "key_id", "b64u", "FORMAT",
           "REQUEST_FORMAT", "ROUTES", "QUERIES"]
