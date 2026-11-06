"""The polynomial mode: a gcd or lcm of polynomials, read in the ring and generators the claim states (run
2026-11-04-gcd-lcm-order, step number-theory).

Outside this mode gcd(x**2 - 1, x - 1) = x - 1 reads INCOMPLETE, because a polynomial gcd is defined up to a unit and sympy
picks the unit by an order nobody stated. A claim that names its ring and generators leaves nothing unbound, and two answers
that differ by a unit are one answer: plus or minus one over ZZ, any nonzero rational over QQ, and zero equals only zero.

PLAN_ROWS is the plan's THE POLYNOMIAL MODE (ledger line 167), in its own notation, exactly: a row that reads otherwise changes
only by replan. A text reads through an allow-list on its syntax tree before it is a polynomial, because Poly takes what is no
polynomial and hands back one: a Tuple as a coefficient list, an equation as its difference, a matrix by its entries, and a
float as a nearby rational. Names the fix adds are read inside the tests, so the file collects at the step's base.
"""
from __future__ import annotations

import ast
import copy
import importlib.util
import inspect
import io
import itertools
import json
import pickle
import re
import sys
import tokenize
from pathlib import Path

import pytest

from concordance import cells, derivation as D, schema, tool_registry
from concordance.derivation import verify
from concordance.verifiers import mathematics as M

pytestmark = pytest.mark.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
I, H, B, E = "INCOMPLETE", "HOLDS", "BROKEN", "SYSTEM_ERROR"
ROW = re.compile(r"^(?P<ring>\S+) \[(?P<gens>[^\]]*)\] (?P<word>gcd|lcm) \[(?P<texts>[^\]]*)\] = (?P<claimed>.+)$")


def spec(row):
    """A row in the plan's notation as the claim it writes."""
    m = ROW.match(row)
    assert m, row
    return {m["word"]: m["texts"].split(", "), f"claimed_{m['word']}": m["claimed"], "generators": m["gens"].split(", "), "ring": m["ring"]}


def read(params, mode="polynomial"):
    return verify({"mode": mode, "params": copy.deepcopy(params)})


def verdict(params, mode="polynomial"):
    return read(params, mode)["verdict"]


def detail(params):
    return read(params)["trail"][0]["detail"]


HOLDING = (
    "QQ [x] gcd [x**2 - 1, x - 1] = x - 1", "QQ [x] gcd [x**2 - 1, x - 1] = 2*x - 2",
    "ZZ [x] gcd [2*x + 2, 4*x + 4] = 2*x + 2", "ZZ [x] gcd [2*x + 2, 4*x + 4] = -2*x - 2",
    "QQ [x] gcd [2*x + 2, 4*x + 4] = x + 1",
    "QQ [x, y] gcd [y - x, x - y] = x - y", "QQ [x, y] gcd [y - x, x - y] = y - x",
    "QQ [y, x] gcd [y - x, x - y] = x - y", "QQ [y, x] gcd [y - x, x - y] = y - x",
    "ZZ [x, y] gcd [y - x, x - y] = x - y", "QQ [x, y] gcd [x**2 - y**2, x + y] = x + y",
    "QQ [x] gcd [x, x + 2] = 1", "QQ [x] gcd [x, x + 2] = 2", "ZZ [x] gcd [x, x + 2] = 1",
    "QQ [x] gcd [x**2 - 1, x - 1, x + 1] = 1", "QQ [x] gcd [x**2 - 1, x**2 - 2*x + 1, x - 1] = x - 1",
    "QQ [x] lcm [x - 1, x + 1] = x**2 - 1", "QQ [x, y] lcm [y - x, x - y] = x - y", "ZZ [x] lcm [2*x + 2, 4*x + 4] = 4*x + 4",
    "QQ [x] gcd [0, x] = x", "QQ [x] gcd [0, 0] = 0", "QQ [x] lcm [0, 0] = 0", "ZZ [x] lcm [0, x] = 0",
)
FALSE = (
    "QQ [x] gcd [x**2 - 1, x - 1] = x + 1", "ZZ [x] gcd [2*x + 2, 4*x + 4] = x + 1", "ZZ [x] gcd [x, x + 2] = 2",
    "QQ [x, y] gcd [y - x, x - y] = x + y", "QQ [x] gcd [x - 1, x + 1] = 0", "QQ [x] lcm [x - 1, x + 1] = x - 1",
)
NOT_CHECKABLE = (
    "RR [x] gcd [x**2 - 1, x - 1] = x - 1", "GF(5) [x] gcd [x**2 - 1, x - 1] = x - 1",
    "QQ [x] gcd [x*y - x*z, x*z - x*y] = x*y - x*z", "QQ [x] gcd [sin(x), x] = 1", "QQ [x] gcd [1/x, x] = 1",
    "ZZ [x] gcd [x, x] = x/2", "QQ [x] gcd [x] = x",
)
PLAN_ROWS = tuple((row, want) for rows, want in ((HOLDING, H), (FALSE, B), (NOT_CHECKABLE, I)) for row in rows)

