"""The Monte-Carlo fuzz, pinned as a regression (tools/mc_fuzz.py).

A fixed seed over a modest number of draws, asserting the invariants the fuzz exists to protect:
no false certify, every seal re-verifies, nothing crashes, no garbage is sealed, and every verify
stays bounded in time — so the ~60 s ReDoS class of regression can never return silently. The tool
runs thousands; this pins the floor in the suite. Seals go to a throwaway data dir.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import mc_fuzz  # noqa: E402


def test_invariants_hold_under_fuzz(tmp_path):
    res = mc_fuzz.run(trials=80, seed=7, data_dir=str(tmp_path))
    assert res.false_certify == 0, "a false packet was certified HOLDS"
    assert res.seal_mismatch == 0, f"{res.seal_mismatch} seal(s) did not re-verify"
    assert res.crashes == 0, "a verify raised or returned a malformed result"
    assert res.sealed_garbage == 0, "adversarial text was sealed HOLDS"
    assert res.worst_time_s < mc_fuzz.TIME_BOUND_S, f"a verify took {res.worst_time_s:.1f}s"
    assert res.worst_mem_mb < mc_fuzz.MEM_BOUND_MB
    assert res.breaches == 0
    # the run must actually have exercised the engine, not no-opped
    assert res.seal_checked > 0 and sum(res.verdicts.values()) >= 70
