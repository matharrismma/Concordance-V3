"""A BROKEN is lifted only on proof that the two sides' denominators vanish together (run 2026-11-04-gcd-lcm-order, step
poles-product).

mathematics._domain_mismatch compares pole bases as written, so one denominator written two ways reads as two poles and a
true identity reads BROKEN: 1/(y + x) = 1/(x + y) does. That guard stays as it was. One helper, _same_zeros, is asked only
after the difference has read zero and the guard has named a difference, and it can only lift: anything it cannot prove
keeps the guard's BROKEN, so its worst case is what the step's base did. There is no new refusal and no third answer. It
runs only on a rational function with rational coefficients written out on each whole side, read twice, by the text's
syntax tree and by the unevaluated value. What is left once matching factors have left the compare is multiplied out in
sympy's sparse ring, and the two products must be one polynomial up to a nonzero rational: a check, never a search, so it
factors nothing. Two paths confirmed without reading the guard at all, so 0.1*x/x + 0.2 = 0.3 read HOLDS beside x/x = 1
reading BROKEN: now every confirm reads this answer.

Three attempts at this step failed review. Every input of those reviews and of the plan's is a row here (ledger lines 36, 39,
42, 45, 47, 49, 56 and 59), with the reading the plan states at line 60. A row that reads otherwise fails the step and changes
only by replan. Cost is pinned by counts, never by timing. Names the fix adds are read inside the tests, so the file collects
at the step's base.
"""
from __future__ import annotations

import ast
import inspect
import re
import textwrap
import threading
from pathlib import Path

import pytest
import sympy
from sympy.polys import polyclasses, polytools

from concordance.derivation import verify
from concordance.verifiers import mathematics as M
from test_bound_values import _restate, equality, read, renamed, symbols

pytestmark = pytest.mark.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
I, H, B = "INCOMPLETE", "HOLDS", "BROKEN"


@pytest.fixture(autouse=True)
def _tables():
    M._ensure_sympy()


# ── the rows ─────────────────────────────────────────────────────────────────────────────────────────────────────────
# Three exact zeros no read of the text can see by its syntax alone.
T1 = "(sin(1)**2 + cos(1)**2 - 1)"
T2 = "((1 + sqrt(2))**2 - 3 - 2*sqrt(2))"
T3 = "((pi + 1)**2 - pi**2 - 2*pi - 1)"
SPLIT_POWER = "(1 + Abs(x) + Abs(y) + Abs(z) + Abs(w) + Abs(v))**({} + {})"


def split_power(n, t="t"):
    """t/t on one side alone, beside the power line 39 found no term count sees."""
    power = SPLIT_POWER.format(n, t)
    return f"{t}/{t} + 1/{power} = 1 + 1/{power}"


def linear_forms(i):
    return "*".join(f"(x + {k}*y + {k*k + i}*z)" for k in range(1, 21))


def product(i):
    """The plan's P(i), written out as that product in the text."""
    return f"({linear_forms(i)})"


def expanded(i):
    """P(i) as the reviews at lines 36 and 42 wrote it, which only a call can write."""
    return f"expand({linear_forms(i)})"


def beside(p, count):
    return "".join(f" + 1/{p(i)}" for i in range(1, count + 1))


# Line 56's product of 60 terms: degree 20 in 12 symbols, and 17 s in factor_list, inside every limit that step held.
F = ("(2*a**2*b*c*e*h**2*j**2*k - a*b*d*e*g*h*i**2*k*l - 2*b*g*j*k**2)*"
     "(a**2*b*h**2*i*k**2*l**2 - a*b*c*e*h**2*j*k**2*l + 2*h**4 - 2*a*b**2*e**4*f**2*i - a*b*d*f*h*j*l + l - a + b**2*c*g*k*l + a*b**2*c**2*f*i*k - g*i*j + 2*a*c**2*d*f*g*i*j*l**2 - a*g**2*h*i**2 + c**3*e*f*k**2*l**2 + a - b + 2*a**2*b*d**2*e*g*i*j*l - a**2*b**2*c**2*h*k**2*l + d**2*e**2*h*k*l - 2*e + j**2 - 2*a*d + a**2*c*f*g*k) + 0")
# Line 59's two sides: 384 terms each when multiplied out, and 4.8 s as a dense Poly, inside every limit here.
A_SIDE = "0/((y**63*a + y**63)*(y**63*b + y**63)*(y**63*c + y**63)*(y**63*d + y**63)*(y**63*" \
         "e + y**63)*(y**63*f + y**63)*(y**63*g + y**63)*(y**63*h + y**63 + y**63*z)) + 1"
B_SIDE = re.sub(r"(\(y\*\*63\*[a-h]) \+ y\*\*63", r"\1 - y**63", A_SIDE)
OVER_ONE = f"0/({F}) + 1 = 1/(a + 1 - a)"
OVER_THE_PRODUCTS = f"{A_SIDE} = {B_SIDE}"

