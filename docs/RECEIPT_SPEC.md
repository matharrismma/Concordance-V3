# Receipt specification — `concordance-receipt/3.0`

This is the versioned, open format of a Concordance receipt. The version id travels in the receipt itself,
in the attestation's `spec` field, so a consumer knows which rules apply; it is bumped on any change to the
envelope or attestation shape, and the record's own `content_hash` is unaffected (SEAL_SPEC.md). A committed
golden receipt (`tests/fixtures/receipt_golden.json`) and its conformance test
(`tests/test_receipt_conformance.py`) pin this format — the reference verifier validates the golden and
rejects tampered copies; regenerate the golden with `tools/mint_golden_receipt.py`.

A receipt is what `seal_fetch` (MCP) and `GET /s/<hash>` (HTTP) return. It has two parts: the **record**,
whose SHA-256 is its address, and the **attestation** beside it, which says who vouches for the record and
where that vouching is publicly logged. The attestation is never inside the hashed bytes, so a record's hash
is the same whether or not anyone has signed it, and a reader with no key material can still re-hash.

```
{
  ...record fields...,                 # see SEAL_SPEC.md; kind = seal | document
  "content_hash": "<64 hex>",          # sha256(canonical(record minus content_hash))
  "attest": {                          # absent → self-attested (content-addressed only)
    "envelope": { "format": "COSE_Sign1", "spec": "concordance-receipt/3.1",
                  "cose_sign1_b64": "...", "content_hash": "...",
                  "kid": "ed25519:<16 hex>", "public_key": "<b64url raw Ed25519>" },
    "pq":       { "format": "pq-detached", "alg": "ML-DSA-65",     # the durable signature (§2d)
                  "signature": "<b64url ML-DSA over the same canonical record bytes>",
                  "content_hash": "...", "kid": "ml-dsa-65:<16 hex>",
                  "public_key": "<b64url raw ML-DSA-65 public key>" },
    "in_toto":  { "payloadType": "application/vnd.in-toto+json",   # the same verdict, DSSE-wrapped (§2b)
                  "payload": "<b64 of an in-toto Statement v1>",
                  "signatures": [ { "keyid": "ed25519:<16 hex>", "sig": "<b64 Ed25519 over PAE>" } ],
                  "public_key": "<b64url raw Ed25519>" },
    "log":      { "service": "rekor", "kind": "rekord", "url": "https://rekor.sigstore.dev",
                  "uuid": "...", "index": 3428399704, "integrated_time": 1792795463, "log_id": "...",
                  "digest": "<sha256 of the statement bytes>",
                  "inclusion_proof": { "logIndex": ..., "treeSize": ..., "rootHash": "...", "hashes": [...] },
                  "signed_entry_timestamp": "..." }
                # or { "service": "rekor", "pending": true, "error": "<why>" }
  }
}
```

## 1. Canonical form and hash

`canonical(obj)` = JSON with sorted keys, separators `,` and `:`, `ensure_ascii=False`, encoded UTF-8 with
`surrogatepass`. `content_hash = sha256(canonical(record − {content_hash, attest}))`. This is the whole claim
of a seal (SEAL_SPEC.md); everything below is about who stands behind it.

## 2. The statement — COSE_Sign1 (RFC 9052)

`cose_sign1_b64` is standard base64 of a CBOR tag-18 array `[protected, unprotected, payload, signature]`.

| part | content |
|---|---|
| protected (bstr-wrapped CBOR map) | `1: -8` (EdDSA) · `3: "application/concordance-record+json"` · `4: <kid bytes>` · `15: {1: iss (kid), 2: sub (content_hash), 6: iat}` — the CWT Claims header (RFC 9597), the SCITT claims · `-70001: {content_hash, kind, verdict}` — the richer claim set, under a private-use label |
| unprotected | `{}` |
| payload | `canonical(record − {content_hash})` — so `sha256(payload) == content_hash` |
| signature | Ed25519 over `Sig_structure = CBOR(["Signature1", protected, b"", payload])` |

Verification needs only the issuer public key: check the signature over the Sig_structure, then check
`sha256(payload)` equals both the header's `content_hash` and the receipt's. `kid` is
`"ed25519:" + sha256(raw public key)[:16]` — a label for key rotation, not a trust anchor; the public key
itself travels in the envelope and in the log entry. Pin the public key of an issuer you trust; `kid` tells
you which one to pin.

## 2a. Standards alignment

