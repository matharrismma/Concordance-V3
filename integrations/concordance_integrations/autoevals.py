"""An autoevals / Braintrust `Scorer` backed by the engine.

    from concordance_integrations.autoevals import Concordance
    s = Concordance()
    s(output='{"steps": [...]}')                          # model emitted packets
    s(output="15% of 200 is 30")                          # plain-language claim
    s(output="the payment is 75,917.93", steps=[...])     # harness knows the packets (per-row override)

Score semantics are `verdict.Outcome.score`: HOLDS → 1 − 0.5·worst_used, BROKEN → 0.0, not checked →
None (autoevals reads None as "skip" — an un-checkable claim is never a failure). `metadata` is the
receipt (verdict, checked, passed, score, reason, read, content_hash, cite_url, budget, counterexample)
plus `route` (which argument reached the engine) and `claim_text` when the output was only the claim.

`Concordance` is defined only when autoevals is importable (else None), so importing this module
never requires autoevals. `concordance_scorer` (the same decision as a plain dict) lives in `.deepeval`.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import engine, verdict
from .deepeval import concordance_scorer  # noqa: F401 — re-exported: the dict-shaped scorer

__all__ = ["Concordance", "concordance_scorer", "score_output"]


def score_output(output: Any, *, steps: Optional[List[Dict[str, Any]]] = None,
                 document: Optional[Dict[str, Any]] = None, seal: bool = True) -> Dict[str, Any]:
    """Framework-free core: the Score's fields as a dict {name, score, metadata}."""
    if steps is not None:
        target: Dict[str, Any] = {"steps": steps}
    elif document is not None:
        target = {"document": document}
    else:
        target = engine.payload_for(output)
    out = verdict.read(engine.verify(seal=seal, **target))
    metadata = out.receipt()
    metadata["route"] = next(iter(target))
    if "claim" not in target:
        metadata["claim_text"] = output if isinstance(output, str) else None
    return {"name": "Concordance", "score": out.score, "metadata": metadata}


def _define():
    from autoevals import Score, Scorer

    class Concordance(Scorer):
        """autoevals Scorer: verify the model output with the engine and score the verdict.
        Per-row overrides via kwargs: steps= (alias packets=), document=."""

        def __init__(self, steps: Optional[List[Dict[str, Any]]] = None, *,
                     packets: Optional[List[Dict[str, Any]]] = None, seal: bool = True) -> None:
            self.steps = steps if steps is not None else packets
            self.seal = seal

        def _name(self) -> str:
            return "Concordance"

        def _run_eval_sync(self, output: Any, expected: Any = None, **kwargs: Any) -> Score:
            steps = kwargs.get("steps", kwargs.get("packets", self.steps))
            r = score_output(output, steps=steps, document=kwargs.get("document"), seal=self.seal)
            return Score(name=r["name"], score=r["score"], metadata=r["metadata"])

    return Concordance


try:
    Concordance: Any = _define()
except Exception:  # noqa: BLE001 — autoevals optional; import of this module must still work
    Concordance = None
