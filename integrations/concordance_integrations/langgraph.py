"""A verification node for LangGraph (and any graph whose node is callable(state) -> update).

The node is a plain function over a dict, so it drops into a LangGraph `StateGraph` unchanged
and works just as well as an AutoGen tool or a hand-rolled agent loop — nothing here imports
langgraph. You give it one thing: how to pull the claim out of your state.

    from concordance_integrations.langgraph import make_verify_node
    graph.add_node("verify", make_verify_node(lambda s: {"claim": s["answer"]}))

The node writes a receipt under `key` (default "concordance"): {verdict, checked, passed,
reason, content_hash, cite_url}. It never decides the graph for you — routing on the result is
yours. With `fail_fast=True` a real counterexample (BROKEN) raises ConcordanceCounterexample;
a claim the engine could not test never raises (a miss stays a miss).
"""
from __future__ import annotations

from typing import Any, Callable, Dict

from . import engine, verdict


class ConcordanceCounterexample(Exception):
    """Raised by a fail_fast node when the engine found a counterexample."""

    def __init__(self, reason: str, receipt: Dict[str, Any]) -> None:
        super().__init__(reason)
        self.receipt = receipt


def make_verify_node(extract: Callable[[Dict[str, Any]], Dict[str, Any]],
                     *, key: str = "concordance", seal: bool = True,
                     fail_fast: bool = False) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """Build a node. `extract(state)` returns {"steps": [...]} or {"claim": "..."}."""
    def node(state: Dict[str, Any]) -> Dict[str, Any]:
        out = verdict.read(engine.verify(**extract(state), seal=seal))
        receipt = out.receipt()
        if fail_fast and out.checked and not out.passed:
            raise ConcordanceCounterexample(out.reason, receipt)
        return {key: receipt}
    return node
