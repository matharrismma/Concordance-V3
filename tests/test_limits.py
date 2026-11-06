"""A limit is read from both sides, and at a finite point only for a form on the list (run 2026-11-04-gcd-lcm-order, step
limits-head).

sympy's limit answers from one side, so Abs(x)/x at 0 = 1 read HOLDS, and oo less oo is nan, so a true infinite claim read
BROKEN. Its sides can also agree and be wrong: 1/(exp(acot(x)) - exp(pi/2))**2 at 0 reads oo on both, and the left side runs
to 0.0472. Each numeric test tried at runtime was beaten by a form built for it, so the trust is structural: at a finite
point the sides are read only for a form on an allow-list, decided before any limit runs. Its numbers are PLAIN, so no zero
or one can hide in them, its values SETTLED, by a read and never by sympy's is_zero, its parts read by NO ZERO HIDES, each
keeping its digits, the whole form cancelling at most 10 digits, a pole's other parts EXACT, and its CUTS hold no cut and no
symbol nobody bound. DECIDED: an infinite reading confirms only in a rational function with rational coefficients at a rational
point, where zero is decidable. The numeric test of what sympy answers lives in the slow sweeps below, where a hang costs nothing
and an engineered claim proves nothing. Those sweeps are evidence, not proof: HOLDS here means the claim survived.

Every row below is the plan's, exactly (ledger line 167, LIMITS), and a row that reads otherwise fails the step and changes only
by replan. Names the fix adds are read inside the tests, so the file collects at the step's base. A row is read in a child that
can be killed: see read.
"""
from __future__ import annotations

import inspect
import json
import random
import re
import sys
from collections import Counter
from fractions import Fraction
from pathlib import Path

import pytest
import sympy

from concordance import audit as M_AUDIT
from concordance.audit import _x_limit, audit, extract
from concordance.config import EngineConfig
from concordance.derivation import verify
from concordance.verifiers import mathematics as M
from test_bound_values import Trials, _restate, every_mode, read as read_here, renamed, renamed_params, symbols

pytestmark = pytest.mark.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
I, H, B = "INCOMPLETE", "HOLDS", "BROKEN"
CFG = EngineConfig(skip_schema_validation=True)


@pytest.fixture(autouse=True)
def _tables():
    M._ensure_sympy()


READER = r"""
import json, sys
sys.path[:0] = sys.argv[1:3]
from concordance.derivation import verify
from concordance.verifiers import mathematics as M
M._ensure_sympy()
print("ready", flush=True)
for line in sys.stdin:
    answer = verify(json.loads(line))
    print(json.dumps({"verdict": answer["verdict"], "detail": str(answer["trail"][0].get("detail"))}), flush=True)
"""
CHILD = Trials(READER, ROOT / "tests")


@pytest.fixture(scope="module", autouse=True)
def _no_child_left():
    yield
    CHILD.stop()


def read(mode, params):
    """A row's verdict, read in a child that can be killed. A row that runs past verify's window at the base leaves its thread running,
    only ending the process stops it, and each such thread slows every test after it: ledger line 130 measured that the checker's pin
    stage could not finish so. A read past the window ends the child and answers None, which is no verdict. read_here is for a test that
    patches the session, on a row that reads at once."""
    answer = CHILD.ask(mode=mode, params=params)
    return answer and answer["verdict"]


# ── the plan's rows ──────────────────────────────────────────────────────────────────────────────────────────────────
HOLDING = (
    "sin(x)/x at 0 = 1", "1/x**2 at 0 = oo", "1/x at oo = 0", "x**2 at 2 = 4", "Abs(x) at 0 = 0", "exp(-1/x**2) at 0 = 0",
    "exp(exp(exp(exp(x)))) at 3 = exp(exp(exp(exp(3))))", "a*sin(x)/x at 0 = a", "sin(a*x)/x at 0 = a", "a*x at 0 = 0", "sin(x - a)/(x - a) at a = 1",
    "sqrt(x) at 0 = 0", "x*log(x) at 0 = 0", "1/x at 0 dir + = oo", "1/x at 0 dir - = -oo", "Abs(x)/x at 0 dir + = 1", "Abs(x)/x at 0 dir - = -1",
    "sign(x) at 0 dir + = 1", "exp(1/x) at 0 dir - = 0", "sqrt(x) at 0 dir + = 0", "x*log(x) at 0 dir + = 0", "x at 1000000 = 1000000",
    "sqrt(x + 1/1000000) at 0 = 1/1000", "1/cos(x) at 2 = 1/cos(2)", "tan(x) at 1 = tan(1)", "1/(x - 1)**2 at 1 = oo", "1/(x - 1/3)**2 at 1/3 = oo",
    "1/(x - 0.1)**2 at 0.1 = oo", "(x + 1)/(x**2 - 2*x + 1) at 1 = oo", "-3/(x**2*(x - 1)**2) at 0 = -oo", "1/x**2 - 1/x**4 at 0 = -oo",
    "1/(x - 1)**2 - 1/(x**2 - 2*x + 1) + 1/(x - 1)**4 at 1 = oo", "cosh(x) - sinh(x) at 10 = exp(-10)", "(sin(x) - x)/x**3 at 0 = -1/6",
    "(tan(x) - sin(x))/x**3 at 0 = 1/2", "(exp(x) - 1 - x)/x**2 at 0 = 1/2", "(cos(x) - 1 + x**2/2)/x**4 at 0 = 1/24", "(x**3 - 8)/(x - 2) at 2 = 12",
    "(sqrt(x) - 1)/(x - 1) at 1 = 1/2", "log(x)/(x - 1) at 1 = 1", "1/x - 1/sin(x) at 0 = 0", "sin(x)/x + tan(x)/x at 0 = 2", "1/(x - 1) - 2/(x**2 - 1) at 1 = 1/2",
    "atan(x)/x + asin(x)/x at 0 = 2", "(x**2 - 2)/(x - sqrt(2)) at sqrt(2) = 2*sqrt(2)", "(1 + cos(x))/(x - pi)**2 at pi = 1/2",
    "(x*exp(x) - x*cosh(x) - x*sinh(x) + x**3)/x**3 at 0 = 1", "((x - 1)*exp(x - 1) - (x - 1)*cosh(x - 1) - (x - 1)*sinh(x - 1) + (x - 1)**3)/(x - 1)**3 at 1 = 1",
    "sin(x**9)/x**9 at 0 = 1", "cosh(x) + sinh(x) at 10 = exp(10)", "x + exp(exp(x)) at 3 = 3 + exp(exp(3))",
    "exp(exp(exp(exp(x)*exp(1 - cosh(300*sinh(1000000*sin(x - 3)))))*exp(1 - cosh(300*sinh(1000000*sin(x - 3)))))*exp(1 - cosh(300*sinh(1000000*sin(x - 3))))) at 3 = exp(exp(exp(exp(3))))",
    "tan(x - 1)/(x - 1) at 1 = 1", "1/(1 + (x - 1)**2) at 1 = 1", "1/(2 + sin(x - 1)) at 1 = 1/2", "log(1 + (x - 1)**2)/(x - 1)**2 at 1 = 1",
    "sqrt(1 + (x - 2)**2) at 2 = 1", "cosh(exp(x)) at 35 = cosh(exp(35))", "x**5 + x**7 at 0 = 0", "(x**5 + x**7)/x**5 at 0 = 1", "(1 - cos(x))/x**2 at 0 = 1/2",
    "sin(x**5)/x**5 at 0 = 1", "sin(x)/x + 1 at 0 = 2", "tan(tan(tan(tan(tan(tan(x)))))) at 1 = tan(tan(tan(tan(tan(tan(1))))))",
)
FALSE = (
    "Abs(x)/x at 0 = 1", "Abs(x)/x at 0 = -1", "sign(x) at 0 = 1", "1/x at 0 = oo", "1/x at 0 = -oo", "exp(1/x) at 0 = oo", "sin(x)/x at 0 = 2",
    "Abs(x)/x at 0 dir + = -1", "1/x at 0 dir + = -oo", "sin(x) at oo = 5", "x*log(x) at 0 = 1", "x at oo = 5", "(cosh(x)**2 - sinh(x)**2 - 1)*x at oo = 0",
    "(1 - (1/2 + (125283 + (x + 524288)*(x + 1)*427590 + 336054*(x + 524288)**2 + 453112*(x + 524288)**3 + 4120*(x + 524288)**4) - sqrt(2)*sin(x)/x*(106118 + (x + 524288)*(x + 1)*286435 + 215677*(x + 524288)**2 + 467167*(x + 524288)**3 + 2913*(x + 524288)**4))**2)/x**2 at 0 = oo",
)
NOT_CHECKABLE = (
    "1/(1 + exp(1/x)) + 1 at 0 = 1", "1/(1 + exp(1/x)) + 1 at 0 dir - = 1", "tanh(x) + 1/(1 + exp(1/x)) at 0 = 0", "1/(1 + exp(1/x)) - pi at 0 = -pi",
    "1/(1/(1 + exp(1/x)) - 1) at 0 = -1", "sign(x**2 - a*x) at 0 = 1", "sign(a*sin(x)) at 0 dir + = 1", "x/(1 - sign(x)**2) at 0 = 0",
    "((x**2 + x**3) - sqrt(log(1 + x)**2))/(x**2 + x**3) at 0 dir - = oo", "sign(atan(sqrt((x - sin(x))**2))) at 0 = I", "Abs(acos(cos(x**3 - x**2))) at 0 = 0",
    "atan(1/x) at 0 = pi/2", "tan(x) at pi/2 = oo", "sin(1/x) at 0 = 5", "x*sin(1/x) at 0 = 0", "x**x at 0 = 1", "x**x at 0 dir + = 1", "x**(1/x) at 0 dir + = 0",
    "sinh(sinh(1/x)) at 0 = oo", "x*sin(exp(1/x)) at 0 = 0", "1/(exp(atan(1/x)) - exp(pi/2))**2 - 1/log(1/x**2) at 0 = oo", "1/(exp(acot(x)) - exp(pi/2))**2 at 0 = oo",
    "exp(exp(1/x)) at 0 = oo", "x**(1/x) at 0 = 0", "exp(log(x)/x) at 0 = 0", "x**(-1/x) at 0 = oo", "log(x)/x at 0 = -oo", "log(x)**3/x**3 at 0 = -oo",
    "1/sqrt(x) at 0 = oo", "sqrt(x) at 0 dir - = 0", "sin(x)/x at 0 dir up = 1", "floor(x) at 1 = 1", "floor(x) at 1 = 0", "floor(x) at 1 dir + = 1",
    "ceiling(x) at 2 = 2", "sin(floor(x)) at 1 = sin(1)", "exp(floor(x)) at 1 = E", "tanh(floor(x)) at 0 = 0", "exp(frac(x)) at 0 = 1", "x + sin(frac(x)) at 0 = 0",
    "cos(ceiling(x)) at 0 dir + = 1", "Piecewise((1, x < 0), (2, true)) at 0 = 2", "Piecewise((1, x < 0), (2, x >= 0)) at 0 = 2",
    "Piecewise((1, x < 0), (2, true)) at 0 dir + = 2", "Max(x**2, 1)*sign(x - 1) at 1 = 1", "sin(x)**2 + cos(x)**2 at oo = 1", "sin(x)*cos(x) - sin(2*x)/2 at oo = 0",
    "sin(1/x)**2 + cos(1/x)**2 at 0 = 1", "sin(1/x) at 0 = 0", "exp(acot(x)) at 0 = exp(pi/2)", "exp(atan(1/x)) at 0 = exp(pi/2)", "tanh(atan(1/x)) at 0 = tanh(pi/2)",
    "exp(tanh(1/x)) at 0 = E", "exp(erf(1/x)) at 0 = E", "tanh(erf(1/x)) at 0 = tanh(1)", "atan(atan2(x, -1)) at 0 = atan(pi)", "exp(acot(x)) at 0 dir - = exp(pi/2)",
    "exp(acot(x)) at 0 dir - = exp(-pi/2)", "exp(acot(x))/1000 at 0 = exp(pi/2)/1000", "exp(acot(x))/10**6 at 0 = exp(pi/2)/10**6",
    "exp(acot(x)/1000) at 0 = exp(pi/2000)", "exp(tanh(1/x))/1000 at 0 = E/1000", "exp(acot(x))/1000 - exp(pi/2)/1000 at 0 = 0", "I*exp(acot(x)) at 0 = I*exp(pi/2)",
    "(1 + I)*exp(tanh(1/x)) at 0 = (1 + I)*E", "a*exp(acot(x)) at 0 = a*exp(pi/2)", "a + exp(acot(x)) at 0 = a + exp(pi/2)", "exp(acot(x - a)) at a = exp(pi/2)",
    "a*exp(acot(x - a)) at a = a*exp(pi/2)", "a + exp(tanh(1/(x - a))) at a = a + E", "x at exp(exp(exp(exp(3)))) dir + = exp(exp(exp(exp(3))))",
    "exp(log(x - 10**100)/(x - 10**100)**3) at 10**100 dir - = oo", "log(x - 10**80)/(x - 10**80) at 10**80 dir - = oo", "sqrt(x - 10**100) at 10**100 dir - = 0",
    "exp(log(x*(x + 1/10**10))/x**3) at 0 dir - = oo", "log(x*(x + 1/10**10)) at 0 dir - = -oo", "log(sin(x)) at 0 = -oo",
    "2/sin(x) at cosh(1)**2 - sinh(1)**2 - 1 = 2/sin(cosh(1)**2 - sinh(1)**2 - 1)",
    "sin(1/sin(x)) at cosh(1)**2 - sinh(1)**2 - 1 = sin(1/sin(cosh(1)**2 - sinh(1)**2 - 1))",
    "acos(cos(x) + (sqrt(5 + 2*sqrt(6)) - sqrt(2) - sqrt(3)))/x at 0 dir + = oo",
    "1/(a*x + x) at sqrt(5 + 2*sqrt(6)) - sqrt(2) - sqrt(3) = 1/(a*(sqrt(5 + 2*sqrt(6)) - sqrt(2) - sqrt(3)) + sqrt(5 + 2*sqrt(6)) - sqrt(2) - sqrt(3))",
    "log(-a**2 + I*x) at 0 = log(-a**2)", "sqrt(-a**2 + I*x) at 0 = sqrt(-a**2)", "2/sin(cosh(x)**2 - sinh(x)**2 - 1) at 1 = 2/sin(cosh(1)**2 - sinh(1)**2 - 1)",
    "1/(x + (1 + sqrt(2))*(1 - sqrt(2)) + 1) at 0 = oo", "x + log(2) at 0 = log(2)", "sqrt(a - b + x) at 0 dir + = sqrt(a - b)", "(1 + I)*x at 0 = 0",
    "exp(-log(x)/x**2) at 0 = oo", "exp(log(x)**2/x**2) at 0 = oo", "I*sin(sqrt(-1 - sqrt(x))) at 0 = -sinh(1)", "sin(sqrt(-1 - x**(1/3))) at 0 = I*sinh(1)",
    "I*sin(sqrt(x**2)) at I = -sinh(1)", "sin(sqrt(x**2 + 2)) at 2*I = I*sinh(sqrt(2))", "tanh(atan(x)) at 2*I = tanh(atan(2*I))",
    "1/atan(cosh(x)**2 - sinh(x)**2 - 1) at 200 = 1/atan(cosh(200)**2 - sinh(200)**2 - 1)", "x/(x*(1 + sqrt(2)) + x*(1 - sqrt(2)) - 2*x) at 0 = 0",
    "sign((sqrt(x) + 1)**2 - x - 2*sqrt(x) - 1) at 0 = 1", "(cosh(x)**2 - sinh(x)**2 - 1)*x at oo = oo", "x*cosh(x)**2 - x*sinh(x)**2 - x at oo = oo",
    "(cosh(x)**2 - sinh(x)**2 - 1)*x**2 at oo = oo", "(cosh(x)**2 - sinh(x)**2 - 1)*x at -oo = -oo", "(sinh(x)**2 - cosh(x)**2 + 1)*x at oo = -oo",
    "(cosh(x)**2 - sinh(x)**2 - 2)*x at oo = oo", "x*cosh(x)**2 - x*sinh(x)**2 - x + 1 at oo = oo", "x*cosh(x)**2 - x*sinh(x)**2 - x + 1 at -oo = -oo",
    "x*log(cosh(x)**2 - sinh(x)**2) at oo = oo", "((a + 1)**2 - a**2 - 2*a - 1)/x**2 at 0 = oo*sign((a + 1)**2 - a**2 - 2*a - 1)", "a/x**2 at 0 = oo*sign(a)",
    "(cosh(x)**2 - sinh(x)**2)**x at oo = oo", "log(x) at -oo = oo", "sqrt(x) + x at -oo = -oo", "log(1 - x) at oo = oo", "acosh(x) at -oo = oo",
    "tan(x) + x at oo = oo", "1/sin(x) + x at oo = oo", "x at oo = oo", "exp(x) at oo = oo", "(a - b)*log(x) at 0 dir - = -oo*sign(a - b)",
    "(a - b)*log(x) + 1/x**2 at 0 dir - = oo", "(a - b)*sqrt(x) at 0 dir - = 0", "a*log(x) - b*log(x) + 1/x**2 at 0 dir - = oo",
    "a**2*log(x) - 3*log(x) + 1/x**2 at 0 dir - = oo", "a*b*log(x) - 3*log(x) + 1/x**2 at 0 dir - = oo", "sqrt(3)*log(x) - a*log(x) + 1/x**2 at 0 dir - = oo",
    "a*log(x - 1) - b*log(x - 1) + 1/(x - 1)**2 at 1 dir - = oo", "(sin(x)**2 + cos(x)**2 - 1)/(x - 1)**2 at 1 = -oo",
    "(sin(x)**2 + cos(x)**2 - 1)/(x - 1)**2 at 1 dir + = -oo", "(sin(x)**2 + cos(x)**2 - 1)/(x - 1)**2 at 1 dir - = -oo",
    "(sin(x)**2 + cos(x)**2 - 1)/(x - 3)**2 at 3 = -oo", "(sin(x)**2 + cos(x)**2 - 1)/(x - 1) at 1 dir + = -oo",
    "2*(sin(x)**2 + cos(x)**2 - 1)/(x - 130)**2 at 130 = oo", "sin(x)**2/(x - 1000)**2 + cos(x)**2/(x - 1000)**2 - 1/(x - 1000)**2 at 1000 = -oo",
    "1/(x - 2)**2 - (sin(x)**2 + cos(x)**2 - 1)/(x - 2)**4 at 2 = -oo", "1/(x - 0.1)**2 - (cosh(x)**2 - sinh(x)**2 - 1)/(x - 0.1)**4 at 0.1 = 0",
    "1/(3 - exp(cosh(x)**2/(x - 0.1)**2 - sinh(x)**2/(x - 0.1)**2 - 1/(x - 0.1)**2 + 1)) at 0.1 = 1/2", "(cosh(x)**2 - sinh(x)**2 - 1)/(x - 2)**2 + 1 at 2 = 0",
    "log(cosh(x)**2 - sinh(x)**2)/(x - 1)**2 at 1 = oo", "log(cosh(x)**2 - sinh(x)**2)/(x - 54)**2 at 54 = oo",
    "log((cosh(x)**2 - sinh(x)**2)**2)/sin(x - 9)**2 at 9 = oo", "tan(pi*(cosh(x)**2 - sinh(x)**2))/(x - 54)**2 at 54 = oo",
    "acos((cosh(2*x/3) - 2*sinh(x/3)**2)/2)/(x - 363)**2 at 363 = -oo", "acos((cosh(2*x/3) - 2*sinh(x/3)**2)/2)/(x - 363)**2 at 363 = oo",
    "acos((cosh(x) - 2*sinh(x/2)**2)/2)/(x - 244)**2 at 244 = -oo", "atan((cosh(x/3) - sinh(x/3))*exp(x/3))/(x - 464)**2 at 464 = -oo",
    "sin(pi*(sinh(2*x/3) - 2*sinh(x/3)*cosh(x/3) + 1)/2)/(x - 496)**2 at 496 = -oo", "atan(x*(cosh(x) - 2*sinh(x/2)**2))/(x - 285)**2 at 285 = -oo",
    "x*(cosh(x/3) - sinh(x/3))*exp(x/3)/(x - 460)**2 at 460 = -oo", "sign(x*(cosh(x/3) - sinh(x/3))*exp(x/3))/(x - 425)**2 at 425 = -oo",
    "((x - 2)*exp(x) - (x - 2)*cosh(x) - (x - 2)*sinh(x) + (x - 2)**3)/(x - 2)**3 at 2 = -oo",
    "((x - 2)*exp(x) - (x - 2)*cosh(x) - (x - 2)*sinh(x) + (x - 2)**3)/(x - 2)**3 at 2 = oo",
    "((x - 2)*exp(x) - (x - 2)*cosh(x) - (x - 2)*sinh(x) + (x - 2)**3)/(x - 2)**3 at 2 = 1", "acos((cosh(2*x/3) - 2*sinh(x/3)**2)/2) at 363 = -pi/3",
    "acos((cosh(2*x/3) - 2*sinh(x/3)**2)/2) at 363.0 = -pi/3", "acos((cosh(2*x/3) - 2*sinh(x/3)**2)/2) at 363.5 = -pi/3",
    "acos((cosh(x) - 2*sinh(x/2)**2)/2) at 69.0 = -pi/3", "log(cosh(2*x/3) - 2*sinh(x/3)**2)**2 at 451 = -4*pi**2",
    "log(cosh(2*x/3) - 2*sinh(x/3)**2)**2 at 451.0 = -4*pi**2", "log(cosh(2*x/3) - 2*sinh(x/3)**2) at 451 = 2*pi*I", "sign(cosh(2*x/3) - 2*sinh(x/3)**2) at 451 = -1",
    "cosh(2*x/3) - 2*sinh(x/3)**2 at 451 = 1", "cosh(x) - sinh(x) at 100 = exp(-100)",
    "(1 - (1/2 + 125283 + (x + 524288)*(x + 1)*427590 + 336054*(x + 524288)**2 + 453112*(x + 524288)**3 + 4120*(x + 524288)**4 - sqrt(2)*(106118 + (x + 524288)*(x + 1)*286435 + 215677*(x + 524288)**2 + 467167*(x + 524288)**3 + 2913*(x + 524288)**4))**2)/x**2 at 0 = -oo",
    "(1 - (4120*x**152 + 453112*x**114 + 336054*x**76 + 427590*x**38 - x*(2913*x**152 + 467167*x**114 + 215677*x**76 + 286435*x**38 + 106118) + 250567/2)**2)/(x - sqrt(2))**2 at sqrt(2) = -oo",
    "sin(x)/(x - a) at b = sin(b)/(b - a)", "(sqrt(x - 2)*exp(x) - sqrt(x - 2)*cosh(x) - sqrt(x - 2)*sinh(x) + (x - 2)**2)/(x - 2)**2 at 2 dir + = -oo",
    "(((x - 2) + (x - 2)**3*exp(x) - (x - 2)**3*cosh(x) - (x - 2)**3*sinh(x) + (x - 2)**5)/(x - 2) - 1)/(x - 2)**4 at 2 = -oo", "tan(exp(x))/(x - 30)**2 at 30 = oo",
    "(exp(x) - E)/(x - 1) at 1 = E", "exp(x)/(x - 1)**2 at 1 = oo", "log(1 + (x - 2)*exp(x) - (x - 2)*cosh(x) - (x - 2)*sinh(x) + (x - 2)**2)/(x - 2)**2 at 2 = 1",
    "sin((x - 1)**2*exp(x) - (x - 1)**2*cosh(x) - (x - 1)**2*sinh(x) + (x - 1)**4)/(x - 1)**4 at 1 = 1", "acos((cosh(x) - 2*sinh(x/2)**2)/2)/(x - 69)**2 at 69 = -oo",
    "acos((cosh(x/2) - 2*sinh(x/4)**2)/2)/(x - 138)**2 at 138 = -oo", "acos((cosh(x/2) - 2*sinh(x/4)**2)/2)/(x - 138)**2 at 138 = oo",
    "atan((cosh(x/2) - sinh(x/2))**8*exp(4*x))/(x - 60)**2 at 60 = -oo", "atan((cosh(x/2) - sinh(x/2))**16*exp(8*x))/(x - 30)**2 at 30 = -oo",
    "log((cosh(x/2) - sinh(x/2))**2*exp(x)/2)/(x - 66)**2 at 66 = oo", "acos((cosh(2*x/3) - 2*sinh(x/3)**2)**4/2)/(x - 103)**2 at 103 = -oo",
    "exp(exp(x))*(cosh(2*x/3) - 2*sinh(x/3)**2)/(x - 451)**2 at 451 = -oo", "exp(x**70)*(cosh(2*x/3) - 2*sinh(x/3)**2)/(x - 451)**2 at 451 = -oo",
    "exp(exp(x))*acos((cosh(2*x/3) - 2*sinh(x/3)**2)/2)/(x - 363)**2 at 363 = -oo",
    "(cosh(2*x/3) - 2*sinh(x/3)**2)*(tan(1000000*sin(x - 451))**2 - 1/100)/(x - 451)**2 at 451 = oo",
    "(cosh(2*x/3) - 2*sinh(x/3)**2)*(tan(1000000*sin(x - 451))**2 - 1/100)/(x - 451)**2 at 451 = -oo", "(cosh(2*x/3) - 2*sinh(x/3)**2)/(x - 451)**2 at 451 = -oo",
    "(cosh(2*x/3) - 2*sinh(x/3)**2)/(x - 451)**2 at 451 = oo", "sign(cosh(2*x/3) - 2*sinh(x/3)**2)/(x - 451)**2 at 451 = -oo",
    "Abs(cosh(2*x/3) - 2*sinh(x/3)**2)/(x - 451)**2 at 451 = -oo", "atan(cosh(x) - 2*sinh(x/2)**2)/(x - 315)**2 at 315 = -oo",
    "log(cosh(2*x/3) - 2*sinh(x/3)**2)/(x - 451)**2 at 451 = oo", "log((cosh(x/3) - sinh(x/3))*exp(x/3))/(x - 446)**2 at 446 = oo",
    "tan(log(cosh(2*x/3) - 2*sinh(x/3)**2))/(x - 451)**2 at 451 = oo", "tan(pi*(cosh(x) - sinh(x))*exp(x))/(x - 133)**2 at 133 = oo",
    "2*tan(pi*(cosh(x + 1) - sinh(x + 1))*exp(x + 1))/(x - 132)**2 at 132 = oo", "cos(pi*(cosh(sqrt(2)*x) - sinh(sqrt(2)*x))*exp(sqrt(2)*x)/2)/(x - 93)**2 at 93 = -oo",
    "sin(pi*x**70*(cosh(x)**2 - sinh(x)**2))/(x - 2)**2 at 2 = -oo", "sin(pi*x**8*tanh(x)*cosh(x)/sinh(x))/(x - 1000)**2 at 1000 = -oo",
    "sin(pi*x**8*tanh(x)*cosh(x)/sinh(x))/(x - 1000)**2 at 1000 dir + = -oo", "sin(pi*x**8*tan(x)*cos(x)/sin(x))/(x - 1000)**2 at 1000 = -oo",
    "2*(tanh(x**2*exp(x**2))*cosh(x**2*exp(x**2)) - sinh(x**2*exp(x**2)))/(x - 8)**2 at 8 = oo",
    "x*(cosh(2*x**2*exp(x**2)) - 2*sinh(x**2*exp(x**2))**2 - 1)/(x - 8)**2 at 8 = oo", "log(1 + x**7)/x**7 at 0 = 1", "sin(x**70) at 2 = sin(2**70)",
    "(cosh(exp(exp(x)))**2 - sinh(exp(exp(x)))**2 - 1)/(x - 4)**2 at 4 = -oo", "(sin(2*x**4) - 2*sin(x**4)*cos(x**4))/(x - 200000)**2 + 1 at 200000 = 0",
    "sin(pi*(cosh(x)**2 - sinh(x)**2))/x**2 at 0 = oo", "1/(1 - tan(x)*cos(x)/sin(x)) at 0 = 0", "2*(tan(x)*cos(x) - sin(x))/(x - 0.1)**2 at 0.1 = 0",
    "(tan(x)*cos(x) - sin(x))/sin(x - 0.1) at 0.1 = 0", "exp((tan(x)*cos(x) - sin(x))/(x - 0.1)) at 0.1 = 0",
    "1/(3 - exp(cosh(x)**2/(x - a) - sinh(x)**2/(x - a))) at a = 0", "((a + 1)**2 - a**2 - 2*a - 1)/x**2 at 0 = 0", "(sin(a)**2 + cos(a)**2 - 1)/x**2 at 0 = 0",
    "(a*(a + 1) - a**2 - a)/x at 0 dir + = 0", "Abs(x)/(Abs(x) + x) at 0 dir - = 0", "2*Abs(x - 1)/(Abs(x - 1) + x - 1) at 1 dir - = 0",
    "x*Abs(x)/(Abs(x) + x)**2 at 0 dir - = 0", "sign(x - 2)*Abs(x - 2)/(Abs(x - 2) + x - 2) at 2 dir - = 0", "sign(x)*x/(1 - sign(x)**2) at 0 = 0",
    "Abs(x)*sin(Abs(x)) at 0 = 0", "exp(1/x**1000) at 0 dir - = oo", "exp(1/x**1000) at 0 dir + = oo", "log(x) at 0 = -oo", "log(x) at 0 dir + = -oo",
    "log(x)/x at 0 dir + = -oo", "1/sqrt(x) at 0 dir + = oo", "log(x - 1) at 1 dir + = -oo", "1/x**2 + sin(x) at 0 = oo", "1/(x - sqrt(2))**2 at sqrt(2) = oo",
    "1/(x - pi)**2 at pi = oo", "(sqrt(x**2) - 2)**2/(x + 2)**2 at -2 = oo", "(sqrt(x**2) + x + (x + 1)**2)/(x + 1)**2 at -1 = -oo",
    "(sqrt(x**2) - 1)/(x + 1)**2 at -1 dir - = -oo", "(sqrt(x**2) - 2)**2/(x + 2)**2 at -2 = 1", "sqrt(x**2) - 1 at -1 = -2", "sqrt(x**2) at -2 = 2",
    "(x**4)**(1/3) - 1 at -1 = 0", "sign(x + 1)*(sqrt(x**2) - 1) at -1 dir - = 2", "Abs(x + 1)/(x + 1)*(sqrt(x**2) - 1) at -1 dir - = 2",
    "(1 - (1/2 + (125283 + (x + 524288)*(x + 1)*427590 + 336054*(x + 524288)**2 + 453112*(x + 524288)**3 + 4120*(x + 524288)**4) - sqrt(2)*sin(x)/x*(106118 + (x + 524288)*(x + 1)*286435 + 215677*(x + 524288)**2 + 467167*(x + 524288)**3 + 2913*(x + 524288)**4))**2)/x**2 at 0 = -oo",
)
MODE_ROWS = tuple((row, want) for rows, want in ((HOLDING, H), (FALSE, B), (NOT_CHECKABLE, I)) for row in rows)

