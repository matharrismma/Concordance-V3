"""Nonlinear-algebra solution check (2026-10-27).

"x^2 = 2 has solution x = 1.41421356", "x^3 - 8 = 0 has root x = 2", and the small system
"x^2 + y^2 = 25 and y = x has solution (3.5355, 3.5355)" returned INCOMPLETE: the mathematics
domain is modes, not a fillable packet, so the translator could not reach it and no extractor built
the packet. These extractors VERIFY BY SUBSTITUTION — the claimed value goes into the residual
R = LHS - RHS and must vanish, judged at the value's OWN stated precision (propagated through the
local slope |R'|). A true root HOLDS; a wrong value MISMATCHES; ambiguous / too-coarse text extracts
NOTHING — the same zero-false-positive discipline that governs all extraction.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from concordance.audit import extract, audit  # noqa: E402
from concordance.config import EngineConfig  # noqa: E402

CFG = EngineConfig(skip_schema_validation=True)


def _extractors(text):
    return [s["extractor"] for s in extract(text)]


# ---- single variable: a claimed root, verified by substitution ----

def test_irrational_root_holds_at_stated_precision():
    """sqrt(2) = 1.41421356... is irrational; the claim is substituted (never solved) and judged at the
    precision stated — the residual R(V)/|R'(V)| is V's own distance from the true root (a Newton step),
    which lies inside half a unit in the last written place."""
    text = "x^2 = 2 has solution x = 1.41421356"
    assert _extractors(text) == ["equation_solution"]
    step = extract(text)[0]
    assert step["spec"]["mode"] == "numeric" and step["spec"]["params"]["claimed_literal"] == "1.41421356"
    res = audit(text, CFG, seal=False)
    assert res["held"] == 1 and res["broken"] == 0


def test_exact_integer_root_holds():
    """An exact root holds even at one significant figure (the residual is exactly zero). The "= 0" form
    the task names is handled cleanly (no stray reading of the exponent as arithmetic)."""
    for t in ["x^3 - 8 = 0 has root x = 2", "x^2 - 4 = 0 has solution x = 2", "x^2 = 4 has root x = 2"]:
        assert _extractors(t) == ["equation_solution"], t
        res = audit(t, CFG, seal=False)
        assert res["held"] == 1 and res["broken"] == 0, (t, res["results"])


def test_low_precision_root_holds_at_its_own_precision():
    """"1.414" is sqrt(2) to the figures written, so it holds at that precision; a different variable
    letter and a mid-sentence placement are handled the same way."""
    for t in ["x^2 = 2 has solution x = 1.414", "n^2 = 9 has solution n = 3",
              "The equation x^2 = 2 has solution x = 1.41421356."]:
        assert _extractors(t) == ["equation_solution"], t
        assert audit(t, CFG, seal=False)["held"] == 1, t


def test_single_var_refuses_the_false_twin():
    """A value wrong beyond the place it is written to leaves a residual past the window -> MISMATCH."""
    for t in ["x^2 = 2 has solution x = 1.5",        # nowhere near sqrt(2)
              "x^2 = 2 has solution x = 1.41425",     # wrong in the 5th decimal
              "x^3 = 8 has root x = 2.10"]:           # 2.1^3 = 9.26, not 8 (stated to 3 figures)
        res = audit(t, CFG, seal=False)
        assert res["broken"] == 1 and res["results"][0]["status"] == "MISMATCH", (t, res["results"])


def test_single_var_one_figure_non_exact_extracts_nothing():
    """One significant figure earns no window (too coarse to judge an irrational either way) unless the
    value is an exact root; "x^2 = 2 has solution x = 1" is neither right nor wrong at that coarseness, so
    a miss stays a miss."""
    for t in ["x^2 = 2 has solution x = 1", "x^2 = 3 has solution x = 2"]:
        assert "equation_solution" not in _extractors(t), t


def test_single_var_zero_false_positives():
    """The unambiguous "has (solution|root) v = value" connective and a strict polynomial are required;
    ordinary prose in a similar shape extracts NOTHING — better to miss than check the wrong thing."""
    for t in [
        "the roots of the problem are deep",             # figurative, no equation
        "the meeting has a solution of x = 5",           # 'has a solution' but no equation before it
        "solution x = 5 was proposed",                   # no 'has', no equation
        "x marks the spot at position 2",                # no equation / connective
        "the value of x is 2",                           # no 'has solution/root', no polynomial
    ]:
        assert "equation_solution" not in _extractors(t), t


# ---- a small system: one substitution check per equation, all must hold ----

def test_system_solution_holds():
    text = "x^2 + y^2 = 25 and y = x has solution (3.5355, 3.5355)"
    assert _extractors(text) == ["equation_system"]
    step = extract(text)[0]
    assert step["spec"]["mode"] == "numeric" and step["spec"]["params"]["claimed_literal"] == "3.5355"
    res = audit(text, CFG, seal=False)
    assert res["held"] == 1 and res["broken"] == 0


def test_system_refuses_the_false_twin():
    """(3.6, 3.6) is wrong in the 2nd figure for x^2 + y^2 = 25, y = x; the first equation's residual lands
    well past the window -> MISMATCH (one failing equation breaks the whole claim)."""
    res = audit("x^2 + y^2 = 25 and y = x has solution (3.6000, 3.6000)", CFG, seal=False)
    assert res["broken"] == 1 and res["results"][0]["status"] == "MISMATCH"
    # a wrong SECOND equation is caught too (y should equal x)
    res = audit("x^2 + y^2 = 25 and y = x has solution (3.0000, 4.0000)", CFG, seal=False)
    assert res["broken"] == 1


def test_system_zero_false_positives():
    """Two single-letter variables read off clean equations are required; a sentence whose sides carry a
    word (not a one-letter variable), or no "and"-joined equation pair before the tuple, extracts nothing."""
    for t in [
        "the budget and the plan have a solution of (3, 4)",     # words, not equations
        "the points are at (3, 4) and (5, 6)",                   # no equations, no 'has solution'
        "our options narrowed and we chose solution (1, 2)",     # no equation pair
    ]:
        assert "equation_system" not in _extractors(t), t


# ---- regression: the claim grammar no longer misreads an exponent as arithmetic (2026-10-27) ----

def test_exponent_is_not_read_as_arithmetic():
    """Before the fix, "x^3 - 8 = 0" was tokenized as the false arithmetic "3 - 8 = 0" (the exponent read
    as an operand), so the equation reported a spurious BROKEN. The exponent now ends the expression, as
    the grammar always intended, and genuine arithmetic still extracts."""
    for t in ["x^3 - 8 = 0", "x^2 - 4 = 0", "2x^2 - 5 = 3"]:
        assert "expression" not in _extractors(t), t
    # genuine arithmetic (and a single-* multiply) is untouched
    assert "product" in _extractors("2*3 = 6")
    assert "expression" in _extractors("2 + 3 * 4 = 14")
    assert "expression" in _extractors("3 - 8 = -5")
    assert "power" in _extractors("2^10 = 1024")


if __name__ == "__main__":
    import pytest
    sys.exit(int(pytest.main([__file__, "-q"])))
