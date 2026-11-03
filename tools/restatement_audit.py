"""Measurement 4 of the TRM report: a restatement-invariance audit of the verifiers and the closure (run
2026-11-03-restatement-audit, step audit-core). An audit, never a vote: a claim restated in a way its own oracle
shows keeps its meaning (tools/restate.py, R1-R5) must get the same verdict, and a change is a defect, named.

It restates, with every restatement that applies, each of the 1,796 benchmark cases (built by tools/benchmark.py's
own case builders, imported, never copied) and runs it through the path the benchmark uses: a derivation-moat claim
through benchmark.verify, every other case through derivation.verify_derivation. It restates each derivation-tier
row (tests/fixtures/derivation_tier.py) and runs it through each path its source asserts on (derivation_tier.run:
verify_derivation, compose with seal=False, the MCP verify tool with seal=False given the steps or the document);
a row no source asserts a verdict on is measured on the derivation path, where every path's listing arrives. R5
renames step ids, which verifiers never see, so it runs on tier rows only. A row built from text by audit.audit is
reached only by R5, on the path its built derivation is passed; audit.audit itself takes the text, and a packet
restatement cannot pass through it, so every restatement is declined there with that reason.

Each restated run is compared with the run of the case as given, by canonical form (validate.canonical_json_bytes):
the verdict; each step's status, by its position in the listing; broken_at, gap_at and error_at, the given run's
pointer read through R5's id map; each step's refutation check names (attempted, survived, counterexamples,
errored, not_applicable); and the response's read. A path's response that does not carry a field is compared on the
fields it does carry (compose's tree carries the verdict and each step's status). Each step's bands and margin are
compared too, and a change there is a named change of kind "band": under a side swap the actual and the claimed
values trade places, so band values may move while the claim does not.

    flip            the verdict went from HOLDS to BROKEN or from BROKEN to HOLDS
    false_to_holds  a verdict other than HOLDS became HOLDS on a case labelled false, or on a tier row whose source
                    asserts a verdict other than HOLDS on that path: a false positive reached by restating the claim
These two are the exit-1 changes. Every other change is a want: first, a verdict that became HOLDS on a tier row no
source asserts a verdict on (its truth is unknown), then the rest. KNOWN lists the exit-1 changes today's engine
shows, each with the run filed to fix it; the tool still exits 1 while any is open, and tests/test_restatement_audit.py
requires the measured exit-1 set to equal KNOWN exactly, so a new one fails the suite and a fixed one must be removed.

It reports every change and every decline by case, the counts by restatement and by reason, and a per-domain
coverage table of the benchmark (restatements applied and declined per domain), naming the domains only R1 reaches.
It exits 1 on any exit-1 change, 2 if it compared nothing, else 0.

It writes nothing: tools/halt_telemetry.py's isolated() (imported, not copied) forces CONCORDANCE_MEMO=0 and puts
the CAS, ledger, memo bucket and data dir in a temporary directory holding a copy of data/'s reference files. It
calls derivation.warm() first and runs one derivation at a time. A run in which a verifier timed out or was busy is
measured once more, and the second measurement stands either way (it is reported, and a change that still rests on a
timed-out run is marked so). Nothing in src/ reads this tool (tests/test_restate.py pins that).

    PYTHONPATH=src python tools/restatement_audit.py [--benchmark all|per-domain|none] [--tier all|fast|none]
                                                    [--case NAME ...] [--row NAME ...] [--json PATH]
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import sys
import time
from collections import Counter, OrderedDict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

KEYS = ("R1", "R2", "R3", "R4", "R5")
POINTERS = ("broken_at", "gap_at", "error_at")
REFUTATIONS = ("attempted", "survived", "counterexamples", "errored", "not_applicable")
EXIT_ONE = ("flip", "false_to_holds")
# The exit-1 changes today's engine shows, each with its filed fixing run and the lead's hold:
# (population, case, path, restatement) -> {"run": ..., "hold": ...}. Measured at the step's base: none.
KNOWN: Dict[Tuple[str, str, str, str], Dict[str, str]] = {}

def known_problems(known: Dict[Any, Any]) -> List[str]:
    """What is wrong with a KNOWN table: a key that is not (population, case, path, restatement), or an entry that
    does not name its fixing run and the lead's hold."""
    out = []
    for key, entry in known.items():
        if not (isinstance(key, tuple) and len(key) == 4 and key[0] in ("benchmark", "tier") and key[3] in KEYS
                and all(isinstance(k, str) and k for k in key)):
            out.append(f"{key!r}: not (population, case, path, restatement)")
        elif not (isinstance(entry, dict) and entry.get("run") and entry.get("hold")):
            out.append(f"{key!r}: names no fixing run and hold")
    return out


