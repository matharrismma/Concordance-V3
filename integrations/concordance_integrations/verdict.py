"""Read an engine verdict the one honest way, once, so every adapter agrees.

Three outcomes, never two. A model that only knows pass/fail will score an un-checkable claim
as a failure, which punishes the engine for its own honesty. So the Outcome keeps `checked`
apart from `passed`:

  HOLDS      -> checked, passed        (survived every attempted refutation; carries a seal)
  BROKEN     -> checked, not passed    (a counterexample — the claim is outside the band)
  anything   -> not checked, passed=None
  else                                 (INCOMPLETE, a gap, or an engine failure — a miss stays
                                        a miss; the adapter must not read it as a verdict)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

HOLDS = "HOLDS"
BROKEN = "BROKEN"
INCOMPLETE = "INCOMPLETE"

_READ = {
    HOLDS: "survived every attempted refutation; shown not false, never shown true",
    BROKEN: "a counterexample was found — the claim is outside the band",
    INCOMPLETE: "at least one step could not be tested — a gap, not a verdict",
}


@dataclass(frozen=True)
class Outcome:
    verdict: str                      # the engine's own verdict string, verbatim
    checked: bool                     # True only for HOLDS / BROKEN — the engine actually tested it
    passed: Optional[bool]            # True=HOLDS, False=BROKEN, None=not checked
    reason: str                       # one sentence, from the engine where it gave one
    content_hash: Optional[str]       # the seal address, when sealed
    cite_url: Optional[str]           # the receipt page, when sealed

    @property
    def abstained(self) -> bool:
        return not self.checked

    def receipt(self) -> Dict[str, Any]:
        """A flat, framework-free dict to drop into a trace, a message, or agent state."""
        return {"verdict": self.verdict, "checked": self.checked, "passed": self.passed,
                "reason": self.reason, "content_hash": self.content_hash, "cite_url": self.cite_url}


def read(result: Dict[str, Any]) -> Outcome:
    """Map a raw engine result (engine.verify's return) to an Outcome."""
    result = result or {}
    v = str(result.get("verdict") or "")
    seal = result.get("seal") if isinstance(result.get("seal"), dict) else {}
    content_hash = seal.get("content_hash") or None
    cite_url = seal.get("cite_url") or None
    reason = (result.get("read") or result.get("means") or result.get("note")
              or _READ.get(v) or f"the engine returned {v or 'no verdict'}; nothing to read as a finding")
    if v == HOLDS:
        return Outcome(v, True, True, reason, content_hash, cite_url)
    if v == BROKEN:
        return Outcome(v, True, False, reason, content_hash, cite_url)
    return Outcome(v, False, None, reason, content_hash, cite_url)
