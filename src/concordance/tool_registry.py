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
             "span; coverage.unchecked_text names the rest). Not a truth engine: where a value can be "
             "computed it is, and the claim must fall in a narrow band around it; everything else is "
             "narrowed, not proven. Returns verdict HOLDS | PARTIAL | BROKEN | INCOMPLETE | SCHEMA_ERROR | "
             "SYSTEM_ERROR, `read` (one sentence on what the verdict is not), `refutations` (attempted / "
             "survived / counterexamples / not_applicable, with bands), the worked trail, and a seal. HOLDS "
             "means survived every attempted refutation — never shown true. BROKEN carries a re-runnable "
             "counterexample, the strongest finding here. SYSTEM_ERROR and INCOMPLETE say nothing about the claim.",
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
             "packets={claim_id: steps}. Elimination, not averaging: per claim, the band the recompute names, the "
             "stated values it eliminated (with how far outside), the survivors, and their [min, max] bracket "
             "(narrow_way); plus the claim matrix, the SVD spectrum (triage: which claims to try to kill first), "
             "verdicts per writer, the nearest clean draft, and feedback per writer naming its counterexample. "
             "A flat spectrum returns UNDERDETERMINED rather than a mean.",
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
