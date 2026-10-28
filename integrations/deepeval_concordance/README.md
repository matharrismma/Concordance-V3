# deepeval-concordance

A DeepEval `BaseMetric` that recomputes the claim with Concordance instead of asking an LLM judge. No model
is configured or called.

## Install

```bash
pip install -e integrations/concordance_client -e integrations/deepeval_concordance
# plus either a running engine (CONCORDANCE_URL=http://host:8020) or `pip install -e .[math]` for in-process
```

## Usage

```python
from deepeval import evaluate
from deepeval.test_case import LLMTestCase
from deepeval_concordance import ConcordanceMetric

metric = ConcordanceMetric(threshold=0.5)                     # url=..., on_unchecked="fail"|"pass"
tc = LLMTestCase(input="What is 15% of 200?", actual_output="15% of 200 is 30")
metric.measure(tc)
print(metric.score, metric.is_successful(), metric.reason)    # 1.0 True survived every attempted refutation; receipt /s/...
print(metric.metadata)                                        # verdict, read, cite_url, seal_hash, budget, checked
evaluate([tc], [metric])                                      # or inside evaluate()
```

`actual_output` is read as a JSON packet (`{"steps": [...]}`, `{"document": {...}}`, `{"mode", "params"}`)
when it parses as one, otherwise as a plain-language claim. When the harness knows the packets, pass
`ConcordanceMetric(packets=[...])` and the output is just the claim being scored.

## What the score means

Not a truth score: signal strength after attempted refutation. HOLDS → `1 − 0.5·worst_used`, BROKEN → 0,
and anything the engine could not check → 0 with `metadata["checked"] == False` (or 1 with
`on_unchecked="pass"`). The reason is the client's wording, verbatim. See
[integrations/README.md](../README.md#score-semantics-the-same-in-every-adapter).
