"""bucket — the smallest bucket: one exact packet, one verifier, one verdict.

A hash table is the floor's data structure: the key IS the identity. This is the memo built on it.
A step is keyed by (spec_hash, domain, engine version, verifier fingerprint) — exactly these bytes
checked by exactly this code — and a hit returns the verdict that was sealed the first time, with
no recompute. Honest by construction: the thing served is the same record a seal binds to and a
reader can re-check; the key carries the verifier's own source hash, so a changed verifier can
never serve a stale verdict. Everything above this is buckets composed — a band is a neighborhood
of buckets, a chain is buckets linked by `uses`, a document is a bucket of chains.

    CONCORDANCE_MEMO=0 disables lookups and stores (every step recomputes).
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from . import __version__, cas
from .validate import canonical_json_bytes, sha256_bytes

_MEMO_STATUSES = frozenset({"CONFIRMED", "MISMATCH", "NOT_APPLICABLE"})   # never ERROR: a timeout is not a verdict
_FINGERPRINTS: Dict[str, str] = {}


def enabled() -> bool:
    return os.environ.get("CONCORDANCE_MEMO", "1").strip().lower() not in ("0", "false", "no", "off")


def _dir() -> Path:
    d = cas._cas_dir() / "bucket"
    d.mkdir(parents=True, exist_ok=True)
    return d


def verifier_fingerprint(domain: str) -> str:
    """SHA-256 of the verifier module's source (the sympy moat for mathematics), cached per process.
    Part of the key: the same packet under changed code is a different bucket."""
    d = (domain or "").strip().lower()
    if d in _FINGERPRINTS:
        return _FINGERPRINTS[d]
    try:
        if d in ("mathematics", "math"):
            from . import derivation as _mod
            mods = [_mod]
        else:
            from . import verifiers as _V
            _V._load_plugins()
            import importlib
            name = _V.VERIFIERS.get(d) or _V.VERIFIERS.get(d.replace("-", "_"))
            mods = [importlib.import_module(name)] if name else []
        h = hashlib.sha256()
        for m in mods:
            p = getattr(m, "__file__", None)
            if p and os.path.exists(p):
                h.update(Path(p).read_bytes())
        fp = h.hexdigest()[:16] if mods else "unknown"
    except Exception:  # noqa: BLE001 — a fingerprint must never break a verdict; unknown just means no memo
        fp = "unknown"
    _FINGERPRINTS[d] = fp
    return fp


def key_for(domain: str, spec_hash: str) -> Optional[str]:
    fp = verifier_fingerprint(domain)
    if fp == "unknown" or not spec_hash:
        return None
    return sha256_bytes(canonical_json_bytes({"spec_hash": spec_hash, "domain": (domain or "").lower(),
                                              "engine": __version__, "verifier": fp}))


def lookup(key: str) -> Optional[Dict[str, Any]]:
    p = _dir() / (key + ".json")
    if not p.exists():
        return None
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    rec["hits"] = int(rec.get("hits") or 0) + 1
    try:
        p.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return rec


def store(key: str, result: Dict[str, Any], domain: str, spec_hash: str) -> bool:
    if result.get("status") not in _MEMO_STATUSES:
        return False
    rec = {"status": result.get("status"), "detail": result.get("detail", ""), "data": result.get("data") or {},
           "refutations": result.get("refutations"), "domain": domain, "spec_hash": spec_hash,
           "engine": __version__, "verifier": verifier_fingerprint(domain), "verified_at": time.time(), "hits": 0}
    try:
        (_dir() / (key + ".json")).write_text(json.dumps(rec, ensure_ascii=False, default=str), encoding="utf-8")
        return True
    except (OSError, TypeError, ValueError):
        return False


def through(domain: str, spec_hash: str, compute: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
    """Serve from the bucket or compute and fill it. The result carries `memo`: hit/miss, the key, and —
    on a hit — when it was first verified and under which engine/verifier, so the trace can say
    'served from bucket, verified <then>' rather than pretending it recomputed."""
    if not enabled():
        return dict(compute(), memo={"hit": False, "key": None, "reason": "memo disabled"})
    key = key_for(domain, spec_hash)
    if key is None:
        return dict(compute(), memo={"hit": False, "key": None, "reason": "verifier not fingerprintable"})
    hit = lookup(key)
    if hit is not None:
        out = {"status": hit["status"], "detail": hit.get("detail", ""), "data": dict(hit.get("data") or {})}
        if hit.get("refutations"):
            out["refutations"] = hit["refutations"]
        out["memo"] = {"hit": True, "key": key, "verified_at": hit.get("verified_at"), "engine": hit.get("engine"),
                       "verifier": hit.get("verifier"), "hits": hit.get("hits")}
        return out
    res = compute()
    stored = store(key, res, domain, spec_hash)
    return dict(res, memo={"hit": False, "key": key, "stored": stored})


def stats() -> Dict[str, Any]:
    d = _dir()
    files = list(d.glob("*.json"))
    hits = 0
    for p in files:
        try:
            hits += int(json.loads(p.read_text(encoding="utf-8")).get("hits") or 0)
        except Exception:  # noqa: BLE001
            pass
    return {"buckets": len(files), "hits": hits, "enabled": enabled(), "engine": __version__,
            "means": "one bucket per (packet bytes, domain, engine version, verifier source); a hit serves the "
                     "verdict sealed the first time, never a recompute"}


__all__ = ["through", "key_for", "lookup", "store", "verifier_fingerprint", "stats", "enabled"]
