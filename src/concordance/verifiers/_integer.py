"""THE RULE: the one way a verifier reads an integer from a spec (run 2026-11-11-exact-integers).

int() alone drops a fraction (int(20.9) is 20) and takes a bool for 1, and round(), math.floor, math.ceil and
math.trunc drop a fraction too, so a claim of 20.9 permutations read as 20 and held. A refused value is never
dropped and never read as the integer it is not. There are three readings, and each fixed site names the one it uses:

  * an INPUT the check computes from reads by _exact_integer: an int, a finite float with no fraction, or a text
    int() reads whole. Anything else (a fraction, a bool, other text, null) is malformed: the reader raises, and the
    site reads the step ERROR, so the derivation reads SYSTEM_ERROR.
  * a CLAIMED RESULT reads by _claimed_integer: a number with a fraction, or a text whose float has one, stands as
    written, so the check compares it and reads it as a wrong claim (the step MISMATCH, the derivation BROKEN); a
    whole number reads as its integer; anything else is malformed, as an input is.
  * where the check's own question is whether a value is VALID, as atomic.quantum_numbers asks of a set, the value
    reads by _valid_integer: a number with a fraction is no valid value (None), and the check compares that with the
    claim; a whole number reads as its integer; anything else is malformed.

Given a field, a refusal names it and says the value is not a whole number, in words that fit any domain:
"perm_n is not a whole number: 5.5". Without one (mathematics.number_theory, which wraps every refusal in its own
"malformed number-theory input" sentence), the words are the ones mathematics has always read. The two readers moved
here from mathematics.py unchanged in what they accept and refuse; tools/integer_probe.py's walk exempts the
conversion inside these two functions, by name, and nothing else in this module.
"""
from __future__ import annotations

import math as _math
from typing import Any, Optional


def _refusal(value: Any, field: Optional[str]) -> str:
    shown = repr(value)
    if len(shown) > 60:
        shown = shown[:57] + "..."
    return f"{value!r} is not an integer" if field is None else f"{field} is not a whole number: {shown}"


def _exact_integer(value, field: Optional[str] = None) -> int:
    """The one way an integer input is read: an int, a finite float with no fraction, or a text of an integer.
    int() alone drops a fraction and takes a bool for 1, so anything else stops here. Each refusal is a TypeError or
    a ValueError, as int()'s own refusal of a text was."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(_refusal(value, field))
    if isinstance(value, float) and not (_math.isfinite(value) and value.is_integer()):
        raise ValueError(_refusal(value, field))
    try:
        return int(value)
    except ValueError:
        if field is None:
            raise
        raise ValueError(_refusal(value, field)) from None


def _claimed_integer(value, field: Optional[str] = None, *, as_number: bool = False):
    """A claimed value as it is compared. One with a fraction stands as written: it is a number the answer is not, so it
    reads BROKEN, where an input with one reads malformed. A text whose value is an integer never has a float with a
    fraction, so this cannot read a true claim false. Everything else is read as an input is. A check that compares
    the claim as a number (a band, arithmetic) asks as_number, and a text with a fraction then stands as its float."""
    try:
        number = float(value) if isinstance(value, str) else value
    except ValueError:
        if field is None:
            raise
        raise ValueError(_refusal(value, field)) from None
    if isinstance(number, float) and _math.isfinite(number) and not number.is_integer():
        return number if as_number else value
    return _exact_integer(value, field)


def _valid_integer(value, field: Optional[str] = None) -> Optional[int]:
    """A value whose validity is the check's own question: None when it is a number with a fraction (no valid value),
    else read as an input is, so a whole number reads as its integer and anything else is malformed."""
    if isinstance(value, float) and _math.isfinite(value) and not value.is_integer():
        return None
    return _exact_integer(value, field)
