"""Measurement 1 of the TRM report: how the derivation closure halts (run 2026-11-02-halt-and-order).

For the 1,796 benchmark cases (built by tools/benchmark.py's own case builders, imported, never copied) and for
every tier row once each (tests/fixtures/derivation_tier.py, the one home of every multi-step derivation the tests
use), this prints, and with --json writes:

    passes       the count of derivations by halt.passes (a pass in which nothing moves ends the closure, so a
                 single step takes 2 passes and a chain of k listed in reverse takes k + 1)
    cap_fired    the count whose halt.reason is "cap", and which. The cap FIRES only then; passes equal to the
                 cap (k + 1 for k steps) is the normal single-step case
    by_cause     every INCOMPLETE and every SYSTEM_ERROR by cause, from the fixed list CAUSES: the per-step
                 unsettled values, missing_refs, unresolved_binding, a repeated id, a bridge, a verifier status.
                 A derivation counts once under each cause its trail shows; "none of these" counts one that
                 shows none, which would mean the list is incomplete
    each         every INCOMPLETE and every SYSTEM_ERROR by name (the benchmark case id, the tier row's name)
                 with the causes its trail shows

It exits 1 if the cap fires even once, 2 if a set it was asked to measure came back empty, else 0.

It writes nothing. Before anything is measured it forces CONCORDANCE_MEMO=0 and points the CAS, the ledger and
the memo bucket (which lives under the CAS) at a temporary directory of its own, overriding CONCORDANCE_CAS_DIR,
CONCORDANCE_LEDGER_DIR and CONCORDANCE_DATA_DIR. The data dir becomes a temporary copy of this repository's
data/ less its runtime state (the stores and caches .gitignore lists), so every verifier reads the same tracked
reference data the benchmark reads (number_theory's and statistics' zeta zeros, the fighting grammar, the specs)
and anything a verifier might write lands in the temporary copy. The environment is put back afterwards, so a test
that runs the tool in its own process is left as it was. It calls derivation.warm() first, then measures one
derivation at a time on its own thread. A derivation in which a verifier timed out or was busy is measured once
more, and the second measurement stands either way: re-measured once, never retried until it passes.

    PYTHONPATH=src python tools/halt_telemetry.py [--only benchmark|tier] [--tier-rows all|fast|slow]
                                                  [--benchmark-stride N] [--json PATH]
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import importlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

DATA = ROOT / "data"
BENCHMARK = ROOT / "tools" / "benchmark.py"
FIXTURES = ROOT / "tests" / "fixtures"
# the runtime state .gitignore keeps out of data/ (stores and caches), plus the two files a run can append to
_RUNTIME = frozenset({"cas", "ledger", ".cache", "cache", "receipt_cards.jsonl", "activity.jsonl"})
_ENV = ("CONCORDANCE_MEMO", "CONCORDANCE_DATA_DIR", "CONCORDANCE_CAS_DIR", "CONCORDANCE_LEDGER_DIR")
_UNSETTLED = ("cycle", "rests on a cycle", "cap")
CAUSES = (
    "unsettled: cycle", "unsettled: rests on a cycle", "unsettled: cap", "unsettled: other",
    "missing_refs", "unresolved_binding", "repeated_id", "bridge",
    "status: NOT_APPLICABLE", "status: ERROR", "status: ERROR, timed out or busy", "status: other",
)
_TIMEOUT = ("timed out", "verifier busy")
# the detail derivation.verify_derivation gives a step the pass cap stopped before its check ran: no verifier
# status was read for it, so none is counted (tests/test_halt_telemetry.py pins this against the engine)
NOT_RUN = "not checked:"


@contextlib.contextmanager
def isolated() -> Iterator[str]:
    """Memo off, and the CAS, ledger, memo bucket and data dir in a temporary directory holding a copy of data/'s
    reference files; the environment and the directory are put back and removed afterwards."""
    before = {k: os.environ.get(k) for k in _ENV}
    tmp = tempfile.mkdtemp(prefix="halt-telemetry-")
    top = os.path.normcase(os.path.abspath(str(DATA)))

    def runtime(d: str, names: List[str]) -> List[str]:
        return [n for n in names if n in _RUNTIME] if os.path.normcase(os.path.abspath(d)) == top else []

    try:
        data = os.path.join(tmp, "data")
        shutil.copytree(str(DATA), data, ignore=runtime)
        os.environ.update({"CONCORDANCE_MEMO": "0", "CONCORDANCE_DATA_DIR": data,
                           "CONCORDANCE_CAS_DIR": os.path.join(tmp, "cas"),
                           "CONCORDANCE_LEDGER_DIR": os.path.join(tmp, "ledger")})
        yield tmp
    finally:
        for k, v in before.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(tmp, ignore_errors=True)


def _load_benchmark():
    """tools/benchmark.py, imported (never edited, never copied) for its case builders."""
    spec = importlib.util.spec_from_file_location("_halt_telemetry_benchmark", BENCHMARK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def benchmark_cases() -> List[Tuple[str, bool, Callable[[], Dict[str, Any]]]]:
    """(name, label, run) for every benchmark case, built and run as benchmark.run builds and runs them: the
    derivation-moat claims through its verify(), every other tier through verify_derivation."""
    B = _load_benchmark()
    from concordance import derivation as D
    out: List[Tuple[str, bool, Callable[[], Dict[str, Any]]]] = []
    for label, spec, desc in B.CLAIMS:
        out.append((f"{spec['mode']}:{desc}", bool(label), lambda s=spec: B.verify(copy.deepcopy(s))))
    for mode, cases in (("domain", B._domain_cases()), ("lighthouse", B._lighthouse_cases()),
                        ("check", B._check_cases())):
        for label, steps, desc in cases:
            out.append((desc, bool(label), lambda s=steps: D.verify_derivation(copy.deepcopy(s))))
    return out


def _tier():
    if str(FIXTURES) not in sys.path:
        sys.path.insert(0, str(FIXTURES))
    return importlib.import_module("derivation_tier")


def tier_rows(which: str = "all") -> List[Dict[str, Any]]:
    """The tier's rows: all, those from fast sources, or those from slow-marked sources (the 1,500-step chain)."""
    rows = _tier().rows()
    return [r for r in rows if which == "all" or (which == "slow") == bool(r["slow"])]


