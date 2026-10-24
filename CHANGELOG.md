# Changelog

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
- `CLAUDE.md`: working notes and the non-negotiables for anyone (or any agent) working in this repo.
