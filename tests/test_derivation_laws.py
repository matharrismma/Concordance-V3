"""The composition law of the order-free derivation closure, and its bounds (run 2026-11-02-order-free-derivation).

derivation.py carries the law in three module-level pure functions over two rails that only switch on (P: a
check holds; R: a check breaks): _transfer, the per-step rule the closure iterates; _meet, Kleene's strong
meet, for the composite only; and _readout, Moisil's r1 'certainly holds' and r2 'not broken', applied at the
output and nowhere else. ERROR and a gap both ride as not-checkable (P=0, R=0), with their cause beside the
rails. These tests hold the laws exhaustively over the step outcomes, prove from the source that no rail is
negated inside _transfer or _meet and that r1 and r2 are used only by _readout, and bound the closure: k + 1
passes, one verifier call per step, a cap that stops part-way never says more than the full closure, and a
halting record that stays out of every sealed record. tests/test_derivation_order_free.py proves (the WIRING
test) that verify_derivation computes through all three functions.
"""
from __future__ import annotations

import ast
import copy
import itertools
import sys
from pathlib import Path
from typing import Dict

import pytest

from concordance import derivation as D

# the derivations live in the tier (tests/fixtures/derivation_tier.py), their one home
_FIXTURES = str(Path(__file__).resolve().parent / "fixtures")
if _FIXTURES not in sys.path:
    sys.path.insert(0, _FIXTURES)
from derivation_tier import (BIND_CHAIN_4, CHAIN_1500, CHAIN_6, DERIVATIONS, HALTING, HALTING_DOC,  # noqa: E402
                             PART_WAY, SELF_BIND, SELF_CYCLE, TRACE_CYCLE, num, repeated_body)

SRC = Path(D.__file__)


@pytest.fixture(scope="module", autouse=True)
def _warm():
    """Pre-pay the heavy imports outside the per-verification timeout, as the server does at boot."""
    D.warm()


def outcomes():
    """Every value a step's effective outcome can take: the four outcomes, and the gap the cap leaves."""
    return {"confirmed": D._CONFIRMED, "broken": D._BROKEN, "error": D._ERROR, "gap": D._GAP, "cap": D._CUT}


def kind(v):
    return "BROKEN" if v.r else "CONFIRMED" if v.p else "ERROR" if "error" in v.why else "GAP"


# ── THE LAWS, exhaustive over the step outcomes ───────────────────────────────────────────────────────────
def test_the_meet_is_monotone_in_the_information_order():
    """Refining a not-checkable step to holds or to broken only ever switches a rail on: a definite composite
    never flips, and no rail that was on goes off."""
    vals = list(outcomes().values())
    flips_checked = 0
    for n in range(1, 5):
        for t in itertools.product(vals, repeat=n):
            before = D._meet(t)
            for i, v in enumerate(t):
                if v.p or v.r:
                    continue
                for refined in (D._CONFIRMED, D._BROKEN):
                    after = D._meet(t[:i] + (refined,) + t[i + 1:])
                    assert after.p >= before.p and after.r >= before.r, (t, i, refined)
                    if before.p or before.r:
                        assert (after.p, after.r) == (before.p, before.r), (t, i, refined)
                        flips_checked += 1
    assert flips_checked > 1000


def test_the_meet_of_nothing_is_not_checkable():
    c = D._meet([])
    assert (c.p, c.r) == (False, False)
    assert D._readout(c) == "INCOMPLETE" and D._meet(iter(())) == c


def test_r1_and_r2_determine_the_outcome_and_r1_never_exceeds_r2():
    vals = list(outcomes().values())
    composites = [D._meet(t) for n in range(4) for t in itertools.product(vals, repeat=n)]
    seen = set()
    for v in vals + composites:
        r1, r2 = D._r1(v), D._r2(v)
        assert r1 <= r2, v                               # never a proof and a counterexample at once
        read = {(True, True): "holds", (False, True): "not checkable", (False, False): "broken"}[(r1, r2)]
        assert read == ("holds" if v.p else "broken" if v.r else "not checkable"), v
        seen.add(read)
    assert seen == {"holds", "not checkable", "broken"}


