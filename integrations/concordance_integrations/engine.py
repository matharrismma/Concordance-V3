"""The one call every adapter makes.

An adapter turns a harness object (a DeepEval test case, a LangGraph state, a Guardrails
string) into a verify request and hands it here. This is the whole coupling to the engine:
one in-process call through the same tool the MCP server and HTTP API dispatch, so an adapter
gets exactly the verdict + trail + seal a remote caller would — no network, no server to run.

`pip install concordance` is the only requirement; the harness process verifies locally.
A keyed, Rekor-logging deployment is reached the same way with CONCORDANCE_ISSUER_KEY set in
the environment (see docs/RUNBOOK.md); the adapter code is unchanged.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


def verify(steps: Optional[List[Dict[str, Any]]] = None, claim: Optional[str] = None,
           *, document: Optional[Dict[str, Any]] = None, mode: Optional[str] = None,
           params: Optional[Dict[str, Any]] = None, seal: bool = True,
           config: Any = None) -> Dict[str, Any]:
    """Verify a structured packet (`steps`), a sentence (`claim`), a document (`document`), or one
    mode call (`mode` + `params`). Returns the engine's result dict: at least {"verdict", "trail",
    "seal"}. Exactly one of steps / claim / document / mode is given.

    verdict is read exactly (verdict.read): HOLDS survived every attempted refutation, BROKEN
    is a counterexample, anything else means the engine could not test it — never a failure of
    the claim.
    """
    given = [k for k, v in (("steps", steps), ("claim", claim), ("document", document), ("mode", mode))
             if v is not None]
    if len(given) != 1:
        raise ValueError("verify() takes exactly one of steps=[...], claim='...', document={...}, "
                         "or mode='...' (with params={...})")
    from concordance.config import EngineConfig
    from concordance.mcp import server as _server
    cfg = config or EngineConfig()
    args: Dict[str, Any] = {"seal": bool(seal)}
    if steps is not None:
        args["steps"] = steps
    elif document is not None:
        args["document"] = document
    elif mode is not None:
        args["mode"], args["params"] = str(mode), dict(params or {})
    else:
        args["claim"] = str(claim)
    return _server._call_tool("verify", args, cfg)


def payload_for(output: Any) -> Dict[str, Any]:
    """The JSON dispatch every adapter's default extractor shares: a model output that parses as
    JSON with a `steps` list, a `document` dict, or `{mode, params}` is sent as that packet; a JSON
    `{claim}` as that claim; a bare list of step dicts as steps; anything else is a plain claim.
    Returns keyword arguments for `verify`."""
    data = output
    if isinstance(output, (str, bytes)):
        text = output.decode() if isinstance(output, bytes) else output
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            return {"claim": text}
    if isinstance(data, dict):
        if isinstance(data.get("steps"), list) and not isinstance(data.get("document"), dict):
            return {"steps": list(data["steps"])}
        if isinstance(data.get("document"), dict):
            return {"document": dict(data["document"])}
        if isinstance(data.get("mode"), str):
            p = data.get("params")
            return {"mode": data["mode"], "params": dict(p) if isinstance(p, dict) else {}}
        if isinstance(data.get("claim"), str):
            return {"claim": data["claim"]}
    if isinstance(data, list) and data and all(isinstance(x, dict) and "domain" in x for x in data):
        return {"steps": list(data)}
    # JSON, but not a shape the engine takes as a packet: it is text making a claim.
    return {"claim": output if isinstance(output, str) else json.dumps(data, default=str)}
