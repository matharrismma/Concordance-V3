# Concordance

**Receipts for numbers.** Send a number with its inputs; code the model didn't write recomputes it; you
get a verdict, the worked trail, and a content-addressed seal anyone can re-derive.

For AI agents (MCP server, HTTP API, Python package) and for the people who have to sign under what
those agents produce.

```bash
pip install "concordance[math,scribe]"      # stdlib core; sympy/numpy are optional extras
python -m concordance serve                 # http://127.0.0.1:8000  (MCP at /mcp)
```

## One call

```bash
curl -s localhost:8000/verify -d '{"steps":[{"id":"m","domain":"real_estate","spec":{"RE_VERIFY":{
  "loan_principal":12000000,"annual_rate":0.045,"loan_term_months":240,"claimed_monthly_payment":75917.93}}}]}'
```

```json
{"verdict": "HOLDS",
 "trail": [{"id": "m", "domain": "real_estate", "status": "CONFIRMED",
            "detail": "real_estate.monthly_mortgage: M = $75917.93/mo (matches claim)"}],
 "seal": {"content_hash": "1decac18e01c…", "cite_url": "/s/1decac18e01c…", "ledgered": true}}
```

`GET /s/<hash>` returns the sealed record; SHA-256 of its canonical JSON reproduces the hash.
`GET /s/<hash>?html=1` is the same record as a page a board member can read.

## MCP

```json
{"mcpServers": {"concordance": {"command": "python", "args": ["-m", "concordance", "mcp"]}}}
```

Eight tools: `verify` · `discern` · `find_verifier` · `seal_fetch` · `audit` · `scribe` · `capabilities` ·
`ledger_verify`. Start with `find_verifier("monthly mortgage payment")` — it returns the domain and the
**JSON schema of its packet** — then `verify(steps=[…])`. A misnamed field returns `SCHEMA_ERROR` naming
the field and its nearest valid name, never a silent "not applicable".

## Read the verdict exactly

| verdict | meaning |
|---|---|
| `HOLDS` | every checked claim recomputed to the stated value |
| `BROKEN` | a checked claim did **not** — the only verdict that is a finding about the claim |
| `PARTIAL` | the checked fragment held; `coverage.unchecked_text` names material text that was **not** checked |
| `INCOMPLETE` | no verifier applied; says nothing about truth |
| `SCHEMA_ERROR` | the packet does not match the domain's schema; `problems[].field` says what to fix |
| `SYSTEM_ERROR` | our verifier failed; never relay this as a refutation |

Plain-language claims (`verify {claim: "…"}`) are checked only where an extractor recognises a tight span;
compound sentences report the unchecked clause. Prefer packets.

## What it checks, and what it does not

`capabilities` reports the live counts (today: 78 verifier modules, ~390 named checks — finance, public
finance, physics, chemistry, statistics, units, medicine arithmetic, number theory, …). The benchmark
(`python tools/benchmark.py`) is 216 labelled cases across every domain, **0 false positives**, re-run on
every push; `tools/mutate.py` measures whether the gate is load-bearing (current score is in `MEASURED.md`
— it is not 100%, and the number is published rather than hidden).

It checks arithmetic and formula application. It does **not** judge whether a correct dose is safe, a
correct abatement is lawful, or a correct payment is affordable; those caveats ride in the receipt headline.

## scribe — many writers, one datum

```python
from concordance import scribe
report = scribe.score_pass(drafts, packets)      # drafts: [{writer, claims:[{id, value}]}]
report["spectrum"]["top_axis"]                   # which claims the writers disagree on
report["broken"]                                 # which claims the ENGINE broke, per writer
report["status"]                                 # CONVERGED | OPEN | UNDERDETERMINED (never averaged)
```

Measured 2026-10-20: five LLM writers agreed to 5–6 significant figures on a bond memo; the recompute still
caught 3 wrong claims consensus could not see. Disagreement locates where to look; the verifier decides.

## Extend

Register a verifier pack without forking: `pyproject.toml` → `[project.entry-points."concordance.verifiers"]
mydomain = "mypkg.mydomain"` exposing `run(packet) -> list[VerifierResult]`. Schemas are generated from
your code (`tools/schema_gen.py --check`); the benchmark requires a labelled true/false pair per domain
(`data/domain_goldens.json`, `tools/benchmark.py --check`).

## Gates (CI runs all of them)

```
PYTHONPATH=src pytest -q                      # suite
PYTHONPATH=src python tools/benchmark.py      # 0 false positives, every domain
PYTHONPATH=src python tools/benchmark.py --check
PYTHONPATH=src python tools/schema_gen.py --check
PYTHONPATH=src python tools/vocab_gate.py
PYTHONPATH=src python tools/closure.py <entrypoints> --lazy   # must be ⊆ CORE_MODULES.txt
```

MIT. Receipts are self-signed in this release; publishing seals to a transparency log
(Sigstore/Rekor, SCITT) is the next milestone.
