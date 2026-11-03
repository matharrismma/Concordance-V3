"""Seal one record no store holds yet, with no store variable set: the child of
tests/test_no_test_writes_the_stores.py, run alone in a subprocess (a single-file subset, so no other test
module has set CONCORDANCE_DATA_DIR at import). The memo is on, so the memo bucket is written too. It
reports where each store resolved to the file named by V3_FRESH_OUT; the parent judges that."""
from __future__ import annotations

import json
import os
from pathlib import Path

from concordance import bucket, cas, ledger
from concordance.config import EngineConfig
from concordance.mcp import server as S

ROOT = Path(__file__).resolve().parents[2]


def test_seal_a_fresh_record(monkeypatch):
    for var in ("CONCORDANCE_DATA_DIR", "CONCORDANCE_CAS_DIR", "CONCORDANCE_LEDGER_DIR"):
        assert var not in os.environ, f"{var} is set: this run would not exercise the bare fallback"
    monkeypatch.setenv("CONCORDANCE_MEMO", "1")
    g = json.loads((ROOT / "data" / "domain_goldens.json").read_text(encoding="utf-8"))["real_estate"]
    step = {"id": "fresh-" + os.environ["V3_FRESH_NONCE"], "domain": "real_estate",
            "spec": {g["packet_key"]: g["true"]}}
    r = S._call_tool("verify", {"steps": [step]}, EngineConfig())
    assert r["verdict"] == "HOLDS"
    h = r["seal"]["content_hash"]
    assert cas.fetch(h) is not None and ledger.precedent_for_record(h) is not None
    assert bucket.stats().get("buckets")
    Path(os.environ["V3_FRESH_OUT"]).write_text(json.dumps({
        "hash": h, "cas": str(cas._cas_dir().resolve()), "ledger": str(ledger._default_ledger_dir().resolve())}),
        encoding="utf-8")
