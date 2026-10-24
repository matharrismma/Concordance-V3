"""scribe — score one pass of a multi-writer draft against the deterministic engine.

Ported from the 2026-10-20 prototype. The engine is the datum; the SVD over the writers × claims
matrix is a disagreement locator — it says WHERE writers read the spec differently, never whether
anyone is right. A flat spectrum (no dominant disagreement axis, yet real spread) is UNDERDETERMINED
and is returned as such; nothing is ever averaged into an answer.

Inputs
  drafts    [{writer, draft?, claims: [{id, value, formula?}]}]   — one entry per writer
  packets   {claim_id: [steps]}                                   — recompute steps per claim id
            (steps as verify takes them: [{id, domain, spec}]); the claimed value is substituted
            wherever a step's spec carries "<value>" or the key named by `value_key`
  claim_ids optional explicit column order

A Writer is anything with write(spec: str, feedback: str | None) -> {draft, claims}. The core ships
no LLM client; the demo in tools/ shows stub writers.
"""
from __future__ import annotations

import copy
import json
from typing import Any, Dict, List, Optional, Protocol

from ..derivation import verify_derivation


class Writer(Protocol):
    name: str

    def write(self, spec: str, feedback: Optional[str] = None) -> Dict[str, Any]: ...


# ── matrix ─────────────────────────────────────────────────────────────────────────────────────────
def claim_matrix(drafts: List[Dict[str, Any]], claim_ids: Optional[List[str]] = None):
    """Rows = writers, columns = claims, cells = the stated value (None if missing)."""
    writers = [str(d.get("writer") or f"w{i + 1}") for i, d in enumerate(drafts)]
    if not claim_ids:
        seen: List[str] = []
        for d in drafts:
            for c in d.get("claims") or []:
                if isinstance(c, dict) and c.get("id") and c["id"] not in seen:
                    seen.append(c["id"])
        claim_ids = seen
    M: List[List[Optional[float]]] = []
    for d in drafts:
        by = {c.get("id"): c for c in (d.get("claims") or []) if isinstance(c, dict)}
        row = []
        for cid in claim_ids:
            v = (by.get(cid) or {}).get("value")
            row.append(float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None)
        M.append(row)
    return writers, claim_ids, M


def spectrum(M: List[List[Optional[float]]], claim_ids: List[str]) -> Dict[str, Any]:
    """Column-normalise by the median, centre, SVD. Returns singular values, the top axis (which claims
    carry the disagreement), its share of the variance, and the spread (RMS row norm)."""
    try:
        import numpy as np
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("scribe needs numpy (pip install numpy)") from e
    A = np.array([[np.nan if v is None else v for v in row] for row in M], dtype=float)
    if A.size == 0 or A.shape[0] < 2:
        return {"singular_values": [], "top_axis": [], "top_axis_share": None, "spread": 0.0,
                "means": "fewer than two writers; no disagreement to locate"}
    med = np.nanmedian(A, axis=0)
    med = np.where((med == 0) | np.isnan(med), 1.0, med)
    R = A / med
    R = np.where(np.isnan(R), 1.0, R)          # a missing claim sits at the centre; it carries no weight here
    C = R - R.mean(axis=0)
    U, S, Vt = np.linalg.svd(C, full_matrices=False)
    tot = float((S ** 2).sum())
    share = float(S[0] ** 2 / tot) if tot > 1e-18 else None
    axis = [(claim_ids[j], float(Vt[0, j])) for j in np.argsort(-np.abs(Vt[0]))[:4]] if tot > 1e-18 else []
    spread = float(np.sqrt((C ** 2).sum() / A.shape[0]))
    return {"singular_values": [float(x) for x in S], "top_axis": axis, "top_axis_share": share,
            "spread": spread, "row_norms": [float(np.linalg.norm(C[i])) for i in range(A.shape[0])],
            "means": "columns normalised by their median and centred; the top right-singular vector names the "
                     "claims the writers disagree on most; share = its fraction of total variance"}


# ── verification ───────────────────────────────────────────────────────────────────────────────────
def _fill(steps: List[Dict[str, Any]], value: float, value_key: str) -> List[Dict[str, Any]]:
    out = copy.deepcopy(steps)

    def walk(o):
        if isinstance(o, dict):
            for k, v in list(o.items()):
                if v == "<value>" or k == value_key:
                    o[k] = float(value)
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(out)
    return out


