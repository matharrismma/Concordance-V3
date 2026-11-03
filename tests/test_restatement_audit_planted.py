"""Measurement 4 of the TRM report, step audit-planted (run 2026-11-03-restatement-audit): planted defects, run end
to end through tools/restatement_audit.py, prove each exit and each comparison of the audit.

Each defect is planted into the engine with monkeypatch and taken out when the test ends, and each runs the real
path of the case it names (benchmark.verify for a derivation-moat claim, a tier row's own path):

    a verifier that flips HOLDS to BROKEN under one restatement      (R1: params not listed expr_a first)  exit 1
    a verifier that turns INCOMPLETE into HOLDS on a false case       (R3: a spaced expr_a)                exit 1
    a verifier that renames its check while its status holds          (R2: swapped sides)                  exit 0
    a closure that moves a pointer under R5, and one that heals a BROKEN tier row into HOLDS     exit 0, exit 1
    a meaning-changing restatement (R4 forgetting the defaulted variable; R2 altering a side), caught by its own
    verifier-free oracle and never by the audit: declined, never run, while with the oracle bypassed the audit
    would read the restatement's own change as a verifier defect
    a path that raises: the audit's own failure, recorded by case, exit 3 (an exit-1 change still reads 1)

Each test names the one change it plants and requires the audit to report exactly that change and no other, so a
defect the audit missed, or one it saw too widely, fails. The planted runs are a few cases each, to keep the fast
suite small.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "restatement_audit.py"

PYTHAGORAS = "equality:Pythagorean identity"                     # HOLDS, labelled true
TWO_PLUS_TWO_FIVE = "equality:2+2=5"                             # labelled false
SQUARES = "equality:difference of squares"                       # HOLDS, labelled true
SQUARE_TRAP = "inequality:(x-3)^2>0 -- false only at x=3 (sampling trap)"   # BROKEN, labelled false
FALSE_DEPENDENCY = "ORDER_FREE['false dependency']"             # BROKEN at a; its source asserts BROKEN


def _tool():
    spec = importlib.util.spec_from_file_location("restatement_audit", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _only(rep):
    """The one change a test plants, as (restatement, kinds, exit_one)."""
    assert len(rep["changes"]) == 1, [(c["restatement"], c["kinds"]) for c in rep["changes"]]
    (c,) = rep["changes"]
    return c["restatement"], c["kinds"], c["exit_one"]


def _math(monkeypatch, mode, planted):
    from concordance import derivation as D
    monkeypatch.setitem(D._MATH_MODES, mode, planted(D._MATH_MODES[mode]))


# ── the exit-1 kinds ──────────────────────────────────────────────────────────────────────────────────────────
def test_a_verifier_that_flips_under_one_restatement_exits_one(monkeypatch):
    """Planted: the equality verifier reads BROKEN when its params are not listed expr_a first. Only R1 reorders
    them, so the audit reports one flip, under R1, and exits 1; KNOWN does not hold it, so the suite's KNOWN pin
    would fail on it."""
    from concordance.verifiers.base import mismatch
    _math(monkeypatch, "equality", lambda real: (
        lambda p: mismatch("mathematics.equality", "planted") if list(p)[:1] != ["expr_a"] else real(p)))
    tool = _tool()
    rep = tool.run(cases=[PYTHAGORAS])
    key, kinds, exit_one = _only(rep)
    assert key == "R1" and kinds[:2] == ["flip", "verdict"] and exit_one
    assert rep["changes"][0]["diffs"][0] == {"field": "verdict", "before": "HOLDS", "after": "BROKEN"}
    assert rep["exit_one"] == rep["exit_one_not_known"] == [["benchmark", PYTHAGORAS, "benchmark.verify", "R1"]]
    assert tool.exit_code(rep) == 1
    assert rep["compared"] == 4                     # R1-R4 ran; the flip is R1's alone


def test_a_verifier_that_turns_incomplete_into_holds_on_a_false_case_exits_one(monkeypatch):
    """Planted: the equality verifier cannot check an expr_a without a space, and confirms one with a space. 2+2=5
    (labelled false) reads INCOMPLETE as given; R3 spaces it out and it reads HOLDS: a false positive reached by
    restating the claim, not a flip, and still exit 1."""
    from concordance.verifiers.base import confirm, na
    _math(monkeypatch, "equality", lambda real: (
        lambda p: confirm("mathematics.equality", "planted") if " " in str(p.get("expr_a")) else
        na("mathematics.equality", "planted")))
    tool = _tool()
    rep = tool.run(cases=[TWO_PLUS_TWO_FIVE])
    key, kinds, exit_one = _only(rep)
    assert key == "R3" and kinds[0] == "false_to_holds" and "flip" not in kinds and exit_one
    assert rep["changes"][0]["diffs"][0] == {"field": "verdict", "before": "INCOMPLETE", "after": "HOLDS"}
    assert rep["changes"][0]["label"] is False and tool.exit_code(rep) == 1


# ── a change that is not exit-1 is still reported ─────────────────────────────────────────────────────────────
def test_a_verifier_that_renames_its_check_while_its_status_holds_is_reported(monkeypatch):
    """Planted: with the sides swapped, the equality verifier confirms under another check name. The status, the
    verdict and the read all hold; only the refutation check names move, and the audit reports exactly that."""
    from concordance.verifiers.base import confirm
    _math(monkeypatch, "equality", lambda real: (
        lambda p: (lambda r: confirm("mathematics.equality_swapped", r.detail) if r.status == "CONFIRMED"
                   and p.get("expr_a") == "1" else r)(real(p))))
    tool = _tool()
    rep = tool.run(cases=[PYTHAGORAS])
    assert _only(rep) == ("R2", ["refutations"], False)
    (d,) = rep["changes"][0]["diffs"]
    assert d["field"] == "refutations" and d["step"] == 0
    assert d["before"]["survived"] == ["mathematics.equality"] and d["after"]["survived"] == ["mathematics.equality_swapped"]
    assert tool.exit_code(rep) == 0


# ── the closure under R5 ──────────────────────────────────────────────────────────────────────────────────────
def _renamed(steps):
    return any(str(s.get("id", ""))[:1] == "r" and str(s.get("id"))[1:].isdigit() for s in steps)


def _closure(monkeypatch, planted):
    from concordance import derivation as D
    monkeypatch.setattr(D, "verify_derivation", planted(D.verify_derivation))


def test_a_closure_that_moves_a_pointer_under_r5_is_reported(monkeypatch):
    """Planted: once ids are renamed, the closure names the last listed step as where trust broke. The verdict and
    every status hold; only broken_at moves, read through R5's id map, and the audit reports exactly that."""
    def moved(real):
        def go(steps):
            r = real(steps)
            if _renamed(steps) and r.get("broken_at"):
                r = dict(r, broken_at=str(steps[-1]["id"]))
            return r
        return go
    _closure(monkeypatch, moved)
    tool = _tool()
    rep = tool.run(rows=[FALSE_DEPENDENCY])
    assert _only(rep) == ("R5", ["broken_at"], False)
    (d,) = rep["changes"][0]["diffs"]
    assert d == {"field": "broken_at", "before": "a", "read_through_map": "r0", "after": "r1"}
    assert tool.exit_code(rep) == 0


