# The notary service: a receipt for a log's chain head

A system that keeps a hash chain of its own records (an operations log, a ledger, an audit trail) sends V3 its
chain's head from time to time, signed with its own key. V3 checks the signature, keeps a copy, and answers with a
**receipt** signed by V3's issuer key. Later, anyone holding that receipt and V3's public key can prove that V3 saw
that head at that sequence number at that time, with no call to V3. A rewrite inside the system's own database cannot
forge it.

This page is the whole specification: an integrator in any language builds from it alone. The exact bytes are in
[notary_vectors.json](notary_vectors.json), and [verify_notary.py](verify_notary.py) checks a receipt offline.

## What a receipt proves, and what it does not

- It proves V3 saw that head, at that seq, for that store, at `witnessed_at`. It says nothing of what the records under
  the head hold.
- A chain rewritten before its first witnessed checkpoint is not caught.
- It is only as strong as V3's key. `GET /notary/key` serves only the current key. Key rotation, with old keys still
  served for old receipts, and a second, independent notary are not built.
- A store's key lives with the store. A thief who holds it can send heads in the store's name. A second head at a seq
  V3 has already witnessed still exposes that: it is answered 409, and the conflicting request is kept with the
  store's own signature, which proves what was sent without trusting V3.
- A receipt is not a seal. It enters no content-addressed store, no ledger, no receipt card and no `/seals` listing,
  and it is never sent to a public transparency log, whatever `CONCORDANCE_PUBLISH` says.

## The address

V3 serves these routes at its own root. On the public host the proxy sends `/v3/*` to V3 with the prefix removed, so
the public address is `https://api.narrowhighway.com/v3/notary...`. Without `/v3` a request on that host reaches the
v2 engine, which does not serve these routes.

| route | answers |
|---|---|
| `POST /notary` | one checkpoint from a registered store: its receipt (200), or a refusal |
| `GET /notary/key` | V3's public key and kid: `{"alg": "Ed25519", "kid", "public_key", "format", "request_format"}` |
| `GET /notary/stores/<store>` | the store's status (below) |
| `GET /notary/stores/<store>/<seq>` | the receipt V3 gave for that seq, byte for byte as it was answered |
| `GET /notary/stores/<store>?after=<n>&limit=<1..500>` | the store's receipts, in the order V3 witnessed them |

Store names live under `/notary/stores/`, so no name can collide with a route. With no issuer key configured, every
`/notary` route, the key route included, answers 503 and says so, and nothing is read or written.

## The store's bytes

The store signs, with Ed25519, these UTF-8 bytes, where `LF` is the byte 0x0A and every line ends with one:

```
concordance-notary-request/v1 LF store LF seq LF head LF at LF
```

| field | form (matched against the whole string; nothing after it, a trailing LF included) |
|---|---|
| `store` | `[a-z0-9][a-z0-9-]{2,62}` |
| `seq` | a JSON integer from 1 to 2^53−1 (9007199254740991): never a boolean, a fraction, an exponent or a string. In the bytes it is written in decimal, with no sign and no leading zero |
| `head` | `[0-9a-f]{64}`: the chain's head, 64 lowercase hex digits (a SHA-256, for example) |
| `at` | `YYYY-MM-DDTHH:MM:SSZ`, a real UTC time (no 30 February, no second 60): when the store made the checkpoint |

The request is one JSON object, UTF-8, at most 4096 bytes, with exactly the keys `store`, `seq`, `head`, `at`, `sig`
and no key twice. `sig` is the store's 64-byte signature in **strict base64url**: the url-safe alphabet
`A-Z a-z 0-9 - _`, no padding, and text that re-encodes to exactly itself, which is 86 characters for 64 bytes. A
registered public key is the 32 raw bytes of an Ed25519 public key in the same strict base64url, 43 characters.

Strict means a decoder that ignores the unused low bits of the last character is not enough: two different texts that
such a decoder reads as the same bytes are refused, all but the one that re-encodes to itself.

