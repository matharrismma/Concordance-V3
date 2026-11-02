"""Derivation moat — reduce a claim (or a multi-step derivation) to a verdict + trail.

The crown jewel of the engine: it verifies a PROVIDED derivation and hands back
HOLDS / BROKEN / INCOMPLETE. The metric that matters most is the FALSE-POSITIVE rate
— it must never return HOLDS for a falsehood (including removable-singularity traps
like x/x == 1). The engine verifies; it does not generate the answer.

A math step's spec is `{mode, params}`; a non-math step's spec is the domain PACKET
(the artifact keys the domain verifier reads, e.g. {"PHYS_VERIFY": {...}}). Math routes
to the sympy verifiers; every other domain routes to its deterministic fleet verifier via
run_for_domain — on the SECULAR surface only, so the witness verifiers (theology /
scripture / witness — signposts, CONCORDANT-never-HOLDS) can never mint a HOLDS seal here.
Ported from 1.0 api/derivation.py (verify_step/verify_derivation), routed directly to
the 2.0 verifiers (no agent_manifest indirection).
"""
from __future__ import annotations

import concurrent.futures as _futures
import copy
import heapq
import json
import logging
import os
import threading as _threading
from typing import Any, Dict, FrozenSet, Iterable, List, NamedTuple, Optional, Tuple

from . import verifiers as _verifiers
from .validate import canonical_json_bytes, sha256_bytes
from .verifiers import bridges as _bridges
from .verifiers import mathematics as _math

_log = logging.getLogger("concordance")
_TERMINAL_FAIL = ("MISMATCH", "ERROR")


def _spec_hash(spec: Any) -> str:
    """Canonical SHA-256 of the exact artifact a step verified — the binding that ties a seal
    to WHAT was checked, not merely to a human-supplied label. Two steps that verify different
    specs can never share a spec_hash, so a HOLDS seal cannot be transplanted onto a different
    claim; a re-fetcher can rehash the spec they hold and confirm it is the one that was checked.
    Best-effort: an unserializable spec hashes its repr rather than raising."""
    try:
        return sha256_bytes(canonical_json_bytes(spec if isinstance(spec, dict) else {"_": spec}))
    except Exception:  # noqa: BLE001 — a fingerprint must never break a verdict
        return sha256_bytes(repr(spec).encode("utf-8"))


def _set_spec_path(spec: Dict[str, Any], path: str, value: Any) -> None:
    """Set spec[...path...] = value for value-binding (3b). `path` is a dotted key into the spec —
    "field", "WRAPPER.field", or "params.field" (depth-bounded). Intermediate non-dicts are replaced
    with dicts. Mutates `spec` (always a caller-owned deep copy)."""
    parts = [p for p in str(path).split(".") if p]
    if not parts:
        return
    d = spec
    for p in parts[:-1]:
        nxt = d.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            d[p] = nxt
        d = nxt
    d[parts[-1]] = value

# DoS guards: reject oversized expressions before sympy sees them, and bound compute time
# so a pathological-but-small expression cannot pin a request thread forever.
_MAX_SPEC_CHARS = int(os.environ.get("CONCORDANCE_MAX_EXPR_CHARS", "4000") or 4000)
_VERIFY_TIMEOUT_S = float(os.environ.get("CONCORDANCE_VERIFY_TIMEOUT_S", "8") or 8)


# Bounded, PROCESS-WIDE verify pool: at most _MAX_WORKERS sympy workers run at once. A
# timed-out worker is not killable (sympy is C-bound), so it keeps its slot until it finishes
# — which IS the bound: under a many-IP flood, excess verifications get an immediate "busy"
# ERROR (never HOLDS) instead of piling up unkillable threads that pin every core.
_MAX_WORKERS = max(1, int(os.environ.get("CONCORDANCE_VERIFY_WORKERS", "4") or 4))
_POOL = _futures.ThreadPoolExecutor(max_workers=_MAX_WORKERS, thread_name_prefix="verify")
_SLOTS = _threading.BoundedSemaphore(_MAX_WORKERS)


class _Saturated(Exception):
    """All verify slots are busy — shed load rather than queue unbounded work."""


def _call_with_timeout(fn, arg):
    """Run a verifier with a hard wall-clock bound on a bounded shared pool. result() returns
    control on timeout so the request never hangs; the worker releases its slot when it ends."""
    if not _SLOTS.acquire(blocking=False):
        raise _Saturated()

    def _run():
        try:
            return fn(arg)
        finally:
            _SLOTS.release()

    return _POOL.submit(_run).result(timeout=_VERIFY_TIMEOUT_S)


# The heavy scientific C-extensions the fleet lazy-imports on first use. If the FIRST heavy
# verification in a fresh worker pays that import INSIDE the wall-clock bound, it can — under
# load — exceed it and turn a TRUE claim into a transient ERROR (errs SAFE, never a false HOLDS,
# but a false negative all the same). warm() pre-pays it at BOOT, outside the timed path.
_HEAVY_LIBS = ("sympy", "numpy", "scipy.stats", "scipy.optimize", "scipy.linalg", "scipy.special")


def warm() -> None:
    """Pre-import the heavy verify deps at boot so no request pays a cold C-extension import
    inside the per-verification timeout. Best-effort: a minimal sovereign install without these
    still boots (the affected domains simply return NOT_APPLICABLE, never a false result)."""
    import importlib
    warmed = []
    for lib in _HEAVY_LIBS:
        try:
            importlib.import_module(lib)
            warmed.append(lib)
        except Exception:  # noqa: BLE001 — warming is optional
            pass
    _log.info("verify deps warmed: %s", ", ".join(warmed) or "(none available)")


