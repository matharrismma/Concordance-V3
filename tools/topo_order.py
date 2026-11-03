"""Measurement 3 of the TRM report: a topological evaluation order, the deterministic, non-learned control any
ranker of the closure's steps would have to beat (run 2026-11-03-topological-order).

For every tier row (tests/fixtures/derivation_tier.py) it runs the derivation twice through tools/order_replica.py's
_run (imported, not copied): once under the engine's own derivation._evaluation_order, the listed order, and once
with _evaluation_order replaced, for that one call and restored in a finally, by the topological order:

  THE ORDER       the installed _evaluation_order reads the closure's own dependency edges, verify_derivation's
                  local `below`, from its caller's frame (sys._getframe), so no second copy of derivation.py's edge
                  rules exists here. It asserts its caller is verify_derivation and `below` is a list of k lists of
                  positions, k == len(steps), and returns Kahn's order over `below`: a step's in-degree counts its
                  DISTINCT predecessors (`below` lists one twice when `uses` repeats an id), the ready step with the
                  smallest listed position goes first, and only Kahn's leftovers, the steps on or resting on a cycle
                  of `below` (self-loops included; decided from `below`, never from the trail's labels), follow in
                  listed position. A reference to an id no step carries, or several steps carry, is no edge in
                  `below`, so a step with a repeated or missing id gets no special place. It asserts the result is a
                  permutation of range(k).

Per row it records halt.passes under each order and the saving, and compares:

  identity        measurement 2's full gate, order_replica's _evaluation_fields: the whole response except
                  halt.passes ("evaluation: response"), and what _transfer settles for each step, keyed by its
                  listed position ("evaluation: settled")
  verifier calls  counted at derivation.verify_step, which the closure looks up at call time, as a multiset of
                  (domain, lowercased as verify_step lowercases it; derivation._spec_hash of the spec the closure
                  built and handed in)
  the floor       a pass that moves nothing ends the closure and is counted, so a run whose first pass moves
                  anything takes at least 2 passes, and a listed run that halted after 1 pass moved nothing in it.
                  A row is at the floor when the topological order takes exactly 1 there, else exactly 2. For a row
                  with no Kahn leftovers (`below` acyclic) a topological order reaches it by construction; for a
                  cyclic row it is measured, not proven

It exits 1 when, on any row:
  identity        either compared field differs between the two orders;
  more_passes     the topological order needs MORE passes than the listed one;
  over_bound      an order calls a (domain, spec hash) key more times than the trail has steps carrying that key
                  whose verifier ran (no unresolved binding, and not a step the closure never checked: halt
                  telemetry's NOT_RUN), or more verifiers than there are steps. A correct run calls each step's
                  verifier once: RECEIPT_REVERSE_CHAIN's three steps share one spec, so its one key is called 3 times;
  calls_differ    the two orders' call multisets differ.
It exits 2 if it measured nothing, else 0.

It writes nothing: tools/halt_telemetry.py's isolated() (imported, not copied) forces CONCORDANCE_MEMO=0 and puts
the CAS, ledger, memo bucket and data dir in a temporary directory holding a copy of data/'s reference files. It
calls derivation.warm() first and runs one derivation at a time on its own thread. A run in which a verifier timed
out or was busy is measured once more and the second measurement stands either way (it is reported): re-measured
once, never retried until it passes.

    PYTHONPATH=src python tools/topo_order.py [--tier-rows all|fast|slow] [--row NAME ...] [--json PATH]
"""
from __future__ import annotations

import argparse
import heapq
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

ORDERS = ("listed", "topological")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _telemetry():
    """tools/halt_telemetry.py, imported for isolated(), its tier loader, its timeout reading and NOT_RUN."""
    return _load("_topo_order_halt_telemetry", ROOT / "tools" / "halt_telemetry.py")


def _replica():
    """tools/order_replica.py, imported for _run (one verification, what _transfer settles read by listed
    position) and _evaluation_fields (measurement 2's two compared fields)."""
    return _load("_topo_order_order_replica", ROOT / "tools" / "order_replica.py")


def tier_rows(which: str = "all") -> List[Dict[str, Any]]:
    return _telemetry().tier_rows(which)


def _require(ok: bool, what: str) -> None:
    """An assertion python -O cannot strip."""
    if not ok:
        raise AssertionError(what)


