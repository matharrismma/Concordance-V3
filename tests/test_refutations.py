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