def test_the_readout_keeps_the_precedence_broken_system_error_incomplete_holds():
    vals = outcomes()

    def expected(names):
        if "broken" in names:
            return "BROKEN"
        if "cap" in names:          # cut off by the cap: a step left unsettled could still break
            return "INCOMPLETE"
        if "error" in names:
            return "SYSTEM_ERROR"
        if names and set(names) == {"confirmed"}:
            return "HOLDS"
        return "INCOMPLETE"

    for n in range(5):
        for names in itertools.product(vals, repeat=n):
            assert D._readout(D._meet([vals[x] for x in names])) == expected(names), names


SEAMS = ([], [{"status": "MISMATCH", "bridge": "theory_inference"}], [{"status": "INCOMPLETE", "bridge": "scale_regime"}],
         [{"status": "NOT_APPLICABLE"}], [{"status": "INCOMPLETE", "bridge": "x"}, {"status": "MISMATCH", "bridge": "y"}])


def test_transfer_settles_only_from_settled_evidence():
    """Exhaustive over the step outcomes, an absent reference, every kind of seam and a repeated id: whatever
    _transfer settles while some input is unsettled (None) it settles identically however each one later
    settles; with every input settled it always settles; and once the closure has halted it always settles,
    keeping what the evidence decided and making the rest a gap."""
    vals = list(outcomes().values())
    owns = [None, D._CONFIRMED, D._BROKEN, D._ERROR, D._GAP]
    cases = early = 0
    for own in owns:
        for deps in itertools.chain.from_iterable(itertools.product([None] + vals, repeat=m) for m in range(3)):
            for missing in ([], ["z"]):
                for seams in SEAMS:
                    for repeated in (False, True):
                        node = {"id": "x", "at": 0, "missing": missing, "seams": seams, "repeated": repeated}
                        got = D._transfer(node, own, list(deps))
                        cases += 1
                        own_fill = owns[1:] if own is None else [own]
                        holes = [vals if d is None else [d] for d in deps]
                        unsettled = own is None or None in deps
                        if not unsettled:
                            assert got is not None, (own, deps, missing, seams, repeated)
                        if got is not None and unsettled:
                            early += 1
                            for o in own_fill:
                                for ds in itertools.product(*holes):
                                    assert D._transfer(node, o, list(ds)) == got, (own, deps, o, ds)
                        for halt in ("cycle", "rests on a cycle", "cap"):
                            h = D._transfer(node, own, list(deps), halt)
                            if halt == "cap":
                                assert h == (D._CUT, True, None)
                            elif got is not None:
                                assert h == got
                            else:
                                assert h[0] == D._GAP and h[2] is None
    assert cases > 3000 and early > 100


def _module():
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    return tree, {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}


def test_no_rail_is_negated_inside_transfer_or_meet():
    """No `not`, `~`, unary minus, subtraction, `!=`, `is not` or `not in`, and no comparison against a
    boolean or 0/1 constant: inside the composition there is no way to read a rail off, so no step settles on
    the absence of evidence."""
    _, fns = _module()
    for name in ("_transfer", "_meet"):
        for n in ast.walk(fns[name]):
            where = (name, getattr(n, "lineno", None))
            assert not (isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.Not, ast.Invert, ast.USub))), where
            assert not (isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Sub, ast.BitXor))), where
            if isinstance(n, ast.Compare):
                assert not any(isinstance(op, (ast.NotEq, ast.IsNot, ast.NotIn)) for op in n.ops), where
                assert not any(isinstance(x, ast.Constant) and isinstance(x.value, (bool, int))
                               for x in [n.left] + n.comparators), where
            if isinstance(n, ast.Name):
                assert n.id not in ("_r1", "_r2", "not_", "invert"), where


