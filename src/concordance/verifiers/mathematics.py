"""Mathematics verifier — symbolic checks via sympy.

  * equality   : simplify(a - b) == 0, with a removable-singularity / pole GUARD
                 so x/x == 1 is NOT sealed as an unconditional identity
  * derivative : d/dx f == g symbolically
  * inequality : L op R symbolically, with a sampling fallback
  * integral / limit / solve / series / matrix / ode

sympy (~4s import) loads on first use via _ensure_sympy, so the engine cold start
stays fast. Ported as-is from 1.0 — the derivation moat, the 0-false-positive crown.
"""
from __future__ import annotations

import ast as _ast
import builtins as _builtins
import functools as _functools
import itertools as _itertools
import math as _math
import operator as _operator
import re as _re
import types as _types
import unicodedata as _unicodedata
from typing import Any, Dict, List

from .base import VerifierResult, band, clamp_tol, confirm, error, mismatch, na
from .base import literal_is_claim, stated_precision, stated_window, window_for
from .base import dispatch  # declarative run() driver
from ._integer import _claimed_integer, _exact_integer  # THE RULE's two readers (verifiers/_integer.py)

simplify = diff = integrate = limit = solve = None
Symbol = oo = S = expand = _SympifyError = None
_PARSE_ERRORS = (SyntaxError, TypeError, ValueError, NotImplementedError)
_sympy_loaded = False
_sympy_ok = None  # None = untried; True/False after first attempt
# The parser's tables, built once from sympy in _ensure_sympy.
_sp = None                  # the sympy module
_SYMPY_VALUES = ()          # what counts as a sympy value: Basic, and MatrixBase, since a mutable Matrix is no Basic
_FUNCTIONS: Dict[str, Any] = {}     # each name on _ALLOWED_FUNCS that sympy binds to a callable
_CONSTANTS: Dict[str, Any] = {}     # the only names that read as a value without the caller supplying them
_NOT_SYMBOLS = frozenset()  # every other name sympy would read as something other than a symbol


def _ensure_sympy() -> bool:
    """Import sympy on first use. Idempotent. Returns True if sympy is available, False on a
    stdlib-only box (the optional `math` extra is not installed). Callers degrade to a clean
    NOT_APPLICABLE — the symbolic checks genuinely need sympy — rather than crash, so the engine
    keeps running offline. (set_algebra does not need sympy; it uses the pure-stdlib engine.)"""
    global simplify, diff, integrate, limit, solve
    global Symbol, oo, S, expand, _SympifyError, _PARSE_ERRORS, _sympy_loaded, _sympy_ok
    global _sp, _SYMPY_VALUES, _FUNCTIONS, _CONSTANTS, _NOT_SYMBOLS
    if _sympy_loaded:
        return _sympy_ok
    try:
        import sympy as _sympy
        from sympy import (
            simplify as _s, diff as _d, integrate as _i, limit as _l, solve as _so,
            Symbol as _Sy, oo as _oo, S as _S, expand as _e, SympifyError as _SE,
        )
        simplify, diff, integrate = _s, _d, _i
        limit, solve, Symbol, oo, S, expand = _l, _so, _Sy, _oo, _S, _e
        _SympifyError = _SE
        _PARSE_ERRORS = (_SE, SyntaxError, TypeError, ValueError, NotImplementedError)
        bound = {n: getattr(_sympy, n, None) for n in _sympy.__all__}
        _FUNCTIONS = {n: bound[n] for n in _ALLOWED_FUNCS if callable(bound.get(n))}
        _FUNCTIONS.update(abs=abs, round=round)    # the two builtin spellings on the list
        _CONSTANTS = {n: bound[n] for n in _CONSTANT_NAMES}
        # What sympy's own auto_symbol reads as an object and not a symbol: anything `from sympy import *`
        # binds to a Basic, a class or a callable, Q, and every real builtin function.
        _NOT_SYMBOLS = frozenset(
            {n for n, v in bound.items() if isinstance(v, (_sympy.Basic, type)) or callable(v) or v is _sympy.Q}
            | {n for n, v in vars(_builtins).items() if isinstance(v, _types.BuiltinFunctionType)})
        _SYMPY_VALUES = (_sympy.Basic, _sympy.MatrixBase)
        _sp = _sympy
        _sympy_ok = True
    except ModuleNotFoundError:
        _sympy_ok = False
    _sympy_loaded = True
    return _sympy_ok


# Characters that are NOT part of any valid math expression string. ast.parse treats '#' as a
# comment and silently drops the rest, so the text after it would never be read — reject such
# inputs early.
#
# `%` WAS ON THIS LIST AND DID NOT BELONG THERE (removed 2026-08-02): SymPy evaluates `16 % 9`
# as Mod natively, and blacklisting it left the fleet unable to check MODULAR ARITHMETIC at all
# — every "n mod m = k" claim returned INCOMPLETE, found when the vortex-math assay tried to
# seal the doubling cycle (16→7, 32→5, 64→1 ... mod 9) and could not. Casting out nines is the
# oldest integrity check in bookkeeping — the ancestor of this project's own hashes — and the
# fleet could not perform it.
_INVALID_EXPR_RE = _re.compile(r"[#@!$&\[\]\{\}\\|`]")

# The word form people actually write: "16 mod 9". Normalized to the operator before parsing so
# every mode (equality, equation, solve, limit) reads it. Word-boundary only, and NEVER before a
# parenthesis: the first draft's IGNORECASE happily rewrote the function form `Mod(16, 9)` into
# `%(16, 9)` — the exact thing its own comment promised it would not touch, caught by the test
# minutes after it was written. The lookahead is the promise, made structural.
_MOD_WORD_RE = _re.compile(r"\bmod\b(?!\s*\()", _re.IGNORECASE)

# Compute-DoS guards: a short input like 9**9**9 expands to a ~369M-digit bignum.
_MAX_POW_EXP = 10000
_MAX_POW_BITS = 2 ** 20     # the size of an integer or rational power, however its base was built
_MAX_AST_NODES = 2000
_MAX_AST_DEPTH = 60
_MAX_EXPR_CHARS = 4000

# What the pole proof may spend, set by measurement with sympy 1.14.0 (MEASURED.md, "Poles, as written"). Past any limit the
# proof ends and the guard's reading stands, so a limit can never move a verdict but back to what it was.
_MAX_POLE_TERMS = 500       # every written factor of one claim, each side's product, and what a worked detail expands
_MAX_POLE_WEIGHT = 64       # one written factor's degree and coefficient bits, read without expanding: see _weight
_MAX_POLE_SYMBOLS = 12      # the symbols of one claim, which every Poly is dense in

# What a limit claim can state, and what may stand in a form whose sides are read at a finite point: see _on_the_list.
_UNSTATED = "unstated"      # what prose writes where it read no side: see verify_limit
_DIRECTIONS = ("+", "-", "+-", _UNSTATED)
_LISTED_CALLS = frozenset({"sin", "cos", "tan", "sinh", "cosh", "tanh", "exp", "log", "atan", "asin", "acos", "Abs", "sign"})
# How far a number on the list may reach: see _plain. What a value must read to count as settled: see _reads_above_the_margin.
# What a read must keep, and how far a form may cancel at the point: see _kept_its_digits and _digits_cancelled.
_MAX_PLAIN = 10**6
_MARGIN = 10**30            # a value at the point reads above 1/_MARGIN, or it is no value to rest on
_KEPT_BITS = 100
_AGREEING = 10**10          # the reads at 40 digits and at 80 agree to 10 digits
_MAX_CANCELLED = 10
# The numeric reads at runtime: see _inner_reads. Past this bound on any argument they stop, measured with sympy 1.14.0: an
# exp of 10**21 reads at once, and 10**100000 did not finish in 35 s.
_READ_DIGITS = 40
_READ_BOUND = 10**21

# SECURITY (red team 2026-08-06, CRITICAL; replaced 2026-11-04): sympy.sympify() EVALUATES arbitrary
# Python, and an expr that named its way out of it was an unauthenticated RCE reachable from public
# POST /verify. A guard in front of it was tried and is withdrawn: a check on a text that something
# else then evaluates cannot be made sufficient, because the text checked and the text evaluated
# differ. So no text from a request reaches sympify, parse_expr or any sympy entry that parses a
# string. parse_expression reads a text by walking Python's ast itself and builds sympy objects
# directly. What is not on its allowlist cannot run, because nothing runs. A missing function name
# yields INCOMPLETE (an honest gap), never a false verdict — add names here as real math needs them.
# Never add a function that parses a text built from what a request names: nsimplify did, with a
# name the request chose, and came off this list for that.
_ALLOWED_FUNCS = frozenset({
    # trig / inverse / hyperbolic
    "sin", "cos", "tan", "cot", "sec", "csc", "sinc", "asin", "acos", "atan", "acot", "asec",
    "acsc", "atan2", "sinh", "cosh", "tanh", "coth", "sech", "csch", "asinh", "acosh", "atanh",
    "acoth", "deg", "rad",
    # exp / log / roots / powers
    "exp", "log", "ln", "sqrt", "cbrt", "root", "Pow",
    # abs / sign / rounding
    "Abs", "abs", "sign", "floor", "ceiling", "frac", "round",
    # number theory / combinatorics
    "Mod", "gcd", "lcm", "igcd", "ilcm", "factorial", "factorial2", "binomial", "totient",
    "isprime", "factorint", "primerange", "nextprime", "prevprime",
    # special functions
    "gamma", "loggamma", "polygamma", "digamma", "beta", "erf", "erfc", "erfi", "zeta",
    "Ei", "li", "Si", "Ci",
    # min / max / complex
    "Min", "Max", "re", "im", "conjugate", "arg",
    # numbers / symbols
    "Rational", "Integer", "Float", "Number", "Symbol", "symbols", "Dummy",
    # relations / logic
    "Eq", "Ne", "Lt", "Le", "Gt", "Ge", "Equality", "Unequality", "StrictLessThan", "LessThan",
    "StrictGreaterThan", "GreaterThan", "Relational", "And", "Or", "Not", "Xor", "Nand", "Nor",
    "Implies", "Equivalent", "ITE", "Piecewise",
    # calculus
    "diff", "Derivative", "integrate", "Integral", "limit", "Limit", "Sum", "summation",
    "Product", "product", "Subs",
    # algebra / manipulation
    "simplify", "expand", "factor", "cancel", "together", "apart", "collect", "trigsimp",
    "radsimp", "N", "evalf", "Poly", "degree", "solve", "solveset", "roots",
    # matrices
    "Matrix", "ImmutableMatrix", "eye", "zeros", "ones", "diag", "Transpose", "det", "trace",
    "Determinant", "Trace", "Inverse", "transpose",
    # containers sympy constructors sometimes need
    "Tuple", "Interval", "FiniteSet", "S",
})

# The names that read as a value without a caller supplying them. Nothing else can: a Name is a
# caller's name, one of these, or a Symbol, so no Name yields a Python object from outside these.
_CONSTANT_NAMES = ("pi", "E", "I", "oo", "zoo", "nan", "EulerGamma", "GoldenRatio", "Catalan",
                   "TribonacciConstant", "true", "false")

# The functions that hand back a plain int or bool, not a sympy value.
_PLAIN_RESULT_FUNCS = frozenset({"igcd", "ilcm", "nextprime", "prevprime", "isprime"})

# The functions sympy's evaluate=False leaves unevaluated; every other call in an unevaluated read
# still evaluates, as it does there.
_UNEVALUATED_FUNCS = frozenset({
    "Abs", "im", "re", "sign", "arg", "conjugate", "acos", "acot", "acsc", "asec", "asin", "atan",
    "acosh", "acoth", "asinh", "atanh", "cos", "cot", "csc", "sec", "sin", "tan", "cosh", "coth",
    "csch", "sech", "sinh", "tanh", "exp", "ln", "log", "sqrt", "cbrt",
})

# The calls whose value is read only once the claim has bound it: see _gcd_or_lcm and _require_generators.
_GCD_LCM = frozenset({"gcd", "lcm"})
_GENERATOR_READERS = frozenset({"Poly", "degree"})
# The calls that substitute a value into what they are given. A degree or a Poly evaluates as it is read, so inside
# one of these it answers for the symbol and never for the value. diff and an indefinite integrate substitute nothing.
_BINDERS = frozenset({"Sum", "summation", "Product", "product", "Subs", "limit", "Limit", "solve", "solveset"})
_BINDERS_BY_LIMITS = frozenset({"integrate", "Integral"})
# What a refusal under _never_confirms says, true of every form it reaches.
_WHERE_INFINITY_CONFIRMS = "An infinite reading confirms only in a rational function with rational coefficients at a rational point"
# The two spellings of a limit, which answer through _limit_answer. Each call here reads its arguments by value: see _call.
_LIMIT_CALLS = frozenset({"limit", "Limit"})
_READ_BY_VALUE = _GCD_LCM | _GENERATOR_READERS | _LIMIT_CALLS

_ARITHMETIC = {_ast.Add: _operator.add, _ast.Sub: _operator.sub, _ast.Mult: _operator.mul,
               _ast.Div: _operator.truediv}
_TERMS, _FACTORS = (_ast.Add, _ast.Sub), (_ast.Mult, _ast.Div)

_WRITTEN_EXPONENT_RE = _re.compile(r"[eE]([+-]?[0-9_]+)$")


class ExpressionRefused(ValueError):
    """A text parse_expression will not read. A ValueError, so it is a member of _PARSE_ERRORS whether
    or not sympy has loaded yet, and each mode keeps its reading of a refused text."""


class NoMeaningRefused(ExpressionRefused):
    """A value the rule refuses. Its own kind, because a text refused this way is arithmetic with no
    meaning, never prose and never a claim that can be set aside: see _refuse_no_meaning."""


class UnboundRefused(NoMeaningRefused):
    """A value the claim never bound, refused before the call runs: see _gcd_or_lcm, _require_generators and _limit_answer.
    Its own kind, because every mode reads it as not checkable, where some read other refusals as errors."""


class PowerRefused(ExpressionRefused):
    """A text the power limits refuse. Its own kind, so an unevaluated read can say so: there a refusal
    is a pole that could not be looked for, and it must never read as no pole."""


def _normalise_expression(expr, word_mod: bool) -> str:
    """The one normal form, and the only text anything reads: no surrounding whitespace (ast.parse
    rejects it as an IndentationError), one spelling of a power, and, for mathematics alone, the word
    form of mod. Physics never read that word: there mod is a name a symbol may have, and reading the
    word would turn a claim that never parsed into one that reads."""
    expr = _MOD_WORD_RE.sub("%", str(expr)).strip() if word_mod else str(expr).strip()
    return expr.replace("^", "**")


