# concordance-integrations

The Concordance verifier, inside the harnesses teams already run. Each adapter wraps one engine
call and hands back a re-checkable receipt (a content-addressed, optionally signed seal). The
engine recomputes the claim — it does not ask a second model, and it does not match a pattern.

```bash
pip install concordance-integrations[all]      # or [deepeval] / [langgraph] / [guardrails]
# the derivation moat (math/physics/stats) also needs: pip install concordance[math]
```

## The one rule

Three outcomes, never two:

| verdict | meaning | scorer | validator | node |
|---|---|---|---|---|
| `HOLDS` | survived every attempted refutation | `1.0` | pass | `passed=True` |
| `BROKEN` | a counterexample — outside the band | `0.0` | **fail** | `passed=False` |
| anything else | the engine could not test it | `None` / abstain | pass (reported) | `passed=None` |

A claim the engine could not check is **never** scored as a failure. Punishing the engine for
saying "I could not test this" would reward a model that answers only checkable things. That
honesty is in the metadata every time.

## DeepEval / autoevals

```python
from concordance_integrations.deepeval import ConcordanceMetric, concordance_scorer

metric = ConcordanceMetric(extract=lambda tc: {"claim": tc.actual_output})
metric.measure(test_case)          # 1.0 / 0.0; metric.reason carries the receipt URL
metric.is_successful()

concordance_scorer(claim="a 12,000,000 loan at 4.5% over 240 months is 75,917.93 a month")
# {"name": "Concordance", "score": 1.0 | 0.0 | None, "metadata": {...receipt...}}
```

`ConcordanceMetric` subclasses DeepEval's `BaseMetric` when DeepEval is installed, so
`evaluate([...], [metric])` accepts it; importing the module never requires DeepEval.

## LangGraph / AutoGen

```python
from concordance_integrations.langgraph import make_verify_node

graph.add_node("verify", make_verify_node(lambda s: {"claim": s["answer"]}))
# writes state["concordance"] = {verdict, checked, passed, reason, content_hash, cite_url}
# make_verify_node(..., fail_fast=True) raises ConcordanceCounterexample on BROKEN
```

The node is a plain `callable(state) -> update` over a dict, so it also works as an AutoGen tool
or in a hand-rolled loop — nothing imports langgraph.

## Guardrails

```python
from guardrails import Guard
from concordance_integrations.guardrails import ConcordanceNumbers

guard = Guard().use(ConcordanceNumbers, on_fail="exception")
guard.validate("the monthly payment is 75,917.93")   # blocks only a provably-wrong number
```

`validate_text(value)` makes the same decision without Guardrails installed.

## Packaging note (owner)

This is prepared as one package for review and iteration. For publication it splits cleanly into
the names each ecosystem expects — `concordance-evals` (DeepEval + autoevals), `concordance-langgraph`,
and `guardrails-ai-concordance` (Guardrails Hub) — each a thin shim over `concordance_integrations`.
The split is a packaging step, not a code change. A PrimeIntellect `verifiers` environment that
exposes the benchmark as un-hackable rewards is the next adapter and is not in this package yet.
