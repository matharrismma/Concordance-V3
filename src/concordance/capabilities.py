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
                    "recorded_at": d.get("recorded_at"), "bands": d.get("bands"),
                    "means": "last benchmark run recorded by tools/benchmark.py --record"}
    except Exception:  # noqa: BLE001
        pass
    return {"version": None, "means": "no recorded benchmark run in this checkout"}


def _beta_upper(failures: int, successes: int, q: float = 0.95) -> float:
    """q-quantile of Beta(1+f, 1+s): the upper bound on the failure rate. Closed form when f == 0;
    otherwise a regularised incomplete beta by continued fraction and bisection (no scipy)."""
    import math
    a, b = 1 + failures, 1 + successes
    if failures == 0:
        return 1.0 - (1.0 - q) ** (1.0 / b)

    def cf(a, b, x):
        tiny = 1e-300
        qab, qap, qam = a + b, a + 1.0, a - 1.0
        c, d = 1.0, 1.0 - qab * x / qap
        d = 1.0 / (d if abs(d) > tiny else tiny)
        h = d
        for m in range(1, 300):
            m2 = 2 * m
            aa = m * (b - m) * x / ((qam + m2) * (a + m2))
            d = 1.0 + aa * d; d = 1.0 / (d if abs(d) > tiny else tiny); c = 1.0 + aa / (c if abs(c) > tiny else tiny); h *= d * c
            aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
            d = 1.0 + aa * d; d = 1.0 / (d if abs(d) > tiny else tiny); c = 1.0 + aa / (c if abs(c) > tiny else tiny)
            de = d * c; h *= de
            if abs(de - 1.0) < 3e-14:
                break
        return h

    def cdf(x):
        if x <= 0: return 0.0
        if x >= 1: return 1.0
        lbt = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
        return math.exp(lbt) * cf(a, b, x) / a if x < (a + 1) / (a + b + 2) else 1.0 - math.exp(lbt) * cf(b, a, 1 - x) / b
    lo, hi = 0.0, 1.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if cdf(mid) < q: lo = mid
        else: hi = mid
    return hi


def trust() -> Dict[str, Any]:
    """The Bayesian reading of a HOLDS: given the recorded benchmark (n labelled cases, f false positives),
    the posterior on the false-pass rate is Beta(1+f, 1+n−f). A HOLDS is not truth; this is how much a
    reader should discount it, from counts rather than confidence. None when no run is recorded."""
    b = _benchmark()
    n, fp = b.get("cases"), b.get("false_positives")
    if not isinstance(n, int) or not isinstance(fp, int) or n <= 0:
        return {"available": False, "means": "no recorded benchmark run; run tools/benchmark.py --record"}
    mean = (1 + fp) / (n + 2)
    up = _beta_upper(fp, n - fp)
    return {"available": True, "benchmark_version": b.get("version"), "cases": n, "false_positives": fp,
            "p_false_pass_mean": mean, "p_false_pass_upper95": up,
            "read": (f"on {n:,} labelled cases with {fp} false positive{'s' if fp != 1 else ''}, the posterior probability that "
                     f"a HOLDS is a false pass is {mean:.2%} (95% upper bound {up:.2%}) — Beta(1+{fp}, 1+{n - fp})"),
            "means": "a survival updates belief; a counterexample sets it to zero; this is the prior on survival itself"}


def _ledger() -> Dict[str, Any]:
    try:
        from . import ledger as L
        n = L.count() if hasattr(L, "count") else None
        return {"entries": n, "means": "entries in the local append-only ledger"}
    except Exception:  # noqa: BLE001
        return {"entries": None, "means": "ledger not readable in this process"}


def _bucket() -> Dict[str, Any]:
    try:
        from . import bucket as B
        return B.stats()
    except Exception:  # noqa: BLE001
        return {"buckets": None, "means": "bucket store not readable in this process"}


def _transparency() -> Dict[str, Any]:
    try:
        from . import transparency as T
        st = T.status()
        return {"issuer_key_configured": st["issuer_key_configured"], "kid": st["kid"], "log": st["rekor"],
                "publish_by_default": st["publish_by_default"],
                "means": "whether seals are signed (COSE_Sign1, Ed25519) and logged to a public transparency log; "
                         "without a key they are self-attested and say so"}
    except Exception:  # noqa: BLE001
        return {"issuer_key_configured": False, "means": "transparency module not importable (install the signing extra)"}


def statement(surface: str = "secular") -> Dict[str, Any]:
    from . import __version__
    return {"engine": "concordance", "version": __version__, "note": NOTE,
            "verifiers": _verifiers(), "tools": _tools(), "benchmark": _benchmark(), "ledger": _ledger(),
            "transparency": _transparency(), "bucket": _bucket(), "trust": trust(),
            "limits": ["verifies arithmetic and formula application only — never clinical, legal, or "
                       "financial suitability",
                       "a plain-text claim is checked only where an extractor recognised a tight span; "
                       "coverage.unchecked_text names the rest",
                       "a seal binds the packet that was checked, not the sentence it came from"]}


__all__ = ["statement", "NOTE"]
