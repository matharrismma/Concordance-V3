"""Value-binding in the derivation — composition 3b (2026-09-25).

A step may BUILD an input from another step's CONFIRMED output, wherever that step is listed:
bind = {"<spec path>": "<srcId>.<key>"} (key defaults to "actual"). The moat resolves it ONLY from a
confirmed source, once that source has settled, and substitutes into a
deep copy of the step's spec before verifying it. Fail-closed: if the source is broken or absent, the
binding is unresolved and the step is a GAP — never verified with a fabricated value, never a guessed
HOLDS, and never a MISMATCH manufactured from our own inability to resolve a reference.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
# the derivations live in the tier (tests/fixtures/derivation_tier.py), their one home
_FIXTURES = str(ROOT / "tests" / "fixtures")
if _FIXTURES not in sys.path:
    sys.path.insert(0, _FIXTURES)

from concordance.derivation import verify_derivation, _set_spec_path  # noqa: E402
from derivation_tier import BIND, BIND_FALSE_SOURCE, NO_BIND  # noqa: E402


def _step(sid, domain, spec, **extra):
    d = {"id": sid, "domain": domain, "spec": spec}
    d.update(extra)
    return d


def test_bind_builds_an_input_from_a_confirmed_output():
    # a1 confirms a 4x6 rectangle (area 24); a2's rect_length is BUILT from a1's output (24), so a
    # 24x1 rectangle has area 24 — the second step's input came from the first step's confirmed result.
    steps = copy.deepcopy(BIND)
    res = verify_derivation(steps)
    assert res["verdict"] == "HOLDS", res
    a2 = next(t for t in res["trail"] if t["id"] == "a2")
    assert a2["status"] == "CONFIRMED"
    assert "a1" in a2["uses"]              # a bind IS a dependency — the source joined `uses`
    assert not a2.get("unresolved_binding")


def test_bind_to_a_broken_source_does_not_fabricate():
    # a1 is WRONG (4x6 = 24, not 99) -> BROKEN, so it is not confirmed and exposes no output. a2 cannot
    # be built from an unconfirmed output, so it is a GAP — never verified with a guessed value.
    steps = copy.deepcopy(BIND_FALSE_SOURCE)
    res = verify_derivation(steps)
    a2 = next(t for t in res["trail"] if t["id"] == "a2")
    assert a2["status"] == "NOT_APPLICABLE" and a2.get("unresolved_binding")
    assert res["verdict"] == "BROKEN"      # the real falsehood at a1 governs


def test_bind_to_a_missing_source_is_a_gap_never_holds():
    steps = [_step("a2", "geometry", {"GEOM_VERIFY": {"rect_width": 1, "claimed_rect_area": 24}},
                   bind={"GEOM_VERIFY.rect_length": "nope.actual_area"})]
    res = verify_derivation(steps)
    assert res["verdict"] != "HOLDS"
    assert res["trail"][0].get("unresolved_binding")


def test_no_bind_is_unchanged():
    # a plain two-step derivation with no bind behaves exactly as before.
    steps = copy.deepcopy(NO_BIND)
    res = verify_derivation(steps)
    assert res["verdict"] == "HOLDS"
    assert all(not t.get("unresolved_binding") for t in res["trail"])


def test_set_spec_path_walks_into_wrappers():
    spec = {"GEOM_VERIFY": {"rect_width": 2}}
    _set_spec_path(spec, "GEOM_VERIFY.rect_length", 10)
    assert spec["GEOM_VERIFY"]["rect_length"] == 10
    _set_spec_path(spec, "top", 7)
    assert spec["top"] == 7


if __name__ == "__main__":
    import pytest
    raise SystemExit(int(pytest.main([__file__, "-q"])))
