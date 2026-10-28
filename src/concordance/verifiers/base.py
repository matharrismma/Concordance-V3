"""Verifier framework — the deterministic computational checks.

A verifier is a PURE function: it takes a spec and returns a VerifierResult.
No I/O, no LLM, no network. It either confirms the artifact's math/logic,
finds a mismatch, errors on malformed input, or declares itself not-applicable.

    CONFIRMED      — the artifact ran and agreed with the claim
    MISMATCH       — the artifact ran and contradicted the claim
    NOT_APPLICABLE — the relevant artifact was absent (verifier could not run)
    ERROR          — the artifact was present but malformed

Ported as-is from 1.0 — domain-neutral.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Literal, Optional, Sequence, Tuple, Union

VerifierStatus = Literal["CONFIRMED", "MISMATCH", "NOT_APPLICABLE", "ERROR"]


@dataclass(frozen=True)
class VerifierResult:
    name: str
    status: VerifierStatus
    detail: str = ""
    data: Optional[Dict[str, Any]] = None

    @property
    def passed(self) -> bool:
        return self.status == "CONFIRMED"

    @property
    def failed(self) -> bool:
        return self.status in ("MISMATCH", "ERROR")

    @property
    def applicable(self) -> bool:
        return self.status != "NOT_APPLICABLE"


def na(name: str, reason: str = "no artifact provided",
       data: Optional[Dict[str, Any]] = None) -> VerifierResult:
    return VerifierResult(name=name, status="NOT_APPLICABLE", detail=reason, data=data)


def confirm(name: str, detail: str = "", data: Optional[Dict[str, Any]] = None) -> VerifierResult:
    return VerifierResult(name=name, status="CONFIRMED", detail=detail, data=data)


def mismatch(name: str, detail: str, data: Optional[Dict[str, Any]] = None) -> VerifierResult:
    return VerifierResult(name=name, status="MISMATCH", detail=detail, data=data)


def error(name: str, detail: str, data: Optional[Dict[str, Any]] = None) -> VerifierResult:
    return VerifierResult(name=name, status="ERROR", detail=detail, data=data)


def band(name: str, actual: float, claimed: float, tol: float, what: str = "value",
         data: Optional[Dict[str, Any]] = None, *, fmt: str = "{:,.6g}", unit: str = "") -> VerifierResult:
    """The inverted comparison. A check does not find the true value; it names the BAND every true claim must
    lie in — [actual − tol, actual + tol] — and reports whether the claim is inside. Inside is a survived
    refutation (CONFIRMED); outside is a COUNTEREXAMPLE (MISMATCH) that carries the recomputed value, the band
    and the distance, so the refutation itself is re-runnable and stronger than any confirmation. `data.band`
    is the same shape either way; receipts and pages read it."""
    tol = abs(float(tol))
    lo, hi = actual - tol, actual + tol
    inside = lo <= claimed <= hi
    off = claimed - actual
    # margin: how much of the allowance the claim spent — 0 is dead centre, 1 is the edge, >1 is outside.
    # The OTDR reading of a check: a pass at 0.98 is a pass, but it is a splice you would redo.
    used = (abs(off) / tol) if tol > 0 else (0.0 if off == 0 else float("inf"))
    bd = {"what": what, "low": lo, "high": hi, "actual": actual, "claimed": claimed, "tolerance": tol,
          "inside": inside, "off_by": off, "used": used, "unit": unit}
    d = dict(data or {}, **{f"actual_{what}": actual, f"claimed_{what}": claimed, "band": bd})
    u = f" {unit}" if unit else ""
    if inside:
        return confirm(name, f"{what} = {fmt.format(actual)}{u}; claim inside [{fmt.format(lo)}, {fmt.format(hi)}]", d)
    d["counterexample"] = {"what": what, "claimed": claimed, "recomputed": actual, "band": [lo, hi], "off_by": off}
    return mismatch(name, f"{what} = {fmt.format(actual)}{u}; claimed {fmt.format(claimed)} is outside "
                          f"[{fmt.format(lo)}, {fmt.format(hi)}] (off by {off:+,.6g})", d)


def bound(name: str, value: float, limit: float, kind: str, what: str = "value",
          data: Optional[Dict[str, Any]] = None, *, fmt: str = "{:,.6g}", unit: str = "",
          tol: float = 0.0) -> VerifierResult:
    """A one-sided band: `kind` is "min" (value must be ≥ limit) or "max" (value must be ≤ limit). Minimum and
    maximum are how a constraint narrows; two of them bracket an optimum. `data.band` has the same shape as
    band() with the open side None, so receipts, the scribe and the page read both alike. A small `tol`
    forgives display rounding at the edge, never past it."""
    tol = abs(float(tol))
    if kind not in ("min", "max"):
        return error(name, f"bound kind must be 'min' or 'max', not {kind!r}")
    lo, hi = (limit, None) if kind == "min" else (None, limit)
    inside = (value >= limit - tol) if kind == "min" else (value <= limit + tol)
    off = (value - limit)
    # headroom for a bound: how close to the limit, as a share of the limit (0 = far, 1 = at the limit, >1 = over).
    # A bound has no allowance to spend, so `used` is the ratio value/limit folded onto the constrained side.
    if limit != 0:
        used = (limit / value) if (kind == "min" and value != 0) else ((value / limit) if kind == "max" else float("inf"))
        used = max(0.0, used)
    else:
        used = 0.0 if inside else float("inf")
    bd = {"what": what, "low": lo, "high": hi, "actual": value, "claimed": value, "tolerance": tol,
          "inside": inside, "off_by": off, "used": used, "unit": unit, "kind": kind}
    d = dict(data or {}, **{what: value, "band": bd})
    u = f" {unit}" if unit else ""
    sym = "≥" if kind == "min" else "≤"
    if inside:
        return confirm(name, f"{what} = {fmt.format(value)}{u} {sym} {fmt.format(limit)} (inside the bound)", d)
    d["counterexample"] = {"what": what, "claimed": value, "recomputed": value,
                           "band": [lo, hi], "off_by": off, "kind": kind}
    return mismatch(name, f"{what} = {fmt.format(value)}{u} violates {sym} {fmt.format(limit)} "
                          f"(outside by {abs(off):,.6g})", d)


def merge_checks(name: str, results: Sequence[VerifierResult], data: Optional[Dict[str, Any]] = None) -> VerifierResult:
    """Fold several band() results for one check into one VerifierResult without losing any band or
    counterexample: the first MISMATCH governs (a counterexample outranks any number of survivals), and
    `data.bands` keeps every band so the receipt can show the whole narrow way."""
    bands = [r.data["band"] for r in results if r.data and isinstance(r.data.get("band"), dict)]
    d = dict(data or {})
    for r in results:
        if r.data:
            d.update({k: v for k, v in r.data.items() if k not in ("band", "counterexample")})
    if bands:
        d["bands"] = bands
    bad = [r for r in results if r.status == "MISMATCH"]
    if bad:
        d["counterexample"] = (bad[0].data or {}).get("counterexample")
        d["band"] = (bad[0].data or {}).get("band")
        return mismatch(name, bad[0].detail, d)
    errs = [r for r in results if r.status == "ERROR"]
    if errs:
        return error(name, errs[0].detail, d)
    return confirm(name, "; ".join(r.detail for r in results if r.passed), d)


def clamp_tol(spec: Dict[str, Any], key: str, default: float) -> float:
    """Caller-supplied tolerance, clamped: a caller may TIGHTEN a tolerance but never LOOSEN
    it past the verifier's default — otherwise an adversarial caller could widen the window to
    force a CONFIRMED on a value that is actually wrong. Missing/malformed -> the default."""
    try:
        v = spec.get(key)
        if v is None:
            return default
        return min(abs(float(v)), abs(default))
    except (TypeError, ValueError):
        return default


_LITERAL = re.compile(r"[-+]?(\d*)(?:\.(\d*))?(?:[eE]([-+]?\d+))?")


_SCALE_WORDS = {"thousand": 1e3, "million": 1e6, "billion": 1e9, "trillion": 1e12,
                "k": 1e3, "m": 1e6, "mn": 1e6, "b": 1e9, "bn": 1e9}


def literal_scale(literal: Any) -> Tuple[str, float]:
    """The number AS WRITTEN and its scale: "$29.3 million" -> ("29.3", 1e6); "$5k" -> ("5", 1e3);
    "41,600" -> ("41,600", 1.0). The literal keeps its own digits so stated_precision reads the figures the
    person gave, and the scale word becomes a factor (the failure report's H5: "$29.3 million" was read as 29.3).
    A one-letter scale (k, M, B, bn) counts only when attached to a $-number ("$29.3M"); a spaced "m" is metres."""
    import re
    s = str(literal or "").strip()
    m = re.match(r"^\$?\s*(-?\d[\d,]*(?:\.\d+)?)\s*(thousand|million|billion|trillion)\b", s, re.I)
    if m:
        return m.group(1), _SCALE_WORDS[m.group(2).lower()]
    m = re.match(r"^\$\s*(-?\d[\d,]*(?:\.\d+)?)(k|m|mn|b|bn)\b", s, re.I)
    if m:
        return m.group(1), _SCALE_WORDS[m.group(2).lower()]
    m = re.match(r"^\$?\s*(-?\d[\d,]*(?:\.\d+)?)", s)
    return (m.group(1) if m else s), 1.0


def stated_precision(literal: Any) -> Optional[Tuple[int, float]]:
    """(significant figures, half a unit in the last stated place) of a number AS THE PERSON WROTE IT.

    "9.81" -> (3, 0.005)   "5730" -> (3, 5.0)   "3.0e8" -> (2, 5e6)   "3e8" -> (1, 5e7)   "0.0025" -> (2, 5e-5)
    A bare integer's trailing zeros are NOT counted significant ("300000000" is one figure) — the
    conservative reading, so a round number never claims more precision than it shows. None when the
    literal is not a number. Pure."""
    s = str(literal if literal is not None else "").strip().replace(",", "").replace(" ", "").replace("$", "")
    m = _LITERAL.fullmatch(s)
    if not m or not (m.group(1) or m.group(2)):
        return None
    ip, fp, ex = m.group(1) or "", m.group(2), int(m.group(3) or 0)
    if fp is not None:                       # a decimal point was written: every written decimal counts
        digits = (ip + fp).lstrip("0")
        return (len(digits) if digits else 1, 0.5 * 10.0 ** (ex - len(fp)))
    core = ip.lstrip("0")
    if not core:
        return (1, 0.5 * 10.0 ** ex)
    stripped = core.rstrip("0")
    trailing = len(core) - len(stripped)
    return (len(stripped), 0.5 * 10.0 ** (ex + trailing))


_HEDGE_RE = None


def hedged_before(before: Any) -> bool:
    """True when the text just before a claimed number ends in a hedge word: about, approximately, roughly,
    around, nearly, almost, close to, circa, an estimated, ~ or ≈. Pure."""
    global _HEDGE_RE
    import re
    if _HEDGE_RE is None:
        _HEDGE_RE = re.compile(r"(?:\b(?:about|approximately|approx|roughly|around|nearly|almost|close\s+to|circa|"
                               r"ca|an?\s+estimated|on\s+the\s+order\s+of)\.?|[~≈])\s*$", re.I)
    return bool(_HEDGE_RE.search(str(before or "")[-32:]))


def stated_window(literal: Any, hedged: bool = False, unit_factor: float = 1.0) -> Optional[float]:
    """THE ONE TOLERANCE RULE for a claim stated in words (2026-10-08, the failure report H6: "about 10 years"
    passed for 10.29, a one-year miss passed, "approximately 300,000 km/s" and "1 mile is 1.6 km" were BROKEN —
    four windows, four rules). Now one:
      * two or more significant figures -> half a unit in the last stated place ("9.81" -> ±0.005);
      * a hedge word doubles that to a full unit ("about 9.81" -> ±0.01) and GRANTS the half-unit window to a
        one-figure claim that otherwise earns none ("about 10" -> ±5; "approximately 300,000 km/s" -> ±50,000);
      * nothing else widens it: a one-figure claim with no hedge ("10", "3e8") is judged exactly.
    `unit_factor` scales the window into the computed unit (km/s judged in m/s: 1000). None = no window."""
    sp = stated_precision(literal)
    if sp is None:
        return None
    try:
        f = abs(float(unit_factor)) or 1.0
    except (TypeError, ValueError):
        f = 1.0
    sig, half = sp
    if sig >= 2:
        return (2.0 * half if hedged else half) * f
    return half * f if hedged else None


def window_for(spec: Dict[str, Any], literal_key: str, default: float, unit_factor: float = 1.0,
               actual: Optional[float] = None) -> Tuple[float, Dict[str, Any]]:
    """The threshold a verifier compares against, and what to record about it. No literal in the spec (the
    structured form): the verifier's own `default`, and nothing recorded. A literal (the plain-text form): the stated
    window — or EXACT (float noise only) when a one-figure claim carries no hedge, because nothing but the
    figures and a hedge may widen a prose claim's window. `hedged` rides in the spec beside the literal
    (audit.extract sets it when a hedge word precedes the number in the quote)."""
    lit = spec.get(literal_key)
    if lit in (None, ""):
        return default, {}
    hedged = bool(spec.get("hedged"))
    w = stated_window(lit, hedged, unit_factor)
    sp = stated_precision(lit)
    exact = 1e-9 * max(1.0, abs(float(actual))) if actual is not None else 1e-9
    info = {"stated_literal": str(lit), "stated_sigfigs": sp[0] if sp else None, "hedged": hedged,
            "stated_window": w if w is not None else 0.0,
            "rule": ("half a unit in the last stated place (two or more figures); a hedge word doubles it and "
                     "grants it to a one-figure claim; nothing else widens it")}
    return (w if w is not None else exact), info


def stated_tolerance_abs(literal: Any, unit_factor: float = 1.0) -> Optional[float]:
    """The absolute tolerance a claim EARNS from its own stated precision — half a unit in its last stated
    place, scaled to the verifier's unit by `unit_factor` (a claim in km/s judged in m/s: 1000) — or None
    when it earns none: an unreadable literal, or a single significant figure, so "3e8" or "300000000"
    never passes as the exact value. The claim's own literal is the ONLY thing that can widen a window;
    a caller never hands in a tolerance (cf. clamp_tol, which only ever tightens). (2026-10-07: "earth
    gravity is 9.81 m/s^2" was refused by a flat 1e-4 — right to every figure stated, called false.)"""
    sp = stated_precision(literal)
    if sp is None or sp[0] < 2:
        return None
    try:
        f = abs(float(unit_factor)) or 1.0
    except (TypeError, ValueError):
        f = 1.0
    return sp[1] * f


# A rule is (requirement, verify_fn). requirement is EITHER a sequence of keys that must ALL
# be present in the artifact, OR a callable(artifact)->bool for irregular conditions (or/
# is-not-None/non-empty). verify_fn is callable(artifact)->VerifierResult.
Requirement = Union[Sequence[str], Callable[[Dict[str, Any]], bool]]
Rule = Tuple[Requirement, Callable[[Dict[str, Any]], "VerifierResult"]]


def dispatch(packet: Dict[str, Any], artifact_key: str, rules: Iterable[Rule], *,
             domain: str, none_reason: str = "") -> List["VerifierResult"]:
    """Declarative run() driver — read ONE artifact, fire each matching rule, and apply
    UNIFORM present-vs-null handling: an absent artifact OR no rule firing yields exactly one
    na(domain, ...). This is behaviour-identical to the hand-written pattern

        art = packet.get(KEY) or {}
        if <keys present>: results.append(fn(art))   # for each rule
        if not results: results.append(na(domain, ...))

    but declarative and consistent, so every verifier reports "nothing applicable" the same
    way and a new check is one line in a rules table. A requirement is a tuple of required
    keys (ALL must be present) or a callable(artifact)->bool for or/is-not-None conditions."""
    art = packet.get(artifact_key) or {}
    out: List["VerifierResult"] = []
    for req, fn in rules:
        fires = req(art) if callable(req) else all(k in art for k in req)
        if fires:
            out.append(fn(art))
    if not out:
        out.append(na(domain, none_reason or f"no {artifact_key} artifacts present"))
    return out