def test_r1_and_r2_are_used_only_by_readout():
    tree, fns = _module()
    used = set()
    for top in tree.body:
        for n in ast.walk(top):
            name = n.id if isinstance(n, ast.Name) else n.attr if isinstance(n, ast.Attribute) else None
            if name in ("_r1", "_r2"):
                used.add((getattr(top, "name", "<module>"), name))
    assert used == {("_readout", "_r1"), ("_readout", "_r2")}
    # and the one negation of a rail lives in r2
    assert any(isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not) for n in ast.walk(fns["_r2"]))
    # the three functions are module-level, reached from verify_derivation as globals
    loads = {n.id for n in ast.walk(fns["verify_derivation"]) if isinstance(n, ast.Name)}
    assert {"_transfer", "_meet", "_readout"} <= loads


# ── the closure: DERIVATIONS, PART_WAY and the chains below are in the tier, tests/fixtures/derivation_tier.py ─
def test_the_closure_halts_by_settling_within_k_plus_1_passes():
    for steps in DERIVATIONS:
        for perm in itertools.permutations(steps):
            r = D.verify_derivation(copy.deepcopy(list(perm)))
            k = len(perm)
            assert r["halt"]["reason"] == "settled" and 1 <= r["halt"]["passes"] <= k + 1, r["halt"]
            assert r["halt"]["cap"] == k + 1
    # tight: a chain listed in reverse settles one link a pass, then one pass in which nothing moves
    chain = copy.deepcopy(CHAIN_6)
    r = D.verify_derivation(list(reversed(chain)))
    assert r["verdict"] == "HOLDS" and r["halt"] == {"passes": 7, "reason": "settled", "cap": 7}
    assert D.verify_derivation(chain)["halt"]["passes"] == 2


def _same(r):
    r = copy.deepcopy(r)
    r["halt"].pop("passes")
    return r


def test_order_replica_every_evaluation_order_gives_the_same_result(monkeypatch):
    """The closure run under every order of visiting the steps within a pass: the same result, field for
    field (only the pass count may differ). A non-monotone rule would show up here as a mismatch."""
    passes_seen = set()
    for steps in DERIVATIONS:
        base = D.verify_derivation(copy.deepcopy(steps))
        for order in itertools.permutations(range(len(steps))):
            # a context of its own, so undoing it leaves conftest's autouse settings in place
            with monkeypatch.context() as m:
                m.setattr(D, "_evaluation_order", lambda k, o=list(order): list(o))
                r = D.verify_derivation(copy.deepcopy(steps))
            assert _same(r) == _same(base), order
            passes_seen.add(r["halt"]["passes"])
        assert D._evaluation_order(3) == [0, 1, 2]          # restored: listed order again
    assert len(passes_seen) > 1          # the injected order was used: it changed how many passes it took


# ── BOUNDED ───────────────────────────────────────────────────────────────────────────────────────────────
def test_each_verifier_runs_exactly_once_or_never_when_its_bind_stays_unresolved(monkeypatch):
    calls: Dict[str, int] = {}
    real = D.verify_step

    def counting(domain, spec):
        h = D._spec_hash(spec)
        calls[h] = calls.get(h, 0) + 1
        return real(domain, spec)

    monkeypatch.setattr(D, "verify_step", counting)
    counted = DERIVATIONS + [
        BIND_CHAIN_4,
        SELF_BIND,
    ]
    ran_late = 0
    for steps in counted:
        for perm in itertools.permutations(steps):
            calls.clear()
            r = D.verify_derivation(copy.deepcopy(list(perm)))
            want: Dict[str, int] = {}
            for t in r["trail"]:
                if t.get("unresolved_binding"):
                    assert t["status"] == "NOT_APPLICABLE" and t["spec_hash"] not in calls
                else:
                    want[t["spec_hash"]] = want.get(t["spec_hash"], 0) + 1
            assert calls == want, [s["id"] for s in perm]
            m = next((t for t in r["trail"] if t["id"] == "m"), None)
            if m is not None and [s["id"] for s in perm] == ["m", "s"]:
                # settled BROKEN by its seam before its bind resolved, and still checked once on its final spec
                assert m["bridge"]["status"] == "MISMATCH" and not m.get("unresolved_binding")
                ran_late += 1
    assert ran_late == 1


