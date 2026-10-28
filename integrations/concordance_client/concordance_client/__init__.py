"""concordance_client — verify a claim, get a score that means something.

    from concordance_client import check
    r = check(steps=[{"id": "m", "domain": "real_estate", "spec": {...}}])
    r = check(document={"title": ..., "steps": [...]})
    r = check(claim="15% of 200 is 30")

Talks to a running engine when CONCORDANCE_URL is set (or `url=` is passed), otherwise imports the engine
in-process. Returns the engine's response plus `score`, `checked` and `reason` under the shared semantics
(integrations/README.md): not a truth score — signal strength after attempted refutation.
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Any, Dict, List, Optional

__all__ = ["check", "score_of", "CheckResult"]

CheckResult = Dict[str, Any]


def _http(url: str, body: Dict[str, Any], timeout: float) -> Dict[str, Any]:
    req = urllib.request.Request(url.rstrip("/") + "/verify", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _local(body: Dict[str, Any]) -> Dict[str, Any]:
    from concordance.config import EngineConfig
    from concordance.mcp.server import _call_tool
    return _call_tool("verify", body, EngineConfig())


def score_of(res: Dict[str, Any], *, on_unchecked: str = "fail") -> Dict[str, Any]:
    """Shared score semantics. HOLDS → 1 − 0.5·worst_used; BROKEN → 0; unchecked → 0 (or 1 with
    on_unchecked="pass"), always with checked=False and a reason that says nothing was established."""
    verdict = str(res.get("verdict") or "")
    trace = res.get("trace") or {}
    budget = trace.get("budget") or {}
    worst = budget.get("worst_used")
    cite = res.get("cite_url") or (res.get("seal") or {}).get("cite_url") or (res.get("seal") or {}).get("content_hash")
    if verdict == "HOLDS":
        used = float(worst) if isinstance(worst, (int, float)) and worst != float("inf") else 0.0
        used = min(max(used, 0.0), 1.0)
        return {"score": 1.0 - 0.5 * used, "checked": True, "verdict": verdict,
                "reason": (res.get("read") or "survived every attempted refutation")
                          + (f"; link budget: {budget.get('read')}" if budget.get("read") else "")
                          + (f"; receipt {cite}" if cite else "")}
    if verdict == "BROKEN":
        cx = []
        for t in res.get("trail") or []:
            cx += (t.get("refutations") or {}).get("counterexamples") or []
        first = cx[0] if cx else {}
        detail = (f"{first.get('what')}: claimed {first.get('claimed')}, recomputed {first.get('recomputed')}, "
                  f"off by {first.get('off_by')}" if first else (res.get("read") or "a counterexample"))
        return {"score": 0.0, "checked": True, "verdict": verdict,
                "reason": f"counterexample — {detail}" + (f"; receipt {cite}" if cite else "")}
    # nothing established about the claim
    why = res.get("read") or res.get("means") or res.get("note") or verdict or "not checked"
    return {"score": 1.0 if on_unchecked == "pass" else 0.0, "checked": False, "verdict": verdict or "UNCHECKED",
            "reason": f"not checked ({verdict or 'no verdict'}): {why} — this says nothing about whether the claim is true"}


def check(*, steps: Optional[List[Dict[str, Any]]] = None, document: Optional[Dict[str, Any]] = None,
          claim: Optional[str] = None, mode: Optional[str] = None, params: Optional[Dict[str, Any]] = None,
          seal: bool = True, url: Optional[str] = None, timeout: float = 30.0,
          on_unchecked: str = "fail") -> CheckResult:
    """Verify one thing. Exactly one of steps / document / claim / (mode, params)."""
    body: Dict[str, Any] = {"seal": seal}
    if steps is not None:
        body["steps"] = steps
    elif document is not None:
        body["document"] = document
    elif claim is not None:
        body["claim"] = claim
    elif mode is not None:
        body["mode"], body["params"] = mode, params or {}
    else:
        raise ValueError("check() needs steps, document, claim, or mode+params")
    base = url or os.environ.get("CONCORDANCE_URL")
    res = _http(base, body, timeout) if base else _local(body)
    out = dict(res)
    out.update(score_of(res, on_unchecked=on_unchecked))
    return out