# ── the order ─────────────────────────────────────────────────────────────────────────────────────────────────
def _edges(frame, k: int) -> List[List[int]]:
    """The closure's own dependency edges: verify_derivation's local `below` (below[i] holds the position of the one
    step carrying each id step i uses or binds from), read from the frame that called _evaluation_order. It fails
    loudly if that caller, or the name, changes."""
    name, module = frame.f_code.co_name, frame.f_globals.get("__name__")
    _require(name == "verify_derivation" and module == "concordance.derivation",
             f"_evaluation_order was called by {module}.{name}, not by concordance.derivation.verify_derivation")
    loc = frame.f_locals
    _require("below" in loc and "steps" in loc, "verify_derivation has no local `below` and `steps` to read")
    below, steps = loc["below"], loc["steps"]
    _require(isinstance(below, list) and isinstance(steps, list) and len(below) == k == len(steps),
             f"`below` is not a list of length k == len(steps) == {k}")
    _require(all(isinstance(b, list) and all(type(j) is int and 0 <= j < k for j in b) for b in below),
             "`below` is not a list of lists of listed positions")
    return below


def kahn(below: Sequence[Sequence[int]]) -> Tuple[List[int], List[int]]:
    """Kahn's algorithm over `below` (below[i]: the positions step i stands on): (the order, Kahn's leftovers). The
    in-degree of a step is the number of its DISTINCT predecessors; of the steps ready at once the one listed first
    goes first; the steps never ready, those on a cycle of `below` (a self-loop included) or resting on one, are the
    leftovers, appended in listed position."""
    k = len(below)
    preds = [set(b) for b in below]
    indeg = [len(p) for p in preds]
    succ: List[List[int]] = [[] for _ in range(k)]
    for i, p in enumerate(preds):
        for j in p:
            succ[j].append(i)
    ready = [i for i in range(k) if not indeg[i]]
    heapq.heapify(ready)
    order: List[int] = []
    while ready:
        j = heapq.heappop(ready)
        order.append(j)
        for i in succ[j]:
            indeg[i] -= 1
            if not indeg[i]:
                heapq.heappush(ready, i)
    placed = set(order)
    leftovers = [i for i in range(k) if i not in placed]
    return order + leftovers, leftovers


def topological(seen: List[Dict[str, Any]]) -> Callable[[int], List[int]]:
    """The _evaluation_order to install for one verify_derivation call. Each call reads `below` from its caller,
    takes Kahn's order over it, checks it is a permutation and appends it, with the leftovers, to `seen`."""
    def _evaluation_order(k: int) -> List[int]:
        frame = sys._getframe(1)
        try:
            below = _edges(frame, k)
        finally:
            del frame
        order, leftovers = kahn(below)
        _require(sorted(order) == list(range(k)), f"the order is not a permutation of range({k}): {list(order)[:20]}")
        seen.append({"order": list(order), "leftovers": list(leftovers)})
        return list(order)
    return _evaluation_order


# ── one run, one row ──────────────────────────────────────────────────────────────────────────────────────────
def _one(D, R, steps, order: str):
    """One verification through order_replica._run, with derivation.verify_step wrapped to count its calls. The
    listed order is the engine's own _evaluation_order, checked to be range(k); for the topological order
    derivation._evaluation_order is replaced. Both are put back in a finally."""
    calls: Counter = Counter()
    seen: List[Dict[str, Any]] = []
    real_v, real_o = D.verify_step, D._evaluation_order
    if order == "listed":
        k = len(steps)
        _require(D._evaluation_order(k) == list(range(k)), "the engine's own evaluation order is not the listed order")

    def counted(domain, spec):
        calls[((domain or "").strip().lower(), D._spec_hash(spec))] += 1
        return real_v(domain, spec)

    D.verify_step = counted
    if order == "topological":
        D._evaluation_order = topological(seen)
    try:
        r, settled = R._run(D, steps)
    finally:
        D.verify_step, D._evaluation_order = real_v, real_o
    _require(order == "listed" or bool(seen), "the topological order was installed but never called")
    return {"r": r, "settled": settled, "calls": calls, "seen": seen}


def _measured(D, R, H, steps, order: str):
    """A run in which a verifier timed out or was busy is measured once more, and the second stands either way."""
    first = _one(D, R, steps, order)
    if not H._timed_out(first["r"]):
        return first, None
    again = _one(D, R, steps, order)
    return again, {"order": order, "first": first["r"].get("verdict"), "second": again["r"].get("verdict"),
                   "still_timed_out": H._timed_out(again["r"])}


def _ran(t: Dict[str, Any], H) -> bool:
    """The trail's own reading of whether a step's verifier ran: not a bind left unresolved, and not a step the
    closure never checked (the detail halt_telemetry's NOT_RUN names)."""
    return not t.get("unresolved_binding") and not str(t.get("detail", "")).startswith(H.NOT_RUN)