def test_a_closure_that_heals_a_broken_row_under_r5_exits_one(monkeypatch):
    """Planted: once ids are renamed, the closure reads a BROKEN derivation as HOLDS. The row's source asserts BROKEN,
    so the change is a flip and a false positive on a row asserted not to hold: exit 1."""
    def healed(real):
        return lambda steps: (lambda r: dict(r, verdict="HOLDS") if _renamed(steps) and r.get("verdict") == "BROKEN"
                              else r)(real(steps))
    _closure(monkeypatch, healed)
    tool = _tool()
    rep = tool.run(rows=[FALSE_DEPENDENCY])
    key, kinds, exit_one = _only(rep)
    assert key == "R5" and kinds[:3] == ["flip", "false_to_holds", "verdict"] and exit_one
    assert rep["changes"][0]["asserts_not_holds"] is True and tool.exit_code(rep) == 1


# ── a meaning-changing restatement is its oracle's to catch, never the audit's ───────────────────────────────
def _forgets_the_default(real):
    def build(subject):
        after, mapping, done = real(subject)
        for s in after:
            s["spec"]["params"].pop("variable", None)        # R4's first known mistake
        return after, mapping, done
    return build


def _alters_a_side(real):
    def build(subject):
        after, mapping, done = real(subject)
        for s in after:
            s["spec"]["params"]["expr_b"] = s["spec"]["params"]["expr_b"].replace("-1", "+1")
        return after, mapping, done
    return build


