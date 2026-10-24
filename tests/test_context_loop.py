"""Strip → packets → verify → reapply: context never reaches the seal and always comes back to the user."""
from __future__ import annotations

from concordance import cas
from concordance.config import EngineConfig
from concordance.mcp import server as S

EMAIL = "jane@acme.com"
RE = {"RE_VERIFY": {"loan_principal": 12_000_000, "annual_rate": 0.045, "loan_term_months": 240,
                    "claimed_monthly_payment": 75917.93}}


def test_steps_strip_text_fields_seal_stripped_and_reveal(tmp_path, monkeypatch):
    monkeypatch.setenv("CONCORDANCE_DATA_DIR", str(tmp_path))
    r = S._call_tool("verify", {"steps": [{"id": "a", "claim": f"per {EMAIL}: 2+2=4", "domain": "mathematics",
                                           "spec": {"mode": "numeric", "params": {"numeric_expr": "2+2", "claimed_value": 4}}}]},
                     EngineConfig())
    assert r["verdict"] == "HOLDS"
    assert r["trail"][0]["claim"] == f"per {EMAIL}: 2+2=4"                 # back to the user
    assert r["context"]["held_placeholders"] == 1 and "trail[0].claim" in r["context"]["reapplied_at"]
    rec = cas.fetch(r["seal"]["content_hash"])
    assert EMAIL not in str(rec) and "[EMAIL_1]" in rec["verifier_results"][0]["data"]["claim"]  # never sealed


def test_document_title_text_labels_stripped_in_root(tmp_path, monkeypatch):
    monkeypatch.setenv("CONCORDANCE_DATA_DIR", str(tmp_path))
    doc = {"title": f"memo for {EMAIL}", "text": "call 10.0.0.7",
           "steps": [{"id": "p", "label": f"P&I ({EMAIL})", "domain": "real_estate", "spec": RE}]}
    r = S._call_tool("verify", {"document": doc}, EngineConfig())
    assert r["verdict"] == "HOLDS" and r["title"] == f"memo for {EMAIL}"
    assert r["context"]["held_placeholders"] == 2
    rec = cas.fetch(r["root"])
    assert EMAIL not in str(rec) and "10.0.0.7" not in str(cas.fetch_spec(rec["text_hash"]))
    assert rec["labels"]["p"] == "P&I ([EMAIL_1])"


def test_plain_claim_round_trips_and_names_what_travelled(tmp_path, monkeypatch):
    monkeypatch.setenv("CONCORDANCE_DATA_DIR", str(tmp_path))
    r = S._call_tool("verify", {"claim": f"Email {EMAIL}: 15% of 200 is 30."}, EngineConfig())
    ctx = r["context"]
    assert ctx["stripped"] and ctx["held_placeholders"] == 1 and "[EMAIL_1]" in ctx["travelled"]
    assert EMAIL not in ctx["travelled"]
    if r.get("seal"):
        assert EMAIL not in str(cas.fetch(r["seal"]["content_hash"]))


def test_nothing_personal_still_reports_the_loop(tmp_path, monkeypatch):
    monkeypatch.setenv("CONCORDANCE_DATA_DIR", str(tmp_path))
    r = S._call_tool("verify", {"steps": [{"id": "p", "domain": "real_estate", "spec": RE}]}, EngineConfig())
    assert r["context"] == {"stripped": True, "held_placeholders": 0, "reapplied_at": [],
                            "means": "free-text fields were scanned; nothing personal found; numbers are never stripped"}


def test_scribe_writers_see_skeleton_user_gets_drafts_back():
    from concordance.scribe import run
    seen = []

    class W:
        name = "w"

        def write(self, spec, feedback=None):
            seen.append(spec)
            return {"claims": [{"id": "pi", "value": 75917.93}], "text": f"re {spec}"}

    pk = {"pi": [{"id": "m", "domain": "public_finance", "spec": {"PUBFIN_VERIFY": {
        "par": 12_000_000, "annual_rate": 0.045, "term_months": 240, "claimed_monthly_pi": 0}}}]}
    reps = run([W()], f"size the bond for {EMAIL}", pk, passes=1, claim_ids=["pi"], value_key="claimed_monthly_pi")
    assert EMAIL not in seen[0] and "[EMAIL_1]" in seen[0]
    assert EMAIL in reps[0]["drafts_revealed"][0]["text"] and EMAIL not in reps[0]["drafts"][0]["text"]
    assert reps[0]["context"]["held_placeholders"] == 1


def test_discern_reports_what_travelled():
    from concordance.discern import discern
    d = discern(f"{EMAIL} says 15% of 200 is 30")
    assert d["context"]["held_placeholders"] == 1 and EMAIL not in d["context"]["travelled"]
