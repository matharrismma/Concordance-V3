"""Packet schemas, generated from the verifiers themselves — never hand-written.

For each verifier module: the artifact key its run() reads (e.g. RE_VERIFY), the fields each
verify_* function reads from its spec, and the docstring's check list. `schema_for(domain)` serves
that as JSON Schema-ish; `validate_steps(steps)` turns a misnamed field into SCHEMA_ERROR naming the
field and its nearest known name, instead of a silent NOT_APPLICABLE.
"""
from __future__ import annotations

import ast
import difflib
import importlib
import inspect
import re
from functools import lru_cache
from typing import Any, Dict, List, Optional

from . import verifiers as _V

_MATH_MODES = {"equality", "inequality", "derivative", "integral", "limit", "solve", "numeric",
               "calc_chain", "system", "number_theory"}


def _module_for(domain: str) -> Optional[str]:
    _V._load_plugins()
    return _V.VERIFIERS.get((domain or "").lower())


def _str_consts(node: ast.AST) -> List[str]:
    return [n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


@lru_cache(maxsize=None)
def _analyse(mod_path: str) -> Dict[str, Any]:
    mod = importlib.import_module(mod_path)
    src = inspect.getsource(mod)
    tree = ast.parse(src)
    artifact: Optional[str] = None
    checks: Dict[str, List[str]] = {}
    fields: set = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "run":
            for n in ast.walk(node):
                # packet.get("KEY") / dispatch(packet, 'KEY', ...)
                if isinstance(n, ast.Call):
                    f = n.func
                    if isinstance(f, ast.Attribute) and f.attr == "get" and n.args and \
                            isinstance(n.args[0], ast.Constant) and re.fullmatch(r"[A-Z][A-Z0-9_]+", str(n.args[0].value)):
                        artifact = artifact or n.args[0].value
                    if isinstance(f, ast.Name) and f.id == "dispatch" and len(n.args) > 1 and \
                            isinstance(n.args[1], ast.Constant):
                        artifact = artifact or n.args[1].value
                if isinstance(n, ast.Compare) and isinstance(n.left, ast.Constant) and isinstance(n.left.value, str):
                    fields.add(n.left.value)
        if isinstance(node, ast.FunctionDef) and node.name.startswith("verify_"):
            fs = sorted({s for s in _str_consts(node)
                         if re.fullmatch(r"[a-z][a-z0-9_]{1,60}", s) and s not in ("spec", "name")})
            # keep only keys read from the spec: spec.get("k") / spec["k"] / "k" in spec
            keys = set()
            for n in ast.walk(node):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get" \
                        and n.args and isinstance(n.args[0], ast.Constant):
                    keys.add(str(n.args[0].value))
                if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant) and isinstance(n.slice.value, str):
                    keys.add(n.slice.value)
                if isinstance(n, ast.Compare) and isinstance(n.left, ast.Constant) and isinstance(n.left.value, str):
                    keys.add(n.left.value)
                # helper calls that read fields off the spec: _num(spec, "a", "b"), _get(art, "k")
                if isinstance(n, ast.Call) and n.args and isinstance(n.args[0], ast.Name) \
                        and n.args[0].id in ("spec", "art", "a", "rv", "pv", "mv", "packet_spec"):
                    for arg in n.args[1:]:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            keys.add(arg.value)
            keys = {k for k in keys if k in fs}
            checks[node.name[7:]] = sorted(keys)
            fields |= keys
    doc = inspect.getdoc(mod) or ""
    named = re.findall(r"^\s*\*\s+([a-z_]+\.[a-z0-9_]+)", doc, re.M)
    example = None
    m = re.search(r"packet shape[^\n]*\n(\s*\{.*?\n\s*\})", doc, re.S | re.I)
    if m:
        example = m.group(1).strip()
    return {"module": mod_path.rsplit(".", 1)[-1], "artifact_key": artifact,
            "checks": checks, "named_checks": named, "fields": sorted(fields), "example": example}


