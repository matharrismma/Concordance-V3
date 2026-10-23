"""MCP server — JSON-RPC over stdio (and Streamable HTTP via mcp/http.py). Stdlib only.

Eight tools, listed in tool_registry. Every result is JSON text. Tool failures are results, never
crashes: an internal failure returns code INTERNAL_FAILURE and says it is not a verdict.
"""
from __future__ import annotations

import json
import sys
from typing import Any, Dict, List, Optional

from .. import __version__, cas
from .. import tool_registry as _registry
from ..config import EngineConfig
from ..derivation import verify_derivation

SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[-1]

INSTRUCTIONS = (
    "Concordance verifies numbers deterministically and returns a re-checkable receipt. "
    "Start with find_verifier(query) to get a domain's packet schema, then verify(steps=[{id, domain, spec}]). "
    "Read the verdict exactly: only BROKEN is a finding about the claim; INCOMPLETE means nothing applied; "
    "SYSTEM_ERROR means our verifier failed; SCHEMA_ERROR names the field to fix. PARTIAL means the checked "
    "fragment held and other text was not checked. Every seal has a content hash: seal_fetch returns the "
    "record, and re-hashing it must reproduce the hash. The engine checks arithmetic and formula application "
    "only; it never judges whether a correct result is safe, legal, or suitable."
)

ERROR_CODES: Dict[str, str] = {
    "INVALID_SPEC": "correct the arguments and retry — the message names what is missing or malformed",
    "SCHEMA_ERROR": "the packet does not match the domain's schema; the message names the field",
    "VERIFIER_NOT_FOUND": "no deterministic verifier covers this domain; consult capabilities for what does",
    "CLAIM_INCOMPLETE": "supply the missing quantities the trail names; the claim was not testable as given",
    "SEAL_NOT_FOUND": "the content hash resolves to nothing held; check the hash",
    "RATE_LIMITED": "back off and retry after the stated interval",
    "INTERNAL_FAILURE": "our fault, not the claim's; retry once, then report it — never read this as a verdict",
    "UNCLASSIFIED": "read the message",
}
_ERROR_PATTERNS = (("rate limit", "RATE_LIMITED"), ("schema", "SCHEMA_ERROR"), ("no seal", "SEAL_NOT_FOUND"),
                   ("not found", "SEAL_NOT_FOUND"), ("required", "INVALID_SPEC"), ("must be", "INVALID_SPEC"),
                   ("invalid", "INVALID_SPEC"), ("malformed", "INVALID_SPEC"), ("no verifier", "VERIFIER_NOT_FOUND"),
                   ("no applicable", "VERIFIER_NOT_FOUND"), ("incomplete", "CLAIM_INCOMPLETE"),
                   ("tool error", "INTERNAL_FAILURE"))

_STR_MAXLEN, _ARR_MAXITEMS, _NUM_BOUND = 4000, 200, 1e12


def negotiate_protocol_version(requested) -> str:
    r = str(requested or "").strip()
    return r if r in SUPPORTED_PROTOCOL_VERSIONS else SUPPORTED_PROTOCOL_VERSIONS[0]


def classify_error(message: str) -> str:
    m = str(message or "").lower()
    for pattern, code in _ERROR_PATTERNS:
        if pattern in m:
            return code
    return "UNCLASSIFIED"


def _is_business_error(result: Any) -> bool:
    return (isinstance(result, dict) and "error" in result
            and not (set(result) - {"error", "detail", "why", "hint", "available", "status", "field"}))


def _strictify(schema: Any) -> Any:
    if not isinstance(schema, dict):
        return schema
    s = dict(schema)
    t = s.get("type")
    if t == "object" or "properties" in s:
        s.setdefault("additionalProperties", False)
        if isinstance(s.get("properties"), dict):
            s["properties"] = {k: _strictify(v) for k, v in s["properties"].items()}
    if t == "string" and not any(k in s for k in ("enum", "pattern", "maxLength", "format", "const")):
        s["maxLength"] = _STR_MAXLEN
    if t == "array":
        s.setdefault("maxItems", _ARR_MAXITEMS)
        s["items"] = _strictify(s.get("items") if isinstance(s.get("items"), dict)
                                else {"type": "string", "maxLength": _STR_MAXLEN})
    if t in ("integer", "number"):
        s.setdefault("minimum", -_NUM_BOUND)
        s.setdefault("maximum", _NUM_BOUND)
    return s