# The plan's HOLDS, each BROKEN at the step's base.
PROVED = (
    "1/(y + x) = 1/(x + y)", "1/(x*y) = 1/(y*x)", "1/(x - y) = -1/(y - x)", "1/(2*x) = (1/2)/x",
    "1/(2*x - 2*y) = 1/(2*(x - y))", "1/(x*y) = (1/x)*(1/y)", "1/(x**2 - y**2) = 1/((x - y)*(x + y))",
    "1/(x + 1 - 1) = 1/x", "1/(x**60 - y**60) = -1/(y**60 - x**60)",
    "1/((x + y + z + w)**30*(a + b + c + d)**30) = 1/((a + b + c + d)**30*(x + y + z + w)**30)",
    f"1/(x**2 - y**2){beside(product, 3)} = 1/((x - y)*(x + y)){beside(product, 3)}",
    "1/(x**60 - y**60) = 1/((x**30 - y**30)*(x**30 + y**30))",
)
A_NAMED_MISS = "1/simplify(y + x) = 1/(y + x)"          # true, and its written order still moves it with the names
MULTIPLICITY = "1/(x**2 - 2*x*y + y**2) = 1/(x - y)**2"     # true, and a named miss: the power's multiplicity is dropped
# The plan's BROKEN as the base reads it, each inside its window.
KEPT = (
    f"1/{T1} - 1/{T1} + 1/(x + 1 - 1) = 1/x", f"simplify(1/{T1} - 1/{T1}) + 1/(x + 1 - 1) = 1/x", A_NAMED_MISS,
    "x/x = 1", "(x**2 - 1)/(x - 1) = x + 1", "x/(x*y) = 1/y", "1/(1/x + 1) = x/(x + 1)", "1/(x**60 - y**60) = 1/x",
    "x**61/x**61 = 1", MULTIPLICITY, OVER_ONE, "1/(x + 0.1 + 1e-20) = 1/(x + 0.1)", "1/(x + 1.0 + 1e-30) = 1/(x + 1.0)",
    f"(1/{T3} - 1/{T3}) % 3 + 1/(y + x) = 1/(x + y)", "((x - 1)/(x - 1)) mod 3 + 1/(y + x) = 1 + 1/(x + y)",
    "(x/x) % 3 + 1/(y + x) = 1 + 1/(x + y)",
    f"1/({T1}*x) - 1/({T1}*x) + 1/x = 1/x", f"x/({T1}*x) - x/({T1}*x) + 1/x = 1/x",
    f"1/({T2}*x) - 1/({T2}*x) + 1/x = 1/x", f"x/({T2}*x) - x/({T2}*x) + 1/x = 1/x",
    "x**y/x**y = x/x", "(x - 1)**y/(x - 1)**y = (x - 1)/(x - 1)", "x**(y + 1)/x**(y + 1) = x/x",
    "x**(Abs(y) - y)/x**(Abs(y) - y) = x/x", "1/(x**60 - y**60)**a + 1/z = 1/(x**60 - y**60)**a",
    f"t/t{beside(product, 1)} = 1{beside(product, 1)}", f"t/t{beside(product, 2)} = 1{beside(product, 2)}",
    f"t/t{beside(product, 3)} = 1{beside(product, 3)}",
    split_power(60),
)
# Each input of the reviews that the rows above do not already hold, by the ledger line that found it.
REVIEWED = {
    36: (("1/(x**120 - y**120)**a + 1/z0 = 1/(x**120 - y**120)**a", B),
         ("1/(y*sqrt(x**60 - y**60) + 0) + 1/z = 1/(y*sqrt(x**60 - y**60) + 0)", B)),
    39: ((split_power(12), B), (split_power(30), B), (split_power(60, "t0"), B), (split_power(60, "t1"), B),
         (split_power(60, "t2"), B), ("1 + 1 = 2", H)),
    42: ((f"t/t{beside(expanded, 1)} = 1{beside(expanded, 1)}", B), (f"t/t{beside(expanded, 2)} = 1{beside(expanded, 2)}", B),
         (f"t/t{beside(expanded, 3)} = 1{beside(expanded, 3)}", B),
         (f"1/(x**2 - y**2){beside(expanded, 3)} = 1/((x - y)*(x + y)){beside(expanded, 3)}", B),
         # These two read HOLDS at the base: no difference is named, so nothing is asked, and they are the base's own.
         (f"1/{T1} - 1/{T1} + 1/x = 1/x", H), ("x + 1.0 + 1e-30 = x + 1.0", H)),
    45: ((f"1/{T2} - 1/{T2} + 1/(y + x) = 1/(x + y)", B), ("(x - 1)**(-y) - (x - 1)**(-y) + 1/(y + x) = 1/(x + y)", B),
         ("Sum(1/(x + 1 - 1), (x, 1, 2)) = Sum(1/x, (x, 1, 2)) + 1/x - 1/x", B),
         ("Integral(1/(x + 1 - 1), (x, 1, 2)) = Integral(1/x, (x, 1, 2)) + 1/x - 1/x", B),
         ("Subs(1/(x + 1 - 1), x, 2) = Subs(1/x, x, 2) + 1/x - 1/x", B),
         ("log(x - 1) - log(x - 1) + 1/(y + x) = 1/(x + y)", B), ("tan(x) - tan(x) + 1/(y + x) = 1/(x + y)", B),
         ("gamma(x) - gamma(x) + 1/(y + x) = 1/(x + y)", B)),
    47: ((f"expand(1/{T2} - 1/{T2}) + 1/(y + x) = 1/(x + y)", B),
         ("simplify(1/(0.1 + 0.2 - 0.3) - 1/(0.1 + 0.2 - 0.3)) + 1/(y + x) = 1/(x + y)", B),
         ("cancel(x/x) + 1/(y + x) = 1 + 1/(x + y)", B), ("simplify(tan(x) - tan(x)) + 1/(y + x) = 1/(x + y)", B)),
    49: (("(x/x) % 3 = 1", H),),
    59: ((OVER_THE_PRODUCTS, B),),
}
# Line 36's third input: a non-zero difference, 3.4 s of simplify at the base. Read once here, and under each rename only in
# the slow job, as every row is that runs an expand of twenty linear forms.
SLOW_ROW = (f"{beside(expanded, 3)[3:]} + 1/w = {beside(expanded, 3)[3:]}", B)
# The three the plan moves: each read HOLDS at the base by arithmetic or by a window, a removable singularity all the same.
MOVED = ("0.1*x/x + 0.2 = 0.3",)
INSIDE_THE_WINDOW = f"0/({F}) + 311/100 = 1/(a + 1 - a)*31/10"
SAME_POLES_IN_THE_WINDOW = "(x**2 - y**2)/(x**2 - y**2)*311/100 = (x - y)/(x - y)*(x + y)/(x + y)*31/10"
STATED_ROWS = (("x/x*3.14159 = 3.14", "3.14", B), ("3.14159 = 3.14*y/y", "3.14", B), ("x/x*3.14159 = x/x*3.14", "3.14", H),
               ("(x**60 - y**60)/(x**60 - y**60)*3.14159 = (y**30 - x**30)/(y**30 - x**30)*3.14", "3.14", B),
               ("x/x*3.14159 = 2.71", "2.71", B), (INSIDE_THE_WINDOW, "3.1", B), (SAME_POLES_IN_THE_WINDOW, "3.1", H))

# Beyond the plan, every one BROKEN at the base. A unary sign reads as Python negates, and sympy adds a negated sum's terms
# back up, so -(1/x - 1/x) reads 0 in the unevaluated read and its pole is gone with no call in the text. The list takes a
# sign on a name or an integer alone. checker-46's other shapes stand beside them.
A_SIGN_ON_A_SUM = ("-(1/x - 1/x) + 1/(y + x) = 1/(x + y)", "-((x - 1)/(x - 1) - (x - 1)/(x - 1)) + 1/(y + x) = 1/(x + y)",
                   "1/(-(1/x - 1/x) + y) = 1/y + 1/z - 1/z", "-(x/x) + 1/(y + x) = -1 + 1/(x + y)")
HIDDEN_POLES = (
    "1/x**0 = 1", "1/x**0 + 1/(y + x) = 1 + 1/(x + y)",
    "1/((x*(y + 1) - x*y - x)*z) - 1/((x*(y + 1) - x*y - x)*z) + 1/(z + 1 - 1) = 1/z",
    "1/(x*(y + 1) - x*y - x) - 1/(x*(y + 1) - x*y - x) + 1/(y + x) = 1/(x + y)",
    "((x + 1)**2 - x**2 - 2*x - 1)**-3 - ((x + 1)**2 - x**2 - 2*x - 1)**-3 + 1/(y + x) = 1/(x + y)",
    "1/(x + 2) - 1/(x + 2) + 1/x = 1/x + 1/(x + 3) - 1/(x + 3)", "1/(x**2 + 1) - 1/(x**2 + 1) + 1/x = 1/x + 1/(x**2 + 2) - 1/(x**2 + 2)",
    "sqrt(x)/sqrt(x) + 1/(y + x) = 1 + 1/(x + y)", "Abs(x)/Abs(x) + 1/(y + x) = 1 + 1/(x + y)",
    "Max(x, y)/Max(x, y) + 1/(y + x) = 1 + 1/(x + y)", "x**2.0/x**2.0 + 1/(y + x) = 1 + 1/(x + y)",
    "simplify((x - 1)/(x - 1)) + 1/(y + x) = 1 + 1/(x + y)", f"simplify(1/{T1} - 1/{T1}) + 1/(y + x) = 1/(x + y)",
    "summation(1/(x + 1 - 1), (x, 1, 2)) + 1/(y + x) = 3/2 + 1/(x + y)", f"1/{T3} - 1/{T3} + 1/(y + x) = 1/(x + y)",
    "1/(pi - 3) - 1/(pi - 3) + 1/(y + x) = 1/(x + y)", "1/(E - E + 1) + 1/(y + x) = 1 + 1/(x + y)",
    "1/(I**2 + 2) - 1/(I**2 + 2) + 1/(y + x) = 1/(x + y)", "1/GoldenRatio - 1/GoldenRatio + 1/(y + x) = 1/(x + y)",
    "x/x + 1/(y + x) = 1 + 1/(x + y)", "x*(1/x) + 1/(y + x) = 1 + 1/(x + y)", "0*(1/(x - 1)) + 1/(y + x) = 1/(x + y)",
    "1/(1/x) = x", "1/(x**2/x) = 1/x",
    "(x + y)/(x + y) = 1", "(y + x)/(x + y) = 1", "(x - y)/(y - x) = -1", "x*y/(x*y) = 1", "2*x/x = 2",
    "(x - 1)/(x**2 - 1) = 1/(x + 1)", "(x**2 - y**2)/(x + y) = x - y", "x*(1/x)*(1/y) = 1/y",
)
# What each limit is for: every one of these is short and BROKEN at the base at once. Past a limit it does not matter which are
# true: the proof ends and the base's reading stands. A term count sees none of them: WIDE takes 19.9 s to build as a Poly
# without the weight, and the eight binomials do not multiply out in 25 s.
def balanced(parts):
    """A sum written as a tree, since a long chain of + is past the parser's depth limit."""
    while len(parts) > 1:
        parts = ["(" + " + ".join(parts[i:i + 2]) + ")" for i in range(0, len(parts), 2)]
    return parts[0]


