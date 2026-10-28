import json

import pytest

pytest.importorskip("autoevals")
pytest.importorskip("concordance")
from autoevals import Score  # noqa: E402

from autoevals_concordance import Concordance  # noqa: E402

RE = {"RE_VERIFY": {"loan_principal": 12_000_000, "annual_rate": 0.045, "loan_term_months": 240,
                    "claimed_monthly_payment": 75917.93}}
GOOD = [{"id": "m", "domain": "real_estate", "spec": RE}]
BAD = [{"id": "m", "domain": "real_estate", "spec": {"RE_VERIFY": dict(RE["RE_VERIFY"], claimed_monthly_payment=70000)}}]


def test_holds_from_json_output(tmp_path, monkeypatch):
    monkeypatch.setenv("CONCORDANCE_DATA_DIR", str(tmp_path))
    s = Concordance()(output=json.dumps({"steps": GOOD}))
    assert isinstance(s, Score) and s.name == "Concordance"
    assert s.metadata["verdict"] == "HOLDS" and s.metadata["checked"] is True and s.metadata["pass"] is True
    assert 0.5 <= s.score <= 1.0 and "receipt" in s.metadata["reason"] and s.metadata["cite_url"]


def test_broken_via_per_row_packets(tmp_path, monkeypatch):
    monkeypatch.setenv("CONCORDANCE_DATA_DIR", str(tmp_path))
    s = Concordance()(output="the monthly payment is 70,000", packets=BAD)
    assert s.metadata["verdict"] == "BROKEN" and s.score == 0.0 and s.metadata["pass"] is False
    assert "counterexample" in s.metadata["reason"] and s.metadata["claim_text"].startswith("the monthly")


def test_unchecked_claim_says_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("CONCORDANCE_DATA_DIR", str(tmp_path))
    s = Concordance()(output="the sky is a lovely colour today")
    assert s.metadata["checked"] is False and s.score == 0.0 and "says nothing" in s.metadata["reason"]
    p = Concordance(on_unchecked="pass")(output="the sky is a lovely colour today")
    assert p.score == 1.0 and p.metadata["checked"] is False and "says nothing" in p.metadata["reason"]
