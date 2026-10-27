"""Calculus & ODE solution check (2026-10-27).

"the derivative of x^2 is 2x", "the integral of 2x is x^2 + C", "the limit of sin(x)/x as x approaches
0 is 1", and "y = e^x satisfies dy/dx = y" returned INCOMPLETE for the same reason the nonlinear-algebra
forms did: the mathematics domain is modes, not a fillable packet, so no extractor built the packet.
These extractors route the UNAMBIGUOUS phrasings to the existing symbolic verifiers (derivative, integral,
limit) and check an ODE BY SUBSTITUTION through the equality verifier — substitute the claimed solution
for y, write each derivative as diff(...), and confirm the two sides reduce to the same thing. Nothing is
solved. A correct claim HOLDS; a wrong one MISMATCHES; ambiguous text ("xy", "1/2x") or prose extracts
NOTHING — the same zero-false-positive discipline that governs all extraction.

The normalizer (_calc_normalize) is the piece the guarded _parse lacks: plain sympify has no implicit
multiplication ("2x" is a SyntaxError) and reads a bare "e" as a symbol, not Euler's number. It is a
strict allowlist tokenizer that inserts "*" only at unambiguous factor adjacencies and DECLINES on
anything it cannot read unambiguously — a normalization that silently changed meaning is worse than a miss.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from concordance.audit import extract, audit, _calc_normalize  # noqa: E402
from concordance.config import EngineConfig  # noqa: E402

CFG = EngineConfig(skip_schema_validation=True)


def _extractors(text):
    return [s["extractor"] for s in extract(text)]


# ---- the normalizer in isolation: 0-FP (a silent meaning change is worse than a miss) ----

def test_normalizer_meaning_preserving_rewrites():
    """The only rewrites are universal: implicit mult, ^->**, Euler's e->E, inf->oo, a known function kept
    as name(...). A function is never split into a product of its letters."""
    assert _calc_normalize("2x") == "2*x"
    assert _calc_normalize("x^2") == "x**2"
    assert _calc_normalize("2(x+1)") == "2*(x+1)"
    assert _calc_normalize("(x+1)(x-1)") == "(x+1)*(x-1)"
    assert _calc_normalize("sin(x)/x") == "sin(x)/x"           # sin kept whole, not s*i*n*(x)
    assert _calc_normalize("e^x") == "E**x"                     # Euler's number, not a symbol
    assert _calc_normalize("x**2 + C") == "x**2+C"             # already-valid input passes through


def test_normalizer_declines_the_ambiguous():
    """Ambiguity is a miss, never a guess: an unknown multi-letter run, a single letter applied like a
    function, implicit mult after a divided number, and a stray non-math character all return None."""
    assert _calc_normalize("xy") is None                        # product of two symbols, or a 2-char name?
    assert _calc_normalize("y(x+1)") is None                    # y times (x+1), or the function y of x+1?
    assert _calc_normalize("1/2x") is None                      # (1/2)x, or 1/(2x)?
    assert _calc_normalize("foo") is None                       # an unlisted name is not a product
    assert _calc_normalize("x = 2") is None                     # not a bare expression
    assert _calc_normalize("x +") is None                       # a dangling operator


# ---- derivative ----

def test_derivative_holds():
    for t in ["the derivative of x^2 is 2x",
              "d/dx(x^2) = 2x",
              "the derivative of x^3 with respect to x is 3x^2",
              "The derivative of sin(x) is cos(x)."]:
        assert _extractors(t) == ["derivative"], t
        assert audit(t, CFG, seal=False)["held"] == 1, t


def test_derivative_refuses_the_false_twin():
    res = audit("the derivative of x^2 is 3x", CFG, seal=False)
    assert res["broken"] == 1 and res["results"][0]["status"] == "MISMATCH"


# ---- integral (the verifier differentiates the claim, so "+ C" falls away) ----

def test_integral_holds():
    for t in ["the integral of 2x is x^2 + C",
              "the integral of 2x is x^2",
              "the antiderivative of cos(x) is sin(x) + C"]:
        assert _extractors(t) == ["integral"], t
        assert audit(t, CFG, seal=False)["held"] == 1, t


def test_integral_refuses_the_false_twin():
    res = audit("the integral of 2x is x^3 + C", CFG, seal=False)
    assert res["broken"] == 1 and res["results"][0]["status"] == "MISMATCH"


# ---- limit (variable, point, and value all read from the phrasing) ----

def test_limit_holds():
    for t in ["the limit of sin(x)/x as x approaches 0 is 1",
              "the limit of (1 + 1/x)^x as x approaches infinity is e"]:
        assert _extractors(t) == ["limit"], t
        assert audit(t, CFG, seal=False)["held"] == 1, t


def test_limit_refuses_the_false_twin():
    res = audit("the limit of sin(x)/x as x approaches 0 is 0", CFG, seal=False)
    assert res["broken"] == 1 and res["results"][0]["status"] == "MISMATCH"


# ---- ODE by substitution (route through the equality verifier; never solve) ----

def test_ode_holds():
    for t in ["y = e^x satisfies dy/dx = y",
              "y = C*exp(2x) is a solution of y' = 2y",
              "y = sin(x) is a solution of y'' + y = 0"]:
        step = extract(t)
        assert [s["extractor"] for s in step] == ["ode"], t
        assert step[0]["spec"]["mode"] == "equality", t         # ODE-by-substitution rides the equality verifier
        assert audit(t, CFG, seal=False)["held"] == 1, t


def test_ode_refuses_the_false_twin():
    """y = x^2 does NOT satisfy dy/dx = y: substituting gives 2x on the left, x^2 on the right."""
    res = audit("y = x^2 satisfies dy/dx = y", CFG, seal=False)
    assert res["broken"] == 1 and res["results"][0]["status"] == "MISMATCH"


# ---- zero false positives: prose and ambiguity in a calculus-shaped sentence extract nothing ----

def test_calculus_zero_false_positives():
    for t in [
        "the derivative of the policy is clear",          # prose, not an expression
        "the integral of the plan is sound",              # prose
        "the limit of liability is 5000 dollars",         # 'limit of' but no 'as v approaches p'
        "the derivative of xy is y",                      # xy ambiguous -> the function will not normalize
        "the derivative of 1/2x is -1/2x^2",              # 1/2x precedence-ambiguous
        "the value of x is 2",                            # no calculus frame at all
        "a = 5 satisfies b = 5",                          # 'satisfies' but the equation has no derivative of a
    ]:
        assert not (set(_extractors(t)) & {"derivative", "integral", "limit", "ode"}), t


if __name__ == "__main__":
    import pytest
    sys.exit(int(pytest.main([__file__, "-q"])))
