"""A scorer for DeepEval and autoevals.

It sits where `NumericDiff` would, but needs no expected value: it recomputes the claim and
scores the verdict. An un-checkable claim does not score 0 — by default it abstains
(`abstain_is_success=True`, score 1.0, success True) so the engine's honesty about what it
could not test is never counted as a model failure. Flip `abstain_is_success=False` to treat
"not checked" as a miss when your eval requires every claim to be reachable.

    from concordance_integrations.deepeval import ConcordanceMetric
    metric = ConcordanceMetric(extract=lambda tc: {"claim": tc.actual_output})
    metric.measure(test_case)      # -> 1.0 / 0.0; metric.reason carries the receipt url

`ConcordanceMetric` subclasses DeepEval's BaseMetric when DeepEval is installed (so
`evaluate([...], [metric])` accepts it) and a plain object otherwise, so importing this module
never requires DeepEval. `concordance_scorer(...)` is the autoevals/Braintrust shape: a dict
with name/score/metadata, score=None when not checked (autoevals reads None as "skip").
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from . import engine, verdict


def _default_extract(test_case: Any) -> Dict[str, Any]:
    """Treat the test case's actual_output as a sentence to extract claims from. Override with
    `extract=` to pass a structured packet instead: return {"steps": [...]}."""
    return {"claim": getattr(test_case, "actual_output", None) or str(test_case)}


def _base():  # BaseMetric when DeepEval is present, else object — resolved once at import.
    try:
        from deepeval.metrics import BaseMetric
        return BaseMetric
    except Exception:  # noqa: BLE001 — DeepEval optional; any import failure means "not installed"
        return object


class ConcordanceMetric(_base()):  # type: ignore[misc]
    def __init__(self, extract: Optional[Callable[[Any], Dict[str, Any]]] = None,
                 *, threshold: float = 1.0, abstain_is_success: bool = True,
                 seal: bool = True) -> None:
        self._extract = extract or _default_extract
        self.threshold = threshold
        self.abstain_is_success = abstain_is_success
        self._seal = seal
        self.score: Optional[float] = None
        self.success: bool = False
        self.reason: str = ""
        self.receipt: Dict[str, Any] = {}
        self.evaluation_model = "concordance"   # DeepEval reads this for its report

    def measure(self, test_case: Any, *args: Any, **kwargs: Any) -> float:
        out = verdict.read(engine.verify(**self._extract(test_case), seal=self._seal))
        self.receipt = out.receipt()
        if out.abstained:
            self.success = self.abstain_is_success
            self.score = 1.0 if self.abstain_is_success else 0.0
            self.reason = f"not checked ({out.verdict}): {out.reason}"
        else:
            self.success = bool(out.passed)
            self.score = 1.0 if out.passed else 0.0
            self.reason = out.reason + (f"  receipt: {out.cite_url}" if out.cite_url else "")
        return self.score

    async def a_measure(self, test_case: Any, *args: Any, **kwargs: Any) -> float:
        return self.measure(test_case, *args, **kwargs)

    def is_successful(self) -> bool:
        return self.success

    @property
    def __name__(self) -> str:   # DeepEval labels the column with this
        return "Concordance"


def concordance_scorer(output: Any = None, *, steps: Optional[list] = None,
                       claim: Optional[str] = None, seal: bool = True, **_: Any) -> Dict[str, Any]:
    """autoevals / Braintrust shape. Pass a packet (steps=) or a sentence (claim=/output=).
    score is 1.0 (HOLDS), 0.0 (BROKEN), or None (not checked → the harness skips it)."""
    if steps is None and claim is None:
        claim = output if isinstance(output, str) else str(output)
    out = verdict.read(engine.verify(steps=steps, claim=claim, seal=seal))
    score = None if out.abstained else (1.0 if out.passed else 0.0)
    return {"name": "Concordance", "score": score, "metadata": out.receipt()}