AUDIT_PATH = ("audit.audit takes the text, and a packet restatement cannot pass through it; the row's built "
              "derivation is audited on the path that passes it")
TEXT_ROW = "a row built from text by audit.audit is reached only by R5, on the path its built derivation is passed"
CLOSURE_ONLY = "R5 renames step ids, which verifiers never see: a closure audit, run on derivation-tier rows only"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _telemetry():
    """tools/halt_telemetry.py, imported for isolated(), its benchmark and tier loaders and its timeout markers."""
    return _load("_restatement_audit_halt_telemetry", ROOT / "tools" / "halt_telemetry.py")


def _restate():
    return _load("_restatement_audit_restate", ROOT / "tools" / "restate.py")


def _canon(obj: Any) -> bytes:
    from concordance.validate import canonical_json_bytes
    return canonical_json_bytes(obj)


def _jsonable(obj: Any) -> Any:
    """obj as plain JSON values: a numpy scalar a verifier leaves in its band data becomes its Python value, and
    anything else JSON cannot hold becomes its repr. Both runs of a comparison pass through it alike."""
    def default(o: Any) -> Any:
        return o.item() if hasattr(o, "item") and callable(o.item) else repr(o)
    return json.loads(json.dumps(obj, default=default))


# ── what a run is compared on ─────────────────────────────────────────────────────────────────────────────────
def _names(xs: Any) -> List[str]:
    return sorted(str(x.get("check") if isinstance(x, dict) else x) for x in (xs or []))


def signature(resp: Dict[str, Any]) -> Dict[str, Any]:
    """The compared fields of one response: the verdict, each step's status, refutation check names and bands,
    the pointers and the read, each only where the path's response carries it."""
    sig: Dict[str, Any] = {"verdict": resp.get("verdict")}
    steps = resp.get("trail") if isinstance(resp.get("trail"), list) else (
        resp.get("steps") if isinstance(resp.get("steps"), list) else [])
    out = []
    for t in steps:
        ref = t.get("refutations") if isinstance(t, dict) else None
        out.append({"status": t.get("status") if isinstance(t, dict) else None,
                    "refutations": {k: _names(ref.get(k)) for k in REFUTATIONS} if isinstance(ref, dict) else None,
                    "bands": {"bands": ref.get("bands"), "margin": ref.get("margin")} if isinstance(ref, dict) else None})
    sig["steps"] = out
    for k in POINTERS:
        if k in resp:
            sig[k] = resp[k]
    if "read" in resp:
        sig["read"] = resp["read"]
    return _jsonable(sig)


def compare(before: Dict[str, Any], after: Dict[str, Any], id_map: Optional[Dict[str, str]] = None
            ) -> List[Dict[str, Any]]:
    """Every compared field that differs between two signatures, by canonical form. A pointer of the given run is
    read through id_map (R5's) before it is compared."""
    diffs: List[Dict[str, Any]] = []

    def differ(a: Any, b: Any) -> bool:
        return _canon(a) != _canon(b)

    if differ(before.get("verdict"), after.get("verdict")):
        diffs.append({"field": "verdict", "before": before.get("verdict"), "after": after.get("verdict")})
    sb, sa = before.get("steps") or [], after.get("steps") or []
    if len(sb) != len(sa):
        diffs.append({"field": "steps", "before": len(sb), "after": len(sa)})
    for i, (b, a) in enumerate(zip(sb, sa)):
        for f in ("status", "refutations", "bands"):
            if differ(b.get(f), a.get(f)):
                diffs.append({"field": "band" if f == "bands" else f, "step": i, "before": b.get(f), "after": a.get(f)})
    for k in POINTERS:
        if (k in before) != (k in after):
            diffs.append({"field": k, "before": before.get(k), "after": after.get(k)})
        elif k in before:
            p = before[k]
            mapped = (id_map or {}).get(p, p) if p is not None else None
            if differ(mapped, after[k]):
                diffs.append({"field": k, "before": p, "read_through_map": mapped, "after": after[k]})
    if ("read" in before) != ("read" in after) or ("read" in before and differ(before["read"], after["read"])):
        diffs.append({"field": "read", "before": before.get("read"), "after": after.get("read")})
    return diffs


