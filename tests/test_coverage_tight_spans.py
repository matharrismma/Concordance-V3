"""P2 regression (2026-10-23): a compound sentence with one checkable clause and one unchecked clause must
never report coverage.complete. The 2026-10-17 review found `verify {claim}` returning complete=true on the
boiling-point sentence because a slot-filler quoted the whole sentence as the claim span."""
import pytest

from concordance import audit
from concordance.config import EngineConfig

C = EngineConfig()

BOILING = ("Water boils at 90 degrees Celsius at sea level, and the kinetic energy of a 2 kg object "
           "moving at 3 m/s is 12 joules.")


def test_the_boiling_point_sentence_is_not_reported_as_fully_checked():
    r = audit.audit(BOILING, C, seal=False)
    assert r["verdict"] == "BROKEN"                       # the KE clause is wrong (9 J)
    cov = r["coverage"]
    assert cov["complete"] is False
    assert any("90 degrees" in u for u in cov["unchecked_text"])
    assert all("Water boils" not in q for q in cov["checked"])   # the span is the clause, not the sentence


@pytest.mark.parametrize("text, unchecked_hint", [
    ("The moon is made of cheese, and 12 + 7 = 19.", "cheese"),
    ("Paris is the capital of Spain; the force on a 10 kg mass accelerating at 3 m/s^2 is 30 N.", "Paris"),
    ("Sales rose 40% last quarter, and 25% of 200 is 50.", "Sales rose 40%"),
    ("The CEO is 52 years old, and the kinetic energy of a 4 kg object at 2 m/s is 8 J.", "52 years"),
    ("Our office has 14 rooms, and 3 times 7 is 21.", "14 rooms"),
    ("The bridge was built in 1932 and a circuit with 12 volts across 4 ohms draws 3 amps.", "1932"),
    ("Gold melts at 500 K, while 2 ^ 10 = 1024.", "500 K"),
    ("Revenue was 3 million dollars; 15% of 80 is 12.", "3 million"),
    ("Mars has 9 moons, and the kinetic energy of a 1 kg mass at 10 m/s is 50 J.", "9 moons"),
    ("He ran 26 miles, so 6 x 7 = 42.", "26 miles"),
])
def test_compound_sentences_name_the_unchecked_clause(text, unchecked_hint):
    r = audit.audit(text, C, seal=False)
    assert r["claims_found"] >= 1, r
    cov = r["coverage"]
    assert cov["complete"] is False, (text, cov)
    assert any(unchecked_hint in u for u in cov["unchecked_text"]), (text, cov)
    assert r["verdict"] in ("PARTIAL", "BROKEN"), r["verdict"]


def test_a_single_clause_claim_is_still_complete():
    r = audit.audit("the kinetic energy of a 2 kg mass at 3 m/s is 9 J", C, seal=False)
    assert r["verdict"] == "HOLDS" and r["coverage"]["complete"] is True


def test_two_claims_in_one_sentence_are_both_checked():
    t = "A circuit with 12 volts across 4 ohms draws 3 amps, and the kinetic energy of a 2 kg mass at 3 m/s is 9 J."
    r = audit.audit(t, C, seal=False)
    doms = sorted(x["domain"] for x in r["results"])
    assert doms == ["electrical", "physics"], r
    assert r["verdict"] == "HOLDS" and r["coverage"]["complete"] is True, r["coverage"]
