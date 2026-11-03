"""Measurement 4 of the TRM report, step audit-core (run 2026-11-03-restatement-audit): tools/restatement_audit.py,
the restatement-invariance audit of the verifiers and the closure.

These tests pin what the audit compares (the verdict, each step's status, the pointers read through R5's id map,
each step's refutation check names and bands, the read) and how a change is classed: a HOLDS/BROKEN flip, and a
verdict that became HOLDS on a case labelled false or a tier row whose source asserts a verdict other than HOLDS,
are the exit-1 kinds; a verdict that became HOLDS on a row no source asserts on comes first among the wants; a band
that moves is a named change. They hold the exits (1 on an exit-1 change, 2 when nothing was compared, else 0) on
runs whose responses are stubbed, so the rule is shown without a verifier; hold a timed-out run to one
re-measurement; hold the paths each restatement may take (R5 on tier rows only, a row audit.audit builds from text
only by R5, audit.audit's own text path declined); run the fast audit (the first benchmark case of every domain and
every fast tier row) so the harness gate sees every domain, and require its exit-1 set to equal KNOWN exactly, as
the benchmark-wide audit must behind -m slow; and run the tool as a subprocess with the stores pointed at a scratch
copy, which must come back byte-identical.

The tool is loaded inside each test, never at module level, so with it absent each test reads red.
"""
from __future__ import annotations

import copy
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
TOOL = ROOT / "tools" / "restatement_audit.py"


