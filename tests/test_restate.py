"""Measurement 4 of the TRM report, step restate-registry (run 2026-11-03-restatement-audit): the restatements R1-R5
of tools/restate.py, each judged by an oracle that calls no verifier.

These tests pin that the registry is fixed and named; that each restatement changes the bytes on worked examples,
never mutates its input, gives the same output every time (here, and in a fresh interpreter under another hash
seed) and declines, with its reason, where it must; that each oracle refuses planted meaning changes, among them
R4's two known mistakes (x renamed with the defaulted variable left in place, and a rename to E, with the other
names sympy reads as something else) and checker-28's finding (a symbol named by a string, Symbol('x'), which a
rename of the bare names does not reach), each refused by the oracle on its own, never by the verifier's guard;
that the first mistake really changes a verdict; that R4's tables and the readings R2-R5 copy from the engine
match mathematics.py and derivation.py, read as text and never imported; that neither the restatements nor their
oracles load concordance.verifiers; and that no module under src/ imports or loads tools/restate.py or
tools/restatement_audit.py.

The worked examples are the benchmark's own claims (tools/benchmark.py's CLAIMS, cited per row), the lighthouse
rows and docstrings named beside them, and the derivation tier's listings (tests/fixtures/derivation_tier.py);
the rest are small inputs written to reach one decline each.

The tool is loaded inside each test that uses it, never at module level, so with it absent every one of those reads
red. The tests that pin the engine's text (the readings the restatements copy), the sources of the examples and
src/'s isolation from the tools do not use it, and pass without it by design.
"""
from __future__ import annotations

import ast
import copy
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import MappingProxyType

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "restate.py"
FIXTURES = ROOT / "tests" / "fixtures"
MATH = ROOT / "src" / "concordance" / "verifiers" / "mathematics.py"
DERIVATION = ROOT / "src" / "concordance" / "derivation.py"


