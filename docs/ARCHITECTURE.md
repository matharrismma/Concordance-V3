# Architecture (generated — `python tools/architecture_gen.py`, version 3.0.0a1)

## The floor — seven primitives

1. **Claim** — a structured packet `{domain, spec}` (or plain text the extractor resolves)
2. **Verifier** — a pure deterministic function `spec → verdict + worked trail` (no I/O, no model)
3. **Verdict** — HOLDS | PARTIAL | BROKEN | INCOMPLETE | SCHEMA_ERROR | SYSTEM_ERROR
4. **Seal** — SHA-256 content-addressed record of `{claim, verdict, trail}` (`cas.py`)
5. **Ledger** — append-only hash chain of seals (`ledger.py`, `ledger_verify`)
6. **Schema** — every verifier's packet schema, generated from its code (`schema.py`)
7. **Scribe** — many writers, one datum: claim matrix → SVD disagreement axis → recompute (`scribe/`)
8. **Document** — a derivation whose steps bind to earlier outputs, sealed as one root over every step's
   packet hash, dependencies and parent seals (`compose.py`) — the primitives applied to their own outputs

## Counts (derived at generation time)

| what | count | means |
|---|---|---|
| core modules reached from the 8 tools | 55 (16,753 lines) | lazy import closure, `tools/closure.py` |
| verifier modules | 78 | distinct verifier modules registered (a module is one domain) |
| named checks | 395 | named checks across modules (from each module's docstring list, else its verify_* functions) |
| domain names accepted | 194 | domain names the dispatcher accepts, aliases included |
| MCP tools | 8 | verify, discern, find_verifier, seal_fetch, audit, scribe, capabilities, ledger_verify |
| benchmark v2.2.0 | 1796 cases, 0 FP, 0 FN | `tools/benchmark.py --json` |

## Request path

```
plain text ──airlock (de-identify)──▶ audit.extract (tight spans) ──▶ steps
packet ─────schema.validate_steps ──▶ derivation.verify_derivation ──▶ verifiers.run_for_domain
                                                   │
                                      receipts.attach ──▶ cas (seal) ──▶ ledger (chain)
```

`verify {claim}` is checked only where an extractor recognised a span; `coverage.unchecked_text`
names the rest. `verify {steps}` validates every packet against the generated schema first and
returns `SCHEMA_ERROR` naming the field (and its nearest valid name) on a mismatch.

## Modules

Top-level: `__main__`, `airlock`, `audit`, `bucket`, `capabilities`, `cas`, `chess`, `compose`, `compute`, `config`, `constraints`, `context`, `derivation`, `discern`, `domain_resolver`, `domains`, `engine`, `gates`, `http_api`, `layers`, `ledger`, `packet`, `receipts`, `record`, `redact`, `schema`, `scribe`, `signing`, `slotfill`, `telemetry`, `text`, `tool_registry`, `transparency`, `validate`, `verifiers`

Packages: `domains/`, `mcp/`, `scribe/`, `verifiers/`

## Extension

Verifier packs register through the `concordance.verifiers` entry-point group (`domain = "pkg.module"`
exposing `run(packet) -> list[VerifierResult]`). The .org application registers its scripture/theology
checks this way; the core never imports them.

## Gates (CI)

suite · benchmark (0 FP, every domain has a golden pair) · schema_gen --check · vocab_gate · closure ⊆ CORE_MODULES.txt ·
nightly: slow tests + mutation score (`tools/mutate.py`).
