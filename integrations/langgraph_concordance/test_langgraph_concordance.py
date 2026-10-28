import json
from typing import Any, Dict, TypedDict

import pytest

pytest.importorskip("concordance")
pytest.importorskip("langgraph")
pytest.importorskip("langchain_core")
from langgraph.graph import END, START, StateGraph  # noqa: E402

from langgraph_concordance import concordance_verify, make_verify_node, route_on_verdict  # noqa: E402

RE = {"RE_VERIFY": {"loan_principal": 12_000_000, "annual_rate": 0.045, "loan_term_months": 240,
                    "claimed_monthly_payment": 75917.93}}
GOOD = [{"id": "m", "domain": "real_estate", "spec": RE}]
BAD = [{"id": "m", "domain": "real_estate", "spec": {"RE_VERIFY": dict(RE["RE_VERIFY"], claimed_monthly_payment=70000)}}]


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
    g.add_conditional_edges("verify", route_on_verdict, {"holds": "holds", "broken": "broken", "unchecked": "unchecked"})
    for n in ("holds", "broken", "unchecked"):
        g.add_edge(n, END)
    return g.compile()


def test_holds_from_json_output(tmp_path, monkeypatch):
    monkeypatch.setenv("CONCORDANCE_DATA_DIR", str(tmp_path))
    out = _graph().invoke({"output": json.dumps({"steps": GOOD})})
    r = out["concordance"]
    assert r["verdict"] == "HOLDS" and r["checked"] and r["passed"] and 0.5 <= r["score"] <= 1.0
    assert r["cite_url"] or r["seal_hash"]
    assert "worst_used" in r["budget"]
    assert out["route"] == "holds"


def test_broken_from_packets_override(tmp_path, monkeypatch):
    monkeypatch.setenv("CONCORDANCE_DATA_DIR", str(tmp_path))
    out = _graph().invoke({"output": "the payment is 70,000 a month", "packets": BAD})
    r = out["concordance"]
    assert r["verdict"] == "BROKEN" and r["checked"] and not r["passed"] and r["score"] == 0.0
    assert "counterexample" in r["reason"]
    assert out["route"] == "broken"


def test_unchecked_plain_claim(tmp_path, monkeypatch):
    monkeypatch.setenv("CONCORDANCE_DATA_DIR", str(tmp_path))
    out = _graph(S2, input_key="answer", result_key="cc").invoke({"answer": "the weather tomorrow will be nice"})
    r = out["cc"]
    assert r["checked"] is False and r["score"] == 0.0 and not r["passed"]
    assert "says nothing" in r["reason"]
    assert route_on_verdict(out, result_key="cc") == "unchecked"


def test_unchecked_pass_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("CONCORDANCE_DATA_DIR", str(tmp_path))
    out = _graph(on_unchecked="pass").invoke({"output": "the weather tomorrow will be nice"})
    r = out["concordance"]
    assert r["checked"] is False and r["score"] == 1.0 and r["passed"] and "says nothing" in r["reason"]
    assert out["route"] == "unchecked"


def test_tool_invoke(tmp_path, monkeypatch):
    monkeypatch.setenv("CONCORDANCE_DATA_DIR", str(tmp_path))
    assert concordance_verify.name == "concordance_verify"
    r = json.loads(concordance_verify.invoke({"claim": "payment check", "steps_json": json.dumps(GOOD)}))
    assert set(r) == {"verdict", "read", "score", "reason", "cite_url", "budget"}
    assert r["verdict"] == "HOLDS" and 0.5 <= r["score"] <= 1.0
    r = json.loads(concordance_verify.invoke({"claim": "payment check", "steps_json": json.dumps(BAD)}))
    assert r["verdict"] == "BROKEN" and r["score"] == 0.0 and "counterexample" in r["reason"]
    r = json.loads(concordance_verify.invoke({"claim": "the weather tomorrow will be nice"}))
    assert r["score"] == 0.0 and "says nothing" in r["reason"]
