"""concordance — deterministic verification with re-checkable receipts.

A claim comes in as a structured packet; a pure verifier recomputes it; the result is a verdict, the
worked trail, and a content-addressed seal in an append-only ledger. See README.md.
"""
from __future__ import annotations

from .config import SURFACES, EngineConfig

__all__ = ["EngineConfig", "SURFACES", "__version__"]
__version__ = "3.0.0a1"
