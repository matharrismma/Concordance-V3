"""Read an engine verdict the one honest way, once, so every adapter agrees.

Three outcomes, never two. A model that only knows pass/fail will score an un-checkable claim
as a failure, which punishes the engine for its own honesty. So the Outcome keeps `checked`
apart from `passed`:

  HOLDS      -> checked, passed        (survived every attempted refutation; carries a seal)
  BROKEN     -> checked, not passed    (a counterexample — the claim is outside the band)
  anything   -> not checked, passed=None
  else                                 (INCOMPLETE, a gap, or an engine failure — a miss stays
                                        a miss; the adapter must not read it as a verdict)

`score` is the one number every adapter reports, and it is not a truth score — it is signal
strength after attempted refutation:

  HOLDS      -> 1 − 0.5·worst_used     (worst_used = trace.budget.worst_used, the share of its
                                        tightest allowance the chain spent: 1.0 dead centre, 0.5
                                        at the edge; null = no banded checks, nothing spent -> 1.0;
                                        inf -> 0.5)
  BROKEN     -> 0.0
  anything   -> None                   (nothing was established; the adapter decides what None
  else                                  means for its harness — never a failure by default)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

HOLDS = "HOLDS"
BROKEN = "BROKEN"
INCOMPLETE = "INCOMPLETE"

_READ = {
    HOLDS: "survived every attempted refutation; shown not false, never shown true",
    BROKEN: "a counterexample was found — the claim is outside the band",
    INCOMPLETE: "at least one step could not be tested — a gap, not a verdict",
}


@dataclass(frozen=True)
class Outcome:
    verdict: str                      # the engine's own verdict string, verbatim
    checked: bool                     # True only for HOLDS / BROKEN — the engine actually tested it
    passed: Optional[bool]            # True=HOLDS, False=BROKEN, None=not checked
    reason: str                       # one sentence, from the engine where it gave one
    content_hash: Optional[str]       # the seal address, when sealed
    cite_url: Optional[str]           # the receipt page, when sealed
    read: Optional[str] = None        # the engine's one-sentence read, verbatim (None if it gave none)
    budget: Optional[Dict[str, Any]] = None          # trace.budget — the link budget, when traced
    counterexample: Optional[Dict[str, Any]] = field(default=None)  # the first counterexample, on BROKEN

    @property
    def abstained(self) -> bool:
        return not self.checked

    @property
    def score(self) -> Optional[float]:
        """HOLDS -> 1 − 0.5·worst_used (clamped to [0, 1]); BROKEN -> 0.0; not checked -> None."""
        if not self.checked:
            return None
        if not self.passed:
            return 0.0
        return 1.0 - 0.5 * _worst_used(self.budget)

    def receipt(self) -> Dict[str, Any]:
        """A flat, framework-free dict to drop into a trace, a message, or agent state."""
        return {"verdict": self.verdict, "checked": self.checked, "passed": self.passed,
                "score": self.score, "reason": self.reason, "read": self.read,
                "content_hash": self.content_hash, "cite_url": self.cite_url,
                "budget": self.budget, "counterexample": self.counterexample}


def _worst_used(budget: Optional[Dict[str, Any]]) -> float:
    """The share of its tightest allowance the chain spent, clamped to [0, 1]. The engine reports
    `worst_used: null` for a chain with no banded checks (every step exact — a rulebook, not a
    tolerance): nothing was spent, so that reads as 0.0. An infinite or NaN value reads as 1.0 —
    the edge of the band."""
    w = (budget or {}).get("worst_used")
    if w is None or isinstance(w, bool) or not isinstance(w, (int, float)):
        return 0.0
    if math.isnan(w) or math.isinf(w):
        return 1.0
    return min(max(float(w), 0.0), 1.0)


def _first_counterexample(result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for step in result.get("trail") or []:
        if not isinstance(step, dict):
            continue
        cx = (step.get("refutations") or {}).get("counterexamples") or []
        if cx and isinstance(cx[0], dict):
            return dict(cx[0])
    return None


def read(result: Dict[str, Any]) -> Outcome:
    """Map a raw engine result (engine.verify's return) to an Outcome."""
    result = result or {}
    v = str(result.get("verdict") or "")
    seal = result.get("seal") if isinstance(result.get("seal"), dict) else {}
    content_hash = seal.get("content_hash") or None
    cite_url = seal.get("cite_url") or None
    engine_read = result.get("read") or None
    trace = result.get("trace") if isinstance(result.get("trace"), dict) else {}
    budget = trace.get("budget") if isinstance(trace.get("budget"), dict) else None
    reason = (engine_read or result.get("means") or result.get("note")
              or _READ.get(v) or f"the engine returned {v or 'no verdict'}; nothing to read as a finding")
    if v == HOLDS:
        return Outcome(v, True, True, reason, content_hash, cite_url, engine_read, budget, None)
    if v == BROKEN:
        cx = _first_counterexample(result)
        if cx:
            reason = (f"counterexample — {cx.get('what')}: claimed {cx.get('claimed')}, "
                      f"recomputed {cx.get('recomputed')}, off by {cx.get('off_by')}")
        return Outcome(v, True, False, reason, content_hash, cite_url, engine_read, budget, cx)
    return Outcome(v, False, None, reason, content_hash, cite_url, engine_read, budget, None)
