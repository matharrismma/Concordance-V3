"""Measurement 3: a topological evaluation order, the deterministic control any ranker would have to beat (run
2026-11-03-topological-order, step topo-order-tool).

tools/topo_order.py runs every tier row (tests/fixtures/derivation_tier.py) under the listed order and under Kahn's
order over the closure's own `below`, read from verify_derivation's frame, with derivation._evaluation_order
replaced for that one call and restored in a finally. It records halt.passes under each and the saving; compares
measurement 2's full gate (tools/order_replica.py's _run and _evaluation_fields: the response except halt.passes,
and what _transfer settles per step); and counts verifier calls at derivation.verify_step as a multiset of
(domain, spec hash). It exits 1 if a compared field differs, if a row needs MORE passes under the topological
order, if an order calls a key more times than the trail has steps carrying it whose verifier ran, or if the two
orders' call multisets differ; 2 if it measured nothing.

These tests pin the order and its passes on eight shapes (and the reverse listing of two of them); make the closure
the judge over the fast tier (every row settles in exactly 2 passes, or 1 where nothing moves: guaranteed for an
acyclic row, measured for a cyclic one) and show an order that drops bind edges fails that check while every exit
stays silent; prove each exit with a planted defect; hold a verifier timeout to one re-measurement; and run the tool
as a subprocess with the stores pointed at a scratch copy, which must come back byte-identical. The 1,500-step chain
runs behind -m slow.

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
TOOL = ROOT / "tools" / "topo_order.py"
FIXTURES = ROOT / "tests" / "fixtures"


def _tool():
    spec = importlib.util.spec_from_file_location("topo_order", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tier():
    if str(FIXTURES) not in sys.path:
        sys.path.insert(0, str(FIXTURES))
    import derivation_tier
    return derivation_tier


def _report(tool, tmp_path, *argv):
    out = tmp_path / "report.json"
    rc = tool.main([*argv, "--json", str(out)])
    return rc, json.loads(out.read_text(encoding="utf-8"))


def _given(tool, name, steps):
    """One derivation of a test's own, measured as the tool measures a tier row: (exit code, report, its row)."""
    rep = tool.run_rows([{"name": name, "steps": steps}])
    (row,) = rep["rows"]
    return tool.exit_code(rep), rep, row


# ── the order and its passes ──────────────────────────────────────────────────────────────────────────────────
def _shapes():
    """name -> (steps, Kahn's order, its leftovers, passes as listed, passes under the topological order)."""
    T = _tier()
    num, rect, area_of = T.num, T.rect, T.area_of
    missing = [num("a", "2+2", 4), num("b", "3+3", 6, uses=["a", "z"]), num("c", "1+1", 2, uses=["b"])]
    repeated = [num("a", "2+2", 4), num("a", "3+3", 6), num("b", "1+1", 2, uses=["a"]), num("c", "2+1", 3, uses=["b"])]
    return {
        # s3 uses s2 uses s1 uses s0, listed s3 first: each link waits a pass as listed
        "a reverse-listed chain": (list(reversed(T.chain_of(4))), [3, 2, 1, 0], [], 5, 2),
        # d uses b and c, each uses a; listed against the edges. b and c are both ready once a is: listed position
        "a diamond": ([num("d", "4+6", 10, uses=["b", "c"]), num("b", "2+2", 4, uses=["a"]),
                       num("c", "3+3", 6, uses=["a"]), num("a", "1+1", 2)], [3, 1, 2, 0], [], 4, 2),
        # a <-> b a cycle, c rests on it, e a self-loop; f uses d, listed before it. Kahn places d then f, and only
        # its leftovers (c, a, b, e: on or resting on a cycle) follow, in listed position
        "a cycle": ([num("f", "5*1", 5, uses=["d"]), num("c", "1+1", 2, uses=["a"]), num("a", "2+2", 4, uses=["b"]),
                     num("b", "3+3", 6, uses=["a"]), num("d", "2+3", 5), num("e", "1+2", 3, uses=["e"])],
                    [4, 0, 1, 2, 3, 5], [1, 2, 3, 5], 3, 2),
        # z is carried by no step: no edge, and b keeps its place (checker-26: moving it last costs a pass)
        "[a, b uses [a, z], c uses b]": (missing, [0, 1, 2], [], 2, 2),
        "[a, b uses [a, z], c uses b], listed in reverse": (list(reversed(missing)), [2, 1, 0], [], 4, 2),
        # a is carried twice: b's reference resolves to neither, so b stands first among the steps c needs
        "[a, a, b uses a, c uses b]": (repeated, [0, 1, 2, 3], [], 2, 2),
        "[a, a, b uses a, c uses b], listed in reverse": (list(reversed(repeated)), [1, 0, 2, 3], [], 3, 2),
        # the bind is an edge in below even though b names no `uses`
        "a bind whose source is listed after its user": (
            [rect("b", None, 1, 24, bind=area_of("a")), rect("a", 4, 6, 24)], [1, 0], [], 3, 2),
        # a bind from an id two steps carry resolves to none: b is blocked, no edge; c still waits on b
        "a bind from a repeated id": (
            [rect("c", 1, 2, 2, uses=["b"]), rect("b", None, 1, 24, bind=area_of("a")), rect("a", 4, 6, 24),
             rect("a", 4, 6, 24)], [1, 0, 2, 3], [], 3, 2),
        # the step listed second has no id, so it is s1, and b uses s1
        "a default id another step uses": ([rect("b", 2, 12, 24, uses=["s1"]), rect(None, 4, 6, 24)], [1, 0], [], 3, 2),
    }


