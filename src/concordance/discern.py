"""discern — the proposal half of the engine, laid open. No verdict, no seal.

Bring plain text; get back what kind of thing it is, the de-identified claim that would be checked,
the structured (domain, spec) steps the extractor recognised, and the domain the resolver would
hint. The caller hands `claims` to `verify` to dispose. Crisis is discerned first and never routed to
arithmetic. Deterministic; nothing is generated.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import audit, text as _text

KINDS = ("empty", "crisis", "claim", "no_claim")


def discern(text: str) -> Dict[str, Any]:
    t = (str(text) if text else "").strip()
    base: Dict[str, Any] = {"input": text, "proposes": True, "confirms": False, "generated": False}
    if not t:
        return {**base, "kind": "empty", "claims": [], "next": "ask_user",
                "why": "nothing was brought"}
    if _text.is_crisis(t):
        return {**base, "kind": "crisis", "claims": [], "next": "real_help",
                "message": _text.CRISIS_RESPONSE, "why": "safety outranks arithmetic"}

    # de-identify: the extractor and the verifier see only the skeleton
    skeleton, held = _strip(t)
    steps = audit.extract(skeleton)
    try:
        audit.compose_uses(steps, skeleton)   # "A, so B": B carries a `uses` edge to A; the gate checks the link
    except Exception:  # noqa: BLE001
        pass
    hint = _hint(skeleton)
    claims: List[Dict[str, Any]] = []
    for s in steps:
        c = {"id": s.get("id"), "domain": s.get("domain"), "spec": s.get("spec"), "span": s.get("claim")}
        if s.get("uses"):
            c["uses"] = s["uses"]
        claims.append(c)
    if claims:
        return {**base, "kind": "claim", "checked_text": skeleton, "held_back": held,
                "claims": claims, "domain_hint": hint, "next": "verify",
                "why": f"{len(claims)} checkable claim(s) recognised; send `claims` as steps to verify"}
    return {**base, "kind": "no_claim", "checked_text": skeleton, "held_back": held, "claims": [],
            "domain_hint": hint, "structured": audit.structured_hint(skeleton), "next": "find_verifier",
            "why": ("no deterministic extractor recognised a checkable claim; this says nothing about "
                    "whether the text is true. Use find_verifier for the domain's packet schema and send "
                    "the structured form.")}


def _strip(t: str):
    """De-identify through the airlock; return (skeleton, count of held items). Falls back to the raw
    text if the airlock is unavailable — the extractor only reads numbers and units anyway."""
    try:
        from . import airlock
        a = airlock.through(t, lambda s: s)
        if a.ok and isinstance(a.result, str):
            return a.checked, len(a.held_pii)
        return t, 0
    except Exception:  # noqa: BLE001
        return t, 0


def _hint(t: str) -> Optional[Dict[str, Any]]:
    try:
        from .domain_resolver import resolve_domain
        r = resolve_domain(t)
        return r if isinstance(r, dict) else {"domain": r}
    except Exception:  # noqa: BLE001
        return None


__all__ = ["discern", "KINDS"]
