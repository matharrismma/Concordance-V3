"""A verdict rests only on a value the claim bound (run 2026-11-04-gcd-lcm-order, step bound-values).

sympy evaluates gcd and lcm of expressions as polynomials before a binder sees them, picks a polynomial's unit by its
default generator order, and reads a third number as a generator. So Subs(gcd(x, 12), x, 6) = 1 read HOLDS though the
gcd of 6 and 12 is 6, and gcd(y - x, x - y) = x - y read HOLDS and, renamed, BROKEN. Poly and degree read that order, and
degree evaluates before a binder too. mathematics._Reader._call now refuses each such call before it runs, and the
refusal reads not checkable in every mode.

Every row below is the plan's, exactly: its EXPECTED READINGS (ledger line 21, which keeps line 4's INCOMPLETE rows
verbatim) and its EVERY MODE table. A row that reads otherwise fails the step and changes only by replan. Names the fix
adds are read inside the tests, so the file collects at the step's base.
"""
from __future__ import annotations

import copy
import importlib.util
import io
import itertools
import json
import math
import queue
import re
import subprocess
import sys
import threading
import tokenize
from collections import Counter
from pathlib import Path

import pytest
import sympy

from concordance.derivation import verify
from concordance.verifiers import mathematics as M

pytestmark = pytest.mark.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
I, H, B, E = "INCOMPLETE", "HOLDS", "BROKEN", "SYSTEM_ERROR"


@pytest.fixture(autouse=True)
def _tables():
    M._ensure_sympy()


def equality(claim):
    a, b = claim.split(" = ")
    return "equality", {"expr_a": a, "expr_b": b}


def read(mode, params):
    return verify({"mode": mode, "params": copy.deepcopy(params)})["verdict"]


def reason(mode, params):
    return verify({"mode": mode, "params": copy.deepcopy(params)})["trail"][0]["detail"]


# ── the plan's rows ──────────────────────────────────────────────────────────────────────────────────────────────────
NOT_CHECKABLE = (
    "gcd(y - x, x - y) = x - y", "gcd(y - x, x - y) = y - x", "gcd(y - x, x - y) = x + y",
    "gcd(y**2 - x**2, x - y) = x - y", "lcm(y - x, x - y) = x - y", "gcd(x/2 - y/3, x - 2*y/3) = x - 2*y/3",
    "gcd(y - x, x - y) + 1 = x - y + 1", "gcd(y - x, x - y)**2 = (x - y)**2",
    "gcd(y - x, x - y)*lcm(y - x, x - y) = -(x - y)**2", "gcd((y - x, x - y)) = x - y",
    "gcd(Tuple(y - x, x - y)) = x - y", "gcd(FiniteSet(y - x, x - y)) = x - y", "gcd(y - x, x - y, modulus=5) = x - y",
    "gcd(y - x, x - y, z) = x - y", "gcd(y - x, x - y, x, y) = x - y", "gcd(sin(x) - y, y - sin(x)) = y - sin(x)",
    "gcd(x - y + z, y - x - z) = x - y + z", "gcd(x**2 - 1, x - 1) = x - 1", "gcd(x**2 - y**2, x + y) = x + y",
    "gcd(x, x + 2) = 1", "gcd(x, 12) = 1", "Sum(gcd(k, 12), (k, 1, 4)) = 4", "Sum(gcd(k, 12), (k, 1, 4)) = 10",
    "Product(gcd(k, 12), (k, 1, 4)) = 1", "Subs(gcd(x, 12), x, 6) = 1", "Subs(gcd(x, 12), x, 6) = 6",
    "Sum(lcm(k, 12), (k, 1, 3)) = 72", "limit(gcd(x, 12), x, 6) = 1", "1/gcd(x**2 - y**2, x + y) = 1/(x + y)",
    "degree(Poly(x**2 + y**3)) = 2", "degree(x**2 + sin(x)**3) = 2", "degree(sin(x)**2 + cos(x)**3) = 3",
    "diff(Poly(x**2 + y**3)) = 2*x",
    "gcd(12.0, 18.0) = 6", "gcd(12.0, 18.0) = 1", "gcd(sqrt(2), 2) = 1", "gcd(pi, 2) = 1",
    "gcd(solve(degree(x**2 + 1) - x, x), 4) = 2", "gcd(solveset(degree(x**2 + 1) - x, x), 4) = 2",
    "det(Matrix(solve(degree(x**2 + 1) - x, x))) = 2", "degree(x**2 + y**3, true) = 0", "degree(x**2 + y**3, (x,)) = 0",
    "degree(x**2 + y**3, (x, y)) = 0", "degree(x**2 + y**3, FiniteSet(x, y)) = 0", "degree(x**2 + y**3, Interval(0, 1)) = 0",
    "degree(Poly(x**2 + y**3, true)) = 0", "degree(Poly(x**2 + y**3, FiniteSet(x, y))) = 0", "degree(x**2 + 1, x + 1) = 0",
    "gcd(-4) = 4", "gcd(-4) = -4",
    "integrate(degree(x**2 + 1), (x, 0, 2)) = 4", "Integral(degree(x**2 + 1), (x, 0, 2)) = 4",
    "Subs(degree(x**2 + 1), x, 2) = 2", "Subs(degree(x**2 + 1), x, 2) = 0", "Sum(degree(x**2 + k, x), (k, 1, 3)) = 6",
    "gcd(nan, 2) = 1",
)
HOLDING = (
    "gcd(12, 18) = 6", "lcm(4, 6) = 12", "gcd(1/2, 1/3) = 1/6", "lcm(1/2, 1/3) = 1", "gcd(-4, 6) = 2", "lcm(-4, 6) = 12",
    "gcd(0, 5) = 5", "Sum(gcd(12, 18), (k, 1, 3)) = 18", "gcd(12, 18, 5) = 1", "lcm(4, 6, 5) = 60", "gcd((12, 18, 5)) = 1",
    "gcd((12, 18), 5) = 1", "gcd(2*3, 4) = 2", "1/gcd(2*3, 4) = 1/2", "degree(x**2 + y**3, y) = 3",
    "degree(Poly(x**2 + y**3, y)) = 3", "degree(Poly(x**2 + y**3, x, y)) = 2", "degree(x**2 + 1) = 2",
    "degree(Poly(x**2 + y**3, (x, y))) = 2", "degree(sin(x)**2 + 1, sin(x)) = 2", "degree(x**2 + 1, y) = 0",
    "integrate(degree(x**2 + 1), x) = 2*x", "gcd((-4,)) = 4", "lcm((-4,)) = 4", "gcd(FiniteSet(-4)) = 4",
)
FALSE = (
    "gcd((-4,)) = -4", "lcm((-4,)) = -4", "gcd(12, 18) = 5", "gcd(-4, 6) = -2", "lcm(-4, 6) = -12", "gcd(12, 18, 5) = 6",
    "lcm(4, 6, 5) = 12", "x/x = 1", "(x**2 - 1)/(x - 1) = x + 1",
)
OTHER_MODES = (
    ("system", {"equations": ["gcd(x, 12) = 1"], "variables": ["x"], "claimed_solution": {"x": 6}}, I),
    ("system", {"equations": ["degree(x**2 + 1) = 2"], "variables": ["x"], "claimed_solution": {"x": 2}}, I),
    ("limit", {"function": "degree(x**2 + 1)", "variable": "x", "point": 2, "claimed_limit": 2}, I),
    ("solve", {"equation": "degree(x**2 + 1) - x", "variable": "x", "claimed_solutions": [2]}, I),
)
PLAN_ROWS = (tuple((*equality(c), v) for rows, v in ((NOT_CHECKABLE, I), (HOLDING, H), (FALSE, B)) for c in rows)
             + OTHER_MODES)

