"""Independently checkable certificates: a proof a separate, minimal checker re-confirms without trusting the verifier.

A verifier CONFIRMS a verdict; a certificate lets anyone re-confirm it without running the verifier again, the pattern
bbchallenge sealed BB(5) with (every machine's verdict carried a proof a small checker re-verified). Producing the proof
may be hard (search, factoring); checking it is cheap arithmetic. The trust moves from "the verifier said so" to "here
is a proof anyone can check". Ported from concordance-2 (d3c4a0f, cf07081, b369b4f) with its checker's holes closed.

Three kinds, each attached by its own check and only when the check can stand behind it:
  * primality (number_theory.primality, 2 <= n <= 10**12): a composite n carries one factor d (1 < d < n, n % d == 0);
    a prime n carries a Pratt/Lucas proof, a base a and the prime factors of n - 1, each itself certified prime
    (Lucas 1876; Pratt 1975: primality is in NP through exactly this proof). The checker also requires that the listed
    primes generate n - 1, none omitted, which is what makes Lucas a proof.
  * polynomial_root (polynomial.root, when the value is 0): integer coefficients and a rational root; one exact
    Horner evaluation.
  * linear_system (linear_algebra.solve_check, when x solves A x = b exactly in rationals): one exact product A x.

Every number is read exactly. In a certificate an integer is a JSON integer and a rational is the text "p" or "p/q";
nothing else reads, so 17.9 is never 17, -2.5 never -2 and true never 1 (concordance-2's checker read all three).
A certificate is also BOUND to the check it rides on: `binds(cert, spec)` reads the checked packet the way the
verifier read it and requires the certificate to state those same inputs, so a valid proof that 17 is prime cannot
stand in for a claim about 19. The checker refuses what is too large to check cheaply (`MAX_*` below) instead of
working on it. docs/verify_receipt.py carries its own copy of the checker and the binding, importing nothing from
here, so a stranger runs it with no part of this engine; tests/test_certificate.py holds the two to the same answers.

Not a verifier (no run(), not registered): a shared library, like log_scale.
"""
from __future__ import annotations

import math
import re
from fractions import Fraction
from typing import Any, Dict, List, Optional, Tuple

from ._integer import _exact_integer  # THE RULE (verifiers/_integer.py): the one integer reader

SCHEMA = 1
PRODUCE_MAX_N = 10 ** 12          # the largest n a primality check attaches a certificate for (trial division to 10**6)
MAX_N_BITS = 64                   # the checker reads primality certificates for n < 2**64 and no larger
MAX_DEGREE = 64                   # a polynomial certificate holds at most 65 coefficients
MAX_DIM = 32                      # a linear-system certificate is at most 32 x 32
MAX_DIGITS = 600                  # either side of a rational holds at most 600 digits
MAX_INT_BITS = 2000               # an integer holds at most 2000 bits (about 600 digits)
_RATIONAL = re.compile(r"-?[0-9]{1,%d}(/[0-9]{1,%d})?" % (MAX_DIGITS, MAX_DIGITS))


# ── exact reads ─────────────────────────────────────────────────────────────────────────────────────────────────
def _int(v: Any) -> int:
    """An integer inside a certificate: a JSON integer and nothing else (no bool, no float, no text)."""
    if type(v) is not int or v.bit_length() > MAX_INT_BITS:
        raise ValueError(f"not an integer a certificate holds: {v!r}"[:120])
    return v


def _rational_text(v: Any) -> Fraction:
    """A rational inside a certificate: the text "p" or "p/q" with q > 0, and nothing else."""
    if not isinstance(v, str) or not _RATIONAL.fullmatch(v):
        raise ValueError(f"not a rational a certificate holds: {v!r}"[:120])
    try:
        return Fraction(v)
    except ZeroDivisionError:
        raise ValueError("a zero denominator") from None


def _text(r: Fraction) -> str:
    return str(r.numerator) if r.denominator == 1 else f"{r.numerator}/{r.denominator}"


def _input_integer(v: Any) -> int:
    """An integer the way a verifier reads its input: THE RULE's reader itself (an int, a finite float with no
    fraction, or a text of an integer; never a bool)."""
    return _exact_integer(v)