@pytest.mark.parametrize("name", list(_shapes()))
def test_the_order_and_its_passes(name):
    tool = _tool()
    steps, order, leftovers, listed, topological = _shapes()[name]
    rc, rep, row = _given(tool, name, steps)
    assert (row["order"], row["leftovers"]) == (order, leftovers), row
    assert row["passes"] == {"listed": listed, "topological": topological}, row
    assert row["saving"] == listed - topological and row["at_floor"] and row["acyclic"] == (not leftovers)
    assert row["identical"] == {"evaluation: response": True, "evaluation: settled": True}
    assert row["calls_equal"] and row["calls"]["listed"] == row["calls"]["topological"] == row["calls"]["verifiers_ran"]
    assert rc == 0 and rep["failures"] == []


# ── the closure is the judge ──────────────────────────────────────────────────────────────────────────────────
# the fast tier rows that need more than 2 passes as listed (run 2026-11-02-halt-and-order, measurement 1)
ABOVE_TWO = {"TWO_STEP, listed in reverse", "HALTING", "chain_of(6), listed in reverse", "README document, listed in reverse",
             "BIND, listed in reverse", "BIND_FALSE_SOURCE, listed in reverse", "AUDIT_TEXTS[0], listed in reverse",
             "RECEIPT_REVERSE_CHAIN"}


def test_under_the_topological_order_every_fast_tier_row_reaches_the_floor(tmp_path):
    """Exactly 2 passes, or 1 where the first pass moves nothing (SELF_BIND, whose one step binds from itself). By
    construction for an acyclic row; for a cyclic row this is measured, not proven: [b uses a, a false uses b]
    takes 3 under both orders (checker-26)."""
    tool = _tool()
    rc, rep = _report(tool, tmp_path, "--tier-rows", "fast")
    assert rc == 0 and rep["failures"] == [], rep["failures"][:3]
    rows, t = rep["rows"], rep["totals"]
    assert t["rows"] == len(rows) == 62
    for r in rows:
        assert r["at_floor"] and r["passes"]["topological"] == r["floor"], r
        assert r["floor"] == (1 if r["passes"]["listed"] == 1 else 2)
    assert {r["name"] for r in rows if r["floor"] == 1} == {"SELF_BIND"}
    assert t["at_floor"] == 62 and t["not_at_floor"] == []
    assert any(not r["acyclic"] for r in rows) and any(r["acyclic"] for r in rows)
    # the saving is exactly the rows above the floor as listed, each brought down to it
    differ = {r["name"]: r for r in rows if r["saving"]}
    assert set(differ) == {r["name"] for r in rows if r["passes"]["listed"] > 2} == ABOVE_TWO
    assert set(t["differing"]) == ABOVE_TWO and all(r["saving"] > 0 for r in rows if r["saving"])
    assert t["saving"]["all"] == t["saving"]["fast_rows"] == sum(r["saving"] for r in rows) > 0
    assert t["saving"]["slow_rows"] == 0
    assert t["identity"] == {"compared": 62, "identical": 62, "share": 1.0}
    assert t["calls"]["equal_rows"] == 62 and t["calls"]["listed"] == t["calls"]["topological"]
    assert t["over_bound_rows"] == 0
    # RECEIPT_REVERSE_CHAIN's three steps share one spec: one key, called once per step
    rcpt = next(r for r in rows if r["name"] == "RECEIPT_REVERSE_CHAIN")
    assert rcpt["calls"] == {"listed": 3, "topological": 3, "verifiers_ran": 3} and rcpt["keys"] == 1