EXPRESSIONS = (
    ("limit(sin(x)/x, x, 0) = 1", H), ("Limit(sin(x)/x, x, 0) = 1", H), ("limit(1/x, x, oo) = 0", H), ("limit(sqrt(x), x, 0) = 0", H),
    ("limit(Abs(x)/x, x, 0) = 1", I), ("limit(Abs(x)/x, x, 0) = -1", I), ("Limit(Abs(x)/x, x, 0) = 1", I),
    ("limit(floor(x), x, 1) = 1", I), ("limit(1/x, x, 0) = oo", I),
    ("limit(Piecewise((1, x < 0), (2, true)), x, 0) = 2", I), ("Limit(Piecewise((1, x < 0), (2, true)), x, 0) = 2", I),
    ("limit(log(x), x, 0) = -oo", I), ("Limit(log(x), x, 0) = -oo", I), ("limit((sqrt(x**2) - 2)**2/(x + 2)**2, x, -2) = oo", I),
    ("Limit(1/(sqrt(x**2) + x + (x + 1)**2), x, -1) = -1/2", I), ("Limit(1/((x**4)**(1/4) + x + (x + 3)**2), x, -3) = -1/6", I),
    ("Limit(sign(x)*x/(1 - sign(x)**2), x, 0) = 0", I), ("Limit(Abs(x)*x/(Abs(x) + x), x, 0) = 0", I),
    ("Limit(1/(x*cosh(x)**2 - x*sinh(x)**2 - x + 1), x, oo) = 0", B), ("Limit(1/(x*cosh(x)**2 - x*sinh(x)**2 - x + 2), x, oo) = 0", B),
)
NUMERIC = {"numeric_expr": "limit(Abs(x)/x, x, 0)", "claimed_value": 1}

PROSE = (
    ("the right-hand limit of e^(-1/x) as x approaches 0 is 0", H), ("the right-hand side limit of e^(-1/x) as x approaches 0 is 0", H),
    ("the left-hand side limit of 1/(1 + e^(1/x)) as x approaches 0 is 1", H), ("the right-hand limit of 1/(1 + e^(1/x)) as x approaches 0 is 0", H),
    ("the right side limit of e^(-1/x) as x approaches 0 is 0", H), ("the right-side limit of e^(-1/x) as x approaches 0 is 0", H),
    ("the left side limit of 1/(1 + e^(1/x)) as x approaches 0 is 1", H), ("the left-hand limit of 1/(1 + e^(1/x)) as x approaches 0 is 1", H),
    ("the limit of sin(x)/x as x approaches 0 is 1", H), ("the right  hand limit of e^(-1/x) as x approaches 0 is 0", H), ("the right-hand\nlimit of e^(-1/x) as x approaches 0 is 0", H),
    ("the limit of e^(-1/x) as x approaches 0 is 5", B), ("the limit of sin(x)/x as x approaches 0 is 2", B), ("As shown above, the limit of sin(x)/x as x approaches 0 is 2", B),
    ("The right answer is that the limit of sin(x)/x as x approaches 0 is 2", B),
    ("the limit of e^(-1/x) as x approaches 0 is 0", I), ("on the right, the limit of e^(-1/x) as x approaches 0 is 0", I), ("from the right, the limit of e^(-1/x) as x approaches 0 is 0", I),
    ("approaching from above, the limit of e^(-1/x) as x approaches 0 is 0", I), ("for positive x, the limit of e^(-1/x) as x approaches 0 is 0", I),
    ("Both the right-hand and the left-hand limit of e^(-1/x) as x approaches 0 is 0", I), ("cf. the limit of e^(-1/x) as x approaches 0 is 0", I),
    ("Both the limit from above and the left-hand limit of e^(-1/x) as x approaches 0 is 0", I), ("Indeed, the right-hand limit of e^(-1/x) as x approaches 0 is 0", I),
)
NAMES_NO_SIDE = "the one-sided limit of e^(-1/x) as x approaches 0 is 0"
# Every side these state, or seem to, stands in words no list reaches or away from the head, so no side is read. The checker's rows at lines 155 to 166 among them.
NO_SIDE_READ = ("the limit of sin(x)/x as x approaches 0 is 1", "on the right, the limit of e^(-1/x) as x approaches 0 is 0", "from the right, the limit of e^(-1/x) as x approaches 0 is 0",
                "approaching from above, the limit of e^(-1/x) as x approaches 0 is 0", "for positive x, the limit of e^(-1/x) as x approaches 0 is 0", "cf. the limit of e^(-1/x) as x approaches 0 is 0",
                "Taking the right-hand version, the limit of e^(-1/x) as x approaches 0 is 0", "For positive x (cf. Fig. 2), the limit of e^(-1/x) as x approaches 0 is 0",
                "From the right, i.e. the limit of e^(-1/x) as x approaches 0 is 0", "With no two-sided value, for positive x the limit of e^(-1/x) as x approaches 0 is 0",
                "with x shrinking to 0 through larger values, the limit of e^(-1/x) as x approaches 0 is 0", "On the left of the page, the limit of sin(x)/x as x approaches 0 is 1",
                "Indeed, the right-hand limit of e^(-1/x) as x approaches 0 is 0", "Indeed, the two-sided limit of e^(-1/x) as x approaches 0 is 0",
                "From the right, unlike the two-sided limit of e^(-1/x) as x approaches 0 is 0", "The right-hand rather than the two-sided limit of e^(-1/x) as x approaches 0 is 0",
                "From the right, e.g. the two-sided limit of e^(-1/x) as x approaches 0 is 0", "We begin here. The right-hand limit of e^(-1/x) as x approaches 0 is 0",
                "We begin here. The two-sided limit of e^(-1/x) as x approaches 0 is 0")
OFF_THE_HEAD = ("Both the right-hand and the left-hand limit of 1/(1 + e^(1/x)) as x approaches 0 equal 1", "the right-hand and left-hand limit of 1/(1 + e^(1/x)) as x approaches 0 is 1",
                        "the right- and left-hand limit of 1/(1 + e^(1/x)) as x approaches 0 is 1", "the right side and the left side limit of 1/(1 + e^(1/x)) as x approaches 0 is 1",
                        "The right-hand limit and the left-hand limit of 1/(1 + e^(1/x)) as x approaches 0 equal 1", "Both the right-hand limit and, by symmetry, the left-hand limit of 1/(1 + e^(1/x)) as x approaches 0 equal 1",
                        "Both the right-hand limit (cf. Eq. 2) and the left-hand limit of 1/(1 + e^(1/x)) as x approaches 0 equal 1", "On the right. The left-hand limit of 1/(1 + e^(1/x)) as x approaches 0 is 1",
                "Both the limit from above and the left-hand limit of 1/(1 + e^(1/x)) as x approaches 0 equal 1", "Both the righthand limit and the left-hand limit of 1/(1 + e^(1/x)) as x approaches 0 equal 1",
                "Both the limit from above and e.g. the left-hand limit of 1/(1 + e^(1/x)) as x approaches 0 equal 1", "Both the limit from above vs. The Left-Hand limit of 1/(1 + e^(1/x)) as x approaches 0 equal 1")


ROW = re.compile(r"(?P<function>.+?) at (?P<point>.+?)(?: dir (?P<direction>\S+))? = (?P<claimed>.+)")


def params(row):
    """A row as limit mode reads it. A direction is there only where the row states one."""
    m = ROW.fullmatch(row)
    out = {"function": m["function"], "variable": "x", "point": m["point"], "claimed_limit": m["claimed"]}
    return {**out, "direction": m["direction"]} if m["direction"] else out


def equality(claim):
    a, b = claim.split(" = ")
    return {"expr_a": a, "expr_b": b}


def value(text, names=("x", "a")):
    return M._parse(text, list(names), rational=True)


def answer(text, point="0", direction="+-"):
    return M._limit_answer(value(text), sympy.Symbol("x"), value(str(point)), direction)


def on_the_list(text, point="0"):
    return M._on_the_list(value(text), sympy.Symbol("x"), value(str(point)))


@pytest.mark.parametrize("row,want", MODE_ROWS)
def test_each_limit_mode_row(row, want):
    assert read("limit", params(row)) == want


def test_the_rows_are_all_here():
    assert (len(HOLDING), len(FALSE), len(NOT_CHECKABLE)) == (64, 14, 240)


@pytest.mark.parametrize("claim,want", EXPRESSIONS)
def test_each_expression_row(claim, want):
    assert read("equality", equality(claim)) == want


def test_the_numeric_row():
    assert read("numeric", NUMERIC) == I


@pytest.mark.parametrize("text,want", PROSE)
def test_each_prose_row_through_x_limit_and_verify(text, want):
    (step,) = extract(text)
    assert step["extractor"] == "limit"
    assert verify(step["spec"])["verdict"] == want
    assert audit(text, CFG, seal=False)["verdict"] == want


def test_one_sided_names_no_side_so_it_extracts_nothing():
    assert _x_limit(NAMES_NO_SIDE) == [] and extract(NAMES_NO_SIDE) == []
    assert _x_limit(NAMES_NO_SIDE.replace("one-sided", "One-Sided")) == []


@pytest.mark.parametrize("text", NO_SIDE_READ)
def test_where_no_side_was_read_direction_is_unstated(text):
    ((_quote, _domain, spec),) = _x_limit(text)
    assert spec["params"]["direction"] == "unstated"


@pytest.mark.parametrize("text", OFF_THE_HEAD)
def test_a_side_word_off_the_head_reads_no_side_whatever_stands_before_it(text):
    """The right side runs to 0 and the left to 1, so a claim taking the last word's side would read a false HOLDS."""
    ((quote, _domain, spec),) = _x_limit(text)
    assert spec["params"]["direction"] == "unstated" and quote.lower().startswith(("limit of", "the limit of"))
    assert audit(text, CFG, seal=False)["verdict"] == I


@pytest.mark.parametrize("start", ["", "the ", "a ", "The ", "A ", "  the ", "\nthe ", "the\n"])
@pytest.mark.parametrize("word,direction", [("right-hand", "+"), ("left-hand", "-"), ("right side", "+"), ("left-hand side", "-")])
def test_the_head_is_the_start_of_the_text_after_at_most_the_or_a(start, word, direction):
    ((_quote, _domain, spec),) = _x_limit(f"{start}{word} limit of 1/x as x approaches 0 is oo")
    assert spec["params"]["direction"] == direction


@pytest.mark.parametrize("start", ["this ", "an ", "the the ", "the a ", "so the ", "(the ", "- the "])
def test_anything_else_before_a_side_is_off_the_head(start):
    ((_quote, _domain, spec),) = _x_limit(f"{start}right-hand limit of 1/x as x approaches 0 is oo")
    assert spec["params"]["direction"] == "unstated"


def test_the_same_side_named_earlier_is_off_the_head_too():
    ((_quote, _domain, spec),) = _x_limit("From the right, the right-hand limit of e^(-1/x) as x approaches 0 is 0")
    assert spec["params"]["direction"] == "unstated"


DOCUMENT = "Notes on limits.\n\nSome words here. The right-hand limit of e^(-1/x) as x approaches 0 is 0"


def test_the_head_is_the_start_of_the_text_the_caller_gave_and_a_document_is_one_text():
    """extract hands _x_limit all it was given, so a side in a document's last sentence is off the head, and the same claim given alone is at it."""
    (step,) = [step for step in extract(DOCUMENT) if step["extractor"] == "limit"]
    assert step["spec"]["params"]["direction"] == "unstated"
    (alone,) = extract(DOCUMENT.rsplit(". ", 1)[1])
    assert alone["spec"]["params"]["direction"] == "+"
    assert "start of the text the caller gave" in _x_limit.__doc__ and "a whole document" in _x_limit.__doc__


@pytest.mark.parametrize("word,direction", [("right  hand", "+"), ("right\nhand", "+"), ("right-\nhand", "+"), ("left \n hand  side", "-"), ("right   side", "+"), ("left\r\nside", "-")])
def test_space_between_side_words_is_any_run_of_spaces_or_line_breaks(word, direction):
    ((_quote, _domain, spec),) = _x_limit(f"the {word} limit of 1/x as x approaches 0 is oo")
    assert spec["params"]["direction"] == direction


def test_no_phrase_list_and_no_sentence_split_stand_in_the_extractor():
    source = inspect.getsource(M_AUDIT._x_limit).split('"""', 2)[-1]
    for word in ("above", "below", "positive", "negative", "from", "split", "sentence"):
        assert word not in source


DASHES = ("-", "\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2015", "\u2212", "\ufe58", "\ufe63", "\uff0d")


@pytest.mark.parametrize("dash", DASHES)
@pytest.mark.parametrize("word", ["one-sided", "right-sided", "left-sided", "right-handed", "left-handed", "One-Sided", "RIGHT-SIDED", "Left-Handed", "one-side", "right-hand-sided", "left-hand-sided"])
def test_a_side_word_with_any_dash_reads_as_its_hyphen_form_and_extracts_nothing(word, dash):
    text = f"the {word.replace('-', dash)} limit of e^(-1/x) as x approaches 0 is 0"
    assert _x_limit(text) == [] and extract(text) == []


@pytest.mark.parametrize("dash", DASHES)
@pytest.mark.parametrize("word,direction", [("right-hand", "+"), ("left-hand", "-"), ("right-hand side", "+"), ("left-hand side", "-"), ("right-side", "+"), ("left-side", "-")])
def test_a_side_that_carries_with_any_dash_carries(word, direction, dash):
    written = word.replace("-", dash)
    ((quote, _domain, spec),) = _x_limit(f"the {written} limit of 1/x as x approaches 0 is oo")
    assert spec["params"]["direction"] == direction and quote == f"{written} limit of 1/x as x approaches 0 is oo"


@pytest.mark.parametrize("dash", DASHES)
def test_two_sided_with_any_dash_extracts_and_states_no_side(dash):
    ((_quote, _domain, spec),) = _x_limit(f"the two{dash}sided limit of sin(x)/x as x approaches 0 is 1")
    assert "direction" not in spec["params"]


@pytest.mark.parametrize("word", ["one sided", "one side", "one-side", "right-hand sided", "left-hand sided", "right hand sided", "right sided", "left sided", "right handed", "left handed", "right", "left", "LEFT"])
def test_any_other_side_word_extracts_nothing_so_a_true_one_sided_claim_is_never_read_as_two_sided(word):
    text = f"the {word} limit of e^(-1/x) as x approaches 0 is 0"
    assert _x_limit(text) == [] and extract(text) == []


@pytest.mark.parametrize("word", ["two-sided", "two sided", "Two-Sided"])
def test_two_sided_still_extracts_and_states_no_side(word):
    ((quote, _domain, spec),) = _x_limit(f"the {word} limit of sin(x)/x as x approaches 0 is 1")
    assert "direction" not in spec["params"] and quote == "limit of sin(x)/x as x approaches 0 is 1"


@pytest.mark.parametrize("word", ["copyright", "bright", "cleft", "upper", "lower"])
def test_a_word_that_only_ends_like_a_side_is_no_side(word):
    assert len(_x_limit(f"the {word} limit of sin(x)/x as x approaches 0 is 1")) == 1


@pytest.mark.parametrize("word,direction", [("right-hand", "+"), ("left-hand", "-"), ("Right-Hand", "+"), ("LEFT-HAND", "-"), ("right hand", "+"), ("left hand", "-"),
                                            ("Right Hand", "+"), ("right-hand side", "+"), ("left-hand side", "-"), ("Right-Hand Side", "+"), ("right hand side", "+"),
                                            ("left hand side", "-"), ("right-hand-side", "+"), ("right side", "+"), ("left side", "-"), ("right-side", "+"), ("left-side", "-"),
                                            ("Right Side", "+"), ("LEFT-SIDE", "-")])
def test_a_side_written_before_limit_of_is_carried_and_kept_in_the_quote(word, direction):
    ((quote, _domain, spec),) = _x_limit(f"the {word} limit of 1/x as x approaches 0 is oo")
    assert spec["params"]["direction"] == direction
    assert quote == f"{word} limit of 1/x as x approaches 0 is oo"


@pytest.mark.parametrize("text", ["With no two-sided value, the limit of sin(x)/x as x approaches 0 is 1", "Indeed, the two-sided limit of sin(x)/x as x approaches 0 is 1"])
def test_two_sided_anywhere_but_the_head_reads_no_side(text):
    ((_quote, _domain, spec),) = _x_limit(text)
    assert spec["params"]["direction"] == "unstated"


@pytest.mark.parametrize("start", ["", "the ", "a ", "A "])
def test_two_sided_at_the_head_writes_no_direction(start):
    ((_quote, _domain, spec),) = _x_limit(f"{start}two-sided limit of sin(x)/x as x approaches 0 is 1")
    assert "direction" not in spec["params"]


# ── where a row is read ──────────────────────────────────────────────────────────────────────────────────────────────
PAST_THE_WINDOW_AT_THE_BASE = ("cosh(x) - sinh(x) at 100 = exp(-100)", "sin(pi*(cosh(x)**2 - sinh(x)**2))/x**2 at 0 = oo", "1/(1 - tan(x)*cos(x)/sin(x)) at 0 = 0",
                               "1/(3 - exp(cosh(x)**2/(x - a) - sinh(x)**2/(x - a))) at a = 0", "1/(x*(sin(x)**2 + cos(x)**2 - 1)) at 0 = 0")


@pytest.mark.parametrize("row", PAST_THE_WINDOW_AT_THE_BASE)
def test_a_row_past_the_window_at_the_base_is_read_in_the_child(row, monkeypatch):
    """Nothing reads it in this session, so with the fix left out no stuck verify stays here, and each row stays a row."""
    monkeypatch.setattr(M, "verify_limit", lambda *_a: pytest.fail("read in the session"))
    assert read("limit", params(row)) == I and CHILD.child.poll() is None


def test_a_read_past_the_window_ends_the_child_and_is_no_verdict():
    """What verify sheds is seen as a timeout, and the child goes with the thread it left."""
    trials = Trials('import sys\nprint("ready", flush=True)\nfor line in sys.stdin:\n    print(\'{"detail": "timed out"}\', flush=True)\n')
    assert trials.ask(mode="limit", params={}) is None and trials.child is None


# ── a direction ──────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("direction", ["up", "", None, 1, 0, True, ["+"], {"+": 1}, "-+", "+ -", " +", "+-+", "both"])
def test_anything_but_a_side_is_refused(direction):
    r = M.verify_limit({"function": "sin(x)/x", "variable": "x", "point": 0, "claimed_limit": 1, "direction": direction})
    assert r.status == "NOT_APPLICABLE" and r.detail.startswith(M._REFUSAL)


@pytest.mark.parametrize("row", ["sin(x)/x at 0 = 1", "1/x at 0 = oo", "Abs(x)/x at 0 = 1", "1/x at oo = 0", "sin(1/x) at 0 = 0"])
def test_absent_means_both_sides(row):
    assert read("limit", {**params(row), "direction": "+-"}) == read("limit", params(row))


def test_the_direction_is_read_by_spec_get_and_restate_names_it():
    assert 'spec.get("direction", "+-")' in inspect.getsource(M.verify_limit)
    R = _restate()
    assert R.MODES["limit"]["direction"] == R.OTHER


# ── UNREAD SIDE ──────────────────────────────────────────────────────────────────────────────────────────────────────
def unstated(row):
    return {**params(row), "direction": "unstated"}


@pytest.mark.parametrize("row,stated", [("Abs(x)/x at 0 = 1", "Abs(x)/x at 0 dir + = 1"), ("Abs(x)/x at 0 = -1", "Abs(x)/x at 0 dir - = -1"), ("exp(-1/x) at 0 = 0", "exp(-1/x) at 0 dir + = 0"),
                                        ("1/(1 + exp(1/x)) at 0 = 1", "1/(1 + exp(1/x)) at 0 dir - = 1"), ("sign(x) at 0 = -1", "sign(x) at 0 dir - = -1")])
def test_where_the_sides_disagree_a_claim_equal_to_one_side_names_direction_and_a_stated_side_reads_it(row, stated):
    r = M.verify_limit(unstated(row))
    assert r.status == "NOT_APPLICABLE" and r.detail.startswith(M._REFUSAL) and "State a direction" in r.detail
    assert read("limit", unstated(row)) == I and read("limit", params(stated)) == H


@pytest.mark.parametrize("row", ["Abs(x)/x at 0 = 2", "Abs(x)/x at 0 = 0", "1/x at 0 = 5", "exp(-1/x) at 0 = 5", "1/(1 + exp(1/x)) at 0 = 1/2", "Abs(x)/x at 0 = oo", "exp(-1/x) at 0 = -oo"])
def test_where_the_sides_disagree_a_claim_equal_to_neither_reads_broken_since_no_side_can_save_it(row):
    r = M.verify_limit(unstated(row))
    assert r.status == "MISMATCH" and "left" in r.data and "right" in r.data


@pytest.mark.parametrize("row,want", [("sin(x)/x at 0 = 1", H), ("sin(x)/x at 0 = 2", B), ("1/x**2 at 0 = oo", H), ("1/x**2 at 0 = -oo", B), ("1/x at oo = 0", H), ("x at oo = oo", I), ("sqrt(x) at 0 = 0", H),
                                      ("log(x) at 0 = -oo", I), ("floor(x) at 1 = 1", I), ("sin(x) at oo = 5", B), ("sin(x) at oo = 0", I), ("sqrt(x) at 0 = 5", B), ("log(x)/x at 0 = 5", I)])
def test_where_the_sides_agree_a_side_changes_nothing(row, want):
    assert read("limit", unstated(row)) == read("limit", params(row)) == read("limit", {**params(row), "direction": "+-"}) == want


@pytest.mark.parametrize("row", ["Abs(x)/x at 0 = 1", "exp(-1/x) at 0 = 0", "1/x at 0 = oo", "1/x at 0 = -oo"])
@pytest.mark.parametrize("direction", [None, "+-"])
def test_an_explicit_both_or_an_absent_direction_reads_broken_for_every_claimed_value(row, direction):
    spec = {**params(row), "direction": direction} if direction else params(row)
    assert read("limit", spec) == B


def test_a_side_is_compared_as_a_reading_is_by_equality_before_any_subtraction():
    assert M._equals(sympy.oo, sympy.oo) and M._equals(-sympy.oo, -sympy.oo) and not M._equals(sympy.oo, -sympy.oo) and not M._equals(sympy.oo, sympy.Integer(5))
    assert M._equals(sympy.sqrt(2)*sympy.sqrt(3), sympy.sqrt(6)) and M._equals(sympy.sin(1)**2 + sympy.cos(1)**2, sympy.Integer(1))