def _tool():
    spec = importlib.util.spec_from_file_location("restate", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tier():
    if str(FIXTURES) not in sys.path:
        sys.path.insert(0, str(FIXTURES))
    import derivation_tier
    return derivation_tier


# the benchmark's own spec builders (tools/benchmark.py eq, iq, dv) and the one step derivation.verify makes of a spec
def _eq(a, b):
    return {"mode": "equality", "params": {"expr_a": a, "expr_b": b, "variables": {}}}


def _iq(lhs, rhs, op):
    return {"mode": "inequality", "params": {"lhs": lhs, "rhs": rhs, "op": op, "variables": {}}}


def _dv(f, v, d):
    return {"mode": "derivative", "params": {"function": f, "variable": v, "claimed_derivative": d}}


def _claim(spec):
    return [{"id": "b", "domain": "mathematics", "spec": spec}]


# rows of tools/benchmark.py CLAIMS (test_the_examples_are_the_benchmarks_own checks each is there, as labelled)
PYTHAGORAS = (True, _eq("sin(x)**2+cos(x)**2", "1"))
SQUARES = (True, _eq("(x-1)*(x+1)", "x**2-1"))
EULER = (True, _eq("exp(I*pi)+1", "0"))
SQUARE_TRAP = (False, _iq("(x-3)**2", "0", ">"))
SINE_TRAP = (False, _iq("sin(x)", "0.9999", "<="))
CUBE = (True, _dv("t**3", "t", "3*t**2"))
# lighthouse 7df6039c7705 (data/benchmark_lighthouse_v2.jsonl), in the {mode, params} form tools/benchmark.py makes
SOLVE = {"mode": "solve", "params": {"equation": "x**2 - 4", "variable": "x", "claimed_solutions": ["2", "-2"]}}
# verify_system's docstring (mathematics.py)
SYSTEM = {"mode": "system", "params": {"equations": ["x + y = 3", "x - y = 1"], "variables": ["x", "y"],
                                       "claimed_solution": {"x": 2, "y": 1}}}
# the names the plan says sympify reads as something else, never a new name
NOT_PLAIN = ("E", "I", "N", "S", "O", "Q", "beta", "gamma", "zeta", "pi")
# checker-28's finding (round 1): an equality whose x is named twice, once bare and once by a string, and the rename
# of the bare names alone, which changes it (sympy reads 0, then v0 - x; for the derivative 2*x, then 0)
STRING_NAMED = (
    (("x - Symbol('x')", "0"), ("v0 - Symbol('x')", "0")),
    (("x - S('x')", "0"), ("v0 - S('x')", "0")),
    (("x - symbols('x')", "0"), ("v0 - symbols('x')", "0")),
    (("Derivative(Symbol('x')**2, x)", "2*x"), ("Derivative(Symbol('x')**2, v0)", "2*v0")),
)


def _eqv(a, b):
    """An equality with variables [], as checker-28 gave its inputs."""
    return {"mode": "equality", "params": {"expr_a": a, "expr_b": b, "variables": []}}


def _ren(s, old, new):
    return re.sub(rf"\b{old}\b", new, s)


def _wire(obj):
    return json.dumps(obj, ensure_ascii=False)


def _bound_equalities():
    """Two equalities, the second binding its expr_b from the first: neither may be restated alone."""
    return [{"id": "a", "domain": "mathematics", "spec": _eq("2+2", "4")},
            {"id": "b", "domain": "mathematics", "bind": {"params.expr_b": "a.actual"}, "spec": _eq("4", "0")}]


# ── the worked examples: name -> (key, subject, the check on the restated subject) ─────────────────────────────
def _params(after, i=0):
    return after[i]["spec"]["params"]


def _mutables(obj, out=None):
    """The ids of every dict and list in obj."""
    out = set() if out is None else out
    if isinstance(obj, (dict, list)):
        out.add(id(obj))
        for v in (obj.values() if isinstance(obj, dict) else obj):
            _mutables(v, out)
    elif isinstance(obj, tuple):
        for v in obj:
            _mutables(v, out)
    return out


def _keys_reversed(before, after):
    if isinstance(before, dict):
        assert list(after) == list(reversed(list(before)))
        for k in before:
            _keys_reversed(before[k], after[k])
    elif isinstance(before, (list, tuple)):
        assert type(after) is type(before)
        for b, a in zip(before, after):
            _keys_reversed(b, a)


def _applied():
    T = _tier()
    num, rect = T.num, T.rect
    return {
        # R1: every object's keys reversed at every depth, the values and their types kept
        "R1 a geometry chain": ("R1", T.ORDER_FREE["true chain"], lambda b, a: _keys_reversed(b, a)),
        "R1 a document": ("R1", T.COMPOSE_DOC, lambda b, a: _keys_reversed(b, a)),
        "R1 a tuple stays a tuple": (
            "R1", [{"id": "a", "domain": "geometry", "spec": {"K": {"t": (1, 2), "u": 3}}}],
            lambda b, a: (_keys_reversed(b, a), isinstance(a[0]["spec"]["K"]["t"], tuple))[1]),
        # R2: the sides exchanged, nothing else
        "R2 difference of squares": ("R2", _claim(SQUARES[1]), lambda b, a: _params(a) == {
            "expr_a": "x**2-1", "expr_b": "(x-1)*(x+1)", "variables": {}}),
        "R2 the second step of GAP_DEPENDENCY": ("R2", T.GAP_DEPENDENCY, lambda b, a: (
            a[0] == b[0] and _params(a, 1) == {"expr_a": "2*x", "expr_b": "x + x", "variables": ["x"]})),
        # R3: one space between every two tokens; '**', 1e5 and every name stay whole
        "R3 the Pythagorean identity": ("R3", _claim(PYTHAGORAS[1]), lambda b, a: (
            _params(a)["expr_a"] == "sin ( x ) ** 2 + cos ( x ) ** 2" and _params(a)["expr_b"] == "1")),
        "R3 1e5 and a name kept whole": ("R3", _claim(_eq("1e5*alpha", "100000*alpha")), lambda b, a: (
            _params(a)["expr_a"] == "1e5 * alpha" and _params(a)["expr_b"] == "100000 * alpha")),
        "R3 lighthouse solve": ("R3", _claim(SOLVE), lambda b, a: _params(a) == {
            "equation": "x ** 2  -  4", "variable": "x", "claimed_solutions": ["2", "- 2"]}),
        "R3 system, split at '='": ("R3", _claim(SYSTEM), lambda b, a: (
            _params(a)["equations"] == ["x  +  y = 3", "x  -  y = 1"]
            and _params(a)["claimed_solution"] == {"x": 2, "y": 1})),
        # R4: every free symbol and every symbol-naming parameter renamed alike; functions and constants kept
        "R4 d/dt t^3": ("R4", _claim(CUBE[1]), lambda b, a: _params(a) == {
            "function": "v0**3", "variable": "v0", "claimed_derivative": "3*v0**2"}),
        "R4 the (x-3)^2 trap, its default variable written in": ("R4", _claim(SQUARE_TRAP[1]), lambda b, a: (
            _params(a) == {"lhs": "(v0-3)**2", "rhs": "0", "op": ">", "variables": {}, "variable": "v0"}
            and list(_params(a))[-1] == "variable")),
        "R4 the Pythagorean identity keeps sin and cos": ("R4", _claim(PYTHAGORAS[1]), lambda b, a: (
            _params(a) == {"expr_a": "sin(v0)**2+cos(v0)**2", "expr_b": "1", "variables": {}})),
        "R4 system, claimed_solution keys renamed": ("R4", _claim(SYSTEM), lambda b, a: _params(a) == {
            "equations": ["v0 + v1 = 3", "v0 - v1 = 1"], "variables": ["v0", "v1"],
            "claimed_solution": {"v0": 2, "v1": 1}}),
        "R4 lighthouse solve": ("R4", _claim(SOLVE), lambda b, a: _params(a) == {
            "equation": "v0**2 - 4", "variable": "v0", "claimed_solutions": ["2", "-2"]}),
        "R4 new names skip a name the claim holds": ("R4", _claim(_eq("x + v0", "v0 + x")), lambda b, a: (
            _params(a)["expr_a"] == "v1 + v2" and _params(a)["expr_b"] == "v2 + v1")),
        "R4 pi kept, x renamed, variables mapped": (
            "R4", [{"id": "b", "domain": "mathematics", "spec": {"mode": "equality", "params": {
                "expr_a": "pi*x", "expr_b": "x*pi", "variables": ["x"]}}}],
            lambda b, a: _params(a) == {"expr_a": "pi*v0", "expr_b": "v0*pi", "variables": ["v0"]}),
        # R5: ids renamed by str(id), a falsy id read as s{i} and made explicit, repeated ids alike
        "R5 DEFAULT_ID_COLLISION": ("R5", T.DEFAULT_ID_COLLISION, lambda b, a: (
            [s["id"] for s in a] == ["r0", "r0", "r1"] and "id" not in b[1]
            and a[2]["bind"] == {"GEOM_VERIFY.rect_length": "r0.actual_area"})),
        "R5 COMPOSE_DOC and its {step_id} text": ("R5", T.COMPOSE_DOC, lambda b, a: (
            a["text"] == "Par {r0}; P&I {r1}; DSCR {r2}." and [s["id"] for s in a["steps"]] == ["r0", "r1", "r2"]
            and a["steps"][1]["bind"] == {"PUBFIN_VERIFY.par": "r0.actual_par"}
            and a["steps"][2]["bind"] == {"RE_VERIFY.annual_debt_service": "r1.annual_pi"})),
        "R5 two carriers of s, listed as one object twice": (
            "R5", T.REPEATED["two s, m proof uses s"][0],
            lambda b, a: [s["id"] for s in a] == ["r0", "r0", "r1"] and a[2]["uses"] == ["r0"]),
        "R5 falsy ids and a missing reference": (
            "R5", [num(0, "2+2", 4), num("", "3+3", 6), num("c", "1+1", 2, uses=["s0", "s1", "z"])],
            lambda b, a: [s["id"] for s in a] == ["r0", "r1", "r2"] and a[2]["uses"] == ["r0", "r1", "z"]),
        "R5 a new id skips a reference already made": (
            "R5", [num("a", "2+2", 4, uses=["r0"])], lambda b, a: a[0]["id"] == "r1" and a[0]["uses"] == ["r0"]),
        "R5 a bound geometry pair": ("R5", [rect("a", 4, 6, 24), rect(None, None, 1, 24, bind=T.AREA)],
                                     lambda b, a: [s["id"] for s in a] == ["r0", "r1"]
                                     and a[1]["bind"] == {"GEOM_VERIFY.rect_length": "r0.actual_area"}),
    }


def _declined():
    T = _tier()
    many = lambda n: "+".join(["x"] * n)  # noqa: E731
    mv = [{"id": "g", "domain": "mathematics",
           "spec": {"MATH_VERIFY": {"expr_a": "x + x", "expr_b": "2*x", "variables": ["x"]}}}]
    return {
        "R1 one key everywhere": ("R1", [{"id": "a"}], "changes no byte"),
        "R1 not a derivation": ("R1", {"title": "t"}, "not a derivation"),
        "R1 no steps": ("R1", [], "no steps"),
        "R1 a step that is not an object": ("R1", [1, 2], "step 0 is not an object"),
        "R1 not JSON": ("R1", [{"id": "a", "spec": {"K": {1, 2}}}], "not JSON"),
        "R2 a derivative": ("R2", _claim(CUBE[1]), "mode 'derivative' is not equality"),
        "R2 two sides alike": ("R2", _claim(_eq("x", "x")), "the two sides parse alike"),
        "R2 a MATH_VERIFY packet": ("R2", mv, "MATH_VERIFY packet is dispatched by its keys"),
        "R2 geometry and numeric": ("R2", T.ORDER_FREE["true chain"], "not mathematics (steps 0, 1)"),
        "R2 a bound pair": ("R2", _bound_equalities(), "another step binds from it (step 0)"),
        "R2 a side that does not parse": ("R2", _claim(_eq("2x", "x+x")), "'2x' does not parse"),
        "R3 one token a side": ("R3", _claim(_eq("x", "1")), "it changes no byte of this step"),
        "R3 non-ASCII": ("R3", _claim(_eq("π*x", "x*π")), "non-ASCII"),
        "R3 near the size guard": ("R3", _claim(_eq(many(1500), "1500*x")), "within 10% of the 4000-character guard"),
        "R3 past the size guard": ("R3", _claim(_eq(many(2100), "2100*x")), "characters, past the 4000-character guard"),
        "R3 an equation holding ==": ("R3", _claim({"mode": "solve", "params": {
            "equation": "x**2 == 4", "variable": "x", "claimed_solutions": ["2", "-2"]}}), "holding '=='"),
        # verify_calc_chain's docstring example
        "R3 calc_chain": ("R3", _claim({"mode": "calc_chain", "params": {"calc_steps": ["16-3-4=9", "9*2=18"]}}),
                          "mode 'calc_chain' is not mapped"),
        "R3 a MATH_VERIFY packet": ("R3", mv, "MATH_VERIFY"),
        "R4 Euler's identity names no free symbol": ("R4", _claim(EULER[1]), "no free symbol to rename"),
        "R4 a field outside its table": ("R4", _claim({"mode": "derivative", "params": {
            "function": "x**2", "variable": "x", "claimed_derivative": "2*x", "true_derivative": "2*x"}}),
            "'true_derivative' is not a field R4 maps for mode derivative"),
        "R4 variables as a non-empty object": ("R4", _claim({"mode": "equality", "params": {
            "expr_a": "x + x", "expr_b": "2*x", "variables": {"x": "real"}}}), "non-empty object"),
        "R4 a name called and used as a symbol": ("R4", _claim(_eq("gamma(x) + gamma", "1")),
                                                  "'gamma' is both called and used as a symbol"),
        "R4 near the size guard": ("R4", _claim(_eq(many(1300), "1300*x")), "within 10%"),
        "R4 numeric is not mapped": ("R4", [T.num("a", "2+2", 4)], "mode 'numeric' is not mapped"),
        "R4 a bound pair": ("R4", _bound_equalities(), "it binds an input from another step (step 1)"),
        "R4 a MATH_VERIFY packet": ("R4", mv, "MATH_VERIFY"),
        # checker-28: a string, or a value a call or an attribute computes, can name a symbol a rename of the bare
        # names does not reach. R4 declines them itself, whatever the verifier's guard would do
        **{f"R4 {before[0]} (checker-28)": ("R4", _claim(_eqv(*before)), "holds a string ('x')")
           for before, _ in STRING_NAMED},
        "R4 a formatted string": ("R4", _claim(_eqv("x - Symbol(f'x')", "0")), "holds a formatted string"),
        "R4 a name a call computes": ("R4", _claim(_eqv("x - Symbol(chr(120))", "0")),
                                      "calls 'Symbol', which R4 cannot show takes no name from a string"),
        "R4 an attribute": ("R4", _claim(_eqv("x*S.Half", "x/2")), "holds an Attribute"),
        "R5 uses that is not a list": ("R5", [{"id": "a", "domain": "geometry", "uses": "a"}], "uses is not a list"),
        "R5 a bind reference that is not a string": (
            "R5", [{"id": "a", "domain": "geometry", "bind": {"P.x": 5}}], "not a string"),
        "R5 not a derivation": ("R5", "steps", "not a derivation"),
        "R5 no steps": ("R5", {"steps": []}, "no steps"),
    }


def _planted():
    """name -> (key, before, after, a fragment of the oracle's refusal): meaning changes an oracle must refuse."""
    T = _tier()

    def edit(before, fn):
        after = copy.deepcopy(before)
        fn(after)
        return after

    def params(fn, i=0):
        return lambda a: fn(a[i]["spec"]["params"])

    def setp(**kw):
        return params(lambda p: p.update(kw))

    def rename_x_to(new, *fields):
        return params(lambda p: p.update({f: _ren(p[f], "x", new) for f in fields}))

    def ids(*new):
        return lambda a: [s.update(id=n) for s, n in zip(a, new)]

    sq, sine, cube, pyth = (_claim(c[1]) for c in (SQUARE_TRAP, SINE_TRAP, CUBE, PYTHAGORAS))
    out = {
        # R1
        "R1 a value changed": ("R1", T.ORDER_FREE["true chain"],
                               edit(T.ORDER_FREE["true chain"], lambda a: a[0]["spec"]["GEOM_VERIFY"].update(
                                   claimed_rect_area=25)), "canonical_json_bytes differ"),
        "R1 a list made a tuple": ("R1", [{"id": "a", "spec": {"K": [1, 2]}}], [{"id": "a", "spec": {"K": (1, 2)}}],
                                   "canonical JSON cannot see it"),
        # R2
        "R2 swapped, and variables changed": ("R2", _claim(SQUARES[1]), edit(_claim(SQUARES[1]), setp(
            expr_a="x**2-1", expr_b="(x-1)*(x+1)", variables=["x"])), "a field other than the two sides changed"),
        "R2 a side altered": ("R2", _claim(SQUARES[1]), edit(_claim(SQUARES[1]), setp(
            expr_a="x**2+1", expr_b="(x-1)*(x+1)")), "not the two sides exchanged"),
        "R2 swapped, and the id changed": ("R2", _claim(SQUARES[1]), edit(_claim(SQUARES[1]), lambda a: (
            a[0].update(id="c"), a[0]["spec"]["params"].update(expr_a="x**2-1", expr_b="(x-1)*(x+1)"))),
            "changed outside its params"),
        "R2 a step another binds from": ("R2", _bound_equalities(), edit(_bound_equalities(), setp(
            expr_a="4", expr_b="2+2")), "another step binds from it"),
        # R3: never inside **, 1e5 or a name; only spaces, only between tokens; never near the size guard
        "R3 a space inside **": ("R3", _claim(_eq("x**2", "x*x")), edit(_claim(_eq("x**2", "x*x")), setp(
            expr_a="x* *2")), "'x* *2' does not parse"),
        "R3 a space inside 1e5": ("R3", _claim(_eq("1e5*x", "x*1e5")), edit(_claim(_eq("1e5*x", "x*1e5")), setp(
            expr_a="1 e5*x")), "'1 e5*x' does not parse"),
        "R3 a space inside a name": ("R3", _claim(PYTHAGORAS[1]), edit(_claim(PYTHAGORAS[1]), setp(
            expr_a="si n(x)**2+cos(x)**2")), "does not parse"),
        "R3 a newline": ("R3", _claim(_eq("(x+1)", "1+x")), edit(_claim(_eq("(x+1)", "1+x")), setp(
            expr_a="(x\n+1)")), "spanning lines"),
        "R3 a tab": ("R3", _claim(_eq("x+1", "1+x")), edit(_claim(_eq("x+1", "1+x")), setp(expr_a="x\t+1")),
                     "with spaces inserted"),
        "R3 a space taken out": ("R3", _claim(_eq("x + 1", "1+x")), edit(_claim(_eq("x + 1", "1+x")), setp(
            expr_a="x +1")), "with spaces inserted"),
        "R3 a leading space": ("R3", _claim(_eq("x+1", "1+x")), edit(_claim(_eq("x+1", "1+x")), setp(
            expr_a=" x+1")), "before its first token"),
        "R3 grown near the size guard": ("R3", _claim(_eq("x+1", "1+x")), edit(_claim(_eq("x+1", "1+x")), setp(
            expr_a="x" + " " * 3700 + "+1")), "within 10%"),
        "R3 a field with no expression changed": ("R3", _claim(_eq("x+1", "1+x")), edit(_claim(_eq("x+1", "1+x")),
                                                  setp(expr_a="x + 1", variables=["x"])), "holds no expression"),
        # R4, the first known mistake: x renamed, the variable the mode defaults left naming x
        "R4 mistake 1: (x-3)^2 > 0, the default variable left": (
            "R4", sq, edit(sq, rename_x_to("v0", "lhs", "rhs")),
            "the mode reads variable (default 'x'), and the restatement does not write it in"),
        "R4 mistake 1: sin(x) <= 0.9999, the default variable left": (
            "R4", sine, edit(sine, rename_x_to("v0", "lhs", "rhs")), "does not write it in"),
        "R4 mistake 1: the default written in as x": (
            "R4", sq, edit(sq, lambda a: (rename_x_to("v0", "lhs", "rhs")(a), setp(variable="x")(a))),
            "'x' is renamed to both 'v0' and 'x'"),
        "R4 mistake 1: an explicit variable not renamed": (
            "R4", cube, edit(cube, params(lambda p: p.update(function="v0**3", claimed_derivative="3*v0**2"))),
            "'t' is renamed to both 'v0' and 't'"),
        # the second known mistake: a rename to E, here with the variable renamed alike
        "R4 mistake 2: x renamed to E in a derivative, variable too": (
            "R4", _claim(_dv("x**2", "x", "2*x")), _claim(_dv("E**2", "E", "2*E")), "the new name 'E' is not drawn"),
        # capture, an old name that is no plain symbol, a called name, and parameters left unmapped
        "R4 x renamed onto y": ("R4", _claim(_eq("x + y", "y + x")), _claim(_eq("y + y", "y + y")),
                                "'x' and 'y' are both renamed to 'y'"),
        "R4 pi renamed": ("R4", _claim(_eq("pi*x", "x*pi")), _claim(_eq("v1*v0", "v0*v1")),
                          "'pi' is not a plain symbol"),
        "R4 inf renamed": ("R4", _claim({"mode": "limit", "params": {
            "function": "1/x", "variable": "x", "point": "inf", "claimed_limit": "0"}}),
            _claim({"mode": "limit", "params": {"function": "1/v0", "variable": "v0", "point": "v1",
                                                "claimed_limit": "0"}}), "'inf' is not a plain symbol"),
        "R4 a called name renamed": ("R4", pyth, edit(pyth, setp(expr_a="cos(v0)**2+cos(v0)**2")),
                                     "the called name 'sin' was renamed"),
        "R4 a called name renamed to a fresh name": ("R4", pyth, edit(pyth, setp(expr_a="v1(v0)**2+cos(v0)**2")),
                                                     "calls 'v1', which R4 cannot show"),
        "R4 variables left naming x": ("R4", T.GAP_DEPENDENCY, edit(T.GAP_DEPENDENCY, params(
            lambda p: p.update(expr_a="v0 + v0", expr_b="2*v0"), 1)), "'x' is renamed to both 'v0' and 'x'"),
        "R4 claimed_solution keys left": ("R4", _claim(SYSTEM), edit(_claim(SYSTEM), setp(
            equations=["v0 + v1 = 3", "v0 - v1 = 1"], variables=["v0", "v1"])), "renamed to both"),
        "R4 the tree changed": ("R4", cube, edit(cube, setp(function="v0**2", variable="v0",
                                                            claimed_derivative="3*v0**2")), "with its names changed"),
        # R5
        "R5 a collision made": ("R5", T.ERROR_BESIDE_FALSE, edit(T.ERROR_BESIDE_FALSE, ids("r0", "r0")),
                                "a collision made"),
        "R5 a collision undone": ("R5", T.REPEATED["two true a, nobody uses a"][0],
                                  edit(T.REPEATED["two true a, nobody uses a"][0], ids("r0", "r1")),
                                  "renamed apart (a collision undone)"),
        "R5 a new id holding '.'": ("R5", T.TWO_STEP, edit(T.TWO_STEP, lambda a: (
            ids("r.0", "r1")(a), a[1].update(uses=["r.0"]))), "holds '.'"),
        "R5 uses left": ("R5", T.TWO_STEP, edit(T.TWO_STEP, ids("r0", "r1")), "uses are not its old uses"),
        "R5 a bind source left": ("R5", T.DEFAULT_ID_COLLISION, edit(T.DEFAULT_ID_COLLISION, ids("r0", "r0", "r1")),
                                  "bind is not its old bind"),
        "R5 a new id the derivation already refers to": (
            "R5", [T.num("a", "2+2", 4, uses=["z"])], [T.num("z", "2+2", 4, uses=["z"])], "is not fresh"),
        "R5 a default id left implicit": ("R5", [T.rect(None, 4, 6, 24)], [T.rect(None, 4, 6, 24)],
                                          "no explicit string id"),
        "R5 the text left": ("R5", T.COMPOSE_DOC, edit(T.COMPOSE_DOC, lambda a: (
            ids("r0", "r1", "r2")(a["steps"]), a["steps"][1]["bind"].update({"PUBFIN_VERIFY.par": "r0.actual_par"}),
            a["steps"][2]["bind"].update({"RE_VERIFY.annual_debt_service": "r1.annual_pi"}))), "text is not"),
        "R5 a bind gained": ("R5", T.TWO_STEP, edit(T.TWO_STEP, lambda a: (
            ids("r0", "r1")(a), a[1].update(uses=["r0"]), a[0].update(bind={"params.claimed_value": "r1.actual"}))),
            "step 0 gained a bind"),
        "R5 a spec changed": ("R5", T.TWO_STEP, edit(T.TWO_STEP, lambda a: (
            ids("r0", "r1")(a), a[1].update(uses=["r0"]), a[1]["spec"]["params"].update(expr_b="13"))),
            "changed in more than its id, uses and bind"),
    }
    # checker-28's four: the bare x renamed, the x a string names left; and the paths a name can be computed by
    for before, after in STRING_NAMED:
        out[f"R4 {before[0]} renamed, its string left (checker-28)"] = (
            "R4", _claim(_eqv(*before)), _claim(_eqv(*after)), "holds a string ('x')")
    out["R4 a formatted string renamed around"] = ("R4", _claim(_eqv("x - Symbol(f'x')", "0")),
                                                   _claim(_eqv("v0 - Symbol(f'x')", "0")), "holds a formatted string")
    out["R4 a name a call computes, renamed around"] = (
        "R4", _claim(_eqv("x - Symbol(chr(120))", "0")), _claim(_eqv("v0 - Symbol(chr(120))", "0")), "calls 'Symbol'")
    out["R4 an attribute, renamed around"] = ("R4", _claim(_eqv("x*S.Half", "x/2")), _claim(_eqv("v0*S.Half", "v0/2")),
                                              "holds an Attribute")
    # the second known mistake for every name the plan names: x renamed to it in the Pythagorean identity
    for n in NOT_PLAIN:
        out[f"R4 mistake 2: x renamed to {n}"] = (
            "R4", pyth, edit(pyth, rename_x_to(n, "expr_a")), f"the new name {n!r} is not drawn")
    return out


def _digest(R):
    """Every restatement and every oracle above, as JSON: what two processes must agree on."""
    out = []
    for name, (key, subject, _) in sorted(_applied().items()):
        o = R.restate(key, subject)
        out.append([name, o.applied, _wire(o.after) if o.applied else o.reason, repr(o.mapping), list(o.restated)])
    for name, (key, subject, _) in sorted(_declined().items()):
        o = R.restate(key, subject)
        out.append([name, o.applied, o.reason])
    for name, (key, before, after, _) in sorted(_planted().items()):
        out.append([name, R.BY_KEY[key].oracle(before, after)])
    return out


# ── the registry ──────────────────────────────────────────────────────────────────────────────────────────────
def test_the_registry_is_fixed_and_named():
    R = _tool()
    assert isinstance(R.REGISTRY, tuple)
    assert [(r.key, r.name) for r in R.REGISTRY] == [
        ("R1", "key order"), ("R2", "equality swap"), ("R3", "whitespace between tokens"),
        ("R4", "symbol rename"), ("R5", "step-id rename")]
    assert isinstance(R.BY_KEY, MappingProxyType) and list(R.BY_KEY) == ["R1", "R2", "R3", "R4", "R5"]
    with pytest.raises(TypeError):
        R.BY_KEY["R6"] = R.REGISTRY[0]
    assert [r.oracle for r in R.REGISTRY] == [R.r1_oracle, R.r2_oracle, R.r3_oracle, R.r4_oracle, R.r5_oracle]
    assert isinstance(R.MODES, MappingProxyType) and all(isinstance(f, MappingProxyType) for f in R.MODES.values())
    assert isinstance(R.DEFAULT_VARIABLE, MappingProxyType)


# ── each restatement changes the bytes, keeps its input, gives the same output twice; its oracle passes it ─────
@pytest.mark.parametrize("name", sorted(_applied()))
def test_each_restatement_changes_the_bytes_on_a_worked_example(name):
    R = _tool()
    key, subject, check = _applied()[name]
    kept = copy.deepcopy(subject)
    sent = _wire(subject)
    o = R.restate(key, subject)
    assert o.applied, o.reason
    assert _wire(subject) == sent and R._same(subject, kept), "the restatement mutated its input"
    assert not (_mutables(subject) & _mutables(o.after)), "the restated subject shares an object with its input"
    assert _wire(o.after) != sent, "the restatement changed no byte"
    assert check(subject, o.after) is not False, _wire(o.after)
    assert R.BY_KEY[key].oracle(subject, o.after) is None
    assert _wire(subject) == sent, "the oracle mutated its input"
    again = R.restate(key, copy.deepcopy(kept))
    assert _wire(again.after) == _wire(o.after) and again.mapping == o.mapping and again.restated == o.restated
    if key == "R1":
        assert R.canonical_json_bytes(o.after) == R.canonical_json_bytes(subject)


@pytest.mark.parametrize("name", sorted(_declined()))
def test_each_restatement_declines_where_it_must(name):
    R = _tool()
    key, subject, why = _declined()[name]
    sent = _wire(subject) if not name.endswith("not JSON") else repr(subject)
    o = R.restate(key, subject)
    assert not o.applied and o.after is None
    assert why in o.reason, o.reason
    assert (repr(subject) if name.endswith("not JSON") else _wire(subject)) == sent, "a decline mutated its input"


def test_a_restatement_its_oracle_refuses_is_declined(monkeypatch):
    """restate() returns nothing its own oracle refuses: a build that forgets the defaulted variable comes back
    declined with the oracle's reason."""
    R = _tool()
    real = R.BY_KEY["R4"].build

    def forgetful(subject):
        after, mapping, done = real(subject)
        for s in after:
            s["spec"]["params"].pop("variable", None)
        return after, mapping, done

    monkeypatch.setattr(R.BY_KEY["R4"], "build", forgetful)
    o = R.restate("R4", _claim(SQUARE_TRAP[1]))
    assert not o.applied
    assert o.reason == ("its oracle refuses it: step 0: the mode reads variable (default 'x'), and the "
                        "restatement does not write it in")


# ── each oracle refuses a planted meaning change ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", sorted(_planted()))
def test_each_oracle_refuses_a_planted_meaning_change(name):
    R = _tool()
    key, before, after, why = _planted()[name]
    sb, sa = repr(before), repr(after)
    reason = R.BY_KEY[key].oracle(before, after)
    assert reason is not None and why in reason, reason
    assert repr(before) == sb and repr(after) == sa, "the oracle mutated what it judged"
    if "checker-28" in name:   # a real meaning change: sympy (no verifier) reads the equality true, then false
        from sympy import simplify, sympify
        holds = [simplify((sympify(p["expr_a"]) - sympify(p["expr_b"])).doit()) == 0
                 for p in (before[0]["spec"]["params"], after[0]["spec"]["params"])]
        assert holds == [True, False], holds


def test_the_names_r4_never_draws_are_not_plain_symbols(monkeypatch):
    """Each name the plan names, sympify reads as something else; inf is a plain Symbol to sympify but infinity to
    mathematics._parse, and mod is rewritten to %; v<digits> are plain. The oracle's plain-Symbol check stands on its
    own: with the name pattern widened to any identifier, it still refuses a rename to each of them."""
    R = _tool()
    assert [n for n in NOT_PLAIN if R._plain(n)] == []
    assert [n for n in NOT_PLAIN + ("inf", "oo", "mod", "Mod") if R._renamable(n)] == []
    assert all(R._plain(f"v{k}") and R.NEW_NAME.fullmatch(f"v{k}") for k in range(12))
    pyth = _claim(PYTHAGORAS[1])
    monkeypatch.setattr(R, "NEW_NAME", re.compile(r"[A-Za-z]\w*"))
    for n in NOT_PLAIN:
        after = copy.deepcopy(pyth)
        after[0]["spec"]["params"]["expr_a"] = _ren(pyth[0]["spec"]["params"]["expr_a"], "x", n)
        assert R.r4_oracle(pyth, after) == f"step 0: sympify({n!r}) is not the plain Symbol({n!r})", n
    after = copy.deepcopy(pyth)
    after[0]["spec"]["params"]["expr_a"] = "sin(w)**2+cos(w)**2"
    assert R.r4_oracle(pyth, after) is None, "a plain fresh name passes once the pattern admits it"


def test_the_first_known_mistake_changes_a_verdict():
    """Grounding (checker-26's measurement): on the benchmark's two symbolic inequality claims, both labelled false,
    renaming x with the defaulted variable left in place turns BROKEN into INCOMPLETE. The oracle refuses exactly
    that, and passes R4's own restatement of each."""
    spec = importlib.util.spec_from_file_location("_restate_benchmark", ROOT / "tools" / "benchmark.py")
    B = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(B)
    R = _tool()
    for label, claim in (SQUARE_TRAP, SINE_TRAP):
        assert (label, claim) in [(lb, sp) for lb, sp, _ in B.CLAIMS]
        mistaken = copy.deepcopy(claim)
        mistaken["params"].update(lhs=_ren(claim["params"]["lhs"], "x", "v0"), rhs=_ren(claim["params"]["rhs"], "x", "v0"))
        assert B.verify(copy.deepcopy(claim))["verdict"] == "BROKEN"
        assert B.verify(copy.deepcopy(mistaken))["verdict"] == "INCOMPLETE"
        assert R.r4_oracle(_claim(claim), _claim(mistaken)) is not None
        assert R.restate("R4", _claim(claim)).applied


def test_the_examples_are_the_benchmarks_own():
    spec = importlib.util.spec_from_file_location("_restate_benchmark", ROOT / "tools" / "benchmark.py")
    B = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(B)
    rows = [(lb, sp) for lb, sp, _ in B.CLAIMS]
    for row in (PYTHAGORAS, SQUARES, EULER, SQUARE_TRAP, SINE_TRAP, CUBE):
        assert row in rows
    lighthouse = [json.loads(line) for f in ("benchmark_lighthouse_v1.jsonl", "benchmark_lighthouse_v2.jsonl")
                  for line in (ROOT / "data" / f).open(encoding="utf-8")]
    (row,) = [r for r in lighthouse if r["id"] == "7df6039c7705"]
    md = dict(row.get("metadata") or row.get("spec_snapshot"))
    assert {"mode": md.pop("mode"), "params": md} == SOLVE
    assert '{"equations": ["x + y = 3",\n    "x - y = 1"], "variables": ["x", "y"], "claimed_solution": {"x": 2, "y": 1}}' \
        in MATH.read_text(encoding="utf-8")


# ── the engine's readings R2-R5 copy, pinned against its source (read as text, never imported) ─────────────────
def _source(path):
    return ast.parse(path.read_text(encoding="utf-8"))


def _math_modes():
    """derivation.py's _MATH_MODES: mode -> the mathematics.py function it calls."""
    for node in ast.walk(_source(DERIVATION)):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_MATH_MODES" for t in node.targets):
            return {k.value: v.attr for k, v in zip(node.value.keys, node.value.values)}
    raise AssertionError("derivation.py holds no _MATH_MODES")


def _reads(fn):
    """(fields read by spec.get(K...) or spec[K], {K: default} for a constant default with its line, any other use
    of spec)."""
    reads, defaults, receivers = set(), {}, set()
    for n in ast.walk(fn):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get"
                and isinstance(n.func.value, ast.Name) and n.func.value.id == "spec"
                and n.args and isinstance(n.args[0], ast.Constant)):
            reads.add(n.args[0].value)
            receivers.add(id(n.func.value))
            if len(n.args) > 1 and isinstance(n.args[1], ast.Constant):
                defaults[n.args[0].value] = (n.args[1].value, n.lineno)
        elif (isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name) and n.value.id == "spec"
              and isinstance(n.slice, ast.Constant)):
            reads.add(n.slice.value)
            receivers.add(id(n.value))
    other = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Name) and n.id == "spec" and id(n) not in receivers]
    return reads, defaults, other


