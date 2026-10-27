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
    artifacts: List[str] = []
    root_fields: set = set()
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
                        if n.args[0].value not in artifacts:
                            artifacts.append(n.args[0].value)
                    if isinstance(f, ast.Name) and f.id == "dispatch" and len(n.args) > 1 and \
                            isinstance(n.args[1], ast.Constant):
                        artifact = artifact or n.args[1].value
                        if n.args[1].value not in artifacts:
                            artifacts.append(n.args[1].value)
                if isinstance(n, ast.Compare) and isinstance(n.left, ast.Constant) and isinstance(n.left.value, str):
                    fields.add(n.left.value)
                    if any(isinstance(c, ast.Name) and c.id == "packet" for c in n.comparators):
                        root_fields.add(n.left.value)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get" \
                        and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                    v = n.args[0].value
                    if not re.fullmatch(r"[A-Z][A-Z0-9_]+", v):
                        fields.add(v)
                        if isinstance(n.func.value, ast.Name) and n.func.value.id == "packet":
                            root_fields.add(v)
        if isinstance(node, ast.FunctionDef) and node.name.startswith("verify_"):
            # Every identifier-like string constant the check mentions is a candidate field, except the
            # check's own name (name = "...", or the first arg to confirm/na/error/mismatch) and strings
            # with a dot or space. Over-inclusion only loosens SCHEMA_ERROR; under-inclusion rejects valid
            # packets (found live 2026-10-23), so the net is cast wide on purpose.
            not_fields = set()
            for n in ast.walk(node):
                if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "name" for t in n.targets) \
                        and isinstance(n.value, ast.Constant):
                    not_fields.add(n.value.value)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("confirm", "na", "error", "mismatch") \
                        and n.args and isinstance(n.args[0], ast.Constant):
                    not_fields.add(n.args[0].value)
            keys = {s_ for s_ in _str_consts(node)
                    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,60}", s_) and s_ not in not_fields
                    and s_ not in ("spec", "True", "False", "None")}
            checks[node.name[7:]] = sorted(keys)
            fields |= keys
        # module-level tables (_RULES, _PLANCK_CHECKS, _CLASSES, …): their identifier-like strings are field
        # names or vocabulary; both are safe to accept
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and (t.id.isupper() or t.id.startswith("_"))
                                                for t in node.targets):
            for c in _str_consts(node):
                if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,60}", c):
                    fields.add(c)
    # INPUT fields — what a *claim* fills, versus what a check computes. The `fields` set above is
    # deliberately over-inclusive so validate_steps never rejects a valid packet; but a caller reading
    # the schema to BUILD a packet (the edge translator, or a model) must see only the keys a verifier
    # reads from its spec. Found 2026-10-27: the geometry schema advertised a_sq_plus_b_sq / actual_*
    # (computed outputs from the data dict), so the translator asked the model to fill the answer. The
    # inputs are the strings read via spec/gv/packet .get(...) or ["..."], tested with `"x" in spec`,
    # or iterated by an `all(k in gv for k in (...))` membership test.
    _SPEC_NAMES = {"spec", "gv", "packet", "a", "art"}   # the artifact dict's parameter names across modules

    def _is_spec(x: ast.AST) -> bool:
        return isinstance(x, ast.Name) and x.id in _SPEC_NAMES

    input_fields: set = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get" \
                and _is_spec(n.func.value) and n.args and isinstance(n.args[0], ast.Constant) \
                and isinstance(n.args[0].value, str):
            input_fields.add(n.args[0].value)
        elif isinstance(n, ast.Subscript) and _is_spec(n.value) \
                and isinstance(n.slice, ast.Constant) and isinstance(n.slice.value, str):
            input_fields.add(n.slice.value)
        elif isinstance(n, ast.Compare) and len(n.ops) == 1 and isinstance(n.ops[0], ast.In) \
                and isinstance(n.left, ast.Constant) and isinstance(n.left.value, str) \
                and n.comparators and _is_spec(n.comparators[0]):
            input_fields.add(n.left.value)
        elif isinstance(n, (ast.GeneratorExp, ast.ListComp, ast.SetComp)) \
                and isinstance(n.elt, ast.Compare) and len(n.elt.ops) == 1 and isinstance(n.elt.ops[0], ast.In) \
                and n.elt.comparators and _is_spec(n.elt.comparators[0]):   # all(k in gv for k in (...))
            for gen in n.generators:
                if isinstance(gen.iter, (ast.Tuple, ast.List, ast.Set)):
                    input_fields |= {e.value for e in gen.iter.elts
                                     if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    input_fields = {f for f in input_fields
                    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,60}", f)
                    and not f.startswith("tolerance") and f != "rel_tol"}
    doc = inspect.getdoc(mod) or ""
    named = re.findall(r"^\s*\*\s+([a-z_]+\.[a-z0-9_]+)", doc, re.M)
    example = None
    m = re.search(r"packet shape[^\n]*\n(\s*\{.*?\n\s*\})", doc, re.S | re.I)
    if m:
        example = m.group(1).strip()
    return {"module": mod_path.rsplit(".", 1)[-1], "artifact_key": artifact, "artifact_keys": artifacts, "root_fields": sorted(root_fields),
            "checks": checks, "named_checks": named, "fields": sorted(fields),
            "input_fields": sorted(input_fields), "example": example}


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
    # Serve the fields a claim FILLS (what each verify_* reads from its spec), not the wider set that
    # validate_steps tolerates — the latter includes computed-output keys and would tell a caller to
    # fill the answer. Fall back to the wide set only if a module reads its inputs through an
    # unrecognised local (input_fields empty), so no domain loses its schema.
    inp = a.get("input_fields") or a["fields"]
    props = {f: {"type": ["number", "string", "boolean", "array", "object"]} for f in inp}
    return {"domain": a["module"], "artifact_key": a["artifact_key"],
            "packet": {"type": "object", "properties": {a["artifact_key"] or "SPEC": {
                "type": "object", "properties": props, "additionalProperties": True}}},
            "checks": a["checks"], "named_checks": a["named_checks"], "example": a["example"],
            "means": "the properties are the fields a claim fills (what each verify_* reads from its spec); a "
                     "check fires when its trigger fields are present (see the module's run())"}


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
        keys_all = a.get("artifact_keys") or ([a["artifact_key"]] if a["artifact_key"] else [])
        present = [k for k in keys_all if k in spec]
        if keys_all and not present:
            if "mode" in spec:
                continue   # a math-mode packet routed under a domain name; derivation handles it
            if a.get("root_fields") and any(k in a["root_fields"] for k in spec):
                pass   # a root-level packet the module reads directly (governance timing)
            elif len(keys_all) == 1:
                problems.append({"step": sid, "field": keys_all[0],
                                 "problem": f"spec must carry the artifact key {keys_all[0]!r}", "got": sorted(spec)[:10]})
                continue
        key = present[0] if present else None
        art = spec.get(key) if key else spec
        if not isinstance(art, dict):
            problems.append({"step": sid, "field": key, "problem": "artifact must be an object"})
            continue
        known = set(a["fields"])
        _free = ("units", "note", "label", "id", "claim", "source", "ref", "claimed_literal", "hedged")
        unknown = [k for k in art if k not in known and not str(k).startswith("tolerance") and k not in _free
                   and not str(k).endswith("_as_written")]         # engine-injected by the extractor
        recognised = [k for k in art if k in known]
        if known and unknown:
            near = {u: difflib.get_close_matches(u, list(known), n=2, cutoff=0.75) for u in unknown[:8]}
            typo = [u for u in unknown[:8] if near.get(u)]
            if not recognised or typo:
                problems.append({"step": sid, "field": (typo or unknown)[0],
                                 "problem": ("no check of this domain reads any of these fields" if not recognised
                                             else "field name(s) look like a misspelling of this domain's schema"),
                                 "unknown": unknown[:8], "nearest": near, "known_fields": sorted(known)[:40]})
            # otherwise: extra informational keys (a label, a scenario note) ride along; the verifier ignores them
    return problems


__all__ = ["schema_for", "validate_steps"]