The envelope is a COSE_Sign1 (RFC 9052) Signed Statement in the SCITT shape
(`draft-ietf-scitt-architecture`, `draft-noa-scitt-ai-agent-receipt`), and it carries the registered CWT
Claims header (RFC 9597, COSE header label 15) with CWT claims (RFC 8392): `iss` (1) = the issuer `kid`,
`sub` (2) = the `content_hash` (the subject), `iat` (6) = issuance time. They live in the protected header
only, so they cannot be swapped, and `verify_receipt.py` rejects a statement whose `sub` is not the payload
hash. A SCITT-aware consumer reads these directly; the richer Concordance claim set (`content_hash`, `kind`,
`verdict`) rides beside them under the private-use label `-70001`. Mapping the Concordance detail to
namespaced CWT claims is the remaining interchange work (the AgentLedger mapping below is done). The
`spec` field names the version a given receipt was minted under.

## 2b. The in-toto form — Statement v1 in a DSSE envelope

The same verdict is also emitted as an in-toto Statement v1 (`https://in-toto.io/Statement/v1`) wrapped in a
DSSE envelope, carried at `attest.in_toto`, for in-toto / SLSA consumers. The Statement's `subject` is the
record (`digest.sha256 = content_hash`); its `predicateType` is this engine's
(`…/attestations/verdict/v1`); its `predicate` is `{verdict, kind, content_hash, spec}`. The DSSE signature
is Ed25519 over `PAE(payloadType, body)` with `payloadType = application/vnd.in-toto+json` — the type is
bound into the signed bytes (the CVE-2022-35929 lesson). Today it is signed with the issuer key; the
production path is keyless (Fulcio / OIDC) and logged to Rekor, with the same structure.

## 2c. The AgentLedger form — proof-of-behavior fields

For an [AgentLedger proof-of-behavior](https://datatracker.ietf.org/doc/html/draft-dembowski-agentledger-proof-of-behavior-00)
consumer, `seal_fetch` also carries `attest.agentledger` (`transparency.agentledger_pob`): the signed,
hash-chained, per-tool_call shape. It is a **view** of the same receipt, not a second attestation —
`payload_hash` is the verified input's `spec_hash`, `result_hash` is the record's `content_hash`,
`prev_hash` is the prior node in this engine's hash-chained ledger (`GENESIS` at the root), `verdict` and
`iat` come from the record and its ledger node, and the `signature` is the record's own COSE_Sign1 (Ed25519)
over `result_hash`, which verifies with `verify_receipt.py`/`verify_envelope` under the issuer key. Like
PoB itself, it records behaviour, not correctness: the verdict says only what was checked. A sealed record
that was never chained (a non-PASS verdict is sealed but not ledgered) reports `chained: false` and a null
`prev_hash`.

## 2d. The durable form — ML-DSA (FIPS 204, lattice / LWE)

A receipt is meant to prove something *permanently*, but Ed25519 rests on the elliptic-curve discrete
log — a problem a quantum computer breaks (the frontier of that attack is Regev's own 2023 factoring
result). An adversary can archive today's receipts and public keys and, once quantum arrives, recover
the private key and forge any of them, backdated. So the receipt carries a second, independent
signature whose hardness survives that: **ML-DSA-65** (FIPS 204), the NIST module-lattice standard,
descended from Regev's Learning-With-Errors. It is at `attest.pq`, signed over the **same** canonical
record bytes the Ed25519 statement covers (`canonical(record − {content_hash, attest})`), so it binds
the same `content_hash`; verification needs only the ML-DSA public key. We do not roll it — it is the
`cryptography` library's vetted FIPS 204 implementation.

Both signatures ride together on purpose (crypto-agility): Ed25519 for today's compact tooling and the
SCITT/Rekor path, ML-DSA for permanence. `verify_receipt.py` reports each on its own line; a receipt is
**durable** when the ML-DSA line passes. A receipt with only the Ed25519 statement is valid today but
says so plainly — not durable past a quantum adversary. The standards path is the RFC 9964 COSE encoding
of ML-DSA once its algorithm ids are pinned; until then the block is self-describing.

Why a lattice is the right floor to stand on: a lattice is a perfect, periodic symmetry. LWE hides a
secret by adding a small error that breaks that symmetry just enough to look like random noise — and
recovering the symmetry from the distorted samples is the worst-case-hard problem the signature rests
on. A forged receipt is exactly an attempt to recover that symmetry without the key; it cannot be done.
The receipt is the concrete, checkable form of that hardness.

## 3. The log entry — Rekor `rekord`

The statement bytes are registered on a Sigstore Rekor instance as a `rekord` (apiVersion 0.0.1):
`spec.data.content` = the statement bytes, `spec.signature` = `{format: "x509", content: <Ed25519 over the
statement bytes>, publicKey: {content: <PKIX PEM>}}`. Rekor verifies that signature before admitting the
entry, so an entry that exists is itself a check. `hashedrekord` is not used because Rekor admits Ed25519
there only in its pre-hashed (SHA-512) form.

A reader fetches `GET {url}/api/v1/log/entries/{uuid}` and checks: the body is a `rekord`; its data hash
equals `sha256(statement bytes)` (Rekor returns the hash, not the bytes, on read-back); its public key is the
issuer key; and the inclusion proof reproduces `rootHash` with RFC 6962 hashing (`leaf = sha256(0x00‖body)`,
`node = sha256(0x01‖left‖right)`). `integrated_time` is the earliest moment the record provably existed.

Duplicate publication returns the existing entry (HTTP 409 → same uuid). A failed publication is a
`pending` claim with the error; `tools/publish_seals.py` retries. Pending is a fact about the log, not about
the record.

## 4. Refutation semantics — what a verdict is not

The engine attempts refutations; it does not establish truth. Each `verifier_results[].data.refutations` is

```
{ "attempted": [check, ...], "survived": [check, ...],
  "counterexamples": [{check, what, claimed, recomputed, band: [low, high], off_by}, ...],
  "errored": [...], "not_applicable": [...],
  "bands": [{check, what, low, high, actual, claimed, tolerance, inside, off_by, unit}, ...] }
```

and `gate_results[0].details` carries `read` (one sentence) and the totals. A **band** is the interval every
true claim must lie in, `[actual − tol, actual + tol]`; `inside` is a survived refutation, `outside` a
counterexample. `not_applicable` names the checks this verifier owns that could not fire on this packet — the
honest edge of what was tested. A reader treats HOLDS as "no counterexample among the attempted checks" and
never as "true"; a counterexample is re-runnable from the sealed packet (`spec_hash`) and outranks any number
of survivals. Verifiers that have not yet adopted `band()` report status only; their `refutations` lists are
still correct, their `bands` empty.

### 4a. Margin and the trace — the OTDR view

Every band carries `used = |off_by| / tolerance` (0 = dead centre, 1 = the edge, >1 = outside; a bound
reports headroom as value/limit folded onto its constrained side). A step's `refutations.margin` is its
tightest band. The derivation's `trace` is the chain shot like a fiber span: one event per step with
`distance` (depth in the `uses` graph), `event` (`pass` | `reflection` = counterexample | `dark` = could not
run), `used`, and for a reflection `off_by`. `trace.budget` is the worst event — the link budget — and its
`read` is sealed into `gate_results[0].details.budget`. Each event also carries its `stratum` — `pure`
(commits to a rulebook: mathematics, number theory, logic, …) or `applied` (commits to data and a band) — and
`stands_on`, every step beneath it transitively; the floor under each is its `spec_hash`, the commitment to
exactly these bytes. A reflection whose `stands_on` all passed gets a `fault_locus`: `data` for an applied step
(the math beneath it held; the input did not), `rule` for a pure one. A HOLDS at 98% of its allowance is a pass you would
redo before building on it; the trace is where you see that.

### 4b. The smallest bucket

A hash table is the floor's data structure, and the memo is built on it: a step is keyed by
`sha256({spec_hash, domain, engine version, verifier source fingerprint})`. A hit serves the verdict, detail,
data and refutations stored the first time — never a recompute — and says so: the trail entry carries
`memo {hit, key, verified_at, engine, verifier}`, the trace event `bucket: hit | miss`, the sealed record
`data.bucket {hit, verified_at, engine}`, and the page a "served from the bucket" line. The key carries the
verifier's own source hash, so changed code can never serve a stale verdict; ERRORs (timeouts, malformed
input) are never memoised. `CONCORDANCE_MEMO=0` disables it. Everything above is buckets composed: a band is a
neighborhood of buckets, a chain is buckets linked by `uses`, a document is a bucket of chains.

