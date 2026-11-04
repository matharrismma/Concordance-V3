"""Text from a request is never evaluated, proved through the real route.

One named test per input class, each sent through http_api.route with seal 0 (equality mode for mathematics), each
input inert: it can only set a marker in this test process or print to this test's stdout. Each test observes the
reach itself: the marker in sys.__dict__, the bytes print wrote (a patched builtin could not see them, because
sympy's parser copies only the real builtin functions), or, for a compute limit, the verdict the evaluated power
reads.

This file imports nothing the fix adds, so every test here collects at the step's base and is red there by its own
assertion. Each also runs under the tripwire: no str reaches sympy's string parser while the route is read.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from concordance import http_api  # noqa: E402
from parse_tripwire import tripwire  # noqa: E402

MARKER = "v3_parse_route_marker"
SETS_MARKER = f"__import__('sys').__dict__.__setitem__('{MARKER}', 1)"   # evaluated, it sets one key in this process
JOINED_BIN = "sin((b\nin\n(5)))"           # with its line breaks a comparison; with them dropped a refused call
JOINED_PRINT = "Matrix(1,1,pr\nin\nt)"     # the same, reaching a function that writes to this test's stdout
CALLABLE_VALUE = "Matrix(1,1,print)"       # a refused function handed over as a value, never named in a call
CALLABLE_KEYWORD = "simplify(sin(x)**2+cos(x)**2,measure=print)"
CARET_POWER = "2^20000"                    # a power spelled so that the exponent limit did not see it
BASE_NESTED_POWER = "(2**1000)**2000"      # each exponent small, the base already large
ROOT_ON_THE_BASE = "((2**1000+1)**(1/2))**10000"   # the base shows no integer; sympy multiplies the exponents out
ROOT_IN_POW = "Pow(sqrt(2**1000+1),10000)"         # the same through the function spelling


@pytest.fixture(autouse=True)
def _no_marker():
    sys.__dict__.pop(MARKER, None)
    yield
    sys.__dict__.pop(MARKER, None)


def _ledger() -> dict:
    return json.loads(http_api.route("GET", "/ledger/verify", {}, {}, {}, b"")[2])


def _post(domain: str, spec: dict) -> dict:
    body = {"steps": [{"id": "r", "domain": domain, "spec": spec}]}
    status, _headers, out = http_api.route("POST", "/verify", {"seal": ["0"]}, body, {}, b"")
    assert status == 200, out
    return json.loads(out)


def _held(capsys, domain: str, spec: dict) -> None:
    before = _ledger()
    capsys.readouterr()
    with tripwire() as hits:
        r = _post(domain, spec)
    out = capsys.readouterr().out
    assert MARKER not in sys.__dict__, "the input was evaluated: the marker is set"
    assert out == "", f"the refused function was reached: {out!r}"
    assert r.get("verdict") not in ("HOLDS", "BROKEN"), f"the input was read: {r.get('verdict')}"
    assert not r.get("seal"), "a seal was written"
    assert _ledger() == before, "the ledger moved"
    assert hits == [], f"text reached sympy's string parser: {hits!r}"


def _equality(capsys, expr_a: str, expr_b: str) -> None:
    _held(capsys, "mathematics", {"mode": "equality", "params": {"expr_a": expr_a, "expr_b": expr_b}})


def _physics(capsys, equation: str, symbols: dict) -> None:
    _held(capsys, "physics", {"PHYS_VERIFY": {"equation": equation, "symbols": symbols}})


def test_physics_equation_text_is_not_evaluated(capsys):
    _physics(capsys, f"x = {SETS_MARKER}", {"x": "m"})


def test_physics_unit_text_is_not_evaluated(capsys):
    _physics(capsys, "x = x", {"x": SETS_MARKER})


def test_joined_lines_read_as_a_refused_call_in_equality(capsys):
    _equality(capsys, JOINED_BIN, "sin(5)")


def test_joined_lines_reach_a_refused_function_in_equality(capsys):
    _equality(capsys, JOINED_PRINT, "1")


def test_joined_lines_read_as_a_refused_call_in_a_physics_equation(capsys):
    _physics(capsys, f"x = {JOINED_BIN}", {"x": "m"})


def test_joined_lines_reach_a_refused_function_in_a_physics_equation(capsys):
    _physics(capsys, f"x = {JOINED_PRINT}", {"x": "m"})


def test_joined_lines_read_as_a_refused_call_in_a_physics_unit(capsys):
    _physics(capsys, "x = x", {"x": JOINED_BIN})


def test_joined_lines_reach_a_refused_function_in_a_physics_unit(capsys):
    _physics(capsys, "x = x", {"x": JOINED_PRINT})


def test_caret_power_passes_no_limit_in_equality(capsys):
    _equality(capsys, CARET_POWER, CARET_POWER)


def test_base_nested_power_passes_no_limit_in_equality(capsys):
    _equality(capsys, BASE_NESTED_POWER, BASE_NESTED_POWER)


def test_caret_power_passes_no_limit_in_a_physics_equation(capsys):
    _physics(capsys, f"x = x*{CARET_POWER}/{CARET_POWER}", {"x": "m"})


def test_base_nested_power_passes_no_limit_in_a_physics_equation(capsys):
    _physics(capsys, f"x = x*{BASE_NESTED_POWER}/{BASE_NESTED_POWER}", {"x": "m"})


def test_root_on_the_base_side_passes_no_limit_in_equality(capsys):
    _equality(capsys, ROOT_ON_THE_BASE, ROOT_ON_THE_BASE)


def test_root_in_the_function_spelling_passes_no_limit_in_equality(capsys):
    _equality(capsys, ROOT_IN_POW, ROOT_IN_POW)


def test_root_on_the_base_side_passes_no_limit_in_a_physics_equation(capsys):
    _physics(capsys, f"x = x*{ROOT_ON_THE_BASE}/{ROOT_ON_THE_BASE}", {"x": "m"})


def test_root_on_the_base_side_passes_no_limit_in_a_physics_unit(capsys):
    _physics(capsys, "x = x", {"x": ROOT_ON_THE_BASE})


def test_callable_value_reaches_nothing_in_equality(capsys):
    _equality(capsys, CALLABLE_VALUE, CALLABLE_VALUE)


def test_callable_value_reaches_nothing_in_a_physics_equation(capsys):
    _physics(capsys, f"x = {CALLABLE_VALUE}", {"x": "m"})


def test_callable_value_reaches_nothing_in_a_physics_unit(capsys):
    _physics(capsys, "x = x", {"x": CALLABLE_VALUE})


def test_callable_keyword_reaches_nothing_in_equality(capsys):
    _equality(capsys, CALLABLE_KEYWORD, "1")
