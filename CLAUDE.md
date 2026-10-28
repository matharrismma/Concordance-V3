# Concordance V3 — working notes for Claude Code

Read this first. Then `README.md`, `MEASURED.md`, and `docs/plans/V3_PLAN.md` / `PRODUCT_PLAN.md` for where
the work is going. Do not reinterpret the plan inside the code; execute it.

## What this is

A deterministic verification engine: a **claim** goes in as a packet, a **verifier** recomputes it, a
**verdict** comes out (`HOLDS | PARTIAL | BROKEN | INCOMPLETE | SCHEMA_ERROR | SYSTEM_ERROR`) with the worked
trail and a **seal** — the SHA-256 of the canonical record, stored content-addressed, ledgered in an
append-only hash chain, signed (COSE_Sign1, Ed25519) and logged on Rekor when an issuer key is configured.
Documents are trees of sealed steps with one root hash. The scribe module scores many writers against one
datum. Eight MCP tools, one stdlib HTTP API. It checks arithmetic and formula application — never whether a
correct number is safe, lawful, or suitable; that caveat rides in every receipt.

It is **stand-alone and synthetic-data only.** Nothing from the owner's employer (no JDA memos, names, figures,
or vocabulary) enters this repo, its fixtures, its docs, or its examples. The fixture memo is invented.

## Non-negotiables (CI enforces most of them)

- **Lean core.** The lazy import closure from the 8 tools must stay ⊆ `CORE_MODULES.txt` (`tools/closure.py`;
  the CI job diffs it). Adding a module means adding it to the entrypoints line in `.github/workflows/ci.yml`
  *and* regenerating `CORE_MODULES.txt` — and being able to say why it belongs in the core rather than in the
  .org application. Target ≤ 40 top-level modules; currently 34 (incl. __init__ and __main__).
- **Eight tools.** `tool_registry.py` is the single source of truth. Anything else is an application's
  business and registers on its own server in front of this one. Do not add a ninth.
- **One canonical form, one hash.** `validate.canonical_json_bytes` is the only serialisation that is hashed.
  Provenance (`attest`) rides *beside* a record, never inside the hashed bytes. Never rewrite `data/ledger/`.
- **Not a truth engine.** A numeric check names the band (`band()`) or bound (`bound()`) a true claim must
  respect; HOLDS is a survived refutation, BROKEN a re-runnable counterexample. New checks use these, never a bare
  `confirm`/`mismatch` on a numeric comparison. `read` and `refutations` travel with every verdict and into the seal.
- **A measurement is never served from the bucket.** `bucket.py` memoises verdicts for production; the suite
  (conftest), the benchmark, the coverage gate and the mutation tool all run with `CONCORDANCE_MEMO=0`. A gate
  that reads a memo measures nothing — the coverage gate dropped to 2/443 the first time this was forgotten.
- **Benchmark 0 false positives.** `tools/benchmark.py --check` (1,796 cases, four tiers). A verifier change
  that drops a case must be explained in `MEASURED.md`, not deleted from the data.
- **Coverage gate.** `tools/unreached.py`: every `verify_*` function either executes under the benchmark or
  has a stated reason in its `ALLOWED` table. Zero unexplained gaps.
- **Schemas generated, not written.** `tools/schema_gen.py --check`; `SCHEMA_ERROR` must name the field and its
  nearest valid name. Golden pairs for every domain (`tests/test_schema_covers_goldens.py`).
- **Vocabulary gate.** `tools/vocab_gate.py`: no organisational/house vocabulary in user-visible strings or docs.
  Say what the thing is.
- **Suite ≤ 60 s.** Anything slower goes behind `-m slow` (runs nightly).
- **No new deps in the core.** stdlib HTTP. Optional extras are `math`, `signing` (cryptography + cbor2),
  `scribe` (numpy), `schema`. Import them lazily inside the function that needs them.
- **Measure, then claim.** Every number in `README.md` or `MEASURED.md` comes from a tool in `tools/`. If you
  can't measure it, don't write it. Publish the negative result too (the mutation score is not 100% and says so).