## V3's bytes and the receipt

V3 signs, with its issuer key, these UTF-8 bytes:

```
concordance-notary/v1 LF kid LF store LF storekey LF seq LF head LF at LF witnessed_at LF prev LF
```

- `kid` is V3's issuer key id: `ed25519:` and the first 16 hex digits of the SHA-256 of V3's 32 raw public key bytes,
  as `/capabilities` gives it for seals.
- `storekey` is the store's key id, computed the same way from the store's 32 raw public key bytes.
- `store`, `seq`, `head`, `at` are the request's.
- `witnessed_at` is V3's UTC time when it witnessed the checkpoint, in the same form as `at`.
- `prev` is the `hash` field of this store's previous receipt in the order V3 witnessed them (not the order of seq),
  or the word `genesis` for the store's first.

The receipt is one JSON object, with its fields in this order:

```
{"format", "kid", "store", "storekey", "seq", "head", "at", "witnessed_at", "prev", "hash", "sig", "store_sig"}
```

`format` is `concordance-notary/v1`; `hash` is the SHA-256 hex of V3's bytes; `sig` is V3's Ed25519 signature over
them, in strict base64url; `store_sig` is the store's own `sig` from the request. Because `kid` and `storekey` are
inside the signed bytes, a key change on either side shows in every receipt after it. The receipts of one store form a
chain by `prev`, so a store that holds them all can check that none is missing.

To check a receipt: rebuild V3's bytes from its fields, check `format`, check `kid` against V3's public key, check that
the SHA-256 of the bytes is `hash`, and verify `sig` over the bytes with V3's key. To check what the store sent,
rebuild the store's bytes and verify `store_sig` with the store's key. `python docs/verify_notary.py receipt.json
--key <V3 public key> [--store-key <store public key>]` does all of it.

## The rules, in this order

Each refusal writes nothing. The first rule a request breaks decides the answer.

| # | rule | answer |
|---|---|---|
| 1 | the body is over 4096 bytes | 413 |
| 2 | the body is not one UTF-8 JSON object with exactly the five keys, none twice | 400 |
| 3 | a field is outside its form (the error names it: `store:`, `seq:`, `head:`, `at:`, `sig:`) | 400 |
| 4 | the store is not registered, or is retired | 403 |
| 5 | the store's signature does not verify over the store's bytes | 403 |
| 6 | the same seq with the same head and the same at: a retry | 200, the stored receipt unchanged |
| 7 | the store had a newly witnessed checkpoint or a conflict less than 60 s ago | 429, with `Retry-After` |
| 8 | the same seq with a different head or a different at: a conflict | 409, with the receipt already given |
| 9 | a seq V3 has not witnessed for this store, whatever its place | 200, a new receipt |

- **A retry is always safe.** It is answered before the rate and never counts toward it, so a store that lost an
  answer sends the same request again and gets the same receipt, byte for byte.
- **The rate**: per store, at most one newly witnessed checkpoint or conflict per minute, which fits a checkpoint
  cadence. It is counted only after the signature verifies, so knowing a store's name is not enough to hold it at 429.
  The 429 body is `{"error", "retry_after"}` and `Retry-After` gives the seconds to wait. The time of the last event is
  kept on disk, so a restart does not reset it.
- **A conflict** never replaces the receipt given. The 409 body is `{"error", "kept", "receipt"}`. The first 100
  conflicting requests of a store are kept with their store signatures; after that each conflict is counted in the
  store's `conflicts_total` and no longer kept. Conflicts share the rate, so a store's key cannot keep the disk busy.
- **Out of order is fine.** A store may send an older checkpoint after a newer one; it is witnessed in the order it
  arrives, and `prev` follows that order.
- 503 means V3 cannot answer now: no issuer key, the file busy past 5 s, or a write that a crash interrupted, which
  the server rolls back when it next starts. Nothing was written. 404 is the one answer for an unknown store and an
  unknown seq alike.

