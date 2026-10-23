"""compose — receipts that stand on receipts.

A DOCUMENT is a derivation whose steps may bind their inputs to earlier steps' outputs (derivation.py's
`bind`), sealed as one content-addressed ROOT whose record names every step's spec_hash, status and
dependencies, the derivation seal that verified them, and any PARENT seals (a scribe pass, an earlier
version). Content addressing makes it a hash tree: change one input anywhere and the root changes.

    doc = {"title": "...", "steps": [{id, domain, spec, bind?, uses?, label?}, ...],
           "parents": ["<seal hash>", ...], "text": "optional prose with {step_id} references"}
    root = compose.seal_document(doc, config)
    -> {"root": "<hash>", "cite_url": "/s/<hash>", "verdict": ..., "steps": [...], "derivation_seal": {...}}

The root record is stored in the CAS like any seal (re-fetch it, re-hash it, it must match); its
derivation seal is ledgered. No new primitive: claim, verifier, seal — applied to their own outputs.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import cas, receipts
from .config import EngineConfig
from .derivation import verify_derivation
from .validate import canonical_json_bytes, sha256_bytes

KIND = "document"


def _tree(trail: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Each step with what it rests on — the edges a reader walks back."""
    out = []
    for t in trail:
        out.append({"id": t.get("id"), "domain": t.get("domain"), "status": t.get("status"),
                    "spec_hash": t.get("spec_hash"), "uses": list(t.get("uses") or []),
                    "link_ok": t.get("link_ok", True), "detail": (t.get("detail") or "")[:240]})
    return out


def seal_document(doc: Dict[str, Any], config: Optional[EngineConfig] = None, *, seal: bool = True) -> Dict[str, Any]:
    config = config or EngineConfig()
    steps = list(doc.get("steps") or [])
    if not steps:
        return {"verdict": "INCOMPLETE", "root": None, "means": "a document needs at least one step"}
    parents = [str(p) for p in (doc.get("parents") or []) if p]
    for p in parents:
        if cas.fetch(p) is None:
            return {"verdict": "SCHEMA_ERROR", "root": None,
                    "problems": [{"field": "parents", "problem": f"parent seal not held: {p[:16]}…"}]}
    res = verify_derivation(steps)
    dom = str(steps[0].get("domain") or "mathematics")
    sealed = receipts.attach(res, config=config, domain=dom, enabled=seal)
    tree = _tree(sealed.get("trail") or [])
    text = doc.get("text") or ""
    root_record = {
        "kind": KIND, "schema_version": "3.0",
        "title": str(doc.get("title") or "")[:200],
        "verdict": sealed.get("verdict"),
        "derivation_seal": (sealed.get("seal") or {}).get("content_hash"),
        "steps": tree,
        "parents": parents,
        "text_hash": sha256_bytes(canonical_json_bytes({"text": text})) if text else None,
        "labels": {str(s.get("id")): str(s.get("label") or "") for s in steps if s.get("label")},
        # the bindings, so a reader (or the receipt page) can re-run the chain and feel an upstream change
        "binds": {str(s.get("id")): dict(s["bind"]) for s in steps if isinstance(s.get("bind"), dict) and s["bind"]},
    }
    out: Dict[str, Any] = {"verdict": sealed.get("verdict"), "steps": tree,
                           "derivation_seal": sealed.get("seal"), "parents": parents, "generated": False}
    if seal:
        root = cas.store(root_record, index=False, card=False)
        if root:
            # keep the prose beside the root (de-identified by the caller) so the page can show it
            if text:
                cas.store_spec({"text": text})
            out["root"] = root
            out["cite_url"] = f"{receipts._public_base(config)}/s/{root}"
            out["means"] = ("the root is the SHA-256 of a record naming every step's spec_hash, status and "
                            "dependencies plus the derivation seal and parent seals; re-fetch /s/<root>, "
                            "re-hash, and walk the tree")
        else:
            out["root"] = None
            out["seal_error"] = "root could not be stored"
    else:
        out["root"] = None
    return out


def fetch_document(root: str) -> Optional[Dict[str, Any]]:
    rec = cas.fetch(root)
    if not rec or rec.get("kind") != KIND:
        return None
    return rec


def walk(root: str, depth: int = 8) -> Optional[Dict[str, Any]]:
    """The tree from a root down through its parents (documents that stood under this one)."""
    rec = fetch_document(root)
    if rec is None:
        return None
    node = {"root": root, "title": rec.get("title"), "verdict": rec.get("verdict"),
            "steps": rec.get("steps"), "derivation_seal": rec.get("derivation_seal"), "parents": []}
    if depth > 0:
        for p in rec.get("parents") or []:
            child = walk(p, depth - 1)
            node["parents"].append(child or {"root": p, "title": None, "verdict": None,
                                              "note": "held as a plain seal, not a document"})
    return node


__all__ = ["seal_document", "fetch_document", "walk", "KIND"]