# math mode -> verifier function. params (the spec body) is passed straight in.
_MATH_MODES = {
    "equality": _math.verify_equality,
    "inequality": _math.verify_inequality,
    "derivative": _math.verify_derivative,
    "integral": _math.verify_integral,
    "limit": _math.verify_limit,
    "solve": _math.verify_solve,
    "calc_chain": _math.verify_calc_chain,        # grade a worked solution (incl. GSM8K <<expr=result>>)
    "numeric": _math.verify_numeric,              # evaluate an expression, check a claimed value
    "number_theory": _math.verify_number_theory,  # gcd / lcm / primality / factorial / binomial / modulo
    "system": _math.verify_system,                # a claimed solution to a system, by substitution
}


def verify_math(spec: Dict[str, Any]) -> Dict[str, str]:
    """Route a `{mode, params}` math spec to its verifier; reduce to a status."""
    mode = (spec.get("mode") or "").strip().lower()
    params = spec.get("params") or {}
    fn = _MATH_MODES.get(mode)
    if fn is None:
        return {"status": "ERROR", "detail": f"unknown math mode {mode!r}"}
    if len(json.dumps(params, default=str)) > _MAX_SPEC_CHARS:  # DoS guard, before sympy
        return {"status": "ERROR", "detail": f"expression too large (> {_MAX_SPEC_CHARS} chars)"}
    try:
        res = _call_with_timeout(fn, params)  # a VerifierResult, time- and pool-bounded
    except _futures.TimeoutError:
        _log.warning("verify timed out (>%.0fs) mode=%s — shed to ERROR (errs safe, never a false HOLDS)",
                     _VERIFY_TIMEOUT_S, mode)
        return {"status": "ERROR", "detail": f"verification timed out (> {_VERIFY_TIMEOUT_S}s)"}
    except _Saturated:
        _log.warning("verify pool saturated mode=%s — shed to ERROR (errs safe)", mode)
        return {"status": "ERROR", "detail": "verifier busy (too many concurrent verifications) — retry shortly"}
    return {"status": res.status, "detail": (res.detail or "")[:300], "data": dict(res.data or {}),
            "refutations": refutations([res])}


def _reduce_domain_results(results: List[Any]) -> Dict[str, str]:
    """Reduce a domain's list of VerifierResult to ONE moat status. A contradiction is the
    cardinal signal, so MISMATCH wins over ERROR wins over CONFIRMED; only an all-CONFIRMED
    applicable set is CONFIRMED. No applicable verifier -> NOT_APPLICABLE (an honest gap, an
    INCOMPLETE composite — never a false HOLDS). Mirrors test_fp_gate._status exactly."""
    applicable = [r for r in results if r.applicable]
    if not applicable:
        return {"status": "NOT_APPLICABLE",
                "detail": "no applicable secular verifier for this domain/artifact"}
    # merged verifier outputs, so another step can BIND to this result once it is confirmed (3b), wherever
    # either is listed. Only ever read for a CONFIRMED source (verify_derivation gates that), so merging all
    # applicable data is harmless.
    merged: Dict[str, Any] = {}
    for r in applicable:
        if getattr(r, "data", None):
            merged.update(r.data)
    ref = refutations(results)
    mism = [r for r in applicable if r.status == "MISMATCH"]
    if mism:
        return {"status": "MISMATCH", "detail": "; ".join(f"{r.name}: {r.detail}" for r in mism)[:300],
                "data": merged, "refutations": ref}
    errs = [r for r in applicable if r.status == "ERROR"]
    if errs:
        return {"status": "ERROR", "detail": "; ".join(f"{r.name}: {r.detail}" for r in errs)[:300],
                "data": merged, "refutations": ref}
    return {"status": "CONFIRMED",
            "detail": "; ".join(f"{r.name}: {r.detail}" for r in applicable if r.passed)[:300],
            "data": merged, "refutations": ref}


def refutations(results: List[Any]) -> Dict[str, Any]:
    """The inverted reading of a check list. A verifier never finds the truth; it ATTEMPTS refutations. This
    names which were attempted, which the claim survived, which produced a counterexample, which errored, and
    which could not fire on this packet — plus every band and counterexample, so the strongest artifact (the
    counterexample) travels first-class."""
    def _n(r):
        return getattr(r, "name", None) or (r.get("name") if isinstance(r, dict) else None)
    def _st(r):
        return getattr(r, "status", None) or (r.get("status") if isinstance(r, dict) else None)
    def _d(r):
        return (getattr(r, "data", None) if not isinstance(r, dict) else r.get("data")) or {}
    out = {"attempted": [], "survived": [], "counterexamples": [], "errored": [], "not_applicable": [],
           "bands": [], "margin": None}
    for r in results:
        n, st, d = _n(r), _st(r), _d(r)
        if st in ("CONFIRMED", "MISMATCH"):
            out["attempted"].append(n)
            (out["survived"] if st == "CONFIRMED" else out["counterexamples"]).append(
                n if st == "CONFIRMED" else {"check": n, **(d.get("counterexample") or {"detail": getattr(r, "detail", "")})})
        elif st == "ERROR":
            out["errored"].append(n)
        else:
            out["not_applicable"].append(n)
        if isinstance(d.get("bands"), list):
            out["bands"].extend({"check": n, **b} for b in d["bands"] if isinstance(b, dict))
        elif isinstance(d.get("band"), dict):
            out["bands"].append({"check": n, **d["band"]})
    # the step's margin: the tightest band is the one that decides whether this splice gets redone
    scored = [b for b in out["bands"] if isinstance(b.get("used"), (int, float))]
    if scored:
        worst = max(scored, key=lambda b: b["used"])
        out["margin"] = {"used": worst["used"], "tightest": worst.get("what"), "bands": len(scored),
                         "read": _margin_read(worst["used"])}
    return out


def _margin_read(used: float) -> str:
    if used == float("inf"):
        return "exact check: outside"
    if used > 1:
        return f"outside the allowance by {used - 1:.0%}"
    if used >= 0.9:
        return f"inside, but {used:.0%} of the allowance spent — redo this splice before building on it"
    if used >= 0.5:
        return f"inside, {used:.0%} of the allowance spent"
    return f"inside with margin ({used:.0%} spent)"


