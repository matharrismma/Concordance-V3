"""Stand-ins for what a read can do inside a cell. No verifier reaches any of them: a test puts one under a
made-up math mode in its own process, or hands it straight to a pool, and every one takes a read's single argument.

hold() is the neutral stand-in for a read that holds Python's global lock: one plain integer power. A power of this
size is a single bytecode that runs in C from start to end without letting go of the lock, so no other thread runs
and a window kept by another thread cannot fire. It is bounded twice, by the kill of whoever runs it and by its own
size: left alone it ends by itself in tens of seconds, so nothing outlives a test for long.
"""
from __future__ import annotations

import os

from concordance.verifiers.base import VerifierResult, confirm, error

EXPONENT = 3 * 10 ** 7


def hold(_params=None) -> VerifierResult:
    held = 3 ** EXPONENT
    return error("standin.hold", f"the power ended by itself ({held.bit_length()} bits); nothing killed this read")


def quick(_params=None) -> VerifierResult:
    return confirm("standin.quick", "answered")


def pid(_params=None) -> VerifierResult:
    return confirm("standin.pid", "answered", {"pid": os.getpid()})


def die(_params=None) -> VerifierResult:
    os._exit(3)


def die_at_start(*_args) -> None:
    os._exit(3)


def raises(_params=None) -> VerifierResult:
    raise ValueError("a stand-in's own words")


class _Unprintable:
    def __str__(self) -> str:
        raise RuntimeError("no string for this")


def unprintable(_params=None) -> VerifierResult:
    return confirm("standin.unprintable", "answered", {"value": _Unprintable()})


def sympy_values(_params=None) -> VerifierResult:
    import sympy
    return confirm("standin.sympy", "answered", {
        "actual": sympy.Rational(1, 3), "whole": sympy.Integer(5), "flag": sympy.true,
        "nested": [{"root": sympy.sqrt(2)}, (sympy.Symbol("x") + 1, "kept")], "plain": 2.5,
        "members": {sympy.Integer(5)}})


def sympy_key(_params=None) -> VerifierResult:
    import sympy
    return confirm("standin.sympy_key", "answered", {"by_symbol": {sympy.Symbol("x"): 1}})


def numpy_values(_params=None) -> VerifierResult:
    import numpy
    return confirm("standin.numpy", "answered", {
        "inside": numpy.bool_(True), "p": numpy.float64(0.25), "count": numpy.int64(3),
        "row": numpy.array([1.0, 2.0]), "bands": [{"inside": numpy.bool_(False), "used": numpy.float64(1.5)}]})


def stdlib_values(_params=None) -> VerifierResult:
    from decimal import Decimal
    from fractions import Fraction
    return confirm("standin.stdlib", "answered", {
        "third": Fraction(1, 3), "cost": Decimal("1.10"), "wave": 1 + 2j, "tags": {"a"}, "fixed": frozenset({1}),
        "pair": (1, "two")})


def leak(_params=None) -> VerifierResult:
    """Take the cell's filter away, so a class off the list reaches the pipe: what the front's reader is there to
    refuse. The cell is the one that goes for it."""
    import collections
    from concordance import cells
    cells._plain = lambda value: value
    return confirm("standin.leak", "answered", {"value": collections.deque([1])})


def limits(_params=None) -> VerifierResult:
    """What this cell's limits are, read from inside it. Where the platform has no `resource` module, None."""
    try:
        import resource
    except ImportError:
        return confirm("standin.limits", "answered", {"as": None, "data": None})
    return confirm("standin.limits", "answered", {"as": resource.getrlimit(resource.RLIMIT_AS),
                                                  "data": resource.getrlimit(resource.RLIMIT_DATA)})


def oom_score(_params=None) -> VerifierResult:
    with open("/proc/self/oom_score_adj", encoding="ascii") as fh:
        return confirm("standin.oom", "answered", {"oom_score_adj": fh.read().strip()})

