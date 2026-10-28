# Changelog

This project versions three surfaces together under semver — the Python library, the MCP tool set,
and the receipt format. See `docs/VERSIONING.md`.

## Unreleased
- Post-quantum durable receipts (`concordance-receipt/3.1`, additive). Beside the Ed25519 COSE
  statement, a receipt now carries `attest.pq`: an **ML-DSA-65** (FIPS 204, module-lattice / Regev's
  LWE) signature over the same canonical record bytes, binding the same `content_hash`. Ed25519 rests
  on a problem a quantum computer breaks; ML-DSA's hardness survives it, so a receipt proves its
  integrity permanently (crypto-agility: both ride together — Ed25519 for today's tooling, ML-DSA for
  permanence). `CONCORDANCE_PQ_ISSUER_KEY` enables it; `docs/verify_receipt.py` reports a `PQ-SIG`
  line and a receipt is "durable" when it passes; `transparency.pq_envelope` + `signing.pq_*` (the
  `cryptography` library's vetted FIPS 204 implementation — never rolled); RECEIPT_SPEC §2d. The
  golden receipt and conformance suite now pin the PQ signature too.

## 3.0.0a1 — 2026-10-24
- Receipt format named and pinned as an open standard, `concordance-receipt/3.0` (the version rides
  in the attestation's `spec`). The COSE_Sign1 statement now carries the registered CWT Claims
  header (RFC 9597, label 15) with CWT claims (RFC 8392: `iss` = kid, `sub` = content_hash, `iat`),
  so a SCITT-aware consumer reads it directly; the same verdict is also emitted as an in-toto
  Statement v1 in a DSSE envelope (`attest.in_toto`) for in-toto/SLSA consumers. The record's
  `content_hash` is unchanged. `tools/mint_golden_receipt.py` + `tests/test_receipt_conformance.py`
  validate the committed golden and reject tampered copies with the no-import `docs/verify_receipt.py`.
- Packaging and listings prepared (owner publishes): PyPI metadata and `[project.urls]`;
  `server.json` MCP-registry manifest; `docs/RUNBOOK.md` "Publishing and listings (owner only)".
- Harness adapters under `integrations/` (`concordance-integrations`, outside the lean core): a
  DeepEval metric + an autoevals/Braintrust scorer, a LangGraph/AutoGen verify node, and a
  Guardrails validator. One rule — `HOLDS` passes, `BROKEN` fails, everything else abstains (a claim
  the engine could not test is never scored a failure).
- Monte-Carlo fuzz (`tools/mc_fuzz.py`, seeded) over the engine invariants: no false certify, every
  seal re-verifies, bounded time and memory per verify, adversarial text never crashes or seals
  garbage. It found and this fixes a ReDoS: a long digit run made several extractor patterns
  backtrack for tens of seconds. `audit._clamp_digits` collapses any run longer than `MAX_DIGITS`
  (40) before recognition — removing only numbers the engine would never check, so the
  zero-false-positive guarantee is untouched. Pinned by `tests/test_redos_guard.py` and
  `tests/test_mc_fuzz.py`.
- Governance: `docs/VERSIONING.md` (semver across the three surfaces, deprecation policy) and
  `tests/test_public_api.py` (pins the tool set, the receipt spec id, the semver shape of the
  version, and the public exports; fails if the current version has no changelog entry).
- Recall: unit-anchored slot-fillers for Newton's second law (`x_force_units`) and kinematics
  (`x_kinematics_units`, with m/s-vs-m/s² lookaheads) reach claims the word-order regexes miss, any
  order, each slot exactly once — recall grows, 0 false positives unchanged.
- Interchange: `transparency.agentledger_pob` maps a receipt to the AgentLedger proof-of-behavior
  shape (`payload_hash`/`result_hash`/`prev_hash`, signed by the record's COSE_Sign1, chained on the
  engine's ledger); `seal_fetch` carries it at `attest.agentledger`. RECEIPT_SPEC §2c.

## 3.0.0a0 — 2026-10-23
- Core carved from v2 (`concordance-2`): 32 top-level modules, 8 MCP tools, stdlib HTTP API; the .org
  application (`witness`) calls it over HTTP and registers its own verifiers via entry points.
- Coverage: compound sentences report the unchecked clause; slot-fillers quote tight spans.
- Packet schemas generated for every domain; `SCHEMA_ERROR` names the field and its nearest valid name.
- `public_finance` verifier (amortization with interest-only prefix, issuance gross-up, ad valorem,
  depreciated value, abatement ladder, PV).
- `concordance.scribe`: many-writer claim matrix, SVD disagreement axis, recompute verdicts, UNDERDETERMINED.
- Benchmark v2.2.0: 1,669 cases over four tiers, 0 false positives; mutation tool.
- `compose.py`: documents as trees of sealed steps (`bind` inputs to earlier outputs), one root hash,
  parents, `/s/<root>?html=1` tree page with whole-chain re-check. Driven by a synthetic memo only.
- License: MIT.
- Transparency: `transparency.py` mints COSE_Sign1 (Ed25519) statements over every served record and logs them
  on Rekor as `rekord` entries (Rekor re-verifies the signature on admission); `attest` rides beside the record
  in `seal_fetch` / `/s/<hash>` and the receipt and tree pages; `python -m concordance keygen`;
  `tools/publish_seals.py` flushes pending entries; `docs/verify_receipt.py` checks hash, signature, log entry
  and Merkle inclusion with no Concordance import; `docs/RECEIPT_SPEC.md`. The v2 in-toto/DSSE `envelope.py`
  and `tools/publish_seal.py` are removed — one statement format, not two.
- Inverted reading — not a truth engine: `band()` / `bound()` in verifiers.base; `refutations` manifest and
  `read` sentence per verdict, sealed into the record; counterexamples (recomputed value, band, off_by) first-class;
  receipt page shows bands; scribe `narrow_way` (eliminated / surviving / [min, max] bracket). 68 verifier
  modules converted (260 checks), verdicts and tolerances unchanged; benchmark reports band coverage (50.6%).
- Context loop closed on every door: `airlock.strip_fields` de-identifies free-text fields in packets and
  documents with one stable map; `reveal_deep` puts context back into the response (never the seal);
  `context` in every verify/discern/scribe result names what travelled and where it was reapplied. Scribe
  writers see only the skeleton; `drafts_revealed` is the user's copy. compose strips title/labels/prose.
- Margin and trace: every band carries `used` (share of tolerance spent); each step a `margin`; each
  derivation a `trace` (OTDR view: distance = depth in `uses`, event = pass | reflection | dark, used, off_by)
  and a `budget` (the worst event), sealed into the gate details and shown on the receipt page.
- `bucket.py` — the smallest bucket: a verdict memo keyed by (packet bytes, domain, engine version, verifier
  source fingerprint); hits are served and labelled on the trail, trace, record and page; errors never memoised.
- `trust` on every HOLDS: Beta(1+FP, 1+n−FP) from `data/benchmark_last.json` (`tools/benchmark.py --record`),
  mean and 95% upper bound on the false-pass rate, in capabilities and the verify response.
- Plugins declare `STRATUM`; the scripture verifier pack (witness/canon) registers as `scripture`, pure.
- `CLAUDE.md`: working notes and the non-negotiables for anyone (or any agent) working in this repo.