# Past the plan's table: units, content, a fold of three, products written out and rows whose gcd is known by construction.
MORE = (
    ("ZZ [x] gcd [x, x + 2] = -1", H), ("QQ [x] gcd [x, x + 2] = 1/2", H), ("QQ [x] gcd [x, x + 2] = -7", H),
    ("QQ [x] gcd [x, x + 2] = 0.5", H), ("ZZ [x] gcd [x, x + 2] = 1/2", I), ("ZZ [x] gcd [x, x + 2] = 0", B), ("ZZ [x] gcd [x, x] = -x", H),
    ("QQ [x] gcd [0.5*x, 0.25*x] = x", H), ("QQ [x] gcd [x/2, x/3] = 6*x", H), ("ZZ [x] gcd [0.5*x, x] = x", I), ("ZZ [x] gcd [x/1, 2*x] = x", H),
    ("ZZ [x] gcd [6*x + 6, 4*x + 4] = 2*x + 2", H), ("ZZ [x] gcd [6*x + 6, 4*x + 4] = x + 1", B), ("QQ [x] gcd [6*x + 6, 4*x + 4] = x + 1", H),
    ("ZZ [x] lcm [6*x + 6, 4*x + 4] = 12*x + 12", H), ("ZZ [x] lcm [6*x + 6, 4*x + 4] = x + 1", B), ("QQ [x] lcm [6*x + 6, 4*x + 4] = x + 1", H),
    ("ZZ [x, y] gcd [6*x + 6*y, 4*x + 4*y] = 2*x + 2*y", H), ("ZZ [x, y] lcm [6*x + 6*y, 4*x + 4*y] = 12*x + 12*y", H),
    ("ZZ [x] gcd [2*x**2 - 2, 3*x - 3] = x - 1", H), ("ZZ [x] gcd [6, 10] = 2", H), ("ZZ [x] gcd [6, 10, 15] = 1", H), ("ZZ [x] lcm [2, 3, 5] = 30", H),
    ("QQ [x] gcd [6, 10] = 1", H), ("QQ [x] lcm [2, 3] = 1", H), ("ZZ [x] gcd [6, 10] = 3", B),
    ("QQ [x] gcd [(x - 1)*(x + 2), (x - 1)*(x + 3)] = x - 1", H), ("QQ [x] lcm [(x - 1)*(x + 2), (x - 1)*(x + 3)] = (x - 1)*(x + 2)*(x + 3)", H),
    ("QQ [x, y] gcd [(x + y)*(x - y), (x + y)**2] = x + y", H), ("QQ [x, y] gcd [(x + y)*(x - y), (x + y)**2] = x - y", B),
    ("QQ [x, y, z] gcd [(x + y + z)*(x - z), (x + y + z)*(y - z), (x + y + z)*(x + z)] = x + y + z", H),
    ("QQ [x, y] gcd [x*y, x] = x", H), ("QQ [x, y, z] gcd [x + y, y + z] = 1", H), ("QQ [x, y] gcd [x, y] = 0", B),
    ("QQ [x] lcm [x, 0] = 0", H), ("QQ [x] lcm [x, 0, x + 1] = 0", H), ("QQ [x] lcm [0, x] = x", B), ("QQ [x] gcd [x, 0, x**2] = x", H),
    ("ZZ [x] gcd [0, 0] = 0", H), ("ZZ [x] gcd [0, 2*x] = -2*x", H), ("ZZ [x] gcd [0, 0] = 1", B), ("QQ [x] gcd [0, 0] = 1", B),
    ("QQ [x] gcd [x**2, x**2] = x^2", H), ("QQ [x, y] gcd [x**2 - 1, x - 1] = x - 1", H), ("QQ [x] gcd [1, x] = 1", H),
    ("QQ [a, b] gcd [a**2 - b**2, a - b] = b - a", H),
    # the mode's named miss: a text whose value is a polynomial and whose form is not
    ("QQ [x] gcd [x/x, x] = 1", I), ("QQ [x] gcd [exp(0)*x, x] = x", I), ("ZZ [x] gcd [factorial(3)*x, x] = x", I),
)