MANY_SYMBOLS_DEEP = balanced([f"a{i}**9999*b{i}**9998*c{i}**9997" for i in range(30)])
MANY_SYMBOLS = balanced([f"a{i}**9999" for i in range(120)])
WIDE = " + ".join("*".join(f"{c}**{9000 - 7*k - i}" for i, c in enumerate("abcdefghijkl")) for k in range(12))
BINOMIALS = "*".join(f"((2**10000)**50*x + {k}*y)" for k in range(1, 9))
PAST_A_LIMIT = ("1/(x**2 - 2**5000*y**2) = 1/((x - 2**2500*y)*(x + 2**2500*y))",
                "1/(x**2 - (2**10000)**2*y**2) = 1/((x - 2**10000*y)*(x + 2**10000*y))",
                f"1/{MANY_SYMBOLS_DEEP} = 1/({MANY_SYMBOLS_DEEP} + 0)", f"1/{MANY_SYMBOLS} = 1/({MANY_SYMBOLS} + 0)",
                f"1/({WIDE}) = 1/(0 + {WIDE})", f"1/({BINOMIALS}) = 1/({BINOMIALS.replace('*x + ', '*x + 0 + ')})")
# And these are true with the same poles on both sides, each BROKEN at the base. Each lifts.
THE_SAME_ZEROS = ("1/(x - 1) + 1/(x + 1) = 2*x/(x**2 - 1)", "1/(x/2 - y/3) = 6/(3*x - 2*y)", "1/(y*(x - 1)) = 1/(y*x - y)",
                  "1/((x - 1)*(x + 1)) = 1/(x**2 - 1)", "1/(x + y - y) = 1/x", "1/(y + x)**2 = 1/(x + y)**2",
                  "1/(x**2*y) = 1/(y*x*x)", "1/(x - (y - z)) = 1/(x - y + z)", "x**-1/(y + x) = 1/(x*(x + y))",
                  "1/(x**5 - y**5) + 1/(x**5 + y**5) = 2*x**5/(x**10 - y**10)", "1/((x/2 - 1/2)*(x + 1)) = 2/(x**2 - 1)",
                  "1/((x - 1)*(x + 1)) = 3/(3*x**2 - 3)", "1/(x**20 - y**20) = 1/((x**10 - y**10)*(x**10 + y**10))")

ROWS = (tuple((c, H) for c in PROVED + THE_SAME_ZEROS)
        + tuple((c, B) for c in KEPT + MOVED + A_SIGN_ON_A_SUM + HIDDEN_POLES + PAST_A_LIMIT)
        + tuple(row for rows in REVIEWED.values() for row in rows))


def params(claim):
    return equality(claim)[1]


def stated(claim, literal):
    return {**params(claim), "claimed_literal": literal}


def verdict_of(claim):
    return read(*equality(claim))


@pytest.mark.parametrize("claim,want", ROWS)
def test_each_expected_reading(claim, want):
    assert verdict_of(claim) == want


@pytest.mark.parametrize("claim,literal,want", STATED_ROWS)
def test_each_stated_precision_row(claim, literal, want):
    assert read("equality", stated(claim, literal)) == want


def test_the_input_that_costs_a_simplify_at_the_base_reads_as_it_did(factored, monkeypatch):
    monkeypatch.setattr(M, "_same_zeros", lambda *_args: pytest.fail("a non-zero difference uses no answer of it"))
    assert verdict_of(SLOW_ROW[0]) == SLOW_ROW[1]
    assert factored == []


@pytest.mark.parametrize("claim,want", [
    ("1/(2 - 2) - 1/(2 - 2) + 1/(y + x) = 1/(x + y)", I), ("1/(x + 1/(2 - 2)) + 1/(y + x) = 1/(x + y)", I),
    ("(1 - 1)**-1 - (1 - 1)**-1 + 1/(y + x) = 1/(x + y)", I), ("0**-1 - 0**-1 + 1/(y + x) = 1/(x + y)", I),
    ("1/(0*x) - 1/(0*x) + 1/(y + x) = 1/(x + y)", I), ("oo - oo + 1/(y + x) = 1/(x + y)", I),
    ("x/(x - x + 1) - x/(x - x + 1) + 1/(z - 1) + 1/(y + x) = 1/(x + y)", B), ("1/(1/x - 1/x + y) = 1/y", B),
])
def test_an_exact_zero_reads_as_the_base_read_it(claim, want):
    """A zero an integer read can see is refused where it was built, as it was, and is never the proof's to answer."""
    assert verdict_of(claim) == want


def test_no_row_of_the_table_is_a_new_refusal():
    """The compare has two answers. What it cannot prove keeps the BROKEN, so nothing here reads INCOMPLETE."""
    assert {want for _claim, want in ROWS} == {H, B} and {want for _c, _l, want in STATED_ROWS} == {H, B}


def costly(row):
    return "expand((x" in row[0]


def reversed_row(claim):
    a, b = claim.split(" = ")
    return f"{b} = {a}"


@pytest.mark.parametrize("claim,want", [row for row in ROWS if not costly(row)])
def test_a_row_read_the_other_way_round_reads_the_same(claim, want):
    assert verdict_of(reversed_row(claim)) == want


@pytest.mark.parametrize("claim,want", [("0.1 + 0.2 = 0.3", H), ("1/3 + 1/3 + 1/3 = 1", H)])
def test_plain_numbers_hold_by_exact_arithmetic_as_they_did(claim, want):
    assert verdict_of(claim) == want


def test_plain_numbers_hold_at_their_stated_precision_as_they_did():
    assert read("equality", stated("3.14159 = 3.14", "3.14")) == H
    assert read("equality", stated("3.14159 = 2.71", "2.71")) == B


# ── the guard stands, and the helper is asked once, and only there ───────────────────────────────────────────────────
def test_the_guard_still_names_what_it_named(monkeypatch):
    """_domain_mismatch is the base's: it answers nothing of the helper's, so a difference it names is named here too."""
    monkeypatch.setattr(M, "_same_zeros", lambda *_args: pytest.fail("the guard asks no proof"))
    assert M._domain_mismatch("1/(y + x)", "1/(x + y)", []) == "x + y, x + y"
    assert M._domain_mismatch("1/(x - y)", "-1/(y - x)", []) == "-x + y, x - y"
    assert M._domain_mismatch("x/x", "1", []) == "x"
    assert M._domain_mismatch("1/(x + y)", "2/(x + y)", []) is None