def schema_for(domain: str) -> Dict[str, Any]:
    d = (domain or "").lower()
    if d in ("mathematics", "math"):
        return {"domain": "mathematics", "forms": [
            {"shape": {"mode": "<one of %s>" % sorted(_MATH_MODES), "params": {"...": "mode-specific"}},
             "numeric": {"mode": "numeric", "params": {"numeric_expr": "12*3.5", "claimed_value": 42, "rel_tol": 1e-6}},
             "equality": {"mode": "equality", "params": {"expr_a": "(x+1)^2", "expr_b": "x^2+2*x+1", "variables": ["x"]}}}],
            "means": "pure arithmetic and symbolic identities; no artifact key"}
    mod = _module_for(d)
    if not mod:
        return {"error": f"no verifier for domain '{domain}'",
                "available": sorted({v.rsplit('.', 1)[-1] for v in _V.VERIFIERS.values()})}
    a = _analyse(mod)
    props = {f: {"type": ["number", "string", "boolean", "array", "object"]} for f in a["fields"]}
    return {"domain": a["module"], "artifact_key": a["artifact_key"],
            "packet": {"type": "object", "properties": {a["artifact_key"] or "SPEC": {
                "type": "object", "properties": props, "additionalProperties": True}}},
            "checks": a["checks"], "named_checks": a["named_checks"], "example": a["example"],
            "means": "fields are those each verify_* function reads from the artifact; a check fires when its "
                     "trigger fields are present (see the module's run())"}


def validate_steps(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return a list of problems (empty = fine). A problem names the step, the field, and the fix."""
    problems: List[Dict[str, Any]] = []
    for i, st in enumerate(steps or []):
        sid = st.get("id") if isinstance(st, dict) else None
        if not isinstance(st, dict) or not isinstance(st.get("spec"), dict):
            problems.append({"step": sid or i, "field": "spec", "problem": "step must be {id, domain, spec:{...}}"})
            continue
        d = str(st.get("domain") or "").lower()
        spec = st["spec"]
        if d in ("mathematics", "math", ""):
            if "mode" in spec:
                if spec.get("mode") not in _MATH_MODES:
                    problems.append({"step": sid, "field": "mode", "problem": f"unknown mode {spec.get('mode')!r}",
                                     "allowed": sorted(_MATH_MODES)})
                continue
        mod = _module_for(d)
        if not mod:
            problems.append({"step": sid, "field": "domain", "problem": f"no verifier for domain '{d}'",
                             "nearest": difflib.get_close_matches(d, list(_V.VERIFIERS), n=3)})
            continue
        a = _analyse(mod)
        key = a["artifact_key"]
        if key and key not in spec:
            if "mode" in spec:
                continue   # a math-mode packet routed under a domain name; derivation handles it
            problems.append({"step": sid, "field": key, "problem": f"spec must carry the artifact key {key!r}",
                             "got": sorted(spec)[:10]})
            continue
        art = spec.get(key) if key else spec
        if not isinstance(art, dict):
            problems.append({"step": sid, "field": key, "problem": "artifact must be an object"})
            continue
        known = set(a["fields"])
        _free = ("units", "note", "label", "id", "claim", "source", "ref")
        unknown = [k for k in art if k not in known and not str(k).startswith("tolerance") and k not in _free]
        recognised = [k for k in art if k in known]
        if known and unknown:
            problems.append({"step": sid, "field": unknown[0],
                             "problem": ("no check of this domain reads any of these fields" if not recognised
                                         else "field name(s) not in this domain's schema"),
                             "unknown": unknown[:8],
                             "nearest": {u: difflib.get_close_matches(u, list(known), n=2, cutoff=0.6) for u in unknown[:8]},
                             "known_fields": sorted(known)[:40]})
    return problems


__all__ = ["schema_for", "validate_steps"]