@pytest.mark.parametrize("row,stated", [("1/x at 0 = oo", "1/x at 0 dir + = oo"), ("1/x at 0 = -oo", "1/x at 0 dir - = -oo"), ("1/(x - 1/3)**3 at 1/3 = oo", "1/(x - 1/3)**3 at 1/3 dir + = oo")])
def test_an_infinite_side_where_zero_is_decidable_names_direction_since_a_stated_side_confirms(row, stated):
    assert "State a direction" in M.verify_limit(unstated(row)).detail
    assert read("limit", unstated(row)) == I and read("limit", params(stated)) == H


@pytest.mark.parametrize("row,stated", [("1/x + sin(x) at 0 = oo", "1/x + sin(x) at 0 dir + = oo"), ("exp(1/x) at 0 = oo", "exp(1/x) at 0 dir + = oo"), ("1/(x - sqrt(2)) at sqrt(2) = oo", "1/(x - sqrt(2)) at sqrt(2) dir + = oo")])
def test_an_infinite_side_past_decided_takes_decideds_reason_since_a_stated_side_could_not_confirm(row, stated):
    detail = M.verify_limit(unstated(row)).detail
    assert detail.startswith(M._REFUSAL) and "An infinite reading confirms only in a rational function" in detail and "State a direction" not in detail
    assert read("limit", unstated(row)) == I and read("limit", params(stated)) == I


@pytest.mark.parametrize("row", ["1/x at 0 = 5", "1/x + sin(x) at 0 = 5"])
def test_a_claim_equal_to_neither_infinite_side_reads_broken(row):
    assert read("limit", unstated(row)) == B


def test_unstated_is_for_prose_and_a_side_it_reads_is_both():
    assert M._DIRECTIONS == ("+", "-", "+-", "unstated")
    r = M.verify_limit(unstated("sin(x)/x at 0 = 1"))
    assert r.status == "CONFIRMED" and "unstated" not in r.detail


# ── (1) the list, decided before any limit runs ──────────────────────────────────────────────────────────────────────
LISTED = (
    ("sin(x)/x", "0"), ("(1 - cos(x))/x**2", "0"), ("x**2", "2"), ("(x**2 - 1)/(x - 1)", "1"), ("tan(x)/x", "0"), ("(exp(x) - 1)/x", "0"),
    ("sinh(x)/x + cosh(x) + tanh(x)", "0"), ("atan(x)/x + asin(x)/x", "0"), ("acos(x)", "0"), ("acos(x/2)", "1"), ("log(1 + x)/x", "0"),
    ("a*sin(x)/x", "0"), ("sin(a*x)/x", "0"), ("sin(x - a)/(x - a)", "a"), ("pi*x", "0"), ("0.5*x", "0"), ("E*x + sqrt(2)", "0"), ("x + 1000000", "0"), ("x/1000000", "0"),
    ("sqrt(x)", "0"), ("x**(1/3)", "0"), ("(x - 1)**(1/3)", "1"), ("sqrt(x + 1)", "0"), ("sqrt(x**2 + 1)", "0"), ("1/sqrt(x)", "0"), ("sqrt(x + 1/1000000)", "0"),
    ("log(x)", "0"), ("log(x - 1)", "1"), ("x*log(x)", "0"), ("log(x)/x", "0"), ("1/log(x)", "0"), ("log(x - 1)", "0"), ("log(1 + x)", "0"),
    ("Abs(x)", "0"), ("sign(x)", "0"), ("Abs(x)/x", "0"), ("2*sign(x)/x", "0"), ("Abs(x**2 - x)/x", "0"), ("sign(sin(x))", "0"), ("sign(x)/cos(a)", "0"),
    ("exp(1/x)", "0"), ("2*exp(1/x)", "0"), ("-exp(-1/x**2)/3", "0"), ("exp(a/x)", "0"), ("1/(1 + exp(1/x))", "0"), ("1/(2 - 3*exp(-1/x))", "0"), ("exp(1/asin(x))", "0"),
    ("exp(exp(exp(exp(x))))", "3"), ("sin(1/x)", "1"), ("exp(1/x)", "1"), ("x + exp(1/x)", "1"), ("1/x + y", "1"), ("tan(a + x)", "0"), ("1/cos(a + x)", "0"),
    ("x", "1000000"), ("x", "-1000000"), ("x", "1/1000000"), ("x", "pi/2 - 1"), ("x", "sqrt(2)/2 + 1/3"), ("x", "(2/3)**(1/3)"), ("x", "a"), ("x**2", "E"),
    ("a*log(x)", "0"), ("a*sqrt(x)", "0"), ("sqrt(3)*sqrt(x)", "0"), ("a*log(x) + b*log(x)", "0"), ("a*sqrt(3) - 3 + x", "0"), ("(a - b)*x", "0"), ("(a - b)/x**2", "0"),
)
OFF_THE_LIST = {
    "named off": (("floor(x)", "1"), ("ceiling(x)", "2"), ("frac(x)", "0"), ("Mod(x, 3)", "0"), ("x % 3", "0"), ("Max(x, 1)", "1"), ("Min(x, 1)", "1"),
                  ("Piecewise((1, x < 0), (2, true))", "0"), ("acot(x)", "0"), ("atan2(x, -1)", "0"), ("erf(x)", "0"), ("gamma(x)", "1"),
                  ("Integral(x, (x, 0, 1))*x", "0"), ("Sum(x**k, (k, 1, 3))", "0"), ("Derivative(sin(x)*y, y)", "0")),
    "a variable exponent": (("x**x", "0"), ("2**x", "0"), ("x**(1/x)", "0"), ("x**y", "1"), ("(1 + x)**(1/x)", "0")),
    "a function of a diverging argument": (("sin(1/x)", "0"), ("x*sin(1/x)", "0"), ("atan(1/x)", "0"), ("tanh(1/x)", "0"), ("log(1/x)", "0"), ("cos(log(x))", "0"),
                                           ("Abs(1/x)", "0"), ("sign(1/x)", "0"), ("sinh(sinh(1/x))", "0"), ("sqrt(1/x)", "0")),
    "a function infinite at the point": (("tan(x)", "pi/2"), ("tan(x) + 1", "pi/2"), ("atan(tan(x))", "pi/2"), ("sin(tan(x))", "pi/2")),
    "an exp with a pole elsewhere": (("1/(1 + exp(1/x)) + 1", "0"), ("x*exp(1/x)", "0"), ("exp(1/x) + 1", "0"), ("pi*exp(1/x)", "0"), ("a*exp(1/x)", "0"),
                                     ("2/(1 + exp(1/x))", "0"), ("1/(x + exp(1/x))", "0"), ("1/(pi + exp(1/x))", "0"), ("1/(1 + exp(1/x))**2", "0"),
                                     ("1/(exp(1/x) + exp(2/x))", "0"), ("exp(1/x + exp(1/x))", "0"), ("exp(exp(1/x))", "0"), ("sin(exp(1/x))", "0"),
                                     ("sqrt(1 + exp(1/x))", "0")),
    "an exp with a pole holding a log or a root": (("exp(log(x)/x)", "0"), ("exp(-log(x)/x**2)", "0"), ("exp(log(x)**2/x**2)", "0"), ("exp(sqrt(x)/x**2)", "0"),
                                                   ("exp(1/sqrt(x))", "0"), ("1/(1 + exp(log(x)/x))", "0"), ("2*exp(x**(1/3)/x**2)", "0")),
    "Abs or sign short of a factor": (("sign(x)**2", "0"), ("exp(sign(x))", "0"), ("sin(sign(x))", "0"), ("Abs(x) + 1", "0"), ("sign(x) - 1", "0"), ("1/(1 - sign(x)**2)", "0"),
                                      ("sqrt(Abs(x))", "0"), ("Abs(sign(x))", "0"), ("Abs(Abs(x) - x)", "0")),
    "another symbol in Abs or sign": (("Abs(a*x)/x", "0"), ("sign(a*x)", "0"), ("sign(x - a)", "a"), ("sign(x**2 - a*x)", "0"), ("sign(a*sin(x))", "0"), ("Abs(x + a)", "0")),
    "a symbol inside a cut": (("sqrt(x + a)", "0"), ("log(a + x)", "0"), ("log(a*x)", "0"), ("asin(a*x)", "0"), ("acos(a*x)", "0"), ("(x - a)**(1/3)", "a"), ("sqrt(a)*x", "0"),
                              ("sqrt(a - b + x)", "0")),
    "a cut the fixed irrational removes": (("(a - b)*log(x)", "0"), ("a*log(x) - b*log(x) + 1/x**2", "0"), ("a**2*log(x) - 3*log(x) + 1/x**2", "0"), ("a*b*log(x) - 3*log(x) + 1/x**2", "0"),
                                           ("sqrt(3)*log(x) - a*log(x) + 1/x**2", "0"), ("(a - b)*sqrt(x)", "0"), ("(a - sqrt(3))*log(x)", "0"), ("(a**2 - 3)*log(x)", "0"),
                                           ("a*log(x - 1) - b*log(x - 1) + 1/(x - 1)**2", "1"), ("(a - b)*x**(-2/3)", "0"), ("(a - b)*asin(x)", "1/2")),
    "a cut inside a cut": (("sqrt(sqrt(x) + 1)", "0"), ("log(1 + sqrt(x))", "0"), ("asin(log(x + 1))", "0"), ("acos(sqrt(x)/2)", "0"), ("sqrt(log(x + 2))", "0"), ("log(x + sqrt(2))", "0"),
                           ("sign(sqrt(x))", "0"), ("Abs(log(x + 1))", "0"), ("sign(asin(x + 2)*sin(x))", "0"), ("Abs(sqrt(x - 2)*cos(x))/cos(x)", "pi/2"), ("sign(log(x - 2)*x)", "0")),
    "a non-integer power of a vanishing base": (("sqrt(x**2)", "0"), ("sqrt(-x)", "0"), ("sqrt(sin(x))", "0"), ("(x**2 + x**3)**(1/3)", "0")),
    "a non-integer power of a power": (("sqrt(x**2)", "-2"), ("sqrt(x**2)", "2"), ("sqrt(x**2) - 1", "-1"), ("(x**4)**(1/4)", "-3"), ("(x**2)**(1/3)", "-1"), ("(3*x**2)**(1/3)", "-1"), ("(x**4)**(1/3) - 1", "-1"),
                                       ("1/sqrt(x**2)", "2"), ("sqrt(sin(x)**2)", "1"), ("sqrt(1/x)", "1"), ("(x**2)**(3/2)", "1"), ("sqrt((x + 1)**2)", "1")),
    "a non-integer power of a diverging base": (("(1/x)**(1/3)", "0"), ("sqrt(log(x))", "0"), ("sqrt(1/x + 1)", "0")),
    "log over a zero but x - p": (("log(sin(x))", "0"), ("log(x**2)", "0"), ("log(1 - cos(x))", "0"), ("log(x*(x + 1/10**10))", "0"), ("log(2*x - 2)", "1")),
    "asin or acos at the edge": (("asin(x)", "1"), ("acos(x)", "1"), ("asin(x)", "-1"), ("acos(x)", "-1"), ("acos(cos(x))", "0"), ("asin(cos(x))", "0"), ("acos(1 - x**2)", "0"),
                                 ("Abs(acos(cos(x**3 - x**2)))", "0")),
    "a number that is not plain": (("x + log(2)", "0"), ("x*cos(1)", "0"), ("x + exp(2)", "0"), ("x + sqrt(5 + 2*sqrt(6))", "0"), ("10**7*x", "0"), ("x/10**7", "0"), ("x + pi**2", "0"),
                                   ("x + pi*sqrt(2)", "0"), ("x + 1/pi", "0"), ("1/(x + (1 + sqrt(2))*(1 - sqrt(2)) + 1)", "0"), ("sin(x + log(2))", "0"), ("x**(1/10000000)", "1")),
    "I": (("I*x", "0"), ("(1 + I)*x", "0"), ("sin(x + I)", "0"), ("I*sin(x)/x", "0"), ("sign(I*x)", "0"), ("sign((1 + I)*cos(x)**2)", "pi/2"), ("sign(x + I*x**2)", "0"), ("Abs(x + I*x**2)/x", "0"),
          ("log(-a**2 + I*x)", "0"), ("sqrt(-a**2 + I*x)", "0")),
    "a point that is not plain": (("x", "10**7"), ("x", "1/10**7"), ("x", "I"), ("x", "2*I"), ("x", "1 + I"), ("x", "log(2)"), ("x", "cos(1)"), ("x", "exp(exp(exp(exp(3))))"), ("x", "10**100"),
                                  ("sin(x)", "atan(2) + atan(1/2)"), ("x", "2*a"), ("x", "a + 1"), ("x", "x"), ("x", "sqrt(5 + 2*sqrt(6)) - sqrt(2) - sqrt(3)"), ("x", "cosh(1)**2 - sinh(1)**2 - 1")),
    "a value unsettled": (("1/(sin(x)**2 + cos(x)**2 - 1)", "0"), ("1/(x*(sin(x)**2 + cos(x)**2 - 1))", "0"), ("1/(cosh(x)**2 - sinh(x)**2 - 1)", "1"), ("1/atan(cosh(x)**2 - sinh(x)**2 - 1)", "200"),
                          ("2/sin(cosh(x)**2 - sinh(x)**2 - 1)", "1"), ("x/(x*(1 + sqrt(2)) + x*(1 - sqrt(2)) - 2*x)", "0"), ("sign(exp(-x))", "100"), ("1/(x**5 + x**6)", "0"), ("log(exp(-x))", "100"),
                          ("sign((x + 1)**2 - x**2 - 2*x - 1)/(x - 1)", "1"), ("Abs(sin(x)**2 + cos(x)**2 - 1)/x", "0"), ("sign(sign(sin(2*x) - 2*sin(x)*cos(x)))", "pi/2"), ("sign(x**5 + x**6)", "0")),
}
OFF_ROWS = tuple((why, text, point) for why, rows in OFF_THE_LIST.items() for text, point in rows)


@pytest.mark.parametrize("text,point", LISTED)
def test_what_the_list_holds(text, point):
    assert on_the_list(text, point), (text, point)


@pytest.mark.parametrize("why,text,point", OFF_ROWS)
def test_what_the_list_leaves_off(why, text, point):
    assert not on_the_list(text, point), (why, text, point)


@pytest.mark.parametrize("why,text,point", OFF_ROWS)
@pytest.mark.parametrize("direction", ["+-", "+", "-"])
def test_off_the_list_reads_not_checkable_in_every_direction_and_no_limit_runs(why, text, point, direction, monkeypatch):
    monkeypatch.setattr(M, "limit", lambda *_a: pytest.fail("the list answers before any limit runs"))
    claim = {"function": text, "variable": "x", "point": point, "claimed_limit": 1, "direction": direction}
    r = M.verify_limit(claim)
    assert r.status == "NOT_APPLICABLE" and r.detail.startswith(M._REFUSAL) and "off the list" in r.detail


def test_a_value_the_list_cannot_read_is_off_it():
    x = sympy.Symbol("x")
    for function in ([x], {"x": 1}, sympy.Matrix([x]), sympy.true, sympy.Eq(x, 1)):
        assert M._on_the_list(function, x, sympy.Integer(0)) is False


def test_log_over_a_zero_stands_only_as_x_minus_p():
    assert on_the_list("log(x)") and on_the_list("log(x - 1)", "1") and on_the_list("log(x - pi/2)", "pi/2")
    assert not on_the_list("log(sin(x))") and not on_the_list("log(1 - cos(x))") and not on_the_list("log(1/x)")


PLAIN = ("0", "1/3", "-5/7", "1000000", "1/1000000", "-1000000/999999", "pi", "pi/2", "2*E", "sqrt(2)", "sqrt(2)/2", "(2/3)**(1/3)", "1000000**(1/3)", "1 + sqrt(2)", "pi - 3", "sqrt(2)/2 + pi/3 + 5 - E")
NOT_PLAIN = ("1000001", "1/1000001", "1000001/2", "10**100", "I", "1 + I", "log(2)", "cos(1)", "atan(2)", "exp(2)", "E**2", "pi**2", "1/pi", "sqrt(pi)", "pi*sqrt(2)", "pi*E", "(-2)**(1/3)", "sqrt(1000001)",
             "sqrt(5 + 2*sqrt(6))", "sqrt(5 + 2*sqrt(6)) - sqrt(2) - sqrt(3)", "(1 + sqrt(2))*(1 - sqrt(2)) + 1 + (1 + pi)**2", "oo")


@pytest.mark.parametrize("text", PLAIN)
def test_a_plain_number(text):
    assert M._plain(value(text))


@pytest.mark.parametrize("text", NOT_PLAIN)
def test_a_number_that_is_not_plain(text):
    assert not M._plain(value(text))


def test_a_number_the_written_form_cannot_show_is_read_as_sympy_leaves_it():
    assert value("(2/3)**(1/3)").is_Mul and M._plain(value("(2/3)**(1/3)"))
    assert value("(1 + sqrt(2))*(1 - sqrt(2)) + 1").free_symbols == set() and not M._plain(sympy.Mul(1 + sympy.sqrt(2), 1 - sympy.sqrt(2), evaluate=False) + 1)


def test_sympys_is_zero_and_is_finite_decide_nothing_on_the_list():
    for helper in (M._on_the_list, M._built_from_the_list, M._power_stands, M._reads_above_the_margin, M._vanishes, M._kept_its_digits, M._plain, M._exact, M._no_zero_hides,
                   M._past_the_bound, M._digits_cancelled):
        source = inspect.getsource(helper).split('"""', 2)[-1]
        assert "is_zero" not in source and "is_finite" not in source and "is_real" not in source


def test_what_is_zero_and_is_finite_would_have_said():
    """Why they decide nothing: each of these is a question sympy leaves open or answers wrongly."""
    assert sympy.sin(sympy.cosh(1)**2 - sympy.sinh(1)**2 - 1).is_zero is False
    assert sympy.cos(sympy.atan(2) + sympy.atan(sympy.Rational(1, 2))).is_zero is None
    assert sympy.tan(sympy.cos(2)).is_finite is None


@pytest.mark.parametrize("function,point", [("cosh(x)**2 - sinh(x)**2 - 1", "1"), ("cosh(x)**2 - sinh(x)**2 - 1", "200"), ("sin(x)**2 + cos(x)**2 - 1", "1"), ("tan(x)*cos(x) - sin(x)", "1")])
def test_a_disguised_zero_hides_at_no_size(function, point):
    """SETTLED reads no sum now: NO ZERO HIDES does, so the form is off the list whatever the sum reads."""
    assert not M._no_zero_hides(value(function), sympy.Symbol("x"), value(point)) and not on_the_list(function, point)


def test_a_sum_that_lost_its_digits_settles_nothing_whatever_it_reads():
    """At 1000 the noise of the sum stands far above the margin, so only the digits it kept can tell."""
    x, zero = sympy.Symbol("x"), value("cosh(x)**2 - sinh(x)**2 - 1")
    assert abs(zero.subs(x, 1000).evalf(40)) > 1 and not M._kept_its_digits(zero.subs(x, 1000))
    assert M._reads_above_the_margin(zero, x, sympy.Integer(1000)) and not on_the_list("cosh(x)**2 - sinh(x)**2 - 1", "1000")
    assert M._kept_its_digits(value("x + 1/3").subs(x, 1000))


def test_each_part_is_read_once_and_inner_parts_first(monkeypatch):
    """sin(x) + 1 stands twice here and reads once, since a read per node outran 12 s on nested tan."""
    x, real, parts = sympy.Symbol("x"), M._kept_its_digits, []
    monkeypatch.setattr(M, "_kept_its_digits", lambda number: parts.append(number) or real(number))
    assert M._no_zero_hides(value("(sin(x) + 1)*cos(sin(x) + 1)"), x, sympy.Integer(1))
    assert len(parts) == len(set(parts)) == 3 and parts.index(sympy.sin(1)) < parts.index(sympy.sin(1) + 1) < parts.index(sympy.cos(sympy.sin(1) + 1))


# ── NO ZERO HIDES ────────────────────────────────────────────────────────────────────────────────────────────────────
def test_keeping_its_digits_takes_every_test():
    """Neither test is enough alone. log claims digits it lost: full claimed precision, and the read at 80 says otherwise. And a retry
    can land on one working precision: the same noise at both, which only the bits it returned can show."""
    x = sympy.Symbol("x")
    claimed = value("log(cosh(x)**2 - sinh(x)**2)").subs(x, 54)
    assert claimed.evalf(40)._prec >= 100 and claimed.evalf(40) != 0 and not M._kept_its_digits(claimed)
    spun = value("tan(pi*(cosh(x) - sinh(x))*exp(x))").subs(x, 133)
    assert spun.evalf(40) == spun.evalf(80) and spun.evalf(40)._prec < 100 and not M._kept_its_digits(spun)
    assert not M._kept_its_digits(sympy.Integer(0))
    for number in (sympy.Integer(3), sympy.sqrt(2), sympy.sin(1), sympy.exp(-100), sympy.log(2)*sympy.I + 1, sympy.Rational(1, 10**40)):
        assert M._kept_its_digits(number)


def spied_digits(monkeypatch):
    real, seen = M._kept_its_digits, []
    monkeypatch.setattr(M, "_kept_its_digits", lambda number: seen.append(number) or real(number))
    return seen


NEAR = sympy.sqrt(2) / 10**7


@pytest.mark.parametrize("function,point,read_there", [
    ("tan(x - 1)/(x - 1)", "1", sympy.sqrt(2)/10**7),                               # a sum exactly 0 at the point
    ("1/x + 1/x**2", "0", 1/NEAR + 1/NEAR**2),                                      # a sum with no finite value there
    ("sqrt(x)", "0", sympy.sqrt(NEAR)),                                             # a non-integer power exactly 0 there
    ("sin(x)", "0", sympy.sin(NEAR)),                                               # a call exactly 0 there
    ("sin(x) + 1", "1", sympy.sin(1) + 1),                                          # one with a finite value reads at the point
])
def test_where_a_part_is_read(function, point, read_there, monkeypatch):
    seen = spied_digits(monkeypatch)
    assert M._no_zero_hides(value(function), sympy.Symbol("x"), value(point))
    assert read_there in seen


@pytest.mark.parametrize("function", ["log(x)", "1/sqrt(x)", "exp(1/x)", "log(x)/x"])
def test_a_call_or_a_power_with_no_finite_value_is_not_read(function, monkeypatch):
    seen = spied_digits(monkeypatch)
    assert M._no_zero_hides(value(function), sympy.Symbol("x"), sympy.Integer(0)) and seen == []


def test_the_other_symbols_are_the_fixed_irrational_in_what_is_read(monkeypatch):
    seen = spied_digits(monkeypatch)
    assert M._no_zero_hides(value("sin(a + x)"), sympy.Symbol("x"), sympy.Integer(1))
    assert seen[-1] == sympy.sin(1 + sympy.sqrt(3))


@pytest.mark.parametrize("function,point,stands", [
    ("exp(exp(exp(exp(x))))", "3", True), ("exp(exp(exp(exp(x))))*sin(x)", "3", True), ("(1 + exp(exp(x)))**10000", "40", True),     # exp, a product and a power past it
    ("sin(exp(exp(exp(x))))", "3", False), ("cos(exp(exp(exp(x))))", "3", False), ("atan(x**70)", "2", False), ("sign(exp(exp(exp(x))))", "3", False),      # any other call
    ("x + exp(exp(x))", "50", False), ("1 + (1 + exp(exp(x)))**10000", "40", False), ("exp(exp(exp(exp(x)))) - 1", "3", False),      # a sum holding a part past it
    ("sin(1 + exp(exp(exp(x)))*x)", "3", False), ("exp(1 + exp(exp(exp(exp(x)))))", "3", False),                                     # past it, one part down
])
def test_only_exp_stands_past_the_reads_bound(function, point, stands):
    assert M._no_zero_hides(value(function), sympy.Symbol("x"), value(point)) is stands


# exp of this point stands just inside the read's bound, and exp of the point at the read's distance just past it.
EDGE_OF_THE_BOUND = "226153/4677"


def test_a_part_that_needs_the_distance_and_stands_past_the_bound_there_is_off():
    x, edge = sympy.Symbol("x"), value(EDGE_OF_THE_BOUND)
    assert sympy.exp(edge).evalf(40) < M._READ_BOUND < sympy.exp(edge + NEAR).evalf(40)
    form = "(x - @)*exp(exp(x)) + (x - @)**2"
    assert M._no_zero_hides(value(form.replace("@", "48")), x, sympy.Integer(48)) is True
    assert M._no_zero_hides(value(form.replace("@", EDGE_OF_THE_BOUND)), x, edge) is False


def test_each_read_is_bound_before_it_runs(monkeypatch):
    """Nothing past the bound reaches a call: the bound reads the argument, and what holds a part past it is never read."""
    x, read_args, form, past = sympy.Symbol("x"), [], value("cos(exp(exp(exp(x))))"), sympy.cos(sympy.exp(sympy.exp(sympy.exp(3))))
    real = sympy.Expr.evalf

    def spy(self, *args, **kwargs):
        read_args.append(self)
        return real(self, *args, **kwargs)
    monkeypatch.setattr(sympy.Expr, "evalf", spy)
    assert M._no_zero_hides(form, x, sympy.Integer(3)) is False
    assert past not in read_args and past.args[0] in read_args


TOO_LARGE_TO_WORK_OUT = (("((x**1000 + 1)**1000 + 1)**1000", "7"), ("1/((x**1000 + 1)**1000 + 1)**1000", "7"), ("sin(((x**1000 + 1)**1000 + 1)**1000)", "7"), ("exp(x**40*log(x))", "2"),
                         ("1 + exp(x**70*log(x))", "2"), ("((a**1000 + 1)**1000 + 1)**1000*x", "0"), ("((1/x**1000 + 1)**1000 + 1)**1000 + 1/x", "0"))


@pytest.mark.parametrize("function,point", TOO_LARGE_TO_WORK_OUT)
def test_an_exact_read_is_held_to_the_parsers_own_power_bound(function, point, monkeypatch):
    """An exact read works a power out in full, so each of these ran on, in sympy's limit at the base and in a read here, and the bound
    stands before anything reads it. No limit runs."""
    monkeypatch.setattr(M, "limit", lambda *_a: pytest.fail("the list answers before any limit runs"))
    assert not on_the_list(function, point)
    assert read_here("limit", {"function": function, "variable": "x", "point": point, "claimed_limit": "1"}) == I