def test_every_confirm_in_verify_equality_reads_the_pole_answer_first():
    """Each confirm is the right side of `_pole_answer(...) or confirm(...)`, so a new path cannot skip the guard unseen."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(M.verify_equality)))
    confirms = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "confirm"]
    guarded = [n.values[1] for n in ast.walk(tree) if isinstance(n, ast.BoolOp) and isinstance(n.op, ast.Or)
               and getattr(getattr(n.values[0], "func", None), "id", "") == "_pole_answer"]
    assert len(confirms) == 4 and all(any(c is g for g in guarded) for c in confirms)


CONFIRM_PATHS = {
    "the difference": {"expr_a": "x/x", "expr_b": "1"},
    "the exact decimals": {"expr_a": "0.1*x/x + 0.2", "expr_b": "0.3"},
    "the stated precision": {"expr_a": "x/x*3.14159", "expr_b": "3.14", "claimed_literal": "3.14"},
}


@pytest.mark.parametrize("path", CONFIRM_PATHS)
def test_a_pole_on_one_side_is_a_mismatch_on_each_path_with_the_singular_set_named(path):
    r = M.verify_equality(CONFIRM_PATHS[path])
    assert r.status == "MISMATCH" and "holds only off the singular set (denominator vanishes at: x)" in r.detail


def _unreduced(monkeypatch):
    """A simplify that leaves every difference standing, so a claim reaches the second zero test, which is expand's."""
    real = M.simplify
    monkeypatch.setattr(M, "simplify", lambda value: sympy.Symbol("unreduced") if value == 0 else real(value))


def test_a_pole_on_one_side_is_a_mismatch_on_the_expand_path_too(monkeypatch):
    _unreduced(monkeypatch)
    r = M.verify_equality({"expr_a": "x/x", "expr_b": "1"})
    assert r.status == "MISMATCH"
    assert r.detail == "x/x == 1 holds only off the singular set (denominator vanishes at: x); not an unconditional identity"


def test_the_proof_lifts_on_the_expand_path_too(monkeypatch):
    _unreduced(monkeypatch)
    assert M.verify_equality(params("1/(y + x) = 1/(x + y)")).status == "CONFIRMED"


@pytest.mark.parametrize("claim,literal", [("x/x*0.1 + 0.2 = x/x*0.3", None), ("x/x*3.14159 = x/x*3.14", "3.14")])
def test_a_decimal_read_with_no_difference_named_never_asks(claim, literal, monkeypatch):
    monkeypatch.setattr(M, "_same_zeros", lambda *_args: pytest.fail("no difference was named"))
    spec = stated(claim, literal) if literal else params(claim)
    assert M.verify_equality(spec).status == "CONFIRMED"


def test_a_failed_window_keeps_its_own_mismatch():
    r = M.verify_equality({"expr_a": "x/x*3.14159", "expr_b": "2.71", "claimed_literal": "2.71"})
    assert r.status == "MISMATCH" and "simplifies to" in r.detail


def test_the_helper_is_asked_once_on_a_claim_it_cannot_prove(monkeypatch):
    real, asked = M._same_zeros, []
    monkeypatch.setattr(M, "_same_zeros", lambda *args: asked.append(args) or real(*args))
    assert M.verify_equality(params("x/x = 1")).status == "MISMATCH"
    assert len(asked) == 1


@pytest.mark.parametrize("claim", ["1/(x**60 - y**60) = 1/x", "1/(y + x) = 2/(x + y)", "x/x + 1/z = 1"])
def test_a_non_zero_difference_never_asks_and_makes_no_factor_list_call(claim, factored, monkeypatch):
    monkeypatch.setattr(M, "_same_zeros", lambda *_args: pytest.fail("a non-zero difference uses no answer of it"))
    r = M.verify_equality(params(claim))
    assert r.status == "MISMATCH" and "simplifies to" in r.detail
    assert factored == []


@pytest.mark.parametrize("a,b", [("x/x + (2**1000)**1047", "2"), ("x/x + Pow(2**1000,1047)", "2")])
def test_a_refused_read_answers_before_anything_is_asked(a, b, monkeypatch):
    monkeypatch.setattr(M, "_same_zeros", lambda *_args: pytest.fail("the refusal comes first"))
    r = M.verify_equality({"expr_a": a, "expr_b": b})
    assert r.status == "NOT_APPLICABLE" and r.detail.startswith(M._REFUSAL)


# ── what the proof requires ──────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("a,b", [claim.split(" = ") for claim in PROVED + THE_SAME_ZEROS])
def test_the_proof_answers_directly(a, b):
    assert M._same_zeros(a, b, []) is True


@pytest.mark.parametrize("text", ["x", "1", "-1", "-x", "+x", "x + y", "x - y", "x*y", "x/y", "x**2", "x**-2", "x**+2", "2**-3", "1/(x + 1)",
                                  "(x + y)**3/(x - 1)**-2", "-1/(y - x)", "-x/y", "-2*x"])
def test_the_list_reads_a_name_an_integer_a_sign_and_the_five_operators(text):
    assert M._written_out(ast.parse(text, mode="eval").body)


@pytest.mark.parametrize("text", [
    "sin(x)", "simplify(x)", "Abs(x)", "x % 3", "x // 2", "x @ y", "x & y", "x < y", "(x, y)", "[x]", "0.5", "1e3", "1j", "x**y", "x**(1/2)", "x**(y + 1)",
    "x**2.0", "x**(1 + 1)", "x**(-y)", "x**--2", "not x", "~x", "x if y else z", "True", "'x'",
    "-(x + y)", "-(1/x - 1/x)", "-(x/x)", "+(x + y)", "--x", "-x**2", "-sin(x)", "(-(1/x - 1/x))**2", "1/(-(y + x))",
])
def test_the_list_reads_nothing_else(text):
    assert not M._written_out(ast.parse(text, mode="eval").body)


@pytest.mark.parametrize("text", ["x", "x + 1", "x*y", "1/x", "x**-2", "(x + y)**2/z", "1/2", "-3", "(1/2)*x"])
def test_the_value_read_takes_what_the_list_takes(text):
    assert M._rational_value(M._parse(text, evaluate=False))


@pytest.mark.parametrize("text", ["pi", "E", "I", "oo", "true", "pi*x", "E + 1", "x + I", "1/(pi - 3)", "EulerGamma", "GoldenRatio", "Catalan",
                                  "TribonacciConstant", "x**2.5", "0.5*x", "x**y", "sqrt(x)", "sin(x)", "Sum(x, (x, 1, 2))", "Abs(x)", "x**pi"])
def test_the_value_read_takes_nothing_else(text):
    assert not M._rational_value(M._parse(text, evaluate=False))


@pytest.mark.parametrize("claim", ["1/(pi*x + pi*y) = 1/(pi*(x + y))", "1/(y + x + E) = 1/(x + y + E)", "1/(y + x + I) = 1/(x + y + I)"])
def test_what_the_list_alone_would_lift_the_value_read_ends(claim, monkeypatch):
    """Each is a name and operators, so the syntax tree passes it: only the value read knows pi, E and I are no symbols."""
    a, b = claim.split(" = ")
    assert all(M._written_out(ast.parse(text, mode="eval").body) for text in (a, b))
    assert not M._same_zeros(a, b, [])
    assert verdict_of(claim) == B


@pytest.mark.parametrize("a,b", [("1/(y + x) + (x/x) % 3", "1 + 1/(x + y)"), ("1/(y + x) + (x/x) mod 3", "1 + 1/(x + y)"),
                                 ("1/(y + x) + 1/sin(1)", "1/(x + y) + 1/sin(1)")])
def test_a_side_off_the_list_ends_the_attempt_before_any_read(a, b, monkeypatch):
    monkeypatch.setattr(M, "_pole_bases", lambda _value: pytest.fail("nothing is read past the list"))
    assert M._same_zeros(a, b, []) is False


def test_a_side_that_passes_the_list_and_not_the_value_read_builds_no_poly(polys):
    assert M._same_zeros("1/(pi*x + pi*y)", "1/(pi*(x + y))", []) is False
    assert polys == []


@pytest.mark.parametrize("text,want", [("x*y", {"x", "y"}), ("2*x", {"2", "x"}), ("x**2", {"x"}), ("(x*y)**3", {"x", "y"}), ("x**0", {"x**0"}),
                                       ("x**-1", {"1/x"}), ("(x + y)*(x - y)", {"x + y", "x - y"}), ("(x + y)**30*(z + 1)", {"x + y", "z + 1"}),
                                       ("x + y", {"x + y"}), ("3*(x + 1)**2*y", {"3", "x + 1", "y"})])