## Layout

```
src/concordance/
  derivation.py   steps → trail; `bind`/`uses` chain outputs into inputs
  verifiers/      one module per domain; ARTIFACT_KEY packets; plugins via entry-point group concordance.verifiers
  schema.py       AST-derived packet schemas; validate_steps
  receipts.py cas.py ledger.py signing.py   seal, store, chain, keys
  bucket.py       the smallest bucket: verdict memo keyed by (spec_hash, domain, engine, verifier fingerprint)
  transparency.py COSE_Sign1 statements, Rekor rekord publication, attest sidecars (docs/RECEIPT_SPEC.md)
  compose.py      documents: trees of sealed steps, one root
  audit.py slotfill.py text.py discern.py    plain-text → packets, with honest coverage
  scribe/         claim matrix, SVD disagreement axis, recompute verdicts
  mcp/server.py http_api.py tool_registry.py capabilities.py
tools/            every gate and generator; `tools/check.py` runs them all
tests/            pytest; tests/SKIPPED_FROM_V2.txt lists what was deliberately left behind
docs/             SEAL_SPEC, RECEIPT_SPEC, RUNBOOK, BENCHMARK, ARCHITECTURE (generated), verify_receipt.py (no concordance import — keep it that way), plans/
deploy/           systemd unit (:8020), Caddy snippet, install.sh with gates and rollback
```

## Daily loop

```bash
pip install -e ".[math,scribe,signing,dev]"
PYTHONPATH=src python -m pytest -q                       # ≤ 60 s, must be green
PYTHONPATH=src python tools/check.py                     # all gates: closure, benchmark, schemas, unreached, vocab
PYTHONPATH=src python tools/architecture_gen.py          # after any module change (docs/ARCHITECTURE.md)
PYTHONPATH=src python -m concordance serve --port 8000   # then curl /verify, open /s/<hash>?html=1
```

Adding a verifier: write `verifiers/<domain>.py` with one `*_VERIFY` artifact key and `verify_*` functions
using `_check` with explicit tolerances → add golden pairs to `data/domain_goldens.json` → per-check goldens to
`data/check_goldens.jsonl` (`tools/harvest_goldens.py` helps) → `tools/schema_gen.py` → run the loop above →
record in `MEASURED.md` and `CHANGELOG.md`.

Changing a receipt field: `docs/SEAL_SPEC.md` / `RECEIPT_SPEC.md` first, then code, then
`docs/verify_receipt.py` if a stranger's check would change, then `tests/test_receipt_page.py` /
`test_transparency.py`.

## How to work here

- Build; don't strategise. The owner knows what he wants to build. Surface misalignment in one line and keep
  going. Terse, direct.
- When something is wrong, say so and fix it; don't soften it. Honest friction is expected.
- Before adding anything, ask whether it belongs in this core or in the .org application (`witness` repo, which
  calls this engine over HTTP via `NH_VERIFY_URL`). Default: it belongs over there.
- Prefer deleting a second way of doing something over documenting both.
- Commit messages: what changed and what was measured. End with the attribution lines the session provides.
- Owner-only steps (never attempt): GitHub Release, PyPI upload, running `deploy/install.sh` on the box, the
  Caddy route, `python -m concordance keygen` into the production `.env`.

## State (keep this section current)

- v3.0.0a0 tagged. CI green. 790 tests. Benchmark v2.2.0: 1,796 / 0 FP. Closure 54 modules.
- Inverted reading landed: band()/bound(), refutations manifest, counterexamples, scribe narrow_way. Band
  coverage 50.6% of attempted refutations (benchmark BANDS line); the rest are exact/boolean/symbolic by nature.
- Transparency layer live-proven against the public Rekor log (index 3428399704); production has no issuer
  key yet, so its receipts say "self-attested".
- Next per PRODUCT_PLAN M1/M2: listings (PyPI, MCP registries), scribe benchmark with non-Claude writers,
  a synthetic-memo pilot presented end to end, scorer packages (DeepEval/autoevals), LangGraph node.