## Reading back

`GET /notary/stores/<store>` with no query answers the store's status:

```
{"store", "status": "registered" | "retired", "receipts", "last_n", "last_hash", "conflicts_total"}
```

`last_n` and `last_hash` are the newest receipt's place and hash, or `null` before the first.

`GET /notary/stores/<store>?after=<n>&limit=<k>` answers the store's receipts with place greater than `n`, in the
order V3 witnessed them (the first is place 1), so a store that lost its own copies can recover V3's:

```
{"store", "after", "limit", "next_after", "receipts": [<receipt>, ...]}
```

Each receipt is the exact text V3 answered when it witnessed it. Ask again with `after=<next_after>` until
`receipts` is empty. `after` alone sets `limit` to 100; `limit` alone sets `after` to 0. `after` is a whole number
from 0 and `limit` one from 1 to 500, written in decimal without sign or leading zero, each at most once and nothing
else in the query. Anything else is 400: `limit=0`, `limit=501`, `after=-1`, `after=x` or any other non-number, an
empty value, a key given twice, an unknown key.

**Names should be opaque.** Anyone who knows a store's name can read its status and its receipts, and the receipt
count gives away the chain's length. A name says nothing V3 checks, so choose one that says nothing about the system
it belongs to.

## Registration

A store's name is bound to its public key on V3's side, by the operator:

```
python -m concordance notary register <store> <public_key> [--data-dir D]
python -m concordance notary retire <store> [--data-dir D]
python -m concordance notary list [--data-dir D]
python -m concordance notary verify <store> [--key <V3 public key>] [--data-dir D]
```

`--data-dir` defaults to `CONCORDANCE_DATA_DIR`; with neither, the command refuses rather than guess, and it refuses
an environment file that names another data directory. Each command
writes in one transaction and prints the absolute path of the file it wrote or read. A name or key outside its form is
refused. A name is never bound twice: retiring keeps the store's receipts readable and leaves the name used for good,
so a store that changes its key takes a new name. `list` and `verify` only read, and create nothing. `verify` walks a
store's receipts in order, recomputing each hash, each signature and each `prev` link, and names the first that fails.
The service reads its stores on every request, so a registration or a retirement takes effect at once.

On the production host these run only through `deploy/notary_register.sh`, which reads the service's user, its
interpreter, its code, its data directory and its environment files from the `nh-v3` unit, refuses when the unit is
not active or runs as root, runs the command as that user with the unit's environment files, and reads the result back
with `notary list`. `--env-file F` loads a systemd environment file into the command's environment as the unit loads it
for the service, so `verify` finds the issuer key there; the file is read by the command itself, so the key is never an
argument and never printed.

## Storage

Everything lives in one SQLite file, `notary/notary.db` under the data directory: tables `stores`, `receipts` and
`conflicts`. It runs in rollback-journal mode, so no `-wal` or `-shm` file appears, and every connection that writes
sets `synchronous=EXTRA`: in that mode a commit is the journal's deletion, and only EXTRA syncs the directory after it,
so a receipt V3 has answered is one it has kept. Every POST is one `BEGIN IMMEDIATE` transaction that holds the write
lock from before the store's status, rate, seq and prev are read until the commit, with a busy timeout of 5 s. A crash
leaves the whole receipt or none of it. Reads open the file read-only, take no lock file and create nothing; only
registration creates the folder and the file. Every read goes through a unique index, on store and n or on store and
seq. One store at the rate limit for a year is 525,600 receipts. The slow test in `tests/test_notary.py` built that
twice on a laptop on 2026-11-09: a 456 MB file, in 12 and 13 s; one receipt read by seq through the service, opening
the file each time, in 0.5 and 0.9 ms (median of 200); a page of 500 in at most 4 and 20 ms. Retention and compaction
for many stores are not built.
