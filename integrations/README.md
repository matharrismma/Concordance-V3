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

## Edge translator (natural language in)

The core refuses to guess — it extracts only phrasings it recognises exactly. This puts a model in
front of it to reach the rest, as a cascade: the deterministic extractors first (free, exact), then
the model only for what they miss. The model **proposes what to check** (it fills the resolved
domain's packet schema); the **engine always recomputes the verdict**, so the model cannot make a
false claim HOLD — the zero-false-positive guarantee is untouched, and the result carries
`proposed_packet` so you can see exactly what was checked.

```python
from concordance_integrations.translate import verify_text

def my_model(prompt):              # bring your own — any str -> str
    return client.responses.create(model="...", input=prompt).output_text

r = verify_text("borrowing 12k at 6% over a year runs about 1032.80 a month", model=my_model)
# r["reached_by"] is "extractor" (free), "model" (tail), or "none" (honest null)
```

The core stays model-free; this layer sits in front of it. Ready-made wrappers
(`concordance_integrations.models`) make it turnkey — `anthropic_model("…")` (uses `ANTHROPIC_API_KEY`),
`openai_model("…", base_url=…)` for OpenAI or any compatible host — or pass your own `str -> str`.

**Onboard, no key.** The task is small (fill a JSON schema) and the engine is the backstop, so a tiny
local model is the right fit: `ollama_model("qwen2.5:0.5b")` (`pip install ollama`, then
`ollama pull qwen2.5:0.5b`) or `llamacpp_model("…/Qwen2.5-0.5B-Instruct-Q4_K_M.gguf")`
(`pip install llama-cpp-python` + a GGUF). A 0.5–1.5B model runs on CPU with no account.

**PID correction loop.** `verify_text(…, model=…, max_rounds=3)` closes the loop: when the model's
packet does not reach a verifier, the engine's error is fed back and the model tries again — it corrects
only the rectified error ("did we reach the check"), stops the instant a verdict is reached, and never
loops to turn a BROKEN into a HOLDS. That lets a small onboard model be nudged to a complete packet with
the 0-false-positive guarantee untouched.

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
The split is a packaging step, not a code change.

## PrimeIntellect (RL rewards)

```python
import verifiers as vf
from concordance_integrations.primeintellect import load_environment, concordance_reward

env = load_environment(dataset=my_dataset)   # reward = the Concordance verdict
```

The reward recomputes each completion's claim: `HOLDS` → 1.0, `BROKEN` → 0.0, un-checkable → 0.0
(configurable). A model cannot game a reward it cannot fool, and a 0-false-positive oracle cannot be
fooled — so this trains models to state exact, checkable numbers. `score_completion(...)` is the
framework-free reward, usable without `verifiers`.
