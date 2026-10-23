# Per-check goldens

One file per verifier module: `{"domain": "<module>", "packet_key": "<ARTIFACT_KEY>", "cases": [{"check": "<verify_* name without prefix>", "true": {...artifact...}, "false": {...artifact...}}]}`.
`true` must make that check CONFIRMED (the derivation HOLDS); `false` must make it MISMATCH (BROKEN) — a wrong claimed value, not malformed input (malformed input is ERROR, which the benchmark counts as "rejected" but does not exercise the arithmetic).
Run: `PYTHONPATH=src python tools/benchmark.py` (the `check` tier) and `tools/mutate.py`.
