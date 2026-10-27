"""The harness adapters (integrations/concordance_integrations), proven against the real engine.

The adapters live outside the lean core (not under src/concordance), so they touch no closure,
module-count, coverage, or vocab gate — only this test. It drives each adapter's framework-free
core against ground-truth goldens (data/domain_goldens.json: a true packet must HOLD, its false
twin must BREAK) and covers the one invariant that matters: a claim the engine could not test
abstains — it is never scored as a failure. The thin framework shims (DeepEval/LangGraph/
Guardrails) are exercised only when those packages are installed; otherwise they skip.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "integrations"))

from concordance_integrations import deepeval as ce_deepeval  # noqa: E402
from concordance_integrations import engine as ce_engine  # noqa: E402
from concordance_integrations import guardrails as ce_guardrails  # noqa: E402
from concordance_integrations import langgraph as ce_langgraph  # noqa: E402
from concordance_integrations import models as ce_models  # noqa: E402
from concordance_integrations import primeintellect as ce_pi  # noqa: E402
from concordance_integrations import translate as ce_translate  # noqa: E402
from concordance_integrations import verdict as ce_verdict  # noqa: E402

_DOMAIN = "mathematics"   # always registered, fast, has a labelled true/false golden pair


def _golden(label: str) -> list:
    goldens = json.loads((_ROOT / "data" / "domain_goldens.json").read_text(encoding="utf-8"))
    g = goldens[_DOMAIN]
    return [{"id": "g", "domain": _DOMAIN, "spec": {g["packet_key"]: g[label]}}]


TRUE_STEPS = _golden("true")
FALSE_STEPS = _golden("false")
UNCHECKABLE = "this sentence carries no arithmetic a verifier could recompute"


# ── the shared read: three outcomes, never two ──────────────────────────────────────────────

def test_engine_and_verdict_true_holds_with_seal():
    out = ce_verdict.read(ce_engine.verify(steps=TRUE_STEPS, seal=True))
    assert out.verdict == "HOLDS"
    assert out.checked is True and out.passed is True
    assert out.content_hash                     # a true claim is sealed
    assert out.abstained is False


def test_engine_and_verdict_false_breaks():
    out = ce_verdict.read(ce_engine.verify(steps=FALSE_STEPS, seal=False))
    assert out.verdict == "BROKEN"
    assert out.checked is True and out.passed is False


def test_uncheckable_abstains_not_fails():
    out = ce_verdict.read(ce_engine.verify(claim=UNCHECKABLE))
    assert out.checked is False and out.passed is None and out.abstained is True


def test_verify_requires_exactly_one_input():
    with pytest.raises(ValueError):
        ce_engine.verify()
    with pytest.raises(ValueError):
        ce_engine.verify(steps=TRUE_STEPS, claim="x")


# ── DeepEval / autoevals scorer (framework-free core) ────────────────────────────────────────

class _Case:
    def __init__(self, actual_output):
        self.actual_output = actual_output


def test_metric_true_passes():
    m = ce_deepeval.ConcordanceMetric(extract=lambda tc: {"steps": TRUE_STEPS})
    assert m.measure(_Case("x")) == 1.0
    assert m.is_successful() is True
    assert m.receipt["content_hash"]


def test_metric_false_fails():
    m = ce_deepeval.ConcordanceMetric(extract=lambda tc: {"steps": FALSE_STEPS})
    assert m.measure(_Case("x")) == 0.0
    assert m.is_successful() is False


def test_metric_abstain_policy():
    passy = ce_deepeval.ConcordanceMetric(extract=lambda tc: {"claim": UNCHECKABLE})
    assert passy.measure(_Case(UNCHECKABLE)) == 1.0 and passy.is_successful() is True
    stricter = ce_deepeval.ConcordanceMetric(extract=lambda tc: {"claim": UNCHECKABLE},
                                             abstain_is_success=False)
    assert stricter.measure(_Case(UNCHECKABLE)) == 0.0 and stricter.is_successful() is False


def test_scorer_shape_and_skip_on_abstain():
    assert ce_deepeval.concordance_scorer(steps=TRUE_STEPS)["score"] == 1.0
    assert ce_deepeval.concordance_scorer(steps=FALSE_STEPS)["score"] == 0.0
    s = ce_deepeval.concordance_scorer(claim=UNCHECKABLE)
    assert s["score"] is None and s["metadata"]["checked"] is False
    assert s["name"] == "Concordance"


# ── LangGraph node (framework-free core) ─────────────────────────────────────────────────────

def test_node_writes_receipt():
    node = ce_langgraph.make_verify_node(lambda s: {"steps": s["steps"]})
    assert node({"steps": TRUE_STEPS})["concordance"]["passed"] is True
    assert node({"steps": FALSE_STEPS})["concordance"]["passed"] is False


def test_node_fail_fast_raises_only_on_counterexample():
    node = ce_langgraph.make_verify_node(lambda s: s["payload"], fail_fast=True)
    assert node({"payload": {"steps": TRUE_STEPS}})["concordance"]["passed"] is True
    with pytest.raises(ce_langgraph.ConcordanceCounterexample):
        node({"payload": {"steps": FALSE_STEPS}})
    # a claim the engine could not test must NOT raise — a miss stays a miss
    assert node({"payload": {"claim": UNCHECKABLE}})["concordance"]["checked"] is False


# ── Guardrails validator (framework-free core) ───────────────────────────────────────────────

def test_validate_text_blocks_only_counterexample():
    ok_true, _, rc_true = ce_guardrails.validate_text("")
    assert ok_true is True and rc_true  # empty extracts nothing -> abstain -> not blocked

    extract_steps = {"extract": lambda value, meta: {"steps": FALSE_STEPS}}
    ok_false, _, _ = ce_guardrails.validate_text("ignored", extract_steps)
    assert ok_false is False

    extract_true = {"extract": lambda value, meta: {"steps": TRUE_STEPS}}
    ok_pass, _, _ = ce_guardrails.validate_text("ignored", extract_true)
    assert ok_pass is True


# ── the edge translator: deterministic head, model tail, verdict always recomputed ──────────

_GOOD = '{"loan_principal":12000,"annual_rate":0.06,"loan_term_months":12,"claimed_monthly_payment":1032.80}'
_TIER2 = "mortgage: loan twelve thousand, rate six percent, term one year, claimed payment 1032.80 a month"


class _Mock:
    def __init__(self, text): self.text = text; self.calls = 0
    def __call__(self, prompt): self.calls += 1; return "sure: " + self.text


def test_tier1_uses_the_extractor_and_never_calls_the_model():
    m = _Mock(_GOOD)
    r = ce_translate.verify_text("a 12,000 loan at 6% annual over 12 months is 1032.80 a month", model=m)
    assert r["verdict"] == "HOLDS" and r["reached_by"] == "extractor"
    assert m.calls == 0   # the deterministic head handled it — the model is not paid for


def test_tier2_lets_the_model_reach_the_verifier():
    m = _Mock(_GOOD)
    r = ce_translate.verify_text(_TIER2, model=m)   # word-number phrasing the extractors miss
    assert r["verdict"] == "HOLDS" and r["reached_by"] == "model" and m.calls == 1
    assert r["proposed_packet"]["RE_VERIFY"]["claimed_monthly_payment"] == 1032.80  # what was checked, shown


def test_the_model_cannot_make_a_false_claim_hold():
    m = _Mock(_GOOD.replace("1032.80", "5000"))   # the model proposes a false packet
    r = ce_translate.verify_text(_TIER2, model=m)
    assert r["verdict"] == "BROKEN"               # the engine recomputed — 0 FP preserved


def test_no_model_falls_back_to_an_honest_null():
    r = ce_translate.verify_text(_TIER2, model=None)
    assert r["reached_by"] == "none" and r["verdict"] != "HOLDS"


def test_model_wrappers_construct_without_the_sdk():
    # the SDK is imported lazily inside the call, so building a wrapper needs nothing installed
    assert callable(ce_models.anthropic_model("claude-x"))
    assert callable(ce_models.openai_model("gpt-x", base_url="https://openrouter.ai/api/v1"))


class _Staged:
    """A model that returns an incomplete packet first, then a complete one — a weak model the PID
    loop should correct."""
    def __init__(self): self.calls = 0
    def __call__(self, prompt):
        self.calls += 1
        return '{"loan_principal":12000}' if self.calls == 1 else _GOOD


def test_pid_loop_corrects_a_weak_model():
    m = _Staged()
    r = ce_translate.verify_text(_TIER2, model=m, max_rounds=3)
    assert r["verdict"] == "HOLDS" and r["reached_by"] == "model" and m.calls == 2   # converged


def test_pid_loop_default_is_single_shot():
    m = _Staged()
    r = ce_translate.verify_text(_TIER2, model=m)   # max_rounds=1 -> no correction
    assert r["reached_by"] == "none" and m.calls == 1


def test_pid_loop_never_flips_a_broken_verdict():
    false_once = _Mock(_GOOD.replace("1032.80", "5000"))
    r = ce_translate.verify_text(_TIER2, model=false_once, max_rounds=5)
    assert r["verdict"] == "BROKEN" and false_once.calls == 1   # stops at the band, never retries to pass


# ── PrimeIntellect reward (framework-free core): the engine as an un-hackable RL reward ──────

def test_primeintellect_reward_is_the_verdict():
    assert ce_pi.concordance_reward(completion="7 factorial is 5040") == 1.0      # HOLDS
    assert ce_pi.concordance_reward(completion="7 factorial is 9999") == 0.0      # BROKEN
    assert ce_pi.concordance_reward(completion=UNCHECKABLE) == 0.0                # abstain -> 0 for training


def test_primeintellect_reward_reads_chat_and_honors_abstain():
    assert ce_pi.score_completion([{"role": "assistant", "content": "15% of 200 is 30"}]) == 1.0
    assert ce_pi.score_completion(UNCHECKABLE, abstain_reward=0.3) == 0.3


def test_primeintellect_env_builds_when_verifiers_installed():
    pytest.importorskip("verifiers")
    env = ce_pi.load_environment()
    assert env is not None and getattr(env, "rubric", None) is not None


# ── framework shims — run only where the framework is installed ──────────────────────────────

def test_deepeval_basemetric_subclass_when_installed():
    pytest.importorskip("deepeval")
    from deepeval.metrics import BaseMetric
    assert isinstance(ce_deepeval.ConcordanceMetric(), BaseMetric)


def test_langgraph_stategraph_composes_when_installed():
    pytest.importorskip("langgraph")
    from typing import TypedDict

    from langgraph.graph import END, START, StateGraph

    class S(TypedDict, total=False):
        steps: list
        concordance: dict

    g = StateGraph(S)
    g.add_node("verify", ce_langgraph.make_verify_node(lambda s: {"steps": s["steps"]}))
    g.add_edge(START, "verify")
    g.add_edge("verify", END)
    out = g.compile().invoke({"steps": TRUE_STEPS})
    assert out["concordance"]["passed"] is True


def test_guardrails_validator_registers_when_installed():
    pytest.importorskip("guardrails")
    assert ce_guardrails.ConcordanceNumbers is not None