def _tool():
    spec = importlib.util.spec_from_file_location("restatement_audit", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── responses and cases of the tests' own, run through stubs (no verifier) ────────────────────────────────────
def _resp(verdict, status="CONFIRMED", names=("mathematics.equality",), read="read", broken_at=None, bands=(),
          detail=""):
    ref = {"attempted": list(names), "survived": list(names) if status == "CONFIRMED" else [],
           "counterexamples": [] if status == "CONFIRMED" else [{"check": n, "detail": "x"} for n in names],
           "errored": [], "not_applicable": [], "bands": list(bands), "margin": None}
    return {"verdict": verdict, "read": read, "broken_at": broken_at, "gap_at": None, "error_at": None,
            "trail": [{"id": "b", "status": status, "detail": detail, "refutations": ref}]}


SQUARES = {"mode": "equality", "params": {"expr_a": "(x-1)*(x+1)", "expr_b": "x**2-1", "variables": {}}}


def _swapped(subject):
    return subject[0]["spec"]["params"]["expr_a"] == "x**2-1"


def _case(run, label=True, population="benchmark", **kw):
    """One case the audit restates: the benchmark's difference of squares, run by `run` instead of a verifier."""
    c = {"population": population, "case": "stubbed", "label": label if population == "benchmark" else None,
         "domains": ["mathematics"], "path": "stub", "subject": [{"id": "b", "domain": "mathematics", "spec": SQUARES}],
         "passes": lambda s: s, "run": run}
    c.update(kw)
    return c


def _audit(tool, *cases):
    return tool.audit_cases(tool._telemetry(), tool._restate(), cases)


def _by_key(res):
    return {c["restatement"]: c for c in res["changes"]}


# ── what is compared, and how a change is classed ─────────────────────────────────────────────────────────────
def test_a_flip_under_one_restatement_is_an_exit_one_change():
    """The stub reads HOLDS until the sides are swapped: only R2 changes the verdict, and the change is a flip."""
    tool = _tool()
    res = _audit(tool, _case(lambda s: _resp("BROKEN" if _swapped(s) else "HOLDS")))
    assert list(_by_key(res)) == ["R2"]
    c = _by_key(res)["R2"]
    assert c["exit_one"] and c["kinds"][0] == "flip" and "verdict" in c["kinds"]
    assert {d["field"] for d in c["diffs"]} >= {"verdict"}
    assert res["applied"][("benchmark", "R1")] == res["applied"][("benchmark", "R2")] == 1
    rep = {"compared": 4, "exit_one": [list(tool._key(c))]}
    assert tool.exit_code(rep) == 1


@pytest.mark.parametrize("label, population, asserts, kinds, exit_one", [
    (False, "benchmark", None, ["false_to_holds", "verdict"], True),       # labelled false: a false positive
    (True, "benchmark", None, ["verdict"], False),                         # labelled true: toward the label, a want
    (None, "tier", True, ["false_to_holds", "verdict"], True),             # the source asserts not HOLDS
    (None, "tier", False, ["verdict"], False),                             # the source asserts HOLDS
    (None, "tier", None, ["into_holds_unasserted", "verdict"], False),     # no source asserts: first among wants
])
def test_a_verdict_that_becomes_holds_is_classed_by_its_label_or_assertion(label, population, asserts, kinds,
                                                                             exit_one):
    tool = _tool()
    case = _case(lambda s: _resp("HOLDS" if _swapped(s) else "INCOMPLETE", status="CONFIRMED" if _swapped(s)
                                 else "NOT_APPLICABLE"), label=label, population=population,
                 asserts_not_holds=asserts)
    c = _by_key(_audit(tool, case))["R2"]
    assert c["kinds"][:len(kinds)] == kinds and c["exit_one"] is exit_one


def test_check_names_bands_read_and_status_are_compared_and_bands_are_named():
    tool = _tool()
    # the status holds while a check stops being attempted: a change of refutation names, never of the verdict
    names = _by_key(_audit(tool, _case(lambda s: _resp("HOLDS", names=("a", "b") if not _swapped(s) else ("a",)))))
    assert names["R2"]["kinds"] == ["refutations"]
    assert not names["R2"]["exit_one"]
    band = {"check": "mathematics.equality", "actual": 1.0, "claimed": 2.0, "used": 0.5}
    moved = dict(band, actual=2.0, claimed=1.0)
    bands = _by_key(_audit(tool, _case(lambda s: _resp("HOLDS", bands=[moved if _swapped(s) else band]))))
    assert bands["R2"]["kinds"] == ["band"] and not bands["R2"]["exit_one"]
    read = _by_key(_audit(tool, _case(lambda s: _resp("HOLDS", read="swapped" if _swapped(s) else "read"))))
    assert read["R2"]["kinds"] == ["read"]
    status = _by_key(_audit(tool, _case(lambda s: _resp("HOLDS", status="ERROR" if _swapped(s) else "CONFIRMED"))))
    assert "status" in status["R2"]["kinds"] and not status["R2"]["exit_one"]


def test_pointers_are_read_through_r5s_id_map():
    tool = _tool()
    before = tool.signature(_resp("BROKEN", status="MISMATCH", broken_at="a"))
    renamed = tool.signature(_resp("BROKEN", status="MISMATCH", broken_at="r0"))
    moved = tool.signature(_resp("BROKEN", status="MISMATCH", broken_at="r1"))
    assert tool.compare(before, renamed, {"a": "r0"}) == []
    assert tool.compare(before, moved, {"a": "r0"}) == [
        {"field": "broken_at", "before": "a", "read_through_map": "r0", "after": "r1"}]
    assert tool.compare(before, renamed, None)[0]["field"] == "broken_at"      # without the map it would read moved


def test_a_real_row_keeps_its_pointer_under_r5_only_through_the_map():
    """ORDER_FREE['false dependency'] breaks at 'a'. Under R5 it breaks at 'r0', its new name: the same step."""
    tool = _tool()
    H, R = tool._telemetry(), tool._restate()
    with H.isolated():
        from concordance import derivation as D
        D.warm()
        (case,) = tool.tier_population(H, names=["ORDER_FREE['false dependency']"])
        o = R.restate("R5", case["subject"])
        base, after = case["run"](case["subject"]), case["run"](o.after)
    assert base["broken_at"] == "a" and after["broken_at"] == o.mapping["a"] == "r0"
    assert tool.compare(tool.signature(base), tool.signature(after), o.mapping) == []
    assert [d["field"] for d in tool.compare(tool.signature(base), tool.signature(after))] == ["broken_at"]


@pytest.mark.parametrize("asserts, path, expected", [
    ([{"path": "derivation", "verdict": "BROKEN"}], "derivation", True),
    ([{"path": "derivation", "verdict": {"not": "HOLDS"}}], "derivation", True),
    ([{"path": "derivation", "verdict": {"in": ["INCOMPLETE", "SYSTEM_ERROR"]}}], "derivation", True),
    ([{"path": "derivation", "verdict": {"in": ["HOLDS", "INCOMPLETE"]}}], "derivation", False),
    ([{"path": "compose", "verdict": "HOLDS"}], "compose", False),
    ([{"path": "compose", "verdict": "BROKEN"}], "derivation", None),
    ([], "derivation", None),
])
def test_what_a_tier_rows_source_asserts_on_a_path(asserts, path, expected):
    assert _tool()._asserts_not_holds(asserts, path) is expected


def test_changes_are_ordered_exit_one_first_then_unasserted_holds():
    tool = _tool()
    mk = lambda kinds, ex, case: {"population": "tier", "case": case, "path": "p", "restatement": "R1",  # noqa: E731
                                  "kinds": kinds, "exit_one": ex}
    changes = [mk(["status"], False, "a"), mk(["into_holds_unasserted", "verdict"], False, "b"),
               mk(["flip", "verdict"], True, "c")]
    assert [c["case"] for c in sorted(changes, key=tool._order)] == ["c", "b", "a"]


def test_the_exits():
    tool = _tool()
    assert tool.exit_code({"compared": 0, "exit_one": []}) == 2
    assert tool.exit_code({"compared": 3, "exit_one": []}) == 0
    assert tool.exit_code({"compared": 3, "exit_one": [["benchmark", "c", "p", "R2"]]}) == 1
    assert tool.main(["--case", "no such case"]) == 2


# ── one re-measurement of a timed-out run ─────────────────────────────────────────────────────────────────────
def test_a_timed_out_run_is_measured_once_more_and_the_second_stands():
    tool = _tool()
    late = _resp("SYSTEM_ERROR", status="ERROR", detail="verification timed out (> 8s)")
    calls = []

    def flaky(s):
        calls.append(_swapped(s))
        return late if len(calls) == 1 else _resp("HOLDS")
    res = _audit(tool, _case(flaky))
    assert res["changes"] == [] and calls[:2] == [False, False]
    assert res["remeasured"] == [{"run": "benchmark:stubbed:stub", "first": "SYSTEM_ERROR", "second": "HOLDS",
                                  "still_timed_out": False}]
    stuck = _audit(tool, _case(lambda s: late if _swapped(s) else _resp("HOLDS")))
    (c,) = stuck["changes"]
    assert c["restatement"] == "R2" and c["timed_out"] is True and not c["exit_one"]
    assert [m["still_timed_out"] for m in stuck["remeasured"]] == [True]


# ── which restatement may take which path ─────────────────────────────────────────────────────────────────────
def test_r5_is_a_closure_audit_and_text_rows_are_reached_only_by_r5():
    tool = _tool()
    rows = ["AUDIT_TEXTS[0], as audit lists it", "AUDIT_TEXTS[0], listed in reverse"]
    rep = tool.run(benchmark="none", rows=rows)
    declined = {(d["case"], d["path"], d["restatement"]): d["reason"] for d in rep["declines"]}
    for k in tool.KEYS:
        assert declined[(rows[0], "audit", k)] == tool.AUDIT_PATH
    for row in rows:
        for k in ("R1", "R2", "R3", "R4"):
            assert declined[(row, "derivation", k)] == tool.TEXT_ROW
        assert (row, "derivation", "R5") not in declined
    assert rep["by_restatement"]["R5"]["applied"] == 2 and rep["compared"] == 2
    one = tool.run(benchmark="all", tier="none", cases=["equality:Pythagorean identity"])
    assert [d["reason"] for d in one["declines"] if d["restatement"] == "R5"] == [tool.CLOSURE_ONLY]
    assert one["compared"] == 4                       # R1-R4 on the claim, its spec passed back to benchmark.verify


def test_a_restatement_that_changes_nothing_the_path_passes_is_declined():
    """A claim is restated as the one step derivation.verify makes of it, and only its spec is passed on: a
    restatement whose spec bytes come back unchanged has nothing to audit."""
    tool = _tool()
    res = _audit(tool, _case(lambda s: _resp("HOLDS"), passes=lambda s: "the same bytes every time"))
    assert res["changes"] == [] and not res["applied"]
    assert {d["reason"] for d in res["declines"] if d["restatement"] in ("R1", "R2", "R3", "R4")} == {
        "the restatement changes nothing the path passes"}


# ── the fast audit, in the gate; the benchmark-wide audit behind -m slow ──────────────────────────────────────
def _domains():
    tool = _tool()
    H = tool._telemetry()
    with H.isolated():
        return sorted({c["domains"][0] for c in tool.benchmark_population(H)})


def test_the_fast_audit_sees_every_domain_and_its_exit_one_set_is_known(capsys):
    """The first benchmark case of every domain and every fast tier row: every domain is reached, its exit-1 set is
    KNOWN exactly, and only mathematics is reached by more than R1 (R2-R4 fit mathematics modes only)."""
    tool = _tool()
    env = {k: os.environ.get(k) for k in ("CONCORDANCE_MEMO", "CONCORDANCE_DATA_DIR", "CONCORDANCE_CAS_DIR",
                                          "CONCORDANCE_LEDGER_DIR")}
    rep = tool.run(benchmark="per-domain", tier="fast")
    assert {k: os.environ.get(k) for k in env} == env, "the audit left the environment changed"
    domains = _domains()
    assert rep["populations"]["benchmark"] == {"cases": len(domains), "of": 1796}
    assert sorted(rep["coverage"]["by_domain"]) == domains and len(domains) > 80
    assert rep["coverage"]["reached_only_by_R1"] == [d for d in domains if d != "mathematics"]
    math = rep["coverage"]["by_domain"]["mathematics"]
    assert [math[k]["applied"] for k in tool.KEYS] == [1, 1, 1, 1, 0]
    fast = [r for r in tool._telemetry()._tier().rows() if not r["slow"]]
    assert rep["populations"]["tier"]["cases"] == sum(len({a["path"] for a in r["asserts"]}) or 1 for r in fast)
    assert {tuple(k) for k in rep["exit_one"]} == {tuple(k) for k in rep["known_in_population"]}
    assert rep["exit_one_not_known"] == [] and rep["known_not_measured"] == [] and rep["known_problems"] == []
    assert tool.exit_code(rep) == (1 if rep["known_in_population"] else 0)
    assert rep["compared"] == sum(row["applied"] for row in rep["by_restatement"].values())
    tool._print(rep)
    assert "reached only by R1" in capsys.readouterr().out


def test_every_known_entry_names_its_fixing_run_and_hold():
    """KNOWN is checked by known_problems, which a planted entry shows is not vacuous: an entry with no fixing
    run or no hold, or a key that is not (population, case, path, restatement), is named."""
    tool = _tool()
    assert tool.known_problems(tool.KNOWN) == []
    good = {"run": "2026-11-04-some-fix", "hold": "no V3 ship in mathematics until the run lands"}
    assert tool.known_problems({("benchmark", "c", "verify_derivation", "R2"): good}) == []
    planted = {("benchmark", "c", "verify_derivation", "R2"): {"run": "2026-11-04-some-fix"},
               ("benchmark", "c", "verify_derivation", "R9"): good, ("c", "R2"): good}
    assert tool.known_problems(planted) == [
        "('benchmark', 'c', 'verify_derivation', 'R2'): names no fixing run and hold",
        "('benchmark', 'c', 'verify_derivation', 'R9'): not (population, case, path, restatement)",
        "('c', 'R2'): not (population, case, path, restatement)"]


@pytest.mark.slow
def test_the_benchmark_wide_audit_s_exit_one_set_is_known(tmp_path):
    tool = _tool()
    out = tmp_path / "audit.json"
    rc = tool.main(["--benchmark", "all", "--tier", "all", "--json", str(out)])
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["populations"]["benchmark"] == {"cases": 1796, "of": 1796}
    assert {tuple(k) for k in rep["exit_one"]} == set(tool.KNOWN)
    assert rc == (1 if tool.KNOWN else 0)
    assert rep["seconds"]["benchmark"] > 0 and rep["seconds"]["all"] >= rep["seconds"]["benchmark"]


# ── no writes ─────────────────────────────────────────────────────────────────────────────────────────────────
def _tree(path):
    out = {}
    for p in sorted(Path(path).rglob("*")):
        rel = p.relative_to(path).as_posix()
        out[rel] = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "dir"
    return out


def test_the_tool_writes_nothing_to_the_stores_it_is_pointed_at(tmp_path, monkeypatch):
    """As a subprocess, with the memo left on and the data, CAS and ledger paths pointed at a scratch copy of the
    real data directory: the scratch copy and the repository's data/ come back byte-identical. The control shows
    the scratch stores are live: a plain verification under that environment writes into them."""
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
    argv = ["--case", "equality:Pythagorean identity", "--case", "golden:physics:true",
            "--row", "COMPOSE_DOC", "--row", "RECEIPT_REVERSE_CHAIN"]
    p = subprocess.run([sys.executable, str(TOOL), *argv, "--json", str(out)], cwd=str(ROOT), env=env,
                       capture_output=True, text=True, timeout=300)
    assert p.returncode == 0, (p.stdout[-2000:], p.stderr[-2000:])
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["populations"]["benchmark"]["cases"] == 2 and rep["populations"]["tier"]["cases"] == 3
    assert rep["compared"] > 0
    assert _tree(scratch) == before and _tree(ROOT / "data") == data_before
    from concordance import derivation as D
    for k in ("CONCORDANCE_DATA_DIR", "CONCORDANCE_CAS_DIR", "CONCORDANCE_LEDGER_DIR"):
        monkeypatch.setenv(k, env[k])
    monkeypatch.setenv("CONCORDANCE_MEMO", "1")
    D.verify_derivation(copy.deepcopy([{"id": "b", "domain": "mathematics", "spec": SQUARES}]))
    assert _tree(scratch) != before