def _uses_only(frame, k):
    """A planted copy of the edge rules that forgets bind sources: only `uses`, resolved to single carriers."""
    loc = frame.f_locals
    single, steps = loc["single"], loc["steps"]
    return [[single[str(u)] for u in (s.get("uses") or []) if str(u) in single] for s in steps]


def test_an_order_that_drops_bind_edges_misses_the_floor_while_every_exit_stays_silent(tmp_path, monkeypatch):
    """checker-26's measurement: such an order never needs MORE passes than listed and changes no response and no
    call, so the tool exits 0; it understates the saving on three reverse-listed bind rows, 3 passes instead of 2,
    and only the floor check sees it."""
    tool = _tool()
    monkeypatch.setattr(tool, "_edges", _uses_only)
    rc, rep = _report(tool, tmp_path, "--tier-rows", "fast")
    assert rc == 0 and rep["failures"] == []
    missed = {r["name"]: r["passes"] for r in rep["rows"] if not r["at_floor"]}
    assert missed == {name: {"listed": 3, "topological": 3} for name in (
        "README document, listed in reverse", "BIND, listed in reverse", "BIND_FALSE_SOURCE, listed in reverse")}
    assert set(rep["totals"]["not_at_floor"]) == set(missed)


# ── each exit, with a planted defect ──────────────────────────────────────────────────────────────────────────
def _kinds(rep):
    return sorted({f["kind"] for f in rep["failures"]})


def test_a_non_topological_order_that_costs_a_pass_exits_1(tmp_path, monkeypatch):
    """The reverse of the listing put in Kahn's place, on a row listed dependency-sorted: 4 passes where the listed
    order takes 2. Responses and calls stay identical, so only the MORE-passes exit fires."""
    tool = _tool()
    monkeypatch.setattr(tool, "kahn", lambda below: (list(reversed(range(len(below)))), []))
    rc, rep = _report(tool, tmp_path, "--row", "ORDER_FREE['true chain']")
    (row,) = rep["rows"]
    assert rc == 1 and _kinds(rep) == ["more_passes"]
    assert row["passes"] == {"listed": 2, "topological": 4} and row["order"] == [2, 1, 0]
    assert all(row["identical"].values()) and row["calls_equal"]


def _plant_transfer(monkeypatch):
    """checker-26's construction: _transfer gives c an origin only when c was first visited before b. The visits
    are read through the rule; _pass_cap, called once at the start of every run, clears them."""
    from concordance import derivation as D
    real_t, real_cap = D._transfer, D._pass_cap
    visited = []

    def cap(k):
        visited.clear()
        return real_cap(k)

    def transfer(node, own, deps, halt=""):
        out = real_t(node, own, deps, halt)
        if node["id"] not in visited:
            visited.append(node["id"])
        if out is not None and node["id"] == "c" and visited.index("c") < visited.index("b"):
            out = (out[0], True, out[2])
        return out

    monkeypatch.setattr(D, "_pass_cap", cap)
    monkeypatch.setattr(D, "_transfer", transfer)


def test_a_patched_transfer_is_caught_in_the_settled_field_with_the_response_unchanged(monkeypatch):
    """[a false, c uses b, b uses a]: listed, c is visited before b and the planted rule makes it originate its
    break; in Kahn's order (a, b, c) it does not. broken_at still names a, so the response is the same; only what
    _transfer settles differs."""
    tool = _tool()
    num = _tier().num
    steps = [num("a", "2+2", 5), num("c", "1+1", 2, uses=["b"]), num("b", "3+3", 6, uses=["a"])]
    rc, rep, row = _given(tool, "a false, c uses b, b uses a", steps)
    assert row["order"] == [0, 2, 1] and row["passes"] == {"listed": 3, "topological": 2}
    assert row["identical"] == {"evaluation: response": True, "evaluation: settled": True}   # the control
    _plant_transfer(monkeypatch)
    rc, rep, row = _given(tool, "a false, c uses b, b uses a", steps)
    assert rc == 1 and _kinds(rep) == ["identity"]
    (f,) = rep["failures"]
    assert f["fields"] == ["evaluation: settled"] and f["verdicts"] == ["BROKEN", "BROKEN"]
    assert row["identical"] == {"evaluation: response": True, "evaluation: settled": False}


