"""A derivation's verdict depends only on what its steps claim and what they rest on, never on the order they
are listed (run 2026-11-02-order-free-derivation).

At 45fcd3c the moat walked the steps once, in listed order, and read a dependency it had not seen yet as a
gap: [a, b uses a] was HOLDS and [b uses a, a] was INCOMPLETE. derivation.py now resolves the steps as a
monotone closure computed through _transfer, _meet and _readout. These tests run every listing order of a set
of derivations whose steps carry explicit unique ids and require, by step id, the same fields; pin each
derivation's value; check every dependency-sorted listing field for field against 45fcd3c's own code, frozen
below; and hold what must never be HOLDS: a cycle, an id no step carries, a repeated id.

The set of steps that ORIGINATE each outcome is not a response field. It is read from the _transfer recorder
(the WIRING test below), which also proves verify_derivation computes through all three functions.
"""
from __future__ import annotations

import copy
import itertools
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from concordance import derivation as D
from concordance.verifiers import bridges as _bridges

# the derivations live in the tier (tests/fixtures/derivation_tier.py), their one home
_FIXTURES = str(Path(__file__).resolve().parent / "fixtures")
if _FIXTURES not in sys.path:
    sys.path.insert(0, _FIXTURES)
from derivation_tier import (CYCLE, CYCLE_AND_RESTING, DEFAULT_ID_COLLISION, ERROR_BESIDE_FALSE,  # noqa: E402
                             FALSE_CYCLE, FALSE_SELF_CYCLE, ORDER_FREE, OUTCOMES, POINTERS, PROOF, REPEATED,
                             SELF_CYCLE, SORTED, TWO_STEP, VERDICT, num, rect)


@pytest.fixture(scope="module", autouse=True)
def _warm():
    """Pre-pay the heavy imports outside the per-verification timeout, as the server does at boot. Measured
    here: a cold first statistics check took over 8 s and was shed to ERROR."""
    D.warm()

# ── the oracle: 45fcd3c's _trace and verify_derivation, verbatim ──────────────────────────────────────────
# Copied from `git show 45fcd3c:src/concordance/derivation.py`, lines 298-367 and 393-595, so "a dependency-
# sorted listing returns every field 45fcd3c returns" is checked against 45fcd3c's code, not a transcription
# of its output. Four edits, and only these: both names gain the suffix _45fcd3c, the one call to _trace
# follows its rename, and `from . import bucket` becomes an absolute import. Every helper they call is
# unchanged by this run, and is the live one.
_stratum, _spec_hash, _set_spec_path = D._stratum, D._spec_hash, D._set_spec_path
_trust, _read, verify_step = D._trust, D._read, D.verify_step