def test_the_bound_on_a_power_binds_only_where_a_read_stands():
    """The distance is read only where a part needs it, so a power it would take past the bound is no reason on its own."""
    assert on_the_list("(x**1000 + 1)**1000", "0") and read("limit", params("(x**1000 + 1)**1000 at 0 = 1")) == H
    assert on_the_list("exp(x**2*log(x))", "3")


@pytest.mark.parametrize("row", ["(sin(x)**2 + cos(x)**2 - 1)/(x - 1)**2 at 1 = -oo", "(sin(x)**2 + cos(x)**2 - 1)/(x - 3)**2 at 3 = -oo", "1/(x - 2)**2 - (sin(x)**2 + cos(x)**2 - 1)/(x - 2)**4 at 2 = -oo",
                                 "sin(x)**2/(x - 1000)**2 + cos(x)**2/(x - 1000)**2 - 1/(x - 1000)**2 at 1000 = -oo", "log(cosh(x)**2 - sinh(x)**2)/(x - 1)**2 at 1 = oo",
                                 "sin(pi*(cosh(x)**2 - sinh(x)**2))/x**2 at 0 = oo", "1/(1 - tan(x)*cos(x)/sin(x)) at 0 = 0"])
def test_a_zero_that_is_zero_everywhere_is_off_the_list_wherever_it_stands(row):
    spec = params(row)
    assert row in NOT_CHECKABLE and not M._no_zero_hides(value(spec["function"]), sympy.Symbol("x"), value(spec["point"]))


@pytest.mark.parametrize("row", ["2*(tan(x)*cos(x) - sin(x))/(x - 0.1)**2 at 0.1 = 0", "(tan(x)*cos(x) - sin(x))/sin(x - 0.1) at 0.1 = 0", "exp((tan(x)*cos(x) - sin(x))/(x - 0.1)) at 0.1 = 0",
                                 "1/(3 - exp(cosh(x)**2/(x - a) - sinh(x)**2/(x - a))) at a = 0"])
def test_what_an_exact_read_of_a_decimal_ran_on_is_off_before_any_limit_runs(row, monkeypatch):
    """sympy's own limit does not finish on these exact values, where the base's float read the disguised zero as noise."""
    monkeypatch.setattr(M, "limit", lambda *_a: pytest.fail("the list answers before any limit runs"))
    assert read_here("limit", params(row)) == I


# ── the whole form's count ───────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("function,point,digits", [
    ("cosh(x) - sinh(x)", "10", 8.385), ("cosh(x) - sinh(x)", "12", 10.12), ("(cosh(x) - sinh(x))**2", "5", 2*4.04), ("sqrt(cosh(x) - sinh(x))", "10", 8.385/2),
    ("sin(cosh(x) - sinh(x))", "10", 8.385), ("cosh(x) - sinh(x) + sin(cosh(x) - sinh(x))", "10", 8.084 + 8.385),
    ("x - 1", "1", 0), ("1/x + 1/x**2", "0", 0), ("x**5 + x**7", "0", 0), ("x + 1", "2", 0),
])
def test_the_digits_a_form_cancels(function, point, digits):
    """Between the largest term and the sum, times the powers it stands under, added across the form. A sum exactly 0 at the point, or
    with no finite value there, counts nothing."""
    assert abs(M._digits_cancelled(value(function), sympy.Symbol("x"), value(point)) - digits) < 0.02


def test_the_count_binds_above_ten_digits_and_no_margin_applies():
    assert on_the_list("cosh(x) - sinh(x)", "11") and not on_the_list("cosh(x) - sinh(x)", "12")
    assert on_the_list("(cosh(x) - sinh(x))**2", "5") and not on_the_list("(cosh(x) - sinh(x))**4", "5")
    assert on_the_list("x**5 + x**7") and read("limit", params("x**5 + x**7 at 0 = 0")) == H


@pytest.mark.parametrize("row", ["acos((cosh(2*x/3) - 2*sinh(x/3)**2)/2) at 363 = -pi/3", "acos((cosh(2*x/3) - 2*sinh(x/3)**2)/2) at 363.0 = -pi/3",
                                 "acos((cosh(2*x/3) - 2*sinh(x/3)**2)/2) at 363.5 = -pi/3", "acos((cosh(x) - 2*sinh(x/2)**2)/2) at 69.0 = -pi/3", "sign(cosh(2*x/3) - 2*sinh(x/3)**2) at 451 = -1"])
def test_a_finite_reading_that_rests_on_a_far_cancelling_sum_is_off(row):
    """Each sum here keeps its digits, and sympy's reading of it is wrong: the count is what takes it off, a decimal point the same as its exact one."""
    spec = params(row)
    assert row in NOT_CHECKABLE
    assert M._no_zero_hides(value(spec["function"]), sympy.Symbol("x"), value(spec["point"]))
    assert M._digits_cancelled(value(spec["function"]), sympy.Symbol("x"), value(spec["point"])) > 10


# ── EXACT ────────────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("function,point,stands", [
    ("1/x - 1/sin(x)", "0", True), ("(1 + cos(x))/(x - pi)**2", "pi", True), ("(x**2 - 2)/(x - sqrt(2))", "sqrt(2)", True), ("sin(x - a)/(x - a)", "a", True), ("exp(1/x)", "0", True),
    ("exp(x)", "1", True), ("sin(x) + sqrt(2)", "1", True), ("1/x**2 + sin(x)", "0", True), ("sqrt(2)*sin(x)/x", "0", True), ("x/(x - sqrt(2))", "1", True),      # no pole, or every part rational
    ("exp(x)/(x - 1)**2", "1", False), ("(exp(x) - E)/(x - 1)", "1", False), ("sin(x)/(x - a)", "a", False), ("sqrt(2)*(x + 1) + 1/x", "0", False),                  # a part irrational beside a pole
    ("(a + x)/x", "0", False), ("acos(x)/x", "0", False), ("x*(x + sqrt(2))/x**2", "0", False), ("(x + 1)**2*(x**2 - 2)/(x - sqrt(2))", "sqrt(2)", False),
])
def test_a_pole_has_every_other_part_rational_at_the_point(function, point, stands):
    assert M._exact(value(function), sympy.Symbol("x"), value(point)) is stands


def test_exact_reads_nothing_numeric(monkeypatch):
    x, inexact, exact = sympy.Symbol("x"), value("exp(x)/(x - 1)**2"), value("sin(x)/x")
    monkeypatch.setattr(sympy.Expr, "evalf", lambda *_a, **_k: pytest.fail("EXACT is sympy's own evaluation at the point"))
    assert M._exact(inexact, x, sympy.Integer(1)) is False and M._exact(exact, x, sympy.Integer(0)) is True


def test_a_plain_polynomial_with_a_surd_in_it_is_bound_as_a_call_is():
    """A coefficient needs no call to be irrational: every number in S is plain, S is 1/2 + (1 - sqrt(2))**70 at 0, and a 2-digit read took 1 - S**2 below 0."""
    row = next(row for row in NOT_CHECKABLE if row.startswith("(1 - (1/2 + 125283"))
    spec = params(row)
    assert not M._exact(value(spec["function"]), sympy.Symbol("x"), value(spec["point"]))
    assert read("limit", spec) == I


# ── Abs and sign, by place ───────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("function", ["Abs(x)/x", "2*Abs(x)/x**2", "sign(x)*x", "sign(x)*Abs(x)", "sign(x)*sign(x + 1)", "-Abs(x)", "Abs(x)*(x + 1)"])
def test_abs_and_sign_stand_as_factors_of_the_whole_product(function):
    assert on_the_list(function)


@pytest.mark.parametrize("function", ["Abs(x)/(Abs(x) + x)", "Abs(x)*sin(Abs(x))", "sign(x)*x/(1 - sign(x)**2)", "Abs(x)*(Abs(x) + 1)", "sign(x)*exp(sign(x))", "Abs(x)*x/(Abs(x) + x)", "x*Abs(x)/(Abs(x) + x)**2",
                                      "sign(x - 2)*Abs(x - 2)/(Abs(x - 2) + x - 2)", "Abs(x)*Abs(Abs(x) + 1)", "sign(x)/(2 + sign(x))"])
def test_a_factor_does_not_license_the_same_one_elsewhere(function):
    """Each is decided by the place of each one in the form, and never by its value."""
    assert not on_the_list(function)


def test_a_read_at_the_margin():
    x = sympy.Symbol("x")
    assert M._reads_above_the_margin(value("exp(-x)"), x, sympy.Integer(60)) and not M._reads_above_the_margin(value("exp(-x)"), x, sympy.Integer(100))
    assert not M._reads_above_the_margin(value("exp(x)"), x, sympy.Integer(10)**22)     # past the read's bound
    assert read("limit", params("sign(exp(-x)) at 60 = 1")) == H and read("limit", params("sign(exp(-x)) at 100 = 1")) == I
    assert read("limit", params("1/(x**3 + x**4) at 0 dir + = oo")) == H and read("limit", params("1/(x**5 + x**6) at 0 dir + = oo")) == I


def test_a_base_exactly_zero_reads_above_the_margin_at_the_reads_distance():
    x, near = sympy.Symbol("x"), sympy.sqrt(2) / 10**7
    assert M._reads_above_the_margin(x, x, near) and not M._reads_above_the_margin(value("x**5 + x**6"), x, near)
    assert not on_the_list("x/(x*(1 + sqrt(2)) + x*(1 - sqrt(2)) - 2*x)")


EXPANDED = ("sqrt(x*(a + b + c + d + e + f + g)**30) at 0 = 0", "sqrt((x - 1)**10000) at 1 = 0")


@pytest.mark.parametrize("row", EXPANDED)
def test_nothing_on_the_list_expands(row, monkeypatch):
    """Past verify's window a claim reads SYSTEM_ERROR, so reading not checkable is the time bound, and the spies are the count."""
    assert read("limit", params(row)) == I
    monkeypatch.setattr(M._sp, "expand", lambda *_a, **_k: pytest.fail("the list reads structure"))
    monkeypatch.setattr(sympy.Expr, "expand", lambda *_a, **_k: pytest.fail("the list reads structure"))
    assert not on_the_list(params(row)["function"], params(row)["point"])


@pytest.mark.parametrize("function,point", [("sqrt(x)", "4"), ("sqrt(x + 5)", "-1"), ("sqrt(x**2 + 1)", "-2"), ("sqrt(x*(x + 1))", "-2"), ("sqrt(x*(x + 1))", "1"), ("(x**2 + x)**(1/3)", "1"), ("sqrt(1 - x)", "-3")])
def test_a_root_of_a_bare_variable_a_sum_or_a_product_stands(function, point):
    assert on_the_list(function, point)


def test_sympy_folds_a_power_of_a_power_and_loses_the_branch():
    """Under a sum that cancels at a negative point sqrt(x**2) reads as x, and bare it does not. (3*x**2)**(1/3) reads the same, the number splitting off first."""
    x = sympy.Symbol("x")
    assert sympy.limit(value("sqrt(x**2) - 1"), x, -1) == -2 and value("sqrt(x**2) - 1").subs(x, -1) == 0
    assert sympy.limit(value("sqrt(x**2)"), x, -2) == 2
    three = value("(3*x**2)**(1/3)")
    assert three.is_Mul and any(part.is_Pow and part.base.is_Pow for part in three.args)


@pytest.mark.parametrize("row", ["sqrt(x**2)/x at oo = 1", "sqrt(x**2)/x at -oo = -1", "1/sqrt(x**2) at oo = 0"])
def test_a_power_of_a_power_at_an_infinity_is_not_touched(row, monkeypatch):
    """No form is listed there, so these read as at the base."""
    monkeypatch.setattr(M, "_on_the_list", lambda *_a: pytest.fail("the list is for a finite point"))
    assert read_here("limit", params(row)) == H


def test_x_minus_p_is_read_by_structure_alone():
    assert on_the_list("sqrt(x - 1)", "1") and on_the_list("sqrt(x - pi/2)", "pi/2")
    assert not on_the_list("sqrt(x*(x + 1) - x**2)", "0") and not on_the_list("sqrt(2*x - 2)", "1")


UNDECIDED = "atan(2) + atan(1/2)"       # pi/2, which subs does not reduce


@pytest.mark.parametrize("function", ["tan(x)", "1/cos(x)", "sign(cos(x))", "Abs(cos(x))", "log(cos(x))", "sqrt(cos(x))", "x/cos(x)", "1/(1 - sin(x))"])
def test_a_point_that_hides_its_value_is_off_the_list(function, monkeypatch):
    assert not on_the_list(function, UNDECIDED)
    monkeypatch.setattr(M, "limit", lambda *_a: pytest.fail("the list answers before any limit runs"))
    assert read_here("limit", {"function": function, "variable": "x", "point": UNDECIDED, "claimed_limit": "1"}) == I


@pytest.mark.parametrize("row", ["tan(x) at 1 = tan(1)", "tan(cos(x)) at 2 = tan(cos(2))", "1/cos(x) at 0 = 1", "1/cos(x) at 2 = 1/cos(2)", "log(cos(x)) at 1 dir + = log(cos(1))",
                                 "sign(cos(x)) at 2 = -1", "Abs(cos(x)) at 2 = -cos(2)", "sqrt(cos(x) + 2) at 2 = sqrt(cos(2) + 2)", "tan(x) at pi/4 = 1"])
def test_a_value_that_settles_stands(row):
    assert read("limit", params(row)) == H


FREE_SYMBOLS = ("a*sin(x)/x at 0 = a", "tan(a + x) at 0 = tan(a)", "1/cos(a + x) at 0 = 1/cos(a)", "sign(x)/cos(a) at 0 dir + = 1/cos(a)", "exp(a*x) at 0 = 1", "cos(a*x)/a at 0 = 1/a",
                "1/(a + x) at 0 = 1/a", "sin(x - a)/(x - a) at a = 1", "tanh(x + a) at 0 = tanh(a)")


@pytest.mark.parametrize("row", FREE_SYMBOLS)
def test_a_value_with_a_free_symbol_that_hides_nothing_stands(row):
    assert read("limit", params(row)) == H


TOWER_UNDER_TAN = "tan(exp(exp(exp(x)))) at 3 = tan(exp(exp(exp(3))))"


def test_a_value_past_the_reads_bound_is_not_settled():
    """No is_zero runs on this, and it did not finish: the read's bound stands first, and the form is off the list."""
    assert read("limit", params(TOWER_UNDER_TAN)) == I


# Every input the reviews at lines 80, 83, 85, 92, 94 and 96 found that is no row of the plan's, with what it reads.
REVIEWED = (
    "tan(x) at atan(2) + atan(1/2) = tan(atan(2) + atan(1/2))", "1/cos(x) at atan(2) + atan(1/2) = 1/cos(atan(2) + atan(1/2))", "log(x - 10**70)/(x - 10**70) at 10**70 dir - = oo",
    "1/atan(cosh(x)**2 - sinh(x)**2 - 1) at 1 = 1/atan(cosh(1)**2 - sinh(1)**2 - 1)", "exp(-log(x)/x**2) at 0 dir - = oo", "exp(log(x)**2/x**2) at 0 dir - = oo",
    "sqrt(x - 10**100) at 10**100 dir + = 0", "sin(sqrt(x**2 + 2)) at 2*I = I*sinh(sqrt(2))",
    "a*log(x) at 0 dir - = -oo*sign(a)", "(a - b)*x**(-2/3) at 0 dir - = -oo*(-1)**(1/3)*sign(a - b)", "(a - b)/x**2 at 0 = oo*sign(a - b)",
    "(sin(a)**2 + cos(a)**2 - 1)/x**2 at 0 = oo*sign(sin(a)**2 + cos(a)**2 - 1)", "(a*(a + 1) - a**2 - a)/x at 0 dir + = oo*sign(a*(a + 1) - a**2 - a)",
)
# The true claim on a coefficient 0 at every value of its symbol, which read BROKEN as at the base until line 122: NO ZERO HIDES reads the
# coefficient at the fixed irrational, where it lost its digits, so the form is off the list and the claim is not checkable.
COEFFICIENT_ZERO_EVERYWHERE = ("((a + 1)**2 - a**2 - 2*a - 1)/x**2 at 0 = 0", "(sin(a)**2 + cos(a)**2 - 1)/x**2 at 0 = 0", "(a*(a + 1) - a**2 - a)/x at 0 dir + = 0")


@pytest.mark.parametrize("row", REVIEWED)
def test_every_input_the_reviews_found_reads_not_checkable(row):
    assert read("limit", params(row)) == I


@pytest.mark.parametrize("row", COEFFICIENT_ZERO_EVERYWHERE)
def test_a_true_claim_on_a_coefficient_that_is_zero_everywhere_reads_not_checkable(row):
    spec = params(row)
    assert row in NOT_CHECKABLE and read("limit", spec) == I
    assert not M._no_zero_hides(value(spec["function"]), sympy.Symbol("x"), value(spec["point"]))


DECIMALS = (
    ("sign(3*x - 0.3) at 0.1 = 1", B), ("Abs(3*x - 0.3)/(3*x - 0.3) at 0.1 = 1", B), ("1/(3*x - 0.3) at 0.1 = 18014398509481984", B),
    ("sign(3*x - 3/10) at 1/10 = 1", B), ("sign(3*x - 0.3) at 0.1 dir + = 1", H), ("sign(3*x - 0.3) at 0.1 dir - = -1", H), ("1/(3*x - 0.3) at 0.1 dir + = oo", H),
    ("x + 0.1 at 0.2 = 0.3", H), ("0.1*x at 3 = 0.3", H), ("x**0.5 at 4 = 2", H), ("x/3 at 0.3 = 0.1", H),
)


@pytest.mark.parametrize("row,want", DECIMALS)
def test_a_decimal_reads_as_what_it_writes(row, want):
    assert read("limit", params(row)) == want


def test_a_decimal_point_given_as_a_number_reads_the_same():
    assert read("limit", {"function": "sign(3*x - 0.3)", "variable": "x", "point": 0.1, "claimed_limit": 1}) == B


@pytest.mark.parametrize("claim,want", [("limit(sign(3*x - 0.3), x, 0.1) = 1", I), ("limit(1/(3*x - 0.3), x, 0.1) = 18014398509481984", I), ("limit(x + 0.1, x, 0.2) = 0.3", H)])
def test_the_functions_read_a_decimal_the_same_way(claim, want):
    assert read("equality", equality(claim)) == want


# ── (2) at oo or -oo ─────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("function,point,claimed,want", [
    ("1/x", "oo", "0", H), ("1/x", "-oo", "0", H), ("exp(x)", "-oo", "0", H), ("exp(x)", "oo", "oo", I), ("x**2", "-oo", "oo", I), ("-x", "oo", "-oo", I),
    ("(1 + 1/x)**x", "oo", "E", H), ("floor(x)/x**2", "oo", "0", H), ("1/x", "oo", "1", B), ("x", "oo", "-oo", B), ("x", "oo", "5", B),
])
@pytest.mark.parametrize("direction", [None, "+", "-", "+-"])
def test_at_an_infinity_direction_changes_nothing_nothing_is_read_and_only_an_infinite_reading_is_lost(function, point, claimed, want, direction, monkeypatch):
    monkeypatch.setattr(M, "_on_the_list", lambda *_a: pytest.fail("the list is for a finite point"))
    monkeypatch.setattr(M, "_off_the_reals", lambda *_a: pytest.fail("no side is read at an infinity"))
    claim = {"function": function, "variable": "x", "point": point, "claimed_limit": claimed}
    assert read_here("limit", {**claim, "direction": direction} if direction else claim) == want


# ── (3) the sides in use ─────────────────────────────────────────────────────────────────────────────────────────────
def spied_limit(monkeypatch, wanted=None):
    real, seen = M.limit, []

    def spy(function, variable, point, side):
        seen.append(side)
        return wanted[side] if wanted and side in wanted else real(function, variable, point, side)
    monkeypatch.setattr(M, "limit", spy)
    return seen


@pytest.mark.parametrize("direction,sides", [("+-", ["+", "-"]), ("+", ["+"]), ("-", ["-"])])
def test_both_sides_are_read_for_both_and_one_for_a_stated_direction(direction, sides, monkeypatch):
    seen = spied_limit(monkeypatch)
    assert set(answer("sin(x)/x", 0, direction)[1]) == set(sides)
    assert seen == sides


@pytest.mark.parametrize("failing,direction,want", [("-", "+-", I), ("+", "+-", I), ("-", "-", I), ("-", "+", H), ("+", "-", H)])
def test_a_failure_on_a_side_in_use_reads_not_checkable(failing, direction, want, monkeypatch):
    real = M.limit

    def failing_side(function, variable, point, side):
        if side == failing:
            raise RuntimeError("sympy gave up")
        return real(function, variable, point, side)
    monkeypatch.setattr(M, "limit", failing_side)
    assert read_here("limit", {**params("sin(x)/x at 0 = 1"), "direction": direction}) == want


@pytest.mark.parametrize("build", [lambda sp: sp.Limit(sp.Symbol("x"), sp.Symbol("x"), 0), lambda sp: sp.nan, lambda sp: sp.zoo,
                                   lambda sp: sp.Integer(1) + sp.Limit(sp.sin(sp.Symbol("y")), sp.Symbol("y"), 0)])
def test_a_side_with_no_value_reads_not_checkable(build, monkeypatch):
    spied_limit(monkeypatch, {"-": build(sympy)})
    assert read_here("limit", params("sin(x)/x at 0 = 1")) == I
    assert read_here("limit", {**params("sin(x)/x at 0 = 1"), "direction": "+"}) == H


# ── (4) the one numeric read ─────────────────────────────────────────────────────────────────────────────────────────
def spied_read(monkeypatch):
    real, seen = M._off_the_reals, []

    def spy(function, variable, at):
        seen.append((function, at))
        return real(function, variable, at)
    monkeypatch.setattr(M, "_off_the_reals", spy)
    return seen


def test_the_read_stands_at_the_distance_the_plan_states(monkeypatch):
    seen = spied_read(monkeypatch)
    assert read_here("limit", params("log(x)/x at 0 = -oo")) == I
    near = sympy.sqrt(2) / 10**7
    assert [abs(at - sign*near) < sympy.Float("1e-70") for (_function, at), sign in zip(seen, (1, -1))] == [True, True] and len(seen) == 2


def test_every_other_symbol_is_one_fixed_irrational_the_same_for_each_in_the_function_and_the_point(monkeypatch):
    seen = spied_read(monkeypatch)
    answer("b*sin(x - a)", "a", "+")
    ((function, at),) = seen
    x, root3 = sympy.Symbol("x"), sympy.sqrt(3)
    assert function == root3*sympy.sin(x - root3) and abs(at - (root3 + sympy.sqrt(2) / 10**7)) < sympy.Float("1e-70")


@pytest.mark.parametrize("mapping", [{"x": "x", "a": "b", "b": "a"}, {"x": "a", "a": "b", "b": "x"}, {"x": "zz", "a": "x", "b": "a"}, {"x": "y", "a": "c", "b": "d"}])
def test_no_rename_moves_the_read(mapping):
    """By name order a - b read as one side of zero, and renamed as the other. One value for each leaves it 0 under every name, and a
    cut that value removes takes the form off the list."""
    for row, want in (("a*sqrt(x) at 0 dir + = 0", H), ("a*sqrt(x) at 0 dir - = 0", I), ("(a - b)*sqrt(x) at 0 dir + = 0", I), ("(a - b)*sqrt(x) at 0 dir - = 0", I),
                      ("sqrt(a - b + x) at 0 dir + = sqrt(a - b)", I), ("(a - b)*sin(x)/x at 0 dir + = a - b", H)):
        assert read("limit", params(row)) == want
        assert read("limit", renamed_params(params(row), mapping)) == want


def test_a_symbol_only_the_point_holds_is_fixed_too(monkeypatch):
    seen = spied_read(monkeypatch)
    answer("sqrt(x)", "a", "+")
    assert abs(seen[0][1] - (sympy.sqrt(3) + sympy.sqrt(2) / 10**7)) < sympy.Float("1e-70")


def test_no_read_runs_where_the_sides_agree_and_no_direction_is_stated(monkeypatch):
    monkeypatch.setattr(M, "_off_the_reals", lambda *_a: pytest.fail("where sympy's sides agree it refuses nothing"))
    for row in ("sqrt(x) at 0 = 0", "x*log(x) at 0 = 0", "sin(x)/x at 0 = 1"):
        assert read_here("limit", params(row)) == H
    assert read_here("limit", params("log(x) at 0 = -oo")) == I      # DECIDED's, and no read's


@pytest.mark.parametrize("row", ["sqrt(x) at 0 dir - = 0", "log(x)/x at 0 = -oo", "1/sqrt(x) at 0 = oo", "log(x)**3/x**3 at 0 = -oo"])
def test_a_function_that_leaves_the_reals_names_direction_as_what_would_bind_it(row):
    detail = M.verify_limit(params(row)).detail
    assert detail.startswith(M._REFUSAL) and "leaves the reals" in detail and "State a direction" in detail


def test_the_read_refuses_only_on_a_non_zero_imaginary_part():
    x = sympy.Symbol("x")
    assert M._leaves_the_reals(value("sqrt(x)"), x, sympy.Integer(0), "+") is None
    assert M._leaves_the_reals(value("sqrt(x)"), x, sympy.Integer(0), "+-") == "-"
    assert M._leaves_the_reals(value("sqrt(-x)"), x, sympy.Integer(0), "+") == "+"
    assert M._leaves_the_reals(value("x**2"), x, sympy.Integer(0), "+-") is None


@pytest.mark.parametrize("row,want", MODE_ROWS)
def test_a_read_unread_marks_nothing_and_the_read_only_ever_refuses(row, want, monkeypatch):
    """With every read left unread, a row reads what sympy's sides alone say. The read can only turn that into not checkable."""
    monkeypatch.setattr(M, "_off_the_reals", lambda *_a: False)
    unread = read_here("limit", params(row))
    assert want == unread or want == I


def test_no_other_numeric_test_runs_at_runtime():
    for helper in (M._limit_answer, M._limit_call, M._on_the_list, M._built_from_the_list, M._power_stands, M._exact, M.verify_limit):
        assert "evalf" not in inspect.getsource(helper) and ".n(" not in inspect.getsource(helper)
    numeric = (M._on_the_list, M._built_from_the_list, M._power_stands, M._exact, M._no_zero_hides, M._kept_its_digits, M._past_the_bound, M._digits_cancelled, M._reads_above_the_margin)
    assert not [helper for helper in numeric if "expand" in inspect.getsource(helper).split('"""', 2)[-1]]
    assert inspect.getsource(M._leaves_the_reals).count("evalf") == 1      # the distance, and no value


