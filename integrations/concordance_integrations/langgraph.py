"""A verification node for LangGraph (and any graph whose node is callable(state) -> update),
a verdict router for `add_conditional_edges`, and a LangChain tool.

The node is a plain function over a dict, so it drops into a LangGraph `StateGraph` unchanged
and works just as well as an AutoGen tool or a hand-rolled agent loop — nothing here imports
langgraph. You give it one thing: how to pull the claim out of your state.

    from concordance_integrations.langgraph import make_verify_node, route_on_verdict
    graph.add_node("verify", make_verify_node(lambda s: {"claim": s["answer"]}))
    graph.add_conditional_edges("verify", route_on_verdict,
                                {"holds": END, "broken": "retry", "unchecked": "ask_human"})

`make_verify_node(input_key="output")` is the no-lambda form: it reads `state[input_key]` through
the JSON dispatch (`engine.payload_for`: JSON with steps / document / {mode, params} is verified as
that packet, anything else as a plain claim), and `state[packets_key]` (a steps list) overrides it
when the harness already knows the packets.

The node writes the receipt under `key` (default "concordance"): {verdict, checked, passed, score,
reason, read, content_hash, cite_url, budget, counterexample}. `score` is Outcome.score (HOLDS →
1 − 0.5·worst_used, BROKEN → 0.0, not checked → None). With `fail_fast=True` a real counterexample
(BROKEN) raises ConcordanceCounterexample; a claim the engine could not test never raises (a miss
stays a miss). `route_on_verdict(state)` returns "holds" | "broken" | "unchecked".

`concordance_verify` is the same check as a LangChain tool, defined only when langchain_core is
importable (else None).
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, Mapping, Optional

from . import engine, verdict

__all__ = ["ConcordanceCounterexample", "make_verify_node", "route_on_verdict", "verify_output",
           "concordance_verify"]


class ConcordanceCounterexample(Exception):
    """Raised by a fail_fast node when the engine found a counterexample."""

    def __init__(self, reason: str, receipt: Dict[str, Any]) -> None:
        super().__init__(reason)
        self.receipt = receipt


def verify_output(output: Any, *, packets: Any = None, seal: bool = True) -> Dict[str, Any]:
    """Verify one model output (or the harness's packets) and return the receipt the node writes."""
    if packets is not None:
        if isinstance(packets, list):
            payload: Dict[str, Any] = {"steps": packets}
        elif isinstance(packets, Mapping):
            payload = engine.payload_for(dict(packets))
        else:
            raise ValueError("packets must be a steps list, {steps}, {document}, or {mode, params}")
    else:
        payload = engine.payload_for(output)
    return verdict.read(engine.verify(seal=seal, **payload)).receipt()


def make_verify_node(extract: Optional[Callable[[Mapping[str, Any]], Dict[str, Any]]] = None,
                     *, key: str = "concordance", seal: bool = True, fail_fast: bool = False,
                     input_key: str = "output", packets_key: str = "packets",
                     result_key: Optional[str] = None) -> Callable[[Mapping[str, Any]], Dict[str, Any]]:
    """Build a node. `extract(state)` returns {"steps": [...]} / {"claim": "..."} / {"document": ...} /
    {"mode": ..., "params": ...}; without it the node reads `state[input_key]` via the JSON dispatch,
    overridden by `state[packets_key]`. `result_key` is an alias for `key`."""
    key = result_key or key

    def node(state: Mapping[str, Any]) -> Dict[str, Any]:
        if extract is not None:
            receipt = verdict.read(engine.verify(**extract(state), seal=seal)).receipt()
        else:
            output, packets = state.get(input_key), state.get(packets_key)
            if output is None and packets is None:
                raise KeyError(f"verify node: state has neither {input_key!r} nor {packets_key!r}")
            receipt = verify_output(output, packets=packets, seal=seal)
        if fail_fast and receipt["checked"] and not receipt["passed"]:
            raise ConcordanceCounterexample(receipt["reason"], receipt)
        return {key: receipt}
    node.__name__ = "concordance_verify"
    return node


def route_on_verdict(state: Mapping[str, Any], result_key: str = "concordance") -> str:
    """For `add_conditional_edges`: "holds" | "broken" | "unchecked"."""
    r = state.get(result_key) or {}
    if not r.get("checked"):
        return "unchecked"
    return "holds" if r.get("verdict") == "HOLDS" else "broken"


_TOOL_FIELDS = ("verdict", "read", "score", "reason", "cite_url", "budget", "checked")


def _define_tool():
    from langchain_core.tools import tool as _lc_tool

    @_lc_tool
    def concordance_verify(claim: str, steps_json: str = "") -> str:
        """Verify an arithmetic or formula claim by recomputing it. Pass the claim in plain language,
        or `steps_json` (a JSON list of step packets, or {"steps": [...]} / {"document": {...}}) when
        the packets are known. Returns JSON: verdict, read, score, reason, cite_url, budget, checked.
        HOLDS is a survived refutation and BROKEN is a counterexample; anything else means the claim
        was not checked (score null) and says nothing about whether it is true."""
        packets = json.loads(steps_json) if steps_json else None
        r = verify_output(claim, packets=packets)
        return json.dumps({k: r.get(k) for k in _TOOL_FIELDS}, separators=(",", ":"), default=str)

    return concordance_verify


try:
    concordance_verify: Any = _define_tool()
except Exception:  # noqa: BLE001 — langchain-core optional; the node and router still work
    concordance_verify = None