def _asserts_not_holds(asserts: Sequence[Dict[str, Any]], path: str) -> Optional[bool]:
    """True when a source asserts a verdict other than HOLDS on this path, False when one asserts HOLDS or allows
    it, None when no source asserts a verdict on it."""
    mine = [a.get("verdict") for a in asserts if a.get("path") == path]
    if not mine:
        return None
    for v in mine:
        if v == "HOLDS" or (isinstance(v, dict) and "in" in v and "HOLDS" in v["in"]):
            return False
    return True


def classify(diffs: Sequence[Dict[str, Any]], label: Optional[bool], asserts_not_holds: Optional[bool],
             tier: bool) -> List[str]:
    """The kinds of one restated run's change: flip and false_to_holds (the exit-1 kinds), into_holds_unasserted
    (a verdict became HOLDS where no source asserts one), and one kind per differing field."""
    kinds = []
    v = next((d for d in diffs if d["field"] == "verdict"), None)
    if v:
        b, a = v["before"], v["after"]
        if {b, a} == {"HOLDS", "BROKEN"}:
            kinds.append("flip")
        if a == "HOLDS" and b != "HOLDS":
            wrong = (label is False) if not tier else (asserts_not_holds is True)
            if wrong:
                kinds.append("false_to_holds")
            elif tier and asserts_not_holds is None:
                kinds.append("into_holds_unasserted")
    for d in diffs:
        if d["field"] not in kinds:
            kinds.append(d["field"])
    return kinds


def _order(change: Dict[str, Any]) -> Tuple[int, str]:
    rank = 0 if change["exit_one"] else 1 if "into_holds_unasserted" in change["kinds"] else 2
    return rank, json.dumps([change["population"], change["case"], change["path"], change["restatement"]])


