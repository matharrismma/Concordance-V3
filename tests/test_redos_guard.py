"""The extraction ReDoS guard (audit._clamp_digits) — pins the fix directly.

A crafted long digit run ("the answer is " + "9"*5000) made several extractor patterns backtrack
for ~60 s on a single input, all returning no claim — a denial-of-service the per-verify timeout
could not shed, because the cost was in recognition. _clamp_digits collapses any run longer than
MAX_DIGITS to a non-numeric marker before the regexes run. This test is independent of the fuzz:
it proves recognition is bounded AND that clamping takes nothing real away.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from concordance import audit  # noqa: E402


def test_long_digit_run_extracts_fast_and_finds_nothing():
    pathological = "the answer is " + "9" * 5000
    t0 = time.perf_counter()
    steps = audit.extract(pathological)
    dt = time.perf_counter() - t0
    assert dt < 2.0, f"extraction took {dt:.1f}s — the ReDoS guard is not holding"
    assert steps == []           # an oversized number is not a checkable claim


def test_clamp_collapses_only_overlong_runs():
    assert "(large number)" in audit._clamp_digits("x " + "9" * (audit.MAX_DIGITS + 1) + " y")
    # a run at the cap is left alone — clamping must not touch real numbers
    keep = "value " + "9" * audit.MAX_DIGITS
    assert audit._clamp_digits(keep) == keep


def test_structured_hint_bounded_on_long_run():
    t0 = time.perf_counter()
    audit.structured_hint("the answer is " + "9" * 5000)
    assert time.perf_counter() - t0 < 2.0


def test_normal_claims_still_extract():
    # the guard removes only oversized runs; ordinary numeric claims are untouched
    assert len(audit.extract("7 factorial is 5040")) >= 1
    assert len(audit.extract("15% of 200 is 30")) >= 1
    assert len(audit.extract("a 2 kg object at 3 m/s has kinetic energy 9 J")) >= 1
