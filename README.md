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

This is not a truth engine. Where a value can be computed it is computed, and the claim must fall inside a
**band** around it — `[actual − tol, actual + tol]`, with the tolerance the verifier sets and a caller may only
tighten. Everything that cannot be computed is **narrowed**, not proven: the engine attempts refutations and
reports which the claim survived, which produced a counterexample, and which could not be attempted. A
counterexample is the strongest thing a receipt can hold; a survival is only the absence of one. Every
response carries `read` (one sentence saying what the verdict is *not*) and `refutations`
(`attempted / survived / counterexamples / not_applicable`, with every band); both are sealed into the record.

A HOLDS also carries `trust`: the Bayesian discount on a survival, from the recorded benchmark counts —
Beta(1+FP, 1+n−FP) on the false-pass rate (today: 1,796 cases, 0 FP → mean 0.06%, 95% upper 0.17%). A
survival updates belief; a counterexample sets it to zero; `trust` is the prior on survival itself, from
counts rather than confidence.

HOLDS is not binary either. Every band carries `used` — the share of its tolerance the claim spent — and the
derivation returns a `trace`: the chain shot like an OTDR, one event per step with its depth, its loss, and
whether it reflected (a counterexample) or went dark. `trace.budget` names the tightest step; a chain that
clears at 98% of its allowance is one you redo before you build on it.

| verdict | meaning |
|---|---|
| `HOLDS` | survived every attempted refutation — shown **not false** by these checks, silent on anything they did not test |
| `BROKEN` | a counterexample: the recomputed value, the band, and how far outside it the claim fell — the only verdict that is a finding about the claim |
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

## Documents — receipts that stand on receipts

A document is a derivation whose steps may **bind** their inputs to earlier steps' outputs, sealed as one
root over every step's packet hash, status and dependencies (plus any parent seals — an earlier version, a
scribe pass):

```bash
curl -s localhost:8000/verify -d '{"document":{"title":"memo","steps":[
  {"id":"par","domain":"public_finance","spec":{"PUBFIN_VERIFY":{"net_proceeds":12000000,"issuance_cost_pct":0.02,"round_up_to":5000,"claimed_par":12245000}}},
  {"id":"debt","domain":"public_finance","spec":{"PUBFIN_VERIFY":{"par":0,"annual_rate":0.045,"term_months":240,"interest_only_months":24,"claimed_monthly_pi":82815.95}},
   "bind":{"PUBFIN_VERIFY.par":"par.actual_par"}}]}}'
```

Change the gross-up and the par step breaks; the steps that rested on it refuse to run rather than report a
stale HOLDS; the root changes. `GET /s/<root>?html=1` shows the tree and re-checks the whole chain from
edited inputs. One hash covers the memo — the chain, not the number.

## Context is stripped, checked, and put back

Every entry point runs the same loop. **In:** personal details in free text (claim text, step labels, document title
and prose, a scribe spec) become stable placeholders — one map per request, so the same email is the same token
everywhere; numbers are never touched, they are what gets checked. **Check:** the verifier and the seal see only
the stripped form; the record in the CAS and the public log never hold the original. **Out:** the response is
walked and the originals put back by lookup — never regenerated — everywhere except the sealed parts, and
`context` says exactly what travelled, how many placeholders were held, and where they were reapplied.
The scribe's writers only ever see the skeleton; `drafts_revealed` is the user's copy.

## Receipts anyone can check — signed and publicly logged

With an issuer key configured (`python -m concordance keygen`), every record served at `/s/<hash>` carries,
beside it and never inside the hashed bytes, a **COSE_Sign1 statement** (Ed25519) over the record and — with
`CONCORDANCE_PUBLISH=1` — a **Rekor transparency-log entry** holding that statement, the signature and the
public key, with its Merkle inclusion proof. A stranger checks all of it with one file and two pip packages:

```bash
curl -s https://narrowhighway.org/s/<hash> > receipt.json
python3 docs/verify_receipt.py receipt.json
# HASH ok · SIGNATURE ok · LOG ok (rekor index …) · INCLUSION ok (root reproduced)
```

`verify_receipt.py` imports nothing from this repo: it re-hashes the record, verifies the signature itself,
fetches the log entry, and recomputes the log's root hash from the inclusion proof (RFC 6962). Tamper with
one digit and HASH fails; swap the key and SIGNATURE fails. Without an issuer key the receipt says
"self-attested" and still re-hashes. Format: `docs/RECEIPT_SPEC.md`.

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

The pass report is **elimination**: for each claim, `narrow_way` gives the band the recompute names, the stated
values it eliminated and by how far, the survivors, and their `[min, max]` bracket cut to the band. Minimum and
maximum make the optimum easy to find; the engine never averages. Where no packet exists the claim is reported
`un-narrowed` with the bracket of what was stated, labelled unverified. Each writer's feedback names its
counterexample — the band and the distance — never another writer's value.

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
