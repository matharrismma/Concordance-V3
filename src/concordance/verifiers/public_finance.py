"""Public finance verifier — the arithmetic behind a development-authority bond and PILOT memo.

Deterministic recomputation of the numbers a board, bond counsel, or auditor signs under. Ported
from the 2026-10-20 scribe prototype (`packets.py`), where these were hand-written recompute
formulas the repo lacked. Checks arithmetic only — never whether an incentive is lawful, prudent,
or well-structured.

Checks:
  * public_finance.amortization          — level P&I over n months after an optional interest-only
                                           prefix; monthly P&I, IO payment, total interest
  * public_finance.issuance_grossup      — par from net proceeds, cost-of-issuance %, round-up increment
  * public_finance.ad_valorem            — tax = value × assessment_ratio × millage / 1000
  * public_finance.depreciated_value     — straight-line % of original cost per year with a floor
  * public_finance.abatement_schedule    — abated share per year (start, step, floor, years) applied to
                                           a per-year full-tax vector; totals, per-year PILOT, NPV
  * public_finance.npv                   — PV of a per-year series, end-of-year convention

PUBFIN_VERIFY packet shape (any subset):
    {
      "par": 12245000, "annual_rate": 0.045, "term_months": 240, "interest_only_months": 24,
      "claimed_monthly_pi": 82815.95, "claimed_monthly_io": 45918.75, "claimed_total_interest": 6745294.80,

      "net_proceeds": 12000000, "issuance_cost_pct": 0.02, "round_up_to": 5000, "claimed_par": 12245000,

      "assessed_value": 18000000, "assessment_ratio": 0.40, "millage": 28.5, "claimed_tax": 205200,

      "original_cost": 9000000, "decline_per_year": 0.10, "floor_pct": 0.20, "year": 3,
      "claimed_value": 6300000,

      "full_tax_by_year": [291276, ...], "abated_start": 1.0, "abated_step": 0.10, "abated_floor": 0.0,
      "abatement_years": 10, "discount_rate": 0.05,
      "claimed_total_abated": 1447740, "claimed_total_pilot": 2049e3, "claimed_pilot_year": 6,
      "claimed_pilot_payment": 123120, "claimed_npv_abated": 1210576.49,

      "series": [...], "series_discount_rate": 0.05, "claimed_pv": 1210576.49
    }
"""
from __future__ import annotations

import math
from typing import Any, Dict, List

from .base import VerifierResult, na, confirm, mismatch, error, clamp_tol
from .base import dispatch

_D = "public_finance"


def _num(spec, *keys):
    out = []
    for k in keys:
        v = spec.get(k)
        out.append(None if v is None else float(v))
    return out


def _check(name, actual, claimed, spec, what, data, tol_key="tolerance", rel=1e-6, abs_floor=0.01):
    """Money is stated to the cent. Default window: one cent, or one part per million of the value — enough to
    forgive display rounding of the FINAL figure, not enough to forgive a rounded intermediate carried into a
    multiplication (the error every writer made in the 2026-10-20 rounds: $42 on $6.2M). A caller may tighten."""
    tol = clamp_tol(spec, tol_key, max(abs_floor, abs(actual) * rel))
    data = dict(data, **{f"actual_{what}": actual, f"claimed_{what}": claimed})
    if abs(actual - claimed) <= tol:
        return confirm(name, f"{what} = {actual:,.2f} (matches claim)", data)
    return mismatch(name, f"{what} = {actual:,.2f}, claimed {claimed:,.2f} (off by {actual - claimed:+,.2f})", data)


# ── amortization ──────────────────────────────────────────────────────────────────────────────────
def verify_amortization(spec: Dict[str, Any]) -> VerifierResult:
    name = f"{_D}.amortization"
    try:
        par, ar, n, io = _num(spec, "par", "annual_rate", "term_months", "interest_only_months")
    except (TypeError, ValueError):
        return error(name, "par, annual_rate, term_months, interest_only_months must be numeric")
    if par is None or ar is None or n is None:
        return na(name)
    io = io or 0.0
    if par <= 0 or ar <= 0 or n <= 0 or io < 0 or io >= n:
        return error(name, "par, annual_rate, term_months must be positive and interest_only_months < term_months")
    r = ar / 12.0
    amort_n = n - io
    pi = par * r * (1 + r) ** amort_n / ((1 + r) ** amort_n - 1)
    io_pay = par * r
    total_interest = io * io_pay + amort_n * pi - par
    data = {"par": par, "annual_rate": ar, "monthly_rate": r, "term_months": n, "interest_only_months": io,
            "amortizing_months": amort_n, "monthly_pi": pi, "monthly_io": io_pay, "total_interest": total_interest,
            "formula": "PI = P r (1+r)^m / ((1+r)^m - 1), m = term - IO months; IO = P r; interest = IO·io + PI·m - P"}
    results = []
    for key, actual, what in (("claimed_monthly_pi", pi, "monthly_pi"), ("claimed_monthly_io", io_pay, "monthly_io"),
                              ("claimed_total_interest", total_interest, "total_interest")):
        if spec.get(key) is not None:
            try:
                results.append(_check(name, actual, float(spec[key]), spec, what, data))
            except (TypeError, ValueError):
                return error(name, f"{key} must be numeric")
    if not results:
        return na(name, "no claimed_monthly_pi / claimed_monthly_io / claimed_total_interest to check")
    bad = [r for r in results if r.status == "MISMATCH"]
    if bad:
        return bad[0]
    return confirm(name, "; ".join(r.detail for r in results), data)


