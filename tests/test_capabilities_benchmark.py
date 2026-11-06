"""/capabilities reads data/benchmark_last.json in both shapes tools/benchmark.py writes.

Two writers, one file. `benchmark.py --record` (1eba67a) writes the tracked data/benchmark_last.json:
version, total, and false_positives / false_negatives as counts. deploy/install.sh writes the same path
with `benchmark.py --json` (emit_json): benchmark_version, the counts under `totals`, and false_positives
as the LIST of cases. Read with the --record keys only, the --json file gave a live /capabilities
version null, cases null, false_positives [] and trust unavailable.

The --record shape is pinned by the tracked file itself: its COMMITTED bytes (git show HEAD:), read and
never rewritten. Not the working copy: install.sh:133 rewrites the working copy in the --json shape on
every install, so in the box's checkout it is not the tracked bytes, and the gate-hygiene ship's on-box
suite failed on exactly that. The --json shape is built through benchmark.emit_json on a small result set,
so a change to the emitter reaches this test; the benchmark is never re-run here (tests/test_benchmark.py
runs it).
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from concordance import capabilities as C

ROOT = Path(__file__).resolve().parents[1]
TRACKED = ROOT / "data" / "benchmark_last.json"   # the WORKING COPY: what capabilities reads; never the pin


def _benchmark_module():
    """tools/benchmark.py, imported for its writer (a grader: never edited, never copied)."""
    spec = importlib.util.spec_from_file_location("_capabilities_benchmark", ROOT / "tools" / "benchmark.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _row(case, holds, verdict):
    return {"case": case, "mode": "domain", "expected_holds": holds, "verdict": verdict,
            "correct": holds == (verdict == "HOLDS")}


def _emit_json_file(tmp_path, rows, false_pos, false_neg, banded):
    """What `benchmark.py --json > data/benchmark_last.json` leaves on disk, for these results."""
    B = _benchmark_module()
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        B.emit_json(rows, false_pos, false_neg, banded)
    p = tmp_path / "benchmark_last.json"
    p.write_text(out.getvalue(), encoding="utf-8")
    return B, p


BANDED = {"attempted": 7, "with_band": 3, "counterexamples_with_band": 1, "counterexamples": 2}


def _committed_benchmark_last() -> dict:
    """data/benchmark_last.json as committed at HEAD. CI (actions/checkout), the harness's worktrees and the
    box's checkout (install.sh clones and pulls it) are all git checkouts, so this reads there; a git
    checkout where it cannot is a failure, not a skip. Only a tree with no .git at all (an export, a
    tarball) skips, saying why: there the committed bytes cannot be read, and the working copy is no
    stand-in for them."""
    if not (ROOT / ".git").exists():
        pytest.skip("not a git checkout (no .git at the repository root): the committed "
                    "data/benchmark_last.json cannot be read, and the working copy may have been rewritten")
    p = subprocess.run(["git", "-C", str(ROOT), "show", "HEAD:data/benchmark_last.json"],
                       capture_output=True, text=True, encoding="utf-8")
    assert p.returncode == 0, f"git show HEAD:data/benchmark_last.json failed in a git checkout: {p.stderr}"
    return json.loads(p.stdout)


def _pin_the_record_shape(tmp_path, monkeypatch):
    d = _committed_benchmark_last()
    assert "total" in d and "totals" not in d, "the tracked file is the --record shape"
    committed = tmp_path / "committed_benchmark_last.json"
    committed.write_text(json.dumps(d), encoding="utf-8")
    monkeypatch.setattr(C, "BENCHMARK_LAST", committed)
    b = C._benchmark()
    assert (b["version"], b["cases"], b["false_positives"], b["false_negatives"]) == \
        (d["version"], d["total"], d["false_positives"], d["false_negatives"])
    assert b["recorded_at"] == d["recorded_at"] and b["bands"] == d["bands"]
    assert "--record" in b["means"]
    t = C.trust()
    assert t["available"] is True and t["cases"] == d["total"] and t["false_positives"] == d["false_positives"]


def test_record_shape_is_read_from_the_tracked_file(tmp_path, monkeypatch):
    _pin_the_record_shape(tmp_path, monkeypatch)


def test_a_working_copy_rewritten_by_install_does_not_move_the_record_pin(tmp_path, monkeypatch):
    """The box: install.sh:133 has left the working copy of data/benchmark_last.json in the --json shape
    (here a file emit_json wrote stands in for it, through the paths, so the real data/ is never written).
    Capabilities reads it as the --json run it is, and the --record pin still holds, from the committed bytes."""
    _, rewritten = _emit_json_file(tmp_path, [_row("a truth held", True, "HOLDS")], [], [], BANDED)
    monkeypatch.setattr(sys.modules[__name__], "TRACKED", rewritten)    # the working copy, as the box has it
    monkeypatch.setattr(C, "BENCHMARK_LAST", rewritten)
    assert "--json" in C._benchmark()["means"]
    pin = tmp_path / "pin"
    pin.mkdir()
    _pin_the_record_shape(pin, monkeypatch)


def test_json_shape_is_read_from_a_file_emit_json_wrote(tmp_path, monkeypatch):
    rows = [_row("a truth held", True, "HOLDS"), _row("a falsehood caught", False, "BROKEN"),
            _row("a falsehood sealed", False, "HOLDS"),
            _row("a truth missed — µ Ł", True, "INCOMPLETE"), _row("another truth missed", True, "ERROR:x")]
    false_neg = [("a truth missed — µ Ł", "INCOMPLETE"), ("another truth missed", "ERROR:x")]
    # the file is UTF-8 (emit_json: ensure_ascii=False); Ł does not decode as cp1252
    B, p = _emit_json_file(tmp_path, rows, ["a falsehood sealed"], false_neg, BANDED)
    monkeypatch.setattr(C, "BENCHMARK_LAST", p)
    b = C._benchmark()
    assert b["version"] == B.BENCHMARK_VERSION
    assert (b["cases"], b["false_positives"], b["false_negatives"]) == (5, 1, 2)   # counts, never the lists
    assert b["bands"] == BANDED and b["recorded_at"] is None                       # --json records no date
    assert "--json" in b["means"] and "--record" not in b["means"]


def test_the_file_install_writes_makes_trust_available(tmp_path, monkeypatch):
    """install.sh:133 writes `benchmark.py --json`; from that file /capabilities reports a version and cases,
    trust is available, and a HOLDS carries it."""
    rows = [_row(f"case {i}", i % 2 == 0, "HOLDS" if i % 2 == 0 else "BROKEN") for i in range(10)]
    B, p = _emit_json_file(tmp_path, rows, [], [], BANDED)
    monkeypatch.setattr(C, "BENCHMARK_LAST", p)
    s = C.statement()
    assert s["benchmark"]["version"] == B.BENCHMARK_VERSION and s["benchmark"]["cases"] == 10
    t = s["trust"]
    assert t["available"] is True and t["cases"] == 10 and t["false_positives"] == 0
    assert t["benchmark_version"] == B.BENCHMARK_VERSION
    from concordance.derivation import verify_derivation
    g = json.loads((ROOT / "data" / "domain_goldens.json").read_text(encoding="utf-8"))["real_estate"]
    r = verify_derivation([{"id": "g", "domain": "real_estate", "spec": {g["packet_key"]: g["true"]}}])
    assert r["verdict"] == "HOLDS" and r["trust"] is not None and r["trust"]["cases"] == 10


@pytest.mark.parametrize("content", ['{"cases": 3}', "[1, 2]"])
def test_a_file_in_neither_shape_reports_no_run(tmp_path, monkeypatch, content):
    p = tmp_path / "benchmark_last.json"
    p.write_text(content, encoding="utf-8")
    monkeypatch.setattr(C, "BENCHMARK_LAST", p)
    b = C._benchmark()
    assert b["version"] is None and "neither shape" in b["means"]
    assert C.trust()["available"] is False
