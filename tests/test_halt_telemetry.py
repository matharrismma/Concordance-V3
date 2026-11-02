"""Measurement 1: how the derivation closure halts (run 2026-11-02-halt-and-order, step halt-telemetry).

tools/halt_telemetry.py runs the 1,796 benchmark cases and every tier row (tests/fixtures/derivation_tier.py)
once each, and reports the count of derivations by halt.passes, the count whose halt.reason is "cap" (the cap
FIRES only then: passes equal to the cap is the normal single-step case), and every INCOMPLETE and SYSTEM_ERROR by
cause from a fixed list. It exits nonzero if the cap fires even once. These tests run it over the tier and require
zero firings; pin that gate with an injected smaller cap; and run it as a subprocess with the stores pointed at a
scratch copy, which must come back byte-identical. The benchmark-wide run is the tool's own output, recorded by
hand: in the suite it would cost the 60 s budget. The one row from a slow source (the 1,500-step chain) is measured
by the slow-marked test, as the tier requires.

The tool is imported inside each test, never at module level, so with it absent each test reads red.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "halt_telemetry.py"


def _tool():
    spec = importlib.util.spec_from_file_location("halt_telemetry", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _report(tool, tmp_path, *argv):
    out = tmp_path / "report.json"
    rc = tool.main([*argv, "--json", str(out)])
    return rc, json.loads(out.read_text(encoding="utf-8"))


def test_the_cap_never_fires_over_the_tier(tmp_path):
    """Every tier row from a fast source, once: zero cap firings, every row measured, and every INCOMPLETE and
    SYSTEM_ERROR explained by a cause on the fixed list."""
    tool = _tool()
    rc, rep = _report(tool, tmp_path, "--only", "tier", "--tier-rows", "fast")
    tier = rep["tier"]
    assert rc == 0 and tier["cap_fired"] == 0 and tier["cap_fired_at"] == [], tier
    assert tier["derivations"] == 62 and sum(tier["passes"].values()) == 62
    assert set(tier["reasons"]) == {"settled"}
    for kind in ("INCOMPLETE", "SYSTEM_ERROR"):
        assert tier["by_cause"][kind]["derivations"] == tier["verdicts"].get(kind, 0)
        assert tier["by_cause"][kind]["none of these"] == 0, (kind, tier["by_cause"][kind])
        assert set(tier["by_cause"][kind]) == set(tool.CAUSES) | {"derivations", "none of these"}
    assert tier["by_cause"]["INCOMPLETE"]["derivations"] > 0 and tier["by_cause"]["SYSTEM_ERROR"]["derivations"] > 0
    assert "benchmark" not in rep


def _named_check(rep, verify):
    """Every INCOMPLETE and SYSTEM_ERROR the report names has that verdict and those causes when run again on
    its own, the named ones are all of them, and the counts by cause are their tallies."""
    import collections
    tool = _tool()
    for kind in ("INCOMPLETE", "SYSTEM_ERROR"):
        each, row = rep["each"][kind], rep["by_cause"][kind]
        assert len(each) == len({e["name"] for e in each}) == row["derivations"] == rep["verdicts"].get(kind, 0)
        tally = collections.Counter(c for e in each for c in e["causes"])
        assert all(row[c] == tally[c] for c in tool.CAUSES)
        assert row["none of these"] == sum(1 for e in each if not e["causes"])
        for e in each:
            r = verify(e["name"])
            assert r["verdict"] == kind and tool.causes(r) == e["causes"], (kind, e, r["verdict"])


def test_each_incomplete_and_system_error_of_the_tier_is_named_with_its_causes(tmp_path, monkeypatch):
    tool = _tool()
    from concordance import derivation as D
    monkeypatch.setenv("CONCORDANCE_DATA_DIR", str(ROOT / "data"))
    rc, rep = _report(tool, tmp_path, "--only", "tier", "--tier-rows", "fast")
    steps = {r["name"]: r["steps"] for r in tool.tier_rows("fast")}
    _named_check(rep["tier"], lambda name: D.verify_derivation(json.loads(json.dumps(steps[name]))))
    assert {e["name"] for e in rep["tier"]["each"]["SYSTEM_ERROR"]} == {
        "ORDER_FREE['erroring dependency']", "SORTED['mixed error and missing']"}


@pytest.mark.slow
def test_each_incomplete_and_system_error_of_the_benchmark_is_named_with_its_causes(tmp_path):
    """The benchmark-wide run (about 10 s, so behind -m slow): every case it names is run again on its own."""
    tool = _tool()
    rc, rep = _report(tool, tmp_path, "--only", "benchmark")
    assert rc == 0 and rep["benchmark"]["derivations"] == rep["benchmark"]["of"] == 1796
    cases = {n: f for n, _, f in tool.benchmark_cases()}
    with tool.isolated():
        _named_check(rep["benchmark"], lambda name: cases[name]())


def test_a_requested_set_that_measures_nothing_exits_2(tmp_path, monkeypatch):
    tool = _tool()
    monkeypatch.setattr(tool, "tier_rows", lambda which="all": [])
    assert tool.main(["--only", "tier"]) == 2


def test_a_step_the_cap_stopped_before_its_check_counts_no_verifier_status():
    """The engine's detail for a step the pass cap stopped before its check ran begins with the tool's NOT_RUN,
    so such a step counts only as cut off by the cap, never as a NOT_APPLICABLE verifier status."""
    tool = _tool()
    from concordance import derivation as D
    steps = {r["name"]: r["steps"] for r in tool.tier_rows("fast")}["TWO_STEP"]
    original = D._pass_cap
    D._pass_cap = lambda k: 0
    try:
        r = D.verify_derivation(json.loads(json.dumps(steps)))
    finally:
        D._pass_cap = original
    assert r["halt"]["reason"] == "cap" and r["verdict"] == "INCOMPLETE"
    assert all(t["unsettled"] == "cap" and t["status"] == "NOT_APPLICABLE"
               and t["detail"].startswith(tool.NOT_RUN) for t in r["trail"])
    assert tool.causes(r) == ["unsettled: cap"]


@pytest.mark.slow
def test_the_cap_never_fires_over_the_tier_rows_from_slow_sources(tmp_path):
    tool = _tool()
    rc, rep = _report(tool, tmp_path, "--only", "tier", "--tier-rows", "slow")
    tier = rep["tier"]
    assert rc == 0 and tier["cap_fired"] == 0 and tier["derivations"] == 1
    assert tier["passes"] == {"1501": 1} and tier["above_two_passes"]["rows"] == ["chain_of(1500), listed in reverse"]


def test_an_injected_smaller_cap_fires_the_gate(tmp_path, monkeypatch):
    """With a cap of k passes for k steps (one short of the closure's k + 1), the cap fires on exactly the rows
    whose closure needs all k + 1 passes, and the tool exits nonzero; with it firing on one row only, it still does."""
    tool = _tool()
    from concordance import derivation as D
    rc, real = _report(tool, tmp_path, "--only", "tier", "--tier-rows", "fast")
    assert rc == 0
    steps = {r["name"]: len(r["steps"]) for r in tool.tier_rows("fast")}
    passes = real["tier"]["passes_by_row"]
    need_all = sorted(n for n in steps if passes[n] == steps[n] + 1)
    assert need_all and len(need_all) < len(steps)
    monkeypatch.setattr(D, "_pass_cap", lambda k: k)
    rc, capped = _report(tool, tmp_path, "--only", "tier", "--tier-rows", "fast")
    assert rc == 1 and capped["tier"]["cap_fired"] == len(need_all)
    assert sorted(capped["tier"]["cap_fired_at"]) == need_all
    assert capped["tier"]["reasons"]["cap"] == len(need_all)
    # even once: only the 6-step rows lose their last pass, and only the reverse-listed chain needed it
    monkeypatch.setattr(D, "_pass_cap", lambda k: k if k == 6 else k + 1)
    rc, once = _report(tool, tmp_path, "--only", "tier", "--tier-rows", "fast")
    assert rc == 1 and once["tier"]["cap_fired_at"] == ["chain_of(6), listed in reverse"]


def test_a_verifier_timeout_is_re_measured_once_never_until_it_passes():
    """A derivation in which a verifier timed out or was busy is measured exactly once more, and that second
    measurement stands, timed out or not; one that did not time out is measured once."""
    tool = _tool()

    def result(detail, verdict):
        return {"verdict": verdict, "halt": {"passes": 2, "reason": "settled", "cap": 2},
                "trail": [{"id": "s", "status": "ERROR" if detail else "CONFIRMED", "detail": detail}]}

    calls = {"always": 0, "once": 0, "never": 0}

    def run(name, details):
        def f():
            calls[name] += 1
            d = details[min(calls[name], len(details)) - 1]
            return result(d, "SYSTEM_ERROR" if d else "HOLDS")
        return f

    timed = "verification timed out (> 8.0s)"
    results, again = tool.measure([("always", run("always", [timed])),
                                   ("once", run("once", ["verifier busy (too many concurrent verifications)", ""])),
                                   ("never", run("never", [""]))])
    assert calls == {"always": 2, "once": 2, "never": 1}
    assert [(n, r["verdict"]) for n, r in results] == [("always", "SYSTEM_ERROR"), ("once", "HOLDS"), ("never", "HOLDS")]
    assert again == [{"name": "always", "first": "SYSTEM_ERROR", "second": "SYSTEM_ERROR", "still_timed_out": True},
                     {"name": "once", "first": "SYSTEM_ERROR", "second": "HOLDS", "still_timed_out": False}]
    rep = tool.summarize(results)
    assert rep["by_cause"]["SYSTEM_ERROR"]["status: ERROR, timed out or busy"] == 1
    assert rep["by_cause"]["SYSTEM_ERROR"]["status: ERROR"] == 0


def _tree(path):
    """Every entry under path, directories included, with each file's bytes hashed."""
    out = {}
    for p in sorted(Path(path).rglob("*")):
        rel = p.relative_to(path).as_posix()
        out[rel] = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "dir"
    return out


def test_the_tool_writes_nothing_to_the_stores_it_is_pointed_at(tmp_path, monkeypatch):
    """Run the tool as a subprocess with the memo left on (CONCORDANCE_MEMO unset) and the data, CAS and ledger
    paths pointed at a scratch copy of the real data directory: the scratch copy and the repository's data/ come
    back byte-identical. The control shows the scratch stores are live: a plain verification under that same
    environment writes into them."""
    tool = _tool()
    scratch = tmp_path / "scratch"
    shutil.copytree(ROOT / "data", scratch / "data")
    for store in ("cas", "ledger"):
        (scratch / "data" / store).mkdir(exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("HARNESS_", "VACUITY_"))}
    env.pop("CONCORDANCE_MEMO", None)
    env.update(CONCORDANCE_DATA_DIR=str(scratch / "data"), CONCORDANCE_CAS_DIR=str(scratch / "data" / "cas"),
               CONCORDANCE_LEDGER_DIR=str(scratch / "data" / "ledger"))
    import concordance
    src = str(Path(concordance.__file__).resolve().parent.parent)
    env["PYTHONPATH"] = os.pathsep.join([src] + [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p])
    before, data_before = _tree(scratch), _tree(ROOT / "data")
    out = tmp_path / "report.json"
    p = subprocess.run([sys.executable, str(TOOL), "--tier-rows", "fast", "--benchmark-stride", "60",
                        "--json", str(out)], cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=300)
    assert p.returncode == 0, (p.stdout[-2000:], p.stderr[-2000:])
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["benchmark"]["derivations"] == 30 and rep["benchmark"]["of"] == 1796 and rep["tier"]["derivations"] == 62
    assert rep["benchmark"]["agrees_with_label"] == 30          # the reference data was there to read
    assert _tree(scratch) == before and _tree(ROOT / "data") == data_before
    # the control: the same stores, the memo on, no isolation -> the memo bucket is written
    from concordance import derivation as D
    for k in ("CONCORDANCE_DATA_DIR", "CONCORDANCE_CAS_DIR", "CONCORDANCE_LEDGER_DIR"):
        monkeypatch.setenv(k, env[k])
    monkeypatch.setenv("CONCORDANCE_MEMO", "1")
    D.verify_derivation([dict(s) for s in tool.tier_rows("fast")[0]["steps"]])
    assert _tree(scratch) != before