@pytest.mark.parametrize("function,at,read_it", [
    ("exp(x)", 10**21, True), ("exp(x)", 10**21 + 1, False), ("sin(x)", 10**21, True), ("sin(x)", 10**21 + 1, False),
    ("exp(-x)", 10**21 + 1, False), ("x**2", 10**30, True), ("(2 + exp(x))**10000", 10**17, True), ("(2 + exp(x))**10000", 10**18, False),
    ("sinh(sinh(x))", 45, True), ("sinh(sinh(x))", 50, False), ("cos(exp(x))", 48, True), ("cos(exp(x))", 49, False),
])
def test_past_the_bound_a_read_stays_unread(function, at, read_it):
    """A factor of I shows whether the value was read: a value read is off the reals, and one unread marks nothing."""
    assert M._off_the_reals(sympy.I*value(function), sympy.Symbol("x"), sympy.Integer(at)) is read_it


SPIRALLING = ("exp(log(x)/x**3) at 0 dir - = oo", "exp(-log(x)/x**4) at 0 dir - = oo", "exp(log(x)**2/x**4) at 0 dir - = oo")


@pytest.mark.parametrize("row", SPIRALLING)
def test_a_function_off_the_reals_past_the_bound_reads_not_checkable(row):
    """Each argument is past the bound at the read's distance, and its modulus grows while its phase spins, so no limit exists. An
    exp with a pole holds no log, so the list refuses each, and the read, which marks a part off the reals before its bound, sees them too."""
    function, x = value(params(row)["function"]), sympy.Symbol("x")
    near = -sympy.sqrt(2) / 10**7
    assert M._inner_reads(function, x, near) == (True, True)
    detail = M.verify_limit(params(row)).detail
    assert detail.startswith(M._REFUSAL) and "off the list" in detail


def test_the_imaginary_part_is_read_before_the_bound_and_a_real_argument_past_it_marks_nothing():
    x, near = sympy.Symbol("x"), -sympy.sqrt(2) / 10**7
    assert M._inner_reads(value("exp(1/x**1000)"), x, near) == (False, True)
    assert read("limit", params("exp(-1/x**1000) at 0 dir - = 0")) == H and read("limit", params("exp(1/x**1000) at 0 dir - = oo")) == I


def test_a_branch_past_the_bound_hides_no_other_branch_that_left_the_reals():
    x = sympy.Symbol("x")
    assert M._off_the_reals(value("exp(x**2*10**30)*sqrt(x)"), x, sympy.Integer(-1)) is True
    assert M._off_the_reals(value("sqrt(x)*exp(x**2*10**30)"), x, sympy.Integer(-1)) is True
    assert M._off_the_reals(value("exp(x**2*10**30)*sqrt(-x)"), x, sympy.Integer(-1)) is False
    assert read("limit", params("exp(exp(exp(exp(x))))*sqrt(x - 3) at 3 dir - = 0")) == I


def test_the_read_goes_inner_first_so_nothing_past_the_bound_reaches_a_call(monkeypatch):
    x, read_args = sympy.Symbol("x"), []
    real = sympy.Expr.evalf

    def spy(self, *args, **kwargs):
        read_args.append(self)
        return real(self, *args, **kwargs)
    monkeypatch.setattr(sympy.Expr, "evalf", spy)
    assert M._off_the_reals(value("sinh(sinh(x))"), x, sympy.Integer(50)) is False
    assert value("sinh(sinh(50))") not in read_args and value("sinh(50)") in read_args


@pytest.mark.parametrize("row", ["exp(exp(exp(exp(x)))) at 3 dir + = exp(exp(exp(exp(3))))", "exp(-1/x**1000) at 0 dir + = 0"])
def test_a_stated_side_reads_a_tower_and_stops_at_the_bound(row):
    assert read("limit", params(row)) == H


def test_the_read_never_works_out_an_exact_power():
    """exp(n*log(d)) at an exact d is d**n, with n of 10**14 here and inside the bound, and that does not finish."""
    x, near = sympy.Symbol("x"), (sympy.sqrt(2) / 10**7).evalf(80)
    assert M._off_the_reals(value("exp(log(x)/x**2)"), x, near) is False and M._off_the_reals(value("exp(log(x)/x**2)"), x, -near) is True


def test_a_read_that_fails_is_unread():
    x = sympy.Symbol("x")
    assert M._off_the_reals(sympy.Function("f")(x), x, sympy.Integer(1)) is False
    assert M._off_the_reals(value("1/x"), x, sympy.Integer(0)) is False
    assert M._off_the_reals(value("x + y"), x, sympy.Integer(1)) is False
    assert M._off_the_reals(value("sin(x + y)"), x, sympy.Integer(1)) is False


# ── (5) an enclosure, and (6) the sides ──────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("row,want", [
    ("sin(x) at oo = 5", B), ("sin(x) at oo = -5", B), ("sin(x) at oo = oo", B), ("sin(x) at oo = 0", I), ("sin(x) at oo = 1", I), ("sin(x) at oo = -1", I),
    ("sin(x) at oo = a", I), ("sin(x) at oo = I", I), ("a + sin(x) at oo = a", I), ("sign(sin(x)) at oo = 1", I), ("Abs(sin(x)) at oo = 1/2", I),
])
def test_an_enclosure_breaks_a_value_outside_it_and_nothing_else(row, want):
    assert read("limit", params(row)) == want


def test_an_enclosure_on_a_finite_point_reads_the_same(monkeypatch):
    spied_limit(monkeypatch, {"+": sympy.AccumBounds(-1, 1), "-": sympy.AccumBounds(-1, 1)})
    claim = params("x at 0 = 5")
    assert read_here("limit", claim) == B and read_here("limit", {**claim, "claimed_limit": "0"}) == I


def test_enclosures_that_differ_read_not_checkable(monkeypatch):
    spied_limit(monkeypatch, {"+": sympy.AccumBounds(-1, 1), "-": sympy.AccumBounds(0, 2)})
    assert read_here("limit", params("x at 0 = 5")) == I


@pytest.mark.parametrize("claimed", ["1", "-1", "0", "oo", "-oo", "a", "I"])
def test_sides_that_disagree_read_broken_for_every_claimed_value_with_the_counterexample(claimed):
    r = M.verify_limit({"function": "Abs(x)/x", "variable": "x", "point": 0, "claimed_limit": claimed})
    assert r.status == "MISMATCH"
    assert (r.data["left"], r.data["right"]) == ("-1", "1")


def test_oo_against_oo_is_compared_by_equality_before_any_subtraction():
    assert sympy.simplify(sympy.oo - sympy.oo) is sympy.nan
    for row in ("1/x**2 at 0 = oo", "-1/x**2 at 0 = -oo", "1/(x - 1)**2 at 1 = oo", "1/x at 0 dir - = -oo"):
        assert read("limit", params(row)) == H


def test_an_infinite_reading_at_an_infinity_never_confirms():
    """sympy answers oo for (cosh(x)**2 - sinh(x)**2 - 2)*x, which is -x, so its infinity at an infinity is nothing a claim can rest on."""
    x = sympy.Symbol("x")
    assert sympy.limit(value("(cosh(x)**2 - sinh(x)**2 - 2)*x"), x, sympy.oo) == sympy.oo
    detail = M.verify_limit(params("x at oo = oo")).detail
    assert detail.startswith(M._REFUSAL) and "An infinite reading confirms only" in detail
    assert read("limit", params("x at oo = 5")) == B and read("limit", params("x at oo = -oo")) == B and read("limit", params("1/x at oo = 0")) == H


@pytest.mark.parametrize("text", ["limit(x, x, oo)", "Limit(exp(x), x, oo)", "limit(-x, x, oo)", "limit(x**2, x, -oo)", "limit(a/x**2, x, 0)", "Limit(1/(x - a)**2 + b/x**2, x, 0)", "limit(log(x), x, 0)", "Limit(log(x), x, 0)",
                                  "limit((sqrt(x**2) - 2)**2/(x + 2)**2, x, -2)"])
def test_the_functions_refuse_a_reading_that_never_confirms(text):
    with pytest.raises(M.UnboundRefused):
        M.parse_expression(text)


# ── DECIDED ──────────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("function", ["x", "5", "1/x**2", "x**2 + 1/3", "0.1*x", "(x + 1)/(x**2 - 2*x + 1)", "-3/(x**2*(x - 1)**2)", "((x + 1)**2 - 1/x)**3/(x - 1/3)", "1/x**2 - 1/x**4"])
def test_a_rational_function_is_the_variable_rational_numbers_sums_products_and_integer_powers(function):
    assert M._rational_function(value(function), sympy.Symbol("x")) is True


@pytest.mark.parametrize("function", ["sin(x)", "exp(x)", "log(x)", "sqrt(x)", "x**(1/3)", "sqrt(2)*x", "pi*x", "E/x", "a*x", "x + a", "Abs(x)", "sign(x)", "x**x", "1/sqrt(x**2)", "x/(1 + sqrt(2))", "I*x", "1/x**2 + sin(x)"])
def test_nothing_else_is(function):
    assert M._rational_function(value(function), sympy.Symbol("x")) is False


@pytest.mark.parametrize("function,point,confirms", [
    ("1/x**2", "0", True), ("1/(x - 1/3)**2", "1/3", True), ("1/(x - 0.1)**2", "0.1", True), ("-3/(x**2*(x - 1)**2)", "0", True),
    ("1/(x - sqrt(2))**2", "sqrt(2)", False), ("1/(x - pi)**2", "pi", False), ("x", "oo", False), ("x", "-oo", False), ("log(x)", "0", False), ("a/x**2", "0", False),
    ("1/(x - a)**2", "a", False), ("1/x**2 + sin(x)", "0", False), ("1/sqrt(x)", "0", False), ("exp(1/x**1000)", "0", False),
])
def test_an_infinite_reading_confirms_only_in_a_rational_function_at_a_rational_point(function, point, confirms):
    x = sympy.Symbol("x")
    for infinite in (sympy.oo, -sympy.oo):
        assert M._never_confirms(infinite, value(function), x, value(point)) is not confirms
    assert M._never_confirms(sympy.Integer(1), value(function), x, value(point)) is False       # a finite reading is no matter for it


def test_decided_reads_nothing_numeric_and_stands_in_two_places(monkeypatch):
    x, form = sympy.Symbol("x"), value("1/(x - 1/3)**2")
    monkeypatch.setattr(sympy.Expr, "evalf", lambda *_a, **_k: pytest.fail("DECIDED is structure"))
    assert M._never_confirms(sympy.oo, form, x, sympy.Rational(1, 3)) is False and M._never_confirms(sympy.oo, sympy.log(x), x, sympy.Integer(0)) is True
    source = inspect.getsource(M)
    assert source.count("_never_confirms(") == 4 and "_never_confirms(value, *args)" in source       # its definition, limit and Limit, and limit mode's two readings
    assert "_never_confirms(actual, ef, x, ep)" in source and "_never_confirms(one_side[0], ef, x, ep)" in source


@pytest.mark.parametrize("row", ["log(x) at 0 = -oo", "log(x) at 0 dir + = -oo", "1/x**2 + sin(x) at 0 = oo", "x at oo = oo", "a/x**2 at 0 = oo*sign(a)", "1/(x - sqrt(2))**2 at sqrt(2) = oo",
                                 "exp(1/x**1000) at 0 dir - = oo", "1/(x - a)**2 at a = oo"])
def test_the_refusal_says_where_an_infinite_reading_confirms_and_nothing_false(row):
    detail = M.verify_limit(params(row)).detail
    assert detail.startswith(M._REFUSAL) and "An infinite reading confirms only in a rational function with rational coefficients at a rational point" in detail
    assert "finite point" not in detail and "no other symbol" not in detail


@pytest.mark.parametrize("text", ["limit(log(x), x, 0)", "Limit(log(x), x, 0)", "limit(x, x, oo)", "limit(1/(x - sqrt(2))**2, x, sqrt(2))"])
def test_the_functions_say_the_same(text):
    with pytest.raises(M.UnboundRefused, match="An infinite reading confirms only in a rational function with rational coefficients at a rational point"):
        M.parse_expression(text)


@pytest.mark.parametrize("text,words", [("limit(Abs(x)/x, x, 0)", "direction states a side"), ("limit(sin(x), x, oo)", "only as enclosed by")])
def test_each_other_refusal_of_the_functions_says_what_is_true_of_it(text, words):
    with pytest.raises(M.UnboundRefused, match=words):
        M.parse_expression(text)


def test_an_infinite_reading_holding_a_symbol_never_confirms_and_one_with_none_at_a_finite_point_does():
    """sign((a + 1)**2 - a**2 - 2*a - 1) is sign(0), and no read here can see that."""
    assert read("limit", params("((a + 1)**2 - a**2 - 2*a - 1)/x**2 at 0 = oo*sign((a + 1)**2 - a**2 - 2*a - 1)")) == I
    assert read("limit", params("a/x**2 at 0 = oo*sign(a)")) == I and read("limit", params("1/x**2 at 0 = oo")) == H
    assert read("limit", params("a/x**2 at 0 = 5")) == B and read("limit", params("a*x at 0 = 0")) == H


def test_a_claimed_value_equal_only_after_simplifying_still_holds():
    assert read("limit", params("a*(1 + a)*sin(x)/x at 0 = a + a**2")) == H
    assert read("limit", params("exp(x) + sin(x)**2 + cos(x)**2 at 1 = E + 1")) == H


# ── the functions limit and Limit ────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text,want", [("limit(sin(x)/x, x, 0)", 1), ("Limit(sin(x)/x, x, 0)", 1), ("limit(1/x, x, oo)", 0), ("Limit(1/x, x, oo)", 0),
                                       ("limit(sqrt(x), x, 0)", 0), ("limit(x**2, x, 3)", 9)])
def test_each_answers_with_the_value(text, want):
    assert M.parse_expression(text) == want


WRONG_FINITE_READING = "1/(x*cosh(x)**2 - x*sinh(x)**2 - x + 1)"


@pytest.mark.parametrize("point", ["oo", "-oo"])
def test_capital_limit_reads_the_function_simplified_at_an_infinity_as_the_base_compare_did(point):
    """The function is 1 at every x, sympy's limit reads the form as written as 0, and limit mode and limit read that as at the base."""
    assert M.parse_expression(f"Limit({WRONG_FINITE_READING}, x, {point})") == 1
    assert M.parse_expression(f"limit({WRONG_FINITE_READING}, x, {point})") == 0
    assert read("equality", equality(f"Limit({WRONG_FINITE_READING}, x, {point}) = 0")) == B
    assert read("equality", equality(f"Limit({WRONG_FINITE_READING}, x, {point}) = 1")) == H


@pytest.mark.parametrize("text", ["Limit(sin(x)/x, x, 0)", "Limit(x**2 + 1, x, 2)"])
def test_capital_limit_simplifies_nothing_at_a_finite_point(text, monkeypatch):
    real, asked = M._limit_answer, []
    monkeypatch.setattr(M, "_limit_answer", lambda *args: asked.append(args) or real(*args))
    written = M._parse(text.split("(", 1)[1].rsplit(", x,", 1)[0], ["x"], rational=True)
    M.parse_expression(text)
    assert asked[0][0] == written


@pytest.mark.parametrize("name", ["limit", "Limit"])
def test_both_spellings_answer_through_the_one_helper(name, monkeypatch):
    real, asked = M._limit_answer, []
    monkeypatch.setattr(M, "_limit_answer", lambda *args: asked.append(args) or real(*args))
    M.parse_expression(f"{name}(sin(x)/x, x, 0)")
    assert len(asked) == 1 and asked[0][3:] == ()


@pytest.mark.parametrize("text", ["limit(Abs(x)/x, x, 0)", "Limit(Abs(x)/x, x, 0)", "limit(1/x, x, 0)", "Limit(1/x, x, 0)", "limit(floor(x), x, 1)", "limit(sin(x), x, oo)",
                                  "Limit(sin(x), x, oo)", "limit(sign(x), x, 0)", "limit(exp(1/x), x, 0)", "limit(tan(x), x, pi/2)"])
def test_anything_else_is_unbound_so_neither_ever_answers_from_one_side(text):
    with pytest.raises(M.UnboundRefused):
        M.parse_expression(text)


@pytest.mark.parametrize("text", ["limit(x, x, 0, 1)", "Limit(x, x, 0, 1)", "limit(1/x, x, oo, 1)", "limit(x, x, 0, y)", "limit(x, x, 0, '+')", "limit(x, x)",
                                  "Limit(x)", "limit(x, x, 0, 1, 2)"])
def test_any_other_number_of_arguments_stays_refused(text):
    with pytest.raises(M.ExpressionRefused):
        M.parse_expression(text)
    assert read("equality", {"expr_a": text, "expr_b": "0"}) == I


def test_a_limit_call_reads_the_same_in_an_unevaluated_read():
    """Limit stood unevaluated there, and the pole of its function read as one of the claim's."""
    assert M.parse_expression("Limit(sin(x)/x, x, 0)", evaluate=False) == 1
    assert M._domain_mismatch("Limit(sin(x)/x, x, 0)", "1", []) is None
    with pytest.raises(M.UnboundRefused):
        M.parse_expression("limit(Abs(x)/x, x, 0)", evaluate=False)


def test_a_limit_inside_a_binder_reads_the_symbol_the_binder_substitutes():
    assert read("equality", equality("Sum(limit(sin(k*x)/x, x, 0), (k, 1, 3)) = 6")) == H


@pytest.mark.parametrize("mode,spec", every_mode("limit(Abs(x)/x, x, 0)"))
def test_every_mode_reads_a_limit_with_no_one_value_as_not_checkable(mode, spec):
    assert read(mode, spec) == I


# ── every new not-checkable goes through _refused ────────────────────────────────────────────────────────────────────
REFUSALS = {
    "a direction that is no side": {"function": "sin(x)/x", "variable": "x", "point": 0, "claimed_limit": 7, "direction": "up"},
    "off the list": {"function": "Piecewise((1, x < 0), (2, true))", "variable": "x", "point": 0, "claimed_limit": 7},
    "leaves the reals": {"function": "sqrt(x)", "variable": "x", "point": 0, "claimed_limit": 7, "direction": "-"},
    "a value inside an enclosure": {"function": "sin(x)", "variable": "x", "point": "oo", "claimed_limit": 0},
    "an enclosure inside a call": {"function": "sign(sin(x))", "variable": "x", "point": "oo", "claimed_limit": 7},
    "a call with no one value": {"function": "limit(Abs(x)/x, x, 0) + x", "variable": "x", "point": 0, "claimed_limit": 7},
    "an infinite reading at an infinity": {"function": "x", "variable": "x", "point": "oo", "claimed_limit": "oo"},
    "an infinite reading holding a symbol": {"function": "a/x**2", "variable": "x", "point": 0, "claimed_limit": "oo*sign(a)"},
    "an infinite reading past DECIDED": {"function": "log(x)", "variable": "x", "point": 0, "claimed_limit": "-oo"},
}


@pytest.mark.parametrize("kind,artifact", REFUSALS.items())
def test_a_new_refusal_is_a_refusal_and_a_passing_artifact_beside_it_reads_incomplete(kind, artifact):
    r = M.verify_limit(artifact)
    assert r.status == "NOT_APPLICABLE" and r.detail.startswith(M._REFUSAL), kind
    assert verify({"MATH_VERIFY": {"expr_a": "1", "expr_b": "1", **artifact}})["verdict"] == I


def test_a_side_that_gives_no_reading_is_a_refusal_too(monkeypatch):
    monkeypatch.setattr(M, "limit", lambda *_a: sympy.nan)
    artifact = params("sin(x)/x at 0 = 1")
    assert M.verify_limit(artifact).detail.startswith(M._REFUSAL)
    assert verify({"MATH_VERIFY": {"expr_a": "1", "expr_b": "1", **artifact}})["verdict"] == I


def test_the_plans_packet_row():
    packet = {"expr_a": "1", "expr_b": "1", "function": "Piecewise((1, x < 0), (2, true))", "variable": "x", "point": 0, "claimed_limit": 7}
    assert verify({"MATH_VERIFY": packet})["verdict"] == I


def test_a_broken_limit_beside_a_passing_artifact_stays_broken():
    assert verify({"MATH_VERIFY": {"expr_a": "1", "expr_b": "1", **params("sin(x)/x at 0 = 2")}})["verdict"] == B


# ── rename invariance ────────────────────────────────────────────────────────────────────────────────────────────────
# Each moves every name a row holds. sympy's generator table holds x before a, so the third turns the pair round; zz is outside
# the table.
RENAMES = {
    "x and y exchanged": {"x": "y", "y": "x", "a": "b", "b": "a"},
    "a three-way cycle": {"x": "a", "a": "b", "b": "x"},
    "the other way round in the table": {"x": "a", "a": "x", "b": "c"},
    "outside the table": {"x": "zz", "a": "x", "b": "a"},
}
EXPRESSION_ROWS = tuple(("equality", equality(claim), want) for claim, want in EXPRESSIONS) + (("numeric", NUMERIC, I),)
SYMBOL_ROWS = tuple(("limit", params(row), want) for row, want in MODE_ROWS) + EXPRESSION_ROWS
# The prose names one letter, so a rename there is a letter and not a token: e is Euler's, and zz is no variable it reads.
PROSE_LETTERS = {"x and y exchanged": "y", "a three-way cycle": "a", "the other way round in the table": "a", "a third letter": "t"}


def test_every_row_holds_a_symbol():
    assert all(symbols(str(p.get("function", p.get("expr_a", p.get("numeric_expr"))))) or p.get("point") == "oo" for _m, p, _w in SYMBOL_ROWS)
    assert len(SYMBOL_ROWS) == 318 + 20 + 1


@pytest.mark.parametrize("name", RENAMES)
def test_every_row_reads_one_verdict_under_each_rename(name):
    moved = [(mode, spec, want, got) for mode, spec, want in SYMBOL_ROWS
             if (got := read(mode, renamed_params(spec, RENAMES[name]))) != want]
    assert moved == []


@pytest.mark.parametrize("name,letter", PROSE_LETTERS.items())
def test_every_prose_row_reads_one_verdict_under_each_letter(name, letter):
    for text, want in PROSE:
        moved = re.sub(r"\bx\b", letter, text)
        assert audit(moved, CFG, seal=False)["verdict"] == want, moved


def test_the_rename_keeps_a_stated_side():
    assert renamed_params(params("1/x at 0 dir + = oo"), RENAMES["outside the table"])["direction"] == "+"
    assert renamed_params(unstated("1/x at 0 = oo"), RENAMES["outside the table"])["direction"] == "unstated"


# What R4 declines, and why: Piecewise is not among R4_FUNCTIONS, so a row calling it takes the renames above.
R4_DECLINES = "Piecewise("


def test_every_row_r4_maps_reads_one_verdict_through_r4():
    R = _restate()
    moved, mapped, declined = [], 0, 0
    for mode, spec, want in SYMBOL_ROWS:
        subject = [{"id": "b", "domain": "mathematics", "spec": {"mode": mode, "params": json.loads(json.dumps(spec))}}]
        out = R.restate("R4", subject)
        if mode == "numeric" or R4_DECLINES in str(spec.get("function", spec.get("expr_a"))):
            assert not out.applied, (mode, spec)
            declined += 1
            continue
        assert out.applied, (mode, spec, out.reason)
        mapped += 1
        assert out.after[0]["spec"]["params"].get("direction") == spec.get("direction")
        restated = out.after[0]["spec"]
        if read(restated["mode"], restated["params"]) != want:
            moved.append((mode, spec, want))
    assert moved == []
    assert mapped >= 100 and declined >= 4


# ── the named misses ─────────────────────────────────────────────────────────────────────────────────────────────────
def test_miss_four_a_one_sided_limit_cannot_be_written_in_the_expression_form():
    for text in ("limit(1/x, x, 0, '+')", "limit(1/x, x, 0, 1)", "Limit(exp(-1/x), x, 0, 1)"):
        assert read("equality", {"expr_a": text, "expr_b": "0"}) == I
    assert read("limit", params("1/x at 0 dir + = oo")) == H       # limit mode is the way to state one


MISS_FIVE = (("Abs(x)*(1 + sqrt(x))/x at 0 = 1", "Abs(x)*(1 + sqrt(x))/x at 0 dir + = 1"), ("sign(x)*(1 + sqrt(x)) at 0 = 1", "sign(x)*(1 + sqrt(x)) at 0 dir + = 1"))


@pytest.mark.parametrize("both,one", MISS_FIVE)
def test_miss_five_a_function_that_leaves_the_reals_reads_incomplete_until_a_side_is_stated(both, one):
    assert read("limit", params(both)) == I and read("limit", params(one)) == H


TRUE_OFF_THE_LIST = ("x*sin(1/x) at 0 = 0", "x**x at 0 = 1", "x**x at 0 dir + = 1", "x**(1/x) at 0 dir + = 0", "floor(x) at 1/2 = 0", "floor(x) at 1 dir + = 1",
                     "tanh(1/x) at 0 dir + = 1", "2**x at 0 = 1", "log(sin(x)) at 0 = -oo")


@pytest.mark.parametrize("row", TRUE_OFF_THE_LIST)
def test_miss_six_off_the_list_reads_incomplete_true_ones_with_the_false_and_with_a_stated_side(row):
    assert read("limit", params(row)) == I


def test_miss_six_each_was_sympys_true_answer_and_the_lost_readings_are_named():
    x = sympy.Symbol("x")
    assert sympy.limit(x*sympy.sin(1/x), x, 0) == 0 and sympy.limit(x**x, x, 0) == 1
    for row in ("tan(x) at pi/2 = oo", "floor(x) at 1 = 1", "sin(1/x) at 0 = 5"):
        assert row in NOT_CHECKABLE


MISS_NINE = ("x at exp(exp(exp(exp(3)))) dir + = exp(exp(exp(exp(3))))", "x + log(2) at 0 = log(2)", "x at 10000000 = 10000000", "I*x at 0 = 0", "sign(exp(-x)) at 100 = 1",
             "1/(x**5 + x**6) at 0 dir + = oo", "sqrt(sqrt(x) + 1) at 0 = 1", "sqrt(x + a) at 1 = sqrt(1 + a)", "(a - b)*sqrt(x) at 0 dir + = 0", "a/x**2 at 0 = oo*sign(a)", "x at oo = oo")


@pytest.mark.parametrize("row", MISS_NINE)
def test_miss_nine_a_number_not_plain_a_value_unsettled_a_cut_in_a_cut_or_a_symbol_in_a_cut_reads_incomplete_true_ones_with_the_false(row):
    assert read("limit", params(row)) == I


MISS_ELEVEN = ("exp(x)/(x - 1)**2 at 1 = oo", "(exp(x) - E)/(x - 1) at 1 = E", "sin(x)/(x - a) at b = sin(b)/(b - a)", "exp(x)/(x - a) at b = exp(b)/(b - a)")


