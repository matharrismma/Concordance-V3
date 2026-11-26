"""The logarithmic scale law, written once: level = k * log_b(value / reference), and read backwards,
value = reference * b^(level / k).

Forward, `level` reads a level off a quantity. Decibels (k = 10 or 20, base 10), return loss (k = -20), exposure value
and password strength in bits (base 2), half-lives elapsed (k = -1, base 2), a radiometric age (k = -T/ln 2, base e),
the Nernst and Goldman potentials (k = RT/zF), the Weber-Fechner law (k), the Clausius-Clapeyron step (k = R/L),
Boltzmann entropy (k = k_B) and the Magnus dew-point term (base e, reference 100 %) are one law with different constants.

Summed, `entropy` is the p-weighted sum of the levels of the p themselves, k * sum(p * log_b(p)): with k = -1 each
term is the information in an outcome of probability p, and the sum is its expectation. Shannon entropy (base 2), the
binary entropy inside a binary symmetric channel's capacity (base 2), the Shannon diversity index (base e) and the von
Neumann entropy of a density matrix's eigenvalues (base 2) are that one sum.

Backwards, `inverse` turns a level back into the quantity it stands for. A distance from its distance modulus (k = 5,
base 10), an amplitude ratio from a Richter difference (base 10), an Elo odds ratio from a rating difference (k = 400,
base 10), a note's frequency from its semitones above A4 (k = 12, base 2, reference 440 Hz), the addresses in a subnet
from its host bits (base 2), what remains after a time in half-lives (k = -T, base 2) or in e-folds (base e: radioactive
decay, Beer-Lambert absorption, an RC charge, logistic growth), the Boltzmann factor (k = k_B T) and the Magnus
saturation vapour pressure (reference 6.112 hPa) are the same law read the other way.

A verifier that uses it supplies its own k, base and reference, calls `level` or `inverse`, and records `law(...)` in its
data under `shared_law`, so the trail and the sealed record name the law, its direction and the constants that grounded
the check. Both directions are one form: a seal that names `log_scale` names this law, and its `law` text says which way.

The arithmetic is exactly what each verifier computed before it was moved here. Forward: base 10 is math.log10, base 2
is math.log2, base e is math.log; the ratio is value / reference only when a reference is given, so an exact integer
reaches math.log2 or math.log whole; and k multiplies the logarithm last. Backwards: base e is math.exp (never math.e
** x), bases 10 and 2 are the power operator; the level is divided by k only when k is not 1, so an exact integer
power stays an exact integer (2 ** 24 is an int; the caller bounds such an exponent, as a CIDR prefix of 0-32 does);
and the reference multiplies last. Summed: each term is p * (k * log_b(p)), the p at or below `floor` are left out
(0 * log 0 is 0), and the terms are added by Python's sum() from 0.0, the compensated sum every supported Python (3.12
and later) uses; so a sum that is all zeros, one certain outcome, is 0.0 and never -0.0.

Not a verifier (no run(), not registered): a shared library, like scale_base.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Optional, Union

FORM = "log_scale"
LAW = "level = k * log_b(value / reference)"
LAW_INVERSE = "value = reference * b^(level / k)"
LAW_ENTROPY = "level = k * sum(p * log_b(p))"
E = "e"
_LOG = {10: math.log10, 2: math.log2, E: math.log}
_POW = {10: lambda x: 10 ** x, 2: lambda x: 2 ** x, E: math.exp}

Base = Union[int, str]


def level(value: Any, reference: Optional[Any] = None, *, k: Any = 1.0, base: Base = 10) -> float:
    """k * log_base(value / reference). With no reference the value is passed to the logarithm whole."""
    log = _LOG[base]
    return k * log(value if reference is None else value / reference)


def inverse(level: Any, reference: Optional[Any] = None, *, k: Any = 1.0, base: Base = 10) -> Any:
    """reference * base ** (level / k): the quantity a level stands for. With k = 1 the level is the exponent whole,
    and with no reference the power is the value."""
    power = _POW[base]
    v = power(level if k == 1 else level / k)
    return v if reference is None else reference * v


def entropy(ps: Any, *, k: Any = -1.0, base: Base = 2, floor: Any = 0.0) -> float:
    """sum(p * (k * log_base(p))) over the p above `floor`: the p-weighted sum of the law's levels of the p."""
    log = _LOG[base]
    return sum((p * (k * log(p)) for p in ps if p > floor), 0.0)


def law(*, k: Any, base: Base, reference: Any = None, inverse: bool = False,
        entropy: bool = False) -> Dict[str, Any]:
    """What a verifier records beside its value: the law and its direction, its base, its constant k and its reference."""
    return {"form": FORM, "law": LAW_ENTROPY if entropy else LAW_INVERSE if inverse else LAW, "base": base, "k": k,
            "reference": 1 if reference is None else reference}


__all__ = ["FORM", "LAW", "LAW_INVERSE", "LAW_ENTROPY", "E", "level", "inverse", "entropy", "law"]