# ── issuance gross-up ─────────────────────────────────────────────────────────────────────────────
def verify_issuance_grossup(spec: Dict[str, Any]) -> VerifierResult:
    name = f"{_D}.issuance_grossup"
    try:
        net, pct, step, claimed = _num(spec, "net_proceeds", "issuance_cost_pct", "round_up_to", "claimed_par")
    except (TypeError, ValueError):
        return error(name, "net_proceeds, issuance_cost_pct, round_up_to, claimed_par must be numeric")
    if net is None or pct is None or claimed is None:
        return na(name)
    if not (0 <= pct < 1) or net <= 0:
        return error(name, "issuance_cost_pct must be in [0,1) and net_proceeds positive")
    raw = net / (1 - pct)
    par = math.ceil(raw / step) * step if step and step > 0 else raw
    data = {"net_proceeds": net, "issuance_cost_pct": pct, "round_up_to": step, "raw_par": raw,
            "formula": "par = ceil((net / (1 - cost%)) / step) * step"}
    return _check(name, par, claimed, spec, "par", data, abs_floor=0.5)


# ── ad valorem ────────────────────────────────────────────────────────────────────────────────────
def verify_ad_valorem(spec: Dict[str, Any]) -> VerifierResult:
    name = f"{_D}.ad_valorem"
    try:
        value, ratio, mills, claimed = _num(spec, "assessed_value", "assessment_ratio", "millage", "claimed_tax")
    except (TypeError, ValueError):
        return error(name, "assessed_value, assessment_ratio, millage, claimed_tax must be numeric")
    if value is None or ratio is None or mills is None or claimed is None:
        return na(name)
    if value < 0 or not (0 < ratio <= 1) or mills < 0:
        return error(name, "assessment_ratio must be in (0,1]; value and millage non-negative")
    tax = value * ratio * mills / 1000.0
    data = {"assessed_value": value, "assessment_ratio": ratio, "millage": mills,
            "formula": "tax = fair market value × assessment ratio × millage / 1000"}
    return _check(name, tax, claimed, spec, "tax", data)


# ── depreciated value ─────────────────────────────────────────────────────────────────────────────
def depreciated(original: float, decline: float, floor_pct: float, year: int) -> float:
    return max(original * (1 - decline * year), original * floor_pct)


def verify_depreciated_value(spec: Dict[str, Any]) -> VerifierResult:
    name = f"{_D}.depreciated_value"
    try:
        orig, decline, floor_pct, year, claimed = _num(spec, "original_cost", "decline_per_year", "floor_pct", "year",
                                                       "claimed_value")
    except (TypeError, ValueError):
        return error(name, "original_cost, decline_per_year, floor_pct, year, claimed_value must be numeric")
    if orig is None or decline is None or year is None or claimed is None:
        return na(name)
    floor_pct = 0.0 if floor_pct is None else floor_pct
    if orig < 0 or not (0 <= decline <= 1) or not (0 <= floor_pct <= 1) or year < 0:
        return error(name, "decline_per_year and floor_pct in [0,1]; year and original_cost non-negative")
    v = depreciated(orig, decline, floor_pct, int(year))
    data = {"original_cost": orig, "decline_per_year": decline, "floor_pct": floor_pct, "year": int(year),
            "formula": "value_y = max(original × (1 − decline × y), original × floor)"}
    return _check(name, v, claimed, spec, "value", data)


# ── abatement schedule ────────────────────────────────────────────────────────────────────────────
def abated_shares(start: float, step: float, floor: float, years: int) -> List[float]:
    return [max(floor, start - step * i) for i in range(years)]


