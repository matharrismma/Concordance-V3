"""public_finance — goldens from the 2026-10-20 scribe prototype rounds (operator ground truth, truth.py)."""
import math
import pytest
from concordance.verifiers import public_finance as PF
from concordance.derivation import verify_derivation

PAR = 12_245_000


def _run(art):
    return PF.run({"PUBFIN_VERIFY": art})[0]


def test_amortization_with_interest_only_prefix_round2_truth():
    r = _run({"par": PAR, "annual_rate": 0.045, "term_months": 240, "interest_only_months": 24,
              "claimed_monthly_pi": 82815.95, "claimed_monthly_io": 45918.75, "claimed_total_interest": 6745294.80})
    assert r.status == "CONFIRMED", r.detail


def test_amortization_round1_truth_no_io():
    r = _run({"par": 12_000_000, "annual_rate": 0.045, "term_months": 240,
              "claimed_monthly_pi": 75917.93, "claimed_total_interest": 6220302.04})
    assert r.status == "CONFIRMED", r.detail


def test_amortization_catches_the_rounding_propagation_the_writers_made():
    # writer A carried 75,918.10 into ×240: total interest 6,220,344 — the engine must break it
    r = _run({"par": 12_000_000, "annual_rate": 0.045, "term_months": 240, "claimed_total_interest": 6220344.0})
    assert r.status == "MISMATCH"


def test_issuance_grossup():
    assert _run({"net_proceeds": 12_000_000, "issuance_cost_pct": 0.02, "round_up_to": 5000,
                 "claimed_par": 12_245_000}).status == "CONFIRMED"
    assert _run({"net_proceeds": 12_000_000, "issuance_cost_pct": 0.02, "round_up_to": 5000,
                 "claimed_par": 12_240_000}).status == "MISMATCH"       # multiplied by 1.02 instead


def test_ad_valorem():
    assert _run({"assessed_value": 18_000_000, "assessment_ratio": 0.40, "millage": 28.5,
                 "claimed_tax": 205_200}).status == "CONFIRMED"
    assert _run({"assessed_value": 18_000_000 + 8_100_000, "assessment_ratio": 0.40, "millage": 27.9,
                 "claimed_tax": 291_276}).status == "CONFIRMED"


def test_depreciated_value_floor():
    assert _run({"original_cost": 9_000_000, "decline_per_year": 0.10, "floor_pct": 0.20, "year": 3,
                 "claimed_value": 6_300_000}).status == "CONFIRMED"
    assert _run({"original_cost": 9_000_000, "decline_per_year": 0.10, "floor_pct": 0.20, "year": 9,
                 "claimed_value": 1_800_000}).status == "CONFIRMED"
    assert _run({"original_cost": 9_000_000, "decline_per_year": 0.10, "floor_pct": 0.20, "year": 9,
                 "claimed_value": 900_000}).status == "MISMATCH"       # ignored the floor


def _full_round2():
    ev = [max(9_000_000 * (1 - 0.1 * y), 1_800_000) for y in range(1, 11)]
    mill = [27.9] * 5 + [28.5] * 5
    return [(18_000_000 + ev[i]) * 0.40 * mill[i] / 1000 for i in range(10)]


def test_abatement_schedule_round2_truth():
    r = _run({"full_tax_by_year": _full_round2(), "abated_start": 1.0, "abated_step": 0.10, "abated_floor": 0.0,
              "abatement_years": 10, "discount_rate": 0.05,
              "claimed_total_abated": 1_447_740, "claimed_pilot_year": 6, "claimed_pilot_payment": 123_120,
              "claimed_npv_abated": 1_210_576.49})
    assert r.status == "CONFIRMED", r.detail


def test_abatement_schedule_round1_truth_15_years():
    full = [205_200.0] * 15
    # years 1-5 100%, then 90..10, year 15 = 0 -> encode as start 1.0 for 5 years is not a linear ladder;
    # express as the per-year share vector check through two calls: the ladder part is years 6..15
    r = _run({"full_tax_by_year": full[5:], "abated_start": 0.9, "abated_step": 0.10, "abated_floor": 0.0,
              "abatement_years": 10, "claimed_total_abated": 205_200 * 4.5})
    assert r.status == "CONFIRMED", r.detail


def test_npv_series_convention():
    r = _run({"series": [100, 100, 100], "series_discount_rate": 0.10, "claimed_pv": 248.69})
    assert r.status == "CONFIRMED"


def test_routes_through_the_derivation_with_a_packet():
    res = verify_derivation([{"id": "a", "domain": "public_finance", "spec": {"PUBFIN_VERIFY": {
        "par": PAR, "annual_rate": 0.045, "term_months": 240, "interest_only_months": 24, "claimed_monthly_pi": 82815.95}}}])
    assert res["verdict"] == "HOLDS", res


def test_schema_is_generated_for_the_new_domain():
    from concordance import schema
    s = schema.schema_for("public_finance")
    assert s["artifact_key"] == "PUBFIN_VERIFY" and "amortization" in s["checks"]
    assert "interest_only_months" in s["checks"]["amortization"]


def test_resolver_routes_bond_language():
    from concordance.domain_resolver import resolve_domain
    assert resolve_domain("the PILOT payment in year 6 on a revenue bond with 28.5 mills")["decision"] == "public_finance"