@pytest.mark.parametrize("row,want", PLAN_ROWS)
def test_each_expected_reading(row, want):
    assert verdict(spec(row)) == want


@pytest.mark.parametrize("row,want", MORE)
def test_units_content_folds_and_written_products(row, want):
    assert verdict(spec(row)) == want


def test_the_table_is_the_plans():
    assert (len(HOLDING), len(FALSE), len(NOT_CHECKABLE)) == (23, 6, 7)


# ── what each field must be ──────────────────────────────────────────────────────────────────────────────────────────
WHOLE = spec("QQ [x, y] gcd [y - x, x - y] = x - y")
MISSING = ("generators", "ring", "gcd", "claimed_gcd")


@pytest.mark.parametrize("field", MISSING)
def test_a_missing_field_is_not_checkable_and_says_what_to_state(field):
    params = {k: v for k, v in WHOLE.items() if k != field}
    assert verdict(params) == I
    assert field.replace("claimed_", "") in detail(params) and "state" in detail(params)
    assert detail(params).startswith(M._REFUSAL)


@pytest.mark.parametrize("field,value", [
    ("generators", []), ("generators", "x"), ("generators", None), ("generators", {"x": 0}), ("generators", ["x", "x"]), ("generators", [1]),
    ("generators", [None]), ("generators", [["x"]]), ("generators", ["x + 1"]), ("generators", ["x y"]), ("generators", [" x"]), ("generators", [""]),
    ("generators", ["_x"]), ("ring", None), ("ring", "qq"), ("ring", "Z"), ("ring", "CC"), ("ring", "QQ[y]"), ("ring", "ZZ_I"), ("ring", ["QQ"]), ("ring", 1),
    ("gcd", "x"), ("gcd", None), ("gcd", {"x": 0}), ("gcd", []), ("gcd", ["x"]), ("gcd", ["x", 0]), ("gcd", [1, 2]), ("gcd", ["x", None]), ("gcd", ["x", ["x"]]),
    ("claimed_gcd", 1), ("claimed_gcd", None), ("claimed_gcd", 1.5), ("claimed_gcd", True), ("claimed_gcd", ["x"]),
], ids=str)
def test_a_field_of_the_wrong_kind_is_not_checkable(field, value):
    assert verdict({**WHOLE, field: value}) == I
    assert detail({**WHOLE, field: value}).startswith(M._REFUSAL)


# A generator is a name the parser reads as a symbol and as nothing else, so no claim can name pi as an indeterminate.
@pytest.mark.parametrize("name", ["pi", "E", "I", "oo", "inf", "true", "false", "nan", "zoo", "sin", "gcd", "beta", "S", "N", "mod", "lambda", "None", "True", "x**2", "x^2"])
def test_a_generator_is_a_name_that_reads_as_a_symbol(name):
    assert verdict({"gcd": [name, name], "claimed_gcd": name, "generators": [name], "ring": "QQ"}) == I