def _functions():
    return {f.name: f for f in ast.walk(_source(MATH)) if isinstance(f, ast.FunctionDef)}


def test_r4s_default_variables_are_mathematics_pys():
    """The five spec.get("variable", "x") reads (mathematics.py, in verify_derivative, verify_integral, verify_limit,
    verify_solve and verify_inequality) are R4's DEFAULT_VARIABLE, mode for mode; a changed or new default fails."""
    R = _tool()
    funcs, found = _functions(), {}
    for mode, fname in _math_modes().items():
        reads, defaults, _ = _reads(funcs[fname])
        if "variable" in reads:
            assert "variable" in defaults, f"{fname} reads variable with no constant default"
            found[mode] = defaults["variable"]
    assert {m: d for m, (d, _) in found.items()} == dict(R.DEFAULT_VARIABLE), found
    assert sorted(found) == ["derivative", "inequality", "integral", "limit", "solve"]
    assert MATH.read_text(encoding="utf-8").count('spec.get("variable", "x")') == 5


def test_r4s_fields_are_what_each_mode_reads():
    """Every field a mapped mode's verifier reads is in MODES, it reads spec only by spec.get and spec[...], and
    every field in MODES is read, save inequality's variables (unread, carried by every benchmark inequality)."""
    R = _tool()
    funcs, modes = _functions(), _math_modes()
    for mode, fields in R.MODES.items():
        reads, defaults, other = _reads(funcs[modes[mode]])
        assert not other, f"{modes[mode]} uses spec otherwise at lines {other}"
        assert reads <= set(fields), f"{mode} reads {sorted(reads - set(fields))}, which R4 does not map"
        assert set(fields) - reads == ({"variables"} if mode == "inequality" else set()), mode
        assert {f for f, r in fields.items() if r == R.VARIABLE} == ({"variable"} if mode in R.DEFAULT_VARIABLE
                                                                      else set()), mode


