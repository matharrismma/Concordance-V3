"""langgraph_concordance — Concordance as a LangGraph node, a verdict router, and a LangChain tool.

    from langgraph_concordance import make_verify_node, route_on_verdict, concordance_verify

    graph.add_node("verify", make_verify_node(input_key="output"))
    graph.add_conditional_edges("verify", route_on_verdict,
                                {"holds": END, "broken": "retry", "unchecked": "ask_human"})

The node reads the model's output from `state[input_key]` and decides how to call the shared client:
JSON with a `steps` list or a `document` dict is verified as such; JSON `{mode, params}` likewise; anything
else is a plain-language claim. `state[packets_key]` (a steps list, or a dict with `steps`/`document`)
overrides the parsed output when the harness already knows the packets. Score semantics are the client's
(integrations/README.md): signal strength after attempted refutation, not a truth score.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, Mapping, Optional

from concordance_client import check

__all__ = ["make_verify_node", "route_on_verdict", "concordance_verify", "verify_output"]


def _kwargs_for(output: Any, packets: Any = None) -> Dict[str, Any]:
    """Pick the one argument `check()` gets. Explicit packets win; then parsed JSON; then a claim."""
    if packets is not None:
        if isinstance(packets, list):
            return {"steps": packets}
        if isinstance(packets, Mapping):
            if isinstance(packets.get("steps"), list) and "title" not in packets and "document" not in packets:
                return {"steps": list(packets["steps"])}
            if isinstance(packets.get("document"), Mapping):
                return {"document": dict(packets["document"])}
            if isinstance(packets.get("steps"), list):
                return {"document": dict(packets)}
            if packets.get("mode"):
                return {"mode": str(packets["mode"]), "params": dict(packets.get("params") or {})}
        raise ValueError("packets must be a steps list, {steps}, {document}, or {mode, params}")
    parsed: Any = output
    if isinstance(output, (str, bytes)):
        text = output.decode() if isinstance(output, bytes) else output
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            return {"claim": text}
    if isinstance(parsed, Mapping):
        if isinstance(parsed.get("steps"), list):
            return {"steps": list(parsed["steps"])}
        if isinstance(parsed.get("document"), Mapping):
            return {"document": dict(parsed["document"])}
        if parsed.get("mode"):
            return {"mode": str(parsed["mode"]), "params": dict(parsed.get("params") or {})}
    if isinstance(parsed, list) and parsed and all(isinstance(p, Mapping) and "domain" in p for p in parsed):
        return {"steps": list(parsed)}
    return {"claim": output if isinstance(output, str) else json.dumps(output)}


def _shape(res: Dict[str, Any]) -> Dict[str, Any]:
    """The native shape the node writes into state."""
    seal = res.get("seal") or {}
    budget = (res.get("trace") or {}).get("budget") or {}
    return {
        "score": res["score"],
        # checked: HOLDS passes, BROKEN fails; unchecked: only on_unchecked="pass" (score 1.0) passes
        "passed": (res.get("verdict") == "HOLDS") if res.get("checked") else res["score"] >= 1.0,
        "reason": res["reason"],
        "verdict": res.get("verdict"),
        "read": res.get("read"),
        "checked": bool(res.get("checked")),
        "cite_url": res.get("cite_url") or seal.get("cite_url"),
        "seal_hash": seal.get("content_hash"),
        "budget": budget,
        "trace": res.get("trace"),
    }


def verify_output(output: Any, *, packets: Any = None, url: Optional[str] = None,
                  on_unchecked: str = "fail", seal: bool = True, timeout: float = 30.0) -> Dict[str, Any]:
    """Verify one model output (or the harness's packets) and return the node's result shape."""
    res = check(url=url, on_unchecked=on_unchecked, seal=seal, timeout=timeout, **_kwargs_for(output, packets))
    return _shape(res)


def make_verify_node(input_key: str = "output", result_key: str = "concordance", packets_key: str = "packets",
                     url: Optional[str] = None, on_unchecked: str = "fail", *, seal: bool = True,
                     timeout: float = 30.0) -> Callable[[Mapping[str, Any]], Dict[str, Any]]:
    """Build a LangGraph node: `state -> {result_key: {score, passed, reason, verdict, read, checked,
    cite_url, seal_hash, budget, trace}}`. Reads `state[input_key]`; `state[packets_key]` overrides it."""
    def verify(state: Mapping[str, Any]) -> Dict[str, Any]:
        output = state.get(input_key)
        packets = state.get(packets_key)
        if output is None and packets is None:
            raise KeyError(f"verify node: state has neither {input_key!r} nor {packets_key!r}")
        return {result_key: verify_output(output, packets=packets, url=url, on_unchecked=on_unchecked,
                                          seal=seal, timeout=timeout)}
    verify.__name__ = "concordance_verify"
    return verify


def route_on_verdict(state: Mapping[str, Any], result_key: str = "concordance") -> str:
    """For `add_conditional_edges`: "holds" | "broken" | "unchecked"."""
    r = state.get(result_key) or {}
    if not r.get("checked"):
        return "unchecked"
    return "holds" if r.get("verdict") == "HOLDS" else "broken"


try:
    from langchain_core.tools import tool as _lc_tool
except ImportError:  # langchain-core is optional at import time; the node and router still work
    concordance_verify = None  # type: ignore[assignment]
else:
    @_lc_tool
    def concordance_verify(claim: str, steps_json: str = "") -> str:
        """Verify an arithmetic or formula claim with Concordance. Pass the claim in plain language, or
        `steps_json` (a JSON list of step packets, or {"steps": [...]} / {"document": {...}}) when the
        packets are known. Returns JSON: verdict, read, score, reason, cite_url, budget. A verdict of
        HOLDS is a survived refutation and BROKEN is a counterexample; anything else means the claim was
        not checked and says nothing about whether it is true."""
        packets = None
        if steps_json:
            packets = json.loads(steps_json)
        r = verify_output(claim, packets=packets)
        return json.dumps({k: r.get(k) for k in ("verdict", "read", "score", "reason", "cite_url", "budget")},
                          separators=(",", ":"), default=str)