NOT_POLYNOMIALS = (
    # what Poly would have read as a polynomial, and what it would have read it as
    "Tuple(1, 2)", "Eq(x, 1)", "solve(x - 1, x)", "zeros(2)", "eye(2)", "ImmutableMatrix(eye(2))", "Poly(x + 1, x)", "FiniteSet(1)", "N(1/3)*x", "N(sqrt(2))*x",
    "Float(0.5)*x", "1.5*N(1)*x",
    # what evaluates away a pole, a function or a symbol, so its value is a polynomial and its text is not
    "x/x", "(x + 1)/(x + 1)", "x*y/y", "(x**2 - 1)/(x - 1)", "0/x", "0*(1/x)", "1/x - 1/x", "x + 1/x - 1/x", "sin(x)/sin(x)", "0*sin(x)", "exp(log(x))", "sqrt(x)**2", "Limit(x, x, 1)",
    "exp(0)*x", "sqrt(4)*x", "gcd(12, 18)*x", "degree(x**2, x)", "factorial(3)*x", "Abs(-2)*x", "expand((x + 1)**2)", "diff(x**2, x)", "Min(x, x)", "Piecewise((x, true))", "Integer(2)*x", "Rational(1, 2)*x",
    # no polynomial at all
    "sin(x)", "1/x", "x**-1", "x**(-1)", "1/(x + 1)", "x**(1/2)", "x**0.5", "x**2.0", "sqrt(x)", "2**x", "x**x", "x**y", "exp(x)", "log(x)", "Abs(x)", "x % 2", "x mod 2", "Mod(x, 2)", "floor(x)",
    "Sum(x, (k, 1, 3))", "Integral(x, x)", "Derivative(x**2, x)", "Subs(y, y, x)", "x < 1", "true", "Interval(0, 1)",
    # a constant outside the ring, or a symbol outside the generators
    "pi", "pi*x", "E", "I", "I*x", "sqrt(2)", "sqrt(2)*x", "oo", "oo*x", "EulerGamma", "y", "x*y", "x + y", "Dummy()", "Symbol(x)",
    # what the parser refuses
    "", " ", "x +", "(x, x)", "[x]", "x = 1", "1/0", "x/0", "x/(1 - 1)", "zoo", "nan", "gcd(x, 2)", "Poly(x + y)", "x**1000000", "_x",
)


@pytest.mark.parametrize("text", NOT_POLYNOMIALS)
def test_what_is_no_polynomial_text_is_not_checkable_wherever_it_stands(text):
    for params in ({"gcd": [text, "x"], "claimed_gcd": "1"}, {"gcd": ["x", text], "claimed_gcd": "1"}, {"gcd": ["x", "x"], "claimed_gcd": text},
                   {"lcm": ["x", text], "claimed_lcm": "1"}, {"lcm": ["x", "x"], "claimed_lcm": text}):
        full = {**params, "generators": ["x"], "ring": "QQ"}
        assert verdict(full) == I, full
        assert detail(full).startswith(M._REFUSAL), full


@pytest.mark.parametrize("text,ring,want", [
    ("(x + 1)**2", "QQ", "x**2 + 2*x + 1"), ("(x + 1)*(x - 1)", "ZZ", "x**2 - 1"), ("-(x + 1)", "ZZ", "x + 1"), ("+x", "ZZ", "x"), ("2*x/2", "ZZ", "x"),
    ("x/(2*3)", "QQ", "x"), ("x/(1/2)", "ZZ", "2*x"), ("x/0.5", "ZZ", "2*x"), ("1.5*x", "QQ", "3*x"), ("1e2*x", "ZZ", "100*x"), ("x**0", "ZZ", "1"), ("x^2", "QQ", "x**2"),
    ("x - x + 1", "ZZ", "1"), ("(x/2)*2", "ZZ", "x"), ("2**3*x", "ZZ", "8*x"),
])
def test_what_a_polynomial_text_may_be(text, ring, want):
    """Sums, products, a whole power, a division by a number and a decimal, read as the exact rational it writes."""
    assert verdict({"gcd": [text, text], "claimed_gcd": want, "generators": ["x"], "ring": ring}) == H


