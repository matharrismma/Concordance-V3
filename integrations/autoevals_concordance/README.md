# autoevals-concordance

An [autoevals](https://github.com/braintrustdata/autoevals) `Scorer` that verifies a model's output with
Concordance and scores it.

## Install

```bash
pip install -e integrations/concordance_client -e integrations/autoevals_concordance
# engine: set CONCORDANCE_URL to a running engine, or `pip install -e .` for in-process
```

## Usage

```python
from autoevals_concordance import Concordance

scorer = Concordance()                                   # url=, on_unchecked="fail"|"pass"
s = scorer(output='{"steps": [{"id": "m", "domain": "real_estate", "spec": {...}}]}')
s.score                   # 0.0 – 1.0
s.metadata["verdict"]     # HOLDS | BROKEN | INCOMPLETE | ...
s.metadata["reason"]      # the client's one-line reason, verbatim
s.metadata["cite_url"]    # receipt a human can open and re-check

# harness knows the packets; the output is just the claim text
scorer(output="the monthly payment is 75,917.93", packets=[{"id": "m", "domain": "real_estate", "spec": {...}}])
```

Output routing: JSON with a `steps` list or `document` dict is verified as such; JSON `{mode, params}` runs
that mode; anything else is a plain-language `claim`. `packets=` / `steps=` (constructor or per-row kwarg)
override the output.

## What the score means

Not a truth score. See [integrations/README.md](../README.md#score-semantics-the-same-in-every-adapter).
`metadata["checked"]` is `False` when nothing was established; with the default `on_unchecked="fail"` that
scores 0.0 and the reason says so in the client's words. autoevals `Score` has no pass/reason fields, so both
live in `metadata` (`pass`, `reason`) alongside `verdict`, `read`, `cite_url`, `seal`, `budget`, `trace`.
