"""Measurement 2 of the TRM report: the closure's result does not depend on the order it visits, or lists, the
steps (run 2026-11-02-halt-and-order).

For every tier row (tests/fixtures/derivation_tier.py) it runs the derivation once as listed, then:

  EVALUATION ORDER, every row. Under every permutation of derivation._evaluation_order (the slot a ranker, or a
  topological order, would fill) when the row has 6 steps or fewer; past 6, under the listed order, its reverse
  and 8 seeded permutations. Each run is compared, by canonical hash, with the listed run on
      evaluation: response   the whole response except halt.passes, the one thing the order may change
      evaluation: settled    what _transfer settles for each step, keyed by its listed position (node["at"],
                             which an evaluation permutation never moves): its effective outcome and the kinds it
                             originates. Read by wrapping _transfer at call time; they are not response fields,
                             and this is the comparison that sees repeated-id and default-id rows
  LISTING, only rows whose every step carries an explicit unique id (a step with no id takes its position as
  its id, and a repeated id names no one step, so permuting those listings would rename steps). Under every
  permutation of the listing up to 6 steps, else the reverse and 8 seeded ones, each compared by step id with
  the listed run on
      listing: verdict, listing: confirmed_steps, listing: outcomes (each step's effective outcome as _transfer
      settles it), listing: originators (the ids originating each kind)

It exits 1 on any mismatch, naming the row, the field and the two orders; 2 if it measured nothing; else 0. A
mismatch where a verifier timed out or was busy is named as a timeout, re-measured once (the re-measurement is
reported), and still fails: never retried until it passes.

It writes nothing: tools/halt_telemetry.py's isolated() (imported, not copied) forces CONCORDANCE_MEMO=0 and puts
the CAS, ledger, memo bucket and data dir in a temporary directory holding a copy of data/'s reference files. It
calls derivation.warm() first and runs one derivation at a time on its own thread.

    PYTHONPATH=src python tools/order_replica.py [--tier-rows all|fast|slow] [--row NAME ...] [--seed N]
                                                 [--max-steps N] [--json PATH]

--max-steps exists for the suite's budget: a 6-step row is 720 evaluation orders and 720 listings, about 7.5 s on
the development laptop, nearly all of it the verifiers themselves (memo off), so tests/test_order_replica.py runs
the rows of up to 5 steps in the fast suite and the whole tier behind -m slow. The tool's own run is the whole tier.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import itertools
import json
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

FIELDS = ("evaluation: response", "evaluation: settled",
          "listing: verdict", "listing: confirmed_steps", "listing: outcomes", "listing: originators")
_EVALUATION, _LISTING = FIELDS[:2], FIELDS[2:]
_KEPT = 20                  # mismatch records kept per row; the count is always whole


def _telemetry():
    """tools/halt_telemetry.py, imported for its isolated() environment and its tier loader."""
    spec = importlib.util.spec_from_file_location("_order_replica_halt_telemetry", ROOT / "tools" / "halt_telemetry.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def tier_rows(which: str = "all") -> List[Dict[str, Any]]:
    return _telemetry().tier_rows(which)


def unique_ids(steps: Sequence[Dict[str, Any]]) -> bool:
    """Every step carries an explicit id, and no two the same: only then does a listing permutation keep the
    derivation the same derivation."""
    ids = [s.get("id") for s in steps]
    return all(ids) and len({str(i) for i in ids}) == len(ids)


def _skipped(steps: Sequence[Dict[str, Any]]) -> Optional[str]:
    if unique_ids(steps):
        return None
    return "a step with no id" if not all(s.get("id") for s in steps) else "a repeated id"


def orders(k: int, seed: int, name: str) -> List[Tuple[int, ...]]:
    """Every permutation of k positions up to 6, else the listed order, the reverse and 8 seeded permutations."""
    if k <= 6:
        return list(itertools.permutations(range(k)))
    rng = random.Random(f"{seed}:{name}")
    out = [tuple(range(k)), tuple(reversed(range(k)))]
    seeded: List[Tuple[int, ...]] = []
    while len(seeded) < 8:
        p = list(range(k))
        rng.shuffle(p)
        t = tuple(p)
        if t not in out and t not in seeded:
            seeded.append(t)
    return out + seeded


def _plain(obj: Any) -> Any:
    """The same value in plain JSON types: a verifier may return a numpy scalar (a statistics band's `inside` is a
    numpy bool), which the one canonical form cannot serialise; it becomes its Python value. Nothing else changes,
    and anything still not JSON raises."""
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    if not isinstance(obj, (str, bytes)) and hasattr(obj, "item") and callable(obj.item) and type(obj).__module__ == "numpy":
        return obj.item()
    return obj


def _hash(obj: Any) -> str:
    from concordance.validate import canonical_json_bytes
    return hashlib.sha256(canonical_json_bytes(_plain(obj))).hexdigest()


def _kind(v) -> str:
    return "BROKEN" if v.r else "CONFIRMED" if v.p else "ERROR" if "error" in v.why else "GAP"


def _run(D, steps, order: Optional[Sequence[int]] = None):
    """One verification, with _transfer wrapped (at call time, so a rule already patched in is the one read) to
    keep each step's settling return by listed position, and the evaluation order injected when given."""
    real_t, real_o = D._transfer, D._evaluation_order
    settled: Dict[int, Tuple[str, Any]] = {}

    def transfer(node, own, deps, halt=""):
        out = real_t(node, own, deps, halt)
        if out is not None:
            settled[node["at"]] = (node["id"], out)
        return out

    D._transfer = transfer
    if order is not None:
        D._evaluation_order = lambda k, o=tuple(order): list(o)
    try:
        r = D.verify_derivation(copy.deepcopy(list(steps)))
    finally:
        D._transfer, D._evaluation_order = real_t, real_o
    return r, settled