def _bound(r: Dict[str, Any], H) -> Counter:
    """How many calls a correct run makes per key: the steps in the trail carrying it whose verifier ran."""
    return Counter((str(t.get("domain", "")).strip().lower(), t.get("spec_hash"))
                   for t in r.get("trail") or [] if _ran(t, H))


def _keys(c: Counter, bound: Optional[Counter] = None) -> List[Dict[str, Any]]:
    out = []
    for (domain, spec_hash), n in sorted(c.items()):
        e = {"domain": domain, "spec_hash": spec_hash, "calls": n}
        if bound is not None:
            e["bound"] = bound[(domain, spec_hash)]
        out.append(e)
    return out


def measure_row(D, R, H, row: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """(the row's summary, its failures, its re-measurements)."""
    steps, name = row["steps"], row["name"]
    k = len(steps)
    got: Dict[str, Dict[str, Any]] = {}
    remeasured: List[Dict[str, Any]] = []
    for order in ORDERS:
        got[order], again = _measured(D, R, H, steps, order)
        if again:
            remeasured.append(dict({"row": name}, **again))
    lst, top = got["listed"], got["topological"]
    fields = {o: R._evaluation_fields(got[o]["r"], got[o]["settled"]) for o in ORDERS}
    identical = {f: fields["listed"][f] == fields["topological"][f] for f in fields["listed"]}
    pl, pt = lst["r"]["halt"]["passes"], top["r"]["halt"]["passes"]
    floor = 1 if pl == 1 else 2
    bound = {o: _bound(got[o]["r"], H) for o in ORDERS}
    timeout = any(H._timed_out(got[o]["r"]) for o in ORDERS)
    failures: List[Dict[str, Any]] = []
    differ = [f for f, same in identical.items() if not same]
    if differ:
        failures.append({"row": name, "kind": "identity", "fields": differ, "timeout": timeout,
                         "verdicts": [lst["r"].get("verdict"), top["r"].get("verdict")]})
    if pt > pl:
        failures.append({"row": name, "kind": "more_passes", "passes": {"listed": pl, "topological": pt}})
    for o in ORDERS:
        calls = got[o]["calls"]
        over = Counter({key: n for key, n in calls.items() if n > bound[o][key]})
        if over or sum(calls.values()) > k:
            failures.append({"row": name, "kind": "over_bound", "order": o, "keys": _keys(over, bound[o]),
                             "calls": sum(calls.values()), "steps": k})
    if lst["calls"] != top["calls"]:
        failures.append({"row": name, "kind": "calls_differ", "listed_only": _keys(lst["calls"] - top["calls"]),
                         "topological_only": _keys(top["calls"] - lst["calls"])})
    first = top["seen"][0]
    summary = {"name": name, "steps": k, "slow": bool(row.get("slow")), "verdict": lst["r"].get("verdict"),
               "passes": {"listed": pl, "topological": pt}, "saving": pl - pt,
               "floor": floor, "at_floor": pt == floor,
               "order": first["order"], "order_is_listed": first["order"] == list(range(k)),
               "leftovers": first["leftovers"], "acyclic": not first["leftovers"], "order_calls": len(top["seen"]),
               "identical": identical,
               "calls": {"listed": sum(lst["calls"].values()), "topological": sum(top["calls"].values()),
                         "verifiers_ran": sum(bound["listed"].values())},
               "keys": len(lst["calls"]), "calls_equal": lst["calls"] == top["calls"],
               "remeasured": len(remeasured)}
    return summary, failures, remeasured


def _report(H, rows: List[Dict[str, Any]], selected: Any) -> Dict[str, Any]:
    R = _replica()
    from concordance import derivation as D
    summaries, failures, remeasured = [], [], []
    for row in rows:
        s, f, again = measure_row(D, R, H, row)
        summaries.append(s)
        failures.extend(f)
        remeasured.extend(again)
    n = len(summaries)
    identical = sum(1 for s in summaries if all(s["identical"].values()))
    over_rows = {f["row"] for f in failures if f["kind"] == "over_bound"}
    return {
        "tool": "topo_order", "rows_selected": selected, "orders": list(ORDERS), "compared": list(R._EVALUATION),
        "memo": "0", "stores": "temporary, removed afterwards",
        "means": ("passes is halt.passes, the last pass moving nothing; saving is listed minus topological; the floor "
                  "is 1 where the listed run's first pass moved nothing, else 2, guaranteed for an acyclic row and "
                  "measured for a cyclic one; calls are counted at derivation.verify_step by (domain, spec hash)"),
        "rows": summaries, "failures": failures,
        "totals": {
            "rows": n,
            "passes": {o: sum(s["passes"][o] for s in summaries) for o in ORDERS},
            "differing": [s["name"] for s in summaries if s["saving"]],
            "saving": {"all": sum(s["saving"] for s in summaries),
                       "fast_rows": sum(s["saving"] for s in summaries if not s["slow"]),
                       "slow_rows": sum(s["saving"] for s in summaries if s["slow"])},
            "at_floor": sum(1 for s in summaries if s["at_floor"]),
            "not_at_floor": [s["name"] for s in summaries if not s["at_floor"]],
            "listed_at_floor": sum(1 for s in summaries if s["passes"]["listed"] == s["floor"]),
            "acyclic": sum(1 for s in summaries if s["acyclic"]),
            "cyclic": [s["name"] for s in summaries if not s["acyclic"]],
            "identity": {"compared": n, "identical": identical, "share": (identical / n) if n else None},
            "calls": {"listed": sum(s["calls"]["listed"] for s in summaries),
                      "topological": sum(s["calls"]["topological"] for s in summaries),
                      "equal_rows": sum(1 for s in summaries if s["calls_equal"])},
            "over_bound_rows": len(over_rows),
            "failures": dict(Counter(f["kind"] for f in failures)),
            "remeasured": remeasured,
        },
    }


def run(which: str = "all", names: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """The tier's rows (all, fast or slow; or those named), measured under halt_telemetry's isolation."""
    H = _telemetry()
    with H.isolated():
        from concordance import derivation as D
        D.warm()
        # the rows are built inside the isolation too: building the audit rows runs audit.audit's verifiers
        rows = tier_rows("all" if names else which)
        if names:
            unknown = sorted(set(names) - {r["name"] for r in rows})
            if unknown:
                raise SystemExit(f"no such tier row: {unknown}")
            rows = [r for r in rows if r["name"] in set(names)]
        return _report(H, rows, list(names) if names else which)


def run_rows(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Rows given by the caller ({"name", "steps"[, "slow"]}), measured as tier rows are, under the same isolation."""
    H = _telemetry()
    with H.isolated():
        from concordance import derivation as D
        D.warm()
        return _report(H, list(rows), "given")


def exit_code(rep: Dict[str, Any]) -> int:
    if not rep["totals"]["rows"]:
        return 2
    return 1 if rep["failures"] else 0


def _print(rep: Dict[str, Any]) -> None:
    t = rep["totals"]
    print("TOPOLOGICAL ORDER  (memo off, temporary stores, verifiers warmed, one derivation at a time)")
    if not t["rows"]:
        return
    s, p = t["saving"], t["passes"]
    print(f"rows {t['rows']}  passes listed {p['listed']} -> topological {p['topological']}  saved {s['all']} "
          f"(rows from fast sources {s['fast_rows']}, from slow sources {s['slow_rows']})")
    print(f"at the floor under the topological order: {t['at_floor']} of {t['rows']} (as listed: {t['listed_at_floor']}); "
          f"acyclic {t['acyclic']} (by construction), cyclic {len(t['cyclic'])} (measured)")
    i, c = t["identity"], t["calls"]
    print(f"identity {i['identical']} of {i['compared']} (response except halt.passes, and what _transfer settles)  "
          f"verifier calls listed {c['listed']}, topological {c['topological']}, equal on {c['equal_rows']} rows")
    for r in rep["rows"]:
        if r["saving"]:
            print(f"  {r['name']}: listed {r['passes']['listed']} -> topological {r['passes']['topological']}")
    for name in t["not_at_floor"]:
        print(f"  NOT AT THE FLOOR: {name}")
    for m in t["remeasured"]:
        print(f"  re-measured once after a verifier timeout: {m}")
    for f in rep["failures"]:
        print(f"FAIL {f['row']} [{f['kind']}]: " + json.dumps({k: v for k, v in f.items() if k not in ("row", "kind")}))


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tier-rows", choices=("all", "fast", "slow"), default="all")
    ap.add_argument("--row", action="append", metavar="NAME", help="only this tier row (repeatable)")
    ap.add_argument("--json", metavar="PATH", help="also write the report as JSON")
    a = ap.parse_args(list(argv) if argv is not None else None)
    rep = run(a.tier_rows, a.row)
    _print(rep)
    if a.json:
        Path(a.json).write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding="utf-8")
    code = exit_code(rep)
    if code == 2:
        print("NOTHING MEASURED", file=sys.stderr)
    elif code:
        print(f"\n{len(rep['failures'])} FAILURE(S): " + ", ".join(f"{k}: {n}" for k, n in rep["totals"]["failures"].items()),
              file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