@pytest.mark.parametrize("key, case, planted, refusal, bypassed", [
    ("R4", SQUARE_TRAP, _forgets_the_default,
     "its oracle refuses it: step 0: the mode reads variable (default 'x'), and the restatement does not write it in",
     ["verdict", "status", "refutations", "broken_at", "gap_at", "read"]),   # BROKEN at b -> INCOMPLETE, gap at b
    ("R2", SQUARES, _alters_a_side,
     "its oracle refuses it: step 0: the parsed sides are not the two sides exchanged",
     ["flip", "verdict", "status", "refutations", "broken_at", "read"]),     # HOLDS -> BROKEN at b: a false alarm
])
def test_a_meaning_changing_restatement_is_caught_by_its_own_oracle_never_by_the_audit(monkeypatch, key, case,
                                                                                         planted, refusal, bypassed):
    """The planted build changes the claim's meaning. Its verifier-free oracle refuses it, so the audit declines it
    with that reason and never runs it. The control bypasses the oracle: the audit then runs the changed claim and
    reads the restatement's own change as a verifier defect, which is why the oracle, not the audit, must catch it."""
    tool = _tool()
    R = tool._restate()
    monkeypatch.setattr(R.BY_KEY[key], "build", planted(R.BY_KEY[key].build))
    monkeypatch.setattr(tool, "_restate", lambda: R)
    rep = tool.run(cases=[case])
    assert rep["changes"] == [] and tool.exit_code(rep) == 0
    assert [d["reason"] for d in rep["declines"] if d["restatement"] == key] == [refusal]
    assert rep["by_restatement"][key]["applied"] == 0
    monkeypatch.setattr(R.BY_KEY[key], "oracle", lambda before, after: None)
    fooled = tool.run(cases=[case])
    restatement, kinds, _ = _only(fooled)
    assert restatement == key and kinds == bypassed


# ── a path that raises: the audit's own failure, exit 3 ───────────────────────────────────────────────────────
def test_a_path_that_raises_is_recorded_by_case_and_exits_three(monkeypatch):
    """Planted: compose raises on a renamed document. The audit records the error by case and restatement, keeps
    auditing the rest, and exits 3, a code no change can give. An exit-1 change found beside an error still exits
    1, and a run that raises before any case is measured exits 3 from main."""
    from concordance import compose
    real = compose.seal_document

    def fragile(doc, *a, **kw):
        if _renamed(doc.get("steps") or []):
            raise RuntimeError("planted: compose cannot take a renamed document")
        return real(doc, *a, **kw)
    monkeypatch.setattr(compose, "seal_document", fragile)
    tool = _tool()
    rep = tool.run(rows=["COMPOSE_DOC"])
    assert rep["changes"] == []
    # COMPOSE_DOC's sources assert on compose and on the MCP document tool, which seals through compose too
    assert rep["errors"] == [{"population": "tier", "case": "COMPOSE_DOC", "path": path, "restatement": "R5",
                              "error": "RuntimeError: planted: compose cannot take a renamed document"}
                             for path in ("compose", "mcp-document")]
    assert rep["compared"] == 2                       # R1 on each path; R2-R4 decline (no mathematics), R5 raised
    assert tool.exit_code(rep) == 3
    assert tool.exit_code(dict(rep, exit_one=[["tier", "COMPOSE_DOC", "compose", "R1"]])) == 1
    assert tool.exit_code({"compared": 0, "exit_one": [], "errors": rep["errors"]}) == 3
    monkeypatch.setattr(tool, "run", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("planted")))
    assert tool.main(["--row", "COMPOSE_DOC"]) == 3


def test_a_case_whose_given_run_raises_is_skipped_and_recorded():
    """The case as given could not be run: nothing to compare it with, so its restatements are not run either, and
    the error names no restatement."""
    tool = _tool()

    def boom(subject):
        raise ValueError("planted")
    case = {"population": "benchmark", "case": "raising", "label": True, "domains": ["mathematics"], "path": "stub",
            "subject": [{"id": "b", "domain": "mathematics", "spec": {"mode": "equality", "params": {
                "expr_a": "x+x", "expr_b": "2*x", "variables": {}}}}], "passes": lambda s: s, "run": boom}
    res = tool.audit_cases(tool._telemetry(), tool._restate(), [case])
    assert res["changes"] == [] and not res["applied"]
    assert res["errors"] == [{"population": "benchmark", "case": "raising", "path": "stub", "restatement": None,
                              "error": "ValueError: planted"}]