# ── the populations ───────────────────────────────────────────────────────────────────────────────────────────
def benchmark_population(H, which: str = "all", names: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    """Each benchmark case as the benchmark builds and runs it: (name, label, domain, the subject R1-R4 restate,
    and the run of a subject). A derivation-moat claim is restated as the one step derivation.verify makes of it,
    and only its spec is passed back to benchmark.verify."""
    B = H._load_benchmark()
    from concordance import derivation as D
    out: List[Dict[str, Any]] = []
    for label, spec, desc in B.CLAIMS:
        out.append({"population": "benchmark", "case": f"{spec['mode']}:{desc}", "label": bool(label),
                    "domains": ["mathematics"], "path": "benchmark.verify",
                    "subject": [{"id": "b", "domain": "mathematics", "spec": spec}],
                    "passes": lambda s: s[0]["spec"], "run": lambda s: B.verify(copy.deepcopy(s[0]["spec"]))})
    for cases in (B._domain_cases(), B._lighthouse_cases(), B._check_cases()):
        for label, steps, desc in cases:
            out.append({"population": "benchmark", "case": desc, "label": bool(label),
                        "domains": [str(s.get("domain")) for s in steps], "path": "verify_derivation",
                        "subject": steps, "passes": lambda s: s, "run": lambda s: D.verify_derivation(copy.deepcopy(s))})
    seen: Counter = Counter()
    for c in out:                      # a few names repeat (check_goldens.jsonl): the second is "<name> #2", and so on
        seen[c["case"]] += 1
        if seen[c["case"]] > 1:
            c["case"] = f"{c['case']} #{seen[c['case']]}"
    if names is not None:
        wanted = set(names)
        out = [c for c in out if c["case"] in wanted]
    elif which == "per-domain":
        seen, picked = set(), []
        for c in out:
            if c["domains"][0] not in seen:
                seen.add(c["domains"][0])
                picked.append(c)
        out = picked
    elif which == "none":
        out = []
    return out


def tier_population(H, which: str = "all", names: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    """Each tier row on each path its source asserts on (the derivation path where none does): its subject (the
    steps, or the document on the document paths) and the run of a subject through that path."""
    T = H._tier()
    rows = T.rows()
    if names is not None:
        wanted = set(names)
        rows = [r for r in rows if r["name"] in wanted]
    elif which == "none":
        rows = []
    elif which != "all":
        rows = [r for r in rows if (which == "slow") == bool(r["slow"])]
    out: List[Dict[str, Any]] = []
    for r in rows:
        paths = list(dict.fromkeys(a["path"] for a in r["asserts"])) or ["derivation"]
        for path in paths:
            doc = path in ("compose", "mcp-document")
            subject = r["doc"] if doc else (r["text"] if path == "audit" else r["steps"])
            out.append({"population": "tier", "case": r["name"], "label": None, "path": path,
                        "domains": list(dict.fromkeys(str(s.get("domain")) for s in r["steps"])),
                        "asserts_not_holds": _asserts_not_holds(r["asserts"], path),
                        "measurement_only": r["measurement_only"], "text": bool(r["text"]), "subject": subject,
                        "passes": lambda s: s, "run": _tier_runner(T, r, path)})
    return out


def _tier_runner(T, row: Dict[str, Any], path: str) -> Callable[[Any], Dict[str, Any]]:
    def go(subject: Any) -> Dict[str, Any]:
        given = dict(row)
        if path in ("compose", "mcp-document"):
            given["doc"] = subject
        elif path != "audit":
            given["steps"] = subject
        return T.run(given, path)
    return go


def _decline_reason(R, case: Dict[str, Any], key: str) -> Optional[str]:
    """The audit's own reasons a restatement does not apply to a case on its path, before the restatement is tried."""
    if case["path"] == "audit":
        return AUDIT_PATH
    if key == "R5" and case["population"] == "benchmark":
        return CLOSURE_ONLY
    if case.get("text") and key != "R5":
        return TEXT_ROW
    return None


def _strip(reason: str) -> str:
    """A restatement's reason without the step numbers it names, for counting by reason."""
    import re
    return re.sub(r" \(steps? [0-9, .]+\)", "", reason)


# ── measuring ─────────────────────────────────────────────────────────────────────────────────────────────────
def _timed_out(H, r: Dict[str, Any]) -> bool:
    steps = r.get("trail") if isinstance(r.get("trail"), list) else r.get("steps") or []
    return any(isinstance(t, dict) and t.get("status") == "ERROR"
               and any(m in str(t.get("detail", "")) for m in H._TIMEOUT) for t in steps)


def _measured(H, run: Callable[[Any], Dict[str, Any]], subject: Any, name: str,
              remeasured: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], bool]:
    """One run; a run in which a verifier timed out or was busy is measured once more, and the second stands."""
    r = run(subject)
    if _timed_out(H, r):
        again = run(subject)
        remeasured.append({"run": name, "first": r.get("verdict"), "second": again.get("verdict"),
                           "still_timed_out": _timed_out(H, again)})
        r = again
    return r, _timed_out(H, r)


def audit_cases(H, R, cases: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Every applicable restatement of every case, each compared with the case as given."""
    changes, declines, remeasured = [], [], []
    applied: Counter = Counter()
    for c in cases:
        name = f"{c['population']}:{c['case']}:{c['path']}"
        base, base_timeout = None, False
        for key in KEYS:
            why = _decline_reason(R, c, key)
            o = None
            if why is None:
                o = R.restate(key, c["subject"])
                if not o.applied:
                    why = o.reason
                elif json.dumps(c["passes"](o.after)) == json.dumps(c["passes"](c["subject"])):
                    why = "the restatement changes nothing the path passes"
            if why is not None:
                declines.append({"population": c["population"], "case": c["case"], "path": c["path"],
                                 "domains": c["domains"], "restatement": key, "reason": why})
                continue
            if base is None:
                base, base_timeout = _measured(H, c["run"], c["subject"], name, remeasured)
            after, after_timeout = _measured(H, c["run"], o.after, f"{name}:{key}", remeasured)
            applied[(c["population"], key)] += 1
            id_map = o.mapping if key == "R5" else None
            diffs = compare(signature(base), signature(after), id_map)
            if not diffs:
                continue
            kinds = classify(diffs, c.get("label"), c.get("asserts_not_holds"), c["population"] == "tier")
            changes.append({"population": c["population"], "case": c["case"], "path": c["path"],
                            "domains": c["domains"], "restatement": key, "kinds": kinds,
                            "exit_one": any(k in EXIT_ONE for k in kinds), "label": c.get("label"),
                            "asserts_not_holds": c.get("asserts_not_holds"),
                            "timed_out": base_timeout or after_timeout, "diffs": diffs})
    changes.sort(key=_order)
    return {"changes": changes, "declines": declines, "remeasured": remeasured, "applied": applied}


def _coverage(cases: Sequence[Dict[str, Any]], declines: Sequence[Dict[str, Any]], applied_keys: Dict[str, set]
              ) -> Dict[str, Any]:
    """Per benchmark domain: each restatement's applied and declined counts, and the domains only R1 reaches."""
    table: Dict[str, Dict[str, Dict[str, int]]] = {}
    for c in cases:
        if c["population"] != "benchmark":
            continue
        dom = c["domains"][0]
        row = table.setdefault(dom, {k: {"applied": 0, "declined": 0} for k in KEYS})
        for k in KEYS:
            row[k]["applied" if k in applied_keys.get(f"{c['case']}|{c['path']}", set()) else "declined"] += 1
    only_r1 = sorted(d for d, row in table.items()
                     if row["R1"]["applied"] and not any(row[k]["applied"] for k in ("R2", "R3", "R4", "R5")))
    return {"by_domain": OrderedDict(sorted(table.items())), "reached_only_by_R1": only_r1}


def run(benchmark: str = "all", tier: str = "all", cases: Optional[Sequence[str]] = None,
        rows: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """The report. benchmark: all, per-domain (the first case of each domain, in benchmark order) or none; tier:
    all, fast (rows from fast sources), slow or none; cases / rows: only these, by name."""
    H, R = _telemetry(), _restate()
    report: Dict[str, Any] = {"tool": "restatement_audit", "memo": "0", "stores": "temporary, removed afterwards",
                              "known": [{"population": k[0], "case": k[1], "path": k[2], "restatement": k[3], **v}
                                        for k, v in sorted(KNOWN.items())]}
    with H.isolated():
        from concordance import derivation as D
        D.warm()
        seconds = {}
        populations = []
        t0 = time.monotonic()
        total = len(benchmark_population(H, "all"))
        bench = benchmark_population(H, benchmark, cases) if (cases is not None or rows is None) else []
        if bench:
            populations.append(("benchmark", bench))
        tier_cases = tier_population(H, tier, rows) if (rows is not None or cases is None) else []
        if tier_cases:
            populations.append(("tier", tier_cases))
        everything: List[Dict[str, Any]] = []
        results: Dict[str, Any] = {"changes": [], "declines": [], "remeasured": [], "applied": Counter()}
        for label, pop in populations:
            t1 = time.monotonic()
            res = audit_cases(H, R, pop)
            seconds[label] = round(time.monotonic() - t1, 1)
            for k in ("changes", "declines", "remeasured"):
                results[k] += res[k]
            results["applied"] += res["applied"]
            everything += pop
        seconds["all"] = round(time.monotonic() - t0, 1)
    results["changes"].sort(key=_order)
    declined_keys: Dict[str, set] = {}
    for d in results["declines"]:
        declined_keys.setdefault(f"{d['case']}|{d['path']}", set()).add(d["restatement"])
    applied_keys = {f"{c['case']}|{c['path']}": set(KEYS) - declined_keys.get(f"{c['case']}|{c['path']}", set())
                    for c in everything}
    by_key: Dict[str, Dict[str, Any]] = {}
    for k in KEYS:
        reasons = Counter(_strip(d["reason"]) for d in results["declines"] if d["restatement"] == k)
        by_key[k] = {"applied": sum(n for (p, kk), n in results["applied"].items() if kk == k),
                     "declined": sum(reasons.values()),
                     "changes": sum(1 for c in results["changes"] if c["restatement"] == k),
                     "declined_by_reason": dict(reasons.most_common())}
    exit_one = [_key(c) for c in results["changes"] if c["exit_one"]]
    measured = {(c["population"], c["case"], c["path"]) for c in everything}
    known_here = sorted(k for k in KNOWN if k[:3] in measured)       # the KNOWN entries this run's population holds
    report.update({
        "populations": {p: {"cases": len(pop), "of": (total if p == "benchmark" else None)} for p, pop in populations},
        "selection": {"benchmark": benchmark if cases is None else "named", "tier": tier if rows is None else "named"},
        "compared": sum(results["applied"].values()),
        "by_restatement": by_key,
        "coverage": _coverage(everything, results["declines"], applied_keys),
        "tier_coverage": _tier_coverage(everything, applied_keys),
        "exit_one": [list(k) for k in exit_one],
        "exit_one_not_known": [list(k) for k in exit_one if k not in KNOWN],
        "known_in_population": [list(k) for k in known_here],
        "known_problems": known_problems(KNOWN),
        "known_not_measured": [list(k) for k in known_here if k not in set(exit_one)],
        "changes": results["changes"],
        "declines": results["declines"],
        "remeasured": results["remeasured"],
        "seconds": seconds,
    })
    return report


def _key(c: Dict[str, Any]) -> Tuple[str, str, str, str]:
    return (c["population"], c["case"], c["path"], c["restatement"])


def _tier_coverage(everything: Sequence[Dict[str, Any]], applied_keys: Dict[str, set]) -> Dict[str, Any]:
    out: Dict[str, Dict[str, int]] = {}
    for c in everything:
        if c["population"] != "tier":
            continue
        row = out.setdefault(c["path"], {"rows": 0, **{k: 0 for k in KEYS}})
        row["rows"] += 1
        for k in applied_keys.get(f"{c['case']}|{c['path']}", set()):
            row[k] += 1
    return dict(sorted(out.items()))


def exit_code(report: Dict[str, Any]) -> int:
    if not report.get("compared"):
        return 2
    return 1 if report.get("exit_one") else 0


# ── output ────────────────────────────────────────────────────────────────────────────────────────────────────
def _print(rep: Dict[str, Any]) -> None:
    print("RESTATEMENT AUDIT  (memo off, temporary stores, verifiers warmed, one derivation at a time)")
    for p, n in rep["populations"].items():
        print(f"  {p}: {n['cases']} " + (f"of {n['of']} cases" if n["of"] else "row-paths")
              + f" ({rep['selection'][p]}), {rep['seconds'].get(p)} s")
    print(f"  restated runs compared: {rep['compared']}")
    print("\nBY RESTATEMENT")
    for k, row in rep["by_restatement"].items():
        print(f"  {k}: applied {row['applied']}, declined {row['declined']}, changed {row['changes']}")
        for reason, n in list(row["declined_by_reason"].items())[:6]:
            print(f"      declined {n}: {reason[:150]}")
    cov = rep["coverage"]
    if cov["by_domain"]:
        print("\nCOVERAGE BY BENCHMARK DOMAIN (applied/declined)")
        for dom, row in cov["by_domain"].items():
            print(f"  {dom:28s} " + "  ".join(f"{k} {row[k]['applied']}/{row[k]['declined']}" for k in KEYS))
        print(f"  reached only by R1 ({len(cov['reached_only_by_R1'])}): {', '.join(cov['reached_only_by_R1'])}")
    if rep["tier_coverage"]:
        print("\nTIER COVERAGE BY PATH (row-paths, then applied per restatement)")
        for path, row in rep["tier_coverage"].items():
            print(f"  {path:14s} {row['rows']:3d}  " + "  ".join(f"{k} {row[k]}" for k in KEYS))
    print(f"\nCHANGES: {len(rep['changes'])} (exit-1: {len(rep['exit_one'])}, of them known: "
          f"{len(rep['exit_one']) - len(rep['exit_one_not_known'])})")
    for c in rep["changes"]:
        flag = "EXIT-1 " if c["exit_one"] else ""
        t = " (rests on a timed-out run)" if c["timed_out"] else ""
        print(f"  {flag}{c['restatement']} {c['population']}:{c['case']} [{c['path']}] {', '.join(c['kinds'])}{t}")
        for d in c["diffs"][:4]:
            print(f"      {d['field']}{' step ' + str(d['step']) if 'step' in d else ''}: "
                  f"{json.dumps(d.get('before'))[:90]} -> {json.dumps(d.get('after'))[:90]}")
    for k in rep["known_not_measured"]:
        print(f"  KNOWN but not measured (fixed? remove it from KNOWN): {k}")
    for m in rep["remeasured"]:
        print(f"  re-measured once after a verifier timeout: {m}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--benchmark", choices=("all", "per-domain", "none"), default="all")
    ap.add_argument("--tier", choices=("all", "fast", "slow", "none"), default="all")
    ap.add_argument("--case", action="append", metavar="NAME", help="only this benchmark case (repeatable)")
    ap.add_argument("--row", action="append", metavar="NAME", help="only this tier row (repeatable)")
    ap.add_argument("--json", metavar="PATH", help="also write the report as JSON")
    a = ap.parse_args(list(argv) if argv is not None else None)
    rep = run(a.benchmark, a.tier, a.case, a.row)
    _print(rep)
    if a.json:
        Path(a.json).write_text(json.dumps(rep, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    code = exit_code(rep)
    if code == 2:
        print("NOTHING COMPARED: no restatement applied to anything measured", file=sys.stderr)
    elif code == 1:
        print(f"\n{len(rep['exit_one'])} EXIT-1 CHANGE(S): a restatement that keeps the meaning moved a verdict",
              file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
