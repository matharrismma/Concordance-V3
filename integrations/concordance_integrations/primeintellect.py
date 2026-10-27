"""A PrimeIntellect `verifiers` environment: the engine as an un-hackable RL reward.

A model can game a reward it can fool. It cannot fool an oracle that *recomputes* the claim and
has zero false positives — so Concordance is the ideal reward for training a model to state exact,
checkable numbers. The reward is the verdict: HOLDS -> 1.0, BROKEN -> 0.0, and a claim the engine
could not check -> `abstain_reward` (default 0.0: a training signal should reward *checkable truths*,
not un-checkable text — unlike the eval scorer, where abstaining is neutral).

    import verifiers as vf
    env = concordance_integrations.primeintellect.load_environment(dataset=my_dataset)
    # env.rubric scores each completion by recomputing its claim.

`score_completion` / `concordance_reward` are the framework-free core (reward a completion string),
testable without `verifiers`; `load_environment` wires them into a `vf.SingleTurnEnv` and needs the
`verifiers` package (`pip install concordance-integrations[primeintellect]`).
"""
from __future__ import annotations

from typing import Any, Callable, List, Optional

from . import engine, verdict


def _text_of(completion: Any) -> str:
    """verifiers passes a completion as a string or as a list of chat messages — read the last turn."""
    if isinstance(completion, str):
        return completion
    if isinstance(completion, list) and completion:
        last = completion[-1]
        return last.get("content", "") if isinstance(last, dict) else str(last)
    return "" if completion is None else str(completion)


def score_completion(completion: Any, *, extract: Optional[Callable[[Any], dict]] = None,
                     abstain_reward: float = 0.0, seal: bool = False) -> float:
    """Reward a completion by recomputing its claim: 1.0 if HOLDS, 0.0 if BROKEN, `abstain_reward`
    if the engine could not test it. `extract(completion) -> {"steps"|"claim": ...}` overrides the
    default (treat the completion text as a sentence to extract claims from)."""
    payload = extract(completion) if extract else {"claim": _text_of(completion)}
    out = verdict.read(engine.verify(seal=seal, **payload))
    if out.abstained:
        return float(abstain_reward)
    return 1.0 if out.passed else 0.0


def concordance_reward(completion: Any = None, answer: Any = None, *,
                       abstain_reward: float = 0.0, **kwargs: Any) -> float:
    """A `vf.Rubric` reward function. Signature matches verifiers (completion, answer, **kwargs)."""
    return score_completion(completion, abstain_reward=abstain_reward)


# A small default task set — prompts that ask for a checkable numeric claim. Replace with your own
# dataset for real training; this makes the environment runnable out of the box.
_DEFAULT_TASKS: List[str] = [
    "State one true sentence of the form 'a <principal> loan at <rate>% a year over <months> months "
    "is <payment> a month', with the payment correct.",
    "State one true percentage claim of the form 'X% of Y is Z'.",
    "State one true claim of the form '<n> factorial is <value>'.",
    "State one true loan-to-value claim: 'a <loan> loan on a <value> property is <p>% LTV'.",
    "State one true balance-sheet claim: 'assets of A, liabilities of L, and equity of E', A = L + E.",
]


def _default_dataset():
    from datasets import Dataset  # part of the verifiers stack
    return Dataset.from_list([{"question": q, "answer": ""} for q in _DEFAULT_TASKS])


def load_environment(dataset: Any = None, *, abstain_reward: float = 0.0,
                     seal: bool = False, **kwargs: Any):
    """Build a `verifiers` SingleTurnEnv whose reward is the Concordance verdict — deterministic,
    0-false-positive, un-hackable. Pass your own `dataset` (a HF Dataset with a prompt column);
    without one, a small default task set is used. Requires the `verifiers` package."""
    import verifiers as vf

    def reward(completion: Any = None, answer: Any = None, **kw: Any) -> float:
        return score_completion(completion, abstain_reward=abstain_reward, seal=seal)

    rubric = vf.Rubric(funcs=[reward], weights=[1.0])
    ds = dataset if dataset is not None else _default_dataset()
    return vf.SingleTurnEnv(dataset=ds, rubric=rubric, **kwargs)
