"""Mode number_theory reads a number as the exact integer it writes (run 2026-11-04-gcd-lcm-order, step number-theory).

verify_number_theory read every value with int(), which drops a fraction and takes a bool for 1, walked a text digit by
digit, took anything for claimed_prime by its truth, and read one claim of two. So {factorial: 5.9, claimed_factorial: 120}
read HOLDS, as did {gcd: '24', claimed_gcd: 2}. Each value now goes through one helper. Every row of PLAN_ROWS is the plan's
EXACT INTEGERS (ledger line 167), exactly; a row that reads otherwise changes only by replan. Names the fix adds are read
inside the tests, so the file collects at the step's base.
"""
from __future__ import annotations

import copy
import itertools
import re
from pathlib import Path

import pytest

from concordance.derivation import verify, verify_math
from concordance.verifiers import mathematics as M

pytestmark = pytest.mark.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
I, H, B, E = "INCOMPLETE", "HOLDS", "BROKEN", "SYSTEM_ERROR"


def read(params):
    return verify({"mode": "number_theory", "params": copy.deepcopy(params)})


def computed(params):
    return verify_math({"mode": "number_theory", "params": copy.deepcopy(params)})["data"]


def verdict(params):
    return read(params)["verdict"]


def detail(params):
    return read(params)["trail"][0]["detail"]


MALFORMED = (
    {"gcd": [12.7, 18], "claimed_gcd": 6},
    {"lcm": [4.2, 6], "claimed_lcm": 12},
    {"factorial": 5.9, "claimed_factorial": 120},
    {"is_prime": 17.5, "claimed_prime": True},
    {"modulo": [17.9, 5], "claimed_modulo": 2},
    {"binomial": [5.5, 2], "claimed_binomial": 10},
    {"gcd": [True, 2], "claimed_gcd": 1},
    {"is_prime": 17, "claimed_prime": "false"},
    {"is_prime": 17, "claimed_prime": "no"},
    {"is_prime": 17, "claimed_prime": 0.5},
    {"gcd": "24", "claimed_gcd": 2},
    {"lcm": "46", "claimed_lcm": 12},
    {"binomial": "52", "claimed_binomial": 10},
    {"modulo": "72", "claimed_modulo": 1},
    {"gcd": {"1": 0, "2": 0}, "claimed_gcd": 1},
    {"binomial": [5, 2, 99], "claimed_binomial": 10},
    {"modulo": [17, 5, 99], "claimed_modulo": 2},
    {"binomial": [5, 2, 7.5], "claimed_binomial": 10},
    {"modulo": [17, 5, "x"], "claimed_modulo": 2},
    {"gcd": [12, 18], "claimed_gcd": 6, "lcm": [4, 6], "claimed_lcm": 99},
)
FALSE = (
    {"gcd": [12, 18], "claimed_gcd": 6.9},
    {"factorial": 5, "claimed_factorial": 120.5},
)
HOLDING = (
    {"gcd": [12, 18], "claimed_gcd": 6},
    {"gcd": [12.0, 18], "claimed_gcd": 6},
    {"gcd": ["12", 18], "claimed_gcd": 6},
    {"lcm": [4, 6], "claimed_lcm": 12},
    {"factorial": 5, "claimed_factorial": 120},
    {"modulo": [17, 5], "claimed_modulo": 2},
    {"binomial": [5, 2], "claimed_binomial": 10},
    {"is_prime": 17, "claimed_prime": True},
)
PLAN_ROWS = tuple((row, want) for rows, want in ((MALFORMED, E), (FALSE, B), (HOLDING, H)) for row in rows)


@pytest.mark.parametrize("params,want", PLAN_ROWS, ids=str)
def test_each_expected_reading(params, want):
    assert verdict(params) == want


def test_the_table_is_the_plans():
    assert (len(MALFORMED), len(FALSE), len(HOLDING)) == (20, 2, 8)


@pytest.mark.parametrize("params", MALFORMED, ids=str)
def test_every_breach_reads_through_the_malformed_path(params):
    assert detail(params).startswith("malformed number-theory input")


@pytest.mark.parametrize("params,answer,claimed", [
    ({"gcd": [12, 18], "claimed_gcd": 6.9}, 6, 6.9),
    ({"factorial": 5, "claimed_factorial": 120.5}, 120, 120.5),
    ({"lcm": [4, 6], "claimed_lcm": 11.5}, 12, 11.5),
    ({"binomial": [5, 2], "claimed_binomial": 10.25}, 10, 10.25),
    ({"modulo": [17, 5], "claimed_modulo": 1.5}, 2, 1.5),
    ({"gcd": [12, 18], "claimed_gcd": "6.9"}, 6, "6.9"),       # a fraction written as a text is the same number
])
def test_a_claimed_fraction_is_a_number_the_answer_is_not(params, answer, claimed):
    assert verdict(params) == B
    assert computed(params)["actual"] == answer and computed(params)["claimed"] == claimed


