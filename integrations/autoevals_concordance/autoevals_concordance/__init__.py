"""autoevals_concordance — an autoevals Scorer backed by Concordance.

    from autoevals_concordance import Concordance
    s = Concordance()
    s(output='{"steps": [...]}')                      # model emitted packets
    s(output="15% of 200 is 30")                      # plain-language claim
    s(output="the payment is 75,917.93", packets=[...])  # harness knows the packets

Score semantics are the shared client's (integrations/README.md): not a truth score — signal strength
after attempted refutation. `_run_eval_sync` returns Score(name="Concordance", score, metadata) where
metadata carries verdict, read, reason, cite_url, seal, budget, checked, pass.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from autoevals import Score, Scorer
from concordance_client import check

__all__ = ["Concordance"]


def _route(output: Any) -> Dict[str, Any]:
    """Decide how the model output reaches check(): steps / document / mode+params / claim."""
    data = output
    if isinstance(output, (str, bytes)):
        text = output.decode() if isinstance(output, bytes) else output
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            return {"claim": text}
    if isinstance(data, dict):
        if isinstance(data.get("steps"), list):
            return {"steps": data["steps"]}
        if isinstance(data.get("document"), dict):
            return {"document": data["document"]}
        if isinstance(data.get("mode"), str):
            return {"mode": data["mode"], "params": data.get("params") or {}}
        if isinstance(data.get("claim"), str):
            return {"claim": data["claim"]}
    if isinstance(data, list) and data and all(isinstance(x, dict) for x in data):
        return {"steps": data}
    return {"claim": output if isinstance(output, str) else json.dumps(data, default=str)}


class Concordance(Scorer):
    """autoevals Scorer: verify the model output with Concordance and score it.

    packets / steps: default packet override (the output is then only the claim text, kept in metadata).
    url: engine URL (default: env CONCORDANCE_URL, else in-process).
    on_unchecked: "fail" (default, unchecked → 0.0) or "pass" (unchecked → 1.0); checked=False either way.
    Per-row overrides via kwargs: packets=, steps=, document=, url=.
    """

    def __init__(self, packets: Optional[List[Dict[str, Any]]] = None, url: Optional[str] = None,
                 on_unchecked: str = "fail", *, steps: Optional[List[Dict[str, Any]]] = None,
                 seal: bool = True, timeout: float = 30.0):
        if on_unchecked not in ("fail", "pass"):
            raise ValueError('on_unchecked must be "fail" or "pass"')
        self.packets = packets if packets is not None else steps
        self.url = url
        self.on_unchecked = on_unchecked
        self.seal = seal
        self.timeout = timeout

    def _name(self) -> str:
        return "Concordance"

    def _run_eval_sync(self, output: Any, expected: Any = None, **kwargs: Any) -> Score:
        packets = kwargs.get("packets", kwargs.get("steps", self.packets))
        document = kwargs.get("document")
        if packets is not None:
            target: Dict[str, Any] = {"steps": packets}
        elif document is not None:
            target = {"document": document}
        else:
            target = _route(output)
        r = check(url=kwargs.get("url", self.url), seal=self.seal, timeout=self.timeout,
                  on_unchecked=self.on_unchecked, **target)
        seal = r.get("seal") or {}
        cite = r.get("cite_url") or seal.get("cite_url")
        metadata = {
            "verdict": r.get("verdict"),
            "read": r.get("read"),
            "reason": r.get("reason"),
            "cite_url": cite,
            "seal": seal.get("content_hash") or seal or None,
            "budget": (r.get("trace") or {}).get("budget"),
            "trace": r.get("trace"),
            "checked": r.get("checked"),
            "pass": bool(r.get("checked")) and float(r.get("score") or 0.0) > 0.0,
            "route": next(iter(target)),
        }
        if "steps" in target or "document" in target:
            metadata["claim_text"] = output if isinstance(output, str) else None
        return Score(name=self._name(), score=float(r.get("score") or 0.0), metadata=metadata)