def test_the_size_guard_is_derivation_pys():
    R = _tool()
    (node,) = [n for n in ast.walk(_source(DERIVATION)) if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == "_MAX_SPEC_CHARS" for t in n.targets)]
    consts = [c.value for c in sorted((c for c in ast.walk(node.value) if isinstance(c, ast.Constant)),
                                      key=lambda c: c.col_offset)]
    assert consts == [R.SIZE_ENV, str(R.SIZE_DEFAULT), R.SIZE_DEFAULT]
    assert "if len(json.dumps(params, default=str)) > _MAX_SPEC_CHARS:" in DERIVATION.read_text(encoding="utf-8")


@pytest.mark.parametrize("path, line", [
    (DERIVATION, 'ids = [str(step.get("id") or f"s{i}") for i, step in enumerate(steps)]'),   # R5's effective ids
    (DERIVATION, 'src_id, _, key = str(ref).partition(".")'),                                  # R5's bind sources
    (DERIVATION, 'uses = [str(u) for u in (step.get("uses") or [])]'),                         # R5's uses
    (DERIVATION, 'if isinstance(bind, dict) and bind:'),                                       # R2-R5's binds
    (DERIVATION, 'domain = (domain or "").strip().lower()'),                                   # R2-R4's routing
    (DERIVATION, 'if domain in ("mathematics", "math") and "MATH_VERIFY" not in (spec or {}):'),
    (DERIVATION, 'mode = (spec.get("mode") or "").strip().lower()'),
    (MATH, 'expr = _MOD_WORD_RE.sub("%", str(expr)).strip()'),     # the oracles parse the stripped string
    (MATH, 'locals_.setdefault("inf", oo)'),                       # why R4 never renames inf
    (MATH, 'if "=" in eq and "==" not in eq:'),                    # solve splits an equation at its first '='
    (MATH, 'lhs, rhs = eq.split("=", 1)'),
    (MATH, 'lhs, rhs = str(eq).split("=", 1)'),                    # system does too
])
def test_the_readings_the_restatements_copy_are_the_engines(path, line):
    assert line in path.read_text(encoding="utf-8"), f"{path.name} no longer reads {line!r}: re-check tools/restate.py"