def _evaluation_fields(r, settled) -> Dict[str, str]:
    resp = copy.deepcopy(r)
    resp.get("halt", {}).pop("passes", None)
    by_at = {str(at): {"id": sid, "outcome": _kind(v), "why": sorted(v.why),
                       "originates": sorted(v.why) if origin else []}
             for at, (sid, (v, origin, _)) in sorted(settled.items())}
    return {"evaluation: response": _hash(resp), "evaluation: settled": _hash(by_at)}


def _listing_fields(r, settled) -> Dict[str, str]:
    outcomes = {sid: {"outcome": _kind(v), "why": sorted(v.why)} for sid, (v, _, _) in settled.values()}
    originators: Dict[str, List[str]] = {}
    for sid, (v, origin, _) in settled.values():
        if origin:
            for kind in v.why:
                originators.setdefault(kind, []).append(sid)
    return {"listing: verdict": _hash(r.get("verdict")), "listing: confirmed_steps": _hash(r.get("confirmed_steps")),
            "listing: outcomes": _hash(outcomes),
            "listing: originators": _hash({k: sorted(v) for k, v in originators.items()})}


def replicate_row(D, H, row: Dict[str, Any], seed: int) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    steps, name = row["steps"], row["name"]
    k = len(steps)
    base_r, base_s = _run(D, steps)
    if H._timed_out(base_r):
        base_r, base_s = _run(D, steps)               # the baseline is measured once more, never until it passes
    listed = list(range(k))
    found: List[Dict[str, Any]] = []
    tally = {"compared": 0, "identical": 0}

    def compare(branch, names, base_f, this_f, this_r, order, again):
        tally["compared"] += 1
        diff = [f for f in names if this_f[f] != base_f[f]]
        if not diff:
            tally["identical"] += 1
            return
        timeout = H._timed_out(this_r) or H._timed_out(base_r)
        m = {"row": name, "branch": branch, "fields": diff, "orders": [listed, list(order)],
             "verdicts": [base_r.get("verdict"), this_r.get("verdict")], "timeout": timeout, "remeasured": None}
        if timeout:
            m["remeasured"] = {"identical": again() == base_f}
        found.append(m)

    base_e = _evaluation_fields(base_r, base_s)
    evals = orders(k, seed, name)
    for order in evals:
        r, s = _run(D, steps, order)
        compare("evaluation", _EVALUATION, base_e, _evaluation_fields(r, s), r, order,
                lambda o=order: _evaluation_fields(*_run(D, steps, o)))
    skipped = _skipped(steps)
    listings: List[Tuple[int, ...]] = []
    if skipped is None:
        base_l = _listing_fields(base_r, base_s)
        listings = orders(k, seed + 1, name)
        for perm in listings:
            permuted = [steps[i] for i in perm]
            r, s = _run(D, permuted)
            compare("listing", _LISTING, base_l, _listing_fields(r, s), r, perm,
                    lambda p=permuted: _listing_fields(*_run(D, p)))
    summary = {"name": name, "steps": k, "verdict": base_r.get("verdict"), "evaluation_orders": len(evals),
               "listings": len(listings), "listing_skipped": skipped, "settled_positions": len(base_s),
               "compared": tally["compared"], "identical": tally["identical"], "mismatches": len(found)}
    return summary, found[:_KEPT]


