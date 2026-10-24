# Receipt specification — v3.0

A receipt is what `seal_fetch` (MCP) and `GET /s/<hash>` (HTTP) return. It has two parts: the **record**,
whose SHA-256 is its address, and the **attestation** beside it, which says who vouches for the record and
where that vouching is publicly logged. The attestation is never inside the hashed bytes, so a record's hash
is the same whether or not anyone has signed it, and a reader with no key material can still re-hash.

```
{
  ...record fields...,                 # see SEAL_SPEC.md; kind = seal | document
  "content_hash": "<64 hex>",          # sha256(canonical(record minus content_hash))
  "attest": {                          # absent → self-attested (content-addressed only)
    "envelope": { "format": "COSE_Sign1", "cose_sign1_b64": "...", "content_hash": "...",
                  "kid": "ed25519:<16 hex>", "public_key": "<b64url raw Ed25519>" },
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
| protected (bstr-wrapped CBOR map) | `1: -8` (EdDSA) · `3: "application/concordance-record+json"` · `4: <kid bytes>` · `-70001: {content_hash, kind, verdict}` — the claim set, under a private-use label |
| unprotected | `{}` |
| payload | `canonical(record − {content_hash})` — so `sha256(payload) == content_hash` |
| signature | Ed25519 over `Sig_structure = CBOR(["Signature1", protected, b"", payload])` |

Verification needs only the issuer public key: check the signature over the Sig_structure, then check
`sha256(payload)` equals both the header's `content_hash` and the receipt's. `kid` is
`"ed25519:" + sha256(raw public key)[:16]` — a label for key rotation, not a trust anchor; the public key
itself travels in the envelope and in the log entry. Pin the public key of an issuer you trust; `kid` tells
you which one to pin.

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

## 5. Documents

A `kind: document` record is a root over steps (`spec_hash`, status, `uses`), a `derivation_seal` and
`parents`. Its attestation covers the root only; each `spec_hash`, the derivation seal and each parent is a
record of its own with its own attestation. Walk the tree by fetching each one and running the same checks.

## 6. Reference verifier

`docs/verify_receipt.py` (≈190 lines; depends on `cbor2` and `cryptography`, imports nothing from this repo)
runs the four checks and prints one line per check plus the document tree. Exit 0 iff every check that could
run passed. `--offline` skips the live log fetch and uses the entry held in the receipt (if any);
`--public-key` pins a key instead of trusting the one in the envelope.

## 7. What this does and does not establish

It establishes that a specific issuer key signed exactly these record bytes, and that a public, append-only
log witnessed that statement no later than `integrated_time`. It does not establish that the issuer key
belongs to who you think it does (pin it), nor anything about the claim beyond what the verdict already says
(arithmetic and formula application — never suitability). A record with no attestation is still a record:
its hash still binds it; it simply has no one vouching that it was produced by a particular engine at a
particular time.
