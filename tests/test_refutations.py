"""The inverted contract: a check names the band every true claim must lie in; HOLDS is a survived refutation,
BROKEN a re-runnable counterexample; the manifest is sealed into the record and read by the page."""
from __future__ import annotations

from concordance import cas
from concordance.config import EngineConfig
from concordance.derivation import refutations, verify_derivation
from concordance.mcp import server as S
from concordance.verifiers.base import band, merge_checks

PKT = {"PUBFIN_VERIFY": {"par": 12_000_000, "annual_rate": 0.045, "term_months": 240,
                         "claimed_monthly_pi": 75917.93, "claimed_total_interest": 6220302.03}}


def test_band_inside_and_outside():
    ok = band("d.c", 100.0, 100.004, 0.01, "x")
    assert ok.status == "CONFIRMED" and ok.data["band"]["inside"] and "counterexample" not in ok.data
    bad = band("d.c", 100.0, 101.0, 0.01, "x")
    assert bad.status == "MISMATCH"
    cx = bad.data["counterexample"]
    assert cx["recomputed"] == 100.0 and cx["claimed"] == 101.0 and cx["band"] == [99.99, 100.01] and cx["off_by"] == 1.0


def test_merge_keeps_every_band_and_counterexample_governs():
    rs = [band("d.c", 1.0, 1.0, 0.1, "a"), band("d.c", 2.0, 5.0, 0.1, "b"), band("d.c", 3.0, 3.0, 0.1, "c")]
    m = merge_checks("d.c", rs, {"k": 1})
    assert m.status == "MISMATCH" and [b["what"] for b in m.data["bands"]] == ["a", "b", "c"]
    assert m.data["counterexample"]["what"] == "b" and m.data["k"] == 1
    ref = refutations([m])
    assert len(ref["bands"]) == 3 and ref["counterexamples"][0]["what"] == "b" and ref["attempted"] == ["d.c"]


def test_holds_reads_as_survived_not_true():
    r = verify_derivation([{"id": "m", "domain": "public_finance", "spec": PKT}])
    assert r["verdict"] == "HOLDS"
    assert r["read"].startswith("survived 1 attempted refutation") and "not shown true" in r["read"]
    assert r["refutations"] == {"attempted": 1, "survived": 1, "counterexamples": 0, "errored": 0, "not_applicable": 0}
    bands = r["trail"][0]["refutations"]["bands"]
    assert [b["what"] for b in bands] == ["monthly_pi", "total_interest"] and all(b["inside"] for b in bands)
    assert all(b["low"] < b["claimed"] < b["high"] for b in bands)


def test_broken_carries_a_rerunnable_counterexample_and_is_sealed(tmp_path, monkeypatch):
    monkeypatch.setenv("CONCORDANCE_DATA_DIR", str(tmp_path))
    pkt = {"PUBFIN_VERIFY": dict(PKT["PUBFIN_VERIFY"], claimed_monthly_pi=75000)}
    r = S._call_tool("verify", {"steps": [{"id": "m", "domain": "public_finance", "spec": pkt}]}, EngineConfig())
    assert r["verdict"] == "BROKEN" and "counterexample" in r["read"]
    cx = r["trail"][0]["refutations"]["counterexamples"][0]
    assert cx["claimed"] == 75000 and abs(cx["recomputed"] - 75917.925) < 0.01 and cx["band"][0] < cx["recomputed"] < cx["band"][1]
    rec = cas.fetch(r["seal"]["content_hash"])
    sealed = rec["verifier_results"][0]["data"]["refutations"]
    assert sealed["counterexamples"][0]["claimed"] == 75000
    assert rec["gate_results"][0]["details"]["read"] == r["read"]
    # re-run the counterexample from the sealed packet: same finding
    spec = cas.fetch_spec(rec["verifier_results"][0]["data"]["spec_hash"])
    again = verify_derivation([{"id": "m", "domain": "public_finance", "spec": spec}])
    assert again["verdict"] == "BROKEN"


def test_receipt_page_shows_the_band(tmp_path, monkeypatch):
    monkeypatch.setenv("CONCORDANCE_DATA_DIR", str(tmp_path))
    from concordance import http_api
    r = S._call_tool("verify", {"steps": [{"id": "m", "domain": "public_finance", "spec": PKT}]}, EngineConfig())
    h = r["seal"]["content_hash"]
    html = http_api._receipt_html(cas.fetch(h), h).decode()
    assert "must lie in" in html and "monthly_pi" in html and "survived" in html


