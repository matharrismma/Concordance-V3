import json

import pytest

pytest.importorskip("deepeval")
pytest.importorskip("concordance")
from deepeval.metrics import BaseMetric  # noqa: E402
from deepeval.test_case import LLMTestCase  # noqa: E402

from deepeval_concordance import ConcordanceMetric, decide  # noqa: E402

RE = {"RE_VERIFY": {"loan_principal": 12_000_000, "annual_rate": 0.045, "loan_term_months": 240,
                    "claimed_monthly_payment": 75917.93}}
STEPS = [{"id": "m", "domain": "real_estate", "spec": RE}]
BAD_STEPS = [{"id": "m", "domain": "real_estate", "spec": {"RE_VERIFY": dict(RE["RE_VERIFY"], claimed_monthly_payment=70000)}}]


def tc(output):
    return LLMTestCase(input="q", actual_output=output)


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CONCORDANCE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("CONCORDANCE_URL", raising=False)


def test_holds_scores_in_band():
    m = ConcordanceMetric(threshold=0.5)
    s = m.measure(tc(json.dumps({"steps": STEPS})))
    assert 0.5 <= s <= 1.0 and m.score == s and m.is_successful() is True
    md = m.metadata
    assert md["verdict"] == "HOLDS" and md["checked"] is True and md["cite_url"] and md["seal_hash"]
    assert "worst_used" in md["budget"] and "receipt" in m.reason and m.reason == m.result["reason"]


def test_broken_scores_zero_with_counterexample():
    m = ConcordanceMetric(packets=BAD_STEPS)
    assert m.measure(tc("the payment is 70,000")) == 0.0
    assert m.is_successful() is False and m.metadata["verdict"] == "BROKEN"
    assert "counterexample" in m.reason and m.metadata["called_with"] == ["steps"]


def test_unchecked_says_nothing():
    m = ConcordanceMetric()
    assert m.measure(tc("The sky was blue and the meeting went well.")) == 0.0
    assert m.metadata["checked"] is False and "says nothing" in m.reason and m.is_successful() is False
    p = ConcordanceMetric(on_unchecked="pass")
    assert p.measure(tc("The sky was blue and the meeting went well.")) == 1.0
    assert p.metadata["checked"] is False and "says nothing" in p.reason and p.is_successful() is True


def test_plain_claim_and_decide():
    m = ConcordanceMetric()
    assert m.measure(tc("15% of 200 is 30")) >= 0.5 and m.metadata["verdict"] == "HOLDS"
    assert decide("not json") == {"claim": "not json"}
    assert decide('{"mode": "percent_of", "params": {"a": 1}}') == {"mode": "percent_of", "params": {"a": 1}}
    assert decide('{"document": {"title": "t", "steps": []}}') == {"document": {"title": "t", "steps": []}}
    assert decide('{"foo": 1}') == {"claim": '{"foo": 1}'}
    assert decide("anything", packets=STEPS) == {"steps": STEPS}


def test_deepeval_contract():
    m = ConcordanceMetric()
    assert isinstance(m, BaseMetric) and m.__name__ == "Concordance" and m.evaluation_model == "concordance"
    assert m.model is None  # no LLM configured
    with pytest.raises(ValueError):
        ConcordanceMetric(on_unchecked="maybe")


def test_async_and_evaluate():
    import asyncio
    m = ConcordanceMetric()
    assert asyncio.run(m.a_measure(tc(json.dumps({"steps": STEPS})))) >= 0.5
    from deepeval import evaluate
    res = evaluate([tc(json.dumps({"steps": STEPS})), tc("The sky was blue and the meeting went well.")],
                   [ConcordanceMetric(threshold=0.5)])
    results = getattr(res, "test_results", res)
    assert [r.success for r in results] == [True, False]
    md = results[1].metrics_data[0]
    assert "says nothing" in md.reason and md.evaluation_model == "concordance"
