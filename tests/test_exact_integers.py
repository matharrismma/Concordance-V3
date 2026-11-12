"""Run 2026-11-11-exact-integers, step fix-a2: THE RULE (src/concordance/verifiers/_integer.py) closes every lossy
integer read in combinatorics.py, periodic_table.py, atomic.py, number_theory.py, wordcraft.py and
operations_research.py.

int() drops a fraction and takes a bool for 1, so P(5,2) claimed 20.9 read HOLDS, as did iron claimed atomic number
26.5 and a quantum-number set with n 2.7. Mathematics' two readers moved into one shared module and every site here
reads through them: an input by _exact_integer (a fraction, a bool or other text reads malformed: SYSTEM_ERROR), a
claimed result by _claimed_integer (a fraction stands as written: BROKEN), and the validity of a quantum number by
_valid_integer (a fraction is invalid, anything not a number malformed). These tests hold: the three readings and
their refusals; mathematics reading exactly as before, its own refusal sentence included; every case of the plan's
TESTS item; one case per closed site, with an input that reached a lossy call at the base (for a probe site, the
probe's own finding: the golden's true spec with the leaf varied), each with its base reading beside it; the sites
rewritten without a lossy call keeping their readings; the readings this step moves that the plan names only by its
rule; and the eight roundings named in tests/integer_fields.json, each with a fractional input that reads as the
check should. Base readings were measured at main 388fe28 (src as at d5003f5).

Names the fix adds are read inside the tests, so the file collects at the step's base and each case reads red there
where its reading moves.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from concordance.derivation import verify_derivation

ROOT = Path(__file__).resolve().parent.parent
H, B, E, I = "HOLDS", "BROKEN", "SYSTEM_ERROR", "INCOMPLETE"
FILES = ("combinatorics.py", "periodic_table.py", "atomic.py", "number_theory.py", "wordcraft.py",
         "operations_research.py")


def read(domain, spec):
    return verify_derivation([{"id": "c", "domain": domain, "spec": json.loads(json.dumps(spec))}])


def verdict(domain, spec):
    return read(domain, spec)["verdict"]


def detail(domain, spec):
    return str(read(domain, spec)["trail"][0].get("detail", ""))


# ── THE RULE's three readings ─────────────────────────────────────────────────────────────────────────────────
def test_an_input_reads_whole_or_is_refused_naming_its_field():
    from concordance.verifiers._integer import _exact_integer
    for value, want in ((20, 20), (20.0, 20), ("20", 20), (-3, -3), (" 7 ", 7)):
        got = _exact_integer(value, "n")
        assert got == want and type(got) is int
    for value in (20.9, True, False, None, "20.0", "twenty", float("inf"), float("nan"), [20], {"n": 20}):
        with pytest.raises((TypeError, ValueError)) as raised:
            _exact_integer(value, "perm_n")
        assert str(raised.value) == f"perm_n is not a whole number: {value!r}"


def test_a_claimed_result_with_a_fraction_stands_as_written():
    from concordance.verifiers._integer import _claimed_integer
    assert _claimed_integer(20.9, "c") == 20.9 and _claimed_integer("20.9", "c") == "20.9"
    assert _claimed_integer("20.9", "c", as_number=True) == 20.9
    for value in (20, 20.0, "20"):
        got = _claimed_integer(value, "c")
        assert got == 20 and type(got) is int
    for value in (True, None, "20.0", "twenty", float("inf"), "1e400"):
        with pytest.raises((TypeError, ValueError)) as raised:
            _claimed_integer(value, "claimed_permutations")
        assert str(raised.value) == f"claimed_permutations is not a whole number: {value!r}"


def test_a_value_whose_validity_is_the_question_reads_a_fraction_invalid():
    from concordance.verifiers._integer import _valid_integer
    assert _valid_integer(2.7, "n") is None and _valid_integer(-0.5, "m_l") is None
    assert _valid_integer(2, "n") == 2 and _valid_integer("2", "n") == 2 and _valid_integer(2.0, "n") == 2
    for value in (True, None, "abc", "2.7", float("inf")):
        with pytest.raises((TypeError, ValueError)) as raised:
            _valid_integer(value, "m_l")
        assert str(raised.value) == f"m_l is not a whole number: {value!r}"


def test_a_long_value_is_shown_cut():
    from concordance.verifiers._integer import _exact_integer
    with pytest.raises(ValueError) as raised:
        _exact_integer("9" * 100 + ".5", "n")
    assert str(raised.value) == "n is not a whole number: '" + "9" * 56 + "..."


# ── mathematics reads exactly as before ───────────────────────────────────────────────────────────────────────
# Each row's status and detail as mathematics.verify_number_theory read it at the base, before the readers moved.
MATHEMATICS = [
    ({"factorial": 5, "claimed_factorial": 120.5}, "MISMATCH", "5! = 120, claimed 120.5"),
    ({"factorial": 5, "claimed_factorial": True}, "ERROR", "malformed number-theory input: True is not an integer"),
    ({"factorial": 5, "claimed_factorial": "120.0"}, "ERROR",
     "malformed number-theory input: invalid literal for int() with base 10: '120.0'"),
    ({"factorial": 5, "claimed_factorial": "one hundred twenty"}, "ERROR",
     "malformed number-theory input: could not convert string to float: 'one hundred twenty'"),
    ({"factorial": 5, "claimed_factorial": None}, "ERROR", "malformed number-theory input: None is not an integer"),
    ({"factorial": 5.5, "claimed_factorial": 120}, "ERROR", "malformed number-theory input: 5.5 is not an integer"),
    ({"factorial": "5", "claimed_factorial": 120}, "CONFIRMED", "5! = 120"),
    ({"factorial": "five", "claimed_factorial": 120}, "ERROR",
     "malformed number-theory input: invalid literal for int() with base 10: 'five'"),
    ({"binomial": [5, 2.5], "claimed_binomial": 10}, "ERROR", "malformed number-theory input: 2.5 is not an integer"),
    ({"binomial": [5, 2], "claimed_binomial": "10.5"}, "MISMATCH", "C(5,2) = 10, claimed 10.5"),
    ({"gcd": [12, True], "claimed_gcd": 6}, "ERROR", "malformed number-theory input: True is not an integer"),
    ({"gcd": [12, 18], "claimed_gcd": 6.0}, "CONFIRMED", "gcd(12, 18) = 6"),
    ({"is_prime": 17.5, "claimed_prime": True}, "ERROR", "malformed number-theory input: 17.5 is not an integer"),
    ({"modulo": [17, float("inf")], "claimed_modulo": 2}, "ERROR",
     "malformed number-theory input: inf is not an integer"),
    ({"lcm": [4, 6], "claimed_lcm": float("nan")}, "ERROR", "malformed number-theory input: nan is not an integer"),
    ({"factorial": 5, "claimed_factorial": 120}, "CONFIRMED", "5! = 120"),
]


@pytest.mark.parametrize("spec,status,words", MATHEMATICS, ids=repr)
def test_mathematics_reads_exactly_as_before(spec, status, words):
    from concordance.verifiers.mathematics import verify_number_theory
    r = verify_number_theory(spec)
    assert (str(r.status), r.detail) == (status, words)


def test_mathematics_reads_through_the_shared_readers():
    from concordance.verifiers import _integer, mathematics
    assert mathematics._exact_integer is _integer._exact_integer
    assert mathematics._claimed_integer is _integer._claimed_integer


# ── the plan's TESTS item ─────────────────────────────────────────────────────────────────────────────────────
def _perm(n, k, c):
    return ("combinatorics", {"COMB_VERIFY": {"perm_n": n, "perm_k": k, "claimed_permutations": c}})


def _element(name, z):
    return ("periodic_table", {"PT_VERIFY": {"name": name, "claimed_atomic_number": z}})


def _quantum(claimed=True, **given):
    spec = {"n": 2, "l": 1, "m_l": 0, "m_s": 0.5, "claimed_valid_quantum_numbers": claimed}
    spec.update(given)
    return ("atomic", {"ATOM_VERIFY": spec})


# (case, (domain, spec), reading at the base, reading now)
PLAN = [
    ("P(5,2) claimed 20.9", _perm(5, 2, 20.9), H, B),
    ("P(5,2) claimed true", _perm(5, 2, True), B, E),
    ("P(5.5,2) claimed 20", _perm(5.5, 2, 20), H, E),
    ("P(5,2.5) claimed 20", _perm(5, 2.5, 20), H, E),
    ("P(5,2) claimed 20", _perm(5, 2, 20), H, H),
    ("P(5,2) claimed 20.0", _perm(5, 2, 20.0), H, H),
    ("P(5,2) claimed '20'", _perm(5, 2, "20"), H, H),
    ("P(5,2) claimed 21", _perm(5, 2, 21), B, B),
    ("P(5,2) claimed '20.0'", _perm(5, 2, "20.0"), E, E),
    ("iron claimed 26.5", _element("iron", 26.5), H, B),
    ("iron claimed 'twenty-seven'", _element("iron", "twenty-seven"), H, E),
    ("iron claimed '26.0'", _element("iron", "26.0"), H, E),
    ("hydrogen claimed true", _element("hydrogen", True), H, E),
    ("iron claimed 26", _element("iron", 26), H, H),
    ("iron claimed 26.0", _element("iron", 26.0), H, H),
    ("iron claimed '26'", _element("iron", "26"), H, H),
    ("hydrogen claimed 1", _element("hydrogen", 1), H, H),
    ("iron claimed 27", _element("iron", 27), B, B),
    ("n 2.7 claimed valid", _quantum(True, n=2.7), H, B),
    ("m_l 0.5 claimed valid", _quantum(True, m_l=0.5), H, B),
    ("n 2.7 claimed invalid", _quantum(False, n=2.7), B, H),
    ("m_l 0.5 claimed invalid", _quantum(False, m_l=0.5), B, H),
    ("m_l true claimed valid", _quantum(True, m_l=True), H, E),
    ("m_l true claimed invalid", _quantum(False, m_l=True), B, E),
    ("the set as given claimed valid", _quantum(True), H, H),
    ("n '2' claimed valid", _quantum(True, n="2"), H, H),
    ("n 'abc' claimed invalid", _quantum(False, n="abc"), E, E),
    ("n null claimed invalid", _quantum(False, n=None), E, E),
]


@pytest.mark.parametrize("case,given,base,now", PLAN, ids=[row[0] for row in PLAN])
def test_the_plans_cases_read_as_the_plan_says(case, given, base, now):
    assert verdict(*given) == now


def test_a_refusal_names_the_field_and_says_it_is_not_a_whole_number():
    assert detail(*_perm(5.5, 2, 20)).endswith("perm_n is not a whole number: 5.5")
    assert detail(*_element("iron", "twenty-seven")).endswith(
        "claimed_atomic_number is not a whole number: 'twenty-seven'")
    assert detail(*_quantum(True, m_l=True)).endswith("m_l is not a whole number: True")
    assert detail(*_perm(5, 2, 20.9)).endswith("P(5,2) = 20, claimed 20.9")
    assert "n=2.7 is not a whole number" in detail(*_quantum(True, n=2.7))


# ── one case per closed site ──────────────────────────────────────────────────────────────────────────────────
VARIED = {"+0.25": lambda v: v + 0.25, "-0.25": lambda v: v - 0.25, "bool": bool,
          "text +0.25": lambda v: str(v + 0.25), "true": lambda v: True}


def _golden(check, leaf, variant):
    """The check's true spec in data/check_goldens.jsonl with one leaf varied, as the probe varies it (or, for the
    two variants the probe does not make, written as a text with a fraction, or as true)."""
    for line in (ROOT / "data" / "check_goldens.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line) if line.strip() else None
        if row and row["check"] == check:
            spec = json.loads(json.dumps(row["true"]))
            path = [int(p) if p.isdigit() else p for p in leaf.split("/")]
            at = spec
            for key in path[:-1]:
                at = at[key]
            at[path[-1]] = VARIED[variant](at[path[-1]])
            return row["domain"], spec
    raise LookupError(check)


# Every site THE PROBE found in these files at the base, with one of its findings: (check, leaf, variant, reading
# at the base, reading now). An input reads SYSTEM_ERROR, a claimed result BROKEN, a quantum number with a fraction
# invalid; the knapsack's weights and capacity are real numbers, so a fraction there reads as it did.
PROBED = {
    'atomic.py:verify_electron_configuration:int(z)#1':
        ('atomic.electron_configuration', 'ATOM_VERIFY/atomic_number', '+0.25', H, E),
    'atomic.py:verify_energy_level:int(spec["level_n"])#1':
        ('atomic.energy_level', 'ATOM_VERIFY/level_n', '+0.25', H, E),
    'atomic.py:verify_quantum_numbers:int(m_l)#1':
        ('atomic.electron_configuration', 'ATOM_VERIFY/m_l', '+0.25', H, B),
    'atomic.py:verify_quantum_numbers:int(spec["l"])#1':
        ('atomic.electron_configuration', 'ATOM_VERIFY/l', '+0.25', H, B),
    'atomic.py:verify_quantum_numbers:int(spec["n"])#1':
        ('atomic.electron_configuration', 'ATOM_VERIFY/n', '+0.25', H, B),
    'atomic.py:verify_shell_capacity:int(spec["claimed_shell_capacity"])#1':
        ('atomic.electron_configuration', 'ATOM_VERIFY/claimed_shell_capacity', '+0.25', H, B),
    'atomic.py:verify_shell_capacity:int(spec["shell_n"])#1':
        ('atomic.electron_configuration', 'ATOM_VERIFY/shell_n', '+0.25', H, E),
    'combinatorics.py:verify_combinations:int(claimed)#1':
        ('combinatorics.combinations', 'COMB_VERIFY/claimed_combinations', '+0.25', H, B),
    'combinatorics.py:verify_combinations:int(k)#1':
        ('combinatorics.combinations', 'COMB_VERIFY/comb_k', '+0.25', H, E),
    'combinatorics.py:verify_combinations:int(n)#1':
        ('combinatorics.combinations', 'COMB_VERIFY/comb_n', '+0.25', H, E),
    'combinatorics.py:verify_derangements:int(claimed)#1':
        ('combinatorics.derangements', 'COMB_VERIFY/claimed_derangements', '+0.25', H, B),
    'combinatorics.py:verify_derangements:int(n)#1':
        ('combinatorics.derangements', 'COMB_VERIFY/derangement_n', '+0.25', H, E),
    'combinatorics.py:verify_multinomial:int(claimed)#1':
        ('combinatorics.derangements', 'COMB_VERIFY/claimed_multinomial', '+0.25', H, B),
    'combinatorics.py:verify_multinomial:int(g)#1':
        ('combinatorics.derangements', 'COMB_VERIFY/multinomial_groups/0', '+0.25', H, E),
    'combinatorics.py:verify_permutations:int(claimed)#1':
        ('combinatorics.derangements', 'COMB_VERIFY/claimed_permutations', '+0.25', H, B),
    'combinatorics.py:verify_permutations:int(k)#1':
        ('combinatorics.derangements', 'COMB_VERIFY/perm_k', '+0.25', H, E),
    'combinatorics.py:verify_permutations:int(n)#1':
        ('combinatorics.derangements', 'COMB_VERIFY/perm_n', '+0.25', H, E),
    'number_theory.py:verify_critical_line:int(spec.get("claimed_zeros_on_line"))#1':
        ('number_theory.critical_line', 'NUM_VERIFY/claimed_zeros_on_line', '+0.25', H, B),
    'number_theory.py:verify_divisor_count:int(claimed_count)#1':
        ('number_theory.divisor_count', 'NUM_VERIFY/claimed_divisor_count', '+0.25', H, B),
    'number_theory.py:verify_divisor_count:int(spec.get("divisors_of"))#1':
        ('number_theory.divisor_count', 'NUM_VERIFY/divisors_of', '+0.25', H, E),
    'number_theory.py:verify_factorial:int(claimed)#1':
        ('number_theory.factorial', 'NUM_VERIFY/claimed_factorial', '+0.25', H, B),
    'number_theory.py:verify_factorial:int(n)#1':
        ('number_theory.factorial', 'NUM_VERIFY/factorial_n', '+0.25', H, E),
    'number_theory.py:verify_gcd:int(a)#1':
        ('number_theory.factorial', 'NUM_VERIFY/gcd_a', '+0.25', H, E),
    'number_theory.py:verify_gcd:int(b)#1':
        ('number_theory.factorial', 'NUM_VERIFY/gcd_b', '+0.25', H, E),
    'number_theory.py:verify_gcd:int(claimed)#1':
        ('number_theory.factorial', 'NUM_VERIFY/claimed_gcd', '+0.25', H, B),
    'number_theory.py:verify_lagarias:int(claimed_n)#1':
        ('number_theory.lagarias', 'NUM_VERIFY/claimed_closest_approach_n', '+0.25', H, B),
    'number_theory.py:verify_lagarias:int(claimed_n)#2':
        ('number_theory.lagarias', 'NUM_VERIFY/claimed_closest_approach_n', '-0.25', B, B),
    'number_theory.py:verify_lagarias:int(spec.get("lagarias_to"))#1':
        ('number_theory.lagarias', 'NUM_VERIFY/lagarias_to', '+0.25', H, E),
    'number_theory.py:verify_modular_inverse:int(a)#1':
        ('number_theory.factorial', 'NUM_VERIFY/mod_a', '+0.25', H, E),
    'number_theory.py:verify_modular_inverse:int(claimed)#1':
        ('number_theory.factorial', 'NUM_VERIFY/claimed_inverse', '+0.25', H, B),
    'number_theory.py:verify_modular_inverse:int(m)#1':
        ('number_theory.factorial', 'NUM_VERIFY/mod_m', '+0.25', H, E),
    'number_theory.py:verify_nicolas:int(claimed_prime)#1':
        ('number_theory.nicolas', 'NUM_VERIFY/claimed_closest_prime', '+0.25', H, B),
    'number_theory.py:verify_nicolas:int(claimed_prime)#2':
        ('number_theory.nicolas', 'NUM_VERIFY/claimed_closest_prime', '-0.25', B, B),
    'number_theory.py:verify_nicolas:int(spec.get("nicolas_primes_to"))#1':
        ('number_theory.nicolas', 'NUM_VERIFY/nicolas_primes_to', '+0.25', H, E),
    'number_theory.py:verify_perfect_number:int(n)#1':
        ('number_theory.perfect_number', 'NUM_VERIFY/n_perfect', '+0.25', H, E),
    'number_theory.py:verify_primality:int(n)#1':
        ('number_theory.factorial', 'NUM_VERIFY/n_prime', '+0.25', H, E),
    'number_theory.py:verify_prime_counting:int(claimed)#1':
        ('number_theory.prime_counting', 'NUM_VERIFY/claimed_prime_count', '+0.25', H, B),
    'number_theory.py:verify_prime_counting:int(x ** 0.5)#1':
        ('number_theory.prime_counting', 'NUM_VERIFY/limit', '-0.25', H, E),
    'number_theory.py:verify_prime_counting:int(x)#1':
        ('number_theory.prime_counting', 'NUM_VERIFY/limit', '+0.25', H, E),
    'number_theory.py:verify_robin:int(claimed_n)#1':
        ('number_theory.robin', 'NUM_VERIFY/claimed_closest_approach_n', '+0.25', H, B),
    'number_theory.py:verify_robin:int(claimed_n)#2':
        ('number_theory.robin', 'NUM_VERIFY/claimed_closest_approach_n', '-0.25', B, B),
    'number_theory.py:verify_robin:int(spec.get("robin_to"))#1':
        ('number_theory.robin', 'NUM_VERIFY/robin_to', '+0.25', H, E),
    'number_theory.py:verify_schoenfeld:int(claimed_n)#1':
        ('number_theory.schoenfeld', 'NUM_VERIFY/claimed_closest_approach_n', '+0.25', H, B),
    'number_theory.py:verify_schoenfeld:int(claimed_n)#2':
        ('number_theory.schoenfeld', 'NUM_VERIFY/claimed_closest_approach_n', '-0.25', B, B),
    'number_theory.py:verify_schoenfeld:int(spec.get("schoenfeld_to"))#1':
        ('number_theory.schoenfeld', 'NUM_VERIFY/schoenfeld_to', '+0.25', H, E),
    'number_theory.py:verify_sequence_term:int(claimed)#1':
        ('number_theory.sequence', 'NUM_VERIFY/claimed_term', '+0.25', H, B),
    'number_theory.py:verify_sequence_term:int(n)#1':
        ('number_theory.sequence', 'NUM_VERIFY/sequence_index', '+0.25', H, E),
    'number_theory.py:verify_zero_count:int(claimed)#1':
        ('number_theory.zero_count', 'NUM_VERIFY/claimed_zero_count', '+0.25', H, B),
    'operations_research.py:verify_assignment_cost:int(pair[0])#1':
        ('operations_research.assignment_cost', 'OR_VERIFY/assignment/0/0', '+0.25', H, E),
    'operations_research.py:verify_assignment_cost:int(pair[1])#1':
        ('operations_research.assignment_cost', 'OR_VERIFY/assignment/0/1', '+0.25', H, E),
    'operations_research.py:verify_knapsack_01:int(cap)#1':
        ('operations_research.critical_path', 'OR_VERIFY/capacity', '+0.25', H, H),
    'operations_research.py:verify_knapsack_01:int(w)#1':
        ('operations_research.critical_path', 'OR_VERIFY/items/0/weight', '-0.25', H, H),
    'periodic_table.py:verify_element:int(claimed_z)#1':
        ('periodic_table.atomic_mass_weighted_average', 'PT_VERIFY/claimed_atomic_number', '+0.25', H, B),
    'wordcraft.py:verify_alphabet:int(float(claimed))#1':
        ('wordcraft.alphabet', 'WORD_VERIFY/claimed_alphabet_letters', '+0.25', H, B),
    'wordcraft.py:verify_edit_distance:int(float(claimed))#1':
        ('wordcraft.alphabet', 'WORD_VERIFY/claimed_edit_distance', '+0.25', H, B),
    'wordcraft.py:verify_letter_rank:int(float(claimed))#1':
        ('wordcraft.alphabet', 'WORD_VERIFY/claimed_rank', '+0.25', H, B),
    'wordcraft.py:verify_letters:int(float(c))#1':
        ('wordcraft.alphabet', 'WORD_VERIFY/claimed_consonants', '+0.25', H, B),
    'wordcraft.py:verify_stress:int(float(claimed))#1':
        ('wordcraft.stress', 'WORD_VERIFY/claimed_stress_syllable', '+0.25', H, B),
    'wordcraft.py:verify_syllables:int(float(cp))#1':
        ('wordcraft.alphabet', 'WORD_VERIFY/claimed_phonemes', '+0.25', H, B),
    'wordcraft.py:verify_syllables:int(float(cs))#1':
        ('wordcraft.alphabet', 'WORD_VERIFY/claimed_syllables', '+0.25', H, B),
}


@pytest.mark.parametrize("site", sorted(PROBED))
def test_each_probed_site_reads_by_the_rule(site):
    check, leaf, variant, base, now = PROBED[site]
    assert verdict(*_golden(check, leaf, variant)) == now


@pytest.mark.parametrize("site", sorted(s for s in PROBED if s.endswith("#2")))
def test_a_claim_with_a_fraction_is_shown_as_written(site):
    """The second int() at these sites rewrote the claim in the detail: 2657.75 was shown as 2657."""
    check, leaf, variant, _, _ = PROBED[site]
    domain, spec = _golden(check, leaf, variant)
    claimed = spec["NUM_VERIFY"][leaf.split("/")[-1]]
    assert f"claimed {claimed}" in detail(domain, spec)


# Each claimed leaf the probe found in these files, once: written as a text with a fraction it stands as written and
# reads BROKEN (a claimed zero count of '1747146.25' raised on its own detail's format in the abandoned step fix-a), and
# given as true it
# is malformed and reads SYSTEM_ERROR.
CLAIMED_LEAVES = sorted({(check, leaf) for check, leaf, _, _, _ in PROBED.values()
                         if leaf.split("/")[-1].startswith("claimed_")})


@pytest.mark.parametrize("check,leaf", CLAIMED_LEAVES, ids=[f"{c} {l}" for c, l in CLAIMED_LEAVES])
def test_each_claimed_leaf_reads_a_text_with_a_fraction_broken_and_true_malformed(check, leaf):
    assert verdict(*_golden(check, leaf, "text +0.25")) == B
    assert verdict(*_golden(check, leaf, "true")) == E


def test_a_claimed_zero_count_written_with_a_fraction_reads_broken():
    spec = {"NUM_VERIFY": {"claimed_zero_count": "29.5", "zero_count_height": 100}}
    assert verdict("zero_count", spec) == B
    assert detail("zero_count", spec).endswith("N(100) = 29 zeros in the strip (Turing's method), claimed 29.5")


# The walk's sites the probe does not reach, each with an input that reached a lossy call at the base:
# (site, case, (domain, spec), reading at the base, reading now).
_NT = "number_theory"
WALKED = [
    ("periodic_table.py:_lookup:int(z)#1", "atomic_number 26.5 identifies no element",
     ("periodic_table", {"PT_VERIFY": {"atomic_number": 26.5, "claimed_name": "iron"}}), H, E),
    ("periodic_table.py:_lookup:int(z)#1", "atomic_number true identifies no element",
     ("periodic_table", {"PT_VERIFY": {"atomic_number": True, "claimed_name": "hydrogen"}}), H, E),
    ('atomic.py:verify_energy_level:int(spec["line_lower"])#1', "line_lower 2.5",
     ("atomic", {"ATOM_VERIFY": {"line_lower": 2.5, "line_upper": 3, "claimed_line_nm": 656.1}}), H, E),
    ('atomic.py:verify_energy_level:int(spec["line_upper"])#1', "line_upper 3.5",
     ("atomic", {"ATOM_VERIFY": {"line_lower": 2, "line_upper": 3.5, "claimed_line_nm": 656.1}}), H, E),
    ('atomic.py:verify_shell_capacity:int(spec["subshell_l"])#1', "subshell_l 2.5",
     ("atomic", {"ATOM_VERIFY": {"subshell_l": 2.5, "claimed_subshell_capacity": 10}}), H, E),
    ('atomic.py:verify_shell_capacity:int(spec["claimed_subshell_capacity"])#1', "subshell capacity claimed 10.5",
     ("atomic", {"ATOM_VERIFY": {"subshell_l": 2, "claimed_subshell_capacity": 10.5}}), H, B),
    ("number_theory.py:verify_divisor_count:int(x)#1", "a claimed divisor 12.5",
     (_NT, {"NUM_VERIFY": {"divisors_of": 12, "claimed_divisors": [1, 2, 3, 4, 6, 12.5]}}), H, B),
    ("number_theory.py:verify_divisor_count:int(x)#1", "a claimed divisor true",
     (_NT, {"NUM_VERIFY": {"divisors_of": 12, "claimed_divisors": [True, 2, 3, 4, 6, 12]}}), H, E),
]


@pytest.mark.parametrize("site,case,given,base,now", WALKED, ids=[f"{row[0]} {row[1]}" for row in WALKED])
def test_each_walked_site_reads_by_the_rule(site, case, given, base, now):
    assert verdict(*given) == now


def test_the_li_criterion_reads_its_index_by_the_rule():
    """number_theory.py:verify_li_criterion:int(spec.get("li_to"))#1, which no domain routes a golden to: li_to 3.5
    was read as 3 and confirmed at the base."""
    from concordance.verifiers import number_theory as NT
    r = NT.verify_li_criterion({"li_to": 3.5, "claimed_li_positive": True})
    assert (str(r.status), r.detail) == ("ERROR", "li_to is not a whole number: 3.5")
    assert str(NT.verify_li_criterion({"li_to": 3, "claimed_li_positive": True}).status) == "CONFIRMED"


# The sites closed with no input able to reach them with a fraction or a bool, each read as before: the digits a
# pattern matched, math.isqrt of an int, the knapsack's integer DP behind its wholeness test, Turing's count, the
# int() around a round() that already returns an int, the values each RH check computes from its height (closed by
# reading the height through THE RULE), and the reader that moved.
_CR = ("atomic", {"ATOM_VERIFY": {"atomic_number": 24, "claimed_configuration": "[Ar] 3d5 4s1"}})
_KNAPSACK = ("operations_research", {"OR_VERIFY": {
    "items": [{"weight": 5, "value": 10}, {"weight": 4, "value": 40}, {"weight": 6, "value": 30},
              {"weight": 3, "value": 50}],
    "capacity": 10, "claimed_optimal_value": 90}})
LOSSLESS = {
    "periodic_table.py:molar_mass:int(cnt)#1":
        ("periodic_table", {"PT_VERIFY": {"formula": "H2O", "claimed_molar_mass": 18.015}}),
    "atomic.py:_parse_config:int(c_s)#1": _CR,
    "atomic.py:_parse_config:int(n_s)#1": _CR,
    "atomic.py:_parse_config:int(n_s)#2": _CR,
    "number_theory.py:_is_prime:int(math.isqrt(n))#1": (_NT, {"NUM_VERIFY": {"n_prime": 137, "claimed_prime": True}}),
    "number_theory.py:_is_perfect_number:int(math.isqrt(n))#1":
        (_NT, {"NUM_VERIFY": {"n_perfect": 496, "claimed_perfect": True}}),
    "operations_research.py:verify_knapsack_01:int(cap)#2": _KNAPSACK,
    "operations_research.py:verify_knapsack_01:int(w)#2": _KNAPSACK,
    "number_theory.py:verify_zero_count:int(mp.nzeros(T))#1":
        ("zero_count", {"NUM_VERIFY": {"claimed_zero_count": 29, "zero_count_height": 100}}),
}
# sites closed with their function's height, read through THE RULE (each is in PROBED's case for that height)
_LAGARIAS = 'number_theory.py:verify_lagarias:int(spec.get("lagarias_to"))#1'
_NICOLAS = 'number_theory.py:verify_nicolas:int(spec.get("nicolas_primes_to"))#1'
_ROBIN = 'number_theory.py:verify_robin:int(spec.get("robin_to"))#1'
_SCHOENFELD = 'number_theory.py:verify_schoenfeld:int(spec.get("schoenfeld_to"))#1'
BY_THEIR_HEIGHT = {
    "number_theory.py:verify_lagarias:int(idx2 + 1)#1": _LAGARIAS,
    "number_theory.py:verify_lagarias:int(np.argmax(ratio[1:]))#1": _LAGARIAS,
    "number_theory.py:verify_nicolas:int(P ** 0.5)#1": _NICOLAS,
    "number_theory.py:verify_nicolas:int(p)#1": _NICOLAS,
    "number_theory.py:verify_robin:int(n[idx])#1": _ROBIN,
    "number_theory.py:verify_robin:int(np.argmax(ratio))#1": _ROBIN,
    "number_theory.py:verify_robin:int(v)#1": _ROBIN,
    "number_theory.py:verify_schoenfeld:int((X + 1) ** 0.5)#1": _SCHOENFELD,
    "number_theory.py:verify_schoenfeld:int(0.1 * math.sqrt(a) * math.log(a) * math.log(a) / eight_pi)#1": _SCHOENFELD,
    "number_theory.py:verify_schoenfeld:int(pref[a])#1": _SCHOENFELD,
    "number_theory.py:verify_schoenfeld:int(pref[b])#1": _SCHOENFELD,
    "number_theory.py:verify_schoenfeld:int(pref[n])#1": _SCHOENFELD,
}
assert set(BY_THEIR_HEIGHT.values()) <= set(PROBED)
# the int() around a round() or math.ceil that already returns an int: dropped, and the rounding named in
# tests/integer_fields.json
AROUND_A_ROUNDING = {
    "number_theory.py:_count_above_np:int(math.ceil((b - start) / h))#1",
    "number_theory.py:_zeros_on_line_checked:int(round(n_strip))#1",
    "number_theory.py:_zeros_on_line_checked.localise:int(round(nb - na))#1",
    "number_theory.py:verify_critical_line:int(round(n_strip))#1",
}
MOVED = {"mathematics.py:_exact_integer:int(value)#1"}


@pytest.mark.parametrize("site", sorted(LOSSLESS))
def test_a_site_closed_without_a_lossy_call_reads_as_before(site):
    assert verdict(*LOSSLESS[site]) == H


def test_the_knapsack_reads_a_fractional_weight_or_capacity_as_a_real_number():
    items = _KNAPSACK[1]["OR_VERIFY"]["items"]
    def packet(given, capacity):
        return ("operations_research",
                {"OR_VERIFY": {"items": given, "capacity": capacity, "claimed_optimal_value": 90}})
    assert verdict(*packet(items, 10.25)) == H
    heavy = [dict(items[0], weight=6.5)] + items[1:]          # 4 + 6.5 > 10.25: the 40 and 50 still fit, 10 does not
    assert verdict(*packet(heavy, 10.25)) == H
    assert verdict("operations_research", {"OR_VERIFY": {"items": [{"weight": float("inf"), "value": 1}],
                                                         "capacity": 10, "claimed_optimal_value": 0}}) == E


def test_a_modular_inverse_claimed_with_a_fraction_is_no_inverse():
    """2 · 0.5 mod 3 is 1.0: read as arithmetic, a fraction would pass, so a claim that is not whole reads BROKEN
    first."""
    spec = {"NUM_VERIFY": {"mod_a": 2, "mod_m": 3, "claimed_inverse": 0.5}}
    assert verdict(_NT, spec) == B
    assert detail(_NT, spec).endswith("a modular inverse is a whole number; claimed 0.5, correct inverse is 2")
    assert verdict(_NT, {"NUM_VERIFY": {"mod_a": 2, "mod_m": 3, "claimed_inverse": 2}}) == H


# ── readings that move by THE RULE, which the plan's TESTS do not list ─────────────────────────────────────────
OTHER_MOVES = [
    ("a claimed text with a fraction, refused by int() at the base, now stands as written",
     ("atomic", {"ATOM_VERIFY": {"subshell_l": 2, "claimed_subshell_capacity": "10.5"}}), E, B),
    ("a claimed text with a fraction (modular inverse)",
     (_NT, {"NUM_VERIFY": {"mod_a": 2, "mod_m": 3, "claimed_inverse": "0.5"}}), E, B),
    ("a claimed count written '3.0' is malformed, as '20.0' is",
     ("wordcraft", {"WORD_VERIFY": {"word": "cat", "claimed_letters": "3.0"}}), H, E),
    ("a claimed count written '3.5' stands as written",
     ("wordcraft", {"WORD_VERIFY": {"word": "cat", "claimed_letters": "3.5"}}), H, B),
    ("a claimed count true is malformed", ("wordcraft", {"WORD_VERIFY": {"word": "a", "claimed_letters": True}}), H, E),
    ("an atomic_number that is other text is malformed where an element claim is made",
     ("periodic_table", {"PT_VERIFY": {"atomic_number": "abc", "claimed_name": "iron"}}), I, E),
    ("m_l other text is malformed, where it read invalid", _quantum(True, m_l="abc"), B, E),
    ("m_l other text claimed invalid", _quantum(False, m_l="abc"), H, E),
    ("n true is malformed", _quantum(True, n=True, l=0, m_l=0), H, E),
]


@pytest.mark.parametrize("case,given,base,now", OTHER_MOVES, ids=[row[0] for row in OTHER_MOVES])
def test_the_readings_the_rule_moves_beyond_the_plans_list(case, given, base, now):
    assert verdict(*given) == now


def test_an_atomic_number_with_no_element_claim_is_not_read():
    assert verdict("periodic_table", {"PT_VERIFY": {"atomic_number": "abc"}}) == I
    from concordance.verifiers import periodic_table as PT
    assert PT.element(atomic_number=26.5) is None and PT.element(atomic_number=26)["symbol"] == "Fe"


# ── the eight roundings named in tests/integer_fields.json ────────────────────────────────────────────────────
def test_riemann_siegel_floors_a_real_height_by_its_own_formula():
    import mpmath as mp
    from concordance.verifiers import number_theory as NT
    for t in (600.37, 1000.5, 2500.25, 7777.77):
        assert abs(NT._rs_z(t) - float(mp.siegelz(t))) < t ** -0.75, t


def test_the_scan_grid_spans_a_real_interval_by_its_own_count():
    import mpmath as mp
    from concordance.verifiers import number_theory as NT
    from concordance.verifiers import riemann_accel
    if riemann_accel._numpy() is False:
        pytest.skip("the vectorised scan needs numpy")
    start, end = 600.3, 640.7
    assert NT._count_above_np(start, end, 0.05, None, None) == mp.nzeros(end) - mp.nzeros(start) == 30


def test_the_critical_line_reads_a_real_height_as_before():
    spec = {"NUM_VERIFY": {"critical_line_height": 100.25, "claimed_zeros_on_line": 29}}
    assert verdict(_NT, spec) == H
    assert "29 zeros on the line = N(T) = 29 in the strip" in detail(_NT, spec)
    assert verdict(_NT, {"NUM_VERIFY": {"critical_line_height": 100.25, "claimed_zeros_on_line": 30}}) == B


def test_each_named_field_is_a_rounding_of_this_step_and_none_reads_a_spec_value():
    named = [f for f in json.loads((ROOT / "tests" / "integer_fields.json").read_text(encoding="utf-8"))["fields"]
             if f["site"].split(":", 1)[0] in FILES]      # step fix-b names others, in the other files
    assert sorted(f["site"] for f in named) == sorted([
        "number_theory.py:_rs_z:int(a)#1", "number_theory.py:_count_above_np:math.ceil((b - start) / h)#1",
        "number_theory.py:_zeros_in_strip:int(T / 400)#1", "number_theory.py:_zeros_in_strip:round(N)#1",
        "number_theory.py:_zeros_on_line_checked:round(n_strip)#1",
        "number_theory.py:_zeros_on_line_checked.localise:round(nb - na)#1",
        "number_theory.py:verify_critical_line:round(n_strip)#1",
        "number_theory.py:verify_critical_line:round(n_strip)#2"])
    assert all(f["test"].split("::")[1] in globals() for f in named)


# ── every site this step closed has its case ──────────────────────────────────────────────────────────────────
def test_every_site_of_these_files_is_closed():
    """THE WALK finds nothing in the six files but the roundings tests/integer_fields.json names, and nothing that
    reads the shared readers' own conversion outside them."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("integer_probe", ROOT / "tools" / "integer_probe.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    walked = tool.walk()
    assert [k for k in walked["findings"] if k.split(":", 1)[0] in FILES] == []
    assert sorted(k for k in walked["excluded"] if k.split(":", 1)[0] in FILES) == sorted(
        f["site"] for f in json.loads((ROOT / "tests" / "integer_fields.json").read_text(encoding="utf-8"))["fields"]
        if f["site"].split(":", 1)[0] in FILES)
    assert walked["exempt"] == {"_integer.py:_exact_integer:int(value)#1": "int"}


def test_every_site_this_step_removed_from_the_walks_list_has_its_case():
    """Against the list HEAD holds (in a gate's worktree, the step's base): each site of these files the step removed
    is a case above, or a rounding tests/integer_fields.json names."""
    try:
        head = subprocess.run(["git", "-C", str(ROOT), "show", "HEAD:tests/integer_walk_known.json"],
                              capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("no git revision holds tests/integer_walk_known.json here")
    now = set(json.loads((ROOT / "tests" / "integer_walk_known.json").read_text(encoding="utf-8"))["sites"])
    removed = {s for s in json.loads(head.decode("utf-8"))["sites"]
               if s not in now and (s.split(":", 1)[0] in FILES or s in MOVED)}
    fields = json.loads((ROOT / "tests" / "integer_fields.json").read_text(encoding="utf-8"))["fields"]
    named = {f["site"] for f in fields}
    cased = (set(PROBED) | {row[0] for row in WALKED} | set(LOSSLESS) | set(BY_THEIR_HEIGHT) | AROUND_A_ROUNDING | MOVED
             | named | {'number_theory.py:verify_li_criterion:int(spec.get("li_to"))#1'})
    assert sorted(removed - cased) == []