def _timed_out(r: Dict[str, Any]) -> bool:
    return any(t.get("status") == "ERROR" and any(m in str(t.get("detail", "")) for m in _TIMEOUT)
               for t in r.get("trail") or [])


def causes(r: Dict[str, Any]) -> List[str]:
    """The causes from CAUSES that a derivation's trail shows, each once. A verifier status counts only where
    the verifier ran: not for a step whose bind stayed unresolved, nor one the cap stopped before its check."""
    seen = set()
    for t in r.get("trail") or []:
        u = t.get("unsettled")
        if u:
            seen.add("unsettled: " + (u if u in _UNSETTLED else "other"))
        for key in ("missing_refs", "unresolved_binding", "repeated_id", "bridge"):
            if t.get(key):
                seen.add(key)
        st = t.get("status")
        ran = not t.get("unresolved_binding") and not str(t.get("detail", "")).startswith(NOT_RUN)
        if ran and st not in ("CONFIRMED", "MISMATCH"):
            if st == "ERROR" and any(m in str(t.get("detail", "")) for m in _TIMEOUT):
                seen.add("status: ERROR, timed out or busy")
            elif st in ("NOT_APPLICABLE", "ERROR"):
                seen.add("status: " + st)
            else:
                seen.add("status: other")
    return [c for c in CAUSES if c in seen]


def measure(named: Sequence[Tuple[str, Callable[[], Dict[str, Any]]]]) -> Tuple[List[Tuple[str, Dict[str, Any]]],
                                                                                 List[Dict[str, Any]]]:
    """Run each derivation once, in order, on this thread; one in which a verifier timed out or was busy is
    measured once more, and that second measurement stands."""
    results, remeasured = [], []
    for name, run in named:
        r = run()
        if _timed_out(r):
            again = run()
            remeasured.append({"name": name, "first": r.get("verdict"), "second": again.get("verdict"),
                               "still_timed_out": _timed_out(again)})
            r = again
        results.append((name, r))
    return results, remeasured


def summarize(results: List[Tuple[str, Dict[str, Any]]]) -> Dict[str, Any]:
    passes = Counter(r["halt"]["passes"] for _, r in results)
    reasons = Counter(r["halt"]["reason"] for _, r in results)
    fired = [n for n, r in results if r["halt"]["reason"] == "cap"]
    verdicts = Counter(r.get("verdict") for _, r in results)
    by_cause: Dict[str, Dict[str, int]] = {}
    each: Dict[str, List[Dict[str, Any]]] = {}
    for kind in ("INCOMPLETE", "SYSTEM_ERROR"):
        row = {"derivations": 0, **{c: 0 for c in CAUSES}, "none of these": 0}
        named: List[Dict[str, Any]] = []
        for name, r in results:
            if r.get("verdict") != kind:
                continue
            row["derivations"] += 1
            found = causes(r)
            for c in found:
                row[c] += 1
            row["none of these"] += not found
            named.append({"name": name, "causes": found})
        by_cause[kind] = row
        each[kind] = named
    return {"derivations": len(results),
            "passes": {str(p): passes[p] for p in sorted(passes)},
            "reasons": dict(sorted(reasons.items())),
            "cap_fired": len(fired), "cap_fired_at": fired,
            "verdicts": dict(sorted(verdicts.items())),
            "by_cause": by_cause,
            "each": each}