def _input_root(v: Any) -> Fraction:
    """A claimed root the way polynomial.root reads it: a text as Fraction reads it, an int exactly, a float as the
    nearest fraction with a denominator up to 10**9; never a bool."""
    if isinstance(v, str):
        return Fraction(v)
    if isinstance(v, bool):
        raise ValueError("a boolean is not a number")
    return Fraction(v).limit_denominator(10 ** 9) if isinstance(v, float) else Fraction(v)


def _input_exact(v: Any) -> Fraction:
    """An entry of a matrix or vector read exactly: an int, a finite float's exact binary value, or a rational
    text; never a bool. A linear-system certificate attaches only when these exact values solve the system."""
    if isinstance(v, bool):
        raise ValueError("a boolean is not a number")
    if isinstance(v, int):
        return Fraction(v)
    if isinstance(v, float):
        if not math.isfinite(v):
            raise ValueError("not finite")
        return Fraction(v)
    if isinstance(v, str):
        return _rational_text(v.strip())
    raise ValueError(f"not a number: {v!r}"[:120])


# ── producers (may be slow; never what anyone has to trust) ─────────────────────────────────────────────────────
def _smallest_factor(n: int) -> int:
    if n % 2 == 0:
        return 2
    i = 3
    while i * i <= n:
        if n % i == 0:
            return i
        i += 2
    return n


def _distinct_prime_factors(m: int) -> List[int]:
    out: List[int] = []
    while m > 1:
        f = _smallest_factor(m)
        out.append(f)
        while m % f == 0:
            m //= f
    return out


