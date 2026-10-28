"""The node inside a compiled StateGraph with `route_on_verdict`, and the LangChain tool. Skipped
when langgraph / langchain-core are not installed."""
import json
from typing import Any, Dict, TypedDict

import pytest

pytest.importorskip("langgraph")
from langgraph.graph import END, START, StateGraph  # noqa: E402

from concordance_integrations.langgraph import make_verify_node, route_on_verdict  # noqa: E402

from conftest import BAD_STEPS, GOOD_STEPS, UNCHECKABLE  # noqa: E402


class S(TypedDict, total=False):
    output: str
    packets: Any
    concordance: Dict[str, Any]
    route: str


class S2(TypedDict, total=False):
    answer: str
    cc: Dict[str, Any]
    route: str


def _graph(schema=S, **node_kw):
    g = StateGraph(schema)
    g.add_node("model", lambda s: {})  # the "model" already wrote `output` / `packets`
    g.add_node("verify", make_verify_node(**node_kw))
    g.add_node("holds", lambda s: {"route": "holds"})
    g.add_node("broken", lambda s: {"route": "broken"})
    g.add_node("unchecked", lambda s: {"route": "unchecked"})
    g.add_edge(START, "model")
    g.add_edge("model", "verify")
    g.add_conditional_edges("verify", lambda s: route_on_verdict(s, node_kw.get("result_key", "concordance")),
                            {"holds": "holds", "broken": "broken", "unchecked": "unchecked"})
    for n in ("holds", "broken", "unchecked"):
        g.add_edge(n, END)
    return g.compile()


def test_holds_from_json_output_routes_holds():
    out = _graph().invoke({"output": json.dumps({"steps": GOOD_STEPS})})
    r = out["concordance"]
    assert r["verdict"] == "HOLDS" and r["checked"] and r["passed"] and 0.5 <= r["score"] <= 1.0
    assert r["cite_url"] and r["content_hash"] and "worst_used" in r["budget"] and r["read"]
    assert out["route"] == "holds"


def test_broken_from_packets_override_routes_broken():
    out = _graph().invoke({"output": "the payment is 70,000 a month", "packets": BAD_STEPS})
    r = out["concordance"]
    assert r["verdict"] == "BROKEN" and r["checked"] and not r["passed"] and r["score"] == 0.0
    assert "counterexample" in r["reason"] and out["route"] == "broken"


def test_unchecked_plain_claim_routes_unchecked():
    out = _graph(S2, input_key="answer", result_key="cc").invoke({"answer": UNCHECKABLE})
    r = out["cc"]
    assert r["checked"] is False and r["score"] is None and r["passed"] is None
    assert out["route"] == "unchecked" and route_on_verdict(out, result_key="cc") == "unchecked"


def test_extract_form_still_composes():
    g = StateGraph(S)
    g.add_node("verify", make_verify_node(lambda s: {"steps": s["packets"]}))
    g.add_edge(START, "verify")
    g.add_edge("verify", END)
    assert g.compile().invoke({"packets": GOOD_STEPS})["concordance"]["passed"] is True


def test_langchain_tool_invoke():
    pytest.importorskip("langchain_core")
    from concordance_integrations.langgraph import concordance_verify
    assert concordance_verify is not None and concordance_verify.name == "concordance_verify"
    r = json.loads(concordance_verify.invoke({"claim": "payment check", "steps_json": json.dumps(GOOD_STEPS)}))
    assert set(r) == {"verdict", "read", "score", "reason", "cite_url", "budget", "checked"}
    assert r["verdict"] == "HOLDS" and 0.5 <= r["score"] <= 1.0
    r = json.loads(concordance_verify.invoke({"claim": "payment check", "steps_json": json.dumps(BAD_STEPS)}))
    assert r["verdict"] == "BROKEN" and r["score"] == 0.0 and "counterexample" in r["reason"]
    r = json.loads(concordance_verify.invoke({"claim": UNCHECKABLE}))
    assert r["score"] is None and r["checked"] is False