def test_bound_is_a_one_sided_band():
    from concordance.verifiers.base import bound
    ok = bound("d.c", 1.31, 1.25, "min", "dscr")
    assert ok.status == "CONFIRMED" and ok.data["band"]["low"] == 1.25 and ok.data["band"]["high"] is None
    bad = bound("d.c", 0.83, 0.80, "max", "ltv")
    assert bad.status == "MISMATCH" and bad.data["counterexample"]["band"] == [None, 0.80]
    assert abs(bad.data["counterexample"]["off_by"] - 0.03) < 1e-9
    assert bound("d.c", 1.0, 1.0, "sideways").status == "ERROR"


def test_scribe_narrow_way_eliminates_and_brackets():
    from concordance.scribe import score_pass
    pk = {"pi": [{"id": "m", "domain": "public_finance", "spec": {"PUBFIN_VERIFY": {
        "par": 12_000_000, "annual_rate": 0.045, "term_months": 240, "claimed_monthly_pi": 0}}}]}
    drafts = [{"writer": "a", "claims": [{"id": "pi", "value": 75917.93}, {"id": "fee", "value": 120000}]},
              {"writer": "b", "claims": [{"id": "pi", "value": 75000}, {"id": "fee", "value": 118000}]},
              {"writer": "c", "claims": [{"id": "pi", "value": 75917.92}, {"id": "fee", "value": 125000}]}]
    r = score_pass(drafts, packets=pk, value_key="claimed_monthly_pi")
    nw = r["narrow_way"]
    assert nw["pi"]["state"] == "narrowed" and [e["writer"] for e in nw["pi"]["eliminated"]] == ["b"]
    assert nw["pi"]["bracket"] == {"min": 75917.92, "max": 75917.93, "from": "surviving"}
    assert nw["pi"]["band"][0] < 75917.92 and nw["pi"]["band"][1] > 75917.93
    assert nw["fee"]["state"] == "un-narrowed" and nw["fee"]["bracket"]["from"] == "stated, unverified"
    assert nw["fee"]["bracket"]["min"] == 118000 and nw["fee"]["bracket"]["max"] == 125000
    assert "ELIMINATED" in r["feedback"]["b"] and "outside [" in r["feedback"]["b"]
    assert r["read"].startswith("1 stated value eliminated by counterexample, 2 inside the band")


def test_scribe_run_is_staged_brackets_only_tighten():
    from concordance.scribe import run
    pk = {"pi": [{"id": "m", "domain": "public_finance", "spec": {"PUBFIN_VERIFY": {
        "par": 12_000_000, "annual_rate": 0.045, "term_months": 240, "claimed_monthly_pi": 0}}}]}

    class W:
        def __init__(self, name, seq):
            self.name, self.seq, self.i, self.seen = name, seq, 0, []

        def write(self, spec, feedback=None):
            self.seen.append(feedback)
            v = self.seq[min(self.i, len(self.seq) - 1)]
            self.i += 1
            return {"claims": [{"id": "pi", "value": v}]}

    a = W("a", [75917.93, 75917.93])
    b = W("b", [75000, 75917.92])          # eliminated in stage 1, corrects in stage 2
    reps = run([a, b], "spec", pk, passes=3, claim_ids=["pi"], value_key="claimed_monthly_pi")
    assert reps[0]["stages"]["pi"]["eliminated"] == [75000.0] and reps[0]["stages"]["pi"]["stage"] == 1
    assert "ELIMINATED" in b.seen[1] and "eliminated: 75,000" in b.seen[1] and "stay within" in b.seen[1]
    assert reps[1]["stages"]["pi"]["stage"] == 2 and reps[1]["stages"]["pi"]["eliminated"] == [75000.0]
    br0, br1 = reps[0]["stages"]["pi"]["bracket"], reps[1]["stages"]["pi"]["bracket"]
    assert br1["min"] >= br0["min"] and br1["max"] <= br0["max"]


