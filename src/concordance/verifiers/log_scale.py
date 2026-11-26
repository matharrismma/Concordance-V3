"""The logarithmic scale law, written once: level = k * log_b(value / reference).

Decibels (k = 10 or 20, base 10), return loss (k = -20), exposure value and password strength in bits (base 2),
half-lives elapsed (k = -1, base 2), a radiometric age (k = -T/ln 2, base e), the Nernst and Goldman potentials
(k = RT/zF), the Weber-Fechner law (k), the Clausius-Clapeyron step (k = R/L), Boltzmann entropy (k = k_B) and the
Magnus dew-point term (base e, reference 100 %) are one law with different constants. A verifier that uses it supplies
its own k, base and reference, calls `level`, and records `law(...)` in its data under `shared_law`, so the trail and the sealed record
name the law and the constants that grounded the check.

The arithmetic is exactly what each verifier computed before it was moved here: base 10 is math.log10, base 2 is
math.log2, base e is math.log; the ratio is value / reference only when a reference is given, so an exact integer
reaches math.log2 or math.log whole; and k multiplies the logarithm last.

Not a verifier (no run(), not registered): a shared library, like scale_base.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Optional, Union

FORM = "log_scale"
LAW = "level = k * log_b(value / reference)"
E = "e"
_LOG = {10: math.log10, 2: math.log2, E: math.log}

Base = Union[int, str]


def level(value: Any, reference: Optional[Any] = None, *, k: Any = 1.0, base: Base = 10) -> float:
    """k * log_base(value / reference). With no reference the value is passed to the logarithm whole."""
    log = _LOG[base]
    return k * log(value if reference is None else value / reference)


def law(*, k: Any, base: Base, reference: Any = None) -> Dict[str, Any]:
    """What a verifier records beside its value: the law, its base, its constant k and its reference."""
    return {"form": FORM, "law": LAW, "base": base, "k": k, "reference": 1 if reference is None else reference}


__all__ = ["FORM", "LAW", "E", "level", "law"]
