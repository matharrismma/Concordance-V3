"""concordance-integrations — the engine inside other people's harnesses.

Thin adapters that wrap one engine call (``engine.verify`` → ``verdict.read``) for the
evaluation and agent frameworks teams already run. Each is a few lines of glue; the value is
the receipt they carry back. Importing any adapter module never requires its framework.

  - ``deepeval``   — a DeepEval metric + an autoevals/Braintrust scorer
  - ``langgraph``  — a verify node for any callable-over-dict graph (LangGraph, AutoGen, …)
  - ``guardrails`` — a Guardrails validator that blocks only a provably-wrong number

The one rule they share (``verdict``): HOLDS passes, BROKEN fails, everything else abstains —
a claim the engine could not test is never scored as a failure.
"""
from __future__ import annotations

from . import engine, verdict
from .verdict import Outcome

__all__ = ["engine", "verdict", "Outcome", "__version__"]
__version__ = "0.1.0a0"
