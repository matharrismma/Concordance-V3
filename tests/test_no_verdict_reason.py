"""A NO-VERDICT STEP KEEPS ITS CHECK'S OWN REASON (derivation._reduce_domain_results, verifiers.base.dispatch).

Before 2026-11-27 every step with no applicable check read one line, "no applicable secular verifier for this
domain/artifact", whatever the check had said: the explicit formula past 356 had worked out that the zeros cannot hear
that far and to lower X, and calc_chain (Kind B) had asked for the arithmetic with an example, and both were dropped.
Measured over 2,190 cases (the benchmark's domain and check cases, every domain empty and with a wrong key, a packet
given but missing fields for each dispatch domain, the 765 stick seal steps): no verdict, step status or seal moved,
and 482 of the 483 no-verdict steps now give their check's own reason. The one left reads the generic line because no
check answered at all (an unknown domain). These pin that, and that a decline's data is never bound.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from concordance.derivation import verify_derivation
from concordance.verifiers.base import dispatch

ROOT = Path(__file__).resolve().parents[1]
GENERIC = "no applicable secular verifier for this domain/artifact"


@pytest.fixture
def real_data(monkeypatch):
    monkeypatch.setenv("CONCORDANCE_DATA_DIR", str(ROOT / "data"))
    monkeypatch.setenv("CONCORDANCE_MEMO", "0")


def _one(step):
    r = verify_derivation([dict(step, id="a")])
    return r, r["trail"][0]


def test_the_check_that_declined_says_why(real_data):
    r, t = _one({"domain": "number_theory",
                 "spec": {"NUM_VERIFY": {"explicit_formula_to": 357, "claimed_zeros_give_primes": True}}})
    assert r["verdict"] == "INCOMPLETE" and t["status"] == "NOT_APPLICABLE"
    assert t["detail"].startswith("number_theory.explicit_formula: ")
    assert "cannot hear every number this far" in t["detail"] and "Lower X" in t["detail"]
    assert t["refutations"]["not_applicable"] == ["number_theory.explicit_formula"]
    assert not r.get("seal")


def test_a_framed_decline_reaches_the_guidance(real_data):
    _, t = _one({"domain": "mathematics",
                 "spec": {"MATH_VERIFY": {"solution_text": "She has nine left, so the answer is 18 dollars."}}})
    assert t["status"] == "NOT_APPLICABLE" and t["detail"].startswith("mathematics.calc_chain: ")
    g = t["guidance"]
    assert g["route"] == "mathematics mode=calc_chain" and g["example"]["claimed_answer"] == 18
    assert "framing_question" in g and "need" in g


def test_a_given_artifact_is_never_called_absent(real_data):
    _, t = _one({"domain": "number_theory", "spec": {"NUM_VERIFY": {"explicit_formula_to": 30}}})
    assert t["detail"] == ("number_theory: NUM_VERIFY is given, but no check here has every field it needs "
                           "(given: explicit_formula_to)")
    _, t = _one({"domain": "number_theory", "spec": {}})
    assert t["detail"] == "number_theory: no NUM_VERIFY artifacts present"


def test_only_a_domain_no_check_answered_reads_the_generic_line(real_data):
    r, t = _one({"domain": "not_a_domain_at_all", "spec": {"X": {"y": 1}}})
    assert t["status"] == "NOT_APPLICABLE" and t["detail"] == GENERIC and r["verdict"] == "INCOMPLETE"


def test_a_declines_data_is_never_bound(real_data):
    """The decline now carries its data; a bind still reads a source only once it is confirmed."""
    r = verify_derivation([
        {"id": "a", "domain": "mathematics",
         "spec": {"MATH_VERIFY": {"solution_text": "She has nine left, so the answer is 18 dollars."}}},
        {"id": "b", "domain": "number_theory", "uses": ["a"], "bind": {"NUM_VERIFY.n_prime": "a.route"},
         "spec": {"NUM_VERIFY": {"n_prime": 97, "claimed_prime": True}}},
    ])
    b = next(t for t in r["trail"] if t["id"] == "b")
    assert b["status"] == "NOT_APPLICABLE" and b.get("unresolved_binding")
    assert r["verdict"] != "HOLDS" and not r.get("seal")


def test_long_field_lists_are_capped():
    art = {f"field_{i:03d}": i for i in range(60)}
    out = dispatch({"K": art}, "K", [(("never",), lambda a: None)], domain="d", none_reason="nope")
    assert len(out) == 1 and out[0].status == "NOT_APPLICABLE"
    assert out[0].detail.endswith("…)") and len(out[0].detail) < 260
