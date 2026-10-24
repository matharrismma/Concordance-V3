"""The AgentLedger proof-of-behavior mapping (transparency.agentledger_pob).

RECEIPT_SPEC §2a named mapping the seal to AgentLedger PoB fields as the remaining interchange
work; this pins it. PoB is a signed, hash-chained, per-tool_call shape (payload_hash / result_hash
/ prev_hash). The mapping is a VIEW of the existing receipt — the signature is the record's own
COSE_Sign1, the chain is the engine's ledger — so this proves the fields line up, the chain links
two sealed receipts, and the reused signature still verifies under the issuer public key.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import json  # noqa: E402

from concordance import signing, transparency  # noqa: E402
from concordance.config import EngineConfig  # noqa: E402
from concordance.mcp import server as _server  # noqa: E402

_GOLDENS = Path(__file__).resolve().parent.parent / "data" / "domain_goldens.json"


def _steps(dom: str):
    g = json.loads(_GOLDENS.read_text(encoding="utf-8"))[dom]
    return [{"id": "g", "domain": dom, "spec": {g["packet_key"]: g["true"]}}]


@pytest.fixture()
def two_sealed_receipts(tmp_path, monkeypatch):
    priv, _pub = signing.generate_keypair()
    monkeypatch.setenv("CONCORDANCE_ISSUER_KEY", priv)
    monkeypatch.setenv("CONCORDANCE_DATA_DIR", str(tmp_path))
    cfg = EngineConfig()
    h1 = _server._call_tool("verify", {"steps": _steps("mathematics"), "seal": True}, cfg)["seal"]["content_hash"]
    h2 = _server._call_tool("verify", {"steps": _steps("acoustics"), "seal": True}, cfg)["seal"]["content_hash"]
    return h1, h2


def test_pob_fields_map_the_receipt(two_sealed_receipts):
    h1, _h2 = two_sealed_receipts
    pob = transparency.agentledger_pob(h1)
    assert pob["format"] == "agentledger-pob"
    assert pob["result_hash"] == h1            # the sealed verdict record is the result
    assert pob["payload_hash"]                 # the verified input's spec_hash
    assert pob["prev_hash"] == "GENESIS"       # first in the chain
    assert pob["chained"] is True
    assert pob["entry_type"] == "tool_call" and pob["tool"] == "concordance.verify"
    assert pob["verdict"] in ("PASS", "HOLDS")


def test_pob_prev_hash_chains_the_two_receipts(two_sealed_receipts):
    h1, h2 = two_sealed_receipts
    pob1, pob2 = transparency.agentledger_pob(h1), transparency.agentledger_pob(h2)
    assert pob2["result_hash"] == h2
    assert pob2["prev_hash"] == pob1["ledger_node"]   # the second receipt chains onto the first node
    assert pob2["prev_hash"] != "GENESIS"


def test_pob_signature_is_the_records_cose_and_verifies(two_sealed_receipts):
    _h1, h2 = two_sealed_receipts
    pob = transparency.agentledger_pob(h2)
    sig = pob["signature"]
    assert sig and sig["alg"] == "ed25519"
    v = transparency.verify_envelope(sig["cose_sign1_b64"], sig["public_key"])
    assert v["signature_ok"] is True
    assert v["payload_hash"] == h2            # the signature binds the result record
    assert v["hash_matches_header"] is True


def test_pob_none_for_unknown_hash(two_sealed_receipts):
    assert transparency.agentledger_pob("0" * 64) is None
