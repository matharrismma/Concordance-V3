# Runbook

```bash
pip install "concordance[math,scribe,signing]"
python -m concordance serve --host 0.0.0.0 --port 8000     # HTTP API + MCP at /mcp
python -m concordance mcp                                  # MCP over stdio
```

Environment: `CONCORDANCE_DATA_DIR` (verifier data + ledger; default `./data`), `CONCORDANCE_PUBLIC_BASE`
(prefix for `cite_url`; empty = relative `/s/<hash>`), `CONCORDANCE_ALLOWED_ORIGINS` (browser origins for `/mcp`).

Transparency (optional, recommended for any public deployment): `python -m concordance keygen` → put the
`CONCORDANCE_ISSUER_KEY=` line in the unit's `EnvironmentFile` (`.env`, mode 0600; never in the repo). With a key
set, every `seal_fetch` / `GET /s/<hash>` carries `attest.envelope` (COSE_Sign1, Ed25519) beside the record. Set
`CONCORDANCE_PUBLISH=1` to also log each statement on Rekor (`CONCORDANCE_REKOR_URL`, default the public
Sigstore log) at first fetch; `tools/publish_seals.py [--all-ledger]` flushes anything still pending (cron it).
Rotate by issuing a new key: old receipts stay valid under the old public key, which is in each envelope and
in the log entry. `GET /capabilities` → `transparency` shows the current kid. Without a key, receipts say
"self-attested" and nothing else changes. Anyone checks a receipt with `docs/verify_receipt.py` (see
docs/RECEIPT_SPEC.md).

Health: `GET /health`. Live counts: `GET /capabilities`. Ledger integrity: `GET /ledger/verify` (re-walks the
hash chain; returns the first break). A seal: `GET /s/<hash>` (JSON) or `?html=1` (page).

Gates before deploy: `pytest -q`, `tools/benchmark.py --check`, `tools/schema_gen.py --check`, `tools/vocab_gate.py`.
Regenerate docs after a verifier change: `tools/schema_gen.py` (docs/schemas.json), `tools/architecture_gen.py`.

Rollback: the engine is a stateless process over an append-only ledger; redeploy the previous version and the
ledger is untouched. Never rewrite `data/ledger/`.