def test_nothing_off_the_list_is_ever_read(monkeypatch):
    """A text the list refuses never reaches the parser, so a call that would outlast the window is refused at once, and it
    reads not checkable, never an error. A generator is a name, so nothing in that field runs either."""
    seen = []
    real = M._parse
    monkeypatch.setattr(M, "_parse", lambda text, *args, **kwargs: (seen.append(text), real(text, *args, **kwargs))[1])
    off_the_list = ("factorial(10**9)", "nextprime(10**500)", "sin(x)", "exp(0)*x", "x/x", "Tuple(1, 2)")
    for text in off_the_list:
        for params in ({"gcd": [text, "x"], "claimed_gcd": "1"}, {"gcd": ["x", "x"], "claimed_gcd": text}):
            assert M.polynomial_claim({**params, "generators": ["x"], "ring": "QQ"}).status == "NOT_APPLICABLE"
        assert M.polynomial_claim({"gcd": ["x", "x"], "claimed_gcd": "x", "generators": [text], "ring": "QQ"}).status == "NOT_APPLICABLE"
    assert not set(seen) & set(off_the_list)


def test_a_text_past_the_parsers_limits_is_refused_and_raises_nothing():
    for text in ("x" + " + x" * 2000, "-" * 3000 + "x", "(" * 3000 + "x" + ")" * 3000, "x" * 5000):
        assert M.polynomial_claim({"gcd": [text, "x"], "claimed_gcd": "1", "generators": ["x"], "ring": "QQ"}).status == "NOT_APPLICABLE"


def test_a_number_written_past_the_list_is_no_polynomial_text():
    assert verdict(spec("QQ [x] gcd [2**(1/2), x] = 1")) == I
    assert verdict(spec("QQ [x] gcd [x**(1 + 1), x] = x")) == I      # an exponent is a written whole number


# ── a spec holds one claim, and the two doors ────────────────────────────────────────────────────────────────────────
def test_a_spec_holds_one_claim_here_too():
    two = {**WHOLE, "lcm": ["x", "y"], "claimed_lcm": "x*y"}
    third = {**WHOLE, "is_prime": 17, "claimed_prime": True}
    for params in (two, third):
        assert verdict(params) == E and verdict(params, "number_theory") == E
        assert detail(params).startswith("malformed number-theory input")


def test_a_claim_that_is_no_gcd_or_lcm_is_not_read_as_one():
    for claim in ({"is_prime": 17, "claimed_prime": True}, {"factorial": 5, "claimed_factorial": 120}, {"lcm": ["x", "x"], "claimed_gcd": "x"}, {}):
        params = {**claim, "generators": ["x"], "ring": "QQ"}
        assert verdict(params) == I and verdict(params, "number_theory") == I


@pytest.mark.parametrize("row,want", PLAN_ROWS + MORE)
def test_mode_number_theory_delegates_when_a_spec_holds_generators_or_ring(row, want):
    assert verdict(spec(row), "number_theory") == want


@pytest.mark.parametrize("params", [
    {"gcd": ["x**2 - 1", "x - 1"], "claimed_gcd": "x - 1"}, {"lcm": ["x - 1", "x + 1"], "claimed_lcm": "x**2 - 1"},
])
def test_mode_number_theory_with_texts_and_neither_keeps_its_error(params):
    assert verdict(params, "number_theory") == E


@pytest.mark.parametrize("params", [{**WHOLE, "generators": None}, {k: v for k, v in WHOLE.items() if k != "generators"}, {k: v for k, v in WHOLE.items() if k != "ring"}], ids=str)
def test_either_field_alone_reaches_the_polynomial_reading(params):
    assert verdict(params, "number_theory") == I