def test_a_base_splits_into_its_written_factors_with_nothing_expanded(text, want, expands):
    assert {str(f) for f in M._written_factors(M._parse(text, evaluate=False))} == want
    assert expands == []


@pytest.mark.parametrize("texts", [("2*x - 2*y", "y - x", "x/2 - y/2", "x - y"), ("-3*x", "x", "x/7"), ("x/2 - y/3", "3*x - 2*y", "2*y - 3*x")])
def test_factors_that_differ_by_a_unit_are_one(texts):
    gens = sympy.symbols("x y")
    assert len({M._unit_free(sympy.Poly(M._parse(t, evaluate=False), *gens, domain="QQ")) for t in texts}) == 1


# A number among a base's factors must be a nonzero Rational, and a factor that is zero as a polynomial ends the attempt, since
# a denominator that is zero everywhere has no zeros to compare.
@pytest.mark.parametrize("a,b", [("1/((x + 1)**2 - x**2 - 2*x - 1) + 1/(y + x)", "1/((x + 1)**2 - x**2 - 2*x - 1) + 1/(x + y)"),
                                 ("1/((x*y - y*x + (x - 1)**2 - x**2 + 2*x - 1)*z)", "1/z"), ("1/(x*(1/2))", "2/x"), ("1/((1/2)*x)", "2/x")])
def test_a_zero_or_a_number_no_rational_ends_the_attempt(a, b):
    assert M._same_zeros(a, b, []) is False


def test_a_constant_with_a_symbol_in_it_has_no_zero_and_is_left_on_one_side():
    """x + 1 - x is no pole, and the plan's order ends the attempt: a miss, and the base's reading."""
    assert M._same_zeros("1/(x + 1 - x) + 1/y", "1 + 1/y", []) is False
    assert verdict_of("1/(x + 1 - x) + 1/y = 1 + 1/y") == B


def test_a_failure_anywhere_keeps_the_guards_reading(monkeypatch):
    """Anything the proof does not reach is no proof. So a sympy that fails keeps the BROKEN, and raises nothing."""
    def fails(*_args, **_kwargs):
        raise sympy.PolynomialError("no")
    monkeypatch.setattr(M._sp, "ring", fails)
    claim = "1/(x**2 - y**2) = 1/((x - y)*(x + y))"
    assert M._same_zeros(*claim.split(" = "), []) is False
    assert M.verify_equality(params(claim)).status == "MISMATCH"


# ── rename invariance ────────────────────────────────────────────────────────────────────────────────────────────────
# Each is a bijection on every row's names, which renamed() checks for itself. sympy's generator table holds x before a,
# so the third turns the pair round; zz is outside the table, so the fourth orders it by another rule.
RENAMES = {
    "x and y exchanged": {"x": "y", "y": "x"},
    "a three-way cycle": {"x": "y", "y": "z", "z": "x"},
    "the other way round in the table": {"x": "a", "a": "x", "y": "b", "b": "y"},
    "outside the table": {"x": "zz", "y": "x"},
}
# RENAME INVARIANCE excludes this one row, as the plan says: its written order still moves it with the names.
NOT_RENAMED = {A_NAMED_MISS}
SYMBOL_ROWS = tuple(row for row in ROWS if symbols(row[0]) and row[0] not in NOT_RENAMED)
COSTLY_ROWS = tuple(row for row in SYMBOL_ROWS if costly(row)) + (SLOW_ROW,)
FAST_ROWS = tuple(row for row in SYMBOL_ROWS if not costly(row))
# R4 maps every other row. These it declines, each for the reason it gives, and each takes the renames above.
R4_DECLINES = {
    "Subs(1/(x + 1 - 1), x, 2) = Subs(1/x, x, 2) + 1/x - 1/x": "calls 'Subs'",
    "summation(1/(x + 1 - 1), (x, 1, 2)) + 1/(y + x) = 3/2 + 1/(x + y)": "calls 'summation'",
    "((x - 1)/(x - 1)) mod 3 + 1/(y + x) = 1 + 1/(x + y)": "does not parse as an expression",
}


def test_the_rename_rows_are_not_thin():
    assert len(SYMBOL_ROWS) > 90 and len(COSTLY_ROWS) == 5 and all(symbols(claim) for claim, _literal, _want in STATED_ROWS)
    assert {n for claim, _want in SYMBOL_ROWS for n in symbols(claim)} >= {"a", "b", "c", "d", "t", "v", "w", "x", "y", "z"}


@pytest.mark.parametrize("name", RENAMES)
def test_every_row_reads_one_verdict_under_each_rename(name):
    moved = [(claim, want) for claim, want in FAST_ROWS if verdict_of(renamed(claim, RENAMES[name])) != want]
    moved += [(claim, want) for claim, literal, want in STATED_ROWS
              if read("equality", stated(renamed(claim, RENAMES[name]), literal)) != want]
    assert moved == []


def test_every_row_reads_one_verdict_through_r4():
    moved, declined = read_through_r4([(c, params(c), w) for c, w in FAST_ROWS]
                                      + [(c, stated(c, lit), w) for c, lit, w in STATED_ROWS])
    assert moved == []
    assert set(declined) == set(R4_DECLINES), declined
    assert all(words in declined[claim] for claim, words in R4_DECLINES.items())


def read_through_r4(rows):
    R = _restate()
    moved, declined = [], {}
    for claim, spec, want in rows:
        subject = [{"id": "b", "domain": "mathematics", "spec": {"mode": "equality", "params": spec}}]
        out = R.restate("R4", subject)
        if not out.applied:
            declined[claim] = out.reason
        elif verify(out.after[0]["spec"])["verdict"] != want:
            moved.append((claim, want))
    return moved, declined


def test_the_row_excluded_from_rename_moves_as_the_plan_says():
    """The plan's named miss (8): the written order of its own sum moves it, and nothing else does."""
    assert verdict_of(A_NAMED_MISS) == B
    assert verdict_of("1/simplify(x + y) = 1/(x + y)") == H


@pytest.mark.slow
@pytest.mark.parametrize("name", RENAMES)
def test_a_costly_row_reads_one_verdict_under_each_rename(name):
    assert [row for row in COSTLY_ROWS if verdict_of(renamed(row[0], RENAMES[name])) != row[1]] == []


@pytest.mark.slow
def test_a_costly_row_reads_one_verdict_reversed_and_through_r4():
    assert [row for row in COSTLY_ROWS if verdict_of(reversed_row(row[0])) != row[1]] == []
    moved, declined = read_through_r4([(c, params(c), w) for c, w in COSTLY_ROWS])
    assert moved == [] and declined == {}


# ── cost, by counts ──────────────────────────────────────────────────────────────────────────────────────────────────
def terms_written(value):
    """How many terms a value writes: those of its largest sum at any depth, so a denominator multiplied out counts."""
    return max([len(sympy.Add.make_args(value))] + [len(found.args) for found in value.atoms(sympy.Add)])


@pytest.fixture
def expands(monkeypatch):
    """The terms of what expand RETURNS, never the estimate: the measure under test cannot be the one that grades it."""
    real, seen = M.expand, []

    def spy(value, *args, **kwargs):
        result = real(value, *args, **kwargs)
        seen.append(terms_written(result))
        return result
    monkeypatch.setattr(M, "expand", spy)
    return seen


