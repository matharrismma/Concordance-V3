"""Source layers — provenance tiers named on a sealed record."""
from __future__ import annotations

SECULAR_LAYERS: tuple[str, ...] = ("primary", "secondary", "tertiary", "reference")
WITNESS_LAYERS: tuple[str, ...] = SECULAR_LAYERS   # v3 compatibility alias; the .org app defines its own


def layers_for(surface: str) -> tuple[str, ...]:
    return SECULAR_LAYERS
