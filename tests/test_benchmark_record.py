"""The saved benchmark record counts what a fresh benchmark run counts (run 2026-11-11-exact-integers, step fix-a2).

tools/benchmark.py --record writes data/benchmark_last.json: version, total, correct, false_positives,
false_negatives, bands (attempted, with_band, counterexamples_with_band, counterexamples), recorded_at and means.
capabilities reads it. A step that moves a count rewrites the record in that same step (the plan's UNCHANGED), so this
test reads the working copy of the record:

  * in the shape --record writes, each count must equal a fresh run's. In a gate's worktree the working copy is the
    step's record, and in CI the commit's;
  * in the shape tools/benchmark.py --json writes (benchmark_version, cases, totals, ...), it skips with that reason.
    Only deploy/install.sh writes that shape, and on the box it puts the last ship's file back before the suite runs
    (install.sh:37-40, 108, 118-120), so the box's install is not where a record is graded.

The harness's pin stage takes the step's code and record away together, so there base code meets base record and
this test reads green; it reads red with the step's code over the base's record (954 saved, 955 measured), which the
step's note shows. A test of the comparison itself shows both branches on given records.

The fresh run raises the verify window to 600 s for its own reads, so a read the suite's load slows is never shed and
the counts never move by load. The benchmark tool is loaded inside each test, never at module level.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

ROOT = Path(__file__).resolve().parent.parent
RECORD = ROOT / "data" / "benchmark_last.json"
BENCHMARK = ROOT / "tools" / "benchmark.py"
COUNTS = ("total", "correct", "false_positives", "false_negatives")
BANDS = ("attempted", "with_band", "counterexamples_with_band", "counterexamples")
JSON_SHAPE = ("the record is in the shape tools/benchmark.py --json writes, which only deploy/install.sh writes and "
              "puts back on the box before its suite: the box's install is not where the record is graded")


def shape(record: Dict[str, Any]) -> Optional[str]:
    """'record' for what --record writes, 'json' for what --json writes, else None."""
    if all(k in record for k in COUNTS + ("bands", "recorded_at")) and "totals" not in record:
        return "record"
    if all(k in record for k in ("benchmark_version", "cases", "totals")):
        return "json"
    return None


def differences(record: Dict[str, Any], fresh: Dict[str, Any]) -> List[str]:
    """Each count of a --record-shaped record that a fresh run does not measure, named with both values."""
    out = [f"{k}: saved {record.get(k)!r}, measured {fresh[k]!r}" for k in COUNTS if record.get(k) != fresh[k]]
    saved = record.get("bands") or {}
    out += [f"bands.{k}: saved {saved.get(k)!r}, measured {fresh['bands'][k]!r}" for k in BANDS
            if saved.get(k) != fresh["bands"][k]]
    return out


def judge(record: Dict[str, Any], fresh) -> List[str]:
    """What is wrong with the saved record against a fresh run (fresh() runs it, only for the --record shape);
    a --json-shaped record skips with JSON_SHAPE, and any other shape is wrong."""
    kind = shape(record)
    if kind == "json":
        pytest.skip(JSON_SHAPE)
    if kind is None:
        return [f"data/benchmark_last.json is in neither shape: keys {sorted(record)}"]
    return differences(record, fresh())


def _fresh_run(monkeypatch) -> Dict[str, Any]:
    spec = importlib.util.spec_from_file_location("benchmark_for_the_record_test", BENCHMARK)
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    monkeypatch.setenv("CONCORDANCE_DATA_DIR", str(ROOT / "data"))      # other tests move it, as test_benchmark says
    from concordance import derivation
    # A read the suite's load slows past the 8 s window is shed to ERROR, which would move the counts (WANT
    # in-suite-benchmark-load-flake); the record is a run with nothing shed, so this run sheds nothing either.
    monkeypatch.setattr(derivation, "_VERIFY_TIMEOUT_S", 600.0)
    n, correct, fp, fn, bands = tool.run(verbose=False, want_bands=True)
    return {"total": n, "correct": correct, "false_positives": fp, "false_negatives": fn, "bands": dict(bands)}


def test_the_saved_record_counts_what_a_fresh_benchmark_run_counts(monkeypatch):
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    wrong = judge(record, lambda: _fresh_run(monkeypatch))
    assert wrong == [], "data/benchmark_last.json does not count what tools/benchmark.py measures: " + "; ".join(wrong) \
        + " (rewrite it with tools/benchmark.py --record in the step that moved the count)"


FRESH = {"total": 1796, "correct": 1796, "false_positives": 0, "false_negatives": 0,
         "bands": {"attempted": 2949, "with_band": 1433, "counterexamples_with_band": 414, "counterexamples": 955}}
RECORDED = {"version": "2.2.0", "total": 1796, "correct": 1796, "false_positives": 0, "false_negatives": 0,
            "bands": {"attempted": 2949, "with_band": 1433, "counterexamples_with_band": 414, "counterexamples": 954},
            "recorded_at": "2026-10-28", "means": "tools/benchmark.py --record; capabilities.trust() turns these counts"}
AS_JSON = {"benchmark_version": "2.2.0", "reproduce": "PYTHONPATH=src python tools/benchmark.py --json", "cases": [],
           "false_positives": [], "false_negatives": [],
           "totals": {"cases": 1796, "false_positives": 0, "false_negatives": 0}, "bands": FRESH["bands"]}


def test_the_comparison_reads_each_shape_as_it_should():
    ran = []

    def fresh():
        ran.append(1)
        return FRESH
    assert judge(RECORDED, fresh) == ["bands.counterexamples: saved 954, measured 955"]
    assert judge(dict(RECORDED, bands=FRESH["bands"]), fresh) == []
    assert judge(dict(RECORDED, total=1795, false_positives=1), fresh) == [
        "total: saved 1795, measured 1796", "false_positives: saved 1, measured 0",
        "bands.counterexamples: saved 954, measured 955"]
    assert judge({"total": 1796}, fresh) == ["data/benchmark_last.json is in neither shape: keys ['total']"]
    assert len(ran) == 3                          # the run happens for a --record-shaped record only
    with pytest.raises(pytest.skip.Exception) as skipped:
        judge(AS_JSON, fresh)
    assert str(skipped.value) == JSON_SHAPE and len(ran) == 3