def run(only: Optional[str] = None, tier_which: str = "all", stride: int = 1) -> Dict[str, Any]:
    """The report: memo off, stores temporary, verifiers warmed, one derivation at a time."""
    report: Dict[str, Any] = {"tool": "halt_telemetry", "memo": "0", "stores": "temporary, removed afterwards",
                              "means": ("halt.passes counts the passes the closure took, the last one moving nothing; "
                                        "the cap fires only where halt.reason is 'cap'; by_cause counts each "
                                        "INCOMPLETE and SYSTEM_ERROR once under every cause on the fixed list its "
                                        "trail shows")}
    with isolated():
        from concordance import derivation as D
        D.warm()
        if only in (None, "benchmark"):
            t0 = time.monotonic()
            cases = benchmark_cases()
            picked = cases[::max(1, stride)]
            results, again = measure([(n, f) for n, _, f in picked])
            label = {n: lab for n, lab, _ in picked}
            rep = summarize(results)
            rep.update({"of": len(cases), "stride": max(1, stride),
                        "agrees_with_label": sum(1 for n, r in results if (r.get("verdict") == "HOLDS") == label[n]),
                        "remeasured": again, "seconds": round(time.monotonic() - t0, 1)})
            report["benchmark"] = rep
        if only in (None, "tier"):
            t0 = time.monotonic()
            rows = tier_rows(tier_which)
            results, again = measure([(r["name"], (lambda s=r["steps"]: D.verify_derivation(copy.deepcopy(s))))
                                      for r in rows])
            rep = summarize(results)
            above = [n for n, r in results if r["halt"]["passes"] > 2]
            rep.update({"rows": tier_which, "passes_by_row": {n: r["halt"]["passes"] for n, r in results},
                        "above_two_passes": {"count": len(above), "of": len(results),
                                             "share": round(len(above) / len(results), 4) if results else None,
                                             "rows": above},
                        "excluded_not_measured": [{"name": e["name"], "reason": e["reason"]}
                                                  for e in _tier().EXCLUDED] if tier_which != "slow" else [],
                        "remeasured": again, "seconds": round(time.monotonic() - t0, 1)})
            report["tier"] = rep
    return report


def _print(report: Dict[str, Any]) -> None:
    print("HALT TELEMETRY  (memo off, temporary stores, verifiers warmed, one derivation at a time)")
    for key in ("benchmark", "tier"):
        rep = report.get(key)
        if rep is None:
            continue
        head = (f"{rep['derivations']} of {rep['of']} cases (stride {rep['stride']})" if key == "benchmark"
                else f"{rep['derivations']} rows ({rep['rows']})")
        print(f"\n{key.upper()}: {head}, {rep['seconds']} s")
        print("  passes:     " + ", ".join(f"{p}: {c}" for p, c in rep["passes"].items()))
        print("  reasons:    " + ", ".join(f"{k}: {c}" for k, c in rep["reasons"].items()))
        print(f"  CAP FIRED:  {rep['cap_fired']}" + (f"  at {rep['cap_fired_at']}" if rep["cap_fired"] else ""))
        print("  verdicts:   " + ", ".join(f"{k}: {c}" for k, c in rep["verdicts"].items()))
        for kind, row in rep["by_cause"].items():
            shown = ", ".join(f"{c}: {n}" for c, n in row.items() if c != "derivations" and n)
            print(f"  {kind} ({row['derivations']}): {shown or 'none'}")
            for e in rep["each"][kind]:
                print(f"      {e['name']}: {', '.join(e['causes']) or 'none of these'}")
        if key == "benchmark":
            print(f"  agrees with its label: {rep['agrees_with_label']} of {rep['derivations']}")
        else:
            a = rep["above_two_passes"]
            print(f"  more than 2 passes: {a['count']} of {a['of']} ({a['share']:.1%})" if a["of"] else "")
            for e in rep["excluded_not_measured"]:
                print(f"  excluded, not measured: {e['name']} ({e['reason']})")
        for m in rep["remeasured"]:
            print(f"  re-measured once after a verifier timeout: {m}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", choices=("benchmark", "tier"))
    ap.add_argument("--tier-rows", choices=("all", "fast", "slow"), default="all")
    ap.add_argument("--benchmark-stride", type=int, default=1, help="measure every Nth benchmark case (default 1)")
    ap.add_argument("--json", metavar="PATH", help="also write the report as JSON")
    a = ap.parse_args(list(argv) if argv is not None else None)
    report = run(a.only, a.tier_rows, a.benchmark_stride)
    _print(report)
    if a.json:
        Path(a.json).write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    sets = [report[k] for k in ("benchmark", "tier") if k in report]
    if any(s["derivations"] == 0 for s in sets):
        print("NOTHING MEASURED in a requested set", file=sys.stderr)
        return 2
    fired = sum(s["cap_fired"] for s in sets)
    if fired:
        print(f"\nCAP FIRED {fired} time(s): the closure was cut off before it settled", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
