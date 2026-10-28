"""The smallest bucket: one exact packet under one verifier → one verdict, served on a hit, never recomputed."""
from __future__ import annotations

import json

from concordance import bucket, cas
from concordance.config import EngineConfig
from concordance.derivation import verify_derivation
from concordance.mcp import server as S

import pytest

STEP = {"id": "m", "domain": "public_finance", "spec": {"PUBFIN_VERIFY": {
    "par": 12_000_000, "annual_rate": 0.045, "term_months": 240, "claimed_monthly_pi": 75917.93}}}


@pytest.fixture(autouse=True)
def _memo_on(monkeypatch):
    monkeypatch.setenv("CONCORDANCE_MEMO", "1")


def test_hit_serves_the_same_verdict_and_says_so(tmp_path, monkeypatch):
    monkeypatch.setenv("CONCORDANCE_DATA_DIR", str(tmp_path))
    r1 = verify_derivation([STEP])
    r2 = verify_derivation([STEP])
    assert r1["trail"][0]["memo"]["hit"] is False and r1["trail"][0]["memo"]["stored"] is True
    assert r2["trail"][0]["memo"]["hit"] is True and r2["trail"][0]["memo"]["engine"]
    assert r1["verdict"] == r2["verdict"] and r1["trail"][0]["refutations"] == r2["trail"][0]["refutations"]
    assert r1["trace"]["events"][0]["bucket"] == "miss" and r2["trace"]["events"][0]["bucket"] == "hit"
    assert r2["trace"]["budget"]["bucket_hits"] == 1
    assert bucket.stats()["buckets"] == 1 and bucket.stats()["hits"] == 1


def test_key_binds_bytes_domain_engine_and_verifier_source(tmp_path, monkeypatch):
    monkeypatch.setenv("CONCORDANCE_DATA_DIR", str(tmp_path))
    k = bucket.key_for("public_finance", "a" * 64)
    assert k and k != bucket.key_for("real_estate", "a" * 64) and k != bucket.key_for("public_finance", "b" * 64)
    monkeypatch.setattr(bucket, "__version__", "9.9.9")
    assert bucket.key_for("public_finance", "a" * 64) != k            # a new engine is a new bucket
    monkeypatch.setattr(bucket, "__version__", bucket.__version__)
    monkeypatch.setitem(bucket._FINGERPRINTS, "public_finance", "deadbeefdeadbeef")
    assert bucket.key_for("public_finance", "a" * 64) != k            # changed verifier source is a new bucket


def test_errors_are_never_memoised(tmp_path, monkeypatch):
    monkeypatch.setenv("CONCORDANCE_DATA_DIR", str(tmp_path))
    bad = {"id": "m", "domain": "public_finance", "spec": {"PUBFIN_VERIFY": {"par": "x", "annual_rate": 0.045, "term_months": 240, "claimed_monthly_pi": 1}}}
    r = verify_derivation([bad])
    assert r["trail"][0]["status"] == "ERROR" and r["trail"][0]["memo"]["stored"] is False
    assert bucket.stats()["buckets"] == 0


def test_disabled_recomputes(tmp_path, monkeypatch):
    monkeypatch.setenv("CONCORDANCE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CONCORDANCE_MEMO", "0")
    verify_derivation([STEP])
    r = verify_derivation([STEP])
    assert r["trail"][0]["memo"] == {"hit": False, "key": None, "reason": "memo disabled"}


def test_sealed_record_and_page_name_the_bucket(tmp_path, monkeypatch):
    monkeypatch.setenv("CONCORDANCE_DATA_DIR", str(tmp_path))
    S._call_tool("verify", {"steps": [STEP]}, EngineConfig())
    r = S._call_tool("verify", {"steps": [STEP]}, EngineConfig())
    rec = cas.fetch(r["seal"]["content_hash"])
    assert rec["verifier_results"][0]["data"]["bucket"]["hit"] is True
    from concordance import http_api
    assert "Served from the bucket" in http_api._receipt_html(rec, r["seal"]["content_hash"]).decode()
    # the memo record itself is plain JSON a reader can open
    k = r["trail"][0]["memo"]["key"]
    m = json.loads((bucket._dir() / (k + ".json")).read_text())
    assert m["spec_hash"] == r["trail"][0]["spec_hash"] and m["status"] == "CONFIRMED"