@pytest.mark.parametrize("params,want", [
    ({"gcd": [12, 18], "claimed_gcd": 6.0}, H),                 # a float with no fraction is the integer it writes
    ({"gcd": [12, 18], "claimed_gcd": "6"}, H),
    ({"gcd": [12, 18], "claimed_gcd": " 6 "}, H),
    ({"gcd": [-12, 18], "claimed_gcd": 6}, H),
    ({"factorial": "5", "claimed_factorial": 120}, H),
    ({"factorial": 5.0, "claimed_factorial": 120}, H),
    ({"is_prime": "17", "claimed_prime": True}, H),
    ({"is_prime": 18.0, "claimed_prime": False}, H),
    ({"modulo": ["17", 5.0], "claimed_modulo": "2"}, H),
    ({"binomial": [5.0, "2"], "claimed_binomial": 10.0}, H),
    ({"gcd": [12, 18], "claimed_gcd": 5}, B),
    ({"gcd": [12, 18], "claimed_gcd": 5.0}, B),
    ({"is_prime": 17, "claimed_prime": False}, B),
    ({"is_prime": 18, "claimed_prime": True}, B),
])
def test_an_integer_reads_as_it_did_however_it_is_written(params, want):
    assert verdict(params) == want


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan"), True, False, None, [12], {"n": 12}, "x", "", "12.0",
                                   "1e3", "1/2", "0x10"], ids=repr)
def test_what_is_no_integer_is_refused_in_each_place(value):
    for params in ({"gcd": [value, 18], "claimed_gcd": 6}, {"lcm": [value, 6], "claimed_lcm": 12}, {"factorial": value, "claimed_factorial": 1},
                   {"is_prime": value, "claimed_prime": True}, {"modulo": [value, 5], "claimed_modulo": 2},
                   {"modulo": [17, value], "claimed_modulo": 2}, {"binomial": [value, 2], "claimed_binomial": 10},
                   {"binomial": [5, value], "claimed_binomial": 10}):
        assert verdict(params) == E, params


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan"), True, False, None, [6], {"n": 6}, "x", "", "1/2", "6.0", "inf", "nan"],
                         ids=repr)
def test_a_claimed_value_that_is_no_number_says_nothing(value):
    """A bool was read as 1, so {gcd: [1, 1], claimed_gcd: true} read HOLDS, and an infinity raised past the malformed path."""
    for params in ({"gcd": [12, 18], "claimed_gcd": value}, {"gcd": [1, 1], "claimed_gcd": value}, {"lcm": [4, 6], "claimed_lcm": value},
                   {"factorial": 5, "claimed_factorial": value}, {"modulo": [17, 5], "claimed_modulo": value},
                   {"binomial": [5, 2], "claimed_binomial": value}):
        assert verdict(params) == E, params
        assert detail(params).startswith("malformed number-theory input"), params


@pytest.mark.parametrize("value", [1, 0, 1.0, "true", "True", None, [True]], ids=repr)
def test_claimed_prime_must_be_a_real_boolean(value):
    assert verdict({"is_prime": 17, "claimed_prime": value}) == E


@pytest.mark.parametrize("params", [
    {"gcd": 12, "claimed_gcd": 12}, {"lcm": 12, "claimed_lcm": 12}, {"gcd": None, "claimed_gcd": 1}, {"gcd": (12, 18), "claimed_gcd": 6},
    {"lcm": {"4": 0, "6": 0}, "claimed_lcm": 12}, {"binomial": [5], "claimed_binomial": 1}, {"binomial": [], "claimed_binomial": 1},
    {"modulo": [17], "claimed_modulo": 2}, {"modulo": [], "claimed_modulo": 2}, {"binomial": (5, 2), "claimed_binomial": 10},
    {"modulo": {"17": 0, "5": 0}, "claimed_modulo": 2}, {"gcd": [12], "claimed_gcd": 12}, {"gcd": [], "claimed_gcd": 0},
], ids=str)
def test_a_list_field_is_a_list_and_a_pair_is_two(params):
    assert verdict(params) == E


@pytest.mark.parametrize("one,other", itertools.combinations((HOLDING[0], *HOLDING[3:]), 2), ids=str)
def test_a_spec_holds_one_claim_whichever_two_it_holds(one, other):
    assert verdict({**one, **other}) == E