# EVERY MODE: one unbound text each, reaching each mode.
UNBOUND = {"gcd": "gcd(x, 12)", "lcm": "lcm(x, 12)", "Poly": "Poly(x**2 + y**3)",
           "degree": "degree(x**2 + sin(x)**3)"}


def every_mode(text):
    return (
        ("equality", {"expr_a": text, "expr_b": "1"}),
        ("derivative", {"function": text, "variable": "x", "claimed_derivative": "0"}),
        ("integral", {"integrand": text, "variable": "x", "claimed_antiderivative": "x"}),
        ("limit", {"function": text, "variable": "x", "point": 6, "claimed_limit": 1}),
        ("solve", {"equation": f"{text} - 1", "variable": "x", "claimed_solutions": [6]}),
        ("inequality", {"lhs": text, "rhs": "100", "op": "<=", "variable": "x"}),
        ("numeric", {"numeric_expr": text, "claimed_value": 1}),
        ("system", {"equations": [f"{text} = 1"], "variables": ["x"], "claimed_solution": {"x": 6}}),
        ("calc_chain", {"calc_steps": [f"{text} = 1"]}),
        ("calc_chain", {"solution_text": f"<<{text}=1>>"}),
        ("calc_chain", {"calc_steps": ["2 + 2 = 4"], "claimed_answer": text}),
    )


MODE_ROWS = tuple((mode, params, I) for text in UNBOUND.values() for mode, params in every_mode(text))

# Each form of binder the plan names, and the forms it says are none.
INSIDE_A_BINDER = (
    "Sum(degree(x**2 + 1), (k, 1, 3))", "summation(degree(x**2 + 1), (k, 1, 3))", "Product(degree(x**2 + 1), (k, 1, 3))",
    "product(degree(x**2 + 1), (k, 1, 3))", "Subs(degree(x**2 + 1), x, 2)", "limit(degree(x**2 + 1), x, 2)",
    "Limit(degree(x**2 + 1), x, 2)", "integrate(degree(x**2 + 1), (x, 0, 2))", "integrate(degree(x**2 + 1), Tuple(x, 0, 2))",
    "integrate(degree(x**2 + 1), (x, 2))", "Integral(degree(x**2 + 1), (x, 0, 2))",
    "Integral(degree(x**2 + 1), Tuple(x, 0, 2))", "Integral(degree(x**2 + 1), (x, 2))",
    "Sum(degree(Poly(x**2 + 1, x)), (k, 1, 3))", "Sum(Poly(x**2 + 1, x), (k, 1, 3))", "Subs(degree(Poly(x + y, x, y)), x, 2)",
    "Sum(1 + degree(x**2 + 1), (k, 1, 3))", "Sum(Sum(degree(x**2 + 1), (j, 1, 2)), (k, 1, 3))",
    "Sum(k, (k, 1, degree(x**2 + 1)))", "Sum(sin(degree(x**2 + 1)), (k, 1, 3))",
    "solve(degree(x**2 + 1) - x, x)", "solveset(degree(x**2 + 1) - x, x)", "solve(Poly(x**2 - 1, x), x)",
)
NO_BINDER = (
    ("diff(degree(x**2 + 1), x) = 0", H), ("integrate(degree(x**2 + 1), x) = 2*x", H), ("Integral(degree(x**2 + 1), x) = 2*x", H),
    ("Sum(degree(5), (k, 1, 3)) = 0", H), ("Sum(1, (k, 1, 2)) + degree(y**2 + 1) = 4", H),
    ("degree(y**2 + 1) + Sum(1, (k, 1, 2)) = 4", H),
)

# THE NAMED MISSES, each true and each not checkable. MEASURED.md names them; what would read them is the row's comment.
NAMED_MISSES = (
    ("equality", {"expr_a": "gcd(x**2 - 1, x - 1)", "expr_b": "x - 1"}, I),                  # (1) the polynomial mode
    ("equality", {"expr_a": "degree(Poly(x*y))", "expr_b": "1"}, I),                         # (2) naming the generators
    ("equality", {"expr_a": "Sum(degree(y**2 + 1), (k, 1, 3))", "expr_b": "6"}, I),          # (3) nothing substitutes y
    ("limit", {"function": "x*degree(y**2 + 1)", "variable": "x", "point": 2, "claimed_limit": 4}, I),
    ("solve", {"equation": "x - degree(y**2 + 1)", "variable": "x", "claimed_solutions": [2]}, I),
    ("system", {"equations": ["x = degree(y**2 + 1)"], "variables": ["x"], "claimed_solution": {"x": 2}}, I),
)


@pytest.mark.parametrize("mode,params,want", PLAN_ROWS)
def test_each_expected_reading(mode, params, want):
    assert read(mode, params) == want


@pytest.mark.parametrize("mode,params,want", MODE_ROWS)
def test_every_mode_reads_an_unbound_value_as_not_checkable(mode, params, want):
    assert read(mode, params) == want