@pytest.mark.parametrize("row", MISS_ELEVEN)
def test_miss_eleven_a_pole_beside_a_value_that_is_not_rational_reads_incomplete_true_ones_with_the_false(row):
    assert read("limit", params(row)) == I


def test_miss_eleven_each_was_true_and_a_pole_only_the_fixed_irrational_makes_counts():
    x = sympy.Symbol("x")
    assert sympy.limit(sympy.exp(x)/(x - 1)**2, x, 1) == sympy.oo and sympy.limit((sympy.exp(x) - sympy.E)/(x - 1), x, 1) == sympy.E
    assert not M._exact(value("sin(x)/(x - a)"), x, sympy.Symbol("b")) and M._exact(value("sin(x)/(x - a)"), x, sympy.Integer(1))


MISS_FOURTEEN = ("log(1 + x**7)/x**7 at 0 = 1", "sin(x**70) at 2 = sin(2**70)", "sin(exp(exp(exp(x)))) at 3 dir - = sin(exp(exp(exp(3))))", "x + exp(exp(x)) at 50 = 50 + exp(exp(50))",
                 "1/(1 + exp(exp(x))) at 50 = 1/(1 + exp(exp(50)))", "cosh(2*x/3) - 2*sinh(x/3)**2 at 451 = 1", "cosh(x) - sinh(x) at 100 = exp(-100)")


@pytest.mark.parametrize("row", MISS_FOURTEEN)
def test_miss_fourteen_what_no_read_can_settle_reads_incomplete_true_ones_with_the_false(row):
    """A value too small for the read's digits, a call other than exp past the bound, a sum holding a part past it, and a form that
    cancels more than 10 digits at the point."""
    assert read("limit", params(row)) == I


def test_miss_fourteen_each_kind_is_what_takes_the_row_off():
    x = sympy.Symbol("x")
    assert not M._no_zero_hides(value("log(1 + x**7)/x**7"), x, sympy.Integer(0))
    assert not M._no_zero_hides(value("sin(x**70)"), x, sympy.Integer(2)) and M._no_zero_hides(value("sin(x**60)"), x, sympy.Integer(2))
    assert not M._no_zero_hides(value("x + exp(exp(x))"), x, sympy.Integer(50)) and M._no_zero_hides(value("exp(exp(x))"), x, sympy.Integer(50))
    assert M._no_zero_hides(value("cosh(x) - sinh(x)"), x, sympy.Integer(100)) and M._digits_cancelled(value("cosh(x) - sinh(x)"), x, sympy.Integer(100)) > 10


def test_miss_thirteen_a_finite_reading_at_an_infinity_stands_in_limit_mode_and_lowercase_limit():
    assert read("limit", params(f"{WRONG_AT_AN_INFINITY} at oo = 1")) == H
    assert read("limit", params(f"{WRONG_FINITE_READING} at oo = 0")) == H
    assert read("equality", equality(f"limit({WRONG_FINITE_READING}, x, oo) = 0")) == H


def test_miss_fifteen_a_denominator_zero_everywhere_reads_incomplete_at_once(monkeypatch):
    monkeypatch.setattr(M, "limit", lambda *_a: pytest.fail("the list answers before any limit runs"))
    assert M.verify_limit(params("1/(x*(sin(x)**2 + cos(x)**2 - 1)) at 0 = 0")).detail.startswith(M._REFUSAL)


def test_miss_twelve_reading_both_sides_doubles_a_limits_cost(monkeypatch):
    """Two limits run where the base ran one, so a form whose one side takes more than half of verify's window sheds to an error."""
    seen = spied_limit(monkeypatch)
    assert read_here("limit", params("sin(x)/x at 0 = 1")) == H and len(seen) == 2
    del seen[:]
    assert read_here("limit", params("sin(x)/x at 0 dir + = 1")) == H and len(seen) == 1
    assert "Reading both sides doubles a limit's cost" in _bullet()


def test_a_denominator_zero_everywhere_is_off_the_list_where_sympys_limit_runs_past_the_window():
    assert read("limit", params("1/(x*(sin(x)**2 + cos(x)**2 - 1)) at 0 = 0")) == I


def test_a_finite_reading_at_an_infinity_stands_as_at_the_base():
    """Nothing is listed at an infinity and no other reading is lost, so a wrong finite side stands too: the first function is 1 at every x,
    and the second runs to exp(1/2), so each of these false claims reads HOLDS here as it did at the step's base."""
    x, row = sympy.Symbol("x"), "1/(x*cosh(x)**2 - x*sinh(x)**2 - x + 1) at oo = 0"
    assert sympy.limit(value(params(row)["function"]), x, sympy.oo) == 0 and sympy.simplify(value("x*cosh(x)**2 - x*sinh(x)**2 - x + 1")) == 1
    assert read("limit", params(row)) == H
    assert sympy.limit(value(WRONG_AT_AN_INFINITY), x, sympy.oo) == 1 and read("limit", params(f"{WRONG_AT_AN_INFINITY} at oo = 1")) == H
    assert abs(value(WRONG_AT_AN_INFINITY).subs(x, 10**9).evalf(30) - sympy.exp(sympy.Rational(1, 2)).evalf(30)) < 1e-6


MISS_FIFTEEN = ("log(x) at 0 dir + = -oo", "1/sqrt(x) at 0 dir + = oo", "exp(1/x**1000) at 0 dir - = oo", "1/x**2 + sin(x) at 0 = oo", "1/(x - sqrt(2))**2 at sqrt(2) = oo", "a/x**2 at 0 = oo*sign(a)", "x at oo = oo")
MISS_FIFTEEN_THROUGH_THE_FUNCTIONS = (("equality", equality("Limit(log(x), x, 0) = 5")), ("equality", equality("limit(x, x, oo) = 5")), ("limit", params("x at limit(x, x, oo) = 5")), ("limit", params("1/x at limit(x, x, oo) = 0")))


@pytest.mark.parametrize("row", MISS_FIFTEEN)
def test_miss_fifteen_a_claim_equal_to_an_infinite_reading_past_decided_reads_incomplete_true_ones_with_the_false(row):
    assert read("limit", params(row)) == I


def test_miss_fifteen_a_wrong_infinite_reading_can_keep_the_bases_false_broken_on_a_true_claim():
    """DECIDED moves a claim only where a reading equals it. sympy reads oo here, and the function is 0 at every x."""
    assert read("limit", params("(cosh(x)**2 - sinh(x)**2 - 1)*x at oo = 0")) == B and sympy.simplify(value("cosh(x)**2 - sinh(x)**2 - 1")) == 0


@pytest.mark.parametrize("mode,spec", MISS_FIFTEEN_THROUGH_THE_FUNCTIONS)
def test_miss_fifteen_limit_and_limit_refuse_an_infinite_reading_wherever_they_are_written(mode, spec):
    """A false claim through them reads INCOMPLETE where it read BROKEN, and the last, a true one, where it read HOLDS: a limit-mode field reads them too."""
    assert read(mode, spec) == I


def test_miss_sixteen_a_power_of_a_power_reads_incomplete_at_any_finite_point_true_ones_with_the_false():
    """sqrt(x**2) at -2 = 2 is true and reads HOLDS at the base, and the rule takes it off with the false ones."""
    for row in ("sqrt(x**2) at -2 = 2", "sqrt(x**2) - 1 at -1 = -2", "(x**4)**(1/3) - 1 at -1 = 0", "sign(x + 1)*(sqrt(x**2) - 1) at -1 dir - = 2", "Abs(x + 1)/(x + 1)*(sqrt(x**2) - 1) at -1 dir - = 2"):
        assert row in NOT_CHECKABLE and read("limit", params(row)) == I
    assert read("limit", params("(sqrt(x**2) - 2)**2/(x + 2)**2 at -2 = 1")) == I


MISS_SEVENTEEN = ("the limit of e^(-1/x) as x approaches 0 is 0", "for positive x, the limit of e^(-1/x) as x approaches 0 is 0", "Indeed, the right-hand limit of e^(-1/x) as x approaches 0 is 0")


@pytest.mark.parametrize("text", MISS_SEVENTEEN)
def test_miss_seventeen_a_prose_limit_with_no_side_read_reads_incomplete_where_the_claim_equals_one_side(text):
    """The base read one side, so the first was a false HOLDS there and the second a true one. Both read not checkable, true ones with the false."""
    (step,) = extract(text)
    assert step["spec"]["params"]["direction"] == "unstated" and audit(text, CFG, seal=False)["verdict"] == I


def test_miss_nine_each_of_those_was_true():
    x = sympy.Symbol("x")
    assert sympy.limit(x + sympy.log(2), x, 0) == sympy.log(2) and sympy.limit(sympy.sign(sympy.exp(-x)), x, 100) == 1 and sympy.limit(sympy.sqrt(sympy.sqrt(x) + 1), x, 0) == 1


@pytest.mark.parametrize("row", ["sin(x)**2 + cos(x)**2 at oo = 1", "sin(x)*cos(x) - sin(2*x)/2 at oo = 0"])
def test_miss_seven_a_claimed_limit_inside_an_enclosure_reads_incomplete_true_identities_with_it(row):
    assert read("limit", params(row)) == I
    function = sympy.sympify(params(row)["function"])
    assert sympy.simplify(function - sympy.sympify(params(row)["claimed_limit"])) == 0


# ── what was found: sympy's own readings, recomputed so the record can quote them ────────────────────────────────────
def test_what_was_found_is_sympys_own_reading():
    x = sympy.Symbol("x")
    # one side, called the limit, and oo less oo
    assert sympy.limit(sympy.Abs(x)/x, x, 0) == 1 and sympy.limit(1/x, x, 0) == sympy.oo
    assert sympy.limit(x**(1/x), x, 0) == 0
    # sides that agree and are wrong: the left side of acot runs to -pi/2, and sympy keeps pi/2
    wrong = 1/(sympy.exp(sympy.acot(x)) - sympy.exp(sympy.pi/2))**2
    assert sympy.limit(wrong, x, 0, "+") == sympy.oo and sympy.limit(wrong, x, 0, "-") == sympy.oo
    assert abs(wrong.subs(x, -sympy.Rational(1, 10**9)).evalf(30) - sympy.Rational(472, 10000)) < sympy.Rational(1, 1000)
    # a jump sympy loses under an Add
    lost = 1/(1 + sympy.exp(1/x)) + 1
    assert sympy.limit(lost, x, 0, "-") == 1 and abs(lost.subs(x, -sympy.Rational(1, 100)).evalf(30) - 2) < sympy.Rational(1, 1000)
    # sign read at the point and not beside it
    a = sympy.Symbol("a")
    assert sympy.limit(sympy.sign(x**2 - a*x), x, 0, "+") == sympy.limit(sympy.sign(x**2 - a*x), x, 0, "-")


# What the build's sweep found on an earlier list: sympy reads Abs and sign as if what they hold were real, so it took the first to 1,
# with a value of (1 + I)/sqrt(2), and the second to a negative absolute value. I is not plain and a cut holds no cut, so both are off.
TAKEN_OFF = ("sign((1 + I)*cos(x)**2) at pi/2 = 1", "Abs(sqrt(x - 2)*cos(x)**2)/cos(x)**2 at pi/2 = -sqrt(2)*sqrt(4 - pi)/2")


@pytest.mark.parametrize("row", TAKEN_OFF)
def test_what_the_sweep_took_off_the_list_reads_not_checkable(row):
    spec = params(row)
    x, point = sympy.Symbol("x"), value(spec["point"])
    assert sympy.limit(value(spec["function"]), x, point, "+") == value(spec["claimed_limit"])
    assert contradiction(value(spec["function"]), x, point, "+", value(spec["claimed_limit"]))
    assert not on_the_list(spec["function"], spec["point"]) and read("limit", spec) == I


ZERO_UNDER_SIGN = "sign((x + 1)**2 - x**2 - 2*x - 1)/(x - 1) at 1 dir - = -oo"


def test_the_argument_of_abs_and_sign_reads_above_the_margin_at_the_reads_distance_too():
    """The sweep found it: the function is 0 everywhere, and sympy's left side runs to -oo, and a contradiction takes the form off the list."""
    x, spec = sympy.Symbol("x"), params(ZERO_UNDER_SIGN)
    assert sympy.expand((x + 1)**2 - x**2 - 2*x - 1) == 0 and sympy.limit(value(spec["function"]), x, 1, "-") == -sympy.oo
    assert not on_the_list(spec["function"], spec["point"]) and read("limit", spec) == I
    assert on_the_list("sign(x)") and on_the_list("Abs(x**2 - x)/x") and on_the_list("sign(sin(x))")


def test_a_row_the_rules_were_built_against_stays_off_the_list():
    for row in ("1/(exp(acot(x)) - exp(pi/2))**2 at 0 = oo", "1/(exp(atan(1/x)) - exp(pi/2))**2 - 1/log(1/x**2) at 0 = oo",
                "1/(1 + exp(1/x)) + 1 at 0 = 1", "sign(x**2 - a*x) at 0 = 1", "exp(exp(1/x)) at 0 = oo", "sinh(sinh(1/x)) at 0 = oo"):
        assert row in NOT_CHECKABLE and not on_the_list(params(row)["function"], params(row)["point"])


# ── the slow sweep: the evidence the list is trusted, measured at build time ─────────────────────────────────────────
# Each point has its own zeros, so a form is built to vanish or blow up where it is read. The generator writes forms that are
# meant to reach the list's edges: jumps, vanishing roots, poles of exp, cancellations, each under what the list allows.
ZEROS = {
    "0": ("x", "-x", "x**2", "x**3", "sin(x)", "1 - cos(x)", "cos(x) - 1", "exp(x) - 1", "log(1 + x)", "x - x**2", "x + x**2", "x**2 - x", "tan(x)", "sinh(x)",
          "atan(x)", "asin(x)", "x - sin(x)", "tanh(x)", "x**2 + x**3", "x**3 - x**2", "cosh(x) - 1"),
    "1": ("x - 1", "1 - x", "(x - 1)**2", "(x - 1)**3", "x**2 - 1", "log(x)", "sin(pi*x)", "x**3 - x**2", "1 - 1/x", "exp(x - 1) - 1", "tan(x - 1)", "atan(x - 1)"),
    "pi/2": ("x - pi/2", "cos(x)", "1 - sin(x)", "sin(2*x)", "(x - pi/2)**2", "cos(x)**2", "tan(x - pi/2)", "sinh(x - pi/2)"),
    "-2": ("x + 2", "x**2 - 4", "sin(x + 2)", "exp(x + 2) - 1", "x**2 + x - 2", "(x + 2)**2", "log(x + 3)", "atan(x + 2)"),
    "0.1": ("x - 0.1", "0.1 - x", "3*x - 0.3", "10*x - 1", "x**2 - 0.01", "(x - 0.1)**2", "sin(x - 0.1)", "0.7*x - 0.07", "exp(x - 0.1) - 1", "log(x + 0.9)"),
}
# Numbers that hide a zero, a one or a complex value, and zeros written so nothing shows, for the list to refuse or to settle.
NOT_PLAIN_NUMBERS = ("log(2)", "cos(1)", "exp(2)", "sqrt(5 + 2*sqrt(6)) - sqrt(2) - sqrt(3)", "(1 + sqrt(2))*(1 - sqrt(2)) + 1", "10**7", "1/10**7", "pi**2", "I", "1 + I")
PLAIN_NUMBERS = ("1", "2", "1/2", "-1", "pi", "0.5", "0.1", "sqrt(2)", "1 + sqrt(2)", "pi/2 - 1", "E", "1000000", "1/1000000")
DISGUISED = ("cosh(x)**2 - sinh(x)**2 - 1", "sin(x)**2 + cos(x)**2 - 1", "(x + 1)**2 - x**2 - 2*x - 1", "tan(x)*cos(x) - sin(x)", "sin(2*x) - 2*sin(x)*cos(x)", "x*(1 + sqrt(2)) + x*(1 - sqrt(2)) - 2*x")
POLES = {"0": ("x", "x**2", "x**3", "x + x**2", "x - x**2"), "1": ("x - 1", "(x - 1)**2", "x**2 - 1"), "pi/2": ("x - pi/2", "cos(x)"), "-2": ("x + 2", "(x + 2)**2"),
         "0.1": ("x - 0.1", "3*x - 0.3", "(x - 0.1)**2")}
WRAPS = ("sign(@)", "Abs(@)", "sqrt((@)**2)", "log(@)", "log(Abs(@))", "log((@)**2)", "acos(cos(@))", "acos(1 - (@)**2)", "asin(1 - (@)**2)", "asin((@)/2)", "acos((@)/2)")
JUMPS = ("@", "1/(1 + @)", "@/(1 + @)", "1/(1 - @)", "1/(2 + @)", "(1 - @)/(1 + @)", "2*@", "-@/3")
ONE = ("1/(@)", "(@) - 1", "(@) + 1", "1 - (@)", "(@)**2", "sqrt(@)", "(@)*(X)", "(@)/(X)", "(@)/(X)**2", "sin(@)", "cos(@)", "exp(@)", "atan(@)", "tanh(@)", "Abs(@)",
       "sign(@)", "log(@)")
TWO = ("(@) + (#)", "(@) - (#)", "(@)*(#)", "(@)/(#)")
SECOND_SYMBOL = ("a*(@)", "(@) + a", "(@)/a", "sin(a*(@))", "(a - b)*(@)", "(a**2 - 3)*(@)", "a*(@) - b*(@) + 1/(X)**2", "(a - sqrt(3))*(@)")
COMPLEX_FACTOR = ("I*(@)", "(1 + I)*(@)")
SCALED = ("(@)/1000", "(@)/10**6", "(@)*0.1", "(@)/0.3")
SHIFTED = ("(@) + 0.25", "0.1 - (@)", "(@) + log(2)", "(@)*cos(1)", "(@) + (1 + sqrt(2))*(1 - sqrt(2)) + 1", "I*(@)")
# A pole under an exp that holds a log or a root: past the read's bound at its distance, and off the reals on one side.
SPIRALS = ("exp(@/(#)**3)", "exp(-@/(#)**4)", "exp(@**2/(#)**4)", "exp(@/(#)**30)", "1/(1 + exp(@/(#)**3))", "2*exp(-@**2/(#)**5)")
FORMS_PER_POINT = 2000
# At an infinity nothing is listed, so these read sympy's own finite value, and no form can come off a list that does not apply. A zero
# in disguise stays out of them, since sympy reads 1/(x*cosh(x)**2 - x*sinh(x)**2 - x + 1) as 0 there and the function is 1. And the sweep finds
# sympy wrong on one form it does hold: exp(sqrt(x**2 + x) - x) runs to exp(1/2), and sympy reads 1. Each is a false HOLDS the base reads too, so
# test_a_finite_reading_at_an_infinity_stands_as_at_the_base holds them, and the sweep names the one it meets.
WRONG_AT_AN_INFINITY = "exp(sqrt(x**2 + x) - x)"
# The contradictions the sweep names, by exact text and point: finite readings at oo that the base reads too, which stand as at the base.
KNOWN_WRONG = ((WRONG_AT_AN_INFINITY, "oo"), (f"({WRONG_AT_AN_INFINITY})*0.1", "oo"))
AT_AN_INFINITY = ("1/x", "1/x**2", "1/(x + 1)", "x/(x**2 + 1)", "(2*x + 1)/(x + 3)", "(x**2 + 1)/(x**2 - 1)", "x/sqrt(x**2 + 1)", "sqrt(x**2 + x) - x", "atan(x)", "tanh(x)", "sin(x)/x",
                  "log(x)/x", "1/log(x)", "(1 + 1/x)**x", "x*exp(-x**2)", "exp(-x**2)", "1/(1 + exp(x))", "exp(1/x)", "cos(1/x)", "x*sin(1/x)", "1/(x + sin(x))", "exp(x)", "x", "log(1 - x)",
                  "sqrt(x) + x", "1/(x + 0.5)", "0.1/x")
WRAPS_AT_AN_INFINITY = ("@", "(@) + 1", "2*(@)", "(@)**2", "exp(@)", "atan(@)", "1/(2 + (@))", "a*(@)", "(a - b)*(@)", "(@) + a", "(@)/a", "sin(@)", "cos(@)", "(@)*0.1", "(@) + 0.25", "(@) - (#)", "(@)*(#)")
FORMS_AT_AN_INFINITY = 500


def unexcused(contradicted):
    return [form for form in contradicted if form not in KNOWN_WRONG]


def base(r, point):
    zero, pole = r.choice(ZEROS[point]), r.choice(POLES[point] + ZEROS[point])
    kind = r.random()
    if kind < .25:
        return zero
    if kind < .45:
        return r.choice(WRAPS).replace("@", zero)
    if kind < .7:
        return r.choice(JUMPS).replace("@", f"exp({r.choice(('', '-', '2*', '-3*', 'a*'))}1/({pole}))".replace("*1/", "/"))
    if kind < .82:
        return r.choice(SPIRALS).replace("@", r.choice((f"log({zero})", f"sqrt({zero})"))).replace("#", pole)
    if kind < .9 and point != "0":      # exactly 0 at 0, where sympy's own limit runs on: the fixed forms below read that one
        return r.choice(("1/(@)", "2/sin(@)", "sign(@)", "Abs(@)/x", "1/(x*(@))", "1/atan(@)", "(@) + x")).replace("@", r.choice(DISGUISED))
    return r.choice(PLAIN_NUMBERS + NOT_PLAIN_NUMBERS + (ZEROS[point][0],))


def form(r, point):
    u = base(r, point)
    for _ in range(r.choice((1, 1, 2, 2, 3))):
        kind = r.random()
        if kind < .66:
            u = r.choice(ONE).replace("@", u).replace("X", ZEROS[point][0])
        elif kind < .86:
            u = r.choice(TWO).replace("@", u).replace("#", base(r, point))
        else:     # a log scaled down runs out too slowly for any sample to see: 1 + log(x)/10**6 stands near 1 at every distance here
            u = r.choice(SECOND_SYMBOL + COMPLEX_FACTOR + SHIFTED + (() if "log" in u else SCALED)).replace("@", u)
    return u


# The two distances: a pole of exp needs wide ones, since exp(-1/x) at 10**-7 is past any digits a sample keeps. The narrow pair
# stands inside the read's distance, since tan(1000000*sin(x))**2 - 1/100 only turns to the sign of its limit inside 10**-7.
WIDE, NARROW = (sympy.sqrt(2)/14, sympy.sqrt(2)/56), (sympy.sqrt(2)/10**3, sympy.sqrt(2)/10**9)
DIGITS = {True: 900, False: 300}
# The other symbols take two sets of values, of opposite sign, so a side that holds only for one of them is contradicted.
SYMBOL_VALUES = ({sympy.Symbol("a"): sympy.Rational(7, 5), sympy.Symbol("b"): sympy.Rational(2, 5)}, {sympy.Symbol("a"): -sympy.Rational(7, 5), sympy.Symbol("b"): sympy.Integer(3)})


def samples(function, variable, point, side, wide):
    """The function at the two distances, or None where either is past what a sample can read, as a read past the bound is."""
    sign = 1 if side == "+" else -1
    digits = DIGITS[wide]
    try:
        if point in (sympy.oo, -sympy.oo):
            at = [(sympy.sign(point)*sympy.sqrt(2)*far).evalf(digits + 20) for far in (10**3, 10**6)]
        else:
            at = [(point + sign*d).evalf(digits + 20) for d in (WIDE if wide else NARROW)]
        if any(M._inner_reads(function, variable, near)[1] for near in at):
            return None
        out = [function.subs(variable, near).evalf(digits, maxn=4*digits) for near in at]
    except Exception:
        return None
    return out if all(v.is_number and v.is_finite for v in out) else None


def contradiction(function, variable, point, side, value, direction="+-", agreed=False):
    """Why these samples contradict this value for this side, or None. A finite side's gap must shrink, and an infinite side's
    magnitude must grow and point the same way. Samples with no finite value read nothing. The two distances are wide only where
    an exp has a pole at the point. A side off the reals is excused only where sympy's sides agree, no direction is stated and the
    other side is real, which is what the plan lets stand. Where a direction is stated, the read should have refused it."""
    wide = any(M._diverges(call.args[0].subs(variable, point)) for call in function.atoms(sympy.exp))
    read_at = samples(function, variable, point, side, wide)
    if read_at is None:
        return None
    far, near = read_at
    if near.as_real_imag()[1] != 0 and not function.has(sympy.I):
        if direction != "+-":
            return f"{str(near)[:24]} is off the reals on a stated side, against {value}"
        other = samples(function, variable, point, "-" if side == "+" else "+", wide)
        if agreed and other is not None and other[1].as_real_imag()[1] == 0:
            return None     # log(x) at 0 = -oo stands
    if value in (sympy.oo, -sympy.oo) or value.has(sympy.oo, -sympy.oo):
        direction = sympy.sign(value)
        if not direction.is_number:
            return None
        if sympy.re(sympy.conjugate(direction)*near) <= 0 or abs(near) < abs(far)*sympy.Float("1.001"):
            return f"{str(far)[:12]} then {str(near)[:12]} against {value}"
        return None
    number = value.evalf(DIGITS[wide])
    if not number.is_number:
        return None
    gap_far, gap_near = abs(far - number), abs(near - number)
    if gap_near > sympy.Float("1e-5") and gap_near > sympy.Float("0.7")*gap_far:
        return f"{str(far)[:12]} then {str(near)[:12]} against {value}"
    return None


def read_form(text, point):
    """One form through the helper, and what the samples say of every value a claim can confirm, so an infinite reading past DECIDED is
    not compared."""
    x = sympy.Symbol("x")
    try:
        function, at = value(text), value(point)
    except M.ExpressionRefused:
        return {"read": "not parsed"}
    infinite = at in (sympy.oo, -sympy.oo)
    if not infinite and not M._on_the_list(function, x, at):
        return {"read": "off the list"}
    answered, against = 0, []
    for direction in ("+-",) if infinite else ("+", "-", "+-"):
        try:
            answered_value, sides = M._limit_answer(function, x, at, direction)
        except M.UnboundRefused:
            continue
        for side, side_value in sides.items():
            if side_value.has(sympy.AccumBounds) or M._never_confirms(side_value, function, x, at):
                continue
            answered += 1
            for held in SYMBOL_VALUES if (function.free_symbols | side_value.free_symbols) - {x} else ({},):
                # the read takes a symbol as positive, so a negative value's side off the reals is a claim about the symbol in general
                stated = direction if not held or held[sympy.Symbol("a")] > 0 else "+-"
                why = contradiction(function.subs(held), x, at.subs(held), side, side_value.subs(held), stated, answered_value is not None)
                if why:
                    against.append(f"{text} at {point} {direction} side {side}: {why}")
    return {"read": "answered" if answered else "refused", "values": answered, "against": against}