def _trace_45fcd3c(trail: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The OTDR view of a derivation. Shoot the chain: every step is an event at a distance (its depth in the
    `uses` graph), with the loss it registered (margin used) and whether it reflected (a counterexample) or
    went dark (could not run). The link budget is the worst event on the chain — the tightest step decides
    whether the whole derivation clears, exactly as the worst splice decides a span."""
    depth: Dict[str, int] = {}
    stands: Dict[str, List[str]] = {}
    events = []
    for t in trail:
        sid = str(t.get("id"))
        uses = [str(u) for u in (t.get("uses") or [])]
        d = 1 + max([depth.get(u, 0) for u in uses] or [0])
        depth[sid] = d
        # the connections: everything this step stands on, transitively, down to the floor
        floor: List[str] = []
        for u in uses:
            for x in [u] + stands.get(u, []):
                if x not in floor:
                    floor.append(x)
        stands[sid] = floor
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
    for e in events:
        if e["event"] == "reflection" and e["stands_on"]:
            below = [x for x in events if x["id"] in e["stands_on"]]
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


def verify_derivation_45fcd3c(steps: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Verify an ordered derivation. The full trail is always returned; the COMPOSITE verdict
    reports the most serious thing that happened, and `broken_at` / `error_at` / `gap_at` each
    name the FIRST step of their kind — where trust stopped, and why.

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

    trail: List[Dict[str, Any]] = []
    seen_ids: set = set()
    confirmed_ids: set = set()
    outcome_by_id: Dict[str, str] = {}   # sid -> effective outcome (CONFIRMED|BROKEN|ERROR|GAP)
    domain_by_id: Dict[str, str] = {}    # sid -> domain, so a cross-domain `uses` edge can be gated
    data_by_id: Dict[str, Dict[str, Any]] = {}  # sid -> a CONFIRMED step's verifier outputs, for value-binding
    broken_at = None
    gap_at = None
    error_at = None

    def _worst_dep_outcome(dep_ids: List[str]) -> str:
        # A step confirmed in isolation but standing on unconfirmed ground inherits the WORST of
        # what it stands on — but our-failure (ERROR) and a gap (NOT_APPLICABLE / a missing ref)
        # must NEVER be manufactured into BROKEN. Only a genuine MISMATCH below carries a break up.
        sev = {"BROKEN": 3, "ERROR": 2, "GAP": 1, "CONFIRMED": 0}
        worst, wv = "GAP", 1
        for u in dep_ids:
            o = outcome_by_id.get(u, "GAP")   # a missing/unseen ref -> cannot evaluate -> GAP
            if sev.get(o, 1) > wv:
                worst, wv = o, sev[o]
        return worst if worst != "CONFIRMED" else "GAP"

    for i, step in enumerate(steps):
        sid = str(step.get("id") or f"s{i}")
        domain = str(step.get("domain", ""))
        spec = step.get("spec") or {}
        uses = [str(u) for u in (step.get("uses") or [])]

        # VALUE-BINDING (3b): a step may BUILD an input from a CONFIRMED prior step's output —
        # bind = {"<spec path>": "<srcId>.<outputKey>"} (outputKey defaults to "actual"). A bind IS a
        # dependency, so its source joins `uses`. Fail-closed: if the source is not confirmed or the
        # output key is absent, the binding is UNRESOLVED and the step is NOT verified with a fabricated
        # value — it becomes a GAP, never a guessed HOLDS and never a MISMATCH manufactured from our own
        # inability to resolve a ref. Substitution is into a deep copy, so the caller's spec is never
        # mutated and the spec_hash below binds the seal to exactly what was checked.
        bind = step.get("bind")
        unresolved: List[str] = []
        if isinstance(bind, dict) and bind:
            spec = copy.deepcopy(spec)
            for path, ref in bind.items():
                src_id, _, key = str(ref).partition(".")
                key = key or "actual"
                if src_id not in uses:
                    uses.append(src_id)
                src_data = data_by_id.get(src_id)
                if src_id not in confirmed_ids or not isinstance(src_data, dict) or key not in src_data:
                    unresolved.append("%s<-%s" % (path, ref))
                    continue
                _set_spec_path(spec, str(path), src_data[key])

        missing = [u for u in uses if u not in seen_ids]
        unconfirmed = [u for u in uses if u in seen_ids and u not in confirmed_ids]
        link_ok = not missing and not unconfirmed and not unresolved

        if unresolved:
            # the step could not be BUILT — we cannot check what we could not assemble. A gap, never a
            # false verdict; the dependency gating below still records what it stood on.
            sr: Dict[str, Any] = {"status": "NOT_APPLICABLE",
                                  "detail": "unresolved binding(s): " + ", ".join(unresolved), "data": {}}
        else:
            # the smallest bucket: exactly these bytes under exactly this verifier — a hit is served, not recomputed
            from concordance import bucket as _bucket
            _sh = _spec_hash(spec)
            sr = _bucket.through(domain, _sh, lambda: verify_step(domain, spec))
        st = sr["status"]

        entry: Dict[str, Any] = {
            "id": sid, "domain": domain, "claim": str(step.get("claim", "")),
            "uses": uses, "status": st, "detail": sr.get("detail", ""), "link_ok": link_ok,
            # the fingerprint of exactly what was checked — travels into the seal so the verdict is bound
            # to its artifact, not the free-text label. For a bound step this is the SUBSTITUTED spec, so
            # the seal binds to what was actually verified.
            "spec_hash": _spec_hash(spec),
            "_spec": spec,          # the exact packet checked; receipts.attach files it beside the seal, then drops it
        }
        # Kind B — surface a verifier's framing (explanation + the question that would let us
        # calculate) so a decline is actionable, not a dead end. Only the curated framing fields
        # travel out, never the verifier's whole internal data dict.
        if sr.get("refutations"):
            entry["refutations"] = sr["refutations"]
        if sr.get("memo"):
            entry["memo"] = sr["memo"]
        _g = sr.get("data") or {}
        _framing = {k: _g[k] for k in ("framing_question", "need", "example", "route") if k in _g}
        if _framing:
            entry["guidance"] = _framing
        if missing:
            entry["missing_refs"] = missing
        if unconfirmed:
            entry["builds_on_unconfirmed"] = unconfirmed
        if unresolved:
            entry["unresolved_binding"] = unresolved
        trail.append(entry)
        seen_ids.add(sid)
        domain_by_id[sid] = domain

        # Classify this step's EFFECTIVE outcome. A step that builds on unconfirmed ground cannot
        # stand — but WHY its ground is unconfirmed decides the honest verdict. Collapsing "our
        # engine failed on a step you depend on" (ERROR) or "we had no verifier for it" (gap) into
        # BROKEN would downgrade the caller's claim on the strength of our own failure — the very
        # inversion of the kernel's fifth clause. Only a genuine MISMATCH may propagate a break.
        if st == "MISMATCH":
            outcome = "BROKEN"
        elif st == "ERROR":
            outcome = "ERROR"             # our failure, never the caller's falsehood
        elif st == "NOT_APPLICABLE":
            outcome = "GAP"               # no verifier applied — a gap, never a falsehood
        elif st == "CONFIRMED":
            outcome = "CONFIRMED" if link_ok else _worst_dep_outcome(uses)
        else:
            outcome = "ERROR"             # unknown status = our failure, never the caller's

        # THE SEAM — a cross-domain BRIDGE (registry §4). A step that CONSUMES a step from another
        # domain must not launder rigor across the boundary: a p-value asserted as PROOF, a scaling
        # law with no dimensional analysis. The single-domain verifier above cannot see the join; this
        # does. A category error at the seam BREAKS; a crossing whose justification is absent is a GAP
        # (unproven, never a false HOLDS). Only checked on a genuine cross-domain `uses` edge.
        for u in uses:
            dep_dom = domain_by_id.get(u)
            if not dep_dom or dep_dom == domain:
                continue
            bres = _bridges.check(domain, step, dep_dom)
            bst = bres.get("status")
            if bst == "MISMATCH":
                entry["bridge"] = bres
                outcome = "BROKEN"
                break
            if bst == "INCOMPLETE" and outcome == "CONFIRMED":
                entry["bridge"] = bres
                outcome = "GAP"

        outcome_by_id[sid] = outcome
        if outcome == "CONFIRMED":
            confirmed_ids.add(sid)
            data_by_id[sid] = sr.get("data") or {}   # this step's outputs, available to bind downstream
        elif outcome == "BROKEN":
            if broken_at is None:
                broken_at = sid
        elif outcome == "ERROR":
            if error_at is None:
                error_at = sid
        else:  # GAP
            if gap_at is None:
                gap_at = sid

    # Precedence: a real falsehood governs even if our engine also stumbled elsewhere.
    if broken_at is not None:
        verdict = "BROKEN"
    elif error_at is not None:
        verdict = "SYSTEM_ERROR"
    elif gap_at is not None:
        verdict = "INCOMPLETE"
    else:
        verdict = "HOLDS"

    agg = {"attempted": 0, "survived": 0, "counterexamples": 0, "errored": 0, "not_applicable": 0}
    for t in trail:
        for k in agg:
            agg[k] += len((t.get("refutations") or {}).get(k) or [])
    out = {
        "verdict": verdict,
        "read": _read(verdict, agg),
        "refutations": agg,
        "trace": _trace_45fcd3c(trail),
        # the Bayesian discount on a survival, from the recorded benchmark counts — only a HOLDS carries one
        "trust": _trust() if verdict == "HOLDS" else None,
        "steps": len(steps),
        "confirmed_steps": len(confirmed_ids),
        "broken_at": broken_at,
        "gap_at": gap_at,
        "error_at": error_at,
        "trail": trail,
        "note": ("The trail is the trust: each step is machine-verified and may build "
                 "only on confirmed prior steps. The engine verifies a provided "
                 "derivation; it does not generate the answer."),
    }
    if verdict == "SYSTEM_ERROR":
        out["means"] = ("OUR engine could not perform this check — this is a failure on our side "
                        "and says NOTHING about whether the claim is true. Do not read it as a "
                        "refutation.")
    return out


# ── the steps: ORDER_FREE (each listed dependency-sorted), OUTCOMES, VERDICT, SORTED, REPEATED and the inline
# derivations below are in the tier, tests/fixtures/derivation_tier.py ─────────────────────────────────────────
FIELDS = ("status", "link_ok", "uses", "missing_refs", "builds_on_unconfirmed", "unresolved_binding", "bridge",
          "spec_hash")


def by_id(r):
    """The fields compared across orders, by step id: the trail's, and the trace's distance and stands_on."""
    out = {t["id"]: {f: t.get(f) for f in FIELDS} for t in r["trail"]}
    for e in r["trace"]["events"]:
        out[e["id"]].update(distance=e["distance"], stands_on=e["stands_on"])
    return out


def kind(v):
    return "BROKEN" if v.r else "CONFIRMED" if v.p else "ERROR" if "error" in v.why else "GAP"


class Recorder:
    """Wraps the three module-level functions verify_derivation computes through and keeps what each returned:
    every settling return of _transfer (one per listed step), every _meet and every _readout."""

    def __init__(self, monkeypatch):
        self._t, self._m, self._r = D._transfer, D._meet, D._readout
        monkeypatch.setattr(D, "_transfer", self.transfer)
        monkeypatch.setattr(D, "_meet", self.meet)
        monkeypatch.setattr(D, "_readout", self.readout)

    def transfer(self, node, own, deps, halt=""):
        out = self._t(node, own, deps, halt)
        if out is not None:
            self.settled.append((node["id"], out))
        return out

    def meet(self, values):
        values = list(values)
        out = self._m(values)
        self.meets.append((values, out))
        return out

    def readout(self, c):
        out = self._r(c)
        self.reads.append((c, out))
        return out

    def run(self, steps):
        self.settled, self.meets, self.reads = [], [], []
        return D.verify_derivation(copy.deepcopy(steps))

    def outcomes(self):
        """Each step's effective outcome and whether it originates it (unique ids only)."""
        return {sid: (kind(v), bool(origin)) for sid, (v, origin, _) in self.settled}

    def originators(self):
        o = self.outcomes()
        return {k: {sid for sid, (kk, origin) in o.items() if origin and kk == k} for k, _ in POINTERS}


def strip(r):
    """45fcd3c's fields: everything but the note string and the new halting record."""
    return {k: v for k, v in r.items() if k not in ("note", "halt")}


# ── RED TO GREEN ──────────────────────────────────────────────────────────────────────────────────────────
def test_the_reversed_two_step_derivation_holds():
    """Measured red at 45fcd3c: [a, b uses a] HOLDS and [b uses a, a] INCOMPLETE (gap_at b, missing_refs a)."""
    a, b = copy.deepcopy(TWO_STEP)
    fwd, rev = D.verify_derivation([a, b]), D.verify_derivation([b, a])
    assert fwd["verdict"] == "HOLDS"
    assert rev["verdict"] == "HOLDS", (rev["verdict"], rev["gap_at"], [t.get("missing_refs") for t in rev["trail"]])
    assert by_id(rev) == by_id(fwd)
    assert rev["confirmed_steps"] == fwd["confirmed_steps"] == 2


# ── ORDER-FREE, PINNED BY VALUE ───────────────────────────────────────────────────────────────────────────
def _pins(name, r):
    t = {e["id"]: e for e in r["trail"]}
    if name == "bind from a false source":
        assert t["c"]["status"] == "NOT_APPLICABLE"
        assert t["c"]["unresolved_binding"] == ["GEOM_VERIFY.rect_length<-a.actual_area"]
    if name == "bridge MISMATCH":
        assert t["m"]["bridge"]["status"] == "MISMATCH" and t["m"]["bridge"]["bridge"] == "theory_inference"
    if name == "bridge INCOMPLETE":
        assert t["m"]["bridge"]["status"] == "INCOMPLETE" and t["m"]["bridge"]["bridge"] == "scale_regime"
    if name == "erroring dependency":
        assert r["error_at"] == "e"


@pytest.mark.parametrize("name", sorted(ORDER_FREE))
def test_every_listing_order_gives_the_same_fields_by_step_id(name, monkeypatch):
    rec = Recorder(monkeypatch)
    first = None
    for perm in itertools.permutations(ORDER_FREE[name]):
        listed = [s["id"] for s in perm]
        r = rec.run(list(perm))
        got = {"fields": by_id(r), "verdict": r["verdict"], "confirmed_steps": r["confirmed_steps"],
               "outcomes": rec.outcomes()}
        if first is None:
            first = got
        assert got == first, (name, listed)
        # the pinned value, in this order
        assert r["verdict"] == VERDICT[name], (name, listed)
        assert got["outcomes"] == OUTCOMES[name], (name, listed)
        _pins(name, r)
        # each pointer names the first originator of its kind in this listing, so with at most one
        # originator of a kind the pointer is the same in every order
        for k, field in POINTERS:
            orig = rec.originators()[k]
            assert r[field] == next((sid for sid in listed if sid in orig), None), (name, listed, field)
            if len(orig) <= 1:
                assert r[field] == (next(iter(orig)) if orig else None), (name, listed, field)


@pytest.mark.parametrize("name", sorted(SORTED))
def test_a_dependency_sorted_listing_returns_every_field_45fcd3c_returns(name):
    steps = SORTED[name]
    new = D.verify_derivation(copy.deepcopy(steps))
    old = verify_derivation_45fcd3c(copy.deepcopy(steps))
    assert set(new) - set(old) == {"halt"}
    assert strip(new) == strip(old)
    assert new["halt"]["reason"] == "settled"


# ── WHERE TRUST STOPPED ───────────────────────────────────────────────────────────────────────────────────
def test_a_cycle_of_holding_steps_originates_its_gap_at_every_member(monkeypatch):
    rec = Recorder(monkeypatch)
    for perm in itertools.permutations(CYCLE):
        r = rec.run(list(perm))
        assert r["verdict"] == "INCOMPLETE"
        assert rec.originators() == {"BROKEN": set(), "GAP": {"a", "b"}, "ERROR": set()}
        assert r["gap_at"] == perm[0]["id"] and r["broken_at"] is None and r["error_at"] is None
        for t in r["trail"]:
            assert t["unsettled"] == "cycle" and t["cycle"] == ["a", "b"]     # the cycle named


def test_an_error_beneath_a_missing_reference_stays_where_45fcd3c_put_it(monkeypatch):
    """[e: unknown math mode, b uses e and an absent z]: error_at e and gap_at null, as at 45fcd3c — b's
    outcome is the ERROR it stands on, which it does not originate."""
    rec = Recorder(monkeypatch)
    for perm in itertools.permutations(SORTED["mixed error and missing"]):
        r = rec.run(list(perm))
        assert r["verdict"] == "SYSTEM_ERROR"
        assert (r["error_at"], r["gap_at"], r["broken_at"]) == ("e", None, None)
        assert rec.outcomes() == {"e": ("ERROR", True), "b": ("ERROR", False)}


def test_holds_if_and_only_if_no_step_originates_a_break_a_gap_or_an_error():
    cases = list(ORDER_FREE.values()) + list(SORTED.values()) + [
        CYCLE,
        FALSE_SELF_CYCLE,
        REPEATED["two true a, nobody uses a"][0],
        ERROR_BESIDE_FALSE,
    ]
    seen = set()
    for steps in cases:
        for perm in itertools.permutations(steps):
            r = D.verify_derivation(copy.deepcopy(list(perm)))
            none = r["broken_at"] is None and r["gap_at"] is None and r["error_at"] is None
            assert (r["verdict"] == "HOLDS") == none, r["verdict"]
            seen.add(r["verdict"])
    assert seen == {"HOLDS", "BROKEN", "INCOMPLETE", "SYSTEM_ERROR"}


# ── NEVER HOLDS ON NO GROUND ──────────────────────────────────────────────────────────────────────────────
def test_a_cycle_whose_members_hold_stays_incomplete_with_the_cycle_named():
    for steps, cycle in ((SELF_CYCLE, ["a"]),
                         (CYCLE_AND_RESTING, ["a", "b"])):
        for perm in itertools.permutations(steps):
            r = D.verify_derivation(copy.deepcopy(list(perm)))
            assert r["verdict"] == "INCOMPLETE"
            t = {e["id"]: e for e in r["trail"]}
            for sid in cycle:
                assert t[sid]["cycle"] == cycle and t[sid]["unsettled"] == "cycle"
            if "c" in t:                      # resting on the cycle: unsettled, a gap, never its origin
                assert t["c"]["unsettled"] == "rests on a cycle" and "cycle" not in t["c"]
                assert t["c"]["builds_on_unconfirmed"] == ["a"] and r["gap_at"] in cycle


def test_a_cycle_with_a_false_member_is_broken_in_every_order():
    for steps in (FALSE_SELF_CYCLE,
                  FALSE_CYCLE):
        for perm in itertools.permutations(steps):
            r = D.verify_derivation(copy.deepcopy(list(perm)))
            assert r["verdict"] == "BROKEN" and r["broken_at"] == "a"


def test_a_reference_to_an_id_no_step_carries_stays_incomplete():
    r = D.verify_derivation([num("a", "2+2", 4, uses=["z"])])
    assert r["verdict"] == "INCOMPLETE" and r["trail"][0]["missing_refs"] == ["z"] and r["gap_at"] == "a"
    r = D.verify_derivation([rect("b", None, 1, 24, bind={"GEOM_VERIFY.rect_length": "z.actual_area"})])
    assert r["verdict"] == "INCOMPLETE" and r["trail"][0]["unresolved_binding"] == ["GEOM_VERIFY.rect_length<-z.actual_area"]


def test_an_empty_derivation_keeps_its_verdict():
    for given in ([], None, "steps"):
        assert D.verify_derivation(given) == verify_derivation_45fcd3c(given)
        assert D.verify_derivation(given)["verdict"] == "SYSTEM_ERROR"


def _counted(monkeypatch):
    calls: Dict[str, int] = {}
    real = D.verify_step

    def counting(domain, spec):
        h = D._spec_hash(spec)
        calls[h] = calls.get(h, 0) + 1
        return real(domain, spec)

    monkeypatch.setattr(D, "verify_step", counting)
    return calls


@pytest.mark.parametrize("name", sorted(REPEATED))
def test_a_repeated_id_is_never_holds(name, monkeypatch):
    steps, verdict = REPEATED[name]
    calls = _counted(monkeypatch)
    for perm in itertools.permutations(steps):
        calls.clear()
        r = D.verify_derivation(copy.deepcopy(list(perm)))
        assert r["verdict"] == verdict, (name, [s["id"] for s in perm])
        for t in r["trail"]:
            if [s["id"] for s in steps].count(t["id"]) > 1:
                assert t["repeated_id"] == 2                       # the repetition, named
            if t["id"] == "b" and "bind" in steps[-1]:
                assert t["unresolved_binding"] == ["GEOM_VERIFY.rect_length<-a.actual_area"]
        if steps[-1].get("claim") == PROOF:
            assert r["broken_at"] == "m" and r["trail"][[s["id"] for s in perm].index("m")]["bridge"]["status"] == "MISMATCH"
        # every listed step verified once, unless its own bind is unresolved
        want: Dict[str, int] = {}
        for t in r["trail"]:
            if not t.get("unresolved_binding"):
                want[t["spec_hash"]] = want.get(t["spec_hash"], 0) + 1
        assert calls == want


def test_a_default_id_colliding_with_an_explicit_one_is_never_holds():
    """Measured at 45fcd3c as HOLDS: [id s1: 5x6=30, no id (so s1): 4x6=24, b binds s1.actual_area claims 24]."""
    r = D.verify_derivation(copy.deepcopy(DEFAULT_ID_COLLISION))
    assert r["verdict"] != "HOLDS"
    t = r["trail"]
    assert t[0]["repeated_id"] == t[1]["repeated_id"] == 2 and t[1]["id"] == "s1"
    assert t[2]["unresolved_binding"] == ["GEOM_VERIFY.rect_length<-s1.actual_area"]


# ── THE WIRING ────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", sorted(ORDER_FREE))
def test_verify_derivation_computes_through_transfer_meet_and_readout(name, monkeypatch):
    """So the laws (tests/test_derivation_laws.py) cannot pass on functions verify_derivation never calls."""
    rec = Recorder(monkeypatch)
    for perm in itertools.permutations(ORDER_FREE[name]):
        listed = [s["id"] for s in perm]
        r = rec.run(list(perm))
        # every step's effective outcome is returned by _transfer, exactly once
        assert sorted(sid for sid, _ in rec.settled) == sorted(listed)
        value = {sid: v for sid, (v, _, _) in rec.settled}
        # the composite is _readout over _meet over exactly those outcomes, in listed order
        assert len(rec.meets) == 1 and len(rec.reads) == 1
        values, met = rec.meets[0]
        assert values == [value[sid] for sid in listed]
        assert rec.reads[0] == (met, r["verdict"])
        assert r["confirmed_steps"] == sum(1 for v in value.values() if v.p)