def test_every_mode_table_covers_every_mode_that_reads_a_text():
    modes = {mode for mode, _params, _want in MODE_ROWS}
    assert modes == {"equality", "derivative", "integral", "limit", "solve", "inequality", "numeric", "system", "calc_chain"}
    assert len(MODE_ROWS) == 4 * 11 and set(UNBOUND) == {"gcd", "lcm", "Poly", "degree"}


@pytest.mark.parametrize("text", INSIDE_A_BINDER)
def test_degree_and_poly_with_a_free_symbol_are_unbound_inside_a_binder(text):
    with pytest.raises(M.UnboundRefused):
        M.parse_expression(text)
    assert read("equality", {"expr_a": text, "expr_b": "0"}) == I


@pytest.mark.parametrize("claim,want", NO_BINDER)
def test_what_binds_nothing_leaves_a_degree_read(claim, want):
    assert read(*equality(claim)) == want


@pytest.mark.parametrize("mode,params,want", NAMED_MISSES)
def test_the_named_misses_stay_misses(mode, params, want):
    assert read(mode, params) == want


def test_the_first_named_miss_is_a_true_claim():
    x = sympy.Symbol("x")
    assert sympy.gcd(x**2 - 1, x - 1) == x - 1


# ── the reader's rule ────────────────────────────────────────────────────────────────────────────────────────────────
def test_unbound_is_a_refusal_with_no_meaning_so_it_keeps_that_handling():
    assert issubclass(M.UnboundRefused, M.NoMeaningRefused)
    assert issubclass(M.UnboundRefused, ValueError)     # a member of _PARSE_ERRORS, whether or not sympy has loaded


@pytest.mark.parametrize("name,text", [("gcd", "gcd(x, 12)"), ("lcm", "lcm(12.0, 18.0)"), ("Poly", "Poly(x**2 + y**3)"),
                                       ("degree", "degree(x**2 + sin(x)**3)"), ("degree", "Subs(degree(x**2 + 1), x, 2)")])
def test_the_refusal_comes_before_the_call_runs(name, text, monkeypatch):
    calls = []
    monkeypatch.setitem(M._FUNCTIONS, name, lambda *a: calls.append(a))
    with pytest.raises(M.UnboundRefused):
        M.parse_expression(text)
    assert calls == []


def test_a_bound_call_is_the_fold_of_two_argument_calls(monkeypatch):
    real, seen = M._FUNCTIONS["gcd"], []

    def two(*args):
        seen.append(len(args))
        return real(*args)
    monkeypatch.setitem(M._FUNCTIONS, "gcd", two)
    assert M.parse_expression("gcd(60, 42, (18, FiniteSet(12)), 3)") == 3
    assert seen and set(seen) == {2}


@pytest.mark.parametrize("text,want", [("gcd(2*3, 4)", 2), ("lcm(2*3, 4)", 12), ("gcd(12, 2*9, 5)", 1), ("gcd((2*3, 4))", 2),
                                       ("degree(x**2 + x)", 2), ("degree(Poly(2*x**2, x))", 2)])
def test_an_unevaluated_read_reads_evaluated_arguments(text, want):
    assert M.parse_expression(text, evaluate=False) == want


def test_an_unevaluated_read_refuses_what_the_evaluated_read_refuses():
    for text in ("gcd(x, 2*3)", "degree(Poly(x + y))", "degree(x**2 + sin(x)**3)", "Subs(degree(x + x**2), x, 2)"):
        with pytest.raises(M.UnboundRefused):
            M.parse_expression(text, evaluate=False)
    with pytest.raises(M.UnboundRefused):
        M._domain_mismatch("gcd(x, 2)", "1", [])        # let out, as a refusal with no meaning is


def test_gcd_and_lcm_agree_with_python_over_integers():
    values = (-6, -4, -1, 0, 1, 3, 4, 6, 12)
    for a in values:
        for b in values:
            assert M.parse_expression(f"gcd({a}, {b})") == math.gcd(a, b)
            assert M.parse_expression(f"lcm({a}, {b})") == math.lcm(a, b)
            for c in (5, -8):
                assert M.parse_expression(f"gcd({a}, {b}, {c})") == math.gcd(a, b, c)
                assert M.parse_expression(f"lcm({a}, {b}, {c})") == math.lcm(a, b, c)


def test_a_fold_over_rationals_is_the_same_in_any_order():
    numbers = ("1/2", "2/3", "3/4", "-5/6")
    for name in ("gcd", "lcm"):
        values = {M.parse_expression(f"{name}({', '.join(order)})") for order in itertools.permutations(numbers)}
        assert len(values) == 1 and values.pop() > 0, name


@pytest.mark.parametrize("text", ["gcd(())", "lcm(())", "gcd((), ())", "gcd(Tuple())", "gcd(FiniteSet())",
                                  "gcd(x)", "lcm(pi)", "gcd(oo, 2)", "gcd(2, Matrix(((12, 18),)))", "gcd(Interval(0, 1), 2)",
                                  "gcd(solveset(sin(x), x), 2)", "gcd(solveset(sin(pi*x), x), 2)",
                                  "lcm(solveset(sin(pi*x), x))"])
def test_a_sequence_that_names_no_numbers_is_refused(text):
    with pytest.raises(M.UnboundRefused):
        M.parse_expression(text)


@pytest.mark.parametrize("name,args", [("gcd", ()), ("lcm", ()), ("gcd", (-4,)), ("lcm", (5,))])
def test_no_sequence_and_no_second_number_stays_refused_as_sympy_refuses_it(name, args):
    with pytest.raises(M.ExpressionRefused) as refused:
        M.parse_expression(f"{name}({', '.join(map(str, args))})")
    assert not isinstance(refused.value, M.UnboundRefused)
    with pytest.raises(TypeError):
        getattr(sympy, name)(*args)