@pytest.mark.parametrize("fields,want", [
    ({"gcd": ["x", "x"], "claimed_gcd": "7", "generators": ["x"]}, I),            # the plan's row
    ({"gcd": ["x", "x"], "claimed_gcd": "7", "ring": "QQ"}, I),
    ({"gcd": ["x", "x"], "claimed_gcd": "7", "generators": ["x"], "ring": "RR"}, I),
    ({"gcd": ["sin(x)", "x"], "claimed_gcd": "1", "generators": ["x"], "ring": "QQ"}, I),
    ({"gcd": ["x", "x"], "claimed_gcd": "7", "generators": ["x"], "ring": "QQ"}, B),
    ({"gcd": ["x", "x"], "claimed_gcd": "x", "generators": ["x"], "ring": "QQ"}, H),
    ({"lcm": ["x - 1", "x + 1"], "claimed_lcm": "x**2 - 1", "generators": ["x"], "ring": "ZZ"}, H),
])
def test_a_packet_reaches_it_and_a_passing_check_beside_a_refusal_reads_incomplete(fields, want):
    assert verify({"MATH_VERIFY": {"expr_a": "1", "expr_b": "1", **fields}})["verdict"] == want


def test_a_box_with_no_sympy_refuses_it_so_a_passing_check_beside_it_cannot_carry_a_packet(monkeypatch):
    monkeypatch.setattr(M, "_ensure_sympy", lambda: False)
    for read_it in (M.polynomial_claim, M.verify_number_theory):
        got = read_it(dict(WHOLE))
        assert got.status == "NOT_APPLICABLE" and got.detail.startswith(M._REFUSAL) and "sympy" in got.detail


def test_a_false_check_beside_a_refusal_stands():
    assert verify({"MATH_VERIFY": {"expr_a": "1", "expr_b": "2", "gcd": ["x", "x"], "claimed_gcd": "7", "generators": ["x"]}})["verdict"] == B


# ── rename invariance ────────────────────────────────────────────────────────────────────────────────────────────────
# Each moves every name a row holds. sympy's generator table holds x before a, so the third turns the pair round; zz is
# outside the table, so the fourth orders it by another rule.
RENAMES = {
    "x and y exchanged": {"x": "y", "y": "x", "z": "w"},
    "a three-way cycle": {"x": "y", "y": "z", "z": "x"},
    "the other way round in the table": {"x": "a", "y": "x", "z": "y"},
    "outside the table": {"x": "zz", "y": "x", "z": "y"},
}


def tokens(text):
    found = list(tokenize.generate_tokens(io.StringIO(text).readline))
    return [(t.string, t.start[1], t.end[1], following.string == "(") for t, following in zip(found, found[1:]) if t.type == tokenize.NAME]


def renamed(text, mapping):
    """One token-level rename of every symbol at once, and its own check: a bijection on the text's names, and every
    function name left alone."""
    names = {name for name, _start, _end, called in tokens(text) if not called}
    moved = {name: mapping.get(name, name) for name in names}
    assert len(set(moved.values())) == len(moved), f"{mapping} is no bijection on {sorted(moved)}"
    out = text
    for name, start, end, called in reversed(tokens(text)):
        if not called:
            out = out[:start] + moved[name] + out[end:]
    assert [t[0] for t in tokens(out) if t[3]] == [t[0] for t in tokens(text) if t[3]]
    return out


def renamed_spec(params, mapping):
    out = dict(params)
    for key, value in params.items():
        if key == "ring":
            continue
        out[key] = [renamed(v, mapping) for v in value] if isinstance(value, list) else renamed(value, mapping)
    return out


RENAME_ROWS = tuple(row for row in PLAN_ROWS + MORE if re.search(r"[a-z]", spec(row[0])["claimed_" + ROW.match(row[0])["word"]] + " ".join(spec(row[0])["generators"])))


def test_the_rename_rows_are_not_thin():
    assert len(RENAME_ROWS) > 60
    assert {name for row, _want in RENAME_ROWS for name in spec(row)["generators"]} >= {"x", "y", "z", "a", "b"}
    with pytest.raises(AssertionError):
        renamed("x + y", {"x": "z", "y": "z"})
    assert renamed("sin(x) + y", {"x": "y", "y": "x"}) == "sin(y) + x"


@pytest.mark.parametrize("name", RENAMES)
def test_every_row_reads_one_verdict_under_each_rename_with_the_generators_permuted(name):
    moved = []
    for row, want in RENAME_ROWS:
        params = renamed_spec(spec(row), RENAMES[name])
        for order in itertools.permutations(params["generators"]):
            got = M.polynomial_claim({**params, "generators": list(order)}).status
            if {"CONFIRMED": H, "MISMATCH": B, "NOT_APPLICABLE": I}.get(got) != want:
                moved.append((row, order, got))
    assert moved == []


