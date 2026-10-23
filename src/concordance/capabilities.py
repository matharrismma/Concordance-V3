"""The live capability statement — every public number computed at call time, with its definition.

Rule (2026-06-10, kept): no capability count is hand-maintained anywhere. Each field below is derived
from the running registries and carries a `means` line naming exactly what was counted.
"""
from __future__ import annotations

import importlib
import inspect
import re
from typing import Any, Dict, List

NOTE = ("Every count is computed from the running engine at the moment you asked and carries the "
        "definition of what was counted. The engine checks arithmetic deterministically and seals the "
        "result; it does not generate answers and it does not judge whether a correct calculation is "
        "safe, legal, or wise.")


def _verifiers() -> Dict[str, Any]:
    from . import verifiers as V
    V._load_plugins()
    by_module: Dict[str, List[str]] = {}
    for alias, mod in V.VERIFIERS.items():
        by_module.setdefault(mod.rsplit(".", 1)[-1], []).append(alias)
    checks = 0
    check_names: List[str] = []
    for mod in sorted(by_module):
        try:
            m = importlib.import_module("concordance.verifiers." + mod)
        except Exception:  # noqa: BLE001
            continue
        doc = inspect.getdoc(m) or ""
        names = re.findall(r"^\s*\*\s+([a-z_]+\.[a-z0-9_]+)", doc, re.M)
        if not names:
            names = [f"{mod}.{n[7:]}" for n, _ in inspect.getmembers(m, inspect.isfunction)
                     if n.startswith("verify_")]
        checks += len(names)
        check_names.extend(names)
    return {"modules": len(by_module),
            "means_modules": "distinct verifier modules registered (a module is one domain)",
            "domain_names": len(V.VERIFIERS),
            "means_domain_names": "domain names the dispatcher accepts, aliases included",
            "checks": checks,
            "means_checks": "named checks across modules (from each module's docstring list, else its verify_* functions)",
            "domains": sorted(by_module)}


def _tools() -> Dict[str, Any]:
    from . import tool_registry as T
    return {"count": len(T.REGISTRY), "names": [t.name for t in T.REGISTRY],
            "means": "MCP tools this server registers"}


def _benchmark() -> Dict[str, Any]:
    try:
        from pathlib import Path
        import json
        p = Path(__file__).resolve().parents[2] / "data" / "benchmark_last.json"
        if p.exists():
            d = json.loads(p.read_text())
            return {"version": d.get("version"), "cases": d.get("total"), "false_positives": d.get("false_positives"),
                    "means": "last benchmark run recorded by tools/benchmark.py --json --record"}
    except Exception:  # noqa: BLE001
        pass
    return {"version": None, "means": "no recorded benchmark run in this checkout"}


def _ledger() -> Dict[str, Any]:
    try:
        from . import ledger as L
        n = L.count() if hasattr(L, "count") else None
        return {"entries": n, "means": "entries in the local append-only ledger"}
    except Exception:  # noqa: BLE001
        return {"entries": None, "means": "ledger not readable in this process"}


def statement(surface: str = "secular") -> Dict[str, Any]:
    from . import __version__
    return {"engine": "concordance", "version": __version__, "note": NOTE,
            "verifiers": _verifiers(), "tools": _tools(), "benchmark": _benchmark(), "ledger": _ledger(),
            "limits": ["verifies arithmetic and formula application only — never clinical, legal, or "
                       "financial suitability",
                       "a plain-text claim is checked only where an extractor recognised a tight span; "
                       "coverage.unchecked_text names the rest",
                       "a seal binds the packet that was checked, not the sentence it came from"]}


__all__ = ["statement", "NOTE"]