def list_tools() -> List[dict]:
    return [{"name": t.name, "description": t.description, "effect": t.effect,
             "inputSchema": _strictify(t.schema)} for t in _registry.REGISTRY]


# ── the plain-claim door ─────────────────────────────────────────────────────────────────────────
def _verify_plain(claim: str, config: EngineConfig, seal_on: bool, hint: Optional[str]) -> Dict[str, Any]:
    from .. import airlock as _airlock, audit as _audit, text as _text
    if _text.is_crisis(claim):
        return {"verdict": "INCOMPLETE", "claim": claim, "claims_found": 0, "trail": [], "seal": None,
                "generated": False, "crisis": True, "note": _text.CRISIS_RESPONSE}
    passage = _airlock.through(claim, lambda skel: _audit.audit(skel, config, seal=seal_on), minimal=True)
    if passage.leaked:
        return {"verdict": "QUARANTINE", "claim": claim, "claims_found": 0, "trail": [], "seal": None,
                "generated": False,
                "note": "The claim could not be de-identified safely; nothing was sent to the verifier and nothing "
                        "was sealed. Strip the personal details and try again."}
    ar = passage.result if isinstance(passage.result, dict) else {}
    results = ar.get("results") or []
    trail = [{"id": f"a{i + 1}", "domain": c.get("domain"), "status": c.get("status"),
              "detail": c.get("detail", ""), "claim": c.get("claim")} for i, c in enumerate(results)]
    verdict = str(ar.get("verdict") or "")
    out = {"verdict": "INCOMPLETE" if verdict == "NOTHING_TO_CHECK" else verdict,
           "claim": claim, "extracted": True,
           "claims_found": ar.get("claims_found", 0), "held": ar.get("held", 0),
           "broken": ar.get("broken", 0), "unchecked": ar.get("unchecked", 0),
           "checks": [{"claim": c.get("claim"), "verdict": c.get("status"), "domain": c.get("domain"),
                       "detail": c.get("detail")} for c in results],
           "trail": trail, "seal": ar.get("seal") if isinstance(ar.get("seal"), dict) else None,
           "coverage": ar.get("coverage"), "generated": False, "note": ar.get("note", "")}
    if hint:
        out["domain_hint"] = str(hint)
    governed = ((ar.get("coverage") or {}).get("governed") or []) if isinstance(ar.get("coverage"), dict) else []
    if out["verdict"] == "INCOMPLETE":
        out["gap_at"] = claim
        if governed:
            out["means"] = ("every checkable claim here is governed by a negation, a reported belief or a condition "
                            "(see coverage.governed), so it was declined rather than checked as asserted; this says "
                            "nothing about whether the bare claim is true.")
        else:
            out["means"] = ("no deterministic extractor recognised a checkable claim; this says nothing about whether "
                            "the claim is true. Bring the domain's packet as steps=[{id, domain, spec}] "
                            "(find_verifier returns the schema), or {mode, params} for arithmetic.")
            try:
                out["structured"] = _audit.structured_hint(claim)
            except Exception:  # noqa: BLE001
                pass
    return out