WORKER = r"""
import json, sys
sys.path[:0] = sys.argv[1:3]
import test_limits as T
T.M._ensure_sympy()
print("ready", flush=True)
for line in sys.stdin:
    trial = json.loads(line)
    print(json.dumps(T.read_form(**trial)), flush=True)
"""


def generated_forms():
    forms = []
    for point in ZEROS:
        r, seen = random.Random(f"limits-{point}"), set()
        while len(seen) < FORMS_PER_POINT:
            text = form(r, point)
            if text not in seen and len(text) < 90:
                seen.add(text)
                forms.append((text, point))
    return forms


def forms_at_an_infinity():
    forms = []
    for point in ("oo", "-oo"):
        r, seen = random.Random(f"limits-{point}"), set()
        while len(seen) < FORMS_AT_AN_INFINITY:
            text = r.choice(AT_AN_INFINITY)
            for _ in range(r.choice((0, 1, 1, 2))):
                text = r.choice(WRAPS_AT_AN_INFINITY).replace("@", text).replace("#", r.choice(AT_AN_INFINITY))
            if len(text) < 90:
                seen.add(text)
        forms += sorted((text, point) for text in seen)
    return forms


def family_of_exp_with_a_pole():
    """The two shapes an exp with a pole may stand in, over the rational functions a sweep can write."""
    poles = ("1/x", "1/x**2", "1/x**3", "1/(x + x**2)", "1/(x - x**2)", "1/(x**2 - x)", "(1 + x)/x", "(x**2 + 1)/x", "(x - 1)/x**2", "1/(x**3 + x**2)", "(x + 2)/(x**2 + x)",
             "1/(x**4 - x)")
    numbers, scales = ("1", "2", "-1", "-2", "1/2", "3", "-3/2"), ("1", "-1", "2", "-2", "1/2")
    return [(text, "0") for r in poles for k in scales
            for text in (f"({k})*exp({r})", *(f"1/({c} + ({k})*exp({r}))" for c in numbers))]


# The forms review wrote by hand against each edge of the list, each read at 0 unless it says otherwise.
HAND_FORMS = """
sign(cos(x) - 1); sign(x**2); sign(1 - cos(x)); sign(sin(x)); sign(sin(x))|pi; sign(cos(x))|pi/2; sign(x**3); sign(x**2 -
1)|1; sign(1 - x)|1; sign(log(x))|1; sign(exp(x) - 1); sign(x**3 - x**2); sign(-x**2); sign(x*sin(x)); sign(sin(x)**2); sign(x
- x**2); sign(Abs(x)); sign(sign(x)); Abs(sign(x)); sign(x)**2; exp(sign(x)); sin(sign(x)); cos(sign(x)); cos(pi*sign(x));
tanh(sign(x)); atan(sign(x)); tan(pi*sign(x)/2); tan(pi*sign(x)/4); log(1 + sign(x)/2); log(2 + sign(x)); log(sign(x) - 1);
log(1 - sign(x)**2); 1/(1 - sign(x)**2); x/(1 - sign(x)**2); sqrt(1 - sign(x)**2); asin(sign(x)); acos(sign(x)); sign(x)/x;
x*sign(x); (1 + sign(x))/2; exp((1 + sign(x))/2); sin(x)*sign(x)/x; sign(Abs(x) - x); sign(x + Abs(x)); Abs(x) - x; 1/(Abs(x)
- x); 1/(Abs(x) + x); x/(Abs(x) + x); sign(sin(x) - x); sign(tan(x) - x); sign(x - sin(x)); sign(cos(x) - 1 + x**2/2);
sign(exp(x) - 1 - x); sign(log(1 + x) - x); sign(x**2*sin(x)); sign(sqrt(1 + x) - 1); sign(sqrt(x)); sign(sqrt(x**2));
sign(asin(x)); sign(atan(x)); sign(tanh(x)); sign(sinh(x) - x); sign(cosh(x) - 1); sign(1 - cosh(x)); sign(acos(x) - pi/2);
sign(cos(x) - 1)*x; sign(cos(x) - 1)/x**2; x + sign(cos(x) - 1); exp(sign(cos(x) - 1)); cos(pi*sign(1 - cos(x))); Abs(x**2 -
x)/x; Abs(cos(x) - 1)/x**2; Abs(sin(x))/x; Abs(x**2 - 1)/(x - 1)|1; Abs(log(x))/(x - 1)|1; Abs(exp(x) - 1)/x;
Abs(sin(x))/sin(x)|pi; Abs(cos(x))/cos(x)|pi/2; Abs(tan(x))/x; Abs(x + x**2)/x; Abs(x - x**3)/x; Abs(sin(x) - x)/x**3;
Abs(x)**(1/2)/x; Abs(Abs(x) - x)/x; Abs(Abs(x) + x)/x; atan(Abs(x))/x; sinh(Abs(x))/x; tan(Abs(x))/x; sin(Abs(x))/x;
(exp(Abs(x)) - 1)/x; log(1 + Abs(x))/x; sqrt(Abs(x))/sqrt(x); Abs(1 - cos(x))/(1 - cos(x)); Abs(x**3 - x**2)/x**2;
Abs(sinh(x))/x; Abs(asin(x))/x; Abs(atan(x))/atan(x); Abs(sign(x) + 1)/2; Abs(sign(x) - 1)/2; sqrt(x**2)/x; sqrt(x**2 +
x**3)/x; sqrt(1 - cos(x))/x; sqrt(1 - cos(x))/Abs(x); sqrt(sin(x)**2)/x; sqrt(sin(x)**2)/sin(x)|pi; sqrt(1 - cos(x)**2)/x;
sqrt(tan(x)**2)/x; (x**2)**(3/2)/x**3; (x**4)**(1/4)/x; (x**6)**(1/2)/x**3; (x**6)**(1/3)/x**2; (x**3)**(1/3)/x;
(x**3)**(2/3)/x**2; (x**2)**(1/3)/x**(2/3); sqrt(x)/sqrt(-x); sqrt(x)*sqrt(-x)/x; sqrt(-x)/x; sqrt(x**4 + x**6)/x**2;
sqrt(x**2 - x**3)/x; (1 - cos(x))**(3/2)/x**3; sin(sqrt(x**2))/x; sqrt(x**2)*log(x**2); sqrt((x - 1)**2)/(x - 1)|1; sqrt(x**2
- 2*x + 1)/(x - 1)|1; sqrt(cos(x)**2)/cos(x)|pi/2; (sin(x)**2)**(3/2)/x**3; x**(1/3)/x**(1/5); (x**2)**(1/5)/x**(2/5);
sqrt(sin(x)**2 + x**4)/x; sqrt(x**2*(1 + x))/x; sqrt(exp(x**2) - 1)/x; sqrt(cosh(x) - 1)/x; sqrt(log(1 + x**2))/x; sqrt(1 -
exp(-x**2))/x; acos(cos(x))/x; acos(1 - x**2)/x; (asin(cos(x)) - pi/2)/x; (asin(sin(x)) - pi/2)/(x - pi/2)|pi/2; (acos(x**2 -
1) - pi)/x; (asin(1 - x**2) - pi/2)/x; acos(sin(x))/(x - pi/2)|pi/2; acos(1 - Abs(x))/sqrt(Abs(x)); acos(cos(x)); acos(1 +
x**2); asin(1 + x**2); asin(cos(x)); acos(1 - x)/sqrt(x); acos(x)/sqrt(1 - x)|1; (pi/2 - asin(x))/sqrt(1 - x)|1;
acos(cos(2*x))/x; tan(acos(cos(x)))/x; sin(acos(cos(x)))/x; sin(acos(1 - x**2))/x; atan(sqrt(x**2))/x; acos(cos(x))/sin(x);
acos(cos(x))**2/x**2; acos(1 - x**2)**2/x**2; acos(1/(1 + x**2))/x; acos(exp(-x**2))/x; asin(exp(-x**2)); (asin(exp(-x**2)) -
pi/2)/x; acos(1 - x**4)/x**2; acos(1 - x**6)/x**3; acos(1 - sin(x)**2)/x; acos(cos(x)**2)/x; log(sin(x)**2 + cos(x)**2 - 1);
1/(sin(x)**2 + cos(x)**2 - 1); log((x + 1)**2 - x**2 - 2*x - 1); 1/((x + 1)**2 - x**2 - 2*x - 1); exp(1/((x + 1)**2 - x**2 -
2*x - 1)); log(Abs(x) - x); log(x - Abs(x)); log(Abs(x) + x); log(x**2); log(Abs(x)); log(1 - cos(x)); log(1 - cos(x)) -
2*log(Abs(x)); log(1 - cos(x)) - log(x**2); log(x)/log(x**2); log(sin(x))/log(x); log(x) - log(sin(x)); log(-x); x*log(-x);
log(sign(x)*x); log(exp(x) - 1) - log(x); log(exp(x) - 1)/log(x); log(log(1 + x)); log(log(1 + x)**2); sqrt(log(1 + x)**2)/x;
log(x**2 + x**3); log(Abs(sin(x)))/log(Abs(x)); log(sin(x)**2) - log(x**2); log(cos(x))|pi/2; log(tan(x)); log(sin(x))|pi;
log(1 + x)/log(1 + 2*x); x**2*log(x); log(x)*sin(x); 1/log(x); 1/log(Abs(x)); 1/log(x)**2; sqrt(x)*log(x)**3; log(x)**(1/3);
sqrt(log(x)); log(x**2) - 2*log(x); log(Abs(x)) - log(x); log(cos(x) - 1); log(x**2)/log(Abs(x)); log(1 - cos(x))/log(x);
log(1 + sign(x)*x)/x; log(Abs(x))*Abs(x)/x; exp(1/x)/(1 + exp(1/x)); (exp(1/x) - exp(-1/x))/(exp(1/x) + exp(-1/x));
exp(1/x**2) - exp(1/x**2 + 1/x); exp(1/x) - exp(1/x**2); x*exp(1/x); x**2*exp(-1/x**2); exp(-1/x**2)/x**100; exp((x**2 - 1)/(x
- 1))|1; exp(1/(x - 1))|1; exp(1/(x**2 - 1))|1; exp(x/(x**2 - x)); exp(1/(x*(x - 1))); exp((x + 1)/x); exp(a/x); exp(-a/x);
exp(a/x**2); exp(1/(a*x)); exp(1/(x - a))|a; a*log(x); a/x; 1/(a*x); x**2/a; sign(a*x); Abs(a*x)/x; sign(x - a)|a; sign(a)*x;
a*exp(1/x); exp(a/x)/(1 + exp(a/x)); 1/(1 + exp(a/x)); sqrt(a*x); sqrt(a*x)/sqrt(x); log(a*x); sign(a*sin(x)); sign(x**2 -
a*x); x*exp(a/x); (1 + exp(1/x))**(1/2); (exp(1/x) - 1)**(1/3); sqrt(1 - exp(1/x)); 1/(1 + exp(1/x))**2; exp(1/x)*sign(x);
exp(1/x)*Abs(x); exp(-1/x)*log(x); exp(1/x)*log(x); exp(-1/x**2)*sign(x); exp(-1/x**2)/sin(x); sin(x)*exp(1/x);
tan(x)*exp(-1/x**2); 1/(exp(1/x) - exp(-1/x)); 1/(1 - exp(1/x)); (1 - exp(1/x))/(1 + exp(1/x)); x/(1 + exp(1/x)); x/(1 -
exp(1/x)); sqrt(1/(1 + exp(1/x))); 1/(1/(1 + exp(1/x)) - 1); (1/(1 + exp(1/x)) - 1/2)**2; exp(1/x)*(1 - sign(x)); exp(1/x)*(1
+ sign(x)); 1/(exp(sign(x)) - E)**2; 1/(exp(sign(x)) - E)**2 - 1/log(x**2); 1/(exp(sign(x)) - E); 1/(tanh(sign(x)) -
tanh(1))**2; x*(1 - sign(x))*exp(1/x); (1 - sign(x)**2)*exp(1/x)
"""


def hand_forms():
    written = (form_.strip() for form_ in " ".join(HAND_FORMS.split()).split(";"))
    return [tuple((form_.split("|") + ["0"])[:2]) for form_ in written if form_]


def complex_under_the_calls():
    """A complex value beside a zero, under each call that reads the sign of what it holds: what took Abs and sign's complex
    arguments off the list, kept so no such form comes back."""
    numbers = ("sqrt(x)", "x**(1/3)", "(1 + I)", "I", "sqrt(x - 2)", "log(x - 2)", "asin(x + 2)", "acos(x + 3)", "sqrt(x - 3)", "exp(I*x + I)", "(2 + I + x)", "(1 + I*x)",
               "log(-1 - x**2)")
    zeros = {"pi/2": ("cos(x)**2", "cos(x)", "1 - sin(x)"), "0": ("x**2", "sin(x)**2", "1 - cos(x)", "x", "sin(x)", "x**3 - x**2")}
    shapes = ("sign({c}*({z}))", "Abs({c}*({z}))/({z})", "Abs({c}*({z}))", "1/sign({c}*({z}))", "sign({c}*({z}))/({z})", "Abs({c}*({z}))/({z})**2", "log({c}*({z}))",
              "log({c}*({z}))/log({z})", "sqrt(({c}*({z}))**2 + 1)", "sin({c}*({z}))/({z})", "atan({c}*({z}))/({z})", "exp({c}*({z}))", "tanh({c}*({z}))/({z})")
    return [(shape.format(c=c, z=z), point) for point, written in zeros.items() for z in written for c in numbers for shape in shapes]


def disguised_zeros_at_zero():
    """A zero everywhere that is exactly 0 at the point: only the read at its distance can tell, so each is off the list."""
    return [(shape.replace("@", zero), "0") for zero in DISGUISED for shape in ("1/(@)", "2/(@)", "1/(x*(@))", "x/(@)", "1/atan(@)", "2/sin(@)", "exp(1/(@))", "1/(1 + (@))**2 - 1/(@)")]


def exp_of_what_is_no_rational_function():
    """The plan keeps an exp with a pole on the list whatever its argument, where every prototype read a rational one."""
    return [(text, "0") for text in (
        "exp(1/sin(x))", "exp(-1/sin(x)**2)", "exp(1/tan(x))", "exp(1/log(1 + x))", "exp(1/sinh(x))", "exp(1/(exp(x) - 1))", "exp(1/(1 - cos(x)))", "exp(-1/(1 - cos(x)))",
        "exp(1/sqrt(x))", "exp(-1/sqrt(x))", "exp(1/atan(x))", "exp(1/asin(x))", "exp(1/tanh(x))", "exp(1/(x*log(x)))", "exp(log(x)/x)", "exp(1/log(x))", "exp(sin(x)/x**2)",
        "1/(1 + exp(1/sin(x)))", "1/(1 + exp(1/tan(x)))", "1/(1 + exp(1/log(1 + x)))", "1/(1 + exp(1/(exp(x) - 1)))", "1/(1 + exp(1/sqrt(x)))", "1/(2 - exp(1/sin(x)))",
        "exp(x*log(x))", "exp(log(x)**2)", "exp(1/x + log(x))", "exp(1/x - 1/sin(x))", "exp(1/x**2 - 1/sin(x)**2)", "exp(-1/x + 1/sin(x))", "exp(sqrt(x)/x)")]


# Zeros and ones in disguise, at the finite points, large ones among them: a sum at 54 cancels past what a read at 40 digits keeps,
# and at 30 it stops just short of the count the list allows. They never stand at oo or -oo, where known wrong readings stand as at the base.
DISGUISE_POLES = {"0": "x", "1": "x - 1", "2": "x - 2", "-2": "x + 2", "pi/2": "x - pi/2", "0.1": "x - 0.1", "30": "x - 30", "54": "x - 54", "451": "x - 451", "1000": "x - 1000"}
DISGUISED_ZEROS = DISGUISED + ("exp(x) - cosh(x) - sinh(x)", "tanh(x)*cosh(x) - sinh(x)", "cosh(2*x/3) - 2*sinh(x/3)**2 - 1", "sinh(2*x/3) - 2*sinh(x/3)*cosh(x/3)")
DISGUISED_ONES = ("cosh(x)**2 - sinh(x)**2", "sin(x)**2 + cos(x)**2", "cosh(2*x/3) - 2*sinh(x/3)**2", "cosh(x) - 2*sinh(x/2)**2", "(cosh(x/3) - sinh(x/3))*exp(x/3)",
                  "(cosh(x/2) - sinh(x/2))**8*exp(4*x)", "tanh(x)*cosh(x)/sinh(x)", "tan(x)*cos(x)/sin(x)")
SPLIT_ZEROS = (("cosh(x)**2", "-sinh(x)**2", "-1"), ("sin(x)**2", "cos(x)**2", "-1"), ("tan(x)*cos(x)", "-sin(x)"), ("sin(2*x)", "-2*sin(x)*cos(x)"), ("exp(x)", "-cosh(x)", "-sinh(x)"))
ZERO_OVER_A_POLE = ("(@)/(P)", "(@)/(P)**2", "2*(@)/(P)**2", "(@)/sin(P)", "(@)/(P)**2 + 1", "1/(P)**2 - (@)/(P)**4", "1/(3 - exp((@)/(P)))")
ONE_THROUGH_A_CALL = ("log(@)", "log((@)**2)", "sin(pi*(@))", "tan(pi*(@))", "sqrt(@)", "cos(pi*(@)/2)", "atan(@)", "acos((@)/2)", "sign(@)", "Abs(@)", "@", "(@)**4", "x*(@)", "exp(x)*(@)")
OVER_A_PART_PAST_THE_BOUND = ("exp(exp(x))*(@)/(P)**2", "exp(x**70)*(@)/(P)**2", "(@)*(tan(1000000*sin(P))**2 - 1/100)/(P)**2", "sin(pi*x**70*(@))/(P)**2", "exp(exp(x))*acos((@)/2)/(P)**2")
COEFFICIENTS = ("((Q)*exp(R) - (Q)*cosh(R) - (Q)*sinh(R) + (Q)**3)/(Q)**3", "(sqrt(Q)*exp(R) - sqrt(Q)*cosh(R) - sqrt(Q)*sinh(R) + (Q)**2)/(Q)**2",
                "(((Q) + (Q)**3*exp(R) - (Q)**3*cosh(R) - (Q)**3*sinh(R) + (Q)**5)/(Q) - 1)/(Q)**4", "log(1 + (Q)*exp(R) - (Q)*cosh(R) - (Q)*sinh(R) + (Q)**2)/(Q)**2",
                "sin((Q)**2*exp(R) - (Q)**2*cosh(R) - (Q)**2*sinh(R) + (Q)**4)/(Q)**4")


def disguises():
    """Every disguise in every place the plan names: bare over a pole, beside one in a sum, split across terms over one pole, as a 1 read
    through a call alone or over a pole, as a coefficient under factors of x - p, and over a part past the read's bound."""
    forms = []
    for point, pole in DISGUISE_POLES.items():
        written = [shape.replace("@", zero).replace("P", pole) for zero in DISGUISED_ZEROS for shape in ZERO_OVER_A_POLE]
        written += [" + ".join(f"({term})/({pole})**{power}" for term in terms) for terms in SPLIT_ZEROS for power in (1, 2, 3)]
        for one in DISGUISED_ONES:
            read_through = [shape.replace("@", one) for shape in ONE_THROUGH_A_CALL]
            written += read_through + [f"({text})/({pole})**2" for text in read_through]
            written += [shape.replace("@", one).replace("P", pole) for shape in OVER_A_PART_PAST_THE_BOUND]
        written += [f"(cosh(exp(exp(x)))**2 - sinh(exp(exp(x)))**2 - 1)/({pole})**2", f"(sin(2*x**4) - 2*sin(x**4)*cos(x**4))/({pole})**2 + 1"]
        written += [shape.replace("Q", pole).replace("R", inner) for shape in COEFFICIENTS for inner in dict.fromkeys(("x", pole))]
        forms += [(text, point) for text in dict.fromkeys(written)]
    return forms


# A root of a power folds under a sum that cancels at a negative point, which the sweep's first forms never reached. Roots of a bare variable,
# a sum and a product stand beside it and stay on the list, so the samples read them.
ROOTS = ("sqrt(x**2)", "(x**4)**(1/4)", "(x**2)**(1/3)", "(3*x**2)**(1/3)", "(x**4)**(1/3)", "sqrt(x**2 + 1)", "sqrt(x*(x + 1))", "sqrt(x*(x - 1))", "(x**2 + x)**(1/3)", "sqrt(-x)", "sqrt(1 - x)", "(x**3 + 9)**(1/3)")
AROUND_A_ROOT = ("@", "@ - 1", "@ + x", "(@ - 2)**2/(x + 2)**2", "(@ + x + (x + 1)**2)/(x + 1)**2", "(@ - 1)/(x + 1)**2", "1/(@ + x + (x + 1)**2)", "1/(@ + x + (x + 3)**2)", "sign(x + 1)*(@ - 1)",
                 "Abs(x + 1)/(x + 1)*(@ - 1)", "sign(x + 2)*(@ + x)", "sign(tan(x + 1))*(@ - 1)")
NEGATIVE_POINTS = ("-1", "-2", "-3", "-1/2")


def roots_at_a_negative_point():
    return [(shape.replace("@", root), point) for point in NEGATIVE_POINTS for root in ROOTS for shape in AROUND_A_ROOT]


# Each function the list names as off, in its plain form and its form at another point.
NAMED_OFF = {"floor": ("floor(x)", "floor(x - 1)"), "ceiling": ("ceiling(x)", "ceiling(x - 1)"), "frac": ("frac(x)", "frac(x - 1)"), "Mod": ("Mod(x, 3)", "Mod(x - 1, 3)"),
             "Piecewise": ("Piecewise((1, x < 0), (2, true))", "Piecewise((1, x < 1), (2, true))"), "Max": ("Max(x, 1)", "Max(x - 1, 1)"), "Min": ("Min(x, 1)", "Min(x - 1, 1)"),
             "acot": ("acot(x)", "acot(x - 1)"), "atan2": ("atan2(x, -1)", "atan2(x - 1, -1)"), "erf": ("erf(x)", "erf(x - 1)"), "a variable exponent": ("x**x", "(x - 1)**x"),
             "a function of a diverging argument": ("tanh(1/x)", "tanh(1/(x - 1))")}
COMPOSED = ("{g}", "{g}/1000", "1 + {g}", "x*{g}", "{g}/x", "{g}/x**2", "2*{g} - 1", "I*{g}", "a*{g}", "a + {g}", "sin({g})", "cos({g})", "tan({g})", "exp({g})", "exp({g}/1000)",
            "log(2 + {g})", "atan({g})", "sinh({g})", "tanh({g})", "sqrt(({g})**2 + 1)", "Abs({g})", "sign({g})", "1/(1 + ({g})**2)", "1/(1 + exp({g}))", "exp(1/x)*{g}", "x*exp({g})/1000",
            "1/(exp({g}) - 1)**2", "exp({g})*sin(x)/x")


def still_holds(function, name):
    """Whether what a form composed still holds the function it was written with: sympy reduces tan(acot(x)) to 1/x as it reads it,
    and a form that no longer holds the function is on or off the list as what it became."""
    if name == "a variable exponent":
        return any(power.exp.has(sympy.Symbol("x")) for power in function.atoms(sympy.Pow))
    return function.has(sympy.tanh if name == "a function of a diverging argument" else getattr(sympy, name))


def composed_off_the_list():
    composed = [(name, outer.format(g=core), point) for name, cores in NAMED_OFF.items() for core, point in zip(cores, ("0", "1")) for outer in COMPOSED]
    return [(name, text, point) for name, text, point in composed if still_holds(value(text), name)]


# What may stay unfinished. sympy's own limit does not finish on a form holding a zero in disguise, and the parser does not finish on
# this text, as neither did at the step's base: a verify sheds each to an error, never to a verdict.
RUNS_WITHOUT_END = frozenset({("sqrt(1/((2*exp(-sqrt(exp(x) - 1)**2/(x**2 + x**3)**5)) + (sinh(x))))", "0")})


def test_each_off_list_function_is_refused_however_it_is_composed(monkeypatch):
    """Structure alone, so it runs here as well as in the sweep. No limit runs, whatever sympy would answer."""
    monkeypatch.setattr(M, "limit", lambda *_a: pytest.fail("the list answers before any limit runs"))
    composed = composed_off_the_list()
    assert len(composed) >= len(NAMED_OFF) * 2 * len(COMPOSED) - 30
    assert {name for name, _text, _point in composed} == set(NAMED_OFF)
    assert [(name, text, point) for name, text, point in composed if on_the_list(text, point)] == []


def test_the_sweeps_exceptions_are_named_by_exact_text_and_point():
    """The form next door, and the named text at another point, are no exception."""
    assert len(KNOWN_WRONG) == SWEEP["contradicted"] and unexcused(KNOWN_WRONG) == []
    for planted in (("2*(exp(sqrt(x**2 + x) - x))", "oo"), ("exp(sqrt(x**2 + x) - x)", "1"), ("exp(sqrt(x**2 + x) - x)", "-oo"), ("sin(x)/x", "0"), ("x/(x**2 + 1)", "oo")):
        assert unexcused([planted]) == [planted]


@pytest.mark.parametrize("text,point", KNOWN_WRONG)
def test_each_exception_is_a_form_the_sweep_holds_and_a_finite_reading_at_an_infinity(text, point):
    assert (text, point) in forms_at_an_infinity() and point in ("oo", "-oo")
    got = read_form(text, point)
    assert got["read"] == "answered" and len(got["against"]) == 1


def test_the_samples_contradict_a_wrong_side_and_leave_a_right_one():
    """A sweep that cannot see is no evidence, so each kind of contradiction is shown to it, on the forms that found them."""
    x, zero = sympy.Symbol("x"), sympy.Integer(0)
    wrong = value("1/(exp(acot(x)) - exp(pi/2))**2")
    assert contradiction(wrong, x, zero, "-", sympy.oo) and contradiction(wrong, x, zero, "+", sympy.oo) is None
    assert contradiction(value("1/(1 + exp(1/x)) + 1"), x, zero, "-", sympy.Integer(1))
    assert contradiction(value("exp(acot(x))/1000"), x, zero, "-", sympy.exp(sympy.pi/2)/1000)
    assert contradiction(value("1/x"), x, zero, "-", sympy.oo) and contradiction(value("1/x"), x, zero, "-", -sympy.oo) is None
    assert contradiction(value("sin(x)/x"), x, zero, "+", sympy.Integer(2)) and contradiction(value("sin(x)/x"), x, zero, "+", sympy.Integer(1)) is None
    assert contradiction(value("sign((1 + I)*cos(x)**2)"), x, value("pi/2"), "+", sympy.Integer(1))
    assert contradiction(value("Abs(sqrt(x - 2)*cos(x)**2)/cos(x)**2"), x, value("pi/2"), "+", -sympy.sqrt(2)*sympy.sqrt(4 - sympy.pi)/2)
    assert contradiction(value("sign(sqrt(x - 2)*cos(x)**2)"), x, value("pi/2"), "+", sympy.Integer(1))     # complex on both sides
    # off the reals: excused only where the sides agree and no direction is stated
    assert contradiction(value("log(x)"), x, zero, "-", -sympy.oo, "+-", True) is None
    assert contradiction(value("log(x)"), x, zero, "-", -sympy.oo, "-")
    assert contradiction(value("exp(log(x)**2)"), x, zero, "-", sympy.oo, "+-", True) is None
    assert contradiction(value("exp(log(x)**2)"), x, zero, "-", sympy.oo, "-")
    assert contradiction(value("exp(log(x)/x**3)"), x, zero, "-", sympy.oo, "-")
    assert contradiction(value("exp(1/x**1000)"), x, zero, "-", sympy.oo, "-") is None