def verify_abatement_schedule(spec: Dict[str, Any]) -> VerifierResult:
    name = f"{_D}.abatement_schedule"
    full = spec.get("full_tax_by_year")
    try:
        start, step, floor, years, disc = _num(spec, "abated_start", "abated_step", "abated_floor", "abatement_years",
                                               "discount_rate")
    except (TypeError, ValueError):
        return error(name, "abatement parameters must be numeric")
    if full is None or start is None or step is None or years is None:
        return na(name)
    try:
        full = [float(x) for x in full]
    except (TypeError, ValueError):
        return error(name, "full_tax_by_year must be a list of numbers")
    years = int(years)
    floor = 0.0 if floor is None else floor
    if len(full) < years or years <= 0 or not (0 <= start <= 1) or not (0 <= floor <= start):
        return error(name, "need full_tax_by_year for every abatement year; 0 ≤ floor ≤ start ≤ 1")
    shares = abated_shares(start, step, floor, years)
    abated = [full[i] * shares[i] for i in range(years)]
    pilot = [full[i] - abated[i] for i in range(years)]
    data = {"abated_share_by_year": shares, "abated_by_year": abated, "pilot_by_year": pilot,
            "total_abated": sum(abated), "total_pilot": sum(pilot),
            "formula": "share_y = max(floor, start − step·(y−1)); abated_y = full_y·share_y; pilot_y = full_y − abated_y"}
    results = []
    try:
        if spec.get("claimed_total_abated") is not None:
            results.append(_check(name, sum(abated), float(spec["claimed_total_abated"]), spec, "total_abated", data))
        if spec.get("claimed_total_pilot") is not None:
            results.append(_check(name, sum(pilot), float(spec["claimed_total_pilot"]), spec, "total_pilot", data))
        if spec.get("claimed_pilot_payment") is not None and spec.get("claimed_pilot_year") is not None:
            y = int(spec["claimed_pilot_year"])
            if not (1 <= y <= years):
                return error(name, f"claimed_pilot_year must be in 1..{years}")
            results.append(_check(name, pilot[y - 1], float(spec["claimed_pilot_payment"]), spec, f"pilot_year_{y}", data))
        if spec.get("claimed_npv_abated") is not None:
            if disc is None:
                return error(name, "claimed_npv_abated needs discount_rate")
            npv = sum(a / (1 + disc) ** (i + 1) for i, a in enumerate(abated))
            data["npv_convention"] = "end of year; year 1 discounted one period"
            results.append(_check(name, npv, float(spec["claimed_npv_abated"]), spec, "npv_abated", data))
    except (TypeError, ValueError):
        return error(name, "claimed_* fields must be numeric")
    if not results:
        return na(name, "no claimed_total_abated / claimed_total_pilot / claimed_pilot_payment / claimed_npv_abated")
    bad = [r for r in results if r.status == "MISMATCH"]
    if bad:
        return bad[0]
    return confirm(name, "; ".join(r.detail for r in results), data)


# ── pv of a series ────────────────────────────────────────────────────────────────────────────────
def verify_npv(spec: Dict[str, Any]) -> VerifierResult:
    name = f"{_D}.npv"
    series = spec.get("series")
    try:
        disc, claimed = _num(spec, "series_discount_rate", "claimed_pv")
    except (TypeError, ValueError):
        return error(name, "series_discount_rate and claimed_pv must be numeric")
    if series is None or disc is None or claimed is None:
        return na(name)
    try:
        xs = [float(x) for x in series]
    except (TypeError, ValueError):
        return error(name, "series must be a list of numbers")
    if disc <= -1:
        return error(name, "series_discount_rate must be > -1")
    pv = sum(x / (1 + disc) ** (i + 1) for i, x in enumerate(xs))
    data = {"n": len(xs), "series_discount_rate": disc, "convention": "end of year; first value discounted one period",
            "formula": "PV = Σ x_t / (1+r)^t, t = 1..n"}
    return _check(name, pv, claimed, spec, "pv", data)


_RULES = [
    (lambda a: "par" in a and "annual_rate" in a and "term_months" in a, verify_amortization),
    (lambda a: "net_proceeds" in a and "issuance_cost_pct" in a and "claimed_par" in a, verify_issuance_grossup),
    (lambda a: "assessed_value" in a and "millage" in a and "claimed_tax" in a, verify_ad_valorem),
    (lambda a: "original_cost" in a and "decline_per_year" in a and "claimed_value" in a, verify_depreciated_value),
    (lambda a: "full_tax_by_year" in a and "abated_start" in a, verify_abatement_schedule),
    (lambda a: "series" in a and "claimed_pv" in a, verify_npv),
]


def run(packet: Dict[str, Any]) -> List[VerifierResult]:
    return dispatch(packet, "PUBFIN_VERIFY", _RULES, domain=_D, none_reason="no PUBFIN_VERIFY artifacts present")