@pytest.fixture
def factored(monkeypatch):
    """Every call of factor_list: by sympy's name for it wherever a claim runs, and by a Poly's own method while the compare
    runs. simplify reaches that method on a dummy of its own inside sympy, on some claims, at the step's base too."""
    seen, comparing = [], []

    def spying(real, only_comparing):
        def spy(*args, **kwargs):
            if comparing or not only_comparing:
                seen.append(args[0])
            return real(*args, **kwargs)
        return spy
    monkeypatch.setattr(M._sp, "factor_list", spying(M._sp.factor_list, False))
    monkeypatch.setattr(polytools.Poly, "factor_list", spying(polytools.Poly.factor_list, True))
    if hasattr(M, "_same_zeros"):
        real_compare = M._same_zeros

        def compare(*args):
            comparing.append(True)
            try:
                return real_compare(*args)
            finally:
                comparing.pop()
        monkeypatch.setattr(M, "_same_zeros", compare)
    return seen


@pytest.fixture
def dense(monkeypatch):
    """Every dense product a Poly can run: the three names polyclasses multiplies by, whichever method reached them."""
    seen = []

    def spying(name, real):
        def spy(*args, **kwargs):
            seen.append(name)
            return real(*args, **kwargs)
        return spy
    for name in ("dmp_mul", "dmp_sqr", "dmp_pow"):
        monkeypatch.setattr(polyclasses, name, spying(name, getattr(polyclasses, name)))
    return seen


@pytest.fixture
def multiplied(monkeypatch):
    """How many terms each sparse product comes to, read off what was multiplied."""
    seen = []
    if hasattr(M, "_product"):
        real = M._product

        def spy(polys, ring):
            product = real(polys, ring)
            seen.append(len(product))
            return product
        monkeypatch.setattr(M, "_product", spy)
    return seen


@pytest.fixture
def polys(monkeypatch):
    """The terms of every Poly the proof builds, read off what was built."""
    real, seen = M._sp.Poly, []

    def spy(*args, **kwargs):
        built = real(*args, **kwargs)
        seen.append(len(built.terms()))
        return built
    monkeypatch.setattr(M._sp, "Poly", spy)
    return seen


def same(claim):
    return M._same_zeros(*claim.split(" = "), [])


def test_every_row_keeps_inside_each_count(expands, factored, polys, multiplied):
    """Each claim alone against the bound, and no claim factors, with the second zero test and the window rows among them."""
    paid = []
    for spec in [params(claim) for claim, _want in ROWS] + [stated(claim, literal) for claim, literal, _want in STATED_ROWS]:
        polys.clear()
        M.verify_equality(spec)
        paid.append(sum(polys))
    assert expands and max(expands) <= M._MAX_POLE_TERMS
    assert 0 < max(paid) <= M._MAX_POLE_TERMS
    assert multiplied and max(multiplied) <= M._MAX_POLE_TERMS
    assert factored == []


def test_the_spies_see_what_they_count(factored, dense, monkeypatch):
    """A count of zero means nothing from a spy that cannot see, so each is shown the call it stands at, inside the compare."""
    def reaches_for_both(polys, ring):
        first = next(iter(polys))
        first.factor_list()
        assert first*first == first**2
        return ring.one
    monkeypatch.setattr(M, "_product", reaches_for_both)
    assert same(PROVED[6]) is True
    assert len(factored) == 2 and {"dmp_mul", "dmp_pow"} <= set(dense)
    sympy.factor_list(sympy.Symbol("x")**2 - 1)
    assert len(factored) == 3


def test_nothing_in_the_module_factors_and_no_degree_budget_exists():
    assert "factor_list" not in inspect.getsource(M)
    assert not hasattr(M, "_MAX_POLE_DEGREE")


def test_the_limits_are_the_ones_the_record_measured():
    assert (M._MAX_POLE_TERMS, M._MAX_POLE_WEIGHT, M._MAX_POLE_SYMBOLS) == (500, 64, 12)


@pytest.mark.parametrize("claim,want", [(OVER_THE_PRODUCTS, False), (PROVED[11], True), (PROVED[6], True), (OVER_ONE, False)])
def test_no_dense_multiplication_runs_in_the_compare_and_the_sparse_one_does(claim, want, dense, factored, multiplied):
    assert same(claim) is want
    assert dense == [] and factored == []
    assert len(multiplied) == 2


def test_line_59s_sides_multiply_to_their_384_terms_each(dense, multiplied):
    assert len(A_SIDE) == 161
    assert same(OVER_THE_PRODUCTS) is False
    assert multiplied == [384, 384] and dense == []


@pytest.mark.parametrize("claim", ["1/(y + x) = 1/(x + y)", "1/(x - y) = -1/(y - x)", "1/(x*y) = 1/(y*x)", "1/(2*x - 2*y) = 1/(2*(x - y))",
                                   "1/(x**60 - y**60) = -1/(y**60 - x**60)", PROVED[9]])
def test_matched_factors_are_never_multiplied(claim, multiplied):
    assert same(claim) is True
    assert multiplied == []


def test_only_what_is_unmatched_is_multiplied(multiplied):
    """The sixty linear forms match, and leave the compare, so the claim pays for x**2 - y**2 and its two factors."""
    assert same(PROVED[10]) is True
    assert multiplied == [2, 2]


@pytest.mark.parametrize("claim", ["x/x = 1", "x**61/x**61 = 1", "(x**60 - y**60)/(x**60 - y**60) = 1", "1/(x*(x + 1)) = 1/x",
                                   f"t/t{beside(product, 3)} = 1{beside(product, 3)}"])
def test_one_side_left_ends_with_nothing_multiplied(claim, multiplied):
    assert same(claim) is False
    assert multiplied == []


@pytest.mark.parametrize("claim,want", [("1/(x*(x + 1)) = 1/(x*(x + 2))", False), ("1/(x + 1) = 1/(x + 2)", False), ("1/(x*y) = 1/(y*(x + 1))", False),
                                        ("1/(x + y) = 1/(x + 2*y)", False), ("1/((x + 1)*(x + 2)) = 1/(x**2 + 3*x + 2)", True),
                                        ("1/((x + 1)*(x + 2)) = 1/(x**2 + 3*x + 3)", False), ("1/(2*x + 2) = 1/(3*x + 3)", True),
                                        ("1/((2*x + 2)*(x - 1)) = 1/(5*x**2 - 5)", True)])
def test_two_products_must_be_one_polynomial_up_to_a_nonzero_rational(claim, want):
    assert same(claim) is want


def test_each_sides_product_is_read_at_and_past_the_bound_before_it_runs(multiplied):
    """Eight binomials count 256 terms and nine count 512, read off the factors before anything runs. These collect, so what
    the eight come to is smaller: the count is what bounds the work, since it holds before anything collects."""
    def forms(sign, count):
        return "*".join(f"(x {sign} {k}*y)" for k in range(1, count + 1))
    assert same(f"1/({forms('+', 8)}) = 1/({forms('-', 8)})") is False
    assert multiplied == [9, 9]
    multiplied.clear()
    assert same(f"1/({forms('+', 9)}) = 1/({forms('-', 9)})") is False
    assert multiplied == []


def test_a_non_zero_difference_reaches_the_proof_on_the_stated_precision_path_alone(monkeypatch):
    """The window asks, so a removable singularity cannot pass inside it, and the same claim with no literal never does."""
    real, asked = M._same_zeros, []
    monkeypatch.setattr(M, "_same_zeros", lambda *args: asked.append(args) or real(*args))
    assert M.verify_equality(stated(SAME_POLES_IN_THE_WINDOW, "3.1")).status == "CONFIRMED"
    assert len(asked) == 1
    asked.clear()
    assert M.verify_equality(params(SAME_POLES_IN_THE_WINDOW)).status == "MISMATCH"
    assert asked == []


def test_the_term_bound_is_read_at_and_past_it_before_any_poly(polys, monkeypatch):
    claim = "1/(x + y + z + w) = 1/(w + z + y + x)"       # two written factors of four terms
    monkeypatch.setattr(M, "_MAX_POLE_TERMS", 8)
    assert same(claim) is True and polys == [4, 4]
    polys.clear()
    monkeypatch.setattr(M, "_MAX_POLE_TERMS", 7)
    assert same(claim) is False and polys == []


