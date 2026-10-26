"""Mint the golden receipt fixture — a real, offline receipt the reference verifier must validate.

Writes tests/fixtures/receipt_golden.json: a sealed record plus its COSE_Sign1 attestation (no live log
entry, so the fixture needs no network to check). Regenerable — a fresh issuer key each run, whose PUBLIC
key is carried in the receipt; no private key is ever written. Re-run after any change to the envelope or
attestation shape (the conformance test, tests/test_receipt_conformance.py, pins it).

    PYTHONPATH=src python tools/mint_golden_receipt.py
"""
import json
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from concordance import cas, signing, transparency as T  # noqa: E402
from concordance.config import EngineConfig  # noqa: E402
from concordance.mcp import server as S  # noqa: E402

priv, _pub = signing.generate_keypair()
os.environ["CONCORDANCE_ISSUER_KEY"] = priv
pq_priv, _pq_pub = signing.pq_generate_keypair()         # the durable (ML-DSA / lattice) half
os.environ["CONCORDANCE_PQ_ISSUER_KEY"] = pq_priv
os.environ["CONCORDANCE_DATA_DIR"] = tempfile.mkdtemp(prefix="nh-golden-")

STEP = {"id": "m", "domain": "real_estate", "spec": {"RE_VERIFY": {
    "loan_principal": 12_000_000, "annual_rate": 0.045, "loan_term_months": 240,
    "claimed_monthly_payment": 75917.93}}}

r = S._call_tool("verify", {"steps": [STEP]}, EngineConfig())
assert r["verdict"] == "HOLDS", r["verdict"]
h = r["seal"]["content_hash"]
record = dict(cas.fetch(h))
record["content_hash"] = h
att = T.attest(h, publish_log=False)   # envelope (COSE/SCITT) + in_toto (DSSE), no live log entry
env = att.get("envelope")
assert env, "no issuer key configured — envelope() returned None"
pq = att.get("pq")
assert pq, "no PQ issuer key configured — pq_envelope() returned None"
receipt = {**record, "attest": {"envelope": env, "in_toto": att.get("in_toto"), "pq": pq}}   # offline golden, no log line

out = ROOT / "tests" / "fixtures" / "receipt_golden.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(receipt, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"wrote {out.relative_to(ROOT)}  (content_hash {h[:16]}…, spec {env.get('spec')}, kid {env.get('kid')}, "
      f"in_toto {'yes' if att.get('in_toto') else 'no'}, pq {pq.get('alg')} kid {pq.get('kid')})")