def _restate():
    module = importlib.util.spec_from_file_location("_polynomial_mode_restate", ROOT / "tools" / "restate.py")
    mod = importlib.util.module_from_spec(module)
    sys.modules[module.name] = mod
    module.loader.exec_module(mod)
    return mod


def test_r4_declines_this_mode_so_these_rows_take_the_tests_own_rename():
    R = _restate()
    out = R.restate("R4", [{"id": "b", "domain": "mathematics", "spec": {"mode": "polynomial", "params": dict(WHOLE)}}])
    assert not out.applied and "polynomial" in out.reason and "not mapped" in out.reason
    assert "polynomial" not in R.MODES


# ── one mode, three lists, and no ninth tool ─────────────────────────────────────────────────────────────────────────
def test_the_mode_is_in_every_list_of_modes():
    (verify_tool,) = [t for t in tool_registry.REGISTRY if t.name == "verify"]
    enum = verify_tool.schema["properties"]["mode"]["enum"]
    assert D._MATH_MODES["polynomial"] is M.polynomial_claim
    assert set(D._MATH_MODES) == schema._MATH_MODES == set(enum) and len(enum) == len(set(enum)) == 11
    assert len(tool_registry.REGISTRY) == 8


def test_the_helper_is_no_verify_function_so_unreached_counts_as_it_did():
    names = [n.name for n in ast.parse(inspect.getsource(M)).body if isinstance(n, ast.FunctionDef) and n.name.startswith("verify_")]
    assert sorted(names) == sorted(f"verify_{mode}" for mode in ("equality", "derivative", "integral", "limit", "solve", "inequality", "set_algebra", "calc_chain", "numeric", "number_theory", "system"))


def test_a_step_may_name_the_mode_and_a_packet_its_fields():
    step = {"id": "a", "domain": "mathematics", "spec": {"mode": "polynomial", "params": dict(WHOLE)}}
    assert schema.validate_steps([step]) == []
    packet = {"id": "b", "domain": "mathematics", "spec": {"MATH_VERIFY": dict(WHOLE)}}
    assert schema.validate_steps([packet]) == []
    assert "polynomial" in schema.schema_for("mathematics")["forms"][0]["shape"]["mode"]
    fields = schema._analyse("concordance.verifiers.mathematics")["input_fields"]
    assert {"generators", "ring"} <= set(fields)


def test_the_verdict_arrives_as_a_step_does():
    step = {"id": "a", "domain": "mathematics", "spec": {"mode": "polynomial", "params": spec("QQ [x, y] gcd [y - x, x - y] = x + y")}}
    out = D.verify_derivation([step])
    assert out["verdict"] == B


# ── what leaves ──────────────────────────────────────────────────────────────────────────────────────────────────────
def _plain_only(value):
    if isinstance(value, dict):
        return all(type(k) is str and _plain_only(v) for k, v in value.items())
    if isinstance(value, list):
        return all(map(_plain_only, value))
    return type(value) in (str, int, float, bool, type(None))


@pytest.mark.parametrize("row", ["QQ [x, y] gcd [y - x, x - y] = x - y", "QQ [x, y] gcd [y - x, x - y] = x + y", "ZZ [x] lcm [0, x] = 0", "QQ [x] gcd [1/x, x] = 1"])
def test_a_result_is_plain_data_so_it_crosses_the_wall_as_it_is(row):
    made = M.polynomial_claim(spec(row))
    assert _plain_only(made.data) and type(made.detail) is str and type(made.status) is str
    json.dumps(made.data)
    got = cells._read(pickle.dumps(cells._plain(made), protocol=pickle.HIGHEST_PROTOCOL))
    assert (got.name, got.status, got.detail, got.data) == (made.name, made.status, made.detail, made.data)
    assert pickle.loads(pickle.dumps(D._MATH_MODES["polynomial"])) is M.polynomial_claim


