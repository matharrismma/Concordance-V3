"""P2 (2026-10-23): a misnamed packet field returns SCHEMA_ERROR naming the field and its nearest known
name — never a silent NOT_APPLICABLE. find_verifier returns the generated schema."""
from concordance import schema
from concordance.config import EngineConfig
from concordance.mcp.server import _call_tool

C = EngineConfig()


def test_misnamed_field_is_a_schema_error_with_the_fix():
    r = _call_tool("verify", {"steps": [{"id": "m", "domain": "real_estate", "spec": {"RE_VERIFY": {
        "principal": 12_000_000, "annual_rate": 0.045, "years": 20, "claimed_monthly_payment": 75917.93}}}]}, C)
    assert r["verdict"] == "SCHEMA_ERROR"
    p = r["problems"][0]
    assert p["step"] == "m" and "principal" in p["unknown"]
    assert p["nearest"]["principal"] == ["loan_principal"]
    assert r.get("seal") is None


def test_the_well_formed_packet_holds():
    r = _call_tool("verify", {"steps": [{"id": "m", "domain": "real_estate", "spec": {"RE_VERIFY": {
        "loan_principal": 12_000_000, "annual_rate": 0.045, "loan_term_months": 240,
        "claimed_monthly_payment": 75917.93}}}], "seal": False}, C)
    assert r["verdict"] == "HOLDS"


def test_missing_artifact_key_is_named():
    r = _call_tool("verify", {"steps": [{"id": "x", "domain": "medicine", "spec": {
        "weight_kg": 70, "dose_mg_per_kg": 5, "claimed_dose_mg": 350}}]}, C)
    assert r["verdict"] == "SCHEMA_ERROR" and r["problems"][0]["field"] == "MED_VERIFY"


def test_unknown_domain_is_named_with_nearest():
    r = _call_tool("verify", {"steps": [{"id": "x", "domain": "realestate", "spec": {"RE_VERIFY": {}}}]}, C)
    assert r["verdict"] == "SCHEMA_ERROR" and r["problems"][0]["field"] == "domain"
    assert "real_estate" in r["problems"][0]["nearest"]


def test_find_verifier_returns_the_schema():
    r = _call_tool("find_verifier", {"query": "monthly mortgage payment"}, C)
    assert r["domain"] == "real_estate"
    s = r["schemas"]["real_estate"]
    assert s["artifact_key"] == "RE_VERIFY" and "loan_principal" in s["packet"]["properties"]["RE_VERIFY"]["properties"]
    assert "monthly_mortgage" in s["checks"]


def test_every_registered_domain_has_a_schema():
    from concordance import verifiers as V
    V._load_plugins()
    for mod in sorted({v.rsplit(".", 1)[-1] for v in V.VERIFIERS.values()}):
        s = schema.schema_for(mod)
        assert "error" not in s, mod
        if mod != "mathematics":
            assert s["artifact_key"] and s["checks"], mod


def test_plain_claim_results_are_marked_extracted():
    r = _call_tool("verify", {"claim": "the force on a 10 kg mass accelerating at 3 m/s^2 is 30 N", "seal": False}, C)
    assert r["verdict"] == "HOLDS" and r["extracted"] is True
    assert r["coverage"]["complete"] is True
