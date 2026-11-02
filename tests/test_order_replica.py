"""Measurement 2: the closure's result does not depend on the order it visits, or lists, the steps (run
2026-11-02-halt-and-order, step order-replica).

tools/order_replica.py runs every tier row (tests/fixtures/derivation_tier.py) under every permutation of
derivation._evaluation_order (at least 8 seeded ones, with the listed and the reverse order, past 6 steps) and
compares, by canonical hash against the listed order, the whole response except halt.passes, and what _transfer
settles for each step (effective outcome and originator kinds) keyed by its listed position. For a row whose every
step carries an explicit unique id it also permutes the LISTING under the same rule and compares, by step id, the
verdict, confirmed_steps, each step's effective outcome and the originator sets. It exits nonzero on any mismatch,
naming the row and the two orders.

These tests run it over the fast tier and require 100% identity (the one row from a slow source, the 1,500-step
chain, behind -m slow); plant, for each compared field, a verdict-neutral defect that differs across evaluation
orders, one of them on a repeated-id row, and an order-dependent defect that changes the verdict, and require the
tool to catch each in the field it targets; hold a verifier timeout to "re-measured once, and it still fails"; and
run it as a subprocess with the stores pointed at a scratch copy, which must come back byte-identical.

The tool is imported inside each test, never at module level, so with it absent each test reads red.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "order_replica.py"


def _tool():
    spec = importlib.util.spec_from_file_location("order_replica", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _report(tool, tmp_path, *argv):
    out = tmp_path / "report.json"
    rc = tool.main([*argv, "--json", str(out)])
    return rc, json.loads(out.read_text(encoding="utf-8"))


def _rule_count(k, n):
    """How many orders the rule asks for: every permutation up to 6 steps, else at least 8 seeded ones."""
    return n == math.factorial(k) if k <= 6 else n >= 8


def test_every_fast_tier_row_is_identical_under_every_order(tmp_path):
    """Every row from a fast source of up to 5 steps. The two 6-step rows (720 evaluation orders and 720 listings
    each, about 15 s together, nearly all of it the verifiers with the memo off) would breach the 60 s budget, so
    they run with the whole tier behind -m slow, below."""
    tool = _tool()
    rc, rep = _report(tool, tmp_path, "--tier-rows", "fast", "--max-steps", "5")
    assert rc == 0 and rep["mismatches"] == [], rep["mismatches"][:3]
    t = rep["totals"]
    assert t["rows"] == 60 and t["identical"] == t["compared"] and t["identity"] == 1.0
    assert {r["name"] for r in rep["left_out"]} == {"chain_of(6)", "chain_of(6), listed in reverse"}
    rows = {r["name"]: r for r in tool.tier_rows("fast")}
    listed = 0
    for row in rep["rows"]:
        k = row["steps"]
        assert _rule_count(k, row["evaluation_orders"]), row
        assert row["settled_positions"] == k, row        # every step's settling return was read, every row
        if tool.unique_ids(rows[row["name"]]["steps"]):
            assert _rule_count(k, row["listings"]), row
            listed += 1
        else:
            assert row["listings"] == 0 and row["listing_skipped"], row
    assert listed and listed < len(rep["rows"])
    # the rows where order-freedom was hardest are on the evaluation branch: repeated ids and default ids
    skipped = {r["name"]: r["listing_skipped"] for r in rep["rows"] if r["listings"] == 0}
    assert skipped["DERIVATIONS[5]"] == "a repeated id" and skipped["DEFAULT_ID_COLLISION"] == "a step with no id"


@pytest.mark.slow
def test_the_whole_tier_is_identical_under_every_order(tmp_path):
    """The whole tier, as the tool's own run measures it: the 6-step rows under all 720 orders and listings, and
    the row from a slow source (the 1,500-step chain) under the listed, reverse and 8 seeded ones."""
    tool = _tool()
    rc, rep = _report(tool, tmp_path)
    assert rc == 0 and rep["mismatches"] == [] and rep["totals"]["identity"] == 1.0
    assert rep["totals"]["rows"] == 63 and rep["left_out"] == []
    by = {r["name"]: r for r in rep["rows"]}
    for name in ("chain_of(6)", "chain_of(6), listed in reverse"):
        assert by[name]["evaluation_orders"] == by[name]["listings"] == 720
    long = by["chain_of(1500), listed in reverse"]
    assert long["steps"] == 1500 and long["evaluation_orders"] == long["listings"] == 10


# ── planted defects: each a monkeypatched _transfer rule, keyed to the order the steps are visited in ──────────
def _plant(monkeypatch, rule):
    """Replace _transfer with `rule` applied over the real one. `state` holds, for the current run, the ids in
    the order first visited and the ids settled so far; _pass_cap, called once at the start of every run, clears
    it."""
    from concordance import derivation as D
    real_t, real_cap = D._transfer, D._pass_cap
    state = {"visited": [], "settled": set()}

    def cap(k):
        state["visited"].clear()
        state["settled"].clear()
        return real_cap(k)

    def transfer(node, own, deps, halt=""):
        out = real_t(node, own, deps, halt)
        if node["id"] not in state["visited"]:
            state["visited"].append(node["id"])
        out = rule(D, node, own, deps, out, state)
        if out is not None:
            state["settled"].add(node["id"])
        return out

    monkeypatch.setattr(D, "_pass_cap", cap)
    monkeypatch.setattr(D, "_transfer", transfer)


def _before(state, a, b):
    v = state["visited"]
    return a in v and (b not in v or v.index(a) < v.index(b))


# (field targeted, row, rule): each changes its field and never the verdict, and only in some visiting orders
DEFECTS = [
    # m settles on its seam before s has settled: it drops the seam's record (the response's trail), nothing else
    ("evaluation: response", "ORDER_FREE['bridge MISMATCH']",
     lambda D, node, own, deps, out, st: (out[0], out[1], None)
     if out and node["id"] == "m" and "s" not in st["settled"] else out),
    # a repeated id (checker-24's): b drops its origin when it settles before either a has
    ("evaluation: settled", "DERIVATIONS[5]",
     lambda D, node, own, deps, out, st: (out[0], False, out[2])
     if out and node["id"] == "b" and "a" not in st["settled"] else out),
    # s, settling after m, reads as a gap it does not originate: one fewer confirmed step, still BROKEN
    ("listing: confirmed_steps", "ORDER_FREE['bridge MISMATCH']",
     lambda D, node, own, deps, out, st: (D._GAP, False, None)
     if out and node["id"] == "s" and "m" in st["settled"] else out),
    # b, visited before a, inherits our failure instead of a's break: its outcome changes, still BROKEN
    ("listing: outcomes", "ORDER_FREE['false dependency']",
     lambda D, node, own, deps, out, st: (D._ERROR, False, None)
     if out and node["id"] == "b" and _before(st, "b", "a") else out),
    # c, visited before a, keeps its gap but no longer originates it
    ("listing: originators", "ORDER_FREE['bind from a false source']",
     lambda D, node, own, deps, out, st: (out[0], False, out[2])
     if out and node["id"] == "c" and _before(st, "c", "a") else out),
]
# the order-dependent rule that changes the verdict: an unsettled dependency read as a gap
VERDICT_DEFECT = ("listing: verdict", "ORDER_FREE['true chain']",
                  lambda D, node, own, deps, out, st: (D._GAP, True, None)
                  if out is None and own is not None and None in deps else out)


@pytest.mark.parametrize("field,row,rule", DEFECTS, ids=[d[0] for d in DEFECTS])
def test_a_verdict_neutral_defect_is_caught_in_the_field_it_targets(field, row, rule, tmp_path, monkeypatch):
    tool = _tool()
    _plant(monkeypatch, rule)
    rc, rep = _report(tool, tmp_path, "--row", row)
    found = rep["mismatches"]
    assert rc == 1 and found, rep["totals"]
    assert field in {f for m in found for f in m["fields"]}, (field, found[:2])
    assert all(m["row"] == row and len(m["orders"]) == 2 and m["orders"][0] != m["orders"][1] for m in found)
    assert all(m["verdicts"][0] == m["verdicts"][1] for m in found)          # verdict-neutral
    assert "listing: verdict" not in {f for m in found for f in m["fields"]}
    assert any(m["branch"] == "evaluation" for m in found)                 # it differs across evaluation orders
    if field.startswith("evaluation"):
        assert {f for m in found for f in m["fields"]} == {field}          # nothing else compared sees it
    if field == "evaluation: settled":
        steps = {r["name"]: r["steps"] for r in tool.tier_rows("fast")}[row]
        assert not tool.unique_ids(steps)                                  # a repeated-id row


def test_an_order_dependent_defect_that_changes_the_verdict_is_caught(tmp_path, monkeypatch):
    field, row, rule = VERDICT_DEFECT
    tool = _tool()
    _plant(monkeypatch, rule)
    rc, rep = _report(tool, tmp_path, "--row", row)
    found = rep["mismatches"]
    assert rc == 1 and field in {f for m in found for f in m["fields"]}
    assert any(m["verdicts"][0] != m["verdicts"][1] for m in found if m["branch"] == "evaluation")
    assert any(m["verdicts"][0] != m["verdicts"][1] for m in found if m["branch"] == "listing")


def test_a_mismatch_from_a_verifier_timeout_is_re_measured_once_and_still_fails(tmp_path, monkeypatch):
    """The 5th verification of the run times out: the listed baseline ran 3, so the first permutation reads one
    step as our failure. That mismatch is named as a timeout, re-measured once (now identical), and still fails."""
    tool = _tool()
    from concordance import derivation as D
    real, calls = D.verify_step, {"n": 0}

    def flaky(domain, spec):
        calls["n"] += 1
        if calls["n"] == 5:
            return {"status": "ERROR", "detail": "verification timed out (> 8.0s)"}
        return real(domain, spec)

    monkeypatch.setattr(D, "verify_step", flaky)
    rc, rep = _report(tool, tmp_path, "--row", "ORDER_FREE['true chain']")
    (m,) = rep["mismatches"]
    assert rc == 1 and m["timeout"] is True and m["remeasured"] == {"identical": True}
    assert m["branch"] == "evaluation" and m["orders"] == [[0, 1, 2], [0, 1, 2]]


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
    rows = ["ORDER_FREE['true chain']", "DERIVATIONS[5]", "ORDER_FREE['bridge MISMATCH']"]
    p = subprocess.run([sys.executable, str(TOOL), *[a for r in rows for a in ("--row", r)], "--json", str(out)],
                       cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=300)
    assert p.returncode == 0, (p.stdout[-2000:], p.stderr[-2000:])
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["totals"]["rows"] == 3 and rep["totals"]["identity"] == 1.0
    assert _tree(scratch) == before and _tree(ROOT / "data") == data_before
    from concordance import derivation as D
    for k in ("CONCORDANCE_DATA_DIR", "CONCORDANCE_CAS_DIR", "CONCORDANCE_LEDGER_DIR"):
        monkeypatch.setenv(k, env[k])
    monkeypatch.setenv("CONCORDANCE_MEMO", "1")
    D.verify_derivation(json.loads(json.dumps(tool.tier_rows("fast")[0]["steps"])))
    assert _tree(scratch) != before
