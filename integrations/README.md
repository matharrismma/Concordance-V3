# Integrations

One package, `concordance_integrations`, that puts the engine's verdict, receipt and link budget inside
harnesses people already run. None of it is core: it calls the engine in-process (the same `verify` tool the
MCP server and HTTP API dispatch) and is installed on its own. The core's import closure does not include this
directory. Importing any adapter module never requires its framework.

```bash
pip install -e ".[math]" -e "integrations[deepeval]"     # or [autoevals] [langgraph] [langchain] [guardrails] [primeintellect] [all]
```

| module | what it is |
|---|---|
| `engine` | the one call: `verify(steps= / claim= / document= / mode=+params=)`; `payload_for(output)` is the JSON dispatch |
| `verdict` | `read(result) -> Outcome`: the shared reading and the shared score |
| `deepeval` | `ConcordanceMetric` (a DeepEval `BaseMetric`) + `concordance_scorer` (the autoevals dict shape) |
| `autoevals` | `Concordance`, an autoevals/Braintrust `Scorer` |
| `langgraph` | `make_verify_node`, `route_on_verdict`, and the `concordance_verify` LangChain tool |
| `guardrails` | `ConcordanceNumbers`, registered as `concordance/numbers` (entry point `guardrails.validators`) |
| `primeintellect` | the verdict as an RL reward for a `verifiers` environment |
| `translate`, `models` | a model in front of the engine so loose phrasing reaches a verifier; the verdict stays the engine's |

## Score semantics (the same in every adapter)

Three outcomes, never two. `Outcome` keeps `checked` apart from `passed`:

- `HOLDS` → checked, passed. `score = 1 − 0.5 · worst_used`, where `worst_used` is `trace.budget.worst_used`,
  the share of its tightest allowance the chain spent (1.0 dead centre, 0.5 at the edge; a chain with no banded
  checks spent nothing → 1.0). Not a truth score: signal strength after attempted refutation.
- `BROKEN` → checked, not passed, `score = 0.0`. The reason names the counterexample (what, claimed,
  recomputed, off_by) and `counterexample` carries it.
- anything else (`INCOMPLETE`, `SCHEMA_ERROR`, `SYSTEM_ERROR`, …) → `checked=False`, `passed=None`,
  `score=None`: the engine could not test it. **Abstain is the default** — never a failure. Each adapter says
  what None means for its harness (DeepEval scores it `abstain_is_success`; autoevals reads None as skip;
  LangGraph routes it `"unchecked"`; Guardrails does not block).

`Outcome.receipt()` is the metadata every adapter carries: `verdict, checked, passed, score, reason, read,
content_hash, cite_url, budget, counterexample` — so a failing eval links to a receipt a human can open and
re-check.

## DeepEval

```python
from deepeval import evaluate
from deepeval.test_case import LLMTestCase
from concordance_integrations.deepeval import ConcordanceMetric

metric = ConcordanceMetric()                       # abstain_is_success=True, threshold=0.5, no LLM configured
tc = LLMTestCase(input="What is 15% of 200?", actual_output="15% of 200 is 30")
metric.measure(tc); metric.score, metric.is_successful(), metric.reason, metric.metadata
evaluate([tc], [metric])
```

`actual_output` goes through the JSON dispatch: `{"steps": [...]}`, `{"document": {...}}`, `{"mode", "params"}`
are verified as that packet, anything else as a plain claim. `extract=lambda tc: {...}` replaces it. An
un-checkable claim scores 1.0 with `abstain_is_success=True` (default) or 0.0 with it off; `metadata["checked"]`
is False and the reason says nothing was established either way.

## autoevals / Braintrust

```python
from concordance_integrations.autoevals import Concordance
s = Concordance()(output='{"steps": [...]}')            # Score(name="Concordance", score, metadata=receipt)
s = Concordance()(output="the payment is 75,917.93", steps=[...])   # per-row packets; output is just the claim
```

`score` is None when not checked (autoevals skips the row). `concordance_scorer(...)` in `.deepeval` is the
same decision as a plain dict.

## LangGraph / LangChain

```python
from langgraph.graph import StateGraph, START, END
from concordance_integrations.langgraph import make_verify_node, route_on_verdict, concordance_verify

g.add_node("verify", make_verify_node(input_key="output"))          # or make_verify_node(lambda s: {"claim": s["answer"]})
g.add_conditional_edges("verify", route_on_verdict, {"holds": END, "broken": "model", "unchecked": END})
concordance_verify.invoke({"claim": "15% of 200 is 30"})            # the same check as an agent tool
```

The node writes the receipt under `key` (default `"concordance"`); `state["packets"]` overrides the output when
the harness knows the packets. `fail_fast=True` raises `ConcordanceCounterexample` on BROKEN only.

## Guardrails

```python
from guardrails import Guard
from concordance_integrations.guardrails import ConcordanceNumbers
guard = Guard().use(ConcordanceNumbers, on_fail="exception")       # blocks only a provably-wrong number
```

`validate_text(value, metadata)` is the same decision without Guardrails installed.

## PrimeIntellect `verifiers`

```python
from concordance_integrations.primeintellect import load_environment, concordance_reward
env = load_environment(dataset=my_dataset)        # reward: HOLDS 1.0, BROKEN 0.0, not checked abstain_reward (0.0)
```

A training signal rewards checkable truths, so here abstain defaults to 0.0 — the one adapter where it does.

## Tests

`PYTHONPATH=src python -m pytest -q tests/test_integrations.py integrations` — the framework-free core against
the goldens, then `integrations/tests/` runs each framework's native path (a real `deepeval.evaluate()`, a
compiled `StateGraph`, an autoevals `Score`) wherever that framework is installed, skipping otherwise.