def test_a_repeated_id_costs_work_in_proportion_to_the_body(monkeypatch):
    """checker-22's body, scaled down: k steps all carrying id 'a', each using 'a', across domains (case variants
    included). Keeping every (step, carrier) pair made the work quadratic: one seam result per cross-domain carrier
    per step. Counted here instead of timed: at most one bridge check per step per distinct dependency domain,
    nothing handed to _transfer larger than the step's own uses, and a trace the size of the body."""
    k = 800
    steps = repeated_body(k)      # held in the tier as EXCLUDED: the stub below is not a real verifier
    monkeypatch.setattr(D, "verify_step", lambda domain, spec: {"status": "CONFIRMED", "detail": "stub", "data": {}})
    checks = []
    real_check = D._bridges.check
    monkeypatch.setattr(D._bridges, "check", lambda *a: checks.append(a[0]) or real_check(*a))
    sizes = []
    real_transfer = D._transfer

    def transfer(node, own, deps, halt=""):
        sizes.append((len(deps), len(node["seams"]), len(node["missing"])))
        return real_transfer(node, own, deps, halt)

    monkeypatch.setattr(D, "_transfer", transfer)
    r = D.verify_derivation(steps)
    assert r["verdict"] == "INCOMPLETE" and r["broken_at"] is None
    # each step has exactly one distinct canonical domain besides its own among the steps carrying 'a'
    assert len(checks) == k
    assert len(sizes) <= 2 * k and all(d <= 1 and s <= 2 and m <= 1 for d, s, m in sizes)
    assert all(t["repeated_id"] == k for t in r["trail"])
    assert sum(len(e["stands_on"]) for e in r["trace"]["events"]) == k
    assert sum(len(t.get("cycle") or []) for t in r["trail"]) <= k


def test_the_pass_cap_is_at_least_k_plus_1():
    for k in range(200):
        assert D._pass_cap(k) >= k + 1
    assert D.verify_derivation([num("a", "2+2", 4)])["halt"] == {"passes": 2, "reason": "settled", "cap": 2}


def test_a_cap_that_stops_part_way_keeps_what_settled_and_never_says_more(monkeypatch):
    """A cap that stops part-way depends on order by design, so it is held apart: in each order and at each
    cap, every settled step's outcome is its uncapped outcome, every step the cap cut off is a gap and
    originates one, and the composite is the uncapped composite or INCOMPLETE — never HOLDS unless the
    uncapped composite is HOLDS."""
    settled_by = []
    real_transfer, real_cap = D._transfer, D._pass_cap

    def transfer(node, own, deps, halt=""):
        out = real_transfer(node, own, deps, halt)
        if out is not None:
            settled_by.append((node["id"], kind(out[0]), out[1]))
        return out

    monkeypatch.setattr(D, "_transfer", transfer)
    part_way = cut_beside_error = 0
    for steps in PART_WAY:
        for perm in itertools.permutations(steps):
            listed = [s["id"] for s in perm]
            monkeypatch.setattr(D, "_pass_cap", real_cap)
            settled_by.clear()
            full = D.verify_derivation(copy.deepcopy(list(perm)))
            full_out = {sid: (kd, o) for sid, kd, o in settled_by}
            for cap in range(len(perm) + 2):
                monkeypatch.setattr(D, "_pass_cap", lambda k, c=cap: c)
                settled_by.clear()
                r = D.verify_derivation(copy.deepcopy(list(perm)))
                got = {sid: (kd, o) for sid, kd, o in settled_by}
                cut = {t["id"] for t in r["trail"] if t.get("unsettled") == "cap"}
                assert sorted(got) == sorted(listed) and r["halt"]["cap"] == cap
                for sid in listed:
                    assert got[sid] == (("GAP", True) if sid in cut else full_out[sid]), (listed, cap, sid)
                assert r["verdict"] in (full["verdict"], "INCOMPLETE"), (listed, cap)
                if r["verdict"] == "HOLDS":
                    assert full["verdict"] == "HOLDS"
                if cut:
                    assert r["halt"]["reason"] == "cap" and r["gap_at"] is not None and r["verdict"] != "HOLDS"
                    part_way += 0 < len(cut) < len(listed)
                    cut_beside_error += (full["verdict"] == "BROKEN" and r["verdict"] == "INCOMPLETE"
                                         and r["error_at"] == "e")
                else:
                    assert r["verdict"] == full["verdict"]
    assert part_way and cut_beside_error


