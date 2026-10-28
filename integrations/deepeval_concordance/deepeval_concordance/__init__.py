"""deepeval_concordance — a DeepEval metric that recomputes the claim instead of asking a judge.

    from deepeval.test_case import LLMTestCase
    from deepeval_concordance import ConcordanceMetric

    metric = ConcordanceMetric(threshold=0.5)
    metric.measure(LLMTestCase(input="...", actual_output="15% of 200 is 30"))
    metric.score, metric.is_successful(), metric.reason, metric.metadata

No LLM is configured or called. `actual_output` is read as: a JSON object with a `steps` list or a `document`
dict (verified as that packet); a JSON `{mode, params}` (verified as that); anything else as a plain-language
`claim`. When the harness already knows the packets, pass `packets=` (alias `steps=`) and the output is only
the claim being scored. Score semantics are the shared client's (integrations/README.md).
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from concordance_client import check
from deepeval.metrics import BaseMetric

__all__ = ["ConcordanceMetric", "decide"]
__version__ = "0.1.0"


def decide(output: Any, *, packets: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Turn a model output (plus an optional packet override) into `check()` keyword arguments."""
    if packets is not None:
        return {"steps": list(packets)}
    if isinstance(output, dict):
        parsed: Any = output
    else:
        text = "" if output is None else str(output)
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            return {"claim": text}
    if isinstance(parsed, dict):
        if isinstance(parsed.get("steps"), list):
            return {"steps": parsed["steps"]}
        if isinstance(parsed.get("document"), dict):
            return {"document": parsed["document"]}
        if isinstance(parsed.get("mode"), str):
            params = parsed.get("params")
            return {"mode": parsed["mode"], "params": params if isinstance(params, dict) else {}}
    # JSON, but not a shape the engine takes as a packet: it is text making a claim.
    return {"claim": "" if output is None else str(output)}


class ConcordanceMetric(BaseMetric):
    """score ∈ [0, 1] (signal strength after attempted refutation), success = score ≥ threshold,
    reason = the client's reason verbatim, metadata = {verdict, read, cite_url, seal_hash, budget, checked}."""

    _required_params: List[Any] = []  # we check actual_output ourselves; no LLM judge, no other fields needed

    def __init__(self, threshold: float = 0.5, packets: Optional[List[Dict[str, Any]]] = None,
                 url: Optional[str] = None, on_unchecked: str = "fail", *,
                 steps: Optional[List[Dict[str, Any]]] = None, seal: bool = True, timeout: float = 30.0,
                 verbose_mode: bool = False, include_reason: bool = True, async_mode: bool = False) -> None:
        if on_unchecked not in ("fail", "pass"):
            raise ValueError('on_unchecked must be "fail" or "pass"')
        if packets is not None and steps is not None:
            raise ValueError("pass packets= or steps=, not both")
        self.threshold = threshold
        self.packets = packets if packets is not None else steps
        self.url = url or os.environ.get("CONCORDANCE_URL") or None
        self.on_unchecked = on_unchecked
        self.seal = seal
        self.timeout = timeout
        self.verbose_mode = verbose_mode
        self.include_reason = include_reason
        self.async_mode = async_mode
        self.strict_mode = False
        self.evaluation_model = "concordance"  # deterministic recomputation; no LLM is involved
        self.score: Optional[float] = None
        self.reason: Optional[str] = None
        self.success: Optional[bool] = None
        self.error: Optional[str] = None
        self.metadata: Dict[str, Any] = {}
        self.score_breakdown: Dict[str, Any] = {}
        self.result: Dict[str, Any] = {}

    def measure(self, test_case: Any, *args: Any, **kwargs: Any) -> float:
        output = getattr(test_case, "actual_output", None)
        if output is None:
            self.error = "test case has no actual_output"
            self.score, self.reason = None, None
            self.success = self.is_successful()
            raise ValueError(self.error)
        self.error = None
        kw = decide(output, packets=self.packets)
        try:
            res = check(seal=self.seal, url=self.url, timeout=self.timeout, on_unchecked=self.on_unchecked, **kw)
        except Exception as e:  # engine unreachable, bad URL — not a verdict about the claim
            self.error = f"{type(e).__name__}: {e}"
            self.score, self.reason = None, None
            self.success = self.is_successful()
            raise
        self.result = res
        self.score = float(res["score"])
        self.reason = res["reason"]
        seal = res.get("seal") or {}
        trace = res.get("trace") or {}
        self.metadata = {
            "verdict": res.get("verdict"),
            "read": res.get("read"),
            "cite_url": res.get("cite_url") or seal.get("cite_url"),
            "seal_hash": seal.get("content_hash"),
            "budget": trace.get("budget"),
            "checked": bool(res.get("checked")),
            "called_with": sorted(kw),
        }
        self.score_breakdown = dict(self.metadata)
        self.success = self.is_successful()
        if self.verbose_mode:
            self.verbose_logs = "\n".join(f"{k}: {v}" for k, v in self.metadata.items()) + f"\nscore: {self.score}"
        return self.score

    async def a_measure(self, test_case: Any, *args: Any, **kwargs: Any) -> float:
        return self.measure(test_case, *args, **kwargs)

    def is_successful(self) -> bool:
        if self.error is not None or self.score is None:
            self.success = False
        else:
            self.success = self.score >= self.threshold
        return self.success

    @property
    def __name__(self) -> str:
        return "Concordance"