@pytest.mark.parametrize("text", [
    # discovery finds two or more, and nothing names one
    "Poly(x**2 + y**3)", "Poly(x**2 + y**3, ())", "Poly(x**2 + y**3, 2)", "Poly(sin(x)**2 + cos(x)**3)",
    "degree(x**2 + sin(x)**3)", "degree(x**2 + sin(x)**3, 0)", "degree(x**2 + y**3, 1)", "degree(pi*x**2 + 1)",
    "degree(x**2 + y**3, solveset(sin(pi*x), x))", "Poly(x**2 + y**3, x**2)",
    # one generator is enough to miss: sympy reads an integer in its place as a generator's index, and most of the rest as
    # a generator it does not find, where it answers 0
    "degree(x**2 + 1, 0)", "degree(x**2 + 1, pi)", "degree(x**2 + 1, true)", "degree(x**2 + 1, (x,))", "degree(x**2 + 1, ())",
    "degree(x**2 + 1, FiniteSet(x))", "Poly(x**2 + 1, x + 1)", "Poly(x**2 + 1, true)", "Poly(x**2 + 1, 2)",
    # a named generator beside one that names none, and a sequence holding one
    "Poly(x**2 + y**3, true, x)", "Poly(x**2 + y**3, 2, x)", "Poly(x**2 + y**3, x, x + 1)", "Poly(x**2 + y**3, (true,))",
    "Poly(x**2 + y**3, (x + 1, y))",
    # a Poly carries its generators, and what is not among them names none
    "degree(Poly(x**2 + y**3, x, y), true)", "degree(Poly(x**2 + y**3, x, y), (x,))", "degree(Poly(x + y, x, y), x + 1)",
    "degree(Poly(x**2 + y**3, x, y), 1)", "Poly(Poly(x + y, x, y), true)",
])
def test_what_names_no_generator_leaves_the_value_unbound(text):
    with pytest.raises(M.UnboundRefused):
        M.parse_expression(text)


@pytest.mark.parametrize("text", ["Poly(x**2 + y**3, x, y)", "Poly(x**2 + y**3, (x, y))", "Poly(x**2 + y**3, y)",
                                  "Poly(Poly(x**2 + y**3, x, y))", "Poly(x**2 + 1)", "degree(x**2 + y**3, x)",
                                  "degree(x**2 + sin(x)**3, sin(x))", "degree(5)",
                                  "diff(Poly(x**2 + y**3, y, x))", "Poly(x**2 + y**3, Tuple(x, y))",
                                  "Poly(sin(x)**2 + 1, sin(x))", "Poly(sin(x)**2 + y, (sin(x), y))",
                                  "degree(sin(x)**2 + 1, sin(x))", "degree(x**2 + 1, y)",
                                  "degree(Poly(x**2 + y**3, x, y), y)", "degree(Poly(x**2 + y**3, x, y), z)",
                                  "Poly(x**2 + 1, ())"])
def test_a_named_generator_binds_the_value(text):
    M.parse_expression(text)


@pytest.mark.parametrize("claim", ["degree(5, x + 1) = 0", "degree(5, true) = 0", "degree(Poly(5, true)) = 0"])
def test_a_constant_has_no_generator_to_miss(claim):
    assert read(*equality(claim)) == H


def test_a_named_symbol_asks_for_no_discovery(monkeypatch):
    monkeypatch.setattr(M, "_generators", lambda value: pytest.fail("a named generator needs no discovery"))
    for text in ("Poly(x**2 + y**3, x, y)", "Poly(x**2 + y**3, (x, y))", "degree(x**2 + y**3, y)"):
        M.parse_expression(text)


def test_a_poly_given_named_generators_reads_the_claims_own_order():
    assert read(*equality("degree(Poly(x**2 + y**3, y, x)) = 3")) == H
    assert read(*equality("degree(Poly(y**2 + x**3, x, y)) = 3")) == H


def test_a_read_leaves_nothing_behind_for_the_next_claim():
    limit = {"function": "degree(x**2 + 1)", "variable": "x", "point": 2, "claimed_limit": 2}
    bound = equality("degree(x**2 + 1) = 2")
    for _ in range(2):
        assert read("limit", limit) == I
        assert read(*bound) == H


REASONS = {
    "gcd(x, 12)": ("x is not one", "polynomial reading", "Write exact numbers", "mode polynomial with ring and generators"),
    "lcm(12.0, 18.0)": ("is not one", "polynomial reading", "Write exact numbers", "mode polynomial with ring and generators"),
    "gcd(())": ("an empty sequence", "State the numbers"),
    "gcd(solveset(sin(pi*x), x), 2)": ("more numbers than a text can write", "State the numbers"),
    "degree(Poly(x**2 + y**3))": ("rests on the generators sympy discovers, (x, y)", "in an order their names set",
                                  "Name the generators in the call", "mode polynomial with ring and generators"),
    "degree(x**2 + sin(x)**3)": ("rests on the generators sympy discovers", "Name the generators in the call"),
    "degree(x**2 + 1, x + 1)": ("takes x + 1 as a generator", "only a symbol or a generator found in it does",
                                "Name the generators in the call", "mode polynomial with ring and generators"),
    "Subs(degree(x**2 + 1), x, 2)": ("evaluates before the binder", "rest on the symbol", "Write the number it should be"),
}


@pytest.mark.parametrize("text,words", REASONS.items())
def test_the_reason_says_what_the_value_would_rest_on_and_what_would_bind_it(text, words):
    detail = reason("equality", {"expr_a": text, "expr_b": "1"})
    assert detail.startswith(M._REFUSAL)
    assert all(w in detail for w in words), detail


def test_a_long_argument_leaves_the_reason_whole():
    long, other = "v" * 200, "w" * 200
    for text in (f"gcd({long}, 2)", f"degree(Poly({long} + {other}))", f"Sum(degree({long} + 1, {long}), (k, 1, 3))",
                 f"degree({long} + 1, {other} + 1)"):
        detail = reason("equality", {"expr_a": text, "expr_b": "1"})
        assert len(detail) < 300
        assert re.search(r"(mode polynomial with ring and generators|outside the binder)$", detail), detail


# ── the four modes that read a refusal as an error, and packets ──────────────────────────────────────────────────────
@pytest.mark.parametrize("mode,params,want", [
    ("numeric", {"numeric_expr": "sin(", "claimed_value": 1}, E),
    ("numeric", {"numeric_expr": "gcd(-4)", "claimed_value": 4}, E),
    ("numeric", {"numeric_expr": "1/0", "claimed_value": 1}, E),
    ("inequality", {"lhs": "sin(", "rhs": "1", "op": "<="}, E),
    ("inequality", {"lhs": "gcd(-4)", "rhs": "1", "op": "<="}, E),
    ("system", {"equations": ["sin( = 1"], "variables": ["x"], "claimed_solution": {"x": 1}}, E),
    ("system", {"equations": ["x = 1"], "variables": ["x"], "claimed_solution": {"x": "sin("}}, E),
    ("calc_chain", {"calc_steps": ["sin( = 1"]}, B),
    ("calc_chain", {"calc_steps": ["gcd(-4) = 4"]}, B),
    ("calc_chain", {"calc_steps": ["2 + 2 = 4"], "claimed_answer": "sin("}, B),
])
def test_other_refusals_keep_todays_reading_in_those_four_modes(mode, params, want):
    assert read(mode, params) == want


