# Measured — concordance-3 at f44bace (2026-10-23)

| metric | v2 (2026-10-20) | v3 now | target |
|---|---|---|---|
| core modules (top-level .py) | 175 | 32 | ≤ 40 |
| core lines excl. verifiers | 51,666 | 9375 | ≤ 22,000 |
| verifier modules / lines | 94 / 27,780 | 92 / 26520 | secular set + public_finance |
| lazy import closure from the 8 tools | 187 modules / 63,598 lines | 52 modules, 14438 lines | ⊆ CORE_MODULES.txt |
| MCP tools | 102 | 8 | 8 |
| server instructions | house metaphor | 98 words, no org vocabulary | < 120 words |
| docs files | 44 | 3 + README | ≤ 6 |
| suite | 2,914 passed / 97 s | 773 passed, 25 skipped / 73 s | green, ≤ 60 s |
| benchmark | v1.0.0: 60 cases, 3 modes | v2.1.0: **1,014 cases**, 0 FP, 0 FN — 60 derivation + 156 per-domain goldens + 798 from the Lighthouse (v1) 722/202 template datasets, run unchanged against v3 verifiers (126 rows skipped by policy: they require executing caller code; 1 labelled policy disagreement, listed in tools/benchmark.py) | ≥ 200, 0 FP |
| mutation score (operator flips, seed 3) | not measured | 12/20 (unchanged after adding Lighthouse: its 6 domains were already covered; the misses are biology/agriculture/thermo/soil/probability/… checks with no case) | 20/20 — NOT MET |
| coverage lie (compound sentence) | present | regression-tested gone (13 cases) | gone |
| misnamed packet field | silent NOT_APPLICABLE | SCHEMA_ERROR naming field + nearest valid name | named |
| packet schemas | none | generated for 78/78 domains (tools/schema_gen.py) | all |
| vocabulary gate (user-visible strings, docs) | n/a | 0 hits | 0 |
| time to first sealed receipt from README | n/a | one pip, one serve, one curl | < 5 min (unmeasured with a stranger) |

Not done (see V3_PLAN.md): P6 (org repo depends on this package), P7 docs regeneration beyond README,
P8 release; Rekor/SCITT receipt envelope (PRODUCT_PLAN M1); mutation 20/20 needs one golden per CHECK (~395),
not per domain (78). Tests skipped from v2 are listed in tests/SKIPPED_FROM_V2.txt (all org-module tests).