def verify_domain(domain: str, spec: Dict[str, Any]) -> Dict[str, str]:
    """Route a non-math domain claim to its deterministic fleet verifier(s) via
    run_for_domain, on the SECULAR surface only. Same DoS bounds as the math path (size guard
    + shared bounded pool + wall-clock timeout). The FP gate proves 0 false-positives across
    every domain this reaches, so a CONFIRMED here is as trustworthy as a math CONFIRMED."""
    packet = spec or {}
    if len(json.dumps(packet, default=str)) > _MAX_SPEC_CHARS:  # DoS guard, before any verifier
        return {"status": "ERROR", "detail": f"packet too large (> {_MAX_SPEC_CHARS} chars)"}
    try:
        results = _call_with_timeout(
            lambda p: _verifiers.run_for_domain(domain, p, surface="secular"), packet)
    except _futures.TimeoutError:
        _log.warning("verify timed out (>%.0fs) domain=%s — shed to ERROR (errs safe, never a false HOLDS)",
                     _VERIFY_TIMEOUT_S, domain)
        return {"status": "ERROR", "detail": f"verification timed out (> {_VERIFY_TIMEOUT_S}s)"}
    except _Saturated:
        _log.warning("verify pool saturated domain=%s — shed to ERROR (errs safe)", domain)
        return {"status": "ERROR", "detail": "verifier busy (too many concurrent verifications) — retry shortly"}
    return _reduce_domain_results(results)


def verify_step(domain: str, spec: Dict[str, Any]) -> Dict[str, str]:
    """Run one step's verifier and reduce to a single status. Fail closed: a verifier
    that raises becomes ERROR (a failed step), never a crash and never a silent pass.
    Mathematics routes to the sympy moat; every other (secular) domain routes to its
    deterministic fleet verifier."""
    domain = (domain or "").strip().lower()
    if not domain:
        return {"status": "ERROR", "detail": "step missing 'domain'"}
    try:
        if domain in ("mathematics", "math") and "MATH_VERIFY" not in (spec or {}):
            return verify_math(spec or {})          # the {mode, params} form -> the sympy moat
        return verify_domain(domain, spec or {})     # a MATH_VERIFY packet routes like any other domain
    except Exception as exc:  # noqa: BLE001 — fail closed
        return {"status": "ERROR", "detail": f"verifier raised: {type(exc).__name__}: {str(exc)[:200]}"}


# The strata. Nothing is "applied" at the bottom: the substrate is commitment (these exact bytes, this hash,
# these bindings) — the floor the system can see. Pure steps commit to a rulebook and carry no tolerance.
# Applied steps commit to data and a band. The connections between them are the `uses`/`bind` edges, and
# the trace shows them so an applied fault can be followed down to the exact steps it stood on.
_EXACT_DOMAINS = frozenset({"mathematics", "math", "number_theory", "combinatorics", "polynomial", "formal_logic",
                            "cryptography", "networking", "linear_algebra", "information_theory", "geometry",
                            "probability", "statistics", "elliptic_curves", "riemann_accel"})


def _stratum(t: Dict[str, Any]) -> str:
    """By domain: pure domains commit to a rulebook (any tolerance there is a float-comparison concession,
    not world data); everything else commits to data. A plugin declares its own with a module-level
    `STRATUM = "pure"` — a canon that is checked by hash is as exact as arithmetic."""
    dom = str(t.get("domain") or "").lower()
    if dom in _EXACT_DOMAINS:
        return "pure"
    try:
        from . import verifiers as _V
        _V._load_plugins()
        path = _V.VERIFIERS.get(dom)
        if path:
            import importlib
            return str(getattr(importlib.import_module(path), "STRATUM", "applied"))
    except Exception:  # noqa: BLE001
        pass
    return "applied"


def _depth_and_floor(trail: List[Dict[str, Any]]) -> Tuple[List[Optional[int]], List[List[str]]]:
    """Each event's distance (its depth in the `uses` graph) and stands_on (everything beneath it, transitively,
    down to the floor), read from the graph by id, so where a step is listed changes neither. An id resolves to
    a step only when exactly one step carries it; one no step carries, or several do, is named and walked no
    further (it adds 0 to the depth), so the work stays in proportion to the body. No recursion: a step is
    placed once the step carrying each id it uses is placed (distance 1 + the deepest of them), and its floor is
    each used id followed by that id's own floor, first occurrence kept. A step on a cycle, or resting on one,
    is never placed: its distance is None and its stands_on names what it reaches, walked with an explicit
    stack (so a step on a cycle names itself)."""
    n = len(trail)
    ids = [str(t.get("id")) for t in trail]
    uses = [[str(u) for u in (t.get("uses") or [])] for t in trail]
    carriers: Dict[str, List[int]] = {}
    for i, sid in enumerate(ids):
        carriers.setdefault(sid, []).append(i)
    single = {u: js[0] for u, js in carriers.items() if len(js) == 1}
    below = [list(dict.fromkeys(single[u] for u in uses[i] if u in single)) for i in range(n)]
    above: List[List[int]] = [[] for _ in range(n)]
    for i, js in enumerate(below):
        for j in js:
            above[j].append(i)
    waiting = [len(js) for js in below]
    depth: List[Optional[int]] = [None] * n
    floor: List[Optional[List[str]]] = [None] * n
    ready = [i for i in range(n) if not waiting[i]]
    while ready:
        i = ready.pop()
        depth[i] = 1 + max([depth[single[u]] if u in single else 0 for u in uses[i]] or [0])
        out: List[str] = []
        seen: set = set()
        for u in uses[i]:
            for x in [u] + (floor[single[u]] if u in single else []):
                if x not in seen:
                    seen.add(x)
                    out.append(x)
        floor[i] = out
        for a in above[i]:
            waiting[a] -= 1
            if not waiting[a]:
                ready.append(a)
    for i in range(n):
        if floor[i] is None:
            out, seen, stack = [], set(), [iter(uses[i])]
            while stack:
                for u in stack[-1]:
                    if u not in seen:
                        seen.add(u)
                        out.append(u)
                        stack.append(iter(uses[single[u]] if u in single else ()))
                        break
                else:
                    stack.pop()
            floor[i] = out
    return depth, [f or [] for f in floor]


