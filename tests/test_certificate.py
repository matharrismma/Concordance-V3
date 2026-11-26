"""CERTIFICATES: a proof of the verdict anyone can re-check without this engine (verifiers/certificate.py).

Ported from concordance-2, whose checker accepted four forgeries, measured 2026-11-26: "17.9 is prime" carrying 17's
proof, "2 is a root of x - 2.5", a coefficient written true, and a valid proof for 17 inside a record about 19. Each
is pinned here as refused, by the engine's checker and by the stranger's copy in docs/verify_receipt.py, which must
give the same answer on every certificate, valid or forged.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import random
import subprocess
import sys
from pathlib import Path

import pytest

from concordance import receipts
from concordance.derivation import verify_derivation
from concordance.verifiers import certificate as C
from concordance.verifiers import linear_algebra, number_theory, polynomial

ROOT = Path(__file__).resolve().parent.parent


def _stranger():
    spec = importlib.util.spec_from_file_location("verify_receipt_cert", ROOT / "docs" / "verify_receipt.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


VR = _stranger()


def _both(cert):
    """The engine's verdict on a certificate, held equal to the stranger's."""
    a, b = C.check(cert)[0], VR.check_certificate(cert)[0]
    assert a == b, (cert, C.check(cert), VR.check_certificate(cert))
    return a


# ── the proofs are right ───────────────────────────────────────────────────────────────────────────────────────
def test_every_n_to_3000_and_a_sample_to_ten_to_the_twelve_is_certified_and_checks():
    r = random.Random(1126)
    ns = list(range(2, 3001)) + [r.randint(3001, 10 ** 12) for _ in range(300)] + [999999999989, 10 ** 12 - 11]
    for n in ns:
        cert = C.primality(n)
        assert (cert["claim"]["verdict"] == "prime") == number_theory._is_prime(n), n
        assert _both(cert), n


def test_a_root_and_an_exact_solution_are_certified_and_check():
    assert _both(C.polynomial_root([2, -3, 1], 1)) and _both(C.polynomial_root([1, -5, 6], 3))
    assert _both(C.polynomial_root([2, -3, 1], C.Fraction(1, 2)))
    assert _both(C.linear_system([[1, 2], [3, 4]], [5, 6], [-4, 4.5]))
    assert _both(C.linear_system([[2, 0], [0, 3]], ["1", "1"], ["1/2", "1/3"]))
    with pytest.raises(ValueError):
        C.polynomial_root([1, -2], 3)                                   # not a root: no certificate is made
    with pytest.raises(ValueError):
        C.linear_system([[1, 2], [3, 4]], [5, 6], [-3.9999999, 4.5])    # not exact: no certificate is made


# ── the four forgeries concordance-2 accepted, and more ────────────────────────────────────────────────────────
def _forge(cert, path, value):
    c = copy.deepcopy(cert)
    node = c
    for k in path[:-1]:
        node = node[k]
    node[path[-1]] = value
    return c


P17, C91 = C.primality(17), C.primality(91)
ROOT_2 = C.polynomial_root([1, -2], 2)
LIN = C.linear_system([[1, 2], [3, 4]], [5, 6], [-4, 4.5])

FORGERIES = {
    "17.9 is prime, carrying 17's proof": _forge(P17, ("claim", "n"), 17.9),
    "n written as text": _forge(P17, ("claim", "n"), "17"),
    "n written as a whole float": _forge(P17, ("claim", "n"), 17.0),
    "2 is a root of x - 2.5": _forge(ROOT_2, ("claim", "coeffs"), [1, -2.5]),
    "a coefficient written true": {**ROOT_2, "claim": {"coeffs": [True, -1], "verdict": "root"}, "proof": {"root": "1"}},
    "a root given as a number, not text": _forge(ROOT_2, ("proof", "root"), 2),
    "a root as a decimal": _forge(ROOT_2, ("proof", "root"), "2.0"),
    "a factor written 7.0": _forge(C91, ("proof", "factor"), 7.0),
    "a factor written true": _forge(C91, ("proof", "factor"), True),
    "a factor that does not divide": _forge(C91, ("proof", "factor"), 6),
    "n itself as its own factor": _forge(C91, ("proof", "factor"), 91),
    "91 claimed prime": _forge(C91, ("claim", "verdict"), "prime"),
    "a prime factor of n - 1 left out": _forge(C.primality(31), ("proof", "factors"), C.primality(31)["proof"]["factors"][:-1]),
    "a base whose order is short": _forge(P17, ("proof", "base"), 2),
    "561 (Carmichael) claimed prime with base 2": {"kind": "primality", "schema": 1, "claim": {"n": 561, "verdict": "prime"},
                                                    "proof": {"base": 2, "factors": [[2, C.primality(2)], [5, C.primality(5)],
                                                                                     [7, C.primality(7)]]}},
    "a factor entry certifying another prime": _forge(P17, ("proof", "factors"), [[2, C.primality(3)]]),
    "n past 64 bits": {"kind": "primality", "schema": 1, "claim": {"n": 2 ** 64 + 13, "verdict": "composite"},
                       "proof": {"factor": 3}},
    "a solution written as numbers": _forge(LIN, ("proof", "x"), [-4, 4.5]),
    "a wrong solution": _forge(LIN, ("proof", "x"), ["-4", "4"]),
    "a zero denominator": _forge(LIN, ("proof", "x"), ["-4", "9/0"]),
    "a system past 32 columns": {**LIN, "claim": {"A": [["1"] * 33], "b": ["33"], "verdict": "solves"}, "proof": {"x": ["1"] * 33}},
    "another schema": {**P17, "schema": 2},
    "an unknown kind": {**P17, "kind": "factorial"},
}


@pytest.mark.parametrize("name", sorted(FORGERIES))
def test_a_forgery_is_refused_by_both_checkers(name):
    assert _both(FORGERIES[name]) is False


def test_both_checkers_agree_on_thousands_of_random_mutations():
    r = random.Random(7)
    good = [C.primality(n) for n in (2, 3, 17, 91, 97, 7919, 999999999989)] + [ROOT_2, LIN,
                                                                                C.polynomial_root([1, -5, 6], 3)]
    values = [0, 1, 2, -1, 17, 17.0, 17.5, "17", "1/2", True, None, [], {}, 2 ** 70, "x", -4, "-4", 1e308]

    def paths(node, here=()):
        if isinstance(node, dict):
            for k, v in node.items():
                yield from paths(v, here + (k,))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                yield from paths(v, here + (i,))
        yield here

    for _ in range(3000):
        cert = r.choice(good)
        ps = [p for p in paths(cert) if p]
        _both(_forge(cert, r.choice(ps), r.choice(values)))


# ── the binding: a proof is about the inputs that were checked ─────────────────────────────────────────────────
def test_a_proof_for_17_does_not_stand_for_a_claim_about_19():
    assert C.binds(P17, {"NUM_VERIFY": {"n_prime": 17, "claimed_prime": True}})[0]
    assert C.binds(P17, {"NUM_VERIFY": {"n_prime": 17.0, "claimed_prime": True}})[0]    # the verifier reads 17.0 as 17
    for other in (19, 17.5, "seventeen", True):
        assert not C.binds(P17, {"NUM_VERIFY": {"n_prime": other, "claimed_prime": True}})[0], other
        assert not VR.bind_certificate(P17, {"NUM_VERIFY": {"n_prime": other, "claimed_prime": True}})[0], other
    assert C.binds(ROOT_2, {"POLY_VERIFY": {"coeffs": [1, -2], "claimed_root": 2}})[0]
    assert not C.binds(ROOT_2, {"POLY_VERIFY": {"coeffs": [1, -3], "claimed_root": 2}})[0]
    assert C.binds(LIN, {"LIN_VERIFY": {"matrix": [[1, 2], [3, 4]], "vec_b": [5, 6], "claimed_solution": [-4, 4.5]}})[0]
    assert not C.binds(LIN, {"LIN_VERIFY": {"matrix": [[1, 2], [3, 5]], "vec_b": [5, 6], "claimed_solution": [-4, 4.5]}})[0]
    assert not C.binds(P17, {"POLY_VERIFY": {"coeffs": [1, -2], "claimed_root": 2}})[0]


# ── the hosts attach a certificate only where they can stand behind it ─────────────────────────────────────────
def test_the_hosts_attach_a_certificate_only_where_it_holds():
    assert number_theory.verify_primality({"n_prime": 97, "claimed_prime": True}).data["certificate"] == C.primality(97)
    assert number_theory.verify_primality({"n_prime": 91, "claimed_prime": True}).data["certificate"] == C91
    assert "certificate" not in number_theory.verify_primality({"n_prime": 10 ** 12 + 39, "claimed_prime": True}).data
    assert "certificate" not in number_theory.verify_primality({"n_prime": 1, "claimed_prime": False}).data
    assert polynomial.verify_root({"coeffs": [1, -2], "claimed_root": 2}).data["certificate"] == ROOT_2
    assert "certificate" not in polynomial.verify_root({"coeffs": [1, -2], "claimed_root": 3}).data
    exact = linear_algebra.run({"LIN_VERIFY": {"matrix": [[1, 2], [3, 4]], "vec_b": [5, 6], "claimed_solution": [-4, 4.5]}})
    near = linear_algebra.run({"LIN_VERIFY": {"matrix": [[1, 2], [3, 4]], "vec_b": [5, 6], "claimed_solution": [-3.9999999, 4.5]}})
    assert exact[0].data["certificate"] == LIN and "certificate" not in near[0].data


# ── through the seal, and checked by the stranger's file ───────────────────────────────────────────────────────
SPEC = {"NUM_VERIFY": {"n_prime": 97, "claimed_prime": True}}


def _record(spec=SPEC, domain="number_theory"):
    res = verify_derivation([{"id": "p", "domain": domain, "spec": spec}])
    rec = receipts.record_from_derivation(res, domain=domain).to_dict()
    rec["content_hash"] = VR.sha256(VR.canonical({k: v for k, v in rec.items() if k != "content_hash"}))
    return res, rec


def test_the_seal_carries_the_certificate_and_it_rebinds_to_its_spec():
    res, rec = _record()
    d = rec["verifier_results"][0]["data"]
    assert res["verdict"] == "HOLDS" and d["certificate"] == C.primality(97)
    assert C.recheck(rec, {d["spec_hash"]: SPEC}) == [
        {"name": "p", "kind": "primality", "ok": True, "detail": C.check(C.primality(97))[1], "bound": True}]
    assert C.recheck(rec)[0]["bound"] is None
    assert C.recheck(rec, {d["spec_hash"]: {"NUM_VERIFY": {"n_prime": 89, "claimed_prime": True}}})[0]["bound"] is False


def _run_stranger(tmp_path, rec, *specs):
    rp = tmp_path / "receipt.json"
    rp.write_text(json.dumps(rec), encoding="utf-8")
    args = [sys.executable, "-X", "utf8", "-I", str(ROOT / "docs" / "verify_receipt.py"), str(rp), "--offline"]
    for i, sp in enumerate(specs):
        f = tmp_path / f"spec{i}.json"
        f.write_text(json.dumps(sp), encoding="utf-8")
        args += ["--spec", str(f)]
    out = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=60)
    return out.returncode, out.stdout


def test_the_strangers_file_rechecks_and_binds_the_certificate(tmp_path):
    _, rec = _record()
    code, out = _run_stranger(tmp_path, rec, SPEC)
    assert code == 0 and "CERT       ok" in out and "BIND       ok" in out, out
    code, out = _run_stranger(tmp_path, rec, {"NUM_VERIFY": {"n_prime": 89, "claimed_prime": True}})
    assert code == 0 and "no --spec re-hashes" in out, out              # a spec of another step binds nothing
    forged = copy.deepcopy(rec)
    forged["verifier_results"][0]["data"]["certificate"]["claim"]["n"] = 17.9
    forged["content_hash"] = VR.sha256(VR.canonical({k: v for k, v in forged.items() if k != "content_hash"}))
    code, out = _run_stranger(tmp_path, forged, SPEC)
    assert code == 1 and "CERT       FAIL" in out, out                  # re-hashed so HASH passes: the CERT line fails it
