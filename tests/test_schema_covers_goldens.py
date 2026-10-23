"""Every golden the benchmark runs must pass schema validation — otherwise a valid packet over HTTP gets
SCHEMA_ERROR (found live 2026-10-23: public_finance read claimed_* fields in a loop the analyzer missed)."""
import json, os
from concordance import schema

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _goldens():
    for line in open(os.path.join(ROOT, "data", "check_goldens.jsonl"), encoding="utf-8"):
        o = json.loads(line)
        yield o["check"], o["domain"], o["true"]
    g = json.load(open(os.path.join(ROOT, "data", "domain_goldens.json"), encoding="utf-8"))
    for dom, v in g.items():
        if v.get("packet_key") and isinstance(v.get("true"), dict):
            yield f"domain:{dom}", dom, {v["packet_key"]: v["true"]}


def test_every_golden_passes_schema_validation():
    bad = []
    for name, dom, spec in _goldens():
        if dom in ("mathematics", "math"):
            continue
        probs = schema.validate_steps([{"id": "g", "domain": dom, "spec": spec}])
        if probs:
            bad.append((name, probs[0].get("field"), probs[0].get("problem")))
    assert not bad, bad[:10]