@pytest.mark.parametrize("params,want", [
    ({"gcd": [12, 18], "claimed_gcd": 6, "lcm": [4, 6]}, H),            # no claimed value beside it, so no second claim
    ({"gcd": [12, 18], "claimed_gcd": 6, "claimed_lcm": 99}, H),
    ({"gcd": [12, 18], "claimed_lcm": 36}, I),                          # no claim at all, as before
    ({"gcd": [12, 18]}, I),
])
def test_a_key_with_no_partner_is_no_claim(params, want):
    assert verdict(params) == want


def test_a_packet_reads_the_same_way():
    def packet(**fields):
        return verify({"MATH_VERIFY": {"expr_a": "1", "expr_b": "1", **fields}})["verdict"]
    assert packet(gcd=[12.7, 18], claimed_gcd=6) == E
    assert packet(gcd=[12, 18], claimed_gcd=6.9) == B
    assert packet(gcd=[12, 18], claimed_gcd=6) == H


# ── what this step did not close ─────────────────────────────────────────────────────────────────────────────────────
# MISS 10: the domain number_theory has its own reads, and a request number through int() across the verifier files is a
# run of its own. Each of these is false or says nothing, and read HOLDS when this step closed. That run, 2026-11-11-exact-
# integers (step fix-a2), flips the table: the domain reads its numbers by THE RULE (verifiers/_integer.py), so a fraction
# in an input reads SYSTEM_ERROR and one in a claimed value BROKEN. The fourth row is not an integer read: claimed_prime is
# read by its truth, so the text 'false' still reads HOLDS, a miss of its own.
DOMAIN_ROWS = (
    ({"gcd_a": 48.7, "gcd_b": 36, "claimed_gcd": 12}, E),
    ({"gcd_a": 48, "gcd_b": 36, "claimed_gcd": 12.9}, B),
    ({"n_prime": 137.5, "claimed_prime": True}, E),
    ({"n_prime": 137, "claimed_prime": "false"}, H),
    ({"factorial_n": 5.9, "claimed_factorial": 120}, E),
)


@pytest.mark.parametrize("artifact,want", DOMAIN_ROWS, ids=str)
def test_the_named_miss_the_domain_number_theory_reads_them_by_the_rule(artifact, want):
    assert verify({"NUM_VERIFY": artifact}, domain="number_theory")["verdict"] == want


# ── the record ───────────────────────────────────────────────────────────────────────────────────────────────────────
def _bullet():
    text = (ROOT / "MEASURED.md").read_text(encoding="utf-8")
    start = text.index("- **Mode number_theory, and the polynomial mode.**")
    return re.sub(r"\s+", " ", text[start:text.index("- **gcd and lcm, by symbol order.**", start)])


def test_the_record_says_what_was_found_and_names_the_miss():
    bullet = _bullet()
    for words in ("drops a fraction", "digit by digit", "one claim of two", "`tests/test_number_theory_mode.py`", "through the malformed path",
                  "a number the answer is not", "must be a real boolean", "a spec holds one claim", "Mode number_theory is closed and the domain number_theory is not",
                  "through NUM_VERIFY", "a run of its own"):
        assert words in bullet, words
    for row in ("{factorial: 5.9, claimed_factorial: 120}", "{gcd: '24', claimed_gcd: 2}", "{gcd_a: 48.7, gcd_b: 36, claimed_gcd: 12}",
                "{gcd_a: 48, gcd_b: 36, claimed_gcd: 12.9}", "{n_prime: 137.5, claimed_prime: true}", "{n_prime: 137, claimed_prime: 'false'}",
                "{factorial_n: 5.9, claimed_factorial: 120}"):
        assert row in bullet, row


CHANGELOG_WORDS = ("Mode number_theory reads a number as the exact integer it writes", "{factorial: 5.9, claimed_factorial: 120}", "{gcd: '24', claimed_gcd: 2}",
                   "reads SYSTEM_ERROR where it read HOLDS", "{gcd: [12, 18], claimed_gcd: 6.9} reads BROKEN", "on a fraction dropped from a number")


def test_the_changelog_says_which_claims_moved():
    unreleased = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").split("## Unreleased", 1)[1].split("\n## ", 1)[0]
    flat = re.sub(r"\s+", " ", unreleased)
    assert [words for words in CHANGELOG_WORDS if words not in flat] == []


def test_the_helper_has_no_second_door():
    """Every read of a value in verify_number_theory goes through the helpers: int( appears only on what they returned."""
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(M))
    (fn,) = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "verify_number_theory"]
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "int"]
    assert all(not any(isinstance(sub, ast.Name) and sub.id == "spec" for sub in ast.walk(call)) for call in calls)