def verify_matrix(writers, claim_ids, M, packets: Dict[str, List[Dict[str, Any]]],
                  value_key: str = "claimed_value") -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Run the recompute packets for every (writer, claim). Verdict per cell: CONFIRMED | MISMATCH |
    MISSING (no value) | NO_PACKET (no recompute defined) | plus the engine detail."""
    out: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for i, w in enumerate(writers):
        out[w] = {}
        for j, cid in enumerate(claim_ids):
            v = M[i][j]
            if v is None:
                out[w][cid] = {"verdict": "MISSING", "detail": "no value stated"}
                continue
            steps = packets.get(cid)
            if not steps:
                out[w][cid] = {"verdict": "NO_PACKET", "detail": "no recompute packet for this claim"}
                continue
            r = verify_derivation(_fill(steps, v, value_key))
            t0 = r["trail"][0] if r.get("trail") else {}
            st = t0.get("status", r.get("verdict"))
            cell = {"verdict": "CONFIRMED" if r.get("verdict") == "HOLDS" else
                    ("MISMATCH" if r.get("verdict") == "BROKEN" else str(st)),
                    "detail": (t0.get("detail") or "")[:240]}
            ref = t0.get("refutations") or {}
            if ref.get("bands"):
                b = ref["bands"][0]
                cell["band"] = [b.get("low"), b.get("high")]
                cell["off_by"] = b.get("off_by")
            out[w][cid] = cell
    return out


def narrow_way(writers, claim_ids, M, verdicts) -> Dict[str, Any]:
    """Elimination, per claim: the band the recompute names, which stated values fell outside it (eliminated,
    with how far), and which survived. The answer is never the average of the drafts; it is what is left after
    the verifier has killed what it can — the narrow way. A claim with no band (no packet, or a verifier that
    has not adopted band()) is reported as un-narrowed."""
    out: Dict[str, Any] = {}
    for j, cid in enumerate(claim_ids):
        band = None
        eliminated, surviving, unknown = [], [], []
        for i, w in enumerate(writers):
            v = M[i][j]
            cell = verdicts[w][cid]
            if cell.get("band") and band is None:
                band = cell["band"]
            if v is None:
                continue
            if cell["verdict"] == "MISMATCH":
                eliminated.append({"writer": w, "value": v, "off_by": cell.get("off_by")})
            elif cell["verdict"] == "CONFIRMED":
                surviving.append({"writer": w, "value": v})
            else:
                unknown.append({"writer": w, "value": v, "why": cell["verdict"]})
        # the bracket: minimum and maximum of what survived (or, un-narrowed, of everything stated), cut to
        # the band. Two bounds make the optimum easy to find; a single point does not.
        pool = [x["value"] for x in surviving] or [x["value"] for x in unknown]
        bracket = None
        if pool:
            mn, mx = min(pool), max(pool)
            if band:
                lo, hi = band
                mn = max(mn, lo) if lo is not None else mn
                mx = min(mx, hi) if hi is not None else mx
            bracket = {"min": mn, "max": mx, "from": "surviving" if surviving else "stated, unverified"}
        out[cid] = {"band": band, "bracket": bracket, "eliminated": eliminated, "surviving": surviving,
                    "unnarrowed": unknown,
                    "state": ("narrowed" if band and (surviving or eliminated) else "un-narrowed")}
    return out


# ── the pass report ────────────────────────────────────────────────────────────────────────────────
FLAT_SHARE = 0.5      # below this, no single axis explains the disagreement
SPREAD_TOL = 1e-4     # relative RMS spread; CONVERGED also requires zero broken recomputes, which is the real guard


def score_pass(drafts: List[Dict[str, Any]], packets: Optional[Dict[str, List[Dict[str, Any]]]] = None,
               claim_ids: Optional[List[str]] = None, value_key: str = "claimed_value") -> Dict[str, Any]:
    writers, ids, M = claim_matrix(drafts, claim_ids)
    spec = spectrum(M, ids)
    verdicts = verify_matrix(writers, ids, M, packets or {}, value_key)
    broken = {w: [cid for cid in ids if verdicts[w][cid]["verdict"] in ("MISMATCH", "MISSING")] for w in writers}
    clean = [w for w in writers if not broken[w]]
    norms = spec.get("row_norms") or [0.0] * len(writers)
    center = min(clean, key=lambda w: norms[writers.index(w)]) if clean else None
    divergent = {}
    for j, cid in enumerate(ids):
        col = [M[i][j] for i in range(len(writers)) if M[i][j] is not None]
        if len(col) > 1 and max(col) != min(col):
            ref = sorted(col)[len(col) // 2] or 1.0
            if (max(col) - min(col)) / abs(ref) > 1e-6:
                divergent[cid] = sorted(col)
    status = "CONVERGED" if (spec["spread"] <= SPREAD_TOL and clean and not any(broken.values())) else \
             ("UNDERDETERMINED" if (spec["top_axis_share"] is not None and spec["top_axis_share"] < FLAT_SHARE
                                    and spec["spread"] > SPREAD_TOL) else "OPEN")
    nw = narrow_way(writers, ids, M, verdicts)
    n_elim = sum(len(c["eliminated"]) for c in nw.values())
    n_surv = sum(len(c["surviving"]) for c in nw.values())
    n_narrowed = sum(1 for c in nw.values() if c["state"] == "narrowed")
    read = (f"{n_elim} stated value{'s' if n_elim != 1 else ''} eliminated by counterexample, {n_surv} inside "
            f"the band, across {n_narrowed} of {len(ids)} claims narrowed; status {status}")
    report = {"status": status, "read": read, "writers": writers, "claim_ids": ids, "matrix": M, "spectrum": spec,
              "verdicts": verdicts, "broken": broken, "broken_total": sum(len(v) for v in broken.values()),
              "narrow_way": nw,
              "clean_writers": clean, "center": center, "divergent": divergent,
              "means": {"status": "CONVERGED: spread at tolerance and every writer passes every recompute; "
                                  "UNDERDETERMINED: real spread with no dominant axis — the spec is ambiguous, "
                                  "do not average; OPEN: a dominant disagreement axis or broken claims remain",
                        "center": "the clean draft nearest the centroid — never an average of drafts",
                        "narrow_way": "per claim: the band the recompute names, the values it eliminated and by how "
                                      "much, the values that survived, and the bracket [min, max] of the survivors "
                                      "cut to the band; the answer is what is left, not a mean",
                        "spectrum": "locates disagreement; it is not evidence of truth (writers sharing training "
                                    "data share errors)"}}
    report["feedback"] = {w: feedback(report, w) for w in writers}
    return report


def feedback(report: Dict[str, Any], writer: str) -> str:
    """What one writer is told before the next pass: the engine's verdicts on ITS claims and the values the
    group diverges on (unattributed). Never the truth, never another writer's draft."""
    L = [f"Pass report for {writer}: status {report['status']}."]
    sp = report["spectrum"]
    if sp.get("top_axis"):
        L.append("Disagreement axis (" + (f"{sp['top_axis_share']:.0%}" if sp.get("top_axis_share") else "n/a") +
                 " of variance): " + ", ".join(f"{c} ({w:+.2f})" for c, w in sp["top_axis"]) + ".")
    L.append("Engine verdicts on your claims:")
    for cid in report["claim_ids"]:
        v = report["verdicts"][writer][cid]
        if v["verdict"] == "MISMATCH" and v.get("band"):
            # the counterexample, not the answer: the band the value must lie in and how far outside it fell
            L.append(f"- {cid}: ELIMINATED — your value is outside [{v['band'][0]:,.6g}, {v['band'][1]:,.6g}] "
                     f"by {v.get('off_by') or 0:+,.6g}; recompute from the packet")
        else:
            L.append(f"- {cid}: {v['verdict']}" + ("" if v["verdict"] == "CONFIRMED" else f" — {v['detail']}"))
    if report["divergent"]:
        L.append("Values the writers diverge on (no names):")
        for cid, vals in report["divergent"].items():
            L.append(f"- {cid}: " + ", ".join(f"{x:,.6g}" for x in vals))
    L.append("Resolve every MISMATCH and every divergent claim from the spec text. Return the full draft and all claims.")
    return "\n".join(L)


def run(writers: List[Writer], spec: str, packets: Dict[str, List[Dict[str, Any]]], passes: int = 3,
        claim_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Drive N writers for up to `passes` rounds. Returns the list of pass reports; stops early on CONVERGED
    or UNDERDETERMINED. Context is the caller's business: pass a de-identified spec and reapply afterwards."""
    reports: List[Dict[str, Any]] = []
    fb: Dict[str, Optional[str]] = {w.name: None for w in writers}
    for _ in range(passes):
        drafts = []
        for w in writers:
            d = w.write(spec, fb.get(w.name))
            drafts.append({"writer": w.name, **d})
        rep = score_pass(drafts, packets, claim_ids)
        rep["drafts"] = drafts
        reports.append(rep)
        if rep["status"] in ("CONVERGED", "UNDERDETERMINED"):
            break
        fb = rep["feedback"]
    return reports


__all__ = ["Writer", "claim_matrix", "spectrum", "verify_matrix", "score_pass", "feedback", "run",
           "FLAT_SHARE", "SPREAD_TOL"]
