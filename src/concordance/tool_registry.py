"""The MCP tool registry — the single source of truth for what this server exposes.

A leaf module: imports nothing from the engine. Eight tools. Anything else is an application's
business and registers on its own server in front of this one.
"""
from __future__ import annotations

from typing import Dict, List, NamedTuple


class ToolSpec(NamedTuple):
    name: str
    effect: str        # read | derive | preserve
    description: str
    schema: dict


_S = {"type": "string"}
_N = {"type": "number"}
_B = {"type": "boolean"}

REGISTRY: List[ToolSpec] = [
    ToolSpec("verify", "derive",
             "Verify numeric claims deterministically. Preferred form: steps=[{id, domain, spec}] where spec is "
             "the domain's packet (find_verifier returns the schema). Also accepts {mode, params} for pure "
             "arithmetic, or a plain-language `claim` (checked only where an extractor recognises a tight "
             "span; coverage.unchecked_text names the rest). Returns verdict HOLDS | PARTIAL | BROKEN | "
             "INCOMPLETE | SCHEMA_ERROR | SYSTEM_ERROR, the worked trail, and a content-addressed seal. Only "
             "BROKEN is a finding about the claim; SYSTEM_ERROR and INCOMPLETE say nothing about its truth.",
             {"type": "object", "properties": {
                 "steps": {"type": "array", "items": {"type": "object"}},
                 "mode": {"type": "string", "enum": ["equality", "inequality", "derivative", "integral",
                                                      "limit", "solve", "numeric", "calc_chain", "system",
                                                      "number_theory"]},
                 "params": {"type": "object"},
                 "claim": _S,
                 "document": {"type": "object"},
                 "seal": _B}}),
    ToolSpec("discern", "read",
             "Plain text in; a proposal out, no verdict: the de-identified text that would be checked, the "
             "structured claims the extractor recognised (ready to pass to verify as steps), and a domain "
             "hint. A cry for help is discerned first and never routed to arithmetic.",
             {"type": "object", "properties": {"text": _S}, "required": ["text"]}),
    ToolSpec("find_verifier", "read",
             "Keyword or claim in; the domain, its named checks, and the JSON schema of its packet out.",
             {"type": "object", "properties": {"query": _S}, "required": ["query"]}),
    ToolSpec("seal_fetch", "read",
             "Fetch a sealed record by content hash. Re-hash the record to confirm it matches.",
             {"type": "object", "properties": {"hash": _S}, "required": ["hash"]}),
    ToolSpec("audit", "derive",
             "A document in; every extractable claim verified, with per-fragment coverage: what was checked, "
             "what held, what broke, and the material text that was NOT checked.",
             {"type": "object", "properties": {"text": _S, "seal": _B}, "required": ["text"]}),
    ToolSpec("scribe", "derive",
             "Score one pass of a multi-writer draft: drafts=[{writer, claims:[{id, value, formula}]}] plus "
             "packets={claim_id: steps}. Returns the claim matrix, the SVD spectrum (which claims the writers "
             "disagree on), engine verdicts per writer, the nearest clean draft, and feedback text per writer. "
             "Disagreement is triage for the verifier, not a truth signal; a flat spectrum returns "
             "INCOMPLETE rather than an average.",
             {"type": "object", "properties": {
                 "drafts": {"type": "array", "items": {"type": "object"}},
                 "packets": {"type": "object"},
                 "claim_ids": {"type": "array", "items": _S}}, "required": ["drafts"]}),
    ToolSpec("capabilities", "read",
             "Live counts and limits: verifier modules, domain names, checks, tools, benchmark, ledger — each "
             "with a line saying exactly what was counted.",
             {"type": "object", "properties": {}}),
    ToolSpec("ledger_verify", "read",
             "Re-walk the local append-only ledger's hash chain. Returns ok, the entry count, and the first "
             "break if any.",
             {"type": "object", "properties": {}}),
]

BY_NAME: Dict[str, ToolSpec] = {t.name: t for t in REGISTRY}
NAMES: List[str] = [t.name for t in REGISTRY]

__all__ = ["ToolSpec", "REGISTRY", "BY_NAME", "NAMES"]