def test_the_data_holds_the_computed_answer_and_what_was_claimed():
    got = M.polynomial_claim(spec("QQ [x] gcd [x**2 - 1, x - 1] = x + 1"))
    assert got.status == "MISMATCH"
    assert got.data["actual"] == "x - 1" and got.data["claimed"] == "x + 1" and got.data["ring"] == "QQ" and got.data["generators"] == ["x"]


def test_a_claim_reads_nothing_it_did_not_state_and_leaves_its_spec_as_it_was():
    params = spec("QQ [y, x] gcd [y - x, x - y] = x - y")
    before = copy.deepcopy(params)
    first, second = M.polynomial_claim(params), M.polynomial_claim(params)
    assert params == before and first == second


REASONS = {
    "generators": ("state generators", "a list of names"),
    "ring": ("state ring", "'ZZ' or 'QQ'"),
    "gcd": ("state gcd or lcm", "a list of two or more polynomial texts", "claimed_gcd or claimed_lcm"),
}


@pytest.mark.parametrize("field,words", REASONS.items())
def test_the_reason_says_what_to_state(field, words):
    got = detail({k: v for k, v in WHOLE.items() if k != field})
    assert all(w in got for w in words), got


@pytest.mark.parametrize("row,words", [
    ("QQ [x] gcd [x*y - x*z, x*z - x*y] = x*y - x*z", ("x*y - x*z is no polynomial in x over QQ", "name every symbol in generators")),
    ("QQ [x] gcd [sin(x), x] = 1", ("sin(x) is no polynomial in x over QQ", "powers")),
    ("ZZ [x] gcd [x, x] = x/2", ("x/2 is no polynomial in x over ZZ", "coefficients in the ring")),
    ("RR [x] gcd [x, x] = x", ("state ring", "RR")),
])
def test_the_reason_names_what_it_could_not_read(row, words):
    got = detail(spec(row))
    assert all(w in got for w in words), got


def test_a_long_text_leaves_the_reason_whole():
    long = " + ".join(["sin(x)"] * 200)
    for params in ({"gcd": [long, "x"], "claimed_gcd": "1"}, {"gcd": ["x", "x"], "claimed_gcd": long}):
        got = detail({**params, "generators": ["x"], "ring": "QQ"})
        assert len(got) < 300 and got.endswith("name every symbol in generators"), got


# ── the record ───────────────────────────────────────────────────────────────────────────────────────────────────────
def _bullet():
    text = (ROOT / "MEASURED.md").read_text(encoding="utf-8")
    start = text.index("- **Mode number_theory, and the polynomial mode.**")
    return re.sub(r"\s+", " ", text[start:text.index("- **gcd and lcm, by symbol order.**", start)])


def test_every_row_the_record_quotes_is_a_row_here():
    quoted = set(re.findall(r"`((?:ZZ|QQ) \[[^`]+\] (?:gcd|lcm) \[[^`]+\] = [^`]+)`", _bullet()))
    assert len(quoted) >= 5 and quoted <= {row for row, _want in PLAN_ROWS + MORE}, quoted


def test_the_record_says_what_the_mode_does_and_what_it_does_not():
    bullet = _bullet()
    for words in ("`polynomial_claim`", "plus or minus one over ZZ, any nonzero rational over QQ", "zero equals only zero", "every symbol must be a named generator",
                  "no benchmark case reaches this mode", "`tools/unreached.py` does not see it", "`tests/test_polynomial_mode.py`", "an allow-list on its syntax tree",
                  "Rings beyond ZZ and QQ", "a text whose value is a polynomial and whose form is not", "x/x", "a Tuple", "an equation", "a matrix", "a float",
                  "the window", "plain data"):
        assert words in bullet, words


CHANGELOG_WORDS = ("A polynomial claim that states its ring and generators can be read", "mode polynomial", "up to a unit", "gcd(x**2 - 1, x - 1)")


def test_the_changelog_says_what_the_mode_reads():
    unreleased = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").split("## Unreleased", 1)[1].split("\n## ", 1)[0]
    flat = re.sub(r"\s+", " ", unreleased)
    assert [words for words in CHANGELOG_WORDS if words not in flat] == []