def run(which: str = "all", names: Optional[Sequence[str]] = None, seed: int = 0,
        max_steps: Optional[int] = None) -> Dict[str, Any]:
    H = _telemetry()
    summaries, mismatches, left_out = [], [], []
    with H.isolated():
        # the rows are built inside the isolation too: building the audit rows runs audit.audit's verifiers
        rows = H.tier_rows("all" if names else which)
        if names:
            unknown = sorted(set(names) - {r["name"] for r in rows})
            if unknown:
                raise SystemExit(f"no such tier row: {unknown}")
            rows = [r for r in rows if r["name"] in set(names)]
        if max_steps is not None:
            left_out = [{"name": r["name"], "steps": len(r["steps"]), "why": f"more than {max_steps} steps (--max-steps)"}
                        for r in rows if len(r["steps"]) > max_steps]
            rows = [r for r in rows if len(r["steps"]) <= max_steps]
        from concordance import derivation as D
        D.warm()
        for row in rows:
            s, m = replicate_row(D, H, row, seed)
            summaries.append(s)
            mismatches.extend(m)
    compared = sum(s["compared"] for s in summaries)
    identical = sum(s["identical"] for s in summaries)
    return {"tool": "order_replica", "seed": seed, "rows_selected": list(names) if names else which,
            "fields": list(FIELDS), "memo": "0", "stores": "temporary, removed afterwards",
            "rows": summaries, "left_out": left_out, "mismatches": mismatches,
            "totals": {"rows": len(summaries), "evaluation_orders": sum(s["evaluation_orders"] for s in summaries),
                       "listings": sum(s["listings"] for s in summaries), "compared": compared,
                       "identical": identical, "identity": (identical / compared) if compared else None,
                       "mismatches": sum(s["mismatches"] for s in summaries),
                       "mismatched_fields": dict(Counter(f for m in mismatches for f in m["fields"]))}}


def _print(rep: Dict[str, Any]) -> None:
    t = rep["totals"]
    print("ORDER REPLICA  (memo off, temporary stores, verifiers warmed, one derivation at a time)")
    print(f"rows {t['rows']}  evaluation orders {t['evaluation_orders']}  listings {t['listings']}  "
          f"compared {t['compared']}  identical {t['identical']}  "
          + (f"identity {t['identity']:.2%}" if t["identity"] is not None else "identity n/a"))
    for r in rep["left_out"]:
        print(f"left out: {r['name']} ({r['why']})")
    skipped = Counter(r["listing_skipped"] for r in rep["rows"] if r["listing_skipped"])
    if skipped:
        print("listing branch skipped (evaluation branch still run): "
              + ", ".join(f"{why}: {n} row(s)" for why, n in sorted(skipped.items())))
    for m in rep["mismatches"]:
        print(f"MISMATCH {m['row']} [{m['branch']}] {', '.join(m['fields'])}: order {m['orders'][0]} vs "
              f"{m['orders'][1]} (verdicts {m['verdicts'][0]} / {m['verdicts'][1]})"
              + (f"; a verifier timed out, re-measured once: {m['remeasured']}" if m["timeout"] else ""))
    if t["mismatches"] > len(rep["mismatches"]):
        print(f"... {t['mismatches'] - len(rep['mismatches'])} more mismatch(es) counted, not listed")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tier-rows", choices=("all", "fast", "slow"), default="all")
    ap.add_argument("--row", action="append", metavar="NAME", help="only this tier row (repeatable)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-steps", type=int, metavar="N", help="leave out (and name) rows of more than N steps")
    ap.add_argument("--json", metavar="PATH", help="also write the report as JSON")
    a = ap.parse_args(list(argv) if argv is not None else None)
    rep = run(a.tier_rows, a.row, a.seed, a.max_steps)
    _print(rep)
    if a.json:
        Path(a.json).write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding="utf-8")
    if not rep["totals"]["compared"]:
        print("NOTHING MEASURED", file=sys.stderr)
        return 2
    if rep["totals"]["mismatches"]:
        print(f"\n{rep['totals']['mismatches']} MISMATCH(ES): the result depends on the order", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