def _lucas_base(n: int, qs: List[int]) -> int:
    for a in range(2, n):
        if pow(a, n - 1, n) == 1 and all(pow(a, (n - 1) // q, n) != 1 for q in qs):
            return a
    raise ValueError(f"no Lucas base for {n}")


def primality(n: int) -> Dict[str, Any]:
    """The certificate of n's primality verdict, 2 <= n <= PRODUCE_MAX_N."""
    if type(n) is not int or not 2 <= n <= PRODUCE_MAX_N:
        raise ValueError("a primality certificate is made for 2 <= n <= 10**12")
    d = _smallest_factor(n)
    if d != n:
        return {"kind": "primality", "claim": {"n": n, "verdict": "composite"}, "proof": {"factor": d}, "schema": SCHEMA}
    if n == 2:
        return {"kind": "primality", "claim": {"n": 2, "verdict": "prime"}, "proof": {"base": 1, "factors": []},
                "schema": SCHEMA}
    qs = _distinct_prime_factors(n - 1)
    return {"kind": "primality", "claim": {"n": n, "verdict": "prime"},
            "proof": {"base": _lucas_base(n, qs), "factors": [[q, primality(q)] for q in qs]}, "schema": SCHEMA}


def polynomial_root(coeffs: List[int], root: Fraction) -> Dict[str, Any]:
    """The certificate that `root` is a root of the integer polynomial `coeffs` (highest degree first)."""
    cf = [_int(c) for c in coeffs]
    r = Fraction(root)
    if not 2 <= len(cf) <= MAX_DEGREE + 1 or _horner(cf, r) != 0:
        raise ValueError("not a root, or outside what a certificate holds")
    cert = {"kind": "polynomial_root", "claim": {"coeffs": cf, "verdict": "root"}, "proof": {"root": _text(r)},
            "schema": SCHEMA}
    ok, why = check(cert)
    if not ok:
        raise ValueError(why)
    return cert


def linear_system(A: List[List[Any]], b: List[Any], x: List[Any]) -> Dict[str, Any]:
    """The certificate that x solves A x = b exactly, every entry read exactly (an int, a float's exact binary
    value, or a rational text)."""
    AF = [[_input_exact(v) for v in row] for row in A]
    bF = [_input_exact(v) for v in b]
    xF = [_input_exact(v) for v in x]
    cert = {"kind": "linear_system",
            "claim": {"A": [[_text(v) for v in row] for row in AF], "b": [_text(v) for v in bF], "verdict": "solves"},
            "proof": {"x": [_text(v) for v in xF]}, "schema": SCHEMA}
    ok, why = check(cert)
    if not ok:
        raise ValueError(why)
    return cert


# ── the checker: pure arithmetic on the certificate alone ───────────────────────────────────────────────────────
def _horner(coeffs: List[int], x: Fraction) -> Fraction:
    acc = Fraction(0)
    for c in coeffs:
        acc = acc * x + c
    return acc


def _check_primality(c: Dict[str, Any], depth: int = 0) -> Tuple[bool, str]:
    if depth > MAX_N_BITS:
        return False, "the proof nests deeper than its n allows"
    try:
        claim, proof = c["claim"], c["proof"]
        n = _int(claim["n"])
        verdict = claim["verdict"]
    except (KeyError, TypeError, ValueError) as e:
        return False, f"malformed claim: {e}"[:160]
    if n < 2:
        return False, "n < 2 is neither prime nor composite"
    if n.bit_length() > MAX_N_BITS:
        return False, f"n has {n.bit_length()} bits; this checker reads primality certificates up to {MAX_N_BITS}"
    if verdict == "composite":
        try:
            d = _int(proof["factor"])
        except (KeyError, TypeError, ValueError) as e:
            return False, f"malformed factor: {e}"[:160]
        if not 1 < d < n or n % d:
            return False, f"{d} is not a factor of {n} strictly between 1 and {n}"
        return True, f"{n} = {d} x {n // d}, composite"
    if verdict != "prime":
        return False, f"unknown verdict {verdict!r}"[:120]
    if n == 2:
        return True, "2 is prime"
    try:
        a = _int(proof["base"])
        factors = proof["factors"]
        if not isinstance(factors, list) or len(factors) > MAX_N_BITS:
            raise ValueError("factors must be a list of at most 64 entries")
        qs = []
        for item in factors:
            if not isinstance(item, list) or len(item) != 2 or not isinstance(item[1], dict):
                raise ValueError("a factor entry is [q, its own primality certificate]")
            q, sub = _int(item[0]), item[1]
            if not 1 < q < n:
                return False, f"listed factor {q} is not between 1 and {n}"
            ok, why = _check_primality(sub, depth + 1)
            if not ok:
                return False, f"factor {q} is not certified prime: {why}"[:200]
            if sub.get("kind") != "primality" or sub["claim"]["n"] != q or sub["claim"]["verdict"] != "prime":
                return False, f"the entry for {q} does not certify {q} prime"
            qs.append(q)
    except (KeyError, TypeError, ValueError) as e:
        return False, f"malformed proof: {e}"[:160]
    m = n - 1
    for q in qs:
        if m % q:
            return False, f"{q} does not divide what is left of n - 1"
        while m % q == 0:
            m //= q
    if m != 1:
        return False, "the listed primes do not generate n - 1: a prime factor is missing"
    if not 1 < a < n or pow(a, n - 1, n) != 1:
        return False, "the base does not satisfy a^(n-1) = 1 (mod n)"
    for q in qs:
        if pow(a, (n - 1) // q, n) == 1:
            return False, f"a^((n-1)/{q}) = 1 (mod n): the base's order is not n - 1"
    return True, f"{n} is prime by Lucas (base {a}; n - 1 has prime factors {sorted(qs)})"


def _check_polynomial_root(c: Dict[str, Any]) -> Tuple[bool, str]:
    try:
        coeffs = c["claim"]["coeffs"]
        if c["claim"]["verdict"] != "root" or not isinstance(coeffs, list) or not 2 <= len(coeffs) <= MAX_DEGREE + 1:
            raise ValueError("a root certificate holds a verdict of root and 2 to 65 coefficients")
        cf = [_int(v) for v in coeffs]
        if cf[0] == 0:
            raise ValueError("the leading coefficient is 0")
        r = _rational_text(c["proof"]["root"])
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as e:
        return False, f"malformed polynomial-root certificate: {e}"[:160]
    if _horner(cf, r) == 0:
        return True, f"p({_text(r)}) = 0 exactly (degree {len(cf) - 1})"
    return False, f"p({_text(r)}) = {_text(_horner(cf, r))}, not 0"


def _check_linear_system(c: Dict[str, Any]) -> Tuple[bool, str]:
    try:
        claim = c["claim"]
        if claim["verdict"] != "solves":
            raise ValueError("a linear-system certificate holds a verdict of solves")
        rows, b, x = claim["A"], claim["b"], c["proof"]["x"]
        if not (isinstance(rows, list) and isinstance(b, list) and isinstance(x, list)) or not rows \
                or len(rows) > MAX_DIM or not 1 <= len(x) <= MAX_DIM or len(rows) != len(b) \
                or any(not isinstance(row, list) or len(row) != len(x) for row in rows):
            raise ValueError("A must be m x n, b of length m and x of length n, each at most 32")
        AF = [[_rational_text(v) for v in row] for row in rows]
        bF = [_rational_text(v) for v in b]
        xF = [_rational_text(v) for v in x]
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as e:
        return False, f"malformed linear-system certificate: {e}"[:160]
    if all(sum((row[j] * xF[j] for j in range(len(xF))), Fraction(0)) == bF[i] for i, row in enumerate(AF)):
        return True, f"A x = b exactly ({len(AF)} x {len(xF)})"
    return False, "A x is not b"


def check(cert: Any) -> Tuple[bool, str]:
    """Re-confirm a certificate from the certificate alone: no verifier runs, only the arithmetic above."""
    if not isinstance(cert, dict) or cert.get("schema") != SCHEMA:
        return False, "not a certificate of schema 1"
    kind = cert.get("kind")
    if not isinstance(cert.get("claim"), dict) or not isinstance(cert.get("proof"), dict):
        return False, "a certificate holds a claim and a proof"
    if kind == "primality":
        return _check_primality(cert)
    if kind == "polynomial_root":
        return _check_polynomial_root(cert)
    if kind == "linear_system":
        return _check_linear_system(cert)
    return False, f"unknown certificate kind {kind!r}"[:120]


# ── the binding: the certificate states the inputs the check read ───────────────────────────────────────────────
_FIELDS = {"primality": ("n_prime",), "polynomial_root": ("coeffs", "claimed_root"),
           "linear_system": ("matrix", "vec_b", "claimed_solution")}


def _packet(spec: Any, fields: Tuple[str, ...]) -> Optional[Dict[str, Any]]:
    """The dict in the spec (the spec itself or one of its values) that holds every field the kind reads."""
    for d in ([spec] if isinstance(spec, dict) else []) + ([v for v in spec.values() if isinstance(v, dict)]
                                                           if isinstance(spec, dict) else []):
        if all(f in d for f in fields):
            return d
    return None


def binds(cert: Any, spec: Any) -> Tuple[bool, str]:
    """Whether the certificate states exactly the inputs this spec gave its check, read as the verifier reads them."""
    kind = cert.get("kind") if isinstance(cert, dict) else None
    fields = _FIELDS.get(kind)
    if fields is None:
        return False, f"unknown certificate kind {kind!r}"[:120]
    pk = _packet(spec, fields)
    if pk is None:
        return False, f"the spec holds no packet with {', '.join(fields)}"
    try:
        claim, proof = cert["claim"], cert["proof"]
        if kind == "primality":
            same = _input_integer(pk["n_prime"]) == claim["n"]
        elif kind == "polynomial_root":
            same = ([_input_integer(v) for v in pk["coeffs"]] == claim["coeffs"]
                    and _input_root(pk["claimed_root"]) == _rational_text(proof["root"]))
        else:
            same = ([[_input_exact(v) for v in row] for row in pk["matrix"]]
                    == [[_rational_text(v) for v in row] for row in claim["A"]]
                    and [_input_exact(v) for v in pk["vec_b"]] == [_rational_text(v) for v in claim["b"]]
                    and [_input_exact(v) for v in pk["claimed_solution"]] == [_rational_text(v) for v in proof["x"]])
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as e:
        return False, f"the spec or the certificate does not read: {e}"[:160]
    return (True, "the certificate states the checked inputs") if same else \
        (False, "the certificate is about other inputs than the ones checked")


def recheck(record: Dict[str, Any], specs: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Re-check every certificate a sealed record carries, and bind each to its spec when `specs` (spec_hash ->
    spec) holds it. One row per certificate: {name, kind, ok, detail, bound}; bound is None when no spec was given."""
    out: List[Dict[str, Any]] = []
    for vr in record.get("verifier_results") or []:
        d = (vr.get("data") or {}) if isinstance(vr, dict) else {}
        cert = d.get("certificate")
        if not isinstance(cert, dict):
            continue
        ok, detail = check(cert)
        bound = None
        spec = (specs or {}).get(d.get("spec_hash"))
        if spec is not None:
            bound = binds(cert, spec)[0]
        out.append({"name": vr.get("name"), "kind": cert.get("kind"), "ok": ok, "detail": detail, "bound": bound})
    return out


__all__ = ["SCHEMA", "primality", "polynomial_root", "linear_system", "check", "binds", "recheck"]
