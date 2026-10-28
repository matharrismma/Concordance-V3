"""The shared score, framework-free: margin-scaled HOLDS, zero BROKEN, None when nothing was established."""
from concordance_integrations import engine, verdict

from conftest import BAD_STEPS, GOOD_STEPS


def test_holds_scores_by_margin():
    out = verdict.read(engine.verify(steps=GOOD_STEPS))
    assert out.verdict == "HOLDS" and out.checked and 0.5 <= out.score <= 1.0
    assert out.score == 1.0 - 0.5 * out.budget["worst_used"] and out.read and out.counterexample is None
    assert out.receipt()["score"] == out.score and "budget" in out.receipt()


def test_broken_scores_zero_with_counterexample():
    out = verdict.read(engine.verify(steps=BAD_STEPS, seal=False))
    assert out.verdict == "BROKEN" and out.score == 0.0
    assert out.counterexample["what"] == "monthly_payment" and "recomputed" in out.reason


def test_unchecked_is_none_not_zero():
    out = verdict.read({"verdict": "INCOMPLETE", "read": "nothing applied"})
    assert out.score is None and out.checked is False and out.passed is None and out.budget is None


def test_margin_clamps_inf_to_the_edge_and_no_band_to_centre():
    at_edge = verdict.Outcome("HOLDS", True, True, "", None, None, None, {"worst_used": float("inf")}, None)
    assert at_edge.score == 0.5
    no_budget = verdict.Outcome("HOLDS", True, True, "", None, None, None, None, None)
    assert no_budget.score == 1.0          # no banded checks: nothing spent
    unbanded = verdict.Outcome("HOLDS", True, True, "", None, None, None, {"worst_used": None}, None)
    assert unbanded.score == 1.0
    over = verdict.Outcome("HOLDS", True, True, "", None, None, None, {"worst_used": 3.0}, None)
    assert over.score == 0.5
    centre = verdict.Outcome("HOLDS", True, True, "", None, None, None, {"worst_used": 0.0}, None)
    assert centre.score == 1.0
