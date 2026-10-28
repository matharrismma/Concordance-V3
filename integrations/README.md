# Integrations

Thin adapters that put Concordance's verdict, trace and link budget into harnesses people already run. None of
this is core: each package imports the engine over HTTP (`CONCORDANCE_URL`) or in-process, and is installed on
its own. The core's import closure does not include this directory.

| package | what it is | install |
|---|---|---|
| `concordance_client/` | the one client the adapters share: `check(...)` → `{verdict, read, score, trace, budget, seal, cite_url}` | `pip install -e integrations/concordance_client` |
| `deepeval_concordance/` | a DeepEval `BaseMetric` | `pip install -e integrations/deepeval_concordance` |
| `autoevals_concordance/` | an autoevals `Scorer` | `pip install -e integrations/autoevals_concordance` |
| `langgraph_concordance/` | a LangGraph node + a LangChain tool | `pip install -e integrations/langgraph_concordance` |

## Score semantics (the same in every adapter)

Not a truth score. `score` is **signal strength after attempted refutation**:

- `HOLDS` → `1 − 0.5 · worst_used` — clears, scaled by how much of its tightest allowance the chain spent
  (1.0 dead centre, 0.5 at the edge). The reason names the tightest step.
- `BROKEN` → `0.0` — a counterexample; the reason carries recomputed value, band and off_by.
- `INCOMPLETE`, `SCHEMA_ERROR`, `SYSTEM_ERROR` → `0.0` with `checked=False` and the reason saying nothing was
  established about the claim. Conservative by default (`on_unchecked="fail"`); `on_unchecked="pass"` scores
  1.0 with `checked=False` for harnesses that only want to catch counterexamples.

Every result carries the `verdict`, the one-sentence `read`, the `trace` (OTDR view) and the `cite_url` so a
failing eval links to a receipt a human can open and re-check.