def _bound_tree(tree) -> None:
    """Today's node and depth limits, on the tree itself. Iterative, so a long chain is refused here
    and cannot overflow the stack; it is what keeps _Reader's recursion shallow."""
    nodes = 0
    todo = [(tree, 1)]
    while todo:
        node, depth = todo.pop()
        nodes += 1
        if nodes > _MAX_AST_NODES:
            raise ExpressionRefused("expression too large")
        if depth > _MAX_AST_DEPTH:
            raise ExpressionRefused("expression too deeply nested")
        todo.extend((child, depth + 1) for child in _ast.iter_child_nodes(node))


def _ceiling(value) -> int:
    return -(-value.p // value.q)


def _settled(value):
    """The value of arithmetic an unevaluated read left written out, as 5000*2 for 10000. It rebuilds
    sums, products and powers and nothing else, so a Sum in an exponent is not run by bounding it. What
    will not rebuild, as an exponent holding a matrix, is no number to bound, and never fails a read."""
    if isinstance(value, (_sp.Add, _sp.Mul, _sp.Pow)):
        try:
            return value.func(*[_settled(arg) for arg in value.args])
        except Exception:
            return value
    return value


def _power_bits(base, exponent) -> int:
    """An upper bound on the bits of the integers base**exponent multiplies out, for a Rational
    exponent. It reads what it knows sympy carries a power through: a power's own base and exponent,
    the pieces of a Piecewise and the entries of a matrix. Everything else is default-deny: what
    carries a power cannot be known by name (a constant Poly is an integer, a matrix expression
    multiplies out when done), so a base it does not read counts every Rational inside it. So a root
    of an integer, which shows no integer at all, is bounded by the integer under it. Each step
    rounds up: a fraction never rounds the bound down. It binds a power and only a power: another
    spelling of one, such as exp of a multiple of a log, has only the timeout."""
    if isinstance(base, _sp.MatrixBase):
        # An entry of M**n is at most (rows * largest entry)**n for n >= 0. A negative power goes through
        # the determinant, whose size grows with the rows, so this is no upper bound for one.
        largest = max((_power_bits(entry, exponent) for entry in base), default=0)
        return largest + _ceiling(abs(exponent)) * base.rows.bit_length()
    if not isinstance(base, _sp.Basic):
        raise PowerRefused("a power is on a mathematical value")
    if base.is_Rational:
        return max(_operator.index(base.p).bit_length(), _operator.index(base.q).bit_length()) * _ceiling(abs(exponent))
    if isinstance(base, _sp.Piecewise):
        return max(_power_bits(piece, exponent) for piece, _condition in base.args)
    if isinstance(base, _sp.Pow):
        root, power = base.as_base_exp()
        power = _settled(power)
        if power.is_Rational:
            return _power_bits(root, abs(power * exponent))
    return sum(_power_bits(arg, exponent) for arg in base.args)


def _bound_power(base, exponent) -> None:
    """The exponent limit, and the cap on the bits of an integer or rational power. Both read the
    values already built, so they hold however the base or the exponent was written: an operator, the
    Pow function, a power nested on the base side. They bind an unevaluated read too. A call in that
    read still multiplies, and a base that collapsed in the evaluated read stands whole there, so this
    can refuse what the evaluated read took; _domain_mismatch fails closed on that."""
    exponent = _settled(exponent)
    if not getattr(exponent, "is_Number", False) or not exponent.is_finite:
        return
    if abs(exponent) > _MAX_POW_EXP:
        raise PowerRefused("exponent too large")
    if exponent.is_Rational and _power_bits(base, exponent) > _MAX_POW_BITS:
        raise PowerRefused("power too large")


def _require_sympy_values(value) -> None:
    """A value a call returned: a sympy value, or a list, tuple or dict of them at every depth. An
    iterator, a str or anything else is refused. This runs after the call, so it is a second line.
    What keeps a request's own text out of a parse is that no str and no callable can reach a call.
    A call can still parse a text sympy builds itself: a decimal in solve reaches sympy's string
    parser with numeric text made from that number, as it did before this parser existed."""
    if isinstance(value, _SYMPY_VALUES):
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _require_sympy_values(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            _require_sympy_values(key)
            _require_sympy_values(item)
    else:
        raise ExpressionRefused(f"a call returned a {type(value).__name__}, not a mathematical value")


def _holds(value, *wanted) -> bool:
    """Whether a built value is or contains any of these, through every container."""
    if isinstance(value, dict):
        return any(_holds(key, *wanted) or _holds(item, *wanted) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(_holds(item, *wanted) for item in value)
    return isinstance(value, _SYMPY_VALUES) and bool(value.has(*wanted))


def _refuse_no_meaning(value, written: bool, carried: bool) -> bool:
    """THE RULE: a value with no meaning never leaves the node that built it. sympy answers a division by
    zero and some poles with zoo, nan, AccumBounds or an oo of its own and carries on, and a later node can
    collapse that into an ordinary number: 1/zoo is 0. So each built value is tested here, at its own node,
    before anything can build on it. A value that is or contains zoo, nan or AccumBounds is refused. So is
    one that contains oo or -oo, unless it is itself written (a name that read as one) or was carried in by
    a value it was built from. It tests the value and never a name: a variable called oo is a symbol and
    earns nothing, and a written oo that reduced to a finite number carries nothing further. Returns whether
    the value holds an infinity, for the node that builds on it."""
    if _holds(value, _sp.zoo, _sp.nan, _sp.AccumBounds):
        raise NoMeaningRefused("a value with no meaning is not read")
    infinite = _holds(value, _sp.oo, -_sp.oo)
    if infinite and not (written or carried):
        raise NoMeaningRefused("an infinity nobody wrote is not read")
    return infinite


def _brief(value) -> str:
    """A value as a reason quotes it: short, so what the reason asks for is never cut off."""
    return str(value)[:40]


def _walk(values):
    """Each element of these values through every sequence, by sympy's own test for one. A dict is no sequence of
    numbers, so it stands as one element."""
    for value in values:
        if hasattr(value, "__iter__") and not isinstance(value, (dict, _sp.Dict)):
            yield from _walk(value)
        else:
            yield value


def _elements(values):
    """_walk, stopped one past what a text can write: a set can have no end. Lazy, so a first answer ends the walk."""
    return _itertools.islice(_walk(values), _MAX_AST_NODES + 1)


def _gcd_or_lcm(function, name: str, args: list):
    """THE RULE for gcd and lcm: they are read over exact rationals and nothing else. sympy reads anything else as
    polynomials, before a binder can substitute, and takes a unit it picks by the symbols' order; given a third
    number it reads that as a generator, and given a float it answers 1. So an element that is not an exact rational
    leaves the value unbound, and a bound call is the fold of sympy's two-argument function, where no number can be
    read as a generator. One element is its absolute value, so no fold keeps a sign."""
    elements = []
    for element in _elements(args):
        if not getattr(element, "is_Rational", False):
            raise UnboundRefused(f"{name} reads exact rational numbers and {_brief(element)} is not one: its value would "
                                 f"rest on a polynomial reading the claim never stated, whose unit sympy picks by the "
                                 f"symbols' order. Write exact numbers, or use mode polynomial with ring and generators")
        elements.append(element)
    if len(args) < 2 and not any(hasattr(arg, "__iter__") for arg in args):
        return function(*args)      # no sequence and no second number: sympy refuses it, and it stays refused
    if not 0 < len(elements) <= _MAX_AST_NODES:
        raise UnboundRefused(f"{name} of {'more numbers than a text can write' if elements else 'an empty sequence'} "
                             f"has no value to read. State the numbers")
    if len(elements) == 1:
        return abs(elements[0])
    return _functools.reduce(function, elements)


def _generators(value) -> tuple:
    """The generators sympy's own discovery finds in a value, in sympy's order. None where it reads none: what it
    cannot read, the call itself then answers as sympy does."""
    from sympy.polys.polytools import poly_from_expr
    try:
        return poly_from_expr(value)[0].gens
    except Exception:
        return ()


def _require_generators(name: str, args: list, binders: int) -> None:
    """THE RULE for Poly and degree: a value resting on generators nobody named is unbound. sympy discovers them and
    orders them by their names, so with two or more the value moves with what the symbols are called. A generator is
    named by a symbol, or by an expression discovery finds in the argument. Anything else in a generator's place, a
    number, a boolean, a sequence, a set or another expression, names none. sympy reads an integer there as a generator's
    index, so degree(x**2 + 1, 0) is 2, and most of the rest as a generator it does not find, where it answers 0. So each
    leaves the value unbound wherever there is a generator to miss: a constant has none. Poly reads a sequence of those
    as its generators, and a Poly carries the generators the claim gave it. Inside a binder, a
    value with a free symbol is unbound however it was written, since it evaluates before the binder substitutes: the
    reader counts binders and does not work out which symbol each one binds, so this refuses a value whose symbol
    nothing substitutes too."""
    from sympy.utilities.iterables import is_sequence
    if binders and any(getattr(element, "free_symbols", None) for element in _elements(args)):
        raise UnboundRefused(f"{name} of {_brief(args[0])} evaluates before the binder around it substitutes a value, so "
                             f"it would rest on the symbol and never on the value. Write the number it should be, or "
                             f"read it outside the binder")
    offered = args[1:]
    if name == "Poly" and len(offered) == 1 and is_sequence(offered[0]):
        offered = list(offered[0])
    if not args or (offered and all(isinstance(gen, _sp.Symbol) for gen in offered)):
        return
    carried = isinstance(args[0], _sp.Poly)
    found = args[0].gens if carried else _generators(args[0])
    stray = [gen for gen in offered if not isinstance(gen, _sp.Symbol) and gen not in found]
    if stray and found:
        raise UnboundRefused(f"{name} of {_brief(args[0])} takes {_brief(stray[0])} as a generator, which names none: only "
                             f"a symbol or a generator found in it does. Name the generators in the call, or use mode "
                             f"polynomial with ring and generators")
    if not offered and not carried and len(found) > 1:
        raise UnboundRefused(f"{name} of {_brief(args[0])} rests on the generators sympy discovers, {_brief(found)}, in an "
                             f"order their names set. Name the generators in the call, or use mode polynomial with ring "
                             f"and generators")


def _diverges(value) -> bool:
    """Whether a value read at a limit's point holds an infinity, zoo or nan."""
    return _holds(value, oo, -oo, _sp.zoo, _sp.nan)


def _fraction(value) -> bool:
    return bool(value.is_Rational) and abs(value.p) <= _MAX_PLAIN and value.q <= _MAX_PLAIN


def _root(value) -> bool:
    """A rational power of a positive fraction, in the form sympy leaves one: (2/3)**(1/3) is 2**(1/3)*3**(2/3)/3."""
    if value.is_Mul:
        return all(map(_root, value.args))
    return bool(value.is_Pow and _fraction(value.base) and value.base > 0 and _fraction(value.exp))


def _plain(value) -> bool:
    """PLAIN: a real number no zero or one can hide in. A flat sum of fractions, each alone or times pi, E or a root. A product
    of sums and a root of a sum are not plain, since (1 + sqrt(2))*(1 - sqrt(2)) + 1 is 0, and I is not, so the list reads a
    real function of a real variable at a real point."""
    for term in _sp.Add.make_args(value):
        number, rest = term.as_coeff_Mul()
        if not (_fraction(number) and (rest in (_sp.S.One, _sp.pi, _sp.E) or _root(rest))):
            return False
    return True


def _hold_to_the_power_bound(function, values: dict) -> None:
    """An exact read works a power out in full, and ((x**1000 + 1)**1000 + 1)**1000 at 7 has no symbol left to stop it, so each
    power is held to the parser's own bound before anything reads it, inner ones first. exp of a multiple of a log is another
    spelling of one, and sympy works it out the same way. Raises PowerRefused."""
    for node in _sp.postorder_traversal(function):
        if node.is_Pow:
            _bound_power(node.base.subs(values), node.exp)
        elif isinstance(node, _sp.exp):
            argument = node.args[0].subs(values)
            logs = [part for part in _sp.Mul.make_args(argument) if isinstance(part, _sp.log)]
            if len(logs) == 1:
                _bound_power(logs[0].args[0], argument / logs[0])


def _with_symbols_fixed(value, variable, point) -> tuple:
    """A value and a point with every symbol but the variable the one fixed irrational, the same for each, for one read alone:
    no renaming can move what it reads."""
    fixed = dict.fromkeys((value.free_symbols | point.free_symbols) - {variable}, _sp.sqrt(3))
    if fixed:
        _hold_to_the_power_bound(value, fixed)
    return value.subs(fixed), point.subs(fixed)


def _reads_above_the_margin(value, variable, point) -> bool:
    """SETTLED, for a value not exactly 0: it reads above the margin at 40 digits, inner values first and inside the read's
    bound. sympy's is_zero and is_finite decide nothing here: is_zero answers False for sin(cosh(1)**2 - sinh(1)**2 - 1), which
    is sin(0), and its answer on a disguised 1 moved with the hash seed. Whether a sum kept its digits is _no_zero_hides's."""
    value, point = _with_symbols_fixed(value, variable, point)
    _hold_to_the_power_bound(value, {variable: point})
    if _inner_reads(value, variable, point)[1]:
        return False
    read = value.subs(variable, point).evalf(_READ_DIGITS)
    return bool(read.is_number and abs(read) * _MARGIN > 1)


def _vanishes(value, variable, point) -> bool:
    """Whether a value is exactly 0 at the point. A zero subs does not reduce is no exact 0, and reads under the margin."""
    value, point = _with_symbols_fixed(value, variable, point)
    return value.subs(variable, point) == 0


def _settled_beside_a_zero(value, variable, point) -> bool:
    """A value that may be exactly 0 at the point: there it must also read above the margin at the read's distance, so one that
    is 0 everywhere is off the list. Elsewhere it reads above the margin at the point."""
    if _vanishes(value, variable, point):
        return _reads_above_the_margin(value, variable, point + _sp.sqrt(2) / 10**7)
    return _reads_above_the_margin(value, variable, point)


def _power_stands(power, variable, point) -> bool:
    """The base of a negative or non-integer power, settled, and a non-integer power over a zero stands only over x - p."""
    base = power.base
    if _diverges(base.subs(variable, point)):
        return power.exp.is_Integer     # the 1/(number + exp) _on_the_list places
    if not power.exp.is_Integer and base != variable - point and _vanishes(base, variable, point):
        return False
    return _settled_beside_a_zero(base, variable, point)


def _built_from_the_list(value, variable, point) -> bool:
    """The list's first sentence and its numbers, node by node: a symbol, a sum, a product, a rational power of these, and a
    call on _LISTED_CALLS whose argument is all of this and finite at the point, the function finite there too. Every part free
    of all symbols is plain. An exp with a pole passes here for _on_the_list to place, and nothing else takes an argument that
    diverges, so a function of one is off the list. Each value a pole or a jump turns on must be settled."""
    if not value.free_symbols:
        return _plain(value)
    if value.is_Symbol:
        return True
    if value.is_Add or value.is_Mul:
        free, held = value.as_independent(*value.free_symbols, as_Add=value.is_Add)
        return _plain(free) and all(_built_from_the_list(part, variable, point) for part in value.func.make_args(held))
    if value.is_Pow:
        if not _fraction(value.exp) or not _built_from_the_list(value.base, variable, point):
            return False
        return (value.exp.is_Integer and value.exp >= 0) or _power_stands(value, variable, point)
    if value.func.__name__ not in _LISTED_CALLS or not _built_from_the_list(value.args[0], variable, point):
        return False
    inner = value.args[0]
    argument = inner.subs(variable, point)
    if _diverges(argument):
        return isinstance(value, _sp.exp)
    if isinstance(value, _sp.log) and _vanishes(inner, variable, point):
        return inner == variable - point
    if isinstance(value, _sp.log):
        return _reads_above_the_margin(inner, variable, point)
    if isinstance(value, (_sp.Abs, _sp.sign)):
        return _settled_beside_a_zero(inner, variable, point)
    if isinstance(value, _sp.tan):
        return _reads_above_the_margin(_sp.cos(inner), variable, point)
    if isinstance(value, (_sp.asin, _sp.acos)):
        return all(_reads_above_the_margin(inner + edge, variable, point) for edge in (-1, 1))
    return not _diverges(value.func(argument))


def _is_cut(node) -> bool:
    return (node.is_Pow and not node.exp.is_Integer) or isinstance(node, (_sp.log, _sp.asin, _sp.acos))


def _exact(function, variable, point) -> bool:
    """EXACT: a form with a pole at the point, any part holding the variable with no finite value there, has every other part
    holding the variable rational at the point, the variable alone aside. A part is a sum, a product, a power or a call. A
    pole's reading rests on coefficients at the point: sympy decides their signs from a 2-digit read and cannot test them for
    zero, and where they are irrational a sum can cancel past what it reads and a coefficient can be 0 everywhere at any order,
    so no test of the form's parts reaches them. Where those values are rational the coefficients are exact. This reads
    nothing numeric: it is sympy's own evaluation at the point."""
    function, point = _with_symbols_fixed(function, variable, point)
    pole = inexact = False
    for node in _sp.preorder_traversal(function):
        if node.is_Atom or not node.has(variable):
            continue
        value = node.subs(variable, point)
        if _diverges(value):
            pole = True
        elif not value.is_Rational:
            inexact = True
    return not (pole and inexact)


def _kept_its_digits(value) -> bool:
    """Whether a number kept its digits: non-zero at 40 digits and at 80, the two reads agreeing to 10 digits, and the read at 40
    returning at least 100 bits. Neither test is enough alone: sympy's log and tan claim digits they lost, so
    log(cosh(54)**2 - sinh(54)**2) reads noise at full claimed precision, and its retry can land on one working precision, so
    tan(pi*(cosh(x) - sinh(x))*exp(x)) at 133 reads the same noise at both, at 1 bit."""
    once, twice = value.evalf(_READ_DIGITS), value.evalf(2 * _READ_DIGITS)
    if once == 0 or twice == 0 or not (once.is_number and twice.is_number):
        return False
    if not all(part == 0 or part._prec >= _KEPT_BITS for part in once.as_real_imag()):
        return False
    return bool(abs(once - twice) * _AGREEING <= abs(twice))


def _past_the_bound(node, variable, point) -> bool:
    """Whether a power or a call, its parts read, stands past the read's bound at the point: the power by its size, the call by
    its argument, as _inner_reads measures them. No value at the point is no read here."""
    if node.is_Pow:
        base = node.base.subs(variable, point)
        if _diverges(base):
            return False
        read = base.evalf(_READ_DIGITS)
        return bool(read != 0 and abs((node.exp * _sp.log(abs(read))).evalf(_READ_DIGITS)) > _READ_BOUND)
    if isinstance(node, _sp.Function):
        argument = node.args[0].subs(variable, point)
        return bool(not _diverges(argument) and abs(argument.evalf(_READ_DIGITS)) > _READ_BOUND)
    return False


def _no_zero_hides(function, variable, point) -> bool:
    """NO ZERO HIDES: sympy's reading rests on a zero test it cannot make, so the list makes that test first, and only by whether
    a read kept its digits. Every sum, every call and every non-integer power, with every other symbol the fixed irrational, is
    read once, bottom-up: at the point where it has a finite value, and at the read's distance where it is exactly 0 there or
    is a sum with no finite value there. So a zero that is 0 everywhere is off the list wherever it stands, and so is a disguised
    1 read through a call. Only exp stands past the read's bound, since an exp is never 0: a product or a power past it is
    unread and marks nothing, but a sum or any other call past it, or holding a part past it, settles nothing, and so does a
    part that needs the distance and stands past the bound there. Each read is bound before it runs, so none can hang."""
    function, point = _with_symbols_fixed(function, variable, point)
    near = point + _sp.sqrt(2) / 10**7
    past, seen = set(), set()
    for node in _sp.postorder_traversal(function):
        if node in seen:
            continue
        seen.add(node)
        if past.intersection(node.args) or _past_the_bound(node, variable, point):
            if node.is_Add or (isinstance(node, _sp.Function) and not isinstance(node, _sp.exp)):
                return False
            past.add(node)
            continue
        if not (node.is_Add or isinstance(node, _sp.Function) or (node.is_Pow and not node.exp.is_Integer)):
            continue
        value, at = node.subs(variable, point), point
        if _diverges(value):
            if not node.is_Add:
                continue
            at = near
        elif value == 0:
            at = near
        if at is near:
            _hold_to_the_power_bound(node, {variable: near})
            if _inner_reads(node, variable, near)[1]:
                return False
        if not _kept_its_digits(node.subs(variable, at)):
            return False
    return True


def _digits_cancelled(node, variable, point, power=1):
    """How far a form cancels at the point: for every sum with a finite non-zero value there, the digits between its largest
    term and the sum, read at 40 digits, times the powers it stands under, added across the whole form. A finite reading can
    still come from a number sympy derives and misreads, as 1 - x0**2 for acos and subs moving a log to another branch:
    acos((cosh(2*x/3) - 2*sinh(x/3)**2)/2) at 363 reads -pi/3 for a function that is pi/3. A sum exactly 0 at the point, or with
    no finite value there, counts nothing, so no margin applies and x**5 + x**7 at 0 stays on the list."""
    if node.is_Atom or not node.free_symbols:
        return 0
    digits = 0
    if node.is_Add:
        value = node.subs(variable, point)
        if value != 0 and not _diverges(value):
            whole = abs(value.evalf(_READ_DIGITS))
            largest = max(abs(term.subs(variable, point).evalf(_READ_DIGITS)) for term in node.args)
            digits = power * max(0, float(_sp.log(largest / whole, 10).evalf(10)))
    if node.is_Pow:
        return digits + _digits_cancelled(node.base, variable, point, power * abs(node.exp))
    return digits + sum(_digits_cancelled(part, variable, point, power) for part in node.args)


def _on_the_list(function, variable, point) -> bool:
    """THE LIST: the forms whose sides sympy is trusted for at a finite point, decided before any limit runs. Past it sympy's
    sides can agree and be wrong, as they are for 1/(exp(acot(x)) - exp(pi/2))**2 at 0, and no sample reaches every such form:
    each numeric test tried at runtime was beaten by a form built for it. So the trust is in what the function is built from,
    the list is measured by a slow sweep and not proved, and HOLDS on it means the claim survived. Each rule answers a false
    reading review or that sweep found. The point is plain or a bare symbol other than the variable. sympy loses the jump of an
    exp with a pole under an Add, so one stands only as the whole function times a number or as 1/(number + that), and holds no
    log and no non-integer power, where the modulus can grow while the phase spins. It reads Abs and sign at the point and not
    beside it, so each stands only as a factor of the whole product, with no other symbol inside, and that is counted by place
    and never by value: a factor does not license the same Abs elsewhere, as in Abs(x)/(Abs(x) + x). CUTS: log, a non-integer
    power, asin and acos hold no symbol but the variable, so a symbol nobody bound never decides which side of a cut it reads,
    and none of them, nor Abs nor sign, holds a cut, so no side goes complex under one. A non-integer power of a power is off,
    since sympy's leading term folds (g**n)**r to g**(n*r) and loses the branch: sqrt(x**2) - 1 at -1 reads -2. And each cut that
    holds the variable must still stand once each other symbol is the one fixed irrational, as it does not in (a - b)*log(x), so
    the read's one value never hides a side. Then _exact, _no_zero_hides and the digits a form may cancel. Every read is bound before it runs, an
    exact one by _hold_to_the_power_bound. Anything that fails to answer here is off the list."""
    try:
        if not (_plain(point) if not point.free_symbols else point.is_Symbol and point != variable):
            return False
        fixed, fixed_point = _with_symbols_fixed(function, variable, point)
        _hold_to_the_power_bound(fixed, {variable: fixed_point})
        if not _built_from_the_list(function, variable, point):
            return False
        kept = set(_sp.preorder_traversal(fixed))
        whole = function
        if function.is_Pow and function.exp == -1 and function.base.is_Add and len(function.base.args) == 2:
            whole = function.base.as_coeff_Add()[1]
        whole = whole.as_coeff_Mul()[1]
        unplaced = sum(isinstance(factor, (_sp.Abs, _sp.sign)) for factor in _sp.Mul.make_args(function))
        for node in _sp.preorder_traversal(function):
            if isinstance(node, _sp.exp) and _diverges(node.args[0].subs(variable, point)) and (node != whole or any(
                    isinstance(part, _sp.log) or (part.is_Pow and not part.exp.is_Integer)
                    for part in _sp.preorder_traversal(node.args[0]))):
                return False
            if isinstance(node, (_sp.Abs, _sp.sign)):
                unplaced -= 1
                if unplaced < 0 or node.free_symbols - {variable}:
                    return False
            if _is_cut(node) and (node.free_symbols - {variable} or (node.has(variable) and node not in kept)):
                return False
            if node.is_Pow and not node.exp.is_Integer and node.base.is_Pow:
                return False
            if (_is_cut(node) or isinstance(node, (_sp.Abs, _sp.sign))) and any(map(_is_cut, _sp.preorder_traversal(node.args[0]))):
                return False
        if not (_exact(function, variable, point) and _no_zero_hides(function, variable, point)):
            return False
        return _digits_cancelled(fixed, variable, fixed_point) <= _MAX_CANCELLED
    except Exception:
        return False


def _imaginary(value) -> bool:
    """Whether a read value is a finite number with a non-zero imaginary part."""
    return bool(value.is_number and value.is_finite and value.as_real_imag()[1] != 0)


def _inner_reads(function, variable, at) -> tuple:
    """Reads a function at a number, inner values first, so nothing past the bound reaches a call that would run without end
    on it. Returns whether any call or power argument, a power's base, or the value of a call or power inside the bound has
    a non-zero imaginary part, and whether the whole stands past the bound. What holds a value past the bound is unread and
    marks nothing, and the imaginary part is read before the bound: a function that has left the reals has left them however
    large it is, and a branch past the bound hides no other branch."""
    past, left = set(), False
    for node in _sp.postorder_traversal(function):
        if past.intersection(node.args):
            past.add(node)
            continue
        if isinstance(node, _sp.Pow):
            read = node.base.subs(variable, at).evalf(_READ_DIGITS)
            size = 0 if read == 0 else (node.exp * _sp.log(abs(read))).evalf(_READ_DIGITS)
        elif isinstance(node, _sp.Function):
            read = size = node.args[0].subs(variable, at).evalf(_READ_DIGITS)
        else:
            continue
        left = left or _imaginary(read)
        if abs(size) > _READ_BOUND:
            past.add(node)
        else:
            left = left or _imaginary(node.subs(variable, at).evalf(_READ_DIGITS))
    return left, function in past


def _off_the_reals(function, variable, at) -> bool:
    """Whether the function has left the reals at a number. What cannot be read marks nothing, so a failure here is a no."""
    try:
        left, unread = _inner_reads(function, variable, at)
        if left or unread:
            return left
        return _imaginary(function.subs(variable, at).evalf(_READ_DIGITS))
    except Exception:
        return False


def _leaves_the_reals(function, variable, point, sides):
    """The side of these, if any, where the function has left the reals: one read at sqrt(2)/10**7 from the point, irrational
    so no exponent lands on an integer. For the read alone every other symbol is one fixed irrational, the same for each, in
    the function and the point alike, so no rename can move it. It only ever refuses: it never confirms a claim and never
    breaks one. Apart from SETTLED and NO ZERO HIDES, no other numeric test runs. The distance is a number and no exact value,
    since sympy turns exp(n*log(d)) into d**n with n as large as the bound, and works that out in full."""
    function, point = _with_symbols_fixed(function, variable, point)
    near = _sp.sqrt(2) / 10**7
    for side in sides:
        if _off_the_reals(function, variable, (point + near if side == "+" else point - near).evalf(2 * _READ_DIGITS)):
            return side
    return None


def _limit_answer(function, variable, point, direction: str = "+-"):
    """THE RULE for a limit, for limit mode and for the functions limit and Limit. sympy reads one side and calls it the
    limit, and its sides can agree and be wrong, so a verdict rests on what is read here, in this order. Anything that gives
    no reading raises UnboundRefused. Otherwise it returns the value, an AccumBounds that only encloses one, or None where
    the sides disagree, and the sides themselves.
    (1) At a finite point sympy's sides are read only for a form on the list. (2) At oo or -oo direction changes nothing,
    nothing is sampled and no form is listed. What an infinite reading confirms, here or anywhere, is _never_confirms's. (3)
    '+-' reads both sides and a stated direction one, and a failure, an unevaluated Limit, a nan and a zoo give no reading. (4) A function
    that leaves the reals on a side, where a direction is stated or the sides disagree, gives none. Where sympy's sides agree
    that refuses nothing, so sqrt(x) at 0 = 0 stands. (5) An AccumBounds is an enclosure, and one held inside a call encloses
    nothing that can be read. (6) Sides that agree give the value, compared by equality before any subtraction at a finite
    point, since oo less oo is nan."""
    infinite = point in (oo, -oo)
    if not infinite and not _on_the_list(function, variable, point):
        raise UnboundRefused(f"{_brief(function)} at {_brief(point)} is off the list of forms whose sides are read at a finite "
                             f"point, where sympy's sides can agree and be wrong. Write it from plain numbers, sums, products, "
                             f"rational powers and sin, cos, tan, sinh, cosh, tanh, exp, log, atan, asin, acos, Abs and sign")
    sides = {}
    for side in "+" if infinite else direction:
        try:
            sides[side] = limit(function, variable, point, side)
        except Exception as e:
            raise UnboundRefused(f"sympy could not read the {side} side of {_brief(function)} at {_brief(point)}: "
                                 f"{type(e).__name__}. A verdict needs that side") from None
        if sides[side].has(_sp.Limit, _sp.nan, _sp.zoo):
            raise UnboundRefused(f"sympy's {side} side of {_brief(function)} at {_brief(point)} reads {_brief(sides[side])}, "
                                 f"which is no value. A verdict needs that side")
    first, last = list(sides.values())[0], list(sides.values())[-1]
    enclosed = _holds([first, last], _sp.AccumBounds)
    agree = first == last or (not enclosed and simplify(first - last) == 0)
    if not infinite and (direction != "+-" or not agree):
        left = _leaves_the_reals(function, variable, point, sides)
        if left:
            raise UnboundRefused(f"{_brief(function)} leaves the reals on the {left} side of {_brief(point)}, so sympy's side "
                                 f"is a branch the claim never named. State a direction on a side where it stays real")
    if enclosed and not (agree and isinstance(first, _sp.AccumBounds)):
        raise UnboundRefused(f"sympy's reading of {_brief(function)} at {_brief(point)} holds an enclosure inside a call, "
                             f"{_brief(first)}, so it gives no value to compare")
    return (first if agree else None), sides


def _rational_function(form, variable) -> bool:
    """Whether a form is built from the variable, rational numbers, sums, products and integer powers, and nothing else."""
    if form.is_Add or form.is_Mul:
        return all(_rational_function(part, variable) for part in form.args)
    if form.is_Pow:
        return bool(form.exp.is_Integer) and _rational_function(form.base, variable)
    return form == variable or bool(form.is_Rational)


def _never_confirms(value, function, variable, point) -> bool:
    """DECIDED: an infinite reading confirms only where zero is decidable, in a rational function of the variable at a rational
    point. There every coefficient is an exact rational, no digit is read and no branch is taken, so sympy's order and sign are
    facts. Anywhere else a claim equal to one reads not checkable, true ones with the false: oo and -oo fall outside it, where
    sympy answers oo for (cosh(x)**2 - sinh(x)**2 - 2)*x, which is -x, and so does a reading holding a symbol, since
    sign((a + 1)**2 - a**2 - 2*a - 1) is sign(0). Past that place zero is undecidable in general, by Richardson's theorem, and
    every test of a form's parts tried here was beaten by a form built for it: (sqrt(x**2) - 2)**2/(x + 2)**2 at -2 reads oo
    for a function that is 1. This reads nothing numeric and only ever refuses."""
    return _diverges(value) and not (point.is_Rational and _rational_function(function, variable))


def _limit_call(name: str, args: list):
    """The functions limit and Limit: the value when _limit_answer has one, and for anything else UnboundRefused, so neither
    ever answers from one side. A fourth argument, the only way these could state a side, stays refused: limit mode states
    one. Limit reads the function simplified at oo and -oo, as the base's compare did, so a finite reading there stands as at
    the base in every spelling."""
    if len(args) != 3:
        raise ExpressionRefused(f"{name} takes a function, a variable and a point. Limit mode states a side")
    if name == "Limit" and args[2] in (oo, -oo):
        args = [simplify(args[0]), *args[1:]]
    value, sides = _limit_answer(*args)
    if value is None:
        raise UnboundRefused(f"{name} of {_brief(args[0])} at {_brief(args[2])} has no one value: sympy reads "
                             f"{', '.join(map(_brief, sides.values()))}. Use limit mode, where direction states a side")
    if isinstance(value, _sp.AccumBounds):
        raise UnboundRefused(f"{name} of {_brief(args[0])} at {_brief(args[2])} has no one value to rest on: sympy reads it "
                             f"only as enclosed by {_brief(value)}")
    if _never_confirms(value, *args):
        raise UnboundRefused(f"{name} of {_brief(args[0])} at {_brief(args[2])} reads {_brief(value)}. {_WHERE_INFINITY_CONFIRMS}")
    return value


class _Reader:
    """Builds sympy objects from a bounded tree. A node it does not name is refused."""

    def __init__(self, source: str, names: Dict[str, Any], rational: bool, evaluate: bool, binders: int = 0):
        self.source, self.names, self.rational, self.evaluate = source, names, rational, evaluate
        self.carried = False    # whether a value the node being built was built from held an infinity
        self.binders = binders  # how many calls that substitute a value the node being built sits inside

    def read(self, node, in_call: bool = False):
        """Every node passes through here, so each built value meets the rule at its own node. Only a read
        that evaluates is tested: the unevaluated read is how a pole is seen, and a refusal there would
        read as no pole."""
        if not self.evaluate:
            return self._build(node, in_call)
        outer, self.carried = self.carried, False
        value = self._build(node, in_call)
        infinite = _refuse_no_meaning(value, isinstance(node, _ast.Name), self.carried)
        self.carried = outer or infinite
        return value

    def _build(self, node, in_call: bool):
        if isinstance(node, _ast.Constant):
            return self._number(node)
        if isinstance(node, _ast.Name):
            return self._name(node.id)
        if isinstance(node, _ast.BinOp):
            return self._binop(node)
        if isinstance(node, _ast.UnaryOp):
            return self._unary(node)
        if isinstance(node, _ast.Compare):
            return self._compare(node)
        if isinstance(node, _ast.Call):
            return self._call(node)
        if isinstance(node, _ast.Tuple) and in_call:   # so a matrix or a Sum limit can be written
            return tuple(self.read(item, in_call=True) for item in node.elts)
        raise ExpressionRefused(f"a {type(node).__name__} is not read as mathematics")

    def _number(self, node):
        if type(node.value) is int:
            return _sp.Integer(node.value)
        if type(node.value) is float:
            written = _ast.get_source_segment(self.source, node)
            exponent = _WRITTEN_EXPONENT_RE.search(written)    # a written 1eN is the power 10**N,
            if exponent and abs(_exact_integer(exponent.group(1))) > _MAX_POW_EXP:    # and sympy expands it whole
                raise ExpressionRefused("exponent too large")
            return _sp.Rational(written) if self.rational else _sp.Float(written)
        raise ExpressionRefused(f"a {type(node.value).__name__} literal is not a number here")

    def _name(self, name: str):
        if name.startswith("_"):
            raise ExpressionRefused("names beginning with underscore are not allowed")
        if name in self.names:
            return self.names[name]
        if name in _CONSTANTS:
            return _CONSTANTS[name]
        if name in _ALLOWED_FUNCS or name in _NOT_SYMBOLS:
            raise ExpressionRefused(f"{name} is not a value")
        return Symbol(name)

    def _evaluating(self):
        """The reader of what an unevaluated read still evaluates."""
        return self if self.evaluate else _Reader(self.source, self.names, self.rational, True, self.binders)

    def _operand(self, node):
        value = self.read(node)
        if not isinstance(value, _SYMPY_VALUES) or isinstance(value, _sp.Tuple):
            raise ExpressionRefused("arithmetic is on sympy values only, never a tuple or list")
        return value

    def _binop(self, node):
        op = type(node.op)
        if op is _ast.Mod:
            # sympy's evaluate=False leaves % and everything under it evaluated.
            reader = self._evaluating()
            return reader._operand(node.left) % reader._operand(node.right)
        if op is not _ast.Pow and op not in _ARITHMETIC:
            raise ExpressionRefused(f"the operator {op.__name__} is not read as mathematics")
        if op is _ast.Pow and any(isinstance(n, _ast.BinOp) and isinstance(n.op, _ast.Pow)
                                  for n in _ast.walk(node.right)):
            raise ExpressionRefused("nested power tower not allowed")
        if op is not _ast.Pow and not self.evaluate:
            kind = _sp.Add if op in _TERMS else _sp.Mul
            return kind(*self._unevaluated_args(node), evaluate=False)
        left, right = self._operand(node.left), self._operand(node.right)
        if op is _ast.Pow:
            _bound_power(left, right)
            return left ** right if self.evaluate else _sp.Pow(left, right, evaluate=False)
        return _ARITHMETIC[op](left, right)

    def _unevaluated_args(self, node) -> list:
        """The arguments sympy's evaluate=False gives one Add or Mul. It flattens a sum written in a
        sum and a product written in a product, so x+(y+z) and x+y+z have one pole base. It does that
        to the tree, before anything is built: by the value built, a sum a call returned would be
        flattened too, and a product holding a matrix, which is a matrix by then, would not be."""
        op = type(node.op)
        ops = _TERMS if op in _TERMS else _FACTORS
        left = self._flattened(node.left, ops)
        if op is _ast.Sub:
            return left + [_sp.Mul(-1, self._operand(node.right), evaluate=False)]
        if op is _ast.Div:
            return left + [_sp.Pow(self._operand(node.right), -1, evaluate=False)]
        return left + self._flattened(node.right, ops)

    def _flattened(self, node, ops) -> list:
        if isinstance(node, _ast.BinOp) and type(node.op) in ops:
            return self._unevaluated_args(node)
        return [self._operand(node)]

    def _unary(self, node):
        if isinstance(node.op, _ast.USub):
            return -self._operand(node.operand)
        if isinstance(node.op, _ast.UAdd):
            return +self._operand(node.operand)
        raise ExpressionRefused(f"the operator {type(node.op).__name__} is not read as mathematics")

    def _compare(self, node):
        relation = {_ast.Lt: _sp.Lt, _ast.LtE: _sp.Le, _ast.Gt: _sp.Gt,
                    _ast.GtE: _sp.Ge}.get(type(node.ops[0]))
        if relation is None or len(node.ops) != 1:
            raise ExpressionRefused("one comparison by <, <=, > or >= is all that is read")
        left, right = self._operand(node.left), self._operand(node.comparators[0])
        return relation(left, right) if self.evaluate else relation(left, right, evaluate=False)

    def _call(self, node):
        func = node.func
        if not isinstance(func, _ast.Name) or func.id not in _ALLOWED_FUNCS:
            raise ExpressionRefused("call to a non-mathematical function is not allowed")
        name = func.id
        if name in self.names:
            raise ExpressionRefused(f"{name} is a value here, not a function")
        if name not in _FUNCTIONS:
            raise ExpressionRefused(f"{name} is not bound to a function")
        if node.keywords:
            raise ExpressionRefused("a call takes no keywords")
        # What follows the integrand and is no bare symbol is read as limits, in whatever form it was written.
        binds = name in _BINDERS or (name in _BINDERS_BY_LIMITS
                                     and not all(isinstance(arg, _ast.Name) for arg in node.args[1:]))
        self.binders += binds
        # A limit reads a decimal as what it writes: a float's rounding moves a jump or a pole off the point.
        rational, self.rational = self.rational, self.rational or name in _LIMIT_CALLS
        # The rule reads values, so it reads evaluated arguments even here in an unevaluated read, as % does: there
        # 2*3 is a product written out, and it is still the number 6.
        reader = self._evaluating() if name in _READ_BY_VALUE else self
        args = [reader.read(arg, in_call=True) for arg in node.args]
        self.rational = rational
        self.binders -= binds
        if name == "Pow" and len(args) >= 2:
            _bound_power(args[0], args[1])
        if name in _GENERATOR_READERS:
            _require_generators(name, args, self.binders)
        # sympy's rational read rewrites the name Float as well as the numbers.
        function = _sp.Rational if self.rational and name == "Float" else _FUNCTIONS[name]
        if name in _GCD_LCM:
            value = _gcd_or_lcm(function, name, args)
        elif name in _LIMIT_CALLS:
            value = _limit_call(name, args)
        elif not self.evaluate and name in _UNEVALUATED_FUNCS:
            value = function(*args, evaluate=False)
        else:
            value = function(*args)
        if name in _PLAIN_RESULT_FUNCS:
            if value is True or value is False:
                return _sp.true if value else _sp.false
            if type(value) is int:
                return _sp.Integer(value)
        _require_sympy_values(value)
        return value


def parse_expression(text, names: Dict[str, Any] = None, rational: bool = False, evaluate: bool = True,
                     word_mod: bool = False, binders: int = 0):
    """Read an expression text into sympy objects. The one way any text reaches sympy.

    It normalises the text once, and everything after reads exactly that text: the limits apply to
    the tree ast.parse builds from it, and nothing re-reads the input. Nothing is evaluated. The
    tree is walked and each node on the allowlist is built directly; every other node is refused.

    names maps the caller's names to sympy values and wins over the constants. rational=True reads
    decimals as exact rationals, as sympify's rational=True does. evaluate=False builds what sympify's
    evaluate=False builds, for reading pole bases. word_mod=True reads the word form of mod, which
    mathematics has and physics does not. binders=1 reads a text the caller will substitute a value
    into, as if inside a call that does. A text the parser will not read, and any failure while
    reading it, raises ExpressionRefused."""
    if not _ensure_sympy():
        # stdlib-only box: the symbolic-math checks need sympy. Raise a _PARSE_ERRORS member so
        # every verify_* wrapper degrades to NOT_APPLICABLE with this reason, never a crash.
        raise ValueError("requires the optional math extra (sympy); not installed on this box")
    try:
        names = names or {}
        source = _normalise_expression(text, word_mod)
        if len(source) > _MAX_EXPR_CHARS:
            raise ExpressionRefused("expression too long")
        if _INVALID_EXPR_RE.search(source):
            raise ExpressionRefused(f"invalid characters in expression: {source!r}")
        # ast normalises identifiers, so a name NFKC would change would become two symbols: one as the
        # caller wrote it, one as the text was read.
        for word in (source, *names):
            if _unicodedata.normalize("NFKC", word) != word:
                raise ExpressionRefused("a text or name Unicode normalisation would change")
        tree = _ast.parse(source, mode="eval")
        _bound_tree(tree)
        return _Reader(source, names, rational, evaluate, binders).read(tree.body)
    except ExpressionRefused:
        raise
    except Exception as e:  # a syntax error, RecursionError, or sympy refusing what it was handed
        raise ExpressionRefused(f"expression is not read as mathematics: {type(e).__name__}") from None


def _parse(expr: str, var_names: List[str] = None, rational: bool = False, evaluate: bool = True, binders: int = 0):
    if not _ensure_sympy():
        raise ValueError("requires the optional math extra (sympy); not installed on this box")
    locals_ = {n: Symbol(n) for n in (var_names or [])}
    locals_.setdefault("oo", oo)
    locals_.setdefault("inf", oo)
    # rational=True parses decimals as EXACT rationals (0.1 -> 1/10), so a chain like 520/1.04 = 500
    # or 6*0.1 = 0.60 is TRUE by exact arithmetic rather than tripping on the last IEEE-754 bit. This
    # TIGHTENS exactness (no float wobble); it never loosens it. Default off to leave every symbolic
    # caller (equality/derivative/limit/series) unchanged.
    return parse_expression(expr, locals_, rational, evaluate, word_mod=True, binders=binders)


def _pole_bases(expr):
    """Bases of NEGATIVE powers in a RAW (un-cancelled) sympy expression — the
    sub-expressions whose vanishing makes expr undefined. Detects removable
    singularities that simplify() would otherwise silently cancel."""
    from sympy import Pow
    poles = set()
    try:
        for sub in expr.atoms(Pow):
            base, exp_ = sub.as_base_exp()
            if exp_.is_number and exp_.is_negative and getattr(base, "free_symbols", set()):
                poles.add(base)
    except Exception:
        pass
    return poles


def _domain_mismatch(a_str, b_str, var_names):
    """If expr_a and expr_b have DIFFERENT poles, an equality that simplifies to zero
    is true only OFF that singular set — NOT an unconditional identity, and must not be
    sealed as a clean HOLDS. Returns a description of the differing poles, or None when
    the domains match. Re-reads the same normalised text unevaluated, so x/x is not auto-reduced
    to 1 before its pole can be seen. A read the power limits or the rule refuse raises, as a member of
    _PARSE_ERRORS, so verify_equality reads the claim as not checkable: a pole that could not be
    looked for is never no pole. Any other failed read is no mismatch, as it has always been."""
    try:
        ra = _parse(a_str, var_names, evaluate=False)
        rb = _parse(b_str, var_names, evaluate=False)
    except (PowerRefused, NoMeaningRefused):
        raise
    except Exception:
        return None
    pa, pb = _pole_bases(ra), _pole_bases(rb)
    if pa == pb:
        return None
    diff_ = pa.symmetric_difference(pb)
    return ", ".join(sorted(str(p) for p in diff_)) if diff_ else None


def _term_estimate(value) -> int:
    """At most how many terms expanding a value writes, read without expanding it, and one past the bound for anything
    that count is not true of. It is true only of a rational function of the free symbols, built here from what the count
    can see: atoms, sums, which add, products, which multiply, and integer powers, which count the terms of their
    multinomial, an inverse too, since expand multiplies out a denominator. A number may also take a rational power. Past
    those, expand reaches what no count sees: it splits a**(60 + t) into a**60*a**t and multiplies that out, and
    exp(60*log(a) + t) is the same power. The count stops one past the bound, so no nesting can make the estimate the cost."""
    over = _MAX_POLE_TERMS + 1
    if getattr(value, "is_Atom", False):
        return 1
    if isinstance(value, _sp.Pow) and (value.exp.is_Integer or (value.exp.is_Rational and not value.base.free_symbols)):
        terms = _term_estimate(value.base)
        return min(_math.comb(min(_ceiling(abs(value.exp)), over) + terms - 1, terms - 1), over)
    product = isinstance(value, _sp.Mul)
    if not product and not isinstance(value, _sp.Add):
        return over
    total = 1 if product else 0
    for part in value.args:
        terms = _term_estimate(part)
        total = min(total * terms if product else total + terms, over)
    return total


def _written_out(node) -> bool:
    """THE LIST, on the text's syntax tree: a name, an integer, a sign on one of those, and +, -, *, / and ** with an
    integer exponent. It is a list of what may stand, so anything else ends the proof. A call and a % have already run in
    the unevaluated read, so what sat under them was never read for a pole. A decimal reads as a float, where two zeros can
    become one. A sign stands on a name or an integer alone: sympy adds a negated sum's terms back up, so -(1/x - 1/x) is 0
    in the unevaluated read and its pole is gone with no call in the text."""
    if isinstance(node, _ast.BinOp):
        if isinstance(node.op, _ast.Pow):
            exponent = node.right.operand if isinstance(node.right, _ast.UnaryOp) else node.right
            return _written_out(node.left) and isinstance(exponent, _ast.Constant) and _written_out(node.right)
        return type(node.op) in _ARITHMETIC and _written_out(node.left) and _written_out(node.right)
    if isinstance(node, _ast.UnaryOp):
        return (isinstance(node.op, (_ast.USub, _ast.UAdd)) and isinstance(node.operand, (_ast.Name, _ast.Constant))
                and _written_out(node.operand))
    return isinstance(node, _ast.Name) or (isinstance(node, _ast.Constant) and type(node.value) is int)


def _rational_value(value) -> bool:
    """The same list on the unevaluated value: a sum, a product, an integer power, a symbol or a rational, and nothing else.
    The syntax tree cannot say this alone, since pi, E and I are names there and only the value knows they are no symbols."""
    if isinstance(value, _sp.Pow):
        return value.exp.is_Integer and _rational_value(value.base)
    if isinstance(value, (_sp.Add, _sp.Mul)):
        return all(map(_rational_value, value.args))
    return value.is_Symbol or value.is_Rational


def _weight(value) -> int:
    """What a value of the list weighs, read without expanding: its degree at most, and about its coefficients' bits, which
    the factors of a term add to and a power multiplies. A term count cannot see either, and each is a cost of its own. Poly
    is dense, so twelve terms near degree 9000 in each of twelve symbols took 19.9 s to build, and eight binomials with
    coefficients of 500,000 bits did not multiply out in 25 s, in a ring or anywhere."""
    if isinstance(value, _sp.Pow):
        return _weight(value.base) * abs(_operator.index(value.exp))     # an integer power: _rational_value's list
    if isinstance(value, _sp.Mul):
        return sum(map(_weight, value.args))
    if isinstance(value, _sp.Add):
        return max(map(_weight, value.args))
    return 1 if value.is_Symbol else _operator.index(max(abs(value.p), value.q)).bit_length()


def _written_factors(base) -> list:
    """A pole base's factors as written: a product's arguments and the base of a positive integer power, nothing expanded.
    Each one's zeros are zeros of the base, and every zero of the base is a zero of one of them."""
    if isinstance(base, _sp.Mul):
        return [factor for arg in base.args for factor in _written_factors(arg)]
    if isinstance(base, _sp.Pow) and base.exp.is_Integer and base.exp > 0:
        return _written_factors(base.base)
    return [base]


def _unit_free(poly):
    """A polynomial's primitive part with its sign fixed, so two that differ by a nonzero constant are one. Which sign is
    any fixed choice, since it is only ever compared, so sympy's order of the symbols cannot move an answer."""
    part = poly.primitive()[1]
    return -part if part.LC() < 0 else part


def _product(polys, ring):
    """Polynomials multiplied out in sympy's sparse ring, whose cost is their terms. A Poly's own product is dense, so it walks
    every power of every symbol: a claim of 161 characters, inside every limit here, took 4.8 s that way and 0.06 s this way."""
    return _functools.reduce(_operator.mul, (ring.from_dict(poly.as_dict(native=True)) for poly in polys))


def _same_zeros(a_str, b_str, var_names) -> bool:
    """Whether the two sides' denominators are proved to vanish together. Asked before a confirm, once _domain_mismatch has
    named a difference, so a claim with a non-zero difference reaches it on the stated-precision path alone. It can only
    lift: True reads as if no difference were named, and anything else, every failure included, keeps the guard's reading.
    So its worst case is what the guard did alone, and there is no third answer. Each side must be a rational function with
    rational coefficients, written out, read twice before anything is evaluated, because _pole_bases reads only what stands
    in that read: a term that cancels takes its pole with it, and the proof must see every denominator or none. Then the
    written factors of every pole base compare as polynomials over QQ, and what matches leaves. What is left on both sides
    is multiplied out, since a product has exactly the zeros of its factors, so equal products prove the zeros equal. That
    is a check and not a search, so nothing here factors: no limit read beforehand bounds what factoring costs."""
    try:
        if not all(_written_out(_ast.parse(_normalise_expression(text, True), mode="eval").body) for text in (a_str, b_str)):
            return False
        sides = [_parse(text, var_names, evaluate=False) for text in (a_str, b_str)]
        if not all(map(_rational_value, sides)):
            return False
        left, right = ({factor for base in _pole_bases(side) for factor in _written_factors(base)} for side in sides)
        factors = left | right
        numbers = {factor for factor in factors if factor.is_number}
        if not all(number.is_Rational and number != 0 for number in numbers):
            return False
        symbols = sorted(sides[0].free_symbols | sides[1].free_symbols, key=str)
        if (len(symbols) > _MAX_POLE_SYMBOLS or sum(map(_term_estimate, factors)) > _MAX_POLE_TERMS
                or max(map(_weight, factors)) > _MAX_POLE_WEIGHT):
            return False
        polys = {factor: _sp.Poly(factor, *symbols, domain="QQ") for factor in factors - numbers}
        if any(poly.is_zero for poly in polys.values()):
            return False        # a denominator that is zero everywhere has no zeros to compare
        left, right = ({_unit_free(poly) for factor, poly in polys.items() if factor in side} for side in (left, right))
        left, right = left - right, right - left
        if not left or not right:
            return not left and not right
        if max(_math.prod(len(poly.terms()) for poly in side) for side in (left, right)) > _MAX_POLE_TERMS:
            return False
        ring = _sp.ring(symbols, _sp.QQ)[0]
        return _product(left, ring).monic() == _product(right, ring).monic()
    except Exception:
        return False


_REFUSAL = "cannot parse "


def _refused(name: str, reason, what: str = "expression") -> VerifierResult:
    """A mode's reading of a text it could not read. run() tells this from any other NOT_APPLICABLE."""
    return na(name, f"{_REFUSAL}{what}: {reason}")


_REMOVABLE = "a removable singularity makes this NOT an unconditional identity (e.g. x/x is undefined at x=0)"


def _pole_answer(a, b, dm, var_names, consequence: str = _REMOVABLE):
    """What the poles answer before a confirm, or None when they raise nothing. Every confirm in verify_equality reads this
    first, however the two sides came to agree: a side that cancelled to a number still has the pole it was written with,
    so arithmetic and a stated window can no more lift a removable singularity than simplify can. Only the proof lifts."""
    if dm and not _same_zeros(a, b, var_names):
        return mismatch("mathematics.equality",
                        f"{a} == {b} holds only off the singular set (denominator vanishes at: {dm}); {consequence}")
    return None


def _worked_equality(a, b, ea, eb, lifted=None):
    """Human-readable detail SHOWING the work behind a confirmed equality (the canonical
    form both sides reduce to). Every form is computed by sympy, never fabricated. A value that
    is no rational function of its free symbols, or is past the term bound, is not worked, and the
    plain detail stands. Nor is a claim the proof lifted: the guard used to answer before this
    ran, and simplify on one side has no bound a term count can give: ten fractions in ten
    symbols estimate 22 terms, and it did not finish in 30 s."""
    if lifted or max(_term_estimate(ea), _term_estimate(eb)) > _MAX_POLE_TERMS:
        return f"{a} = {b}; the difference simplifies to 0"
    try:
        ca, cb = expand(ea), expand(eb)
        if ca == cb:
            return f"{a} = {b}; both sides reduce to {ca}"
    except Exception:
        pass
    try:
        sa = simplify(ea)
        return (f"{a} = {b}; the two sides are equal -- each reduces to {sa}, "
                f"so their difference simplifies to 0")
    except Exception:
        return f"{a} = {b}; the difference simplifies to 0"


def verify_equality(spec: Dict[str, Any]) -> VerifierResult:
    _ensure_sympy()
    a = spec.get("expr_a")
    b = spec.get("expr_b")
    var_names = spec.get("variables", [])
    if a is None or b is None:
        return na("mathematics.equality")
    try:
        ea = _parse(a, var_names)
        eb = _parse(b, var_names)
        diff_ = simplify(ea - eb)
        _dm = _domain_mismatch(a, b, var_names)
        if diff_ == 0:
            return (_pole_answer(a, b, _dm, var_names)
                    or confirm("mathematics.equality", _worked_equality(a, b, ea, eb, _dm)))
        if expand(ea - eb) == 0:
            return (_pole_answer(a, b, _dm, var_names, "not an unconditional identity")
                    or confirm("mathematics.equality", _worked_equality(a, b, ea, eb, _dm)))
        # EXACT DECIMALS (2026-10-08, the failure report C3): "0.1 + 0.2 = 0.3" is TRUE, and IEEE-754 left
        # 5.55e-17 behind, which read as a mismatch. When both sides are plain numbers, re-read every decimal
        # as the exact rational it writes (0.1 = 1/10) and compare exactly — the same arithmetic that already
        # made 1/3 + 1/3 + 1/3 = 1 hold. Then, and only then, the claim's own precision: a claimed literal
        # stated to two or more figures earns half a unit in its last place (stated_tolerance_abs); a
        # one-figure literal earns nothing, and a structured call with no literal stays exact. Only a literal that
        # is the number on the claimed side earns that: any other can only narrow, and exact is already the narrowest.
        if not getattr(ea, "free_symbols", set()) and not getattr(eb, "free_symbols", set()):
            try:
                ra, rb = _parse(a, var_names, rational=True), _parse(b, var_names, rational=True)
                if simplify(ra - rb) == 0:
                    return (_pole_answer(a, b, _dm, var_names)
                            or confirm("mathematics.equality",
                                       f"{a} = {b}; by exact rational arithmetic both sides reduce to {ra}",
                                       {"exact_rational": str(ra)}))
            except NoMeaningRefused:
                raise       # undefined by exact arithmetic: the float read's window must not certify it
            except _PARSE_ERRORS:
                pass
            lit = spec.get("claimed_literal")
            tol = stated_window(lit, bool(spec.get("hedged"))) if lit not in (None, "") else None
            foreign: Dict[str, Any] = {}
            if tol is not None:
                try:
                    fa, fb = float(ea.evalf()), float(eb.evalf())
                except Exception:
                    fa = fb = None
                if fb is not None and not literal_is_claim(lit, fb):
                    foreign = {"stated_literal": str(lit), "literal_not_the_claim": True}
                elif fa is not None and _math.isfinite(fa) and _math.isfinite(fb):
                    sig = (stated_precision(lit) or (0, 0.0))[0]
                    # the stated-precision band: b must lie within ±tol of a's value
                    bd = band("mathematics.equality", fa, fb, tol, "value",
                              {"actual": fa, "claimed": fb, "stated_sigfigs": sig, "stated_tolerance_abs": tol},
                              fmt="{:.10g}")
                    if bd.status == "ERROR":
                        return bd
                    if bd.passed:
                        return (_pole_answer(a, b, _dm, var_names)
                                or confirm("mathematics.equality",
                                           f"{a} = {fa:.10g} agrees with {b} at the stated precision of {sig} significant "
                                           f"figure(s) (half a unit in the last place = ±{tol:g})", bd.data))
            if foreign:
                return mismatch("mathematics.equality", f"{a} - ({b}) simplifies to {diff_}", foreign)
        return mismatch("mathematics.equality", f"{a} - ({b}) simplifies to {diff_}")
    except _PARSE_ERRORS as e:
        return _refused("mathematics.equality", e)
    except Exception as e:
        return error("mathematics.equality", f"computation failure: {e}")


def verify_derivative(spec: Dict[str, Any]) -> VerifierResult:
    _ensure_sympy()
    f = spec.get("function")
    var = spec.get("variable", "x")
    claimed = spec.get("claimed_derivative")
    if f is None or claimed is None:
        return na("mathematics.derivative")
    try:
        x = Symbol(var)
        ef = _parse(f, [var])
        ec = _parse(claimed, [var])
        actual = diff(ef, x)
        if simplify(actual - ec) == 0:
            return confirm("mathematics.derivative", f"d/d{var} of {f} = {actual}, matches {claimed}")
        return mismatch("mathematics.derivative",
                        f"d/d{var} of {f} = {actual}, but claimed {claimed}",
                        {"computed": str(actual), "claimed": str(ec)})
    except _PARSE_ERRORS as e:
        return _refused("mathematics.derivative", e)
    except Exception as e:
        return error("mathematics.derivative", f"computation failure: {e}")


def verify_integral(spec: Dict[str, Any]) -> VerifierResult:
    _ensure_sympy()
    f = spec.get("integrand")
    var = spec.get("variable", "x")
    claimed = spec.get("claimed_antiderivative")
    if f is None or claimed is None:
        return na("mathematics.integral")
    try:
        x = Symbol(var)
        ef = _parse(f, [var])
        ec = _parse(claimed, [var])
        derivative = diff(ec, x)
        if simplify(derivative - ef) == 0:
            return confirm("mathematics.integral", f"d/d{var} of claimed antiderivative {claimed} = {ef}")
        return mismatch("mathematics.integral",
                        f"d/d{var} of {claimed} = {derivative}, expected {ef}",
                        {"derivative_of_claim": str(derivative), "integrand": str(ef)})
    except _PARSE_ERRORS as e:
        return _refused("mathematics.integral", e)
    except Exception as e:
        return error("mathematics.integral", f"computation failure: {e}")


def _equals(reading, claimed) -> bool:
    """Whether a reading is the claimed value, by equality before any subtraction, since oo less oo is nan."""
    return reading == claimed or simplify(reading - claimed) == 0


def verify_limit(spec: Dict[str, Any]) -> VerifierResult:
    """UNREAD SIDE: prose can state a side in words no list reaches, and a side nobody read matters only where the sides
    disagree. direction 'unstated' reads as both sides, and there a claim equal to one side reads not checkable, naming direction
    as what would bind it, while a claim equal to neither reads BROKEN, since no side can save it. Past DECIDED an infinite side
    takes DECIDED's reason instead, since a stated side could not confirm it. '+-' and an absent direction read BROKEN for every
    claimed value."""
    _ensure_sympy()
    f = spec.get("function")
    var = spec.get("variable", "x")
    point = spec.get("point")
    claimed = spec.get("claimed_limit")
    direction = spec.get("direction", "+-")
    if f is None or point is None or claimed is None:
        return na("mathematics.limit")
    if direction not in _DIRECTIONS:
        return _refused("mathematics.limit", f"{_brief(direction)} names no side: state '+', '-' or '+-'", "direction")
    try:
        x = Symbol(var)
        ef = _parse(f, [var], rational=True, binders=1)     # exactly, as equality reads a decimal: a float's rounding moves
        ep = _parse(str(point), [var], rational=True, binders=1)    # a jump or a pole off the point
        ec = _parse(str(claimed), [var], rational=True, binders=1)
        reads = "+-" if direction == _UNSTATED else direction
        actual, sides = _limit_answer(ef, x, ep, reads)
        written = f"lim_{{{var}->{point}{'' if reads == '+-' else reads}}} {f}"
        if actual is None:
            one_side = [side for side in sides.values() if _equals(side, ec)] if direction == _UNSTATED else []
            if one_side and _never_confirms(one_side[0], ef, x, ep):
                raise UnboundRefused(f"sympy reads {_brief(f)} as {_brief(one_side[0])} on one side, so a claim equal to it is not "
                                     f"read. {_WHERE_INFINITY_CONFIRMS}")
            if one_side:
                raise UnboundRefused(f"{written} has no one value, left {sides['-']} and right {sides['+']}, and {_brief(claimed)} "
                                     f"is one side, which nothing here read. State a direction")
            return mismatch("mathematics.limit", f"{written} has no one value: left {sides['-']}, right {sides['+']}, "
                                                 f"claimed {claimed}",
                            {"left": str(sides["-"]), "right": str(sides["+"]), "claimed": str(ec)})
        if isinstance(actual, _sp.AccumBounds):
            if (ec < actual.min) is _sp.true or (ec > actual.max) is _sp.true:
                return mismatch("mathematics.limit", f"{written} lies in {actual}, claimed {claimed}",
                                {"computed": str(actual), "claimed": str(ec)})
            raise UnboundRefused(f"sympy reads {_brief(f)} only as enclosed by {actual}, and {_brief(claimed)} is not outside "
                                 f"it, so a value inside proves nothing. State a function sympy can reduce")
        if _equals(actual, ec):
            if _never_confirms(actual, ef, x, ep):
                raise UnboundRefused(f"sympy reads {_brief(f)} as {_brief(actual)}, so a claim equal to it is not read. "
                                     f"{_WHERE_INFINITY_CONFIRMS}")
            return confirm("mathematics.limit", f"{written} = {actual}, matches {claimed}")
        return mismatch("mathematics.limit", f"{written} = {actual}, claimed {claimed}",
                        {"computed": str(actual), "claimed": str(ec)})
    except _PARSE_ERRORS as e:
        return _refused("mathematics.limit", e)
    except Exception as e:
        return error("mathematics.limit", f"computation failure: {e}")


def verify_solve(spec: Dict[str, Any]) -> VerifierResult:
    _ensure_sympy()
    eq = spec.get("equation")
    var = spec.get("variable", "x")
    claimed = spec.get("claimed_solutions")
    if eq is None or claimed is None:
        return na("mathematics.solve")
    try:
        x = Symbol(var)
        if "=" in eq and "==" not in eq:
            lhs, rhs = eq.split("=", 1)
            eq_expr = _parse(lhs, [var], binders=1) - _parse(rhs, [var], binders=1)
        else:
            eq_expr = _parse(eq, [var], binders=1)
        actual = sorted(solve(eq_expr, x), key=lambda s: str(s))
        claimed_set = sorted([_parse(str(c), [var], binders=1) for c in claimed], key=lambda s: str(s))
        if len(actual) != len(claimed_set):
            return mismatch("mathematics.solve",
                            f"solutions count mismatch: actual {actual} vs claimed {claimed_set}")
        for a, c in zip(actual, claimed_set):
            if simplify(a - c) != 0:
                return mismatch("mathematics.solve", f"solution {a} != claimed {c}",
                                {"computed": [str(s) for s in actual],
                                 "claimed": [str(s) for s in claimed_set]})
        return confirm("mathematics.solve", f"solutions {[str(s) for s in actual]} match claim")
    except _PARSE_ERRORS as e:
        return _refused("mathematics.solve", e)
    except Exception as e:
        return error("mathematics.solve", f"computation failure: {e}")


def verify_inequality(spec):
    """Verify a claimed inequality by SYMBOLIC DECISION only.

    Sampling is used solely to DISPROVE — a violation at any point makes a universal claim
    false (sound). It is NEVER used to confirm, because finite sampling can miss a violation
    between points: (x-3)**2 > 0 is false only at x=3; sin(x) <= 0.9999 only near x=pi/2.
    A truth we cannot decide symbolically is returned INCONCLUSIVE (a safe false-negative),
    never sealed as HOLDS — the 0-false-positive guarantee comes before coverage."""
    _ensure_sympy()
    import sympy as sp
    lhs, rhs = spec.get("lhs"), spec.get("rhs")
    op = spec.get("op", "<=")
    var = spec.get("variable", "x")
    if lhs is None or rhs is None:
        return na("mathematics.inequality")
    if op not in ("<", "<=", ">", ">="):
        return error("mathematics.inequality", f"bad op {op!r}")
    try:
        # SAME guards as equality (rejects '#'-truncation, giant exponents, oversized ASTs)
        L, R = _parse(lhs, [var]), _parse(rhs, [var])
    except UnboundRefused as e:
        return _refused("mathematics.inequality", e)
    except _PARSE_ERRORS as e:
        return error("mathematics.inequality", f"parse error: {e}")
    x = sp.Symbol(var, real=True)
    L, R = L.subs(sp.Symbol(var), x), R.subs(sp.Symbol(var), x)
    diff_ = sp.simplify(L - R)
    rel = {"<=": diff_ <= 0, ">=": diff_ >= 0, "<": diff_ < 0, ">": diff_ > 0}[op]

    # 1) direct symbolic decision — settles every constant comparison and many universals
    try:
        truth = sp.simplify(rel)
        if truth is sp.true:
            return confirm("mathematics.inequality", f"{lhs} {op} {rhs} holds (symbolic)")
        if truth is sp.false:
            return mismatch("mathematics.inequality", f"{lhs} {op} {rhs} is false (symbolic)")
    except Exception:
        pass

    # 2) solution-set decision for a univariate claim over the stated domain
    dom_name = spec.get("domain", "Reals")
    dom = {"Positive": sp.Interval.open(0, sp.oo),
           "Nonneg": sp.Interval(0, sp.oo)}.get(dom_name, sp.S.Reals)
    if diff_.free_symbols <= {x}:
        try:
            sol = sp.solve_univariate_inequality(rel, x, relational=False, domain=dom)
            if dom.is_subset(sol):
                return confirm("mathematics.inequality",
                               f"{lhs} {op} {rhs} holds on {dom_name} (solved)")
            return mismatch("mathematics.inequality",
                            f"{lhs} {op} {rhs} does not hold on all of {dom_name} (solved)")
        except Exception:
            pass

    # 3) counterexample search — SOUND for disproof only (a violation => genuinely false)
    for s in (-1000, -10, -1, -0.5, 0, 0.5, 1, 10, 1000):
        try:
            if dom is not sp.S.Reals and s not in dom:
                continue
            d = float(diff_.subs(x, s))
        except Exception:
            continue
        if ((op == "<=" and d > 1e-9) or (op == "<" and d >= 0)
                or (op == ">=" and d < -1e-9) or (op == ">" and d <= 0)):
            return mismatch("mathematics.inequality", f"{lhs} {op} {rhs} fails at {var}={s}")

    # 4) genuinely inconclusive — NEVER confirm from finite sampling
    return na("mathematics.inequality",
              f"{lhs} {op} {rhs}: symbolic decision inconclusive — not sealed")


def verify_set_algebra(spec: Dict[str, Any]) -> VerifierResult:
    """Set-algebra identity — the Boole/Stone bridge (the algebra of sets IS a Boolean algebra).

    Under the correspondence union -> |, intersection -> &, complement -> ~, an identity between
    set expressions holds for ALL sets exactly when the matching propositional formula is a
    tautology (Stone's representation theorem: every Boolean algebra embeds in a field of sets).
    De Morgan, distributivity and absorption for sets are decided here by exact truth-table
    enumeration over element membership (pure standard library) — the third form of one Boolean
    algebra (logic / circuits / sets), and runnable on the sovereign stdlib-only box.

    Spec:
      variables: set names, e.g. ["A", "B", "C"] (membership of an arbitrary element)
      set_a, set_b: set expressions (& intersection, | union, ~ complement, ^ symmetric difference)
      claimed_equal: bool — are the two sets equal for every choice of A, B, C?
    """
    name = "mathematics.set_algebra"
    a = spec.get("set_a")
    b = spec.get("set_b")
    claimed = spec.get("claimed_equal")
    if a is None or b is None or claimed is None:
        return na(name)
    var_names = spec.get("variables") or []
    from ._boolean import boolean_equivalent, BooleanParseError
    try:
        # sets equal for all elements iff no membership pattern separates them
        equal = boolean_equivalent(a, b, var_names)
    except BooleanParseError as e:
        return _refused(name, e, "set expression")
    except Exception as e:  # noqa: BLE001
        return error(name, f"computation failure: {e}")
    claimed_b = bool(claimed)
    if equal == claimed_b:
        return confirm(name, f"sets {a!r} and {b!r} equal-for-all={equal}, matches claim",
                       {"set_a": a, "set_b": b, "actual": equal, "claimed": claimed_b})
    return mismatch(name, f"sets {a!r} and {b!r} equal-for-all={equal}, claimed {claimed_b}",
                    {"set_a": a, "set_b": b, "actual": equal, "claimed": claimed_b})


# <<lhs=rhs>> calculator annotations and the final '#### N', for grading GSM8K-style worked solutions.
_CALC_ANNOTATION = _re.compile(r"<<\s*(.+?)\s*=\s*(.+?)\s*>>")
_FINAL_ANSWER = _re.compile(r"####\s*([\-\d.,/]+)")

# Inline arithmetic written in prose, e.g. the final step GSM8K leaves un-bracketed:
# "99 + 5 = $104", "12/20 x 100% = 60%". The LHS must carry >=1 operator so a plain "x = 5"
# variable definition is not mistaken for a computation. Currency, percent, thousands commas and
# an 'x'/'×' multiplication sign are normalized away before parsing.
_INLINE_EQ = _re.compile(
    r"(?<![\w.)])(\$?\d[\d.,]*(?:\s*[-+*/x×]\s*\$?\d[\d.,]*)+)\s*=\s*\$?(\d[\d.,]*)")
_INLINE_X = _re.compile(r"(?<=[\d)])\s*[x×]\s*(?=[\d(])")
_THOUSANDS = _re.compile(r"(?<=\d),(?=\d\d\d(?:\D|$))")
# A matched result followed by '/n' (a fraction) or ' n/n' (a mixed number) means the true value is
# longer than the integer captured — prose arithmetic is ambiguous there, so the step is SKIPPED
# rather than graded on a truncated number. Declining beats guessing.
_FRACTION_TAIL = _re.compile(r"\s*/\s*\d|\s+\d+\s*/\s*\d")
# A matched result immediately followed by an operator is not a result but the next expression in a
# chained equality "A = B = C" (GSM8K: "4 * 60 / 5 = 4 * 12 = <<4*60/5=48>>48", where our regex
# grabs "4 * 60 / 5 = 4"). Skip it — the bracketed step still carries the real check. A result
# followed by prose ("= $300 left") is a genuine final step and stays graded.
_CHAINED_TAIL = _re.compile(r"\s*[-+*/x×]")
# Prose algebra — a coefficient-variable ("2x"), a variable in an operation ("X + 3", "X*4") or a
# parenthesized variable ("(X+80)"). A segment carrying any of these is NOT graded inline: the
# equations are symbolic and the numeric fragments ("4x - 4" -> "4 - 4") would be mis-read. Single
# trailing-letter only, so ordinals/units ("7th", "5km") do not trip it into over-matching symbols.
_ALGEBRA = _re.compile(r"\d[a-zA-Z](?![a-zA-Z])|\b[a-zA-Z]\s*[-+*/=]\s*\d|\b[a-zA-Z]\s*\*|\([a-zA-Z]")


def _norm_inline(tok: str) -> str:
    """Normalize a prose arithmetic token to something _parse accepts: drop $, 'x'->*, drop
    thousands commas. Percent signs are stripped by the caller (both sides, symmetrically)."""
    t = tok.replace("$", "").replace("×", "*")
    t = _INLINE_X.sub("*", t)
    t = _THOUSANDS.sub("", t)
    return t.strip()


def _inline_is_prose(lhs: str, rhs: str, var_names) -> bool:
    """Whether an inline equation is prose to skip, not arithmetic to grade. A refusal by the rule is not
    prose: it is arithmetic with no meaning, and dropping it would let a chain certify over a false step.
    So it is kept, and _ok reads it as unparseable."""
    try:
        L = _parse(lhs, var_names, rational=True)
        R = _parse(rhs, var_names, rational=True)
    except NoMeaningRefused:
        return False
    except _PARSE_ERRORS:
        return True  # not a parseable computation -> prose, skip (never a silent confirm)
    if getattr(L, "free_symbols", None) or getattr(R, "free_symbols", None):
        return True  # contains variables -> not a pure numeric step, skip
    return not (getattr(L, "is_number", False) and getattr(R, "is_number", False))


def _calc_chain_framing(spec: Dict[str, Any]) -> VerifierResult:
    """Kind B: when there is nothing gradeable, do not just decline — EXPLAIN why and ASK for the
    structure needed to calculate, so the caller (a person, or a proposer model) can supply the work
    and we verify it. This NEVER guesses the answer; it asks for the computation. The framing lives in
    data so a surface can render the question; the status stays NOT_APPLICABLE (nothing was verified).
    Deterministic routing by what the input looks like."""
    name = "mathematics.calc_chain"
    text = spec.get("solution_text")
    if isinstance(text, str) and _ALGEBRA.search(text):
        return na(name, "reads as an equation to SOLVE, not a worked chain to CHECK — I verify "
                  "provided work, I do not solve the problem",
                  data={"need": "equation(s), the unknown(s), and a claimed solution",
                        "framing_question": "What is the equation, and the claimed value for each "
                        "unknown? Give me equations + variables + a claimed solution and I will "
                        "verify it by substitution.",
                        "example": {"equations": ["2*x = 10"], "variables": ["x"],
                                    "claimed_solution": {"x": 5}},
                        "route": "mathematics mode=system"})
    if isinstance(text, str) and text.strip():
        return na(name, "the answer is stated in prose, not as checkable arithmetic — I grade written "
                  "steps, I do not infer the computation",
                  data={"need": "the arithmetic written as steps",
                        "framing_question": "Which quantities combine to reach the answer? Write the "
                        "arithmetic as steps (e.g. '16-3-4=9', '9*2=18') and I will check every one.",
                        "example": {"calc_steps": ["16-3-4=9", "9*2=18"], "claimed_answer": 18},
                        "route": "mathematics mode=calc_chain"})
    return na(name, "no worked solution provided to grade",
              data={"need": "calc_steps or a solution_text with the arithmetic written out",
                    "framing_question": "Give me the worked steps and I will verify each one. What "
                    "calculation reaches the answer?",
                    "example": {"calc_steps": ["16-3-4=9", "9*2=18"], "claimed_answer": 18},
                    "route": "mathematics mode=calc_chain"})


def verify_calc_chain(spec: Dict[str, Any]) -> VerifierResult:
    """Grade a worked arithmetic/algebra SOLUTION: a chain of 'lhs = rhs' steps reaching a final
    answer. Each step is checked with the SAME equality engine (simplify(lhs - rhs) == 0), so a
    single wrong step is caught; the final answer, if given, must equal the last step. Accepts
    explicit steps (calc_steps = ['16-3-4=9', '9*2=18'] or [{'lhs':.., 'rhs':..}]) OR a GSM8K-style
    solution_text with <<lhs=rhs>> calculator annotations and a '#### N' final answer. In
    solution_text, inline prose equations ("99 + 5 = $104", "12/20 x 100% = 60%") are graded too —
    not just the bracketed ones — so a solution whose final step is written in prose is still
    certified; a prose fragment that is not a pure numeric computation is skipped, never silently
    confirmed. Decimals are parsed as exact rationals, so 520/1.04 = 500 and 6*0.1 = 0.60 hold by
    exact arithmetic instead of tripping on a float's last bit. Deterministic, no NL understanding —
    it grades a worked chain, it does not solve the word problem. An opt-in step_rel_tol (clamped to
    <= 1e-2) additionally accepts steps rounded to display precision (e.g. 2/3 -> 0.67); the default
    is 0 (exact), preserving the zero-false-positive guarantee."""
    name = "mathematics.calc_chain"
    if not _ensure_sympy():
        return na(name, "requires the optional math extra (sympy)")
    var_names = spec.get("variables") or []
    # Exact by default (preserving the zero-false-positive guarantee); a caller may opt into a display
    # tolerance, but clamp_tol caps it at 1e-2 and lets it only TIGHTEN — never widen the FP window.
    tol = clamp_tol(spec, "step_rel_tol", 1e-2) if spec.get("step_rel_tol") is not None else 0.0
    claimed_answer = spec.get("claimed_answer")
    pairs: List = []
    raw = spec.get("calc_steps")
    text = spec.get("solution_text")
    if raw:
        for s in raw:
            if isinstance(s, dict) and (s.get("lhs") is not None or s.get("expr") is not None):
                pairs.append((str(s.get("lhs", s.get("expr"))), str(s.get("rhs", s.get("result")))))
            elif isinstance(s, str) and "=" in s:
                lhs, rhs = s.split("=", 1)
                pairs.append((lhs, rhs))
    elif isinstance(text, str):
        # Collect <<lhs=rhs>> annotations (authoritative) in text order, then add any inline
        # prose equations that are NOT just an echo of a bracketed step (deduped by value), so the
        # final un-bracketed step GSM8K-style solutions end on is graded too. Each entry carries its
        # text position so the merged chain stays in reading order (the final-answer check compares
        # against the LAST step).
        positioned: List = []
        seen = set()

        def _key(a: str, b: str) -> str:
            return _re.sub(r"\s+", "", a) + "=" + _re.sub(r"\s+", "", b)

        # Bracketed <<lhs=rhs>> steps are authoritative. Record them AND the text segments BETWEEN
        # them: an inline scan runs per segment, never across a bracket, so an echo
        # ("a op b = <<a op b=c>>c") splits at the boundary and matches neither side — no cross-
        # binding of an LHS before a bracket to the result after it.
        segments: List = []
        last = 0
        for m in _CALC_ANNOTATION.finditer(text):
            positioned.append((m.start(), m.group(1), m.group(2)))
            seen.add(_key(m.group(1), m.group(2)))
            segments.append((last, text[last:m.start()]))
            last = m.end()
        segments.append((last, text[last:]))
        for off, seg in segments:
            if _ALGEBRA.search(seg):
                continue  # prose algebra: variables/coefficients get mis-read -> decline the segment
            for m in _INLINE_EQ.finditer(seg):
                if "%" in seg[m.start():m.end() + 1]:
                    continue  # percent is an ambiguous operand/label ("100 * 20%", "= 50%") -> decline
                if _FRACTION_TAIL.match(seg, m.end()):
                    continue  # result is a fraction/mixed number ("= 2/5", "= 3 1/2") -> decline
                if _CHAINED_TAIL.match(seg, m.end()):
                    continue  # "A = B = C": the RHS is the next expression, not a result -> decline
                pre = seg[:m.start()].rstrip()
                if pre and (pre[-1].isdigit() or pre[-1] == ")"):
                    continue  # LHS is a fragment of a mixed number ("1 1/2") or a coefficient ("(1/2) 278")
                lhs, rhs = _norm_inline(m.group(1)), _norm_inline(m.group(2))
                if _key(lhs, rhs) in seen:
                    continue  # already counted as a bracketed step
                if _inline_is_prose(lhs, rhs, var_names):
                    continue
                seen.add(_key(lhs, rhs))
                positioned.append((off + m.start(), lhs, rhs))
        positioned.sort(key=lambda t: t[0])
        pairs = [(a, b) for _p, a, b in positioned]
        if claimed_answer is None:
            fm = _FINAL_ANSWER.search(text)
            if fm:
                claimed_answer = fm.group(1).replace(",", "")
    else:
        return _calc_chain_framing(spec)
    if not pairs:
        return _calc_chain_framing(spec)

    def _ok(lhs: str, rhs: str) -> bool:
        L, R = _parse(lhs, var_names, rational=True), _parse(rhs, var_names, rational=True)
        if simplify(L - R) == 0:
            return True
        if tol > 0:
            try:
                lf, rf = float(L), float(R)
                return _math.isfinite(lf) and _math.isfinite(rf) and abs(lf - rf) <= tol * max(1.0, abs(lf))
            except (TypeError, ValueError):
                return False
        return False

    step_failures: List[str] = []
    unbound = None      # read last: a chain is false on any false step, and a refusal must not hide one
    for i, (lhs, rhs) in enumerate(pairs):
        try:
            if not _ok(lhs, rhs):
                step_failures.append(f"step {i + 1}: {lhs.strip()} != {rhs.strip()}")
        except UnboundRefused as e:
            unbound = e
        except _PARSE_ERRORS:
            step_failures.append(f"step {i + 1}: unparseable ({lhs.strip()}={rhs.strip()})")
    final_failure = None
    if claimed_answer is not None:
        try:
            if not _ok(str(claimed_answer), pairs[-1][1]):
                final_failure = f"final answer {claimed_answer} != last step {pairs[-1][1].strip()}"
        except UnboundRefused as e:
            unbound = e
        except _PARSE_ERRORS:
            final_failure = f"final answer {claimed_answer} not comparable"
    failures = step_failures + ([final_failure] if final_failure else [])
    data = {"steps": len(pairs), "final_answer": claimed_answer, "step_rel_tol": tol,
            "chain": [f"{l.strip()}={r.strip()}" for l, r in pairs][:50]}
    # Kind B: every written step checked out, but the stated answer isn't linked to the last verified
    # value — the final step was left in prose. Don't imply the math is wrong; explain and ask for the
    # missing step so we can finish the check. (Status stays MISMATCH: nothing was certified.)
    if final_failure and not step_failures:
        data["framing_question"] = (
            f"All {len(pairs)} written steps check out, but I can't connect your answer "
            f"{claimed_answer} to the last verified value ({pairs[-1][1].strip()}) — the final step "
            f"isn't written out. Show it as 'a op b = {claimed_answer}' and I'll verify it.")
        data["need"] = "the final computation, written as a step"
    if failures:
        return mismatch(name, "; ".join(failures)[:300], data)
    if unbound is not None:
        return _refused(name, unbound)
    tail = f"; final answer {claimed_answer}" if claimed_answer is not None else ""
    return confirm(name, f"all {len(pairs)} steps verified{tail}", data)


def verify_numeric(spec: Dict[str, Any]) -> VerifierResult:
    """Evaluate an arithmetic/numeric expression and check a claimed value — the engine as the
    verifier behind any solver (the solver proposes a number, the engine disposes). Exact via sympy,
    compared to the claim within rel_tol (default 1e-6 to accept display rounding, clamped <= 1e-2).
    Spec: {"numeric_expr": "sqrt(2) + 1", "claimed_value": 2.414214, "rel_tol": 1e-6}."""
    name = "mathematics.numeric"
    if not _ensure_sympy():
        return na(name, "requires the optional math extra (sympy)")
    expr = spec.get("numeric_expr")
    claimed = spec.get("claimed_value")
    if expr is None or claimed is None:
        return na(name)
    # clamp_tol: default 1e-6 and a caller may only TIGHTEN below it, never loosen — the earlier
    # min(..., 1e-2) let a caller widen the match window to 1e-2 (the FP-widening hole clamp_tol closes).
    rel_tol = clamp_tol(spec, "rel_tol", 1e-6)
    try:
        val = _parse(str(expr), spec.get("variables") or [])
        fv = float(val.evalf() if hasattr(val, "evalf") else val)
        cv = float(claimed)
    except UnboundRefused as e:
        return _refused(name, e)
    except _PARSE_ERRORS as e:
        return error(name, f"could not evaluate {expr!r}: {type(e).__name__}")
    except (TypeError, ValueError):
        return mismatch(name, f"{expr} is not a pure number (has free symbols?)", {"expr": str(expr)})
    if not _math.isfinite(fv):      # past a float, or infinite: no window around it can mean anything
        if _math.isfinite(cv):      # and no finite claim equals it, which does prove this one false
            return mismatch(name, f"{expr} is not finite as a float, so no finite claim equals it", {"expr": str(expr)})
        return error(name, f"{expr} is not finite as a float, so it cannot be compared with {cv}")
    if not _math.isfinite(cv):      # before any window: at the top of the float range a window's own edge is infinite
        return mismatch(name, f"{expr} is finite, and the claim {cv} is not", {"expr": str(expr)})
    diff = abs(fv - cv)
    threshold = rel_tol * max(1.0, abs(fv))
    strict_threshold = threshold   # the exact-match window, before any stated-precision widening below
    data = {"expr": str(expr), "computed": fv, "claimed": cv, "rel_tol": rel_tol, "abs_diff": diff}
    # STATED PRECISION (2026-10-07), as physical_constants keeps it: the literal as the person wrote it
    # ("1.41421") earns half a unit in its last stated place — two or more significant figures only, so a
    # one-figure "1" never passes as sqrt(2). Only the claim's own literal can widen the window; a structured
    # caller that sends no literal keeps the strict default unchanged (clamp_tol still only tightens).
    stated_used = False
    lit = spec.get("claimed_literal")
    if lit is not None:
        # THE ONE RULE (2026-10-08, H6): the stated window replaces the flat default; a hedge doubles it; a
        # one-figure claim is exact without a hedge (window_for).
        threshold, info = window_for(spec, "claimed_literal", threshold, 1.0, fv, claimed=cv)
        data.update(info)
        data["stated_tolerance"] = threshold
        stated_used = not info.get("literal_not_the_claim")
    # the band: the claim must lie in [computed − threshold, computed + threshold]
    bd = band(name, fv, cv, threshold, "value", data, fmt="{:.10g}")
    data = bd.data
    if bd.status == "ERROR":
        return bd
    if bd.passed:
        # EXPLAIN WHY IT IS WHAT IT IS (2026-10-09): a certification must say whether the claim is EXACT or only
        # correct to the precision stated. A bare "holds" on "sqrt(150) is 12" reads as an equality; it is not
        # (sqrt(150) = 12.2474). So when the claim holds only through the stated-precision window, the verdict names
        # it an APPROXIMATION and gives the exact value, so no reader mistakes "to 2 s.f." for "equals".
        exact = diff <= strict_threshold
        data["exact"] = bool(exact)
        if stated_used and not exact:
            sig = data.get("stated_sigfigs")
            data["approximation"] = True
            return confirm(name, f"{expr} = {fv:.10g}, and your '{lit}' is correct to the {sig} significant "
                                 f"figure(s) you wrote — but it is an APPROXIMATION, not exact: the exact value is "
                                 f"{fv:.10g}, not {cv}.", data)
        if stated_used:
            return confirm(name, f"{expr} = {fv:.10g} — the claim {cv} is exact (to the "
                                 f"{data.get('stated_sigfigs')} significant figure(s) stated).", data)
        if not exact:
            data["approximation"] = True
            return confirm(name, f"{expr} = {fv:.10g}, which the claim {cv} matches within {rel_tol:.0e} "
                                 f"(display rounding; the exact value is {fv:.10g}).", data)
        return confirm(name, f"{expr} = {fv:.10g} — the claim {cv} is exact.", data)
    return mismatch(name, f"{expr} = {fv:.10g}, claimed {cv} — off by {diff:.4g}; {bd.detail}", data)


# The claims a number-theory spec can hold, each a value and its claimed answer. A spec holds one.
_NUMBER_CLAIMS = (("gcd", "claimed_gcd"), ("lcm", "claimed_lcm"), ("is_prime", "claimed_prime"),
                  ("factorial", "claimed_factorial"), ("binomial", "claimed_binomial"), ("modulo", "claimed_modulo"))
_MALFORMED_NUMBER = "malformed number-theory input"


def _claims_held(spec: Dict[str, Any]) -> list:
    """The claims a spec states: a value and its claimed answer, both there. A key alone claims nothing."""
    return [claim for claim in _NUMBER_CLAIMS if all(key in spec for key in claim)]


def _more_than_one_claim(name: str, held: list) -> VerifierResult:
    return error(name, f"{_MALFORMED_NUMBER}: a spec holds one claim, and this one holds {' and '.join(key for key, _ in held)}")


# _exact_integer and _claimed_integer, the one way a number-theory value is read, live in verifiers/_integer.py
# (THE RULE, run 2026-11-11-exact-integers), imported above unchanged: called with no field, as here, each refusal
# reads exactly as it read when they were defined in this module.


def _exact_integers(value, count: int = None) -> list:
    """A list of integers, of exactly count where the claim reads a pair. Iterating a text would read it digit by digit, a
    dict by its keys, and indexing a longer list would drop the rest, so none of them reaches _exact_integer."""
    if not isinstance(value, list) or count not in (None, len(value)):
        raise TypeError(f"expected a list{f' of exactly {count}' if count else ''}, got {_brief(value)}")
    return [_exact_integer(item) for item in value]


def verify_number_theory(spec: Dict[str, Any]) -> VerifierResult:
    """Number-theory claims — gcd, lcm, primality, factorial, binomial, modulo — checked exactly.
    Spec (any one): {"gcd": [12, 18], "claimed_gcd": 6} · {"lcm": [4, 6], "claimed_lcm": 12} ·
    {"is_prime": 17, "claimed_prime": true} · {"factorial": 5, "claimed_factorial": 120} ·
    {"binomial": [5, 2], "claimed_binomial": 10} · {"modulo": [17, 5], "claimed_modulo": 2}.
    Every value reads as the exact integer it writes, and a spec holds one claim. A spec holding generators or ring is a
    polynomial claim: see polynomial_claim."""
    name = "mathematics.number_theory"
    if "generators" in spec or "ring" in spec:
        return polynomial_claim(spec)
    if not _ensure_sympy():
        return na(name, "requires the optional math extra (sympy)")
    held = _claims_held(spec)
    if len(held) > 1:
        return _more_than_one_claim(name, held)
    from sympy import igcd, ilcm, isprime, factorial as _fact, binomial as _binom
    try:
        if "gcd" in spec and "claimed_gcd" in spec:
            a = _exact_integers(spec["gcd"])
            actual, claimed, label = igcd(*a), _claimed_integer(spec["claimed_gcd"]), f"gcd{tuple(a)}"
        elif "lcm" in spec and "claimed_lcm" in spec:
            a = _exact_integers(spec["lcm"])
            actual, claimed, label = ilcm(*a), _claimed_integer(spec["claimed_lcm"]), f"lcm{tuple(a)}"
        elif "is_prime" in spec and "claimed_prime" in spec:
            n, claimed = _exact_integer(spec["is_prime"]), spec["claimed_prime"]
            if not isinstance(claimed, bool):
                raise TypeError(f"claimed_prime must be a real boolean, got {_brief(claimed)}")
            actual, label = bool(isprime(n)), f"isprime({n})"
        elif "factorial" in spec and "claimed_factorial" in spec:
            n = _exact_integer(spec["factorial"])
            actual, claimed, label = _operator.index(_fact(n)), _claimed_integer(spec["claimed_factorial"]), f"{n}!"
        elif "binomial" in spec and "claimed_binomial" in spec:
            n, k = _exact_integers(spec["binomial"], 2)
            actual, claimed, label = _operator.index(_binom(n, k)), _claimed_integer(spec["claimed_binomial"]), f"C({n},{k})"
        elif "modulo" in spec and "claimed_modulo" in spec:
            a, m = _exact_integers(spec["modulo"], 2)
            actual, claimed, label = a % m, _claimed_integer(spec["claimed_modulo"]), f"{a} mod {m}"
        else:
            return na(name)
    except (TypeError, ValueError, IndexError) as e:
        return error(name, f"{_MALFORMED_NUMBER}: {e}")
    data = {"claim": label, "actual": actual, "claimed": claimed}
    if actual == claimed:
        return confirm(name, f"{label} = {actual}", data)
    return mismatch(name, f"{label} = {actual}, claimed {claimed}", data)


_POLYNOMIAL_RINGS = ("ZZ", "QQ")


def _polynomial_form(node, names) -> bool:
    """THE LIST of a polynomial text, on its syntax tree: a named generator, a number, a sign on what is here, a sum and a
    product of what is here, a division by what holds no generator, and a power to a whole number as written. It is a list
    of what may stand, because Poly takes what is no polynomial and hands back one, and the value cannot say so afterwards.
    A call is gone by then: Tuple(1, 2) would read as the coefficients of x + 2, Eq(x, 1) as x - 1, a matrix by its entries, and
    N(sqrt(2)) as a nearby rational. A division that cancels is gone too, so x/x would read as 1 and take its pole with it."""
    if isinstance(node, _ast.BinOp):
        if isinstance(node.op, _ast.Pow):
            return type(getattr(node.right, "value", None)) is int and _polynomial_form(node.left, names)
        if type(node.op) not in _ARITHMETIC:
            return False
        return _polynomial_form(node.left, names) and _polynomial_form(node.right, () if isinstance(node.op, _ast.Div) else names)
    if isinstance(node, _ast.UnaryOp):
        return isinstance(node.op, (_ast.USub, _ast.UAdd)) and _polynomial_form(node.operand, names)
    if isinstance(node, _ast.Name):
        return node.id in names
    return isinstance(node, _ast.Constant) and type(node.value) in (int, float)


def _polynomial_in(text, names: list, ring: str):
    """A text as a polynomial of the claim's ring in the claim's generators, or None where it is not one. The list is read
    before the text is, so nothing off it ever runs, and a call that would outlast the window is refused at once. Every name
    is a generator by then, so no symbol reaches a coefficient domain, and a fraction in ZZ is what Poly itself refuses."""
    if not isinstance(text, str):
        return None
    source = _normalise_expression(text, True)
    if len(source) > _MAX_EXPR_CHARS:
        return None
    try:
        tree = _ast.parse(source, mode="eval")
        _bound_tree(tree)
        if not _polynomial_form(tree.body, names):
            return None
        return _sp.Poly(_parse(text, names, rational=True), *map(Symbol, names), domain=ring)
    except Exception:       # a text no read could finish is no polynomial, whatever refused it
        return None


def _polynomial_fold(word: str, polys: list):
    """The gcd or lcm of polynomials of one ring, by Poly's own two-argument function. sympy reaches an lcm by dividing by the
    gcd, so an lcm with a zero polynomial is answered here, and it is zero."""
    if word == "lcm":
        for poly in polys:
            if poly.is_zero:
                return poly
    return _functools.reduce(getattr(_sp.Poly, word), polys)


def _one_answer(one, other, ring: str) -> bool:
    """Whether two polynomials of one ring are the same answer: they differ by a unit, plus or minus one over ZZ and any
    nonzero rational over QQ. Zero is no unit's multiple of anything else, so zero equals only zero. No term order or
    generator order can move this, since both sides are read in the one order the claim stated."""
    if one.is_zero or other.is_zero:
        return one.is_zero and other.is_zero
    return one.monic() == other.monic() if ring == "QQ" else one == other or one == -other


def _all_generators(names: list) -> bool:
    """Whether every name is an identifier the parser reads as that symbol and as nothing else, each once. So pi, I, oo, a
    function's name and x + 1 name no generator, no claim can read a constant as an indeterminate, and no call runs here."""
    try:
        return (all(isinstance(n, str) and n.isidentifier() and _parse(n) == Symbol(n) for n in names)
                and len(set(names)) == len(names))
    except _PARSE_ERRORS:
        return False


def polynomial_claim(spec: Dict[str, Any]) -> VerifierResult:
    """A gcd or lcm of polynomials, read only in the ring and generators the claim states, so no answer rests on a generator
    order or a unit sympy picked. Spec: {"gcd": ["x**2 - 1", "x - 1"], "claimed_gcd": "x - 1", "generators": ["x"], "ring":
    "QQ"}, or lcm and claimed_lcm the same way, where ring is ZZ or QQ. Named so tools/unreached.py does not count it: no
    benchmark case reaches this mode. Everything it returns is plain data, so a cell sends no sympy value to the front."""
    name = "mathematics.polynomial"

    def refused(reason):
        return _refused(name, reason, "polynomial claim")

    if not _ensure_sympy():
        return refused("requires the optional math extra (sympy)")
    held = _claims_held(spec)
    if len(held) > 1:
        return _more_than_one_claim(name, held)
    word = held[0][0] if held else None
    if word not in ("gcd", "lcm"):
        return refused("state gcd or lcm as a list of two or more polynomial texts, with claimed_gcd or claimed_lcm as a text")
    texts, claimed = spec[word], spec[f"claimed_{word}"]
    if not isinstance(texts, list) or len(texts) < 2:
        return refused(f"state {word} as a list of two or more polynomial texts")
    names, ring = spec.get("generators"), spec.get("ring")
    if not isinstance(names, list) or not names or not _all_generators(names):
        return refused("state generators as a list of names, each once, each read as a symbol and nothing else")
    if not isinstance(ring, str) or ring not in _POLYNOMIAL_RINGS:
        return refused(f"state ring as 'ZZ' or 'QQ', the two this mode reads{f', not {_brief(ring)}' if ring is not None else ''}")
    over = f"{_brief(', '.join(names))} over {ring}"
    polys = []
    for text in (*texts, claimed):
        poly = _polynomial_in(text, names, ring)
        if poly is None:
            return refused(f"{_brief(text)} is no polynomial in {over}. Write it with coefficients in the ring by sums, products, "
                           f"powers to a whole number and division by a number, and name every symbol in generators")
        polys.append(poly)
    actual = _polynomial_fold(word, polys[:-1])
    label = f"{word} in {ring}[{', '.join(names)}] of {'; '.join(texts)}"
    data = {"claim": label, "actual": str(actual.as_expr()), "claimed": claimed, "ring": ring, "generators": list(names)}
    if _one_answer(actual, polys[-1], ring):
        return confirm(name, f"{label} = {data['actual']}, which the claim {claimed} is up to a unit of {ring}", data)
    return mismatch(name, f"{label} = {data['actual']}, and the claim {claimed} differs from it by no unit of {ring}", data)


def verify_system(spec: Dict[str, Any]) -> VerifierResult:
    """A claimed solution to a SYSTEM of equations — verified by substitution (each equation must
    hold), so no solver ambiguity and no false positive. Spec: {"equations": ["x + y = 3",
    "x - y = 1"], "variables": ["x", "y"], "claimed_solution": {"x": 2, "y": 1}}."""
    name = "mathematics.system"
    if not _ensure_sympy():
        return na(name, "requires the optional math extra (sympy)")
    eqs = spec.get("equations")
    claimed = spec.get("claimed_solution")
    var_names = spec.get("variables") or (list(claimed.keys()) if isinstance(claimed, dict) else [])
    if not eqs or not isinstance(claimed, dict):
        return na(name)
    try:
        subs = {Symbol(k): _parse(str(v), var_names, binders=1) for k, v in claimed.items()}
    except UnboundRefused as e:
        return _refused(name, e)
    except _PARSE_ERRORS as e:
        return error(name, f"unparseable claimed value: {type(e).__name__}")
    failures = []
    unbound = None      # read last: a system is false on any false equation, and a refusal must not hide one
    for eq in eqs:
        if "=" not in str(eq):
            return error(name, f"equation has no '=': {eq!r}")
        lhs, rhs = str(eq).split("=", 1)
        try:
            if simplify((_parse(lhs, var_names, binders=1) - _parse(rhs, var_names, binders=1)).subs(subs)) != 0:
                failures.append(str(eq).strip())
        except UnboundRefused as e:
            unbound = e
        except _PARSE_ERRORS:
            return error(name, f"unparseable equation: {eq!r}")
    data = {"equations": [str(e).strip() for e in eqs], "claimed_solution": claimed}
    if failures:
        return mismatch(name, "solution fails: " + "; ".join(failures)[:200], data)
    if unbound is not None:
        return _refused(name, unbound)
    return confirm(name, f"claimed solution satisfies all {len(eqs)} equations", data)


_RULES = [
    (lambda mv: ("calc_steps" in mv or "solution_text" in mv), verify_calc_chain),
    (lambda mv: ("numeric_expr" in mv and "claimed_value" in mv), verify_numeric),
    (lambda mv: any(k in mv for k in ("gcd", "lcm", "is_prime", "factorial", "binomial", "modulo")), verify_number_theory),
    (lambda mv: ("equations" in mv and "claimed_solution" in mv), verify_system),
    (lambda mv: ("expr_a" in mv and "expr_b" in mv), verify_equality),
    (lambda mv: ("set_a" in mv and "set_b" in mv and "claimed_equal" in mv), verify_set_algebra),
    (lambda mv: ("function" in mv and "claimed_derivative" in mv), verify_derivative),
    (lambda mv: ("integrand" in mv and "claimed_antiderivative" in mv), verify_integral),
    (lambda mv: ("function" in mv and "point" in mv and "claimed_limit" in mv), verify_limit),
    (lambda mv: ("equation" in mv and "claimed_solutions" in mv), verify_solve),
    (lambda mv: ("lhs" in mv and "rhs" in mv and "op" in mv), verify_inequality),
]


GOLDEN_PACKET_KEY = "MATH_VERIFY"  # dispatch()-routed, so the auto-detector needs this named
GOLDEN_EXAMPLE = {"function": "x**2", "variable": "x", "claimed_derivative": "2*x"}  # d/dx x^2 = 2x


def run(packet: Dict[str, Any]) -> List[VerifierResult]:
    results = dispatch(packet, 'MATH_VERIFY', _RULES, domain='mathematics', none_reason='no MATH_VERIFY artifacts present')
    if any(r.status == "NOT_APPLICABLE" and r.detail.startswith(_REFUSAL) for r in results):
        # As in physics: a step's status drops NOT_APPLICABLE, so a passing check beside a refused text would read
        # the whole packet as HOLDS, and it goes. A MISMATCH or an error stands, so a refused text hides no false claim.
        return [r for r in results if r.status != "CONFIRMED"]
    return results
