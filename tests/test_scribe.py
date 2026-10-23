"""scribe — replays the two 2026-10-20 prototype rounds (every writer's recorded JSON) through the module.
The finding to reproduce: spread ≈ 0 on pass 1 (five writers agreed to 5–6 figures) yet the recompute broke
3 claims (round 1 — the prototype counted 2 under real_estate's 0.1% window; public_finance holds money to the
cent, so writer A's $75,918.10 monthly payment is also wrong, by 17 cents) and 1 claim (round 2); zero broken after pass 2; the center is a clean draft; a planted
wrong value is broken and never chosen."""
import copy, glob, json, os
import pytest

from concordance import scribe

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "scribe")
PF = "PUBFIN_VERIFY"


def _num(expr):
    return [{"id": "re", "domain": "mathematics", "spec": {"mode": "numeric", "params": {
        "numeric_expr": expr, "claimed_value": "<value>", "rel_tol": 1e-3}}}]


def _pf(art):
    return [{"id": "re", "domain": "public_finance", "spec": {PF: art}}]


# round 1 — plain memo: 12M par, 4.5%, 240 mo; 18M real property, 40%, 28.5 mills; 15-yr ladder
FULL1 = 18_000_000 * 0.40 * 28.5 / 1000
AB1 = [1.0] * 5 + [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1] + [0.0]
PACKETS1 = {
    "monthly_ds": _pf({"par": 12_000_000, "annual_rate": 0.045, "term_months": 240, "claimed_monthly_pi": "<value>"}),
    "annual_ds": _num("12*12000000*(0.045/12)*(1+0.045/12)^240/((1+0.045/12)^240-1)"),
    "total_interest": _pf({"par": 12_000_000, "annual_rate": 0.045, "term_months": 240, "claimed_total_interest": "<value>"}),
    "dscr": [{"id": "re", "domain": "real_estate", "spec": {"RE_VERIFY": {
        "net_operating_income": 1_500_000, "annual_debt_service": 911015.10, "claimed_dscr": "<value>"}}}],
    "ltv": [{"id": "re", "domain": "real_estate", "spec": {"RE_VERIFY": {
        "loan_amount": 12_000_000, "appraised_value": 27_000_000, "claimed_ltv": "<value>"}}}],
    "full_tax": _pf({"assessed_value": 18_000_000, "assessment_ratio": 0.40, "millage": 28.5, "claimed_tax": "<value>"}),
    "pilot_y7": _pf({"full_tax_by_year": [FULL1] * 15, "abated_start": 1.0, "abated_step": 0.0, "abatement_years": 15,
                     "claimed_pilot_year": 7, "claimed_pilot_payment": "<value>"}),
    "total_abated_15": _num(f"{FULL1}*{sum(AB1)}"),
    "total_pilot_15": _num(f"{FULL1}*(15-{sum(AB1)})"),
    "npv_abated": _pf({"series": [FULL1 * a for a in AB1], "series_discount_rate": 0.05, "claimed_pv": "<value>"}),
    "payroll": _num("150*52000"),
    "abated_per_job": _num(f"{FULL1}*{sum(AB1)}/150"),
}
# pilot_y7 under a non-linear ladder (5 flat years then steps) is not one abatement_schedule call; recompute directly
PACKETS1["pilot_y7"] = _num(f"{FULL1}*(1-{AB1[6]})")

# round 2 — IO period, gross-up, depreciating equipment, millage step
PAR2 = 12_245_000
EV = [max(9_000_000 * (1 - 0.1 * y), 1_800_000) for y in range(1, 11)]
MILL = [27.9] * 5 + [28.5] * 5
FULL2 = [(18_000_000 + EV[i]) * 0.40 * MILL[i] / 1000 for i in range(10)]
PACKETS2 = {
    "par": _pf({"net_proceeds": 12_000_000, "issuance_cost_pct": 0.02, "round_up_to": 5000, "claimed_par": "<value>"}),
    "monthly_io": _pf({"par": PAR2, "annual_rate": 0.045, "term_months": 240, "interest_only_months": 24, "claimed_monthly_io": "<value>"}),
    "monthly_pi": _pf({"par": PAR2, "annual_rate": 0.045, "term_months": 240, "interest_only_months": 24, "claimed_monthly_pi": "<value>"}),
    "total_interest": _pf({"par": PAR2, "annual_rate": 0.045, "term_months": 240, "interest_only_months": 24, "claimed_total_interest": "<value>"}),
    "dscr_amort": [{"id": "re", "domain": "real_estate", "spec": {"RE_VERIFY": {
        "net_operating_income": 1_500_000, "annual_debt_service": round(12 * 82815.9516, 2), "claimed_dscr": "<value>"}}}],
    "equip_val_y3": _pf({"original_cost": 9_000_000, "decline_per_year": 0.10, "floor_pct": 0.20, "year": 3, "claimed_value": "<value>"}),
    "full_tax_y1": _pf({"assessed_value": 18_000_000 + EV[0], "assessment_ratio": 0.40, "millage": 27.9, "claimed_tax": "<value>"}),
    "full_tax_y8": _pf({"assessed_value": 18_000_000 + EV[7], "assessment_ratio": 0.40, "millage": 28.5, "claimed_tax": "<value>"}),
    "pilot_y6": _pf({"full_tax_by_year": FULL2, "abated_start": 1.0, "abated_step": 0.10, "abatement_years": 10,
                     "claimed_pilot_year": 6, "claimed_pilot_payment": "<value>"}),
    "total_abated_10": _pf({"full_tax_by_year": FULL2, "abated_start": 1.0, "abated_step": 0.10, "abatement_years": 10,
                            "claimed_total_abated": "<value>"}),
    "npv_abated": _pf({"full_tax_by_year": FULL2, "abated_start": 1.0, "abated_step": 0.10, "abatement_years": 10,
                       "discount_rate": 0.05, "claimed_npv_abated": "<value>"}),
    "abated_per_job": _num(f"{sum(FULL2[i] * (1 - 0.1 * i) for i in range(10))}/150"),
}


