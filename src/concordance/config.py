"""EngineConfig — run settings for one engine.

v3 has one surface. The v2 `surface` field is accepted for compatibility and ignored except that
`witness` is rejected: the witness verifiers and their surfacing live in the .org application, which
registers them through the `concordance.verifiers` entry-point group.
"""
from __future__ import annotations

from dataclasses import dataclass

SURFACES: tuple[str, ...] = ("secular",)
IDENTITY = "Concordance — deterministic verification with re-checkable receipts"


@dataclass(frozen=True)
class EngineConfig:
    surface: str = "secular"
    run_verifiers: bool = True
    skip_schema_validation: bool = False
    default_scope: str = "local"
    schema_path: str = ""

    def __post_init__(self) -> None:
        if self.surface not in SURFACES:
            raise ValueError(f"surface must be one of {SURFACES}, got {self.surface!r}")

    @property
    def identity(self) -> str:
        return IDENTITY

    @property
    def source_layers(self) -> tuple[str, ...]:
        from .layers import layers_for
        return layers_for(self.surface)

    @property
    def witness_surfaced(self) -> bool:
        return False