## 5. Documents

A `kind: document` record is a root over steps (`spec_hash`, status, `uses`), a `derivation_seal` and
`parents`. Its attestation covers the root only; each `spec_hash`, the derivation seal and each parent is a
record of its own with its own attestation. Walk the tree by fetching each one and running the same checks.

## 6. Reference verifier

`docs/verify_receipt.py` (≈200 lines; imports nothing from this repo) runs the four checks and prints one
line per check plus the document tree. The hash check is pure Python standard library — a reader with no
dependencies installed can re-hash a record and confirm its `content_hash`; the signature and log checks
import `cbor2` and `cryptography` lazily, only when they run. Exit 0 iff every check that could run passed.
`--offline` skips the live log fetch and uses the entry held in the receipt (if any); `--public-key` pins a
key instead of trusting the one in the envelope. `tests/test_receipt_conformance.py` runs these same
functions against the golden receipt and against tampered copies, so the independent check is known to pass
a real receipt and reject a forged one.

## 7. What this does and does not establish

It establishes that a specific issuer key signed exactly these record bytes, and that a public, append-only
log witnessed that statement no later than `integrated_time`. It does not establish that the issuer key
belongs to who you think it does (pin it), nor anything about the claim beyond what the verdict already says
(arithmetic and formula application — never suitability). A record with no attestation is still a record:
its hash still binds it; it simply has no one vouching that it was produced by a particular engine at a
particular time.
