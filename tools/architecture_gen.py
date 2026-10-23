"""Regenerate docs/ARCHITECTURE.md from the running code. Every count is derived; nothing is hand-maintained.

    PYTHONPATH=src python tools/architecture_gen.py
"""
import json, os, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from concordance import capabilities, tool_registry, __version__
from concordance import verifiers as V

cap = capabilities.statement()
core = [l.split()[0] for l in open(os.path.join(ROOT, "CORE_MODULES.txt")) if not l.startswith("#")]
top = sorted(m for m in core if "." not in m)
pkgs = sorted({m.split(".")[0] for m in core if "." in m})
lines = sum(int(l.split()[1]) for l in open(os.path.join(ROOT, "CORE_MODULES.txt")) if not l.startswith("#"))
bench = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "benchmark.py"), "--json"], capture_output=True, text=True,
                       env=dict(os.environ, PYTHONPATH=os.path.join(ROOT, "src")))
b = json.loads(bench.stdout) if bench.stdout.strip().startswith("{") else {}
tot = b.get("totals", {})

doc = f"""# Architecture (generated — `python tools/architecture_gen.py`, version {__version__})

## The floor — seven primitives

1. **Claim** — a structured packet `{{domain, spec}}` (or plain text the extractor resolves)
2. **Verifier** — a pure deterministic function `spec → verdict + worked trail` (no I/O, no model)
3. **Verdict** — HOLDS | PARTIAL | BROKEN | INCOMPLETE | SCHEMA_ERROR | SYSTEM_ERROR
4. **Seal** — SHA-256 content-addressed record of `{{claim, verdict, trail}}` (`cas.py`)
5. **Ledger** — append-only hash chain of seals (`ledger.py`, `ledger_verify`)
6. **Schema** — every verifier's packet schema, generated from its code (`schema.py`)
7. **Scribe** — many writers, one datum: claim matrix → SVD disagreement axis → recompute (`scribe/`)

## Counts (derived at generation time)

| what | count | means |
|---|---|---|
| core modules reached from the 8 tools | {len(core)} ({lines:,} lines) | lazy import closure, `tools/closure.py` |
| verifier modules | {cap['verifiers']['modules']} | {cap['verifiers']['means_modules']} |
| named checks | {cap['verifiers']['checks']} | {cap['verifiers']['means_checks']} |
| domain names accepted | {cap['verifiers']['domain_names']} | {cap['verifiers']['means_domain_names']} |
| MCP tools | {len(tool_registry.REGISTRY)} | {', '.join(tool_registry.NAMES)} |
| benchmark v{b.get('benchmark_version','?')} | {tot.get('cases','?')} cases, {tot.get('false_positives','?')} FP, {tot.get('false_negatives','?')} FN | `tools/benchmark.py --json` |

## Request path

```
plain text ──airlock (de-identify)──▶ audit.extract (tight spans) ──▶ steps
packet ─────schema.validate_steps ──▶ derivation.verify_derivation ──▶ verifiers.run_for_domain
                                                   │
                                      receipts.attach ──▶ cas (seal) ──▶ ledger (chain)
```

`verify {{claim}}` is checked only where an extractor recognised a span; `coverage.unchecked_text`
names the rest. `verify {{steps}}` validates every packet against the generated schema first and
returns `SCHEMA_ERROR` naming the field (and its nearest valid name) on a mismatch.

## Modules

Top-level: {', '.join('`'+m+'`' for m in top)}

Packages: {', '.join('`'+p+'/`' for p in pkgs)}

## Extension

Verifier packs register through the `concordance.verifiers` entry-point group (`domain = "pkg.module"`
exposing `run(packet) -> list[VerifierResult]`). The .org application registers its scripture/theology
checks this way; the core never imports them.

## Gates (CI)

suite · benchmark (0 FP, every domain has a golden pair) · schema_gen --check · vocab_gate · closure ⊆ CORE_MODULES.txt ·
nightly: slow tests + mutation score (`tools/mutate.py`).
"""
open(os.path.join(ROOT, "docs", "ARCHITECTURE.md"), "w", encoding="utf-8").write(doc)
print("wrote docs/ARCHITECTURE.md")
