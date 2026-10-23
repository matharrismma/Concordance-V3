"""The receipt page: the sealed packet is filed beside the seal under its spec_hash; the page shows the
inputs and re-checks without touching the record; `_spec` never leaves the engine."""
import json
from concordance import cas, http_api
from concordance.config import EngineConfig
from concordance.mcp.server import _call_tool

C = EngineConfig()
STEP = {"id": "m", "domain": "real_estate", "spec": {"RE_VERIFY": {
    "loan_principal": 12_000_000, "annual_rate": 0.045, "loan_term_months": 240, "claimed_monthly_payment": 75917.93}}}


def test_spec_sidecar_matches_the_trail_spec_hash_and_is_not_returned():
    r = _call_tool("verify", {"steps": [STEP]}, C)
    assert r["verdict"] == "HOLDS" and "_spec" not in json.dumps(r)
    sh = r["trail"][0]["spec_hash"]
    assert cas.fetch_spec(sh) == STEP["spec"]


def test_receipt_page_shows_inputs_and_recheck_form():
    r = _call_tool("verify", {"steps": [STEP]}, C)
    rec = _call_tool("seal_fetch", {"hash": r["seal"]["content_hash"]}, C)
    html = http_api._receipt_html(rec, r["seal"]["content_hash"]).decode()
    assert 'name="annual_rate" value="0.045"' in html and "Re-check" in html
    assert "/verify?seal=0" in html                      # re-checks never mint


def test_recheck_route_with_seal_off_returns_fresh_verdict_without_sealing():
    status, _, body = http_api.route("POST", "/verify", {"seal": ["0"]},
                                     {"steps": [{"id": "r", "domain": "real_estate", "spec": {"RE_VERIFY": {
                                         **STEP["spec"]["RE_VERIFY"], "annual_rate": 0.05}}}]}, {}, b"")
    j = json.loads(body)
    assert status == 200 and j["verdict"] == "BROKEN" and j.get("seal") is None
