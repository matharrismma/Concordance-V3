"""A Guardrails validator: block a number only when it is provably wrong.

Registered as `concordance/numbers` for a string field. It extracts the checkable claims from
the text and verifies each. It fails **only** on a counterexample (BROKEN) — a number shown to
be outside its band. A claim the engine could not test is not a failure, so the guard does not
block it; that honesty is reported in the result's metadata, never hidden. This is the
difference from a pattern or a second model: the guard fires on a recomputation, not a guess.

    from concordance_integrations.guardrails import ConcordanceNumbers
    guard = Guard().use(ConcordanceNumbers, on_fail="exception")

`validate_text(value)` is the same decision without Guardrails installed — framework-free and
always importable, so the engine logic is testable on its own. `ConcordanceNumbers` is the
registered Validator class when Guardrails is installed, else None; `register()` builds it on
demand and raises a clear error if Guardrails is missing.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Tuple

from . import engine, verdict


def validate_text(value: str, metadata: Optional[Dict[str, Any]] = None
                  ) -> Tuple[bool, str, Dict[str, Any]]:
    """Returns (ok, reason, receipt). ok is False only for a counterexample. `metadata` may
    carry `extract(value, metadata) -> {"steps"|"claim": ...}` to pass a structured packet."""
    metadata = metadata or {}
    extract: Optional[Callable[[str, Dict[str, Any]], Dict[str, Any]]] = metadata.get("extract")
    payload = extract(value, metadata) if extract else {"claim": value}
    out = verdict.read(engine.verify(**payload))
    ok = not (out.checked and not out.passed)   # fail only on BROKEN
    return ok, out.reason, out.receipt()


def _register():
    """Define + register the Validator against whichever Guardrails layout is installed."""
    try:                                                  # guardrails-ai >= 0.4
        from guardrails.validator_base import (FailResult, PassResult, Validator,
                                               register_validator)
    except Exception:                                     # noqa: BLE001 — older layout
        from guardrails.validators import (FailResult, PassResult, Validator,  # type: ignore
                                           register_validator)

    @register_validator(name="concordance/numbers", data_type="string")
    class ConcordanceNumbers(Validator):  # type: ignore[misc, valid-type]
        def validate(self, value: Any, metadata: Dict[str, Any]) -> Any:
            ok, reason, receipt = validate_text(str(value), metadata)
            if ok:
                return PassResult(metadata=receipt)
            return FailResult(error_message=reason, metadata=receipt)

    return ConcordanceNumbers


def register():
    """Register and return the Validator class. Raises if Guardrails is not installed."""
    try:
        return _register()
    except ImportError as exc:  # noqa: PERF203
        raise ImportError("guardrails-ai is not installed; `pip install "
                          "concordance-integrations[guardrails]`") from exc


try:
    ConcordanceNumbers: Any = _register()
except Exception:  # noqa: BLE001 — Guardrails optional; import of this module must still work
    ConcordanceNumbers = None
