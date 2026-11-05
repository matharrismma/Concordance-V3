"""bucket — the smallest bucket: one exact packet, one verifier, one verdict.

A hash table is the floor's data structure: the key IS the identity. This is the memo built on it.
A step is keyed by (spec_hash, domain, engine version, verifier fingerprint) — exactly these bytes
checked by exactly this code — and a hit returns the verdict that was sealed the first time, with
no recompute. Honest by construction: the thing served is the same record a seal binds to and a
reader can re-check; the key carries the hash of every source the verdict reads (_sources), so a
changed verifier, or a changed module it stands on, can never serve a stale verdict. Everything above
this is buckets composed — a band is a neighborhood of buckets, a chain is buckets linked by `uses`,
a document is a bucket of chains.

    CONCORDANCE_MEMO=0 disables lookups and stores (every step recomputes).
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

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


def _source(module: str) -> Optional[Path]:
    """The file a module's source is in: its own __file__ when it is loaded, so the key reads what this process reads,
    and otherwise where inside the package it would load from. None for anything that is not there."""
    path = getattr(sys.modules.get(module), "__file__", None)
    if path:
        return Path(path)
    target = Path(__file__).resolve().parent.joinpath(*module.split(".")[1:])
    for candidate in (target.parent / (target.name + ".py"), target / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _imports(module: str, source: bytes) -> Set[str]:
    """The modules inside this package a source names, lazy imports included, read from its syntax tree: nothing is
    imported or run. "from . import x" names both the package and x; a name that is no module is dropped by _source."""
    path = _source(module)
    is_package = hasattr(sys.modules.get(module), "__path__") or (path is not None and path.name == "__init__.py")
    package = module if is_package else module.rpartition(".")[0]
    named: Set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            named.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = package.split(".")
                base = ".".join(parts[:len(parts) - node.level + 1] + ([base] if base else []))
            named.add(base)
            named.update(f"{base}.{alias.name}" for alias in node.names)
    return {n for n in named if n.split(".")[0] == __package__ and _source(n) is not None}


def _closure(roots: Set[str]) -> Dict[str, bytes]:
    """Every module inside this package the roots reach, and the source of each."""
    seen: Dict[str, bytes] = {}
    todo = sorted(roots)
    while todo:
        module = todo.pop()
        if module in seen:
            continue
        path = _source(module)
        if path is None:
            raise LookupError(module)
        seen[module] = path.read_bytes()
        todo.extend(_imports(module, seen[module]))
    return seen


def _sources(domain: str) -> Dict[str, bytes]:
    """What a verdict in this domain reads, by module: the import closure of its verifier and of the runner, which is
    verifiers/__init__.py (run_for_domain drives every domain, and calls verifiers/spec.py for each), and derivation.py,
    which folds every verdict. Derivation is hashed but not walked: it imports the bridges and mathematics for all, and
    a domain that never reads them would move with them. Empty for a domain with no verifier."""
    from . import verifiers as _V
    _V._load_plugins()
    import importlib
    d = (domain or "").strip().lower()
    name = _V.VERIFIERS.get(d) or _V.VERIFIERS.get(d.replace("-", "_"))
    if not name:
        return {}
    importlib.import_module(name)
    seen = _closure({name, _V.__name__})
    derivation = __package__ + ".derivation"
    return dict(seen, **{derivation: _source(derivation).read_bytes()})


def verifier_closure(domain: str) -> List[str]:
    """The modules a domain's fingerprint hashes, sorted. Empty for a domain with no verifier."""
    return sorted(_sources(domain))


def verifier_fingerprint(domain: str) -> str:
    """SHA-256 of the source a verdict reads (_sources), cached per process. Part of the key: the same packet under
    changed code is a different bucket, whichever module on the way to the verdict changed."""
    d = (domain or "").strip().lower()
    if d in _FINGERPRINTS:
        return _FINGERPRINTS[d]
    try:
        sources = _sources(d)
        h = hashlib.sha256()
        for module in sorted(sources):
            h.update(module.encode("utf-8") + b"\0" + sources[module])
        fp = h.hexdigest()[:16] if sources else "unknown"
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


__all__ = ["through", "key_for", "lookup", "store", "verifier_closure", "verifier_fingerprint", "stats", "enabled"]
