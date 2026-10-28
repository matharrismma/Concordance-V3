"""ConcordanceMetric inside DeepEval itself: BaseMetric contract, async, and a real `evaluate()`
run with no LLM configured. Skipped when deepeval is not installed."""
import asyncio
import json

import pytest

pytest.importorskip("deepeval")
from deepeval.metrics import BaseMetric  # noqa: E402
from deepeval.test_case import LLMTestCase  # noqa: E402

from concordance_integrations.deepeval import ConcordanceMetric  # noqa: E402
from concordance_integrations.engine import payload_for  # noqa: E402

from conftest import BAD_STEPS, GOOD_STEPS, UNCHECKABLE  # noqa: E402


def tc(output):
    return LLMTestCase(input="q", actual_output=output)


def test_holds_scores_in_band_with_metadata():
    m = ConcordanceMetric()
    s = m.measure(tc(json.dumps({"steps": GOOD_STEPS})))
    assert 0.5 <= s <= 1.0 and m.score == s and m.is_successful() is True
    md = m.metadata
    assert md["verdict"] == "HOLDS" and md["checked"] is True and md["cite_url"] and md["content_hash"]
    assert "worst_used" in md["budget"] and md["counterexample"] is None
    assert "receipt" in m.reason and "link budget" in m.reason


def test_broken_scores_zero_and_names_the_counterexample():
    m = ConcordanceMetric(extract=lambda tc: {"steps": BAD_STEPS})
    assert m.measure(tc("the payment is 70,000")) == 0.0
    assert m.is_successful() is False and m.metadata["verdict"] == "BROKEN"
    assert "counterexample" in m.reason and "recomputed" in m.reason
    assert m.metadata["counterexample"]["what"] == "monthly_payment"


def test_unchecked_says_nothing_under_both_policies():
    m = ConcordanceMetric()
    assert m.measure(tc(UNCHECKABLE)) == 1.0
    assert m.metadata["checked"] is False and "nothing was established" in m.reason and m.is_successful() is True
    strict = ConcordanceMetric(abstain_is_success=False)
    assert strict.measure(tc(UNCHECKABLE)) == 0.0
    assert strict.metadata["checked"] is False and "nothing was established" in strict.reason
    assert strict.is_successful() is False


def test_plain_claim_and_json_dispatch():
    m = ConcordanceMetric()
    assert m.measure(tc("15% of 200 is 30")) >= 0.5 and m.metadata["verdict"] == "HOLDS"
    assert payload_for("not json") == {"claim": "not json"}
    assert payload_for('{"mode": "percent_of", "params": {"a": 1}}') == {"mode": "percent_of", "params": {"a": 1}}
    assert payload_for('{"document": {"title": "t", "steps": []}}') == {"document": {"title": "t", "steps": []}}
    assert payload_for('{"foo": 1}') == {"claim": '{"foo": 1}'}
    assert payload_for(json.dumps({"steps": GOOD_STEPS})) == {"steps": GOOD_STEPS}


def test_deepeval_contract():
    m = ConcordanceMetric()
    assert isinstance(m, BaseMetric) and m.__name__ == "Concordance" and m.evaluation_model == "concordance"
    assert m.model is None  # no LLM configured


def test_async_and_real_evaluate_run_with_no_llm():
    m = ConcordanceMetric()
    assert asyncio.run(m.a_measure(tc(json.dumps({"steps": GOOD_STEPS})))) >= 0.5
    from deepeval import evaluate
    res = evaluate([tc(json.dumps({"steps": GOOD_STEPS})), tc(json.dumps({"steps": BAD_STEPS})), tc(UNCHECKABLE)],
                   [ConcordanceMetric(abstain_is_success=False)])
    results = getattr(res, "test_results", res)
    assert [r.success for r in results] == [True, False, False]
    md = results[2].metrics_data[0]
    assert "nothing was established" in md.reason and md.evaluation_model == "concordance"