def _trace(trail: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The OTDR view of a derivation. Shoot the chain: every step is an event at a distance (its depth in the
    `uses` graph; None on a cycle), with the loss it registered (margin used) and whether it reflected (a
    counterexample) or went dark (could not run). The link budget is the worst event on the chain — the
    tightest step decides whether the whole derivation clears, exactly as the worst splice decides a span."""
    depths, floors = _depth_and_floor(trail)
    events = []
    for t, d, floor in zip(trail, depths, floors):
        sid = str(t.get("id"))
        ref = t.get("refutations") or {}
        m = ref.get("margin") or {}
        st = t.get("status")
        kind = ("reflection" if st == "MISMATCH" else "dark" if st in ("NOT_APPLICABLE", "ERROR") else "pass")
        ev = {"id": sid, "distance": d, "stratum": _stratum(t), "stands_on": floor, "spec_hash": t.get("spec_hash"),
              "bucket": ("hit" if (t.get("memo") or {}).get("hit") else "miss"),
              "event": kind, "status": st,
              "used": m.get("used"), "tightest": m.get("tightest"), "read": m.get("read")}
        if kind == "reflection":
            cx = (ref.get("counterexamples") or [{}])[0]
            ev["off_by"] = cx.get("off_by")
        events.append(ev)
    scored = [e for e in events if isinstance(e.get("used"), (int, float))]
    worst = max(scored, key=lambda e: e["used"]) if scored else None
    # energy — the predictive-coding reading: each event's prediction error is its margin used (clamped to 1,
    # squared), a reflection is a full unit of error. The chain's energy is what the scribe loop drives down;
    # a pass at the edge costs almost as much as a miss, which is why it gets redone.
    energy = sum(min(float(e["used"]), 1.0) ** 2 for e in scored) + sum(1.0 for e in events if e["event"] == "reflection" and not isinstance(e.get("used"), (int, float)))
    budget = {"events": len(events), "scored": len(scored), "energy": energy,
              "bucket_hits": sum(1 for e in events if e["bucket"] == "hit"),
              "worst_used": worst["used"] if worst else None,
              "worst_step": worst["id"] if worst else None,
              "worst_what": worst.get("tightest") if worst else None,
              "reflections": sum(1 for e in events if e["event"] == "reflection"),
              "dark": sum(1 for e in events if e["event"] == "dark")}
    if worst is None:
        budget["read"] = "no banded checks on this chain; nothing to budget"
    elif worst["used"] > 1:
        budget["read"] = f"chain fails at {worst['id']} ({worst.get('tightest')}): outside its allowance"
    else:
        budget["read"] = (f"chain clears; tightest event {worst['id']} ({worst.get('tightest')}) at "
                          f"{worst['used']:.0%} of its allowance")
    strata = {"pure": sum(1 for e in events if e["stratum"] == "pure"),
              "applied": sum(1 for e in events if e["stratum"] == "applied")}
    # where a fault sits relative to the floor: an applied reflection standing on clean pure steps is a data
    # fault, not a math fault — the connections say so
    at: Dict[str, List[int]] = {}
    for n, e in enumerate(events):
        at.setdefault(e["id"], []).append(n)
    for e in events:
        # a step standing on an id several steps carry stands on no step anyone can name: no locus is claimed
        if e["event"] == "reflection" and e["stands_on"] and all(len(at.get(x, ())) <= 1 for x in e["stands_on"]):
            below = [events[n] for n in sorted(n for x in e["stands_on"] for n in at.get(x, ()))]
            if below and all(b["event"] == "pass" for b in below):
                e["fault_locus"] = ("data" if e["stratum"] == "applied" else "rule") + \
                                   f": every step it stands on passed ({', '.join(b['id'] for b in below)})"
    return {"events": events, "budget": budget, "strata": strata,
            "means": "energy = Σ min(used,1)² over scored events (+1 per unscored reflection): the chain's total prediction "
                     "error, which a correction loop must drive down; "
                     "an OTDR trace of the derivation: distance is depth in the dependency graph, stands_on is every "
                     "step beneath it down to the floor, stratum is pure (commits to a rulebook, no tolerance) or "
                     "applied (commits to data and a band), used is the share of a step's tolerance the claim spent, "
                     "a reflection is a counterexample, dark is a step that could not run; the worst event is the "
                     "link budget; the floor under every step is its spec_hash — the commitment to exactly these bytes"}


def _trust() -> Optional[Dict[str, Any]]:
    try:
        from .capabilities import trust
        t = trust()
        return t if t.get("available") else None
    except Exception:  # noqa: BLE001
        return None


def _read(verdict: str, agg: Dict[str, int]) -> str:
    """One sentence that says what the verdict is NOT. HOLDS is not truth: it is the set of refutations that
    failed. BROKEN is a counterexample, which is a finding. The rest are facts about the engine."""
    a, s, c = agg["attempted"], agg["survived"], agg["counterexamples"]
    if verdict == "HOLDS":
        return (f"survived {s} attempted refutation{'s' if s != 1 else ''}; not shown true — shown not false by "
                f"these checks, and silent on anything they did not test")
    if verdict == "BROKEN":
        return f"{c} counterexample{'s' if c != 1 else ''} out of {a} attempted; the claim is outside the band"
    if verdict == "INCOMPLETE":
        return f"{s} of {a} attempted refutations survived; at least one step could not be tested — a gap, not a verdict"
    return "the engine failed, not the claim; nothing here is a finding"


# ── the composition law ───────────────────────────────────────────────────────────────────────────────────
# A step's effective outcome rides on two rails that only switch on: P, a check holds, and R, a check breaks.
# CONFIRMED is P, BROKEN is R, and ERROR and a gap are both not-checkable (P=0, R=0), told apart only by the
# cause kept beside the rails. Three pure functions carry the law, and verify_derivation computes through
# them: _transfer (the per-step rule the closure iterates), _meet (Kleene's strong meet, for the composite
# only) and _readout (Moisil's r1 and r2, the one place a rail is read off, then the precedence). Both rails on
# at once would be Belnap's "both"; no rule produces it.
class _Rails(NamedTuple):
    p: bool                 # a check holds
    r: bool                 # a check breaks
    why: FrozenSet[str]     # beside the rails: "confirmed", "broken", "error" (our failure), "gap", "cap"


_CONFIRMED = _Rails(True, False, frozenset({"confirmed"}))
_BROKEN = _Rails(False, True, frozenset({"broken"}))
_ERROR = _Rails(False, False, frozenset({"error"}))
_GAP = _Rails(False, False, frozenset({"gap"}))
_CUT = _Rails(False, False, frozenset({"cap"}))       # a gap the pass cap left unsettled
# a verifier's status as the step's own check; an unknown status is our failure, never the caller's
_OWN = {"CONFIRMED": _CONFIRMED, "MISMATCH": _BROKEN, "ERROR": _ERROR, "NOT_APPLICABLE": _GAP}


def _transfer(node: Dict[str, Any], own: Optional[_Rails], deps: List[Optional[_Rails]],
              halt: str = "") -> Optional[Tuple[_Rails, bool, Optional[Dict[str, Any]]]]:
    """The per-step rule the closure iterates: 45fcd3c's rule, made to wait for evidence instead of reading
    its absence. A step's own non-confirmed check governs it; a seam MISMATCH breaks it, even over its own
    ERROR; a dependency's break reaches it only through its own confirmed check; standing on our failure it
    is ERROR and standing on a gap it is a gap, never BROKEN.

    `node` is what the listing fixes about the step: its `id` and listed position `at`, the ids it uses that
    resolve to no single step because no step or several steps carry them (`missing`), the bridge results on
    its cross-domain `uses` edges that can decide it, its first MISMATCH and first INCOMPLETE (`seams`), and
    whether another step carries its id (`repeated`). `own` is its own check, or None until that check can run
    (a bind's source is unsettled). `deps` holds the value of the one step carrying each other id it uses, None
    while that step is unsettled.

    Returns None while the outcome still turns on something unsettled, else (value, originates, bridge).
    `originates` says the outcome is the step's own (its check, its seam, an id that resolves to no single step,
    its repeated id, a cycle or the cap) and did not come only from a dependency of that kind. `halt` is set only once the
    closure has halted: "cycle" for a step on a cycle of unsettled steps, "rests on a cycle" for one with such
    a cycle beneath it, "cap" for one the pass cap cut off; a step still waiting then becomes a gap. No rail
    is negated here, so a step never settles on the absence of evidence."""
    if halt == "cap":
        return _CUT, True, None                             # the pass cap cut it off before it settled
    for seam in node["seams"]:
        if seam.get("status") == "MISMATCH":
            return _BROKEN, True, seam                      # a category error at the join: the seam breaks it
    if own is None:                                         # its own check has not run: a bind awaits its source
        return (_GAP, True, None) if halt else None
    if own.r:
        return own, True, None                              # its own check breaks
    if own.p:                                               # its own check holds, so its ground decides
        if any(d and d.r for d in deps):
            return _BROKEN, False, None                     # a break beneath it reaches it through its check
        if any(d is None for d in deps):                    # something beneath it is unsettled: wait
            if halt:
                return _GAP, halt == "cycle" or bool(node["missing"]) or node["repeated"], None
            return None
        if all(d.p for d in deps):
            if node["missing"]:
                return _GAP, True, None                     # it names an id that resolves to no single step
            for seam in node["seams"]:
                if seam.get("status") == "INCOMPLETE":
                    return _GAP, True, seam                 # the crossing's justification is absent: unproven
            if node["repeated"]:
                return _GAP, True, None                     # another step carries its id: which one is meant?
            return own, False, None                         # it holds, and so does everything it stands on
        if any("error" in d.why for d in deps):
            return _ERROR, False, None                      # it stands on our failure, never a falsehood
        if node["missing"]:
            return _GAP, True, None
        return _GAP, node["repeated"], None                 # it stands on a gap
    return own, True, None                                  # its own ERROR or gap governs


def _meet(values: Iterable[_Rails]) -> _Rails:
    """Kleene's strong meet, for the composite only. On the rails the composite holds only if every step holds
    (P is the AND of the P rails) and breaks if any step breaks (R is the OR of the R rails); the causes ride
    beside. Monotone in the information order: refining a not-checkable step to holds or to broken never flips
    a definite composite. The meet of nothing is not-checkable: with nothing checked, nothing holds."""
    vs = list(values)
    return _Rails(bool(vs) and all(v.p for v in vs), any(v.r for v in vs),
                  frozenset().union(*(v.why for v in vs)))


def _r1(v: _Rails) -> bool:
    """Moisil's r1, 'certainly holds': the P rail."""
    return v.p


def _r2(v: _Rails) -> bool:
    """Moisil's r2, 'not broken': the R rail read off. The one negation of a rail; only _readout calls it."""
    return not v.r


def _readout(c: _Rails) -> str:
    """The composite verdict, read off the rails at the output and nowhere else: r2 false is BROKEN, r1 true is
    HOLDS, and the causes beside the rails give the precedence BROKEN > SYSTEM_ERROR > INCOMPLETE > HOLDS. A run
    the pass cap cut off reads INCOMPLETE rather than SYSTEM_ERROR: a step it left unsettled could still break."""
    if not _r2(c):
        return "BROKEN"
    if "cap" in c.why:
        return "INCOMPLETE"
    if "error" in c.why:
        return "SYSTEM_ERROR"
    if _r1(c):
        return "HOLDS"
    return "INCOMPLETE"


def _pass_cap(k: int) -> int:
    """The most passes the closure may take over k steps: k + 1. Each step settles once and its verifier runs
    once, and the closure halts on its own within k + 1 passes (tests/test_derivation_laws.py holds that bound,
    tight on a chain listed in reverse), so the cap is a backstop, never a verdict: a run it cuts off is
    INCOMPLETE, never HOLDS. Tests inject a smaller cap here to drive the cut-off."""
    return k + 1


def _evaluation_order(k: int) -> List[int]:
    """The order the closure visits steps within a pass: listed order. The result never depends on it (the
    order-replica test swaps in others); only the number of passes does."""
    return list(range(k))


def _cycles(succ: Dict[int, List[int]]) -> Dict[int, List[int]]:
    """Every node of `succ` that lies on a cycle, mapped to the members of its strongly connected group.
    Tarjan's algorithm with an explicit stack, so a long chain cannot exhaust the recursion limit."""
    index: Dict[int, int] = {}
    low: Dict[int, int] = {}
    on: set = set()
    stack: List[int] = []
    out: Dict[int, List[int]] = {}
    for root in succ:
        if root in index:
            continue
        index[root] = low[root] = len(index)
        stack.append(root)
        on.add(root)
        work = [(root, iter(succ[root]))]
        while work:
            v, it = work[-1]
            for w in it:
                if w not in index:
                    index[w] = low[w] = len(index)
                    stack.append(w)
                    on.add(w)
                    work.append((w, iter(succ[w])))
                    break
                if w in on:
                    low[v] = min(low[v], index[w])
            else:
                work.pop()
                if work:
                    low[work[-1][0]] = min(low[work[-1][0]], low[v])
                if low[v] == index[v]:
                    group = []
                    while True:
                        w = stack.pop()
                        on.discard(w)
                        group.append(w)
                        if w == v:
                            break
                    if len(group) > 1 or v in succ[v]:
                        for w in group:
                            out[w] = group
    return out


def verify_derivation(steps: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Verify a derivation, in whatever order its steps are listed. The full trail is always returned, in
    listed order; the COMPOSITE verdict reports the most serious thing that happened, and `broken_at` /
    `error_at` / `gap_at` each name the FIRST step, in listed order, where that kind of outcome ORIGINATES —
    where trust stopped, and why — never a step that only inherited it.

    The steps resolve as a monotone closure. A step settles only from settled evidence (its own check, the
    settled outcomes of the steps it uses, its seams), never from the absence of a dependency not yet settled.
    Its verifier runs exactly once, on its final spec, as soon as every source it binds from has settled, or
    never if a bind stays unresolved. The closure halts on the first pass in which nothing settles and no
    verifier runs, within k + 1 passes for k steps, and only then does a step still unsettled become a gap:
    one on a cycle, or one the pass cap cut off (INCOMPLETE, never HOLDS). `halt` says how it stopped. The
    rule is monotone, so each step's outcome, the set of steps originating each kind and the verdict do not
    depend on the order the steps are listed in (only which originator a pointer names, when a kind has
    several), and nothing but the pass count depends on the order they are visited in.

    "Our engine could not check this" is NOT "your claim is false." Those are different
    sentences about different things, and only one of them is about the caller. A verifier
    that ERRORs — unusable input, a raise, a missing domain — is a failure of OURS, so it
    returns SYSTEM_ERROR, never BROKEN (contract §5.6, and the taxonomy in §7). Collapsing
    them would be the inverse of the kernel's fifth clause: instead of silently upgrading our
    authority, we would be silently downgrading the caller's claim on the strength of our own
    bug. Someone checking a dosage deserves to know which of the two happened.

    Precedence, so honesty runs BOTH ways:
        BROKEN > SYSTEM_ERROR > INCOMPLETE > HOLDS
    A genuine MISMATCH anywhere still governs — an engine error elsewhere in the derivation
    must not become a place for a real falsehood to hide.
    """
    if not isinstance(steps, list) or not steps:
        return {"verdict": "SYSTEM_ERROR", "detail": "no steps provided", "trail": [],
                "means": "the engine was given nothing to check — this says nothing about any claim"}

    from . import bucket as _bucket
    k = len(steps)
    # ── what the listing fixes before anything runs ──
    ids = [str(step.get("id") or f"s{i}") for i, step in enumerate(steps)]
    carriers: Dict[str, List[int]] = {}           # id -> every listed step carrying it
    for i, sid in enumerate(ids):
        carriers.setdefault(sid, []).append(i)
    domains = [str(step.get("domain", "")) for step in steps]
    # VALUE-BINDING (3b): a step may BUILD an input from another step's CONFIRMED output, wherever that step
    # is listed — bind = {"<spec path>": "<srcId>.<outputKey>"} (outputKey defaults to "actual"). A bind IS a
    # dependency, so its source joins `uses`. Fail-closed: if the source is not confirmed, is carried by no
    # step or by more than one, or lacks the output key, the binding is UNRESOLVED and the step is NOT verified
    # with a fabricated value — it becomes a GAP, never a guessed HOLDS and never a MISMATCH manufactured from
    # our own inability to resolve a ref. Substitution is into a deep copy, so the caller's spec is never
    # mutated and the spec_hash binds the seal to exactly what was checked.
    uses_of: List[List[str]] = []
    binds_of: List[List[Tuple[Any, Any, str, str]]] = []
    for step in steps:
        uses = [str(u) for u in (step.get("uses") or [])]
        binds: List[Tuple[Any, Any, str, str]] = []
        bind = step.get("bind")
        if isinstance(bind, dict) and bind:
            for path, ref in bind.items():
                src_id, _, key = str(ref).partition(".")
                if src_id not in uses:
                    uses.append(src_id)
                binds.append((path, ref, src_id, key or "actual"))
        uses_of.append(uses)
        binds_of.append(binds)
    # An id resolves to a step only when exactly one listed step carries it. A reference to an id several steps
    # carry resolves to none of them — like a bind from it, and like an id no step carries — so its user stands
    # on a gap of its own and never waits on, or is wired to, each carrier: the work stays in proportion to the
    # body, not to (step, carrier) pairs.
    single = {u: js[0] for u, js in carriers.items() if len(js) == 1}
    below = [[single[u] for u in uses_of[i] if u in single] for i in range(k)]
    above: List[List[int]] = [[] for _ in range(k)]
    for i in range(k):
        for j in dict.fromkeys(below[i]):
            above[j].append(i)
    # THE SEAM — a cross-domain BRIDGE (registry §4). A step that CONSUMES a step from another domain must not
    # launder rigor across the boundary: a p-value asserted as PROOF, a scaling law with no dimensional
    # analysis. The single-domain verifier cannot see the join; this does. A category error at the seam BREAKS;
    # a crossing whose justification is absent is a GAP (unproven, never a false HOLDS). Checked on every
    # genuine cross-domain `uses` edge, against the domain of each step carrying the id (a repeated id too),
    # wherever it is listed. A bridge result reads only the two domains and the crossing step, so each step is
    # checked once per distinct dependency domain, and keeps only what _transfer reads: its first MISMATCH and
    # its first INCOMPLETE.
    carrier_domains: Dict[str, List[str]] = {}          # id -> one domain per canonical name, in listed order
    named: Dict[str, set] = {}
    for j in range(k):
        c = _bridges._canon(domains[j])
        if c and c not in named.setdefault(ids[j], set()):
            named[ids[j]].add(c)
            carrier_domains.setdefault(ids[j], []).append(domains[j])

    def _seams(i: int) -> List[Dict[str, Any]]:
        own = _bridges._canon(domains[i])
        seen: set = set()
        kept: List[Dict[str, Any]] = []
        for u in uses_of[i]:
            for dom in carrier_domains.get(u, ()):
                c = _bridges._canon(dom)
                if not own or c == own or c in seen:
                    continue                            # the same domain, or one already checked: no new seam
                seen.add(c)
                res = _bridges.check(domains[i], steps[i], dom)
                if res.get("status") == "MISMATCH":
                    kept.append(res)
                    return kept
                if res.get("status") == "INCOMPLETE" and not kept:
                    kept.append(res)
        return kept

    nodes = [{"id": ids[i], "at": i,
              "missing": [u for u in uses_of[i] if u not in single],      # resolves to no single step
              "seams": _seams(i),
              "repeated": len(carriers[ids[i]]) > 1}
             for i in range(k)]

    sr: List[Optional[Dict[str, Any]]] = [None] * k     # each step's own check, once it has run
    checked: List[Any] = [None] * k                     # the exact spec its verifier ran on
    # a bind from an id no step carries, or one several steps carry, can never resolve
    blocked = [any(len(carriers.get(src, ())) != 1 for _, _, src, _ in binds_of[i]) for i in range(k)]
    val: List[Optional[_Rails]] = [None] * k            # each step's effective outcome, once settled
    origin = [False] * k
    bridge: List[Optional[Dict[str, Any]]] = [None] * k

    def _resolve(i: int) -> Tuple[List[Tuple[Any, Any]], List[str], bool]:
        """Step i's binds against what has settled: (resolved (path, value) pairs, unresolved, pending)."""
        resolved, unresolved, pending = [], [], False
        for path, ref, src, key in binds_of[i]:
            js = carriers.get(src, ())
            if len(js) == 1:
                v = val[js[0]]
                if v is None:
                    pending = True                      # its source has not settled: wait, never guess
                    continue
                data = (sr[js[0]] or {}).get("data") or {}
                if v.p and isinstance(data, dict) and key in data:
                    resolved.append((path, data[key]))
                    continue
            unresolved.append("%s<-%s" % (path, ref))
        return resolved, unresolved, pending

    def _built(i: int, resolved: List[Tuple[Any, Any]]) -> Any:
        spec = steps[i].get("spec") or {}
        if binds_of[i]:
            spec = copy.deepcopy(spec)
            for path, value in resolved:
                _set_spec_path(spec, str(path), value)
        return spec

    def _own(i: int) -> Optional[_Rails]:
        if blocked[i]:
            return _GAP                                 # it could not be BUILT: we cannot check what we could not assemble
        return _OWN.get(sr[i]["status"], _ERROR) if sr[i] is not None else None

    # ── the closure: visit the steps a change could move, in evaluation order, until a pass moves nothing ──
    order = _evaluation_order(k)
    rank = [0] * k
    for r, i in enumerate(order):
        rank[i] = r
    cap = _pass_cap(k)
    passes, how = 0, "settled"
    frontier = list(range(k))
    while True:
        if passes >= cap:
            how = "cap"
            break
        passes += 1
        heap = [rank[i] for i in frontier]
        heapq.heapify(heap)
        queued = set(frontier)
        later: set = set()
        moved = False
        while heap:
            i = order[heapq.heappop(heap)]
            if sr[i] is None and not blocked[i]:
                resolved, unresolved, pending = _resolve(i)
                if unresolved:
                    blocked[i] = True
                elif not pending:
                    # the smallest bucket: exactly these bytes under exactly this verifier — a hit is served
                    spec = checked[i] = _built(i, resolved)
                    sr[i] = _bucket.through(domains[i], _spec_hash(spec), lambda: verify_step(domains[i], spec))
                    moved = True
            if val[i] is None:
                res = _transfer(nodes[i], _own(i), [val[j] for j in below[i]])
                if res is not None:
                    val[i], origin[i], bridge[i] = res
                    moved = True
                    for a in above[i]:
                        if rank[a] > rank[i]:
                            if a not in queued:
                                queued.add(a)
                                heapq.heappush(heap, rank[a])
                        else:
                            later.add(a)
        if not moved:
            break
        frontier = sorted(later)

    # ── only now does a step still unsettled become a gap: on a cycle, resting on one, or cut off by the cap ──
    unsettled: Dict[int, str] = {}
    on_cycle: Dict[int, List[int]] = {}
    cycle_names: Dict[int, List[str]] = {}
    still = [i for i in range(k) if val[i] is None]
    if still:
        if how == "cap":
            unsettled = {i: "cap" for i in still}
        else:
            on_cycle = _cycles({i: sorted({j for j in below[i] if val[j] is None}) for i in still})
            unsettled = {i: ("cycle" if i in on_cycle else "rests on a cycle") for i in still}
            for group in {id(g): g for g in on_cycle.values()}.values():
                names = sorted({ids[j] for j in group})        # once per cycle, not once per member
                for j in group:
                    cycle_names[j] = names
        last = {i: _transfer(nodes[i], _own(i), [val[j] for j in below[i]], unsettled[i]) for i in still}
        for i, res in last.items():
            val[i], origin[i], bridge[i] = res

    confirmed_ids = {ids[i] for i in range(k) if val[i].p}
    trail: List[Dict[str, Any]] = []
    for i, step in enumerate(steps):
        resolved, unresolved, _ = _resolve(i)
        if sr[i] is not None:
            spec, s = checked[i], sr[i]
        else:
            # the step could not be BUILT (or the cap stopped the closure before its check ran) — a gap, never
            # a false verdict; the dependency gating still records what it stood on
            spec = _built(i, resolved)
            s = {"status": "NOT_APPLICABLE", "data": {},
                 "detail": ("unresolved binding(s): " + ", ".join(unresolved)) if unresolved else
                           "not checked: the pass cap stopped the closure before this step's check ran"}
        uses = uses_of[i]
        missing = [u for u in uses if u not in carriers]       # an id no step carries, as at 45fcd3c
        unconfirmed = [u for u in uses if u in carriers and u not in confirmed_ids]
        entry: Dict[str, Any] = {
            "id": ids[i], "domain": domains[i], "claim": str(step.get("claim", "")),
            "uses": uses, "status": s["status"], "detail": s.get("detail", ""),
            "link_ok": not missing and not unconfirmed and not unresolved,
            # the fingerprint of exactly what was checked — travels into the seal so the verdict is bound
            # to its artifact, not the free-text label. For a bound step this is the SUBSTITUTED spec, so
            # the seal binds to what was actually verified.
            "spec_hash": _spec_hash(spec),
            "_spec": spec,          # the exact packet checked; receipts.attach files it beside the seal, then drops it
        }
        # Kind B — surface a verifier's framing (explanation + the question that would let us
        # calculate) so a decline is actionable, not a dead end. Only the curated framing fields
        # travel out, never the verifier's whole internal data dict.
        if s.get("refutations"):
            entry["refutations"] = s["refutations"]
        if s.get("memo"):
            entry["memo"] = s["memo"]
        _g = s.get("data") or {}
        _framing = {kk: _g[kk] for kk in ("framing_question", "need", "example", "route") if kk in _g}
        if _framing:
            entry["guidance"] = _framing
        if missing:
            entry["missing_refs"] = missing
        if unconfirmed:
            entry["builds_on_unconfirmed"] = unconfirmed
        if unresolved:
            entry["unresolved_binding"] = unresolved
        if bridge[i]:
            entry["bridge"] = bridge[i]
        if nodes[i]["repeated"]:
            entry["repeated_id"] = len(carriers[ids[i]])      # how many listed steps carry this id
        if i in unsettled:
            entry["unsettled"] = unsettled[i]
            if i in on_cycle:
                entry["cycle"] = list(cycle_names[i])
        trail.append(entry)

    # where trust stopped: the first step, in listed order, where each kind of outcome originates
    def _first(kind: str) -> Optional[str]:
        return next((ids[i] for i in range(k) if origin[i] and kind in val[i].why), None)

    broken_at = _first("broken")
    error_at = _first("error")
    gap_at = next((ids[i] for i in range(k) if origin[i] and val[i].why & {"gap", "cap"}), None)
    verdict = _readout(_meet(val))

    agg = {"attempted": 0, "survived": 0, "counterexamples": 0, "errored": 0, "not_applicable": 0}
    for t in trail:
        for kk in agg:
            agg[kk] += len((t.get("refutations") or {}).get(kk) or [])
    out = {
        "verdict": verdict,
        "read": _read(verdict, agg),
        "refutations": agg,
        "trace": _trace(trail),
        # the Bayesian discount on a survival, from the recorded benchmark counts — only a HOLDS carries one
        "trust": _trust() if verdict == "HOLDS" else None,
        "steps": len(steps),
        "confirmed_steps": len(confirmed_ids),
        "broken_at": broken_at,
        "gap_at": gap_at,
        "error_at": error_at,
        "trail": trail,
        "note": ("The trail is the trust: each step is machine-verified and stands only on "
                 "steps that are themselves confirmed, wherever they are listed. The engine "
                 "verifies a provided derivation; it does not generate the answer."),
        # how the closure stopped. Response only: record_from_derivation names the fields it seals, and this
        # is not one of them, so SEAL_SPEC and RECEIPT_SPEC are unchanged.
        "halt": {"passes": passes, "reason": how, "cap": cap},
    }
    if verdict == "SYSTEM_ERROR":
        out["means"] = ("OUR engine could not perform this check — this is a failure on our side "
                        "and says NOTHING about whether the claim is true. Do not read it as a "
                        "refutation.")
    return out


def verify(spec: Dict[str, Any], domain: str = "mathematics") -> Dict[str, Any]:
    """One-claim convenience: the verdict for a single `{mode, params}` spec."""
    return verify_derivation([{"id": "b", "domain": domain, "spec": spec}])
