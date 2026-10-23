# Runbook

```bash
pip install "concordance[math,scribe,signing]"
python -m concordance serve --host 0.0.0.0 --port 8000     # HTTP API + MCP at /mcp
python -m concordance mcp                                  # MCP over stdio
```

Environment: `CONCORDANCE_DATA_DIR` (verifier data + ledger; default `./data`), `CONCORDANCE_PUBLIC_BASE`
(prefix for `cite_url`; empty = relative `/s/<hash>`), `CONCORDANCE_ALLOWED_ORIGINS` (browser origins for `/mcp`).

Health: `GET /health`. Live counts: `GET /capabilities`. Ledger integrity: `GET /ledger/verify` (re-walks the
hash chain; returns the first break). A seal: `GET /s/<hash>` (JSON) or `?html=1` (page).

Gates before deploy: `pytest -q`, `tools/benchmark.py --check`, `tools/schema_gen.py --check`, `tools/vocab_gate.py`.
Regenerate docs after a verifier change: `tools/schema_gen.py` (docs/schemas.json), `tools/architecture_gen.py`.

Rollback: the engine is a stateless process over an append-only ledger; redeploy the previous version and the
ledger is untouched. Never rewrite `data/ledger/`.