def test_trace_distance_and_stands_on_are_computed_without_recursion():
    tree, _ = _module()
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and fn.name in (
                "_depth_and_floor", "_trace", "_cycles", "_transfer", "_meet", "_readout", "verify_derivation",
                "_resolve", "_built", "_own", "_first"):
            calls = {n.func.id for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
            assert fn.name not in calls, fn.name
    # on a cycle there is no depth, and stands_on names what the step reaches, itself included
    ev = {e["id"]: e for e in D.verify_derivation(copy.deepcopy(TRACE_CYCLE))["trace"]["events"]}
    assert (ev["a"]["distance"], ev["a"]["stands_on"]) == (None, ["b", "a"])
    assert (ev["b"]["distance"], ev["b"]["stands_on"]) == (None, ["a", "b"])
    assert (ev["c"]["distance"], ev["c"]["stands_on"]) == (None, ["a", "b"])
    assert (ev["d"]["distance"], ev["d"]["stands_on"]) == (1, [])
    ev = D.verify_derivation(copy.deepcopy(SELF_CYCLE))["trace"]["events"][0]
    assert (ev["distance"], ev["stands_on"]) == (None, ["a"])


def _has_key(obj, key):
    if isinstance(obj, dict):
        return key in obj or any(_has_key(v, key) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return any(_has_key(v, key) for v in obj)
    return False


def test_the_halting_record_rides_in_the_response_only(tmp_path, monkeypatch):
    """SEAL_SPEC and RECEIPT_SPEC are unchanged: the halting record is in the response and in no sealed record —
    not record_from_derivation's, and not compose's document root."""
    monkeypatch.setenv("CONCORDANCE_DATA_DIR", str(tmp_path))
    from concordance import cas, compose, receipts
    from concordance.config import EngineConfig
    steps = HALTING
    r = D.verify_derivation(copy.deepcopy(steps))
    assert r["verdict"] == "HOLDS" and r["halt"] == {"passes": 3, "reason": "settled", "cap": 3}
    assert not _has_key(receipts.record_from_derivation(r).to_dict(), "halt")
    doc = compose.seal_document(copy.deepcopy(HALTING_DOC), EngineConfig())
    assert doc["verdict"] == "HOLDS" and doc["root"]
    root = cas.fetch(doc["root"])
    assert root["kind"] == "document" and not _has_key(root, "halt")
    assert not _has_key(cas.fetch(doc["derivation_seal"]["content_hash"]), "halt")


@pytest.mark.slow
def test_a_reverse_listed_chain_of_1500_steps_settles():
    """Longer than Python's default recursion limit (1,000): a recursive walk of the chain would raise here."""
    k = 1500
    chain = copy.deepcopy(CHAIN_1500)
    r = D.verify_derivation(list(reversed(chain)))
    assert r["verdict"] == "HOLDS" and r["confirmed_steps"] == k
    assert r["halt"] == {"passes": k + 1, "reason": "settled", "cap": k + 1}
    ev = {e["id"]: e for e in r["trace"]["events"]}
    assert ev["s0"]["distance"] == 1 and ev[f"s{k - 1}"]["distance"] == k
    assert ev[f"s{k - 1}"]["stands_on"] == [f"s{i}" for i in range(k - 2, -1, -1)]