@pytest.mark.parametrize("params,want", [
    ({"calc_steps": ["gcd(12, 18) = 6", "6 * 2 = 12"], "claimed_answer": 12}, H),
    ({"solution_text": "<<gcd(12, 18)=6>> and <<6*2=12>> #### 12"}, H),
    ({"calc_steps": ["lcm(4, 6, 5) = 60"]}, H),
    ({"calc_steps": ["gcd(12.0, 18.0) = 6"]}, H),       # this mode reads a decimal as the exact rational it writes
    ({"calc_steps": ["gcd(12, 18) = 5"]}, B),
    ({"calc_steps": ["gcd(12, 18, 5) = 6"]}, B),
])
def test_a_chain_of_bound_numbers_reads_as_its_arithmetic(params, want):
    assert read("calc_chain", params) == want


@pytest.mark.parametrize("mode,params", [
    ("calc_chain", {"calc_steps": ["gcd(x, 12) = 1", "2 + 2 = 5"]}),
    ("calc_chain", {"calc_steps": ["2 + 2 = 5", "gcd(x, 12) = 1"]}),
    ("calc_chain", {"calc_steps": ["gcd(x, 12) = 1", "2 + 2 = 4"], "claimed_answer": 5}),
    ("system", {"equations": ["gcd(x, 12) = 1", "x = 7"], "variables": ["x"], "claimed_solution": {"x": 6}}),
    ("system", {"equations": ["x = 7", "gcd(x, 12) = 1"], "variables": ["x"], "claimed_solution": {"x": 6}}),
])
def test_an_unbound_step_never_hides_a_false_one(mode, params):
    assert read(mode, params) == B


@pytest.mark.parametrize("artifact", [
    {"numeric_expr": "gcd(x, 12)", "claimed_value": 1},
    {"lhs": "gcd(x, 12)", "rhs": "100", "op": "<="},
    {"equations": ["gcd(x, 12) = 1"], "variables": ["x"], "claimed_solution": {"x": 6}},
    {"calc_steps": ["gcd(x, 12) = 1"]},
    {"function": "degree(x**2 + sin(x)**3)", "variable": "x", "claimed_derivative": "0"},
])
def test_a_passing_artifact_beside_an_unbound_one_reads_incomplete(artifact):
    assert verify({"MATH_VERIFY": {"expr_a": "1", "expr_b": "1", **artifact}})["verdict"] == I


# ── rename invariance ────────────────────────────────────────────────────────────────────────────────────────────────
# Each moves every name a row holds. sympy's generator table holds x before a, so the third turns the pair round; zz is
# outside the table, so the fourth orders it by another rule.
RENAMES = {
    "x and y exchanged": {"x": "y", "y": "x", "z": "w", "k": "n", "j": "m"},
    "a three-way cycle": {"x": "y", "y": "z", "z": "x", "k": "j", "j": "k"},
    "the other way round in the table": {"x": "a", "y": "x", "z": "y", "k": "b", "j": "c"},
    "outside the table": {"x": "zz", "y": "x", "z": "y", "k": "kk", "j": "jj"},
}
NOT_SYMBOLS = {"pi", "E", "I", "oo", "nan", "true", "modulus"}


def tokens(text):
    """Each NAME token with its span, and whether a call reads it."""
    found = list(tokenize.generate_tokens(io.StringIO(text).readline))
    return [(t.string, t.start[1], t.end[1], following.string == "(")
            for t, following in zip(found, found[1:]) if t.type == tokenize.NAME]


def symbols(text):
    return {name for name, _start, _end, called in tokens(text) if not called and name not in NOT_SYMBOLS}


def functions(text):
    return [name for name, _start, _end, called in tokens(text) if called]


def renamed(text, mapping):
    """One token-level rename of every symbol at once, and its own check: a bijection on the text's names, and every
    function name left alone. A name the mapping does not hold stays."""
    moved = {name: mapping.get(name, name) for name in symbols(text)}
    assert len(set(moved.values())) == len(moved), f"{mapping} is no bijection on {sorted(moved)}"
    out = text
    for name, start, end, called in reversed(tokens(text)):
        if name in moved and not called:
            out = out[:start] + moved[name] + out[end:]
    assert functions(out) == functions(text) and symbols(out) == set(moved.values())
    return out


def renamed_params(params, mapping):
    out = {}
    for key, value in params.items():
        if key == "claimed_solution":
            out[key] = {mapping[k]: v for k, v in value.items()}
        elif key == "variable":
            out[key] = mapping[value]
        elif key == "variables":
            out[key] = [mapping[v] for v in value]
        elif isinstance(value, str):
            out[key] = renamed(value, mapping)
        elif isinstance(value, list):
            out[key] = [renamed(v, mapping) if isinstance(v, str) else v for v in value]
        else:
            out[key] = value
    return out


def holds_a_symbol(params):
    texts = [v for value in params.values() for v in (value if isinstance(value, list) else [value])]
    return any(isinstance(v, str) and symbols(v) for v in texts)


EXTRA_ROWS = (tuple((*equality(c), v) for c, v in NO_BINDER)
              + tuple(("equality", {"expr_a": t, "expr_b": "0"}, I) for t in INSIDE_A_BINDER))
SYMBOL_ROWS = tuple(r for r in PLAN_ROWS + MODE_ROWS + NAMED_MISSES + EXTRA_ROWS if holds_a_symbol(r[1]))