def test_margin_and_trace_read_like_an_otdr(tmp_path, monkeypatch):
    monkeypatch.setenv("CONCORDANCE_DATA_DIR", str(tmp_path))
    par = {"id": "par", "domain": "public_finance", "spec": {"PUBFIN_VERIFY": {
        "net_proceeds": 12_000_000, "issuance_cost_pct": 0.02, "round_up_to": 5000, "claimed_par": 12_245_000}}}
    def debt(sid, claim):
        return {"id": sid, "domain": "public_finance", "bind": {"PUBFIN_VERIFY.par": "par.actual_par"},
                "spec": {"PUBFIN_VERIFY": {"par": 0, "annual_rate": 0.045, "term_months": 240,
                                           "interest_only_months": 24, "claimed_monthly_pi": claim}}}
    r = S._call_tool("verify", {"steps": [par, debt("tight", 82816.00), debt("bad", 82900)]}, EngineConfig())
    ev = {e["id"]: e for e in r["trace"]["events"]}
    assert ev["par"]["distance"] == 1 and ev["tight"]["distance"] == 2       # depth from `uses`
    assert ev["par"]["event"] == "pass" and ev["par"]["used"] == 0.0
    assert ev["tight"]["event"] == "pass" and 0.5 < ev["tight"]["used"] < 1   # inside, most of the cent spent
    assert ev["bad"]["event"] == "reflection" and ev["bad"]["used"] > 1 and ev["bad"]["off_by"] > 80
    b = r["trace"]["budget"]
    assert b["worst_step"] == "bad" and b["reflections"] == 1 and b["read"].startswith("chain fails at bad")
    # sealed: the budget is in the record and on the page
    rec = cas.fetch(r["seal"]["content_hash"])
    assert rec["gate_results"][0]["details"]["budget"]["worst_step"] == "bad"
    from concordance import http_api
    html = http_api._receipt_html(rec, r["seal"]["content_hash"]).decode()
    assert "Link budget: chain fails at bad" in html and "margin:" in html
    # a clean chain reports its tightest splice
    r2 = S._call_tool("verify", {"steps": [par, debt("ok", 82815.95)]}, EngineConfig())
    assert r2["trace"]["budget"]["read"].startswith("chain clears; tightest event ok")


def test_bound_reports_headroom():
    from concordance.verifiers.base import bound
    assert abs(bound("d", 1.60, 1.25, "min", "dscr").data["band"]["used"] - 1.25 / 1.60) < 1e-9   # 78% of the way to the floor
    assert abs(bound("d", 0.60, 0.80, "max", "ltv").data["band"]["used"] - 0.75) < 1e-9
    assert bound("d", 0.90, 0.80, "max", "ltv").data["band"]["used"] > 1


def test_trace_strata_and_connections_locate_the_fault():
    from concordance.derivation import verify_derivation
    steps = [{"id": "n", "domain": "mathematics", "spec": {"mode": "numeric", "params": {"numeric_expr": "12000000*0.02", "claimed_value": 240000}}},
             {"id": "par", "domain": "public_finance", "uses": ["n"], "spec": {"PUBFIN_VERIFY": {
                 "net_proceeds": 12_000_000, "issuance_cost_pct": 0.02, "round_up_to": 5000, "claimed_par": 12_245_000}}},
             {"id": "bad", "domain": "public_finance", "bind": {"PUBFIN_VERIFY.par": "par.actual_par"}, "spec": {"PUBFIN_VERIFY": {
                 "par": 0, "annual_rate": 0.045, "term_months": 240, "interest_only_months": 24, "claimed_monthly_pi": 82900}}}]
    r = verify_derivation(steps)
    ev = {e["id"]: e for e in r["trace"]["events"]}
    assert ev["n"]["stratum"] == "pure" and ev["n"]["used"] is not None          # pure steps carry a margin too
    assert ev["par"]["stratum"] == "applied" and ev["par"]["stands_on"] == ["n"]
    assert ev["bad"]["stands_on"] == ["par", "n"] and ev["bad"]["distance"] == 3   # transitive, down to the floor
    assert ev["bad"]["fault_locus"].startswith("data: every step it stands on passed")
    assert r["trace"]["strata"] == {"pure": 1, "applied": 2}
    assert all(e["spec_hash"] for e in r["trace"]["events"])                      # the floor under each event
