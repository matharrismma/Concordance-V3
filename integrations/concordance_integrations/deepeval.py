"""A scorer for DeepEval (and the dict-shaped autoevals scorer; the `Scorer` class is in `.autoevals`).

It sits where `NumericDiff` would, but needs no expected value and asks no judge: it recomputes
the claim and scores the verdict (`Outcome.score`: HOLDS → 1 − 0.5·worst_used, BROKEN → 0.0).
An un-checkable claim does not score 0 — by default it abstains (`abstain_is_success=True`,
score 1.0, success True) so the engine's honesty about what it could not test is never counted
as a model failure. Flip `abstain_is_success=False` to treat "not checked" as a miss (score 0.0)
when your eval requires every claim to be reachable. Either way `metadata["checked"]` is False
and the reason says nothing was established.

    from concordance_integrations.deepeval import ConcordanceMetric
    metric = ConcordanceMetric()                       # reads test_case.actual_output
    metric.measure(test_case)                          # -> score; metric.reason carries the receipt url
    metric.metadata                                    # verdict, read, cite_url, content_hash, budget, checked, counterexample

The default extractor is the JSON dispatch (`engine.payload_for`): an `actual_output` that parses
as JSON with `steps` / `document` / `{mode, params}` is verified as that packet, anything else
as a plain-language claim. Pass `extract=` to decide yourself: it takes the test case and returns
{"steps": [...]} / {"claim": "..."} / {"document": {...}} / {"mode": ..., "params": {...}}.

`ConcordanceMetric` subclasses DeepEval's BaseMetric when DeepEval is installed (so
`evaluate([...], [metric])` accepts it) and a plain object otherwise, so importing this module
never requires DeepEval. `concordance_scorer(...)` is the autoevals/Braintrust dict shape:
name/score/metadata, score=None when not checked (autoevals reads None as "skip").
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from . import engine, verdict


def _default_extract(test_case: Any) -> Dict[str, Any]:
    """JSON dispatch on the test case's actual_output (see `engine.payload_for`)."""
    output = getattr(test_case, "actual_output", None)
    return engine.payload_for(output if output is not None else str(test_case))


def _base():  # BaseMetric when DeepEval is present, else object — resolved once at import.
    try:
        from deepeval.metrics import BaseMetric
        return BaseMetric
    except Exception:  # noqa: BLE001 — DeepEval optional; any import failure means "not installed"
        return object


class ConcordanceMetric(_base()):  # type: ignore[misc]
    _required_params: List[Any] = []   # actual_output is read by the extractor; no judge, no other fields

    def __init__(self, extract: Optional[Callable[[Any], Dict[str, Any]]] = None,
                 *, threshold: float = 0.5, abstain_is_success: bool = True,
                 seal: bool = True, verbose_mode: bool = False, include_reason: bool = True,
                 async_mode: bool = False) -> None:
        self._extract = extract or _default_extract
        self.threshold = threshold
        self.abstain_is_success = abstain_is_success
        self._seal = seal
        self.verbose_mode = verbose_mode
        self.include_reason = include_reason
        self.async_mode = async_mode
        self.strict_mode = False
        self.score: Optional[float] = None
        self.success: Optional[bool] = None
        self.reason: str = ""
        self.error: Optional[str] = None
        self.receipt: Dict[str, Any] = {}
        self.metadata: Dict[str, Any] = {}
        self.score_breakdown: Dict[str, Any] = {}
        self._abstained = False
        self.evaluation_model = "concordance"   # DeepEval reads this for its report; no LLM is involved

    def measure(self, test_case: Any, *args: Any, **kwargs: Any) -> float:
        self.error = None
        out = verdict.read(engine.verify(**self._extract(test_case), seal=self._seal))
        self.receipt = out.receipt()
        self.metadata = {k: self.receipt[k] for k in
                         ("verdict", "read", "cite_url", "content_hash", "budget", "checked", "counterexample")}
        self.score_breakdown = dict(self.metadata)
        self._abstained = out.abstained
        if out.abstained:
            self.score = 1.0 if self.abstain_is_success else 0.0
            self.reason = (f"not checked ({out.verdict or 'no verdict'}): {out.reason} — nothing was "
                           "established about the claim; this says nothing about whether it is true")
        else:
            self.score = float(out.score)
            tail = f"; link budget: {out.budget['read']}" if out.budget and out.budget.get("read") else ""
            self.reason = out.reason + tail + (f"; receipt {out.cite_url}" if out.cite_url else "")
        self.success = self.is_successful()
        if self.verbose_mode:
            self.verbose_logs = "\n".join(f"{k}: {v}" for k, v in self.metadata.items()) + f"\nscore: {self.score}"
        return self.score

    async def a_measure(self, test_case: Any, *args: Any, **kwargs: Any) -> float:
        return self.measure(test_case, *args, **kwargs)

    def is_successful(self) -> bool:
        if self.error is not None or self.score is None:
            self.success = False
        elif self._abstained:
            self.success = bool(self.abstain_is_success)
        else:
            self.success = self.score >= self.threshold
        return self.success

    @property
    def __name__(self) -> str:   # DeepEval labels the column with this
        return "Concordance"


def concordance_scorer(output: Any = None, *, steps: Optional[list] = None,
                       claim: Optional[str] = None, seal: bool = True, **_: Any) -> Dict[str, Any]:
    """autoevals / Braintrust dict shape. Pass a packet (steps=) or a sentence (claim=), or let the
    JSON dispatch read output=. score is Outcome.score: 1 − 0.5·worst_used (HOLDS), 0.0 (BROKEN),
    or None (not checked → the harness skips it)."""
    if steps is not None:
        payload: Dict[str, Any] = {"steps": steps}
    elif claim is not None:
        payload = {"claim": claim}
    else:
        payload = engine.payload_for(output)
    out = verdict.read(engine.verify(seal=seal, **payload))
    return {"name": "Concordance", "score": out.score, "metadata": out.receipt()}
