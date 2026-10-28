"""The autoevals `Scorer` subclass, returning a real `Score`. Skipped when autoevals is not installed."""
import json

import pytest

pytest.importorskip("autoevals")
from autoevals import Score, Scorer  # noqa: E402

from concordance_integrations.autoevals import Concordance  # noqa: E402

from conftest import BAD_STEPS, GOOD_STEPS, UNCHECKABLE  # noqa: E402


def test_holds_from_json_output():
    s = Concordance()(output=json.dumps({"steps": GOOD_STEPS}))
    assert isinstance(s, Score) and isinstance(Concordance(), Scorer) and s.name == "Concordance"
    assert s.metadata["verdict"] == "HOLDS" and s.metadata["checked"] is True and s.metadata["passed"] is True
    assert 0.5 <= s.score <= 1.0 and s.metadata["cite_url"] and s.metadata["route"] == "steps"


def test_broken_via_per_row_steps():
    s = Concordance()(output="the monthly payment is 70,000", steps=BAD_STEPS)
    assert s.metadata["verdict"] == "BROKEN" and s.score == 0.0 and s.metadata["passed"] is False
    assert "counterexample" in s.metadata["reason"] and s.metadata["claim_text"].startswith("the monthly")


def test_unchecked_is_skipped_not_failed():
    s = Concordance()(output=UNCHECKABLE)
    assert s.score is None and s.metadata["checked"] is False and s.metadata["passed"] is None