def test_the_generator_is_fixed_and_reaches_every_point():
    forms = generated_forms()
    assert forms == generated_forms() and len(forms) == len(ZEROS) * FORMS_PER_POINT and len(hand_forms()) > 250
    assert {point for _text, point in forms} == set(ZEROS)
    assert any("exp(" in text and on_the_list(text, point) for text, point in forms)
    assert any("exp(log(" in text and on_the_list(text, point) for text, point in forms)       # the class the read must see past the bound
    assert any("." in text and on_the_list(text, point) for text, point in forms) and "0.1" in ZEROS
    assert any("(a - b)*" in text and on_the_list(text, point) for text, point in forms)       # a symbol factor the one irrational makes 0
    assert forms_at_an_infinity() == forms_at_an_infinity() and {point for _text, point in forms_at_an_infinity()} == {"oo", "-oo"}


def test_the_disguises_stand_where_the_plan_puts_them_and_never_at_an_infinity():
    forms = disguises()
    texts = {point: {text for text, at in forms if at == point} for point in DISGUISE_POLES}
    assert forms == disguises() and set(texts) == set(DISGUISE_POLES) and {"54", "451", "0.1", "0", "pi/2"} <= set(texts)
    for point, pole in DISGUISE_POLES.items():
        written = texts[point]
        assert f"(sin(x)**2 + cos(x)**2 - 1)/({pole})**2" in written                                                  # bare over a pole
        assert f"1/({pole})**2 - (cosh(x)**2 - sinh(x)**2 - 1)/({pole})**4" in written                                # beside a pole in a sum
        assert f"(sin(x)**2)/({pole})**2 + (cos(x)**2)/({pole})**2 + (-1)/({pole})**2" in written                     # split across terms
        for call in ("log(sin(x)**2 + cos(x)**2)", "sin(pi*(sin(x)**2 + cos(x)**2))", "tan(pi*(sin(x)**2 + cos(x)**2))", "sqrt(sin(x)**2 + cos(x)**2)"):
            assert call in written and f"({call})/({pole})**2" in written                                             # a 1, through a call
        assert f"(({pole})*exp(x) - ({pole})*cosh(x) - ({pole})*sinh(x) + ({pole})**3)/({pole})**3" in written         # a coefficient under factors of x - p
        assert f"(({pole})*exp({pole}) - ({pole})*cosh({pole}) - ({pole})*sinh({pole}) + ({pole})**3)/({pole})**3" in written       # with x - p inside the call
        assert f"exp(exp(x))*(cosh(2*x/3) - 2*sinh(x/3)**2)/({pole})**2" in written                                   # over a part past the bound
        assert "((cosh(x/2) - sinh(x/2))**8*exp(4*x))**4" in written and f"(((cosh(x/2) - sinh(x/2))**8*exp(4*x))**4)/({pole})**2" in written       # a power over a sum that cancels far


def test_no_disguise_stands_at_an_infinity():
    """Known wrong readings stand there as at the base, and MEASURED.md's sentence with the counts says so."""
    assert not [text for text, _point in forms_at_an_infinity() for zero in DISGUISED_ZEROS + DISGUISED_ONES if zero in text]


def sweep_forms():
    return (generated_forms() + forms_at_an_infinity() + hand_forms() + family_of_exp_with_a_pole() + complex_under_the_calls() + disguised_zeros_at_zero()
            + exp_of_what_is_no_rational_function() + disguises() + roots_at_a_negative_point())


# What the record quotes, measured with sympy 1.14.0. The values compared move by a few from run to run, so the record rounds them.
SWEEP = {"forms": 17534, "answered": 4255, "contradicted": 2, "unfinished": 1, "off-list compositions": 656}
ABOUT_VALUES = 14000


@pytest.mark.slow
def test_no_value_the_helper_answers_is_contradicted_by_a_sample():
    """The sweep the plan asks for, its counts printed. A contradiction takes the form off the list, or stops the run."""
    trials = Trials(WORKER, ROOT / "tests")
    counts, against, contradicted, unfinished = Counter(), [], [], []
    forms = sweep_forms()
    try:
        for text, point in forms:
            got = trials.ask(text=text, point=point)
            if got is None:
                unfinished.append((text, point))
                continue
            counts[got["read"]] += 1
            counts["values compared"] += got.get("values", 0)
            against += got.get("against", [])
            contradicted += [(text, point)] if got.get("against") else []
    finally:
        trials.stop()
    measured = {"forms": len(forms), "answered": counts["answered"], "values compared": counts["values compared"],
                "contradicted": len(against), "unfinished": len(unfinished), "off-list compositions": len(composed_off_the_list())}
    print("\nlimit sweep:", json.dumps({**measured, "off the list": counts["off the list"], "refused on the list": counts["refused"]}, sort_keys=True))
    assert unexcused(contradicted) == [], against
    assert sorted(contradicted) == sorted(KNOWN_WRONG) and len(against) == SWEEP["contradicted"], against
    assert [form for form in unfinished if form not in RUNS_WITHOUT_END and not any(zero in form[0] for zero in DISGUISED_ZEROS + DISGUISED_ONES)] == []
    assert (measured["forms"], measured["off-list compositions"]) == (SWEEP["forms"], SWEEP["off-list compositions"])
    assert counts["answered"] >= 4040 and counts["values compared"] >= 13290


# ── the second slow sweep: DECIDED's evidence ────────────────────────────────────────────────────────────────────────
# Rational functions with a pole at a rational point, unexpanded, nested and cancelling, and the truth from Fraction polynomial arithmetic, with
# no sympy in it. A polynomial is its list of coefficients, lowest first, and a function a pair of them.
RATIONAL_POINTS = tuple(map(Fraction, ("0", "0", "1", "-1", "2", "1/3", "-5/2", "7")))
RATIONAL_FORMS = 10000
MOST_COEFFICIENTS = 40


def trimmed(p):
    p = list(p)
    while p and p[-1] == 0:
        p.pop()
    return p


def plus(p, q):
    return trimmed([(p[i] if i < len(p) else 0) + (q[i] if i < len(q) else 0) for i in range(max(len(p), len(q)))])


def times(p, q):
    out = [Fraction(0)] * max(len(p) + len(q) - 1, 0)
    for i, a in enumerate(p):
        for j, b in enumerate(q):
            out[i + j] += a * b
    return trimmed(out)


def value_at(p, point):
    total = Fraction(0)
    for coefficient in reversed(p):
        total = total * point + coefficient
    return total


def without_the_root(p, point):
    """How many times x - point divides p, and what is left."""
    count = 0
    while p and value_at(p, point) == 0:
        quotient, carry = [Fraction(0)] * (len(p) - 1), Fraction(0)
        for i in range(len(p) - 1, 0, -1):
            carry = p[i] + carry * point
            quotient[i - 1] = carry
        p, count = trimmed(quotient), count + 1
    return count, p


def the_truth(numerator, denominator, point):
    """What each side does at a pole, by the order and the sign of what is left, or None where the function is finite there. Sides that
    differ give no value for both."""
    above, top = without_the_root(numerator, point)
    below, bottom = without_the_root(denominator, point)
    if above >= below:
        return None
    right = value_at(top, point) / value_at(bottom, point) > 0
    left = right if (below - above) % 2 == 0 else not right
    written_as = {True: "oo", False: "-oo"}
    return {"+": written_as[right], "-": written_as[left], "+-": written_as[right] if left == right else None}


def written(number):
    return str(number.numerator) if number.denominator == 1 else f"({number.numerator}/{number.denominator})"


def rational_leaf(r, point):
    kind = r.random()
    if kind < .45:
        return f"(x - {written(point)})", ([-point, Fraction(1)], [Fraction(1)])
    if kind < .7:
        return "x", ([Fraction(0), Fraction(1)], [Fraction(1)])
    number = Fraction(r.randint(-9, 9), r.choice((1, 1, 2, 3, 7)))
    return written(number), (trimmed([number]), [Fraction(1)])


def rational_form(r, point, depth):
    """A text and the function it writes, each built by the same steps."""
    if depth == 0 or r.random() < .15:
        return rational_leaf(r, point)
    kind = r.random()
    text, (top, bottom) = rational_form(r, point, depth - 1)
    if kind < .3:
        power = r.choice((-4, -3, -2, -1, 2, 3))
        if power < 0 and not top:
            return text, (top, bottom)
        numerator, denominator = [Fraction(1)], [Fraction(1)]
        for _ in range(abs(power)):
            numerator, denominator = times(numerator, top if power > 0 else bottom), times(denominator, bottom if power > 0 else top)
        return f"({text})**({power})", (numerator, denominator)
    other, (other_top, other_bottom) = rational_form(r, point, depth - 1)
    if kind < .65:
        return f"({text} + {other})", (plus(times(top, other_bottom), times(other_top, bottom)), times(bottom, other_bottom))
    if kind < .8:
        return f"({text} - {other})", (plus(times(top, other_bottom), [-c for c in times(other_top, bottom)]), times(bottom, other_bottom))
    return f"({text})*({other})", (times(top, other_top), times(bottom, other_bottom))


def rational_forms(count=RATIONAL_FORMS):
    """Each form with a pole at its point, as written, with the truth of its sides."""
    r, forms = random.Random("limits-decided"), []
    while len(forms) < count:
        point = r.choice(RATIONAL_POINTS)
        text, (numerator, denominator) = rational_form(r, point, r.choice((2, 3, 4)))
        if not numerator or not denominator or max(len(numerator), len(denominator)) > MOST_COEFFICIENTS:
            continue
        truth = the_truth(numerator, denominator, point)
        if truth is not None:
            forms.append((text, written(point), truth, numerator, denominator))
    return forms


def refutes(truth, claim, status):
    """Whether the truth of one side refutes a reading of a claim on it: a HOLDS of what is not so, or a BROKEN of what is."""
    return (status == "CONFIRMED" and claim != truth) or (status == "MISMATCH" and claim == truth)


def test_the_fractions_read_a_pole_with_no_sympy_in_them():
    one, x_less_1 = [Fraction(1)], [Fraction(-1), Fraction(1)]
    assert the_truth(one, times(x_less_1, x_less_1), Fraction(1)) == {"+": "oo", "-": "oo", "+-": "oo"}
    assert the_truth(one, x_less_1, Fraction(1)) == {"+": "oo", "-": "-oo", "+-": None}
    assert the_truth([Fraction(-1)], times(x_less_1, x_less_1), Fraction(1)) == {"+": "-oo", "-": "-oo", "+-": "-oo"}
    assert the_truth(x_less_1, x_less_1, Fraction(1)) is None and the_truth(times(x_less_1, x_less_1), x_less_1, Fraction(1)) is None
    assert the_truth(x_less_1, times(x_less_1, times(x_less_1, x_less_1)), Fraction(1))["+-"] == "oo"       # what cancels counts for nothing
    for helper in (trimmed, plus, times, value_at, without_the_root, the_truth, rational_leaf, rational_form):
        assert "sympy" not in inspect.getsource(helper) and "M." not in inspect.getsource(helper)


def test_the_text_sent_is_the_function_the_truth_is_of():
    """Read by Python's own arithmetic at a number no pole stands on."""
    for text, _point, _truth, numerator, denominator in rational_forms(200):
        exact = re.sub(r"\d+", r"Fraction(\g<0>)", text)
        at = Fraction(101, 97)
        assert eval(exact, {"x": at, "Fraction": Fraction}) == value_at(numerator, at) / value_at(denominator, at), text


def test_the_second_sweep_refutes_what_is_false_and_leaves_what_is_true():
    assert refutes("oo", "-oo", "CONFIRMED") and refutes("oo", "oo", "MISMATCH") and refutes(None, "oo", "CONFIRMED")
    assert not refutes("oo", "oo", "CONFIRMED") and not refutes("oo", "-oo", "MISMATCH") and not refutes(None, "oo", "MISMATCH") and not refutes("oo", "oo", "NOT_APPLICABLE")


def test_the_rational_forms_are_fixed_and_reach_every_kind():
    forms = rational_forms(300)
    assert [form[:3] for form in forms] == [form[:3] for form in rational_forms(300)]
    assert {point for _text, point, *_rest in forms} == set(map(written, RATIONAL_POINTS))
    assert {"oo", "-oo", None} == {truth["+-"] for _text, _point, truth, *_rest in forms}
    assert any("**(-" in text for text, *_rest in forms) and any(" - " in text for text, *_rest in forms)
    assert any(without_the_root(numerator, Fraction(point.strip("()")))[0] > 0 for _text, point, _truth, numerator, _denominator in forms)      # a pole that cancels in part


RATIONAL_WORKER = r"""
import json, sys
sys.path[:0] = sys.argv[1:3]
from concordance.verifiers import mathematics as M
M._ensure_sympy()
print("ready", flush=True)
for line in sys.stdin:
    print(json.dumps({"status": str(M.verify_limit(json.loads(line)).status).split(".")[-1]}), flush=True)
"""
RATIONAL_SWEEP = {"forms": RATIONAL_FORMS, "claims": 6*RATIONAL_FORMS, "refuted": 0}
RATIONAL_FLOORS = {"CONFIRMED": 24000, "MISMATCH": 32000}


@pytest.mark.slow
def test_no_reading_of_a_rational_function_is_refuted_by_fractions():
    """The second sweep the plan asks for, its counts printed. A claim that truth refutes stops the run."""
    trials = Trials(RATIONAL_WORKER, ROOT / "tests")
    counts, refuted, unfinished = Counter(), [], []
    forms = rational_forms()
    try:
        for text, point, truth, _numerator, _denominator in forms:
            for direction, want in truth.items():
                for claim in ("oo", "-oo"):
                    got = trials.ask(function=text, variable="x", point=point, claimed_limit=claim, direction=direction)
                    if got is None:
                        unfinished.append((text, point, direction, claim))
                        continue
                    counts[got["status"]] += 1
                    if refutes(want, claim, got["status"]):
                        refuted.append((text, point, direction, claim, want, got["status"]))
    finally:
        trials.stop()
    measured = {"forms": len(forms), "claims": sum(counts.values()) + len(unfinished), "refuted": len(refuted), "unfinished": len(unfinished), **counts}
    print("\nrational sweep:", json.dumps(measured, sort_keys=True))
    assert refuted == [] and unfinished == []
    assert (measured["forms"], measured["claims"]) == (RATIONAL_SWEEP["forms"], RATIONAL_SWEEP["claims"])
    assert counts["CONFIRMED"] >= RATIONAL_FLOORS["CONFIRMED"] and counts["MISMATCH"] >= RATIONAL_FLOORS["MISMATCH"]


# ── the record ───────────────────────────────────────────────────────────────────────────────────────────────────────
def _bullet():
    text = (ROOT / "MEASURED.md").read_text(encoding="utf-8")
    start = text.index("- **Limits, by side.**")
    return re.sub(r"\s+", " ", text[start:text.index("**Time.**", start)])


def test_every_reading_the_record_quotes_is_a_row_here():
    quoted = set(re.findall(r"`([^`]+ = [^`]+)`", _bullet()))
    rows = {row for row, _want in MODE_ROWS + DECIMALS} | {claim for claim, _want in EXPRESSIONS} | set(TAKEN_OFF + EXPANDED + SPIRALLING + MISS_NINE + MISS_ELEVEN + MISS_FOURTEEN + MISS_FIFTEEN) | {ZERO_UNDER_SIGN}
    rows |= {"a*log(x) - b*log(x) + 1/x**2 at 0 dir - = oo", f"{WRONG_AT_AN_INFINITY} at oo = 1", f"{WRONG_FINITE_READING} at oo = 0", "((x**1000 + 1)**1000 + 1)**1000 at 7 = 1", "exp(-1/x**1000) at 0 dir - = 0",
             "Limit(log(x), x, 0) = 5", "limit(x, x, oo) = 5", "x at limit(x, x, oo) = 5", "1/x at limit(x, x, oo) = 0"}
    rows |= {one for _both, one in MISS_FIVE}
    assert len(quoted) >= 12 and quoted <= rows, quoted - rows


def test_the_record_says_what_was_found_what_the_rule_does_and_names_its_misses():
    bullet = _bullet()
    for words in ("answers from one side", "oo from oo, which is nan", "`direction`", "`_limit_answer`", "BROKEN for every claimed value",
                  "left and right in the data", "`UnboundRefused`", "right-hand and left-hand", "one-sided, which names no side", "A side word with any dash reads as its hyphen form",
                  "sympy's sides can agree and be wrong", "the left side runs to 0.0472", "So the trust is structural", "`_on_the_list`",
                  "decided before any limit runs", "whatever sympy would answer", "floor, ceiling, frac, Mod, Piecewise, Max, Min, acot, atan2, erf",
                  "a variable exponent and a function of a diverging argument", "the whole function times a number or as 1/(number + that)",
                  "a factor of the whole product", "only as x - p", "off at 1 and -1", "PLAIN: every number is real and plain", "at most 10**6", "I is not plain",
                  "SETTLED: sympy's is_zero and is_finite decide nothing", "above 10**-30 at 40 digits", "inner values first and inside the read's bound",
                  "NO ZERO HIDES: sympy's reading rests on a zero test it cannot make", "is read once, bottom-up", "reads non-zero at 40 digits and at 80", "the two reads agree to 10 digits",
                  "the read at 40 returns at least 100 bits", "a zero that is 0 everywhere is off the list wherever it stands", "a disguised 1 read through a call", "Only exp stands past the read's bound",
                  "a part that needs the distance and stands past the bound there", "held to the parser's own bound", "above 10 digits the form is off",
                  "EXACT: a form with a pole at the point has every other part holding the variable rational there", "the variable alone aside", "EXACT reads nothing numeric",
                  "decided by each one's place in the form and never by its value", "with or without side after them",
                  "The capital Limit reads the function simplified at oo and -oo", "in limit mode and lowercase limit",
                  "must also read above that margin at the read's distance", "CUTS: log, a non-integer power, asin and acos hold no symbol but the variable", "A cut holds no cut",
                  "An exp with a pole holds no log and no non-integer power", "must still stand once each other symbol is the fixed irrational", "an infinite reading there never confirms",
                  "A finite reading at an infinity stands as at the base", "a cut the fixed irrational removes",
                  "DECIDED: an infinite reading confirms only where zero is decidable", "built from the variable, rational numbers, sums, products and integer powers and nothing else",
                  "DECIDED stands in two places and nowhere else", "This is the one reading this run newly gives", "by Richardson's theorem", "DECIDED reads nothing numeric and only ever refuses",
                  "EXACT, NO ZERO HIDES and the count stand as written", "moves by DECIDED only where a reading equals it",
                  "A claim equal to an infinite reading reads INCOMPLETE anywhere but a rational function with rational coefficients at a rational point",
                  "so a wrong infinite reading can keep the base's false BROKEN on a true claim", "Limit refuses an infinite reading at any point, and limit where the claim wrote the infinity",
                  "here reads INCOMPLETE at once", "A non-integer power of a power is off the list at any finite point", "folds (g**n)**r to g**(n*r) and loses the branch", "the number splitting off first",
                  "and right side and left side, with or without the hyphen", "or from any other word naming a side", "any run of spaces or line breaks", "HEAD: a side, and two-sided, is read only at the head of a claim, the start of the text, after at most the or a", "Anywhere else it reads no side",
                  "UNREAD SIDE: prose can state a side in words no list reaches", "A side nobody read matters only where the sides disagree", "writes direction 'unstated' where it read no side and no two-sided stands at the head",
                  "a claim equal to one side reads INCOMPLETE, naming direction as what would bind it", "a claim equal to neither reads BROKEN, since no side can save it", "Where the sides agree a side changes nothing",
                  "An infinite side compares by equality first", "takes DECIDED's reason",
                  "it only ever refuses", "sqrt(2)/10**7", "past 1e21", "Apart from SETTLED and NO ZERO HIDES, no other numeric test runs at runtime", "An imaginary part is read before that bound",
                  "the same for each so no rename can move it", "A decimal reads as what it writes", "nothing on the list expands",
                  "`tests/test_limits.py`", "shed to an error and never to a verdict",
                  "A claimed value outside an AccumBounds reads BROKEN", "A one-sided limit cannot be written in the expression form",
                  "reads INCOMPLETE until the claim states a side", "true ones with the false and even with a stated side",
                  "true identities sympy cannot reduce at oo", "over a number that is not plain reads INCOMPLETE", "no benchmark case or tier row carries direction", "sympy 1.14.0",
                  "Twelve misses are named", "A non-integer power of a power reads INCOMPLETE at any finite point, true ones with the false",
                  "A prose limit with no side read, where the sides disagree, reads INCOMPLETE when the claim equals one side, true ones with the false", *MISS_SEVENTEEN,
                  "so the first was a false HOLDS there and the second a true one", "a stated side anywhere but the start of the text being unread, a later sentence's among them",
                  "A form with a pole at the point and another part whose finite value there is not rational reads INCOMPLETE", "whose pole only the fixed irrational makes",
                  "A value too small for the read's digits at the read's distance reads INCOMPLETE", "a call other than exp past the read's bound", "a sum holding a part past it",
                  "a form that cancels more than 10 digits at the point", "a power past the parser's bound", "A finite reading at oo or -oo stands as at the base, wrong ones included",
                  "Reading both sides doubles a limit's cost", "sheds to an error where the base answered from one side"):
        assert words in bullet, words
    assert "so it cannot hang" not in bullet and "one narrowing" not in bullet


def test_the_record_says_the_list_is_measured_and_gives_the_sweeps_counts():
    bullet = _bullet()
    for words in ("The list is measured, not proved", "HOLDS there means the claim survived, nothing more", f"about {ABOUT_VALUES:,} values a claim can confirm compared",
                  "so an infinite reading past DECIDED is not compared", "A second sweep is DECIDED's evidence", f"{RATIONAL_SWEEP['forms']:,} rational functions", f"{RATIONAL_SWEEP['claims']:,} claims",
                  "no sympy in it", "0 refuted by that truth", "goes through a child that can be killed",
                  "a side off the reals excused only where sympy's sides agree and no direction is stated", "at the finite points, a decimal and large points such as 54 and 451 and negative ones among them, and at oo and -oo",
                  "plain and non-plain numbers and symbol factors such as a - b", "Disguised zeros and ones stand at the finite points alone", "bare over a pole, beside one in a sum, split across terms",
                  "as 1s through log, sin, tan and sqrt", "as coefficients under factors of x - p", "in sums that cancel far and over a part past the read's bound",
                  "Roots of a power, a bare variable, a sum and a product stand under sums that cancel at negative points", "Disguises stay out at oo and -oo, where known wrong readings stand as at the base", "exp(sqrt(x**2 + x) - x) and that form times 0.1 at oo, named by exact text and point with their count pinned",
                  "each a finite reading the base reads too", "what a contradiction finds comes off it"):
        assert words in bullet, words
    for name, count in SWEEP.items():
        assert f"{count:,} {name}" in bullet, (name, count)


def test_the_poles_record_says_where_factor_list_is_and_is_not_called():
    text = re.sub(r"\s+", " ", (ROOT / "MEASURED.md").read_text(encoding="utf-8"))
    assert "no claim makes a factor_list call" not in text
    assert "the pole compare makes no factor_list call, though simplify reaches factor_list on some claims, as it does at the base" in text


CHANGELOG_WORDS = ("A limit is read from both sides", "sign(3*x - 0.3) at 0.1 = 1 reads BROKEN where it read HOLDS", "any other word naming a side", "`direction`", "Abs(x)/x at 0 = 1 reads BROKEN where it read HOLDS", "1/x**2 at 0 = oo reads HOLDS where it read BROKEN",
                   "limit(Abs(x)/x, x, 0) = 1 reads INCOMPLETE", "now need a stated side", "Abs(x)*(1 + sqrt(x))/x at 0 = 1", "x*sin(1/x) at 0 = 0 and x**x at 0 = 1",
                   "lose their readings", "right-hand", "one-sided", "measured by a slow sweep, not proved", "on a side of a limit the claim never named",
                   "plain real numbers", "never by sympy's is_zero", "keeps a cut out of a cut", "with any dash", "x at oo = oo", "a/x**2 at 0 = oo*sign(a)",
                   "An infinite reading confirms only in a rational function with rational coefficients at a rational point", "1/(x - 1/3)**2 at 1/3 = oo", "log(x) at 0 dir + = -oo",
                   "1/(x - sqrt(2))**2 at sqrt(2) = oo", "(cosh(x)**2 - sinh(x)**2 - 1)*x at oo = 0 stays a false BROKEN", "Limit(log(x), x, 0) = 5", "1/x at limit(x, x, oo) = 0",
                   "A non-integer power of a power is off the list at any finite point", "sqrt(x**2) at -2 = 2", "as do right side and left side", "at the head of a claim", "direction 'unstated'",
                   "a claim equal to one side reads INCOMPLETE", "a claim equal to neither reads BROKEN",
                   "a zero that is 0 everywhere is off it wherever it stands", "((a + 1)**2 - a**2 - 2*a - 1)/x**2 at 0 = 0", "log(1 + x**7)/x**7 at 0 = 1", "sin(x**70) at 2 = sin(2**70)",
                   "x + exp(exp(x)) at 50 = 50 + exp(exp(50))", "exp(x)/(x - 1)**2 at 1 = oo", "(exp(x) - E)/(x - 1) at 1 = E", "sin(x)/(x - a) at b = sin(b)/(b - a)", "cosh(x) - sinh(x) at 100 = exp(-100)",
                   "Abs(x)/(Abs(x) + x) at 0 dir - = 0", "with or without side after them", "Limit reads the function simplified at oo and -oo")


def test_the_changelog_says_which_claims_moved():
    unreleased = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").split("## Unreleased", 1)[1].split("\n## ", 1)[0]
    flat = re.sub(r"\s+", " ", unreleased)
    assert all(words in flat for words in CHANGELOG_WORDS), [words for words in CHANGELOG_WORDS if words not in flat]