def test_the_term_bound_counts_every_written_factor_of_the_claim(polys):
    """A claim pays for all its factors, so the bound is the claim's: each of these is far inside it alone."""
    def powers(count):
        return "*".join(f"((x + y + z)**10 + {k})" for k in range(1, count + 1))
    assert M._term_estimate(M._parse("(x + y + z)**10 + 1", evaluate=False)) == 67
    assert same(f"1/({powers(3)}) = 1/({powers(3).replace('x + y', 'y + x')})") is True     # 6 written factors, 402 terms
    polys.clear()
    assert same(f"1/({powers(4)}) = 1/({powers(4).replace('x + y', 'y + x')})") is False    # 8, 536
    assert polys == []


@pytest.mark.parametrize("at,past", [("1/(x**64 + 1) = 1/(1 + x**64)", "1/(x**65 + 1) = 1/(1 + x**65)"),
                                     ("1/(x + 2**31*y) = 1/(2**31*y + x)", "1/(x + 2**32*y) = 1/(2**32*y + x)"),
                                     ("1/((x**8 + 1)**8 + 1) = 1/(1 + (x**8 + 1)**8)", "1/((x**8 + 1)**9 + 1) = 1/(1 + (x**8 + 1)**9)")])
def test_the_weight_is_read_at_and_past_it_before_any_poly(at, past, polys):
    assert same(at) is True
    polys.clear()
    assert same(past) is False and polys == []


def test_the_symbols_are_read_at_and_past_their_limit_before_any_poly(polys):
    def claim(count):
        names = [f"a{i}" for i in range(count)]
        return f"1/({' + '.join(names)}) = 1/({' + '.join(reversed(names))})"
    assert same(claim(M._MAX_POLE_SYMBOLS)) is True
    polys.clear()
    assert same(claim(M._MAX_POLE_SYMBOLS + 1)) is False and polys == []


@pytest.mark.parametrize("claim", PAST_A_LIMIT)
def test_what_a_limit_is_for_reaches_neither_poly_nor_factor_list(claim, polys, factored):
    assert same(claim) is False
    assert polys == [] and factored == []


def test_no_poly_is_built_past_the_term_bound(polys):
    assert same("1/((x + y + z + w)**30 + 1) = 1/(1 + (w + z + y + x)**30)") is False
    assert polys == []


@pytest.mark.parametrize("text", ["x", "3", "x + y", "(x + y)**7", "(x + 2*y + 3*z)**6", "x**5*y**3 + z**9", "(x**2 + 3)*(x**3 - 7)",
                                  "2**30*x + 1", "(2*x + 3*y)**9 - 5", "(1/3)*x + y/7", "(x + y)**20 + (x - y)**20"])
def test_the_weight_never_reads_under_the_degree_and_follows_the_coefficients(text):
    value = M._parse(text, evaluate=False)
    weight = M._weight(value)
    poly = sympy.Poly(value, *(sorted(value.free_symbols, key=str) or sympy.symbols("x,")), domain="QQ")
    assert poly.total_degree() <= weight
    assert max(max(abs(c.p), c.q) for c in poly.coeffs()).bit_length() <= weight * M._term_estimate(value).bit_length()


# ── the worked detail ────────────────────────────────────────────────────────────────────────────────────────────────
PLAIN = "a = b; the difference simplifies to 0"


def test_worked_equality_skips_its_expand_and_its_simplify_past_the_estimate(expands, monkeypatch):
    monkeypatch.setattr(M, "simplify", lambda value: pytest.fail("the plain detail runs no simplify"))
    over = M._parse("(x + y + z)**40")
    assert M._term_estimate(over) > M._MAX_POLE_TERMS
    assert M._worked_equality("a", "b", over, over) == PLAIN
    assert expands == []


def test_worked_equality_keeps_its_work_inside_the_estimate(expands):
    x = M._parse("(x + 1)**2")
    assert M._worked_equality("a", "b", x, x) == "a = b; both sides reduce to x**2 + 2*x + 1"
    assert expands == [3, 3]


def test_the_two_sides_each_answer_for_the_estimate(expands):
    small, over = M._parse("x + 1"), M._parse("(x + y + z)**40")
    for ea, eb in ((small, over), (over, small)):
        assert M._worked_equality("a", "b", ea, eb) == PLAIN
    assert expands == []


@pytest.mark.parametrize("text", ["sin(x)**2 + cos(x)**2", "exp(x + y)", "Abs(x) + 1", "x**y", "sqrt(x) + 1", "Matrix(((x + y, 1), (2, 3)))"])
def test_what_is_no_rational_function_of_its_free_symbols_keeps_the_plain_detail(text, expands, monkeypatch):
    monkeypatch.setattr(M, "simplify", lambda value: pytest.fail("the plain detail runs no simplify"))
    value = M._parse(text)
    assert M._worked_equality("a", "b", value, value) == PLAIN
    assert expands == []


def test_a_confirmed_equality_keeps_the_detail_it_earned():
    r = M.verify_equality({"expr_a": "sin(x)**2 + cos(x)**2", "expr_b": "1"})
    assert r.status == "CONFIRMED" and r.detail == "sin(x)**2 + cos(x)**2 = 1; the difference simplifies to 0"
    r = M.verify_equality({"expr_a": "(x + 1)**2", "expr_b": "x**2 + 2*x + 1"})
    assert r.detail == "(x + 1)**2 = x**2 + 2*x + 1; both sides reduce to x**2 + 2*x + 1"


# A lifted claim used to answer before any of this ran, and simplify on a side has no bound a term count can give: the second
# of these estimates 22 terms beside 1/(x - y), and it did not finish in 30 s.
FRACTIONS = balanced([f"1/(x + {k})" for k in range(1, 101)])
TEN_SYMBOLS = balanced([f"1/(a{k} + {k})" for k in range(1, 11)])


@pytest.mark.parametrize("claim", [PROVED[9], "1/(x - y) = -1/(y - x)", f"1/(x - y) + {FRACTIONS} = -1/(y - x) + {FRACTIONS}",
                                   f"1/(x - y) + {TEN_SYMBOLS} = -1/(y - x) + {TEN_SYMBOLS}"])
def test_a_lifted_claim_takes_the_plain_detail_and_simplifies_no_side(claim, expands, factored, monkeypatch):
    a, b = claim.split(" = ")
    real, simplified = M.simplify, []
    monkeypatch.setattr(M, "simplify", lambda value: simplified.append(value) or real(value))
    r = M.verify_equality(params(claim))
    assert r.status == "CONFIRMED" and r.detail == f"{a} = {b}; the difference simplifies to 0"
    assert expands == [] and factored == [] and len(simplified) == 1       # the difference, and never a side


def test_a_claim_with_no_difference_named_keeps_its_work():
    """The plain detail is for a lift. Everything the guard never spoke about keeps the base's detail."""
    r = M.verify_equality({"expr_a": "(x + 1)/(x - 1)", "expr_b": "(x - 1 + 2)/(x - 1)"})
    assert r.status == "CONFIRMED" and "reduce" in r.detail


# ── the term estimate ────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text,want", [("x", 1), ("3", 1), ("pi", 1), ("x + y", 2), ("(x + y)**2", 3), ("(x + y + z)**2", 6), ("(x + y)*(x - y)", 4),
                                       ("1/(x + y)**2", 3), ("1/x + 1", 2), ("(x + y)**2 + 1/x", 4), ("sqrt(2)*x + 1", 2),
                                       ("(1 + sqrt(2))**(5/2)*x", 4)])
def test_the_term_estimate_reads_without_expanding(text, want, expands):
    assert M._term_estimate(M._parse(text, rational=True)) == want
    assert expands == []