def _load(round_dir, n):
    drafts = []
    for f in sorted(glob.glob(os.path.join(FIX, round_dir, f"pass{n}", "agent*.json"))):
        d = json.load(open(f))
        drafts.append({"writer": os.path.basename(f)[:-5], "draft": d.get("draft", ""), "claims": d["claims"]})
    return drafts


@pytest.mark.parametrize("round_dir, packets, expect_broken_p1", [("round1", PACKETS1, 3), ("round2", PACKETS2, 1)])
def test_replay_reproduces_the_recorded_finding(round_dir, packets, expect_broken_p1):
    p1 = scribe.score_pass(_load(round_dir, 1), packets)
    assert len(p1["writers"]) == 5
    assert p1["spectrum"]["spread"] < 1e-3, "five writers agreed to 5–6 figures"
    assert p1["broken_total"] == expect_broken_p1, p1["broken"]
    assert p1["center"] in p1["clean_writers"]
    assert p1["status"] == "OPEN"
    p2 = scribe.score_pass(_load(round_dir, 2), packets)
    assert p2["broken_total"] == 0
    assert p2["status"] == "CONVERGED", (p2["status"], p2["spectrum"]["spread"])


def test_a_planted_wrong_value_is_broken_and_never_the_center():
    drafts = _load("round2", 2)
    bad = copy.deepcopy(drafts[0])
    bad["writer"] = "planted"
    for c in bad["claims"]:
        if c["id"] == "pilot_y6":
            c["value"] = 123_120 * 1.10          # 10% high: consensus would barely notice; the engine must
    rep = scribe.score_pass(drafts + [bad], PACKETS2)
    assert "pilot_y6" in rep["broken"]["planted"]
    assert rep["center"] != "planted"
    assert rep["spectrum"]["top_axis"][0][0] == "pilot_y6"      # and the axis points straight at it


def test_flat_spectrum_is_underdetermined_not_averaged():
    # two writers, three claims, every claim disagrees by a different amount: no dominant axis
    drafts = [{"writer": "a", "claims": [{"id": "x", "value": 100}, {"id": "y", "value": 200}, {"id": "z", "value": 300}]},
              {"writer": "b", "claims": [{"id": "x", "value": 130}, {"id": "y", "value": 150}, {"id": "z", "value": 420}]},
              {"writer": "c", "claims": [{"id": "x", "value": 90}, {"id": "y", "value": 260}, {"id": "z", "value": 290}]}]
    rep = scribe.score_pass(drafts, {})
    assert rep["status"] in ("UNDERDETERMINED", "OPEN")
    assert rep["center"] is None or rep["center"] in rep["writers"]
    assert all(v["verdict"] == "NO_PACKET" for w in rep["verdicts"].values() for v in w.values())


def test_feedback_never_names_other_writers_or_truth():
    rep = scribe.score_pass(_load("round1", 1), PACKETS1)
    fb = rep["feedback"]["agentA"]
    assert "agentB" not in fb and "agentC" not in fb
    assert "MISMATCH" in fb and "Resolve every MISMATCH" in fb


def test_run_drives_stub_writers_to_convergence():
    class Stub:
        def __init__(self, name, vals):
            self.name, self.vals, self.calls = name, vals, 0

        def write(self, spec, feedback=None):
            self.calls += 1
            v = dict(self.vals)
            if feedback and "MISMATCH" in feedback:
                v["payroll"] = 7_800_000                  # it "reads the feedback" and fixes the one error
            return {"draft": "d", "claims": [{"id": k, "value": x} for k, x in v.items()]}
    ws = [Stub("good", {"payroll": 7_800_000}), Stub("bad", {"payroll": 7_000_000})]
    reports = scribe.run(ws, "spec", {"payroll": _num("150*52000")}, passes=3)
    assert reports[0]["broken"]["bad"] == ["payroll"] and reports[-1]["status"] == "CONVERGED"
    assert len(reports) == 2