# ── neither the restatements nor their oracles load the verifiers ─────────────────────────────────────────────
def test_the_restatements_import_nothing_from_the_verifiers():
    imported = set()
    for n in ast.walk(_source(TOOL)):
        if isinstance(n, ast.Import):
            imported |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            imported.add(n.module)
    assert {m for m in imported if m.split(".")[0] == "concordance"} == {"concordance.validate"}
    assert {m.split(".")[0] for m in imported} - {"concordance", "sympy"} <= set(sys.stdlib_module_names) | {"__future__"}


def test_in_a_fresh_interpreter_nothing_loads_the_verifiers_and_the_output_is_the_same():
    """Every restatement and every oracle above, run in a fresh interpreter under a hash seed other than this
    process's: concordance.verifiers and concordance.derivation never load, and the output is this process's."""
    script = (
        "import importlib.util, json, sys\n"
        f"spec = importlib.util.spec_from_file_location('_t_restate', {str(Path(__file__))!r})\n"
        "T = importlib.util.module_from_spec(spec); spec.loader.exec_module(T)\n"
        "out = T._digest(T._tool())\n"
        "loaded = sorted(m for m in sys.modules if m.startswith(('concordance.verifiers', 'concordance.derivation')))\n"
        "print(json.dumps({'out': out, 'loaded': loaded, 'sympy': 'sympy' in sys.modules}))\n")
    seed = "2" if os.environ.get("PYTHONHASHSEED") == "1" else "1"
    env = dict(os.environ, PYTHONHASHSEED=seed)
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, env=env, cwd=str(ROOT),
                          timeout=300)
    assert proc.returncode == 0, proc.stderr
    got = json.loads(proc.stdout.strip().splitlines()[-1])
    assert got["loaded"] == [] and got["sympy"] is True
    assert got["out"] == json.loads(json.dumps(_digest(_tool())))