def _plant_double(monkeypatch, when):
    """bucket.through, the closure's one path to a verifier, made to call the verifier twice whenever when() holds:
    the result, and so the response, is unchanged."""
    from concordance import bucket
    real = bucket.through

    def through(domain, spec_hash, compute):
        if when():
            return real(domain, spec_hash, lambda: (compute(), compute())[1])
        return real(domain, spec_hash, compute)

    monkeypatch.setattr(bucket, "through", through)


def test_a_double_count_under_both_orders_is_caught_by_the_per_key_bound(tmp_path, monkeypatch):
    """RECEIPT_REVERSE_CHAIN: three steps, one spec, so the bound for its one key is 3. Doubled under both orders,
    each calls it 6 times; the multisets are equal, so the equality check alone would pass it."""
    tool = _tool()
    _plant_double(monkeypatch, lambda: True)
    rc, rep = _report(tool, tmp_path, "--row", "RECEIPT_REVERSE_CHAIN")
    (row,) = rep["rows"]
    assert rc == 1 and _kinds(rep) == ["over_bound"]
    assert sorted(f["order"] for f in rep["failures"]) == ["listed", "topological"]
    assert all(f["keys"] == [dict(f["keys"][0], calls=6, bound=3)] for f in rep["failures"])
    assert row["calls_equal"] and row["calls"] == {"listed": 6, "topological": 6, "verifiers_ran": 3}
    assert all(row["identical"].values())


def _topological_installed(D, original):
    return lambda: D._evaluation_order is not original


def test_a_double_count_under_one_order_only_is_caught(tmp_path, monkeypatch):
    """Doubled only while the topological order is installed: that order breaks the bound, the listed one does
    not, and the two call multisets differ."""
    tool = _tool()
    from concordance import derivation as D
    _plant_double(monkeypatch, _topological_installed(D, D._evaluation_order))
    rc, rep = _report(tool, tmp_path, "--row", "RECEIPT_REVERSE_CHAIN")
    (row,) = rep["rows"]
    assert rc == 1 and _kinds(rep) == ["calls_differ", "over_bound"]
    assert [f["order"] for f in rep["failures"] if f["kind"] == "over_bound"] == ["topological"]
    (diff,) = [f for f in rep["failures"] if f["kind"] == "calls_differ"]
    assert diff["listed_only"] == [] and [k["calls"] for k in diff["topological_only"]] == [3]
    assert not row["calls_equal"] and row["calls"] == {"listed": 3, "topological": 6, "verifiers_ran": 3}


def test_a_call_that_escapes_the_count_under_one_order_is_caught_by_equality_alone(tmp_path, monkeypatch):
    """The equality exit on its own: while the topological order is installed, the first verifier is called past
    the counted derivation.verify_step. The response is the same and no key exceeds its bound, but the multisets
    differ."""
    tool = _tool()
    from concordance import bucket
    from concordance import derivation as D
    real, original_v = bucket.through, D.verify_step
    topo, done = _topological_installed(D, D._evaluation_order), []

    def through(domain, spec_hash, compute):
        if topo() and not done:
            done.append(1)
            counted, D.verify_step = D.verify_step, original_v
            try:
                return real(domain, spec_hash, compute)
            finally:
                D.verify_step = counted
        return real(domain, spec_hash, compute)

    monkeypatch.setattr(bucket, "through", through)
    rc, rep = _report(tool, tmp_path, "--row", "ORDER_FREE['true chain']")
    (row,) = rep["rows"]
    assert rc == 1 and _kinds(rep) == ["calls_differ"]
    assert row["calls"] == {"listed": 3, "topological": 2, "verifiers_ran": 3} and all(row["identical"].values())


def test_nothing_measured_exits_2(monkeypatch):
    tool = _tool()
    monkeypatch.setattr(tool, "tier_rows", lambda which="all": [])
    assert tool.main(["--tier-rows", "fast"]) == 2


