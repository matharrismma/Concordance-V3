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

from typing import Any, Dict, List, Optional


def verify(steps: Optional[List[Dict[str, Any]]] = None, claim: Optional[str] = None,
           *, seal: bool = True, config: Any = None) -> Dict[str, Any]:
    """Verify a structured packet (`steps`) or a sentence (`claim`). Returns the engine's
    result dict: at least {"verdict", "trail", "seal"}. Exactly one of steps/claim is given.

    verdict is read exactly (verdict.read): HOLDS survived every attempted refutation, BROKEN
    is a counterexample, anything else means the engine could not test it — never a failure of
    the claim.
    """
    if (steps is None) == (claim is None):
        raise ValueError("verify() takes exactly one of steps=[...] or claim='...'")
    from concordance.config import EngineConfig
    from concordance.mcp import server as _server
    cfg = config or EngineConfig()
    args: Dict[str, Any] = {"seal": bool(seal)}
    if steps is not None:
        args["steps"] = steps
    else:
        args["claim"] = str(claim)
    return _server._call_tool("verify", args, cfg)
