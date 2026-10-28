import pytest

pytest.importorskip("concordance")
from concordance_client import check, score_of  # noqa: E402

RE = {"RE_VERIFY": {"loan_principal": 12_000_000, "annual_rate": 0.045, "loan_term_months": 240,
                    "claimed_monthly_payment": 75917.93}}


def test_holds_scores_by_margin(tmp_path, monkeypatch):
    monkeypatch.setenv("CONCORDANCE_DATA_DIR", str(tmp_path))
    r = check(steps=[{"id": "m", "domain": "real_estate", "spec": RE}])
    assert r["verdict"] == "HOLDS" and r["checked"] and 0.5 <= r["score"] <= 1.0 and "receipt" in r["reason"]


def test_broken_scores_zero_with_counterexample(tmp_path, monkeypatch):
    monkeypatch.setenv("CONCORDANCE_DATA_DIR", str(tmp_path))
    bad = {"RE_VERIFY": dict(RE["RE_VERIFY"], claimed_monthly_payment=70000)}
    r = check(steps=[{"id": "m", "domain": "real_estate", "spec": bad}])
    assert r["verdict"] == "BROKEN" and r["score"] == 0.0 and "recomputed" in r["reason"]


def test_unchecked_is_not_false():
    r = score_of({"verdict": "INCOMPLETE", "read": "nothing applied"})
    assert r["score"] == 0.0 and r["checked"] is False and "says nothing" in r["reason"]
    assert score_of({"verdict": "INCOMPLETE"}, on_unchecked="pass")["score"] == 1.0