# ── no module under src/ imports or loads the restatement tools ───────────────────────────────────────────────
_TOOL_FILE = re.compile(r"(?<![\w-])(restate|restatement_audit)\.py(?!\w)")
_TOOL_MODULE = re.compile(r"(?:\w+\.)*(restate|restatement_audit)")


def _loads_the_tools(source):
    """What in a module's source imports or names tools/restate.py or tools/restatement_audit.py: its import
    statements, and its string constants that are those modules' names or name those files. Never a bare word."""
    hits = []
    for n in ast.walk(ast.parse(source)):
        if isinstance(n, ast.Import):
            hits += [a.name for a in n.names if _TOOL_MODULE.fullmatch(a.name)]
        elif isinstance(n, ast.ImportFrom):
            if n.module and _TOOL_MODULE.fullmatch(n.module):
                hits.append(n.module)
            hits += [f"{n.module}.{a.name}" for a in n.names if a.name in ("restate", "restatement_audit")]
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            s = n.value.replace("\\", "/")
            if _TOOL_FILE.search(s) or _TOOL_MODULE.fullmatch(s.strip()):
                hits.append(repr(n.value))
    return hits


def test_no_module_under_src_imports_or_loads_the_restatement_tools():
    loads = [
        "import restate", "from tools import restate", "import tools.restatement_audit as ra",
        "from restate import REGISTRY", "from .restatement_audit import main", "importlib.import_module('restate')",
        "spec_from_file_location('r', ROOT / 'tools' / 'restate.py')", "runpy.run_path('tools\\\\restatement_audit.py')",
        "__import__('tools.restate')",
    ]
    assert [s for s in loads if not _loads_the_tools(s)] == []
    words = ["x = 'the Restatement (Second) of Contracts'", "def restated():\n    restatement = 1",
             "import restatements_of_law", "s = 'we restate the claim'", "t = 'restate.python'"]
    assert [s for s in words if _loads_the_tools(s)] == []
    law = (ROOT / "src" / "concordance" / "verifiers" / "law.py").read_text(encoding="utf-8")
    assert "Restatement (Second) of" in law and _loads_the_tools(law) == []
    files = sorted((ROOT / "src").rglob("*.py"))
    assert len(files) > 100
    hits = {str(p.relative_to(ROOT)): h for p in files if (h := _loads_the_tools(p.read_text(encoding="utf-8")))}
    assert hits == {}
