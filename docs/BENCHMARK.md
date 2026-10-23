# The benchmark — the bound behind "0 false positives" (v2.2.0)

A universal zero-false-positive claim is stronger than a finite benchmark can establish, so the claim is
bounded and the bound is this package. **Reproduce:** `PYTHONPATH=src python tools/benchmark.py --json`.

Four tiers, all labelled, FP and FN reported separately (a missed truth is never hidden in an accuracy figure):

| tier | cases | source |
|---|---|---|
| derivation | 60 | equality / inequality / derivative, ported from 1.0's public benchmark (v1.0.0, unchanged) |
| domain | 2 per registered domain | `data/domain_goldens.json` — one true and one false packet per verifier module; `--check` fails the build if a domain lacks a pair |
| lighthouse | 798 (+126 skipped by policy) | the v1 engine's template-generated, perturbation-labelled datasets (`data/benchmark_lighthouse_v1/v2.jsonl`), run unchanged against these verifiers; rows needing execution of caller-supplied code are skipped and counted; one labelled policy disagreement is listed in `tools/benchmark.py` |
| check | one true (and usually one derived false) per **named check** | `data/check_goldens.jsonl`, harvested from the test suite by `tools/harvest_goldens.py`; the false golden is the true packet with its claimed value perturbed ×1.37 and is kept only if the engine actually rejects it |

**Mutation evidence.** `tools/mutate.py --sample N` flips one operator token in N random verifier modules
and reports whether the benchmark or the per-domain tests go red. Equivalent mutants exist (an error-message
string, a symmetric balance both sides of which are negated); the score is published in `MEASURED.md`
rather than rounded up.

**What it does not establish:** anything outside these packets. A verifier with a check no case reaches is
unmeasured; `tools/harvest_goldens.py` and the mutation score are how that gap is found.
