"""compose — receipts that stand on receipts. Driven by the SYNTHETIC memo (invented company, invented
numbers): no real deal is used anywhere in this repository."""
import copy, json
from concordance import cas, compose, http_api
from concordance.config import EngineConfig
from concordance.mcp.server import _call_tool
from concordance.validate import canonical_json_bytes, sha256_bytes

C = EngineConfig()
PF = "PUBFIN_VERIFY"
DOC = {"title": "Synthetic bond memo", "steps": [
    {"id": "par", "domain": "public_finance", "label": "gross-up",
     "spec": {PF: {"net_proceeds": 12_000_000, "issuance_cost_pct": 0.02, "round_up_to": 5000, "claimed_par": 12_245_000}}},
    {"id": "debt", "domain": "public_finance", "label": "P&I after IO",
     "spec": {PF: {"par": 0, "annual_rate": 0.045, "term_months": 240, "interest_only_months": 24,
                   "claimed_monthly_pi": 82815.95, "claimed_total_interest": 6745294.80}},
     "bind": {"PUBFIN_VERIFY.par": "par.actual_par"}},
    {"id": "dscr", "domain": "real_estate", "label": "coverage",
     "spec": {"RE_VERIFY": {"net_operating_income": 1_500_000, "annual_debt_service": 0, "claimed_dscr": 1.5093}},
     "bind": {"RE_VERIFY.annual_debt_service": "debt.annual_pi"}},
], "text": "Par {par}; P&I {debt}; DSCR {dscr}."}


def test_a_chained_document_seals_as_one_root_that_rehashes():
    r = compose.seal_document(DOC, C)
    assert r["verdict"] == "HOLDS" and r["root"]
    assert [s["uses"] for s in r["steps"]] == [[], ["par"], ["debt"]]
    rec = cas.fetch(r["root"]); h = rec.pop("content_hash")
    assert sha256_bytes(canonical_json_bytes(rec)) == h
    assert rec["kind"] == "document" and rec["derivation_seal"] == r["derivation_seal"]["content_hash"]
    assert rec["binds"]["debt"] == {"PUBFIN_VERIFY.par": "par.actual_par"}


def test_an_upstream_change_breaks_the_root_and_starves_what_rested_on_it():
    d = copy.deepcopy(DOC)
    d["steps"][0]["spec"][PF]["issuance_cost_pct"] = 0.03
    r = compose.seal_document(d, C, seal=False)
    assert r["verdict"] == "BROKEN"
    st = {s["id"]: s["status"] for s in r["steps"]}
    assert st == {"par": "MISMATCH", "debt": "NOT_APPLICABLE", "dscr": "NOT_APPLICABLE"}   # never a stale HOLDS


def test_a_document_can_stand_on_a_document_and_walk_back():
    v1 = compose.seal_document(DOC, C)
    v2 = compose.seal_document(dict(DOC, title="v2", parents=[v1["root"]]), C)
    assert v1["root"] != v2["root"]
    w = compose.walk(v2["root"])
    assert w["title"] == "v2" and w["parents"][0]["root"] == v1["root"] and w["parents"][0]["title"] == "Synthetic bond memo"


def test_an_unknown_parent_is_a_schema_error_not_a_dangling_pointer():
    r = compose.seal_document(dict(DOC, parents=["0" * 64]), C, seal=False)
    assert r["verdict"] == "SCHEMA_ERROR" and r["problems"][0]["field"] == "parents"


def test_verify_tool_takes_a_document_and_validates_its_packets():
    r = _call_tool("verify", {"document": DOC, "seal": False}, C)
    assert r["verdict"] == "HOLDS"
    bad = copy.deepcopy(DOC); bad["steps"][0]["spec"][PF]["net_proceds"] = bad["steps"][0]["spec"][PF].pop("net_proceeds")
    r = _call_tool("verify", {"document": bad, "seal": False}, C)
    assert r["verdict"] == "SCHEMA_ERROR" and r["problems"][0]["nearest"]["net_proceds"] == ["net_proceeds"]


def test_tree_page_renders_steps_binds_and_parents():
    v1 = compose.seal_document(DOC, C)
    v2 = compose.seal_document(dict(DOC, title="v2", parents=[v1["root"]]), C)
    rec = cas.fetch(v2["root"])
    html = http_api._document_html(rec, v2["root"]).decode()
    assert html.count('class="step"') == 3 and "rests on: par" in html and "rests on: debt" in html
    assert "par.actual_par" in html                       # binds travel to the page so re-check propagates
    assert f'/s/{v1["root"]}?html=1' in html              # the parent is a link