def _restate():
    spec = importlib.util.spec_from_file_location("_bound_values_restate", ROOT / "tools" / "restate.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_the_rename_rows_are_not_thin():
    assert len(SYMBOL_ROWS) > 120
    names = {n for _mode, params, _want in SYMBOL_ROWS for v in params.values() if isinstance(v, str) for n in symbols(v)}
    assert names >= {"x", "y", "z", "k"}


def test_the_rename_refuses_what_is_no_bijection_and_leaves_functions_alone():
    with pytest.raises(AssertionError):
        renamed("x + y", {"x": "z", "y": "z"})
    with pytest.raises(AssertionError):
        renamed("x + a", {"x": "a"})
    assert renamed("gcd(x, sin(y)) + pi", {"x": "y", "y": "x"}) == "gcd(y, sin(x)) + pi"
    assert renamed("sin(sin)", {"sin": "cos"}) == "sin(cos)"


@pytest.mark.parametrize("name", RENAMES)
def test_every_row_with_a_symbol_reads_one_verdict_under_each_rename(name):
    moved = [(mode, params, want, got) for mode, params, want in SYMBOL_ROWS
             if (got := read(mode, renamed_params(params, RENAMES[name]))) != want]
    assert moved == []


# What R4 declines, and why: R4_FUNCTIONS holds none of these calls, and R4 does not map these two modes. Those rows take
# the test's own renames above.
R4_DECLINES = re.compile(r"\b(degree|Poly|Tuple|FiniteSet|Subs|summation|product)\(")


def test_every_row_r4_maps_reads_one_verdict_through_r4():
    R = _restate()
    moved, mapped, declined = [], 0, 0
    for mode, params, want in SYMBOL_ROWS:
        subject = [{"id": "b", "domain": "mathematics", "spec": {"mode": mode, "params": copy.deepcopy(params)}}]
        out = R.restate("R4", subject)
        texts = json.dumps(params)
        if mode in ("numeric", "calc_chain") or R4_DECLINES.search(texts):
            assert not out.applied, (mode, params)
            declined += 1
            continue
        assert out.applied, (mode, params, out.reason)
        mapped += 1
        if verify(out.after[0]["spec"])["verdict"] != want:
            moved.append((mode, params, want))
    assert moved == []
    assert mapped >= 40 and declined >= 40


# ── what was found: sympy's own readings, recomputed so the record can quote them ────────────────────────────────────
def test_what_was_found_is_sympys_own_reading():
    x, y, a, k = sympy.symbols("x y a k")
    # a gcd evaluates before the binder sees it: the sum of gcd(k, 12) for k from 1 to 4 is 10, and it read 4
    assert sympy.gcd(k, 12) == 1 and sympy.Sum(sympy.gcd(k, 12), (k, 1, 4)).doit() == 4
    assert sum(math.gcd(i, 12) for i in range(1, 5)) == 10
    assert sympy.gcd(x, x + 2) == 1 and math.gcd(2, 2 + 2) == 2
    # a third number is a generator, and a float answers 1
    twelve, eighteen, four, six, five = map(sympy.Integer, (12, 18, 4, 6, 5))
    assert sympy.gcd(twelve, eighteen, five) == 6 and sympy.lcm(four, six, five) == 12
    assert sympy.gcd(sympy.Float(12.0), sympy.Float(18.0)) == sympy.Float(1.0)
    # sympy's generator table holds x before a, so the unit moves with the names: sign, and scale with it
    assert sympy.Poly(a + x).gens == (x, a)
    assert sympy.gcd(y - x, x - y) == x - y and sympy.gcd(x - y, y - x) == x - y
    assert sympy.gcd(x/2 - y/3, x - 2*y/3) != sympy.gcd(y/2 - x/3, y - 2*x/3).subs({x: y, y: x}, simultaneous=True)
    # Poly and degree read that order, and degree evaluates before a binder
    assert sympy.degree(sympy.Poly(x**2 + y**3)) == 2 and sympy.degree(sympy.Poly(y**2 + x**3)) == 3
    assert sympy.degree(x**2 + 1) == 2 and sympy.degree(5) == 0
    # in a generator's place an integer is an index, and most of the rest a generator it does not find
    assert sympy.degree(x**2 + 1, 0) == 2 and sympy.degree(x**2 + 1, x + 1) == 0 and sympy.degree(x**2 + 1, sympy.pi) == 0


def _paragraph():
    text = (ROOT / "MEASURED.md").read_text(encoding="utf-8")
    start = text.index("- **gcd and lcm, by symbol order.**")
    return re.sub(r"\s+", " ", text[start:text.index("- **Poles, as written.**", start)])


def test_every_reading_the_record_quotes_is_a_row_here():
    para = _paragraph()
    quoted = set(re.findall(r"`([^`]+ = [^`]+)`", para))
    rows = set(NOT_CHECKABLE) | set(HOLDING) | set(FALSE)
    rows |= {f"{r[1]['expr_a']} = {r[1]['expr_b']}" for r in NAMED_MISSES if r[0] == "equality"}
    assert len(quoted) >= 10 and quoted <= rows, quoted - rows


def test_the_record_says_what_the_rule_does_and_names_its_misses():
    para = _paragraph()
    for words in ("before a binder or a substitution sees it", "scale and sign alike", "`UnboundRefused`",
                  "reads INCOMPLETE in every mode", "the fold of sympy's two-argument function",
                  "no benchmark case or tier row reaches gcd or lcm through an expression",
                  "the true ones with the false", "even where nothing later reads their order",
                  "even when nothing substitutes that symbol", "`tests/test_bound_values.py`", "Nine finite sums",
                  "solve and solveset among them", "by an expression sympy discovers in the argument",
                  "which its Sum oracle cannot see", "as a generator's index",
                  "moved under a rename by the pole comparison and not by the function",
                  "and it still does: `Mod` is a call"):
        assert words in para, words
    assert len(SUMS_NOT_REDUCED) == 9
    assert "alphabetical" not in para and "sign-ambiguous" not in para


CHANGELOG_WORDS = ("a value the claim never bound", "gcd(12, 18, 5) = 1 and lcm(4, 6, 5) = 60 read HOLDS where they read BROKEN",
                   "read INCOMPLETE in every mode", "Subs, limit, solve, solveset or a definite integral",
                   "degree(x**2 + 1, x + 1) = 0")


def test_the_changelog_says_which_claims_moved():
    unreleased = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").split("## Unreleased", 1)[1].split("\n## ", 1)[0]
    assert all(w in re.sub(r"\s+", " ", unreleased) for w in CHANGELOG_WORDS)


# ── the allowlist ────────────────────────────────────────────────────────────────────────────────────────────────────
GUARDED = frozenset({"gcd", "lcm", "Poly", "degree"})
UNGUARDED = frozenset({
    "sin", "cos", "tan", "cot", "sec", "csc", "sinc", "asin", "acos", "atan", "acot", "asec", "acsc", "atan2", "sinh", "cosh",
    "tanh", "coth", "sech", "csch", "asinh", "acosh", "atanh", "acoth", "deg", "rad",
    "exp", "log", "ln", "sqrt", "cbrt", "root", "Pow",
    "Abs", "abs", "sign", "floor", "ceiling", "frac", "round",
    "Mod", "igcd", "ilcm", "factorial", "factorial2", "binomial", "totient", "isprime", "factorint", "primerange",
    "nextprime", "prevprime",
    "gamma", "loggamma", "polygamma", "digamma", "beta", "erf", "erfc", "erfi", "zeta", "Ei", "li", "Si", "Ci",
    "Min", "Max", "re", "im", "conjugate", "arg",
    "Rational", "Integer", "Float", "Number", "Symbol", "symbols", "Dummy",
    "Eq", "Ne", "Lt", "Le", "Gt", "Ge", "Equality", "Unequality", "StrictLessThan", "LessThan", "StrictGreaterThan",
    "GreaterThan", "Relational", "And", "Or", "Not", "Xor", "Nand", "Nor", "Implies", "Equivalent", "ITE", "Piecewise",
    "diff", "Derivative", "integrate", "Integral", "limit", "Limit", "Sum", "summation", "Product", "product", "Subs",
    "simplify", "expand", "factor", "cancel", "together", "apart", "collect", "trigsimp", "radsimp", "N", "evalf",
    "solve", "solveset", "roots",
    "Matrix", "ImmutableMatrix", "eye", "zeros", "ones", "diag", "Transpose", "det", "trace", "Determinant", "Trace",
    "Inverse", "transpose",
    "Tuple", "Interval", "FiniteSet", "S",
})


def test_every_allowlisted_name_is_classified_exactly_once():
    assert GUARDED | UNGUARDED == M._ALLOWED_FUNCS, sorted(GUARDED ^ UNGUARDED ^ M._ALLOWED_FUNCS)
    assert not GUARDED & UNGUARDED


# What the sweep found that is neither order-reading nor eager, so a change to any of them fails it until it is read.
# (a) Class C, which stays: two pole bases that differ only as written read as two poles, so the claim the sweep writes
# reads BROKEN when a rename puts y + x where the value prints x + y. Step poles-product lifts such a BROKEN only on proof, and
# Mod is a call off the list that proof reads, so this is its named miss and the set stands as it was.
MOD_MOVES = ("Mod(x**2 - y**2, x + y)", "(x + y)*(Mod((x**2 - y**2)/(x + y), 1))")
MOVED_BY_POLES = frozenset({("x and y exchanged", MOD_MOVES[0]), ("outside the table", MOD_MOVES[0])})
# (b) A false BROKEN on a true claim, and no eager function: Sum(f(k)).doit() equals the three terms, as the test below
# proves. simplify leaves these finite sums unreduced or rewrites them over the bound k, and the pole guard reads the
# bound k of root(2, k) as a pole, so the difference reads as not zero. They read BROKEN at the step's base too.
SUMS_NOT_REDUCED = (
    ("Sum(arg(k), (k, 1, 3))", "(arg(1)) + (arg(2)) + (arg(3))"), ("Sum(frac(k), (k, 1, 3))", "(frac(1)) + (frac(2)) + (frac(3))"),
    ("Sum(im(k), (k, 1, 3))", "(im(1)) + (im(2)) + (im(3))"), ("Sum(ln(k), (k, 1, 3))", "(ln(1)) + (ln(2)) + (ln(3))"),
    ("Sum(ln(k, 2), (k, 1, 3))", "(ln(1, 2)) + (ln(2, 2)) + (ln(3, 2))"), ("Sum(log(k), (k, 1, 3))", "(log(1)) + (log(2)) + (log(3))"),
    ("Sum(log(k, 2), (k, 1, 3))", "(log(1, 2)) + (log(2, 2)) + (log(3, 2))"),
    ("Sum(root(2, k), (k, 1, 3))", "(root(2, 1)) + (root(2, 2)) + (root(2, 3))"),
    ("Sum(sign(k), (k, 1, 3))", "(sign(1)) + (sign(2)) + (sign(3))"),
)


def test_a_pole_written_the_other_way_still_moves_the_sweeps_claim():
    """Class C as the sweep meets it, pinned. The two bases are one pole, and the proof that would say so reads no call, so
    the base's BROKEN stands under these renames: the named miss of step poles-product, which the sweep below also reads."""
    a, b = MOD_MOVES
    assert read("equality", {"expr_a": a, "expr_b": b}) == H
    for name, text in sorted(MOVED_BY_POLES):
        assert text == a
        moved = RENAMES[name]
        assert read("equality", {"expr_a": renamed(a, moved), "expr_b": renamed(b, moved)}) == B


@pytest.mark.parametrize("lhs,rhs", SUMS_NOT_REDUCED)
def test_a_sum_the_sweep_names_is_no_eager_function(lhs, rhs):
    done = M.parse_expression(lhs).doit() - M.parse_expression(rhs)
    assert abs(sympy.N(done)) < 1e-12


# The sweep's fixed table: every symbol asymmetric, a Poly with named generators among them.
ONE_ARGUMENT = ("x", "x + 2*y", "y - x", "x - y", "x**2 + y**3", "x*y + 1", "x/y", "sin(x) + y", "1/(x + 2*y)", "x**2 - y**2",
                "x/2 - y/3", "x**2 + sin(x)**3", "sin(x)**2 + cos(x)**3", "Poly(x**2 + y**3, x, y)", "Poly(y - x, x, y)",
                "Poly(y - x, y, x)", "3")
TWO_ARGUMENTS = (("x", "y"), ("y", "x"), ("y - x", "x - y"), ("x**2 + y**3", "x"), ("x**2 + y**3", "y"), ("x + 2*y", "3"),
                 ("3", "x + 2*y"), ("x**2 - y**2", "x + y"), ("x/2 - y/3", "x - 2*y/3"), ("sin(x) - y", "y - sin(x)"),
                 ("Poly(x**2 + y**3, x, y)", "x"), ("Poly(x**2 + y**3, x, y)", "y"),
                 ("Poly(x**2 + y**3, x, y)", "Poly(y - x, x, y)"))
SHAPES_OF_K = ("{f}({k})", "{f}({k}, 2)", "{f}(2, {k})")
TRIAL_BOUND_S = 20      # past derivation's own 8 s window, so a shed verify is seen as a timeout and not as a kill
NOT_BY_SUM = frozenset({"diff", "Derivative"})      # their second argument is a variable, which that oracle misreads

WORKER = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
from concordance.derivation import verify
from concordance.verifiers import mathematics as M
M._ensure_sympy()


def value(text):
    try:
        v = M.parse_expression(text)
    except M.ExpressionRefused as e:
        return {"refused": str(e)[:80]}
    return {"text": str(v.as_expr() if isinstance(v, M._sp.Poly) else v)}


def verdict(a, b):
    r = verify({"mode": "equality", "params": {"expr_a": a, "expr_b": b}})
    return {"verdict": r["verdict"], "detail": str(r["trail"][0].get("detail"))}


def agrees(lhs, rhs):
    return {"agrees": bool(abs(M._sp.N(M.parse_expression(lhs).doit() - M.parse_expression(rhs))) < 1e-12)}


print("ready", flush=True)
for line in sys.stdin:
    trial = json.loads(line)
    print(json.dumps(globals()[trial.pop("op")](**trial)), flush=True)
"""


class Trials:
    """One child interpreter takes trials a line at a time, so a trial past its bound is killed and reported and the next
    runs in a new child: a verify past its window leaves a thread running, which only ending the process stops."""

    def __init__(self):
        self.child = self.lines = None

    def _start(self):
        self.child = subprocess.Popen([sys.executable, "-c", WORKER, str(ROOT / "src")], stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8")
        self.lines = queue.Queue()
        threading.Thread(target=lambda c=self.child, q=self.lines: [q.put(line) for line in c.stdout],
                         daemon=True).start()
        assert self.lines.get(timeout=120).strip() == "ready"

    def ask(self, **trial):
        """The trial's answer, or None if it did not finish inside the bound."""
        if self.child is None or self.child.poll() is not None:
            self._start()
        self.child.stdin.write(json.dumps(trial) + "\n")
        self.child.stdin.flush()
        try:
            answer = json.loads(self.lines.get(timeout=TRIAL_BOUND_S))
        except queue.Empty:
            self.stop()
            return None
        if "timed out" in answer.get("detail", ""):
            self.stop()
            return None
        return answer

    def stop(self):
        if self.child is not None:
            self.child.kill()
            self.child.wait()
        self.child = None


def sweep_renames(trials, names):
    """Each name over the fixed table: called, renamed, and the verdict of its value compared. A value that is a Poly is
    compared through as_expr()."""
    counts, moved, unfinished = Counter(), [], []
    shapes = [f"{{f}}({a})" for a in ONE_ARGUMENT] + [f"{{f}}({a}, {b})" for a, b in TWO_ARGUMENTS]
    for name in names:
        for shape in shapes:
            text = shape.format(f=name)
            counts["rename trials"] += 1
            own = trials.ask(op="value", text=text)
            if own is None:
                unfinished.append(text)
            elif "refused" in own:
                counts["refused as called"] += 1
                for key, mapping in RENAMES.items():
                    other = trials.ask(op="value", text=renamed(text, mapping))
                    if other is None:
                        unfinished.append(renamed(text, mapping))
                    elif "refused" not in other:
                        moved.append((key, text))
            else:
                base = trials.ask(op="verdict", a=text, b=own["text"])
                if base is None:
                    unfinished.append(text)
                    continue
                counts[f"called {base['verdict']}"] += 1
                for key, mapping in RENAMES.items():
                    other = trials.ask(op="verdict", a=renamed(text, mapping), b=renamed(own["text"], mapping))
                    if other is None:
                        unfinished.append(renamed(text, mapping))
                    elif other["verdict"] != base["verdict"]:
                        moved.append((key, text))
                    else:
                        counts["renames compared"] += 1
    return counts, moved, unfinished


def sweep_sums(trials, names):
    """For a name that takes an integer as a value: Sum(f(k), (k, 1, 3)) against f(1) + f(2) + f(3)."""
    counts, broken, eager, unfinished = Counter(), [], [], []
    for name in sorted(set(names) - NOT_BY_SUM):
        for shape in SHAPES_OF_K:
            terms = [shape.format(f=name, k=i) for i in (1, 2, 3)]
            counts["sum trials"] += 1
            read_terms = [trials.ask(op="value", text=t) for t in terms]
            if None in read_terms:
                unfinished.append(terms[0])
            elif any("refused" in t for t in read_terms):
                counts["takes no integer"] += 1
            else:
                lhs, rhs = f"Sum({shape.format(f=name, k='k')}, (k, 1, 3))", " + ".join(f"({t})" for t in terms)
                got = trials.ask(op="verdict", a=lhs, b=rhs)
                if got is None:
                    unfinished.append(lhs)
                    continue
                counts[f"sum {got['verdict']}"] += 1
                if got["verdict"] == B:
                    held = trials.ask(op="agrees", lhs=lhs, rhs=rhs)
                    (broken if held and held["agrees"] else eager).append((lhs, rhs))
    return counts, broken, eager, unfinished


@pytest.mark.slow
def test_no_unguarded_name_reads_an_order_or_evaluates_before_a_binder():
    """The sweep the plan asks for, its counts printed. Anything new here is in the run's scope or stops it for a replan."""
    names = sorted(n for n in UNGUARDED if n in M._FUNCTIONS)
    trials = Trials()
    try:
        by_rename, moved, unfinished = sweep_renames(trials, names)
        by_sum, broken, eager, more = sweep_sums(trials, names)
    finally:
        trials.stop()
    print("\nsweep:", json.dumps({"names": len(names), "unbound on the list": len(UNGUARDED) - len(names), **by_rename,
                                  **by_sum, "moved": len(moved), "sums not reduced": len(broken), "eager": len(eager),
                                  "unfinished": len(unfinished + more)}, sort_keys=True))
    assert unfinished + more == []
    assert eager == []
    assert set(moved) == set(MOVED_BY_POLES)
    assert sorted(broken) == sorted(SUMS_NOT_REDUCED)
