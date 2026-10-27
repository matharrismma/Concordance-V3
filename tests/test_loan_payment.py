"""The loan / mortgage monthly-payment recognizer (audit._x_loan_payment).

This is the claim the live site missed — "a 12,000 loan at 6% annual over 12 months is 1032.80 a
month" reached no verifier and fell back to weak cards. Now it routes to the real_estate monthly
amortization verifier (M = P·r(1+r)^n/((1+r)^n−1)) and comes back with a verdict. Four slots anchor
it (principal on a loan/mortgage, an annual rate %, a term, a monthly payment), so a wrong payment
breaks honestly and a non-claim fires nothing — recall grows, 0 false positives unchanged.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from concordance.audit import audit, extract  # noqa: E402
from concordance.config import EngineConfig  # noqa: E402

CFG = EngineConfig(skip_schema_validation=True)


def _names(text):
    return [s["extractor"] for s in extract(text)]


def test_the_flagship_loan_question_now_holds():
    t = "a 12,000 loan at 6% annual over 12 months is 1032.80 a month"   # true: 12000 @6%/yr, 12mo -> 1032.80
    assert "loan_payment" in _names(t)
    r = audit(t, CFG, seal=False)
    assert r["held"] == 1 and r["broken"] == 0, r["results"]


def test_mortgage_in_years_converts_to_months():
    t = "a $200,000 mortgage at 4.5% for 30 years is 1013.37 a month"    # 360 months
    assert "loan_payment" in _names(t)
    r = audit(t, CFG, seal=False)
    assert r["held"] == 1 and r["broken"] == 0, r["results"]


def test_a_wrong_payment_breaks():
    r = audit("a 12,000 loan at 6% annual over 12 months is 2000 a month", CFG, seal=False)  # 1032.80, not 2000
    assert r["broken"] == 1 and r["results"][0]["status"] == "MISMATCH"


def test_zero_false_positives_on_near_misses():
    for t in ["I took out a big loan at the bank",          # no numbers
              "a 6% mortgage sounds high",                   # no principal, term, or payment
              "the loan was for 12 months"]:                 # no rate or payment
        assert "loan_payment" not in _names(t), t


# ---- loan-to-value (LTV) — the core lending and DeFi-collateral ratio ----

def test_ltv_holds_both_keyword_positions_and_formats():
    for t in ["a 240,000 loan on a 300,000 property is 80% LTV",          # 80% LTV (after)
              "a $240,000 loan against a $300,000 home is an LTV of 80%",  # LTV of 80% (before)
              "a 240,000 loan on a 300,000 collateral is 0.8 loan-to-value"]:  # decimal, DeFi collateral
        assert "ltv" in _names(t), t
        r = audit(t, CFG, seal=False)
        assert r["held"] == 1 and r["broken"] == 0, (t, r["results"])


def test_ltv_wrong_ratio_breaks():
    r = audit("a 150,000 loan on a 300,000 property is 80% LTV", CFG, seal=False)  # 0.5, not 0.8
    assert r["broken"] == 1 and r["results"][0]["status"] == "MISMATCH"


def test_ltv_zero_false_positives():
    for t in ["a 240,000 loan on a 300,000 property",     # no LTV keyword / ratio
              "the LTV rules changed last year"]:          # no amounts
        assert "ltv" not in _names(t), t


# ---- debt-service coverage ratio (DSCR) — the lender's underwriting ratio ----

def test_dscr_holds_both_keyword_positions():
    for t in ["a property with 24,000 NOI and 22,755 in annual debt service has a DSCR of 1.055",
              "24,000 net operating income and 22,755 debt service is a 1.055 DSCR"]:
        assert "dscr" in _names(t), t
        r = audit(t, CFG, seal=False)
        assert r["held"] == 1 and r["broken"] == 0, (t, r["results"])


def test_dscr_wrong_ratio_breaks():
    r = audit("24,000 NOI and 22,755 in annual debt service is a DSCR of 2.0", CFG, seal=False)  # 1.055
    assert r["broken"] == 1 and r["results"][0]["status"] == "MISMATCH"


def test_dscr_zero_false_positives():
    for t in ["the DSCR was fine last quarter",   # no amounts
              "24,000 NOI looks healthy"]:          # no debt service, no DSCR
        assert "dscr" not in _names(t), t


# ---- balance-sheet identity (assets = liabilities + equity) = proof of reserves ----

def test_balance_sheet_holds_any_order_and_reserves():
    for t in ["assets of 1,000, liabilities of 600, and equity of 400",
              "with 1,000 in assets, 600 in liabilities, and 400 in equity, the books balance",
              "reserves of 1,000 against 600 in liabilities and 400 equity",   # proof of reserves
              "equity of 400, assets of 1,000, liabilities of 600"]:            # scrambled order
        assert "balance_sheet" in _names(t), t
        r = audit(t, CFG, seal=False)
        assert r["held"] == 1 and r["broken"] == 0, (t, r["results"])


def test_balance_sheet_that_does_not_balance_breaks():
    r = audit("assets of 1,000, liabilities of 600, and equity of 999", CFG, seal=False)  # 600+999 != 1000
    assert r["broken"] == 1 and r["results"][0]["status"] == "MISMATCH"


def test_balance_sheet_zero_false_positives_when_a_slot_is_missing():
    for t in ["the company has strong assets",                 # only one label
              "assets of 1000 and liabilities of 600"]:          # no equity
        assert "balance_sheet" not in _names(t), t