def _call_tool(name: str, args: dict, config: EngineConfig) -> Any:
    args = args or {}
    if name == "verify":
        from .. import receipts, schema as _schema
        seal_on = args.get("seal", True) is not False
        if isinstance(args.get("document"), dict):
            from .. import compose as _compose, schema as _schema2
            bad = _schema2.validate_steps(args["document"].get("steps") or [])
            if bad:
                return {"verdict": "SCHEMA_ERROR", "root": None, "problems": bad,
                        "means": "a step's packet did not match its domain's schema; nothing was sealed"}
            return _compose.seal_document(args["document"], config, seal=seal_on)
        claim = str(args.get("claim") or "").strip()
        if claim and not isinstance(args.get("steps"), list) and not args.get("mode"):
            return _verify_plain(claim, config, seal_on, args.get("domain"))
        if isinstance(args.get("steps"), list):
            steps = args["steps"]
            bad = _schema.validate_steps(steps)
            if bad:
                return {"verdict": "SCHEMA_ERROR", "trail": [], "seal": None, "problems": bad,
                        "means": "a packet did not match its domain's schema; nothing was verified. Fix the named "
                                 "fields (find_verifier returns the schema) and resend."}
            res = verify_derivation(steps)
            dom = str(steps[0].get("domain") or "mathematics") if steps else "mathematics"
        else:
            res = verify_derivation([{"id": "b", "domain": "mathematics",
                                      "spec": {"mode": args.get("mode"), "params": args.get("params", {})}}])
            dom = "mathematics"
        return receipts.attach(res, config=config, domain=dom, enabled=seal_on)
    if name == "discern":
        from .. import discern as _d
        return _d.discern(str(args.get("text") or ""))
    if name == "find_verifier":
        from .. import domain_resolver as _dr, schema as _schema
        r = _dr.resolve_domain(str(args.get("query") or ""))
        if isinstance(r, dict):
            doms = [r.get("decision")] + [c.get("domain") for c in (r.get("candidates") or [])]
            doms = [d for i, d in enumerate(doms) if d and d not in doms[:i]]
            r["domain"] = r.get("decision")
            r["schemas"] = {d: _schema.schema_for(d) for d in doms[:3]}
        return r
    if name == "seal_fetch":
        rec = cas.fetch(args.get("hash", ""))
        return rec if rec is not None else {"error": "seal not found"}
    if name == "audit":
        from .. import audit as _audit, text as _text
        t = str(args.get("text") or "")
        if _text.is_crisis(t):
            return {"verdict": "INCOMPLETE", "claims_found": 0, "results": [], "crisis": True,
                    "note": _text.CRISIS_RESPONSE}
        return _audit.audit(t, config, seal=args.get("seal", True) is not False)
    if name == "scribe":
        from .. import scribe as _scribe
        return _scribe.score_pass(args.get("drafts") or [], packets=args.get("packets") or {},
                                  claim_ids=args.get("claim_ids"))
    if name == "capabilities":
        from .. import capabilities as _cap
        return _cap.statement()
    if name == "ledger_verify":
        from .. import ledger as _ledger
        return _ledger.verify_chain()
    raise KeyError(f"unknown tool: {name}")


def handle(request: dict, config: EngineConfig, session: Optional[Dict[str, Any]] = None,
           profile: Optional[str] = None) -> Optional[dict]:
    rid = request.get("id")
    method = request.get("method")
    if method == "initialize":
        negotiated = negotiate_protocol_version((request.get("params") or {}).get("protocolVersion"))
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": negotiated, "capabilities": {"tools": {}},
            "serverInfo": {"name": "concordance", "version": __version__},
            "instructions": INSTRUCTIONS}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": list_tools()}}
    if method == "tools/call":
        p = request.get("params") or {}
        name, args = p.get("name"), p.get("arguments") or {}
        if name not in _registry.BY_NAME:
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": f"unknown tool: {name}"}}
        try:
            result = _call_tool(name, args, config)
        except KeyError as e:
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": str(e)}}
        except Exception as e:  # noqa: BLE001 — tool errors are results, not crashes
            try:
                from .. import telemetry
                telemetry.record("mcp_error", tool=str(name), detail=f"{type(e).__name__}: {str(e)[:160]}")
            except Exception:  # noqa: BLE001
                pass
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": json.dumps(
                    {"error": "tool error", "code": "INTERNAL_FAILURE",
                     "remedy": ERROR_CODES["INTERNAL_FAILURE"]})}], "isError": True}}
        if _is_business_error(result):
            code = classify_error(result.get("error"))
            typed = dict(result, code=code, remedy=ERROR_CODES.get(code, ERROR_CODES["UNCLASSIFIED"]))
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": json.dumps(typed, ensure_ascii=False)}], "isError": True}}
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}],
            "isError": False}}
    if method and method.startswith("notifications/"):
        return None
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"method not found: {method}"}}


def serve_stdio(surface: str = "secular") -> None:
    config = EngineConfig()
    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle(req, config)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


__all__ = ["handle", "serve_stdio", "list_tools", "INSTRUCTIONS", "PROTOCOL_VERSION",
           "SUPPORTED_PROTOCOL_VERSIONS", "negotiate_protocol_version"]