# ── the order fails loudly, and the patch is put back ─────────────────────────────────────────────────────────
def test_an_order_that_is_not_a_permutation_raises_and_the_engine_is_restored():
    tool = _tool()
    from concordance import derivation as D
    original_o, original_v = D._evaluation_order, D.verify_step
    real_kahn = tool.kahn
    tool.kahn = lambda below: ([0] * len(below), [])
    try:
        with pytest.raises(AssertionError, match="not a permutation"):
            tool.run_rows([{"name": "TWO_STEP", "steps": _tier().TWO_STEP}])
    finally:
        tool.kahn = real_kahn
    assert D._evaluation_order is original_o and D.verify_step is original_v


def test_the_order_reads_below_only_from_verify_derivation():
    """Called from any frame but verify_derivation's, the installed order refuses rather than guess its edges."""
    tool = _tool()
    with pytest.raises(AssertionError, match="verify_derivation"):
        tool.topological([])(2)


# ── a verifier timeout is re-measured once ────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("timeouts,rc,still", [((2,), 0, False), ((2, 5), 1, True)])
def test_a_verifier_timeout_is_re_measured_once_never_until_it_passes(timeouts, rc, still, tmp_path, monkeypatch):
    """ORDER_FREE['true chain'] calls 3 verifiers a run. The listed run's 2nd call times out, so it is measured once
    more; when that run's 2nd call (the 5th) times out too, the second measurement stands, timed out, and the
    row fails on identity. 9 calls either way: never a third measurement."""
    tool = _tool()
    from concordance import derivation as D
    real, calls = D.verify_step, {"n": 0}

    def flaky(domain, spec):
        calls["n"] += 1
        if calls["n"] in timeouts:
            return {"status": "ERROR", "detail": "verification timed out (> 8.0s)"}
        return real(domain, spec)

    monkeypatch.setattr(D, "verify_step", flaky)
    got, rep = _report(tool, tmp_path, "--row", "ORDER_FREE['true chain']")
    assert got == rc and calls["n"] == 9
    assert rep["totals"]["remeasured"] == [{"row": "ORDER_FREE['true chain']", "order": "listed",
                                            "first": "SYSTEM_ERROR", "second": "SYSTEM_ERROR" if still else "HOLDS",
                                            "still_timed_out": still}]
    if still:
        (f,) = rep["failures"]
        assert f["kind"] == "identity" and f["timeout"] is True


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
    rows = ["ORDER_FREE['true chain']", "BIND, listed in reverse", "RECEIPT_REVERSE_CHAIN"]
    p = subprocess.run([sys.executable, str(TOOL), *[a for r in rows for a in ("--row", r)], "--json", str(out)],
                       cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=300)
    assert p.returncode == 0, (p.stdout[-2000:], p.stderr[-2000:])
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["totals"]["rows"] == 3 and rep["totals"]["identity"]["share"] == 1.0
    assert rep["totals"]["saving"]["all"] == 1 + 2                 # BIND reversed 3 -> 2; RECEIPT_REVERSE_CHAIN 4 -> 2
    assert _tree(scratch) == before and _tree(ROOT / "data") == data_before
    from concordance import derivation as D
    for k in ("CONCORDANCE_DATA_DIR", "CONCORDANCE_CAS_DIR", "CONCORDANCE_LEDGER_DIR"):
        monkeypatch.setenv(k, env[k])
    monkeypatch.setenv("CONCORDANCE_MEMO", "1")
    D.verify_derivation(json.loads(json.dumps(tool.tier_rows("fast")[0]["steps"])))
    assert _tree(scratch) != before


# ── the whole tier, the 1,500-step chain included ─────────────────────────────────────────────────────────────
@pytest.mark.slow
def test_the_whole_tier_reaches_the_floor_and_the_long_chain_saves_1499_passes(tmp_path):
    tool = _tool()
    rc, rep = _report(tool, tmp_path)
    assert rc == 0 and rep["failures"] == []
    t = rep["totals"]
    assert t["rows"] == 63 and t["at_floor"] == 63 and t["identity"]["share"] == 1.0
    long = next(r for r in rep["rows"] if r["name"] == "chain_of(1500), listed in reverse")
    assert long["slow"] and long["acyclic"] and long["order"] == list(range(1499, -1, -1))
    assert long["passes"] == {"listed": 1501, "topological": 2} and long["saving"] == 1499
    assert long["calls"] == {"listed": 1500, "topological": 1500, "verifiers_ran": 1500} and long["calls_equal"]
    assert t["saving"]["slow_rows"] == 1499 and t["saving"]["all"] == t["saving"]["fast_rows"] + 1499
    assert set(t["differing"]) == ABOVE_TWO | {long["name"]}