# A term count is true only of a rational function of its free symbols. These are, and expand may have them.
WITHIN_THE_BOUND = ("(x + y + z)**7", "(x + y)**5*(x - y)**4", "(x + y)**3 + (y + z)**4", "1/(x + y + z)**4", "(x + 1)*(y + 1)*(z + 1)",
                    "((x + y)**2 + 1)**3", "((x + y)*(x - y))**3", "((x + y)*(x - y))**(-2)", "(x + 1)/(y + 1)**2", "(x + y + z + w)**10",
                    "x**10000 + 1", "(1 + sqrt(2) + sqrt(3))**(41/2)*x", "pi*x + pi*y", "(x + y)**2/z + 1/x")
# These are not, the finding's inputs first. A number stands in for Abs in the two after the exp form: every constant is a
# rational function of nothing, so a test of that alone leaves the same hole open with no symbol in it.
EXP_OF_LOG = "exp(60*log(1 + Abs(x) + Abs(y)) + t)"
PAST_THE_BOUND = (SPLIT_POWER.format(12, "t"), SPLIT_POWER.format(30, "t"), SPLIT_POWER.format(60, "t"), EXP_OF_LOG,
                  "x + (1 + sqrt(2) + sqrt(3) + sqrt(5) + sqrt(7) + sqrt(11))**(60 + pi)",
                  "x*exp(60*log(1 + sqrt(2) + sqrt(3)) + pi)", "(x + y)**(5/2)", "x**(y + z)", "sqrt(x) + 1", "sin((x + y)**2)",
                  "(x + y)**2 + sin(x)", "Abs(x + y)**60", "log((x + y)**60)", "x*sin(1) + 1", "Sum(x**k, (k, 1, 3))",
                  "Piecewise((x, y > 0), (2, true))", "(x + y)**2.0", "2**(x + y)", "exp(x + y)", "cos(x)**2 + sin(x)**2",
                  "(1 + sqrt(2) + sqrt(3))**(61/2)*x")      # a rational power of a number the count reads: 528 terms


def test_the_table_holds_both_kinds():
    assert len(WITHIN_THE_BOUND) >= 10 and len(PAST_THE_BOUND) >= 10
    assert all(M._term_estimate(M._parse(t)) <= M._MAX_POLE_TERMS for t in WITHIN_THE_BOUND)


def expand_stopped(value, seconds=20):
    """expand, stopped so a value it cannot finish fails here and hangs nothing. No time is pinned: this is only a stop."""
    answer = []
    threading.Thread(target=lambda: answer.append(sympy.expand(value)), daemon=True).start()
    for _ in range(seconds * 20):
        if answer:
            return answer[0]
        threading.Event().wait(0.05)
    pytest.fail(f"expand did not return in {seconds} s, so the estimate of {str(value)[:60]} was no bound")


@pytest.mark.parametrize("text", WITHIN_THE_BOUND + PAST_THE_BOUND)
def test_whenever_the_estimate_answers_expand_writes_no_more(text):
    value = M._parse(text)
    estimate = M._term_estimate(value)
    assert estimate > M._MAX_POLE_TERMS or terms_written(expand_stopped(value)) <= estimate


@pytest.mark.parametrize("text", PAST_THE_BOUND)
def test_a_value_no_count_is_true_of_reads_one_past_the_bound(text):
    assert M._term_estimate(M._parse(text)) == M._MAX_POLE_TERMS + 1


@pytest.mark.parametrize("text", ["(x + y + z + w)**30", "(x + y)**10000", "((x + y)**100 + 1)**100", "(((x + y)**100 + 1)**100 + 1)**100"])
def test_the_estimate_stops_one_past_the_bound(text):
    assert M._term_estimate(M._parse(text)) == M._MAX_POLE_TERMS + 1


# ── the named miss ───────────────────────────────────────────────────────────────────────────────────────────────────
# A pole the exact compare cannot prove keeps the base's BROKEN, true ones with the false. Each of these is true, by kind.
def quadratics(pairs):
    return "*".join(f"(x**2 + {a + b}*x*y + {a*b}*y**2)" for a, b in pairs)


# Twelve linear forms paired two ways, so nothing matches and each side multiplies to 3**6 = 729 terms by the count.
PAST_THE_TERM_BOUND = (f"1/({quadratics([(1, 2), (3, 4), (5, 6), (7, 8), (9, 10), (11, 12)])}) = "
                       f"1/({quadratics([(1, 3), (2, 4), (5, 7), (6, 8), (9, 11), (10, 12)])})")
TRUE_AND_KEPT = {
    "a float": "1/(x + 0.5) = 1/(0.5 + x)",
    "a non-rational constant": "1/(pi*x + pi*y) = 1/(pi*(x + y))",
    "a non-polynomial base": "1/sin(y + x) = 1/sin(x + y)",
    "off the allow-list": A_NAMED_MISS,
    "a sign on a sum": "1/(-(x + y)) = -1/(y + x)",
    "past the term bound": PAST_THE_TERM_BOUND,
    "a power's multiplicity": MULTIPLICITY,
}


@pytest.mark.parametrize("kind", TRUE_AND_KEPT)
def test_the_named_miss_keeps_the_broken_of_a_true_claim(kind):
    claim = TRUE_AND_KEPT[kind]
    a, b = (M._parse(text, rational=True) for text in claim.split(" = "))
    assert sympy.simplify(a - b) == 0
    assert verdict_of(claim) == B


def test_the_claim_past_the_term_bound_reaches_no_multiplication(multiplied):
    assert same(PAST_THE_TERM_BOUND) is False
    assert multiplied == []


# ── the record ───────────────────────────────────────────────────────────────────────────────────────────────────────
def _bullet():
    text = (ROOT / "MEASURED.md").read_text(encoding="utf-8")
    start = text.index("- **Poles, as written.**")
    return re.sub(r"\s+", " ", text[start:text.index("- **Limits, by side.**", start)])


def test_every_reading_the_record_quotes_is_a_row_here():
    quoted = set(re.findall(r"`([^`]+ = [^`]+)`", _bullet()))
    rows = {claim for claim, _want in ROWS} | {claim for claim, _literal, _want in STATED_ROWS}
    assert len(quoted) >= 6 and quoted <= rows, quoted - rows


def test_the_record_says_what_was_found_what_the_rule_does_and_names_its_miss():
    bullet = _bullet()
    for words in ("compared pole bases as written", "can only lift a BROKEN, and only on proof", "keeps the base's reading",
                  "`_domain_mismatch` stays as it was", "no new refusal", "a rational function with rational coefficients",
                  "syntax tree", "the unevaluated value", "a sign on a name or an integer", "primitive part",
                  "per claim", "500 terms", "12 symbols", "every confirm reads this answer", "exact-decimal",
                  "stated-precision", "`tests/test_poles.py`", "by counts and never by timing", "sympy 1.14.0",
                  "the terms of what expand returns", "true ones with the false", "sympy's sparse polynomial ring",
                  "up to a nonzero rational", "a check and not a search", "no degree budget exists", "the pole compare makes no factor_list call",
                  "simplify reaches factor_list on some claims, as it does at the base",
                  "no dense Poly multiplication runs in the compare",
                  "a float, a non-rational constant, a non-polynomial base, anything off the list, a claim past the term bound, "
                  "or a power's multiplicity the written factors drop",
                  "a rename that writes the sum in sympy's order reads HOLDS"):
        assert words in bullet, words


def test_the_changelog_says_which_claims_moved():
    unreleased = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").split("## Unreleased", 1)[1].split("\n## ", 1)[0]
    flat = re.sub(r"\s+", " ", unreleased)
    for words in ("1/(y + x) = 1/(x + y)", "read HOLDS where they read BROKEN", "x/x = 1", "only on proof",
                  "keeps its BROKEN", "every confirm reads this answer", "0.1*x/x + 0.2 = 0.3 reads BROKEN where it read HOLDS",
                  "x/x*3.14159 = 3.14"):
        assert words in flat, words
