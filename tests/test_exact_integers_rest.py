"""Run 2026-11-11-exact-integers, step fix-b: THE RULE (src/concordance/verifiers/_integer.py) closes every other
lossy integer read in the verifiers, so THE PROBE and THE WALK each find nothing and both known lists are empty.

Step fix-a2 closed six files (tests/test_exact_integers.py); this step closes the forty others the lists held, and
mathematics' two last entries. Each site reads by one of THE RULE's three readings: an input by _exact_integer (a
fraction, a bool or other text is malformed: SYSTEM_ERROR), a claimed result by _claimed_integer (a fraction stands
as written: BROKEN), and whether a value is valid, as Shor's period, by _valid_integer (a fraction is invalid). A
value the code has already found whole, or the digits a pattern matched, reads through _exact_integer exactly as
int() read it; an int() or round() whose argument was already an int is dropped, and an int() of a sympy, numpy
or Fraction integer reads through operator.index or .numerator. A call that floors or rounds a real value the
check computes, as its own definition (Meeus's calendar, the ceilings of counts of whole things, a repeat count,
the Riemann-Siegel table), is named in tests/integer_fields.json with a test here whose fractional input reads as
the check should.

These tests hold: one case per site THE PROBE found in these files, the golden's true spec with the leaf varied, its
base reading beside it; each claimed leaf of those, written as a text with a fraction, BROKEN, and given as true,
SYSTEM_ERROR; a crafted case for each site the probe does not reach that an input can reach; the readings of the
sites closed with no lossy input, as before; the twenty named roundings; both lists empty; and every site this step
removed from the walk's list mapped to its case. Base readings were measured at main c6f7a1c.

Names the fix adds are read inside the tests, so the file collects at the step's base and each case reads red there
where its reading moves.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from concordance.derivation import verify, verify_derivation

ROOT = Path(__file__).resolve().parent.parent
H, B, E, I = "HOLDS", "BROKEN", "SYSTEM_ERROR", "INCOMPLETE"
SIX = ("combinatorics.py", "periodic_table.py", "atomic.py", "number_theory.py", "wordcraft.py",
       "operations_research.py")


def read(domain, spec):
    return verify_derivation([{"id": "c", "domain": domain, "spec": json.loads(json.dumps(spec))}])


def verdict(domain, spec):
    return read(domain, spec)["verdict"]


def detail(domain, spec):
    return str(read(domain, spec)["trail"][0].get("detail", ""))


VARIED = {"+0.25": lambda v: v + 0.25, "-0.25": lambda v: v - 0.25, "bool": bool,
          "text +0.25": lambda v: str(v + 0.25), "true": lambda v: True}


def _golden(check, leaf, variant):
    """The check's true spec in data/check_goldens.jsonl with one leaf varied, as the probe varies it (or written as
    a text with a fraction, or as true)."""
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


def _true(check):
    for line in (ROOT / "data" / "check_goldens.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line) if line.strip() else None
        if row and row["check"] == check:
            return row["domain"], row["true"]
    raise LookupError(check)


# ── every site THE PROBE found in these files ─────────────────────────────────────────────────────────────────
# One finding each: (check, leaf, variant, reading at the base, reading now).
PROBED = {
    'acoustics.py:verify_harmonic_frequency:int(n)#1':
        ('acoustics.decibel_ratio', 'ACOUS_VERIFY/harmonic_n', '+0.25', H, E),
    'architecture.py:verify_occupant_load:round(c)#1':
        ('architecture.floor_area_ratio', 'ARCH_VERIFY/claimed_occupant_count', '+0.25', H, B),
    'architecture.py:verify_occupant_load:round(c)#2':
        ('architecture.floor_area_ratio', 'ARCH_VERIFY/claimed_occupant_count', '+0.25', H, B),
    'architecture.py:verify_occupant_load:round(c)#3':
        ('architecture.floor_area_ratio', 'ARCH_VERIFY/claimed_occupant_count', '+0.25', H, B),
    'biology.py:verify_replicates:int(minimum)#1':
        ('biology.replicates', 'BIO_VERIFY/min_replicates', '+0.25', H, E),
    'biology.py:verify_replicates:int(n)#1':
        ('biology.replicates', 'BIO_VERIFY/n_replicates', '+0.25', H, E),
    'calendar_time.py:verify_leap_year:int(year)#1':
        ('calendar_time.day_of_week', 'CAL_VERIFY/year', '+0.25', H, E),
    'construction.py:verify_floor_tiles:int(c)#1':
        ('construction.floor_tiles', 'CONSTR_VERIFY/claimed_tile_count', '+0.25', H, B),
    'construction.py:verify_paint_coverage:int(c)#1':
        ('construction.paint_coverage', 'CONSTR_VERIFY/claimed_paint_cans', '+0.25', H, B),
    'cryptography.py:verify_key_strength:int(bits)#1':
        ('cryptography.key_strength', 'CRYPTO_VERIFY/key_bits', '+0.25', H, E),
    'cybersecurity.py:verify_password_entropy:int(_CHARSET_SIZES.get(str(charset), charset))#1':
        ('cybersecurity.cvss_severity', 'CYBER_VERIFY/charset_size', '+0.25', H, E),
    'cybersecurity.py:verify_password_entropy:int(length)#1':
        ('cybersecurity.cvss_severity', 'CYBER_VERIFY/password_length', '+0.25', H, E),
    'cybersecurity.py:verify_port_class:int(port)#1':
        ('cybersecurity.cvss_severity', 'CYBER_VERIFY/port_number', '+0.25', H, E),
    'cybersecurity.py:verify_subnet_hosts:int(claimed)#1':
        ('cybersecurity.cvss_severity', 'CYBER_VERIFY/claimed_host_count', '+0.25', H, B),
    'cybersecurity.py:verify_subnet_hosts:int(prefix)#1':
        ('cybersecurity.cvss_severity', 'CYBER_VERIFY/cidr_prefix', '+0.25', H, E),
    'ecology.py:verify_trophic_efficiency:int(lf)#1':                   # its own wholeness test refused a fraction
        ('ecology.trophic_efficiency', 'ECO_VERIFY/trophic_levels_up', '+0.25', E, E),
    'elliptic_curves.py:verify_l_value:int(spec.get("conductor"))#1':
        ('elliptic_curves.l_value', 'ELLIPTIC_VERIFY/conductor', '+0.25', H, E),
    'elliptic_curves.py:verify_l_value:int(spec.get("root_number"))#1':
        ('elliptic_curves.l_value', 'ELLIPTIC_VERIFY/root_number', '+0.25', H, E),
    'elliptic_curves.py:verify_l_value:int(spec["claimed_analytic_rank"])#1':
        ('elliptic_curves.l_value', 'ELLIPTIC_VERIFY/claimed_analytic_rank', '+0.25', H, B),
    'elliptic_curves.py:verify_l_value:int(x)#1':
        ('elliptic_curves.l_value', 'ELLIPTIC_VERIFY/a_invariants/0', '+0.25', H, E),
    'ephemeris.py:_jd_to_iso_date:math.floor(365.25 * C)#1':           # derived; named in integer_fields.json
        ('ephemeris.equinox_solstice', 'EPH_VERIFY/year', '-0.25', B, E),
    'ephemeris.py:verify_equinox_solstice:int(y)#1':
        ('ephemeris.equinox_solstice', 'EPH_VERIFY/year', '+0.25', H, E),
    'genetics.py:verify_orf_bounds:int(orf.get("end"))#1':
        ('genetics.orf_bounds', 'GENETICS_VERIFY/claimed_orf/end', '+0.25', H, B),
    'genetics.py:verify_orf_bounds:int(orf.get("start"))#1':
        ('genetics.orf_bounds', 'GENETICS_VERIFY/claimed_orf/start', '+0.25', H, B),
    'geography.py:verify_utm_zone:int(claimed)#1':
        ('geography.utm_zone', 'GEO_LOC_VERIFY/claimed_utm_zone', '+0.25', H, B),
    'geometry.py:verify_polygon_angle_sum:int(n)#1':
        ('geometry.polygon_interior_angle_sum', 'GEOM_VERIFY/polygon_n', '+0.25', H, E),
    'governance.py:verify_decision_timing:int(acted)#1':
        ('governance.decision_timing', 'acted_at_epoch', '+0.25', H, E),
    'governance.py:verify_decision_timing:int(created)#1':
        ('governance.decision_timing', 'created_epoch', '+0.25', H, E),
    'governance.py:verify_witness_count_consistency:int(top_count)#1':
        ('governance.witness_count_consistency', 'witness_count', '+0.25', H, B),
    'history_chronology.py:verify_century_assignment:int(claimed)#1':
        ('history_chronology.century_assignment', 'HIST_VERIFY/claimed_century', '+0.25', H, B),
    'history_chronology.py:verify_century_assignment:int(year)#1':
        ('history_chronology.century_assignment', 'HIST_VERIFY/year_CE', '+0.25', H, E),
    'history_chronology.py:verify_decade_assignment:int(claimed)#1':
        ('history_chronology.decade_assignment', 'HIST_VERIFY/claimed_decade_start', '+0.25', H, B),
    'history_chronology.py:verify_decade_assignment:int(year)#1':
        ('history_chronology.decade_assignment', 'HIST_VERIFY/year_CE', '+0.25', H, E),
    'history_chronology.py:verify_elapsed_years_bce_to_ce:int(claimed)#1':
        ('history_chronology.elapsed_years_bce_to_ce', 'HIST_VERIFY/claimed_elapsed', '+0.25', H, B),
    'history_chronology.py:verify_elapsed_years_bce_to_ce:int(from_bce)#1':
        ('history_chronology.elapsed_years_bce_to_ce', 'HIST_VERIFY/from_BCE', '+0.25', H, E),
    'history_chronology.py:verify_elapsed_years_bce_to_ce:int(to_ce)#1':
        ('history_chronology.elapsed_years_bce_to_ce', 'HIST_VERIFY/to_CE', '+0.25', H, E),
    'history_chronology.py:verify_era_classification:int(year)#1':
        ('history_chronology.era_classification', 'HIST_VERIFY/year', '+0.25', H, E),
    'history_chronology.py:verify_year_arithmetic:int(claimed)#1':
        ('history_chronology.year_arithmetic', 'HIST_VERIFY/claimed_elapsed_years', '+0.25', H, B),
    'history_chronology.py:verify_year_arithmetic:int(from_y)#1':
        ('history_chronology.year_arithmetic', 'HIST_VERIFY/from_year', '-0.25', H, E),
    'history_chronology.py:verify_year_arithmetic:int(to_y)#1':
        ('history_chronology.year_arithmetic', 'HIST_VERIFY/to_year', '+0.25', H, E),
    'information_theory.py:verify_hamming_distance:int(claimed)#1':
        ('info_theory.hamming_distance', 'INFO_VERIFY/claimed_hamming', '+0.25', H, B),
    'law.py:verify_constitutional_age_requirement:int(age)#1':
        ('law.constitutional_age_requirement', 'LAW_VERIFY/age', '+0.25', H, E),
    'molecular_geometry.py:verify_vsepr:int(bd)#1':
        ('molecular_geometry.vsepr', 'VSEPR_VERIFY/bonding_domains', '+0.25', H, E),
    'molecular_geometry.py:verify_vsepr:int(lp)#1':
        ('molecular_geometry.vsepr', 'VSEPR_VERIFY/lone_pairs', '+0.25', H, E),
    'music_theory.py:verify_equal_temperament_freq:int(n)#1':
        ('music.equal_temperament_freq', 'MUS_VERIFY/midi_note', '+0.25', H, E),
    'music_theory.py:verify_interval_semitones:int(claimed)#1':
        ('music.equal_temperament_freq', 'MUS_VERIFY/claimed_semitones', '+0.25', H, B),
    'networking.py:verify_subnet_host_count:int(claimed)#1':
        ('networking.cidr_membership', 'NET_VERIFY/claimed_usable_hosts', '+0.25', H, B),
    'networking.py:verify_subnet_host_count:int(prefix)#1':
        ('networking.cidr_membership', 'NET_VERIFY/subnet_prefix', '+0.25', H, E),
    'nuclear_physics.py:verify_binding_energy_per_nucleon:int(Af)#1':     # its own wholeness test refused a fraction
        ('nuclear_physics.binding_energy_per_nucleon', 'NUCLEAR_VERIFY/nucleon_count', '+0.25', E, E),
    'polynomial.py:_coeffs:int(v)#1':
        ('polynomial.rational_roots', 'POLY_VERIFY/coeffs/0', '+0.25', H, E),
    'probability.py:verify_binomial_mean:int(n)#1':
        ('probability.binomial_mean', 'PROB_VERIFY/binomial_n', '+0.25', H, E),
    'probability.py:verify_binomial_probability:int(k)#1':
        ('probability.binomial', 'PROB_VERIFY/binomial_k', '+0.25', H, E),
    'probability.py:verify_binomial_probability:int(n)#1':
        ('probability.binomial', 'PROB_VERIFY/binomial_n', '+0.25', H, E),
    'probability.py:verify_poisson_probability:int(k)#1':
        ('probability.poisson', 'PROB_VERIFY/poisson_k', '+0.25', H, E),
    'public_finance.py:verify_abatement_schedule:int(spec["claimed_pilot_year"])#1':
        ('public_finance.abatement_schedule', 'PUBFIN_VERIFY/claimed_pilot_year', '+0.25', H, E),
    'public_finance.py:verify_abatement_schedule:int(years)#1':
        ('public_finance.abatement_schedule', 'PUBFIN_VERIFY/abatement_years', '+0.25', H, E),
    'public_finance.py:verify_depreciated_value:int(year)#1':
        ('public_finance.depreciated_value', 'PUBFIN_VERIFY/year', '+0.25', H, E),
    'public_finance.py:verify_depreciated_value:int(year)#2':
        ('public_finance.depreciated_value', 'PUBFIN_VERIFY/year', '+0.25', H, E),
    'quantum_computing.py:verify_born_rule:int(idx)#1':
        ('quantum_computing.born_rule', 'QCOMP_VERIFY/outcome_index', '+0.25', H, E),
    'quantum_computing.py:verify_grover_iterations:int(N)#1':
        ('quantum_computing.grover_iterations', 'QCOMP_VERIFY/n_items', '+0.25', H, E),
    'quantum_computing.py:verify_grover_iterations:int(claimed)#1':
        ('quantum_computing.grover_iterations', 'QCOMP_VERIFY/claimed_grover_iterations', '+0.25', H, B),
    'quantum_computing.py:verify_shor_period:int(N)#1':
        ('quantum_computing.shor_period', 'QCOMP_VERIFY/shor_N', '+0.25', H, E),
    'quantum_computing.py:verify_shor_period:int(a)#1':
        ('quantum_computing.shor_period', 'QCOMP_VERIFY/shor_a', '+0.25', H, E),
    'quantum_computing.py:verify_shor_period:int(r)#1':                 # validity: a period with a fraction is none
        ('quantum_computing.shor_period', 'QCOMP_VERIFY/shor_r', '+0.25', H, B),
    'statistics.py:verify_trajectory:int(tj.get("successes"))#1':
        ('statistics.trajectory', 'STAT_VERIFY/trajectory/successes', '+0.25', H, E),
    'statistics.py:verify_trajectory:int(tj.get("trials"))#1':
        ('statistics.trajectory', 'STAT_VERIFY/trajectory/trials', '+0.25', H, E),
}


@pytest.mark.parametrize("site", sorted(PROBED))
def test_each_probed_site_reads_by_the_rule(site):
    check, leaf, variant, base, now = PROBED[site]
    assert verdict(*_golden(check, leaf, variant)) == now


# Each claimed leaf above: written as a text with a fraction it stands as written and reads BROKEN, and given as true
# it is malformed and reads SYSTEM_ERROR. claimed_pilot_year is no claimed result: it names the year a claimed payment
# is for, so it reads as an input (malformed), as the probe's row above shows. witness_count is the declared count the
# check holds against the named witnesses: a claimed result.
CLAIMED_LEAVES = sorted({(check, leaf) for check, leaf, _, _, _ in PROBED.values()
                         if any(part.startswith("claimed_") for part in leaf.split("/"))
                         and leaf != "PUBFIN_VERIFY/claimed_pilot_year"}
                        | {("governance.witness_count_consistency", "witness_count")})


@pytest.mark.parametrize("check,leaf", CLAIMED_LEAVES, ids=[f"{c} {l}" for c, l in CLAIMED_LEAVES])
def test_each_claimed_leaf_reads_a_text_with_a_fraction_broken_and_true_malformed(check, leaf):
    assert verdict(*_golden(check, leaf, "text +0.25")) == B
    assert verdict(*_golden(check, leaf, "true")) == E


def test_a_claimed_occupant_count_is_shown_as_written():
    """int(round(c)) rewrote the claim in the data and the detail: 108.25 was shown as 108."""
    spec = {"ARCH_VERIFY": {"floor_area_m2": 1000, "occupant_load_factor_m2_per_person": 9.3,
                            "claimed_occupant_count": 108.25}}
    assert verdict("architecture", spec) == B
    assert detail("architecture", spec).endswith("= 108 occupants, claimed 108.25")


# ── the sites the probe does not reach, each with an input that reached a lossy call at the base ──────────────
START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
BSD = {"a_invariants": [0, -1, 1, -10, -20], "conductor": 11, "root_number": 1, "tamagawa_product": 5,
       "torsion_order": 5, "sha_order": 1, "inputs_source": "Cremona's tables / LMFDB 11.a3", "claimed_bsd_holds": True}
GAME = {"claimed_is_nash": True, "row_payoff_A": [[3, 0], [5, 1]], "col_payoff_B": [[3, 5], [0, 1]], "profile": [1, 1]}
GOV = {"scope": "local", "created_epoch": 1700000000, "acted_at_epoch": 1700003600}
RANK = {"returned_ids": ["c_a", "c_b", "c_c"], "target_id": "c_c"}
MINIMAL = {"formula": "(A & B) | (A & ~B)", "claimed_minimal": "A", "variables": ["A", "B"]}
ECO = {"energy_input": 10000.0, "trophic_levels_up": 2, "claimed_energy_output": 100.0}
NUC = {"mass_defect_amu": 0.5284, "nucleon_count": 56, "claimed_binding_energy_MeV_per_nucleon": 8.79}


def _shor(r, claimed_valid):
    return ("quantum_computing", {"QCOMP_VERIFY": {"shor_a": 7, "shor_N": 15, "shor_r": r,
                                                   "claimed_period_valid": claimed_valid}})


_SHOR = "quantum_computing.py:verify_shor_period:int(r)#1"
_EL, _GT = "elliptic_curves", "game_theory"
# (site, case, (domain, spec), reading at the base, reading now)
CRAFTED = [
    ("chess.py:verify_position:int(claimed)#1", "claimed balance 0.5",
     ("chess", {"CHESS_VERIFY": {"fen": START, "claim": "material", "claimed_balance": 0.5}}), H, B),
    ("chess.py:verify_position:int(claimed)#1", "claimed balance true",
     ("chess", {"CHESS_VERIFY": {"fen": START, "claim": "material", "claimed_balance": True}}), B, E),
    ('elliptic_curves.py:verify_bsd_formula:int(spec.get("tamagawa_product"))#1', "tamagawa_product 5.5",
     (_EL, {"ELLIPTIC_VERIFY": dict(BSD, tamagawa_product=5.5)}), H, E),
    ('elliptic_curves.py:verify_bsd_formula:int(spec.get("torsion_order"))#1', "torsion_order 5.25",
     (_EL, {"ELLIPTIC_VERIFY": dict(BSD, torsion_order=5.25)}), H, E),
    ('elliptic_curves.py:verify_bsd_formula:int(spec.get("sha_order", 1))#1', "sha_order 1.5",
     (_EL, {"ELLIPTIC_VERIFY": dict(BSD, sha_order=1.5)}), H, E),
    ('elliptic_curves.py:verify_bsd_formula:int(spec.get("conductor"))#1', "conductor 11.5",
     (_EL, {"ELLIPTIC_VERIFY": dict(BSD, conductor=11.5)}), H, E),
    ('elliptic_curves.py:verify_bsd_formula:int(spec.get("root_number"))#1', "root_number true",
     (_EL, {"ELLIPTIC_VERIFY": dict(BSD, root_number=True)}), H, E),
    ("elliptic_curves.py:verify_bsd_formula:int(x)#1", "a_invariants 0.25",
     (_EL, {"ELLIPTIC_VERIFY": dict(BSD, a_invariants=[0.25, -1, 1, -10, -20])}), H, E),
    ("formal_logic.py:verify_minimal_form:int(stated)#1", "claimed_minimal_terms 1.5",
     ("formal_logic", {"LOGIC_VERIFY": dict(MINIMAL, claimed_minimal_terms=1.5)}), H, B),
    ("formal_logic.py:verify_minimal_form:int(stated)#1", "claimed_minimal_terms 'one'",
     ("formal_logic", {"LOGIC_VERIFY": dict(MINIMAL, claimed_minimal_terms="one")}), I, E),
    ("game_theory.py:_index:int(f)#1", "profile [1, true]", (_GT, {"GAME_VERIFY": dict(GAME, profile=[1, True])}), H, E),
    ("game_theory.py:_index:int(f)#1", "profile [1, '1.0']", (_GT, {"GAME_VERIFY": dict(GAME, profile=[1, "1.0"])}), H, E),
    ("governance.py:verify_decision_timing:int(override)#1", "wait_window_seconds 60.5",
     ("governance", dict(GOV, wait_window_seconds=60.5)), H, E),
    ("retrieval.py:verify_rank_of_target:int(claimed)#1", "claimed rank 3.5",
     ("retrieval", {"RET_VERIFY": dict(RANK, claimed_rank=3.5)}), H, B),
    ("retrieval.py:verify_no_false_silence:int(claimed_n)#1", "claimed result count 0.5",
     ("retrieval", {"RET_VERIFY": {"claimed_result_count": 0.5, "corpus_contains_match": False, "query": "q"}}), H, B),
    ('spectral.py:verify_diagonalize:int(a["power"])#1', "power 2.5",
     ("spectral", {"SPECTRAL_VERIFY": {"matrix": [[2, 0], [0, 3]], "power": 2.5}}), H, E),
    ('spectral.py:verify_diagonalize:int(a["power"])#1', "power true",
     ("spectral", {"SPECTRAL_VERIFY": {"matrix": [[2, 0], [0, 3]], "power": True}}), H, E),
    ("ecology.py:verify_trophic_efficiency:int(lf)#1", "trophic_levels_up true",
     ("ecology", {"ECO_VERIFY": dict(ECO, trophic_levels_up=True)}), B, E),
    ("ecology.py:verify_trophic_efficiency:int(lf)#1", "trophic_levels_up '2.0'",
     ("ecology", {"ECO_VERIFY": dict(ECO, trophic_levels_up="2.0")}), H, E),
    ("nuclear_physics.py:verify_binding_energy_per_nucleon:int(Af)#1", "nucleon_count '56.0'",
     ("nuclear_physics", {"NUCLEAR_VERIFY": dict(NUC, nucleon_count="56.0")}), H, E),
    ("nuclear_physics.py:verify_binding_energy_per_nucleon:int(Af)#1", "nucleon_count true",
     ("nuclear_physics", {"NUCLEAR_VERIFY": dict(NUC, nucleon_count=True)}), B, E),
    # Shor's period is the value whose validity is claimed (THE RULE's validity reading): 4.5 is no period, where
    # int() read it as the valid period 4. So a claim that it is invalid is this step's one new pass, BROKEN -> HOLDS.
    (_SHOR, "r 4 claimed valid", _shor(4, True), H, H),
    (_SHOR, "r 4.5 claimed valid", _shor(4.5, True), H, B),
    (_SHOR, "r 4.5 claimed invalid", _shor(4.5, False), B, H),
    (_SHOR, "r true claimed invalid", _shor(True, False), H, E),
    (_SHOR, "r true claimed valid", _shor(True, True), B, E),
]


@pytest.mark.parametrize("site,case,given,base,now", CRAFTED, ids=[f"{row[0]} {row[1]}" for row in CRAFTED])
def test_each_crafted_case_reads_by_the_rule(site, case, given, base, now):
    assert verdict(*given) == now


def test_the_determinism_check_reads_its_trial_count_by_the_rule():
    """computer_science.py:verify_determinism:int(spec.get("trials", 3))#1: 2.5 trials ran as 2 at the base."""
    from concordance.verifiers import computer_science as CS
    code = "def f(x):\n    return x * 2\n"
    spec = {"code": code, "function_name": "f", "test_cases": [{"args": [1]}]}
    r = CS.verify_determinism(dict(spec, trials=2.5))
    assert (str(r.status), r.detail) == ("ERROR", "trials is not a whole number: 2.5")
    assert str(CS.verify_determinism(dict(spec, trials=3)).status) == "CONFIRMED"


def test_a_polynomial_reads_its_coefficients_by_the_rule():
    """polynomial.py:rational_roots:int(v)#1 and _divisors:int(n)#1: [1, -5.5, 6] was read as [1, -5, 6] (roots 2, 3)."""
    from concordance.verifiers import polynomial as PO
    with pytest.raises(ValueError, match=r"coeffs is not a whole number: -5\.5"):
        PO.rational_roots([1, -5.5, 6])
    with pytest.raises(ValueError):
        PO._divisors(6.5)
    assert [str(r) for r in PO.rational_roots([1, -5, 6])] == ["2", "3"] and PO._divisors(6) == [1, 2, 3, 6]


def test_a_word_count_claim_reads_by_the_rule(monkeypatch):
    """linguistics.py:verify_word_count:int(claimed_count)#1 and int(actual)#1, with the corpus stubbed: a claimed
    count of 3.5 was read as 3 at the base; the corpus's own count reads exactly."""
    from concordance.verifiers import linguistics as LI
    monkeypatch.setattr(LI, "_word_study", lambda strongs: {"occurrence_count": 3.0})
    monkeypatch.setattr(LI, "_layer0_unavailable", lambda result: False)
    def status(claimed):
        return str(LI.verify_word_count("G26", claimed).status)
    assert status(3) == "CONFIRMED" and status(3.5) == "MISMATCH" and status(True) == "ERROR"
    assert "claimed 3.5" in LI.verify_word_count("G26", 3.5).detail


# ── the sites closed with no input able to reach them with a fraction or a bool ───────────────────────────────
_EQ = ("chemistry", {"CHEM_VERIFY": {"equation": "Ca(OH)2 + 2 HCl -> CaCl2 + 2 H2O"}})
_ION = ("chemistry", {"CHEM_VERIFY": {"equation": "Fe^3+ + 3 OH^- -> Fe(OH)3"}})
_DOC = _true("doc_validation.isbn10")
_EPH = _true("ephemeris.equinox_solstice")
_EL1 = _true("elliptic_curves.l_value")
LOSSLESS = {           # each reads HOLDS, as at the base
    "agriculture.py:_zone_to_int:int(m.group(1))#1": _true("agriculture.hardiness_zone_match"),
    "chemistry.py:_parse_charge:int(digits)#1": _ION,
    "chemistry.py:_parse_formula:int(mdigits)#1": _EQ,
    "chemistry.py:_parse_formula:int(ndigits)#1": _EQ,
    "chemistry.py:_split_term:int(m.group(1))#1": _EQ,
    "chemistry.py:_nullspace_positive_integer:int(v * den_lcm)#1": _true("chemistry.equation"),
    'chess.py:verify_position:int(mat.get("balance"))#1':
        ("chess", {"CHESS_VERIFY": {"fen": START, "claim": "material", "claimed_balance": 0}}),
    "document_validation.py:_isbn10_check:int(ch)#1": _DOC,
    "document_validation.py:_isbn13_check:int(ch)#1": _DOC,
    "document_validation.py:_luhn_check:int(ch)#1": _DOC,
    "document_validation.py:_ean_check:int(ch)#1": _DOC,
    "elliptic_curves.py:_primes:int(n ** 0.5)#1": _EL1,
    "elliptic_curves.py:verify_l_value:int(10 * math.sqrt(N))#1": _EL1,
    "elliptic_curves.py:verify_bsd_formula:int(10 * math.sqrt(N))#1": ("elliptic_curves", {"ELLIPTIC_VERIFY": BSD}),
    "ephemeris.py:verify_equinox_solstice:int(x)#1": _EPH,
    "ephemeris.py:_jd_to_iso_date:int(math.floor(day_f))#1": _EPH,
    "ephemeris.py:_jd_to_iso_date:int(E - 1 if E < 14 else E - 13)#1": _EPH,
    "ephemeris.py:_jd_to_iso_date:int(C - 4716 if month > 2 else C - 4715)#1": _EPH,
    "geography.py:verify_utm_zone:int(((lf + 180.0) // 6) + 1)#1": _true("geography.utm_zone"),
    "music_theory.py:_parse_note:int(s[octave_idx:])#1": _true("music.interval_semitones"),
    "spectral.py:verify_fourier_convolution:int(N)#1":
        ("spectral", {"SPECTRAL_VERIFY": {"a": [1, 2], "b": [1, 1], "claimed_convolution": [1, 3, 2]}}),
    "governance.py:verify_decision_timing:int(override)#1": ("governance", dict(GOV, wait_window_seconds=60)),
    "game_theory.py:_index:int(f)#1": (_GT, {"GAME_VERIFY": GAME}),
}


@pytest.mark.parametrize("site", sorted(LOSSLESS))
def test_a_site_closed_without_a_lossy_input_reads_as_before(site):
    assert verdict(*LOSSLESS[site]) == H


def test_the_equinox_tolerance_is_a_real_number_and_reads_as_before():
    """ephemeris.py:verify_equinox_solstice:int(clamp_tol(spec, "tolerance_days", 2))#1: the day difference it bounds
    is whole, so 1.5 days reads as 1 did."""
    spec = {"EPH_VERIFY": {"year": 2024, "event": "summer_solstice", "claimed_event_iso": "2024-06-22"}}
    assert verdict("ephemeris", spec) == H
    assert verdict("ephemeris", {"EPH_VERIFY": dict(spec["EPH_VERIFY"], tolerance_days=1.5)}) == B
    assert verdict("ephemeris", {"EPH_VERIFY": dict(spec["EPH_VERIFY"], tolerance_days=1)}) == B


MATHEMATICS = [        # mathematics' estimators and readers read exactly as before: operator.index, never int()
    ({"expr_a": "1/(x**2 - y**2)", "expr_b": "1/((x - y)*(x + y))"}, H),     # _weight, _term_estimate
    ({"expr_a": "(2/3)**5", "expr_b": "32/243"}, H),                          # _power_bits
    ({"expr_a": "1.5e3", "expr_b": "1500"}, H),                               # _Reader._number
]


@pytest.mark.parametrize("params,want", MATHEMATICS, ids=[p["expr_a"] for p, _ in MATHEMATICS])
def test_mathematics_reads_its_own_integers_as_before(params, want):
    assert verify({"mode": "equality", "params": dict(params, variables={})})["verdict"] == want


def test_the_numpy_scan_reads_its_own_floors_as_before():
    """riemann_accel.py:_np_z:int(m.max())#1: m is the int64 array of floors, read through operator.index."""
    from concordance.verifiers import riemann_accel as RA
    if RA._numpy() is False:
        pytest.skip("numpy absent")
    ts = [600.0 + 0.37 * i for i in range(50)]
    assert max(abs(float(a) - b) for a, b in zip(RA._np_z(ts), RA._py_z(ts))) < 1e-9


def test_the_si_units_parser_reads_its_exponent_digits_as_before():
    """si_units.py:_atom:int(m.group(2) or 1)#1."""
    from concordance.verifiers import si_units as SI
    assert SI.parse("m^3") == ({"m": 3}, 1.0) and SI.convert(1.0, "km^2", "m^2") == 1000000.0


def test_the_stated_precision_reads_its_exponent_digits_as_before():
    """base.py:stated_precision:int(m.group(3) or 0)#1."""
    from concordance.verifiers import base as BA
    assert [BA.stated_precision(x) for x in ("2.5e-3", "1.20E+4", "300", "7")] == [
        (2, 5e-05), (3, 50.0), (1, 50.0), (1, 0.5)]


# the sites closed by their function's own input reading, each in a case above
BY_THEIR_INPUT = {
    "architecture.py:verify_occupant_load:int(round(c))#1": "architecture.py:verify_occupant_load:round(c)#1",
    "architecture.py:verify_occupant_load:int(round(c))#2": "architecture.py:verify_occupant_load:round(c)#2",
    "architecture.py:verify_occupant_load:int(round(c))#3": "architecture.py:verify_occupant_load:round(c)#3",
    "architecture.py:verify_occupant_load:int(round(c))#4": "architecture.py:verify_occupant_load:round(c)#3",
    "architecture.py:verify_occupant_load:round(c)#4": "architecture.py:verify_occupant_load:round(c)#3",
    "ecology.py:verify_trophic_efficiency:int(lf)#2": "ecology.py:verify_trophic_efficiency:int(lf)#1",
    "ecology.py:verify_trophic_efficiency:int(lf)#3": "ecology.py:verify_trophic_efficiency:int(lf)#1",
    "history_chronology.py:verify_century_assignment:math.ceil(y / 100)#1":
        "history_chronology.py:verify_century_assignment:int(year)#1",
    "nuclear_physics.py:verify_binding_energy_per_nucleon:int(Af)#2":
        "nuclear_physics.py:verify_binding_energy_per_nucleon:int(Af)#1",
    "quantum_computing.py:verify_grover_iterations:math.floor(math.pi * math.sqrt(n) / 4)#1":
        "quantum_computing.py:verify_grover_iterations:int(N)#1",
    "polynomial.py:_divisors:int(n)#1": "polynomial.py:_coeffs:int(v)#1",
    "polynomial.py:rational_roots:int(v)#1": "polynomial.py:_coeffs:int(v)#1",
    "computer_science.py:verify_determinism:int(spec.get(\"trials\", 3))#1": "test_the_determinism_check_reads_its_trial_count_by_the_rule",
    "linguistics.py:verify_word_count:int(claimed_count)#1": "test_a_word_count_claim_reads_by_the_rule",
    "linguistics.py:verify_word_count:int(actual)#1": "test_a_word_count_claim_reads_by_the_rule",
    "ephemeris.py:verify_equinox_solstice:int(clamp_tol(spec, \"tolerance_days\", 2))#1":
        "test_the_equinox_tolerance_is_a_real_number_and_reads_as_before",
    "mathematics.py:_power_bits:int(base.p)#1": "test_mathematics_reads_its_own_integers_as_before",
    "mathematics.py:_power_bits:int(base.q)#1": "test_mathematics_reads_its_own_integers_as_before",
    "mathematics.py:_Reader._number:int(exponent.group(1))#1": "test_mathematics_reads_its_own_integers_as_before",
    "mathematics.py:_term_estimate:int(product)#1": "test_mathematics_reads_its_own_integers_as_before",
    "mathematics.py:_weight:int(value.exp)#1": "test_mathematics_reads_its_own_integers_as_before",
    "mathematics.py:_weight:int(max(abs(value.p), value.q))#1": "test_mathematics_reads_its_own_integers_as_before",
    "mathematics.py:verify_number_theory:int(_fact(n))#1": "tests/test_exact_integers.py::test_mathematics_reads_exactly_as_before",
    "mathematics.py:verify_number_theory:int(_binom(n, k))#1": "tests/test_exact_integers.py::test_mathematics_reads_exactly_as_before",
    "riemann_accel.py:_np_z:int(m.max())#1": "test_the_numpy_scan_reads_its_own_floors_as_before",
    "si_units.py:_atom:int(m.group(2) or 1)#1": "test_the_si_units_parser_reads_its_exponent_digits_as_before",
    "base.py:stated_precision:int(m.group(3) or 0)#1": "test_the_stated_precision_reads_its_exponent_digits_as_before",
    # moved into a helper of its own, named in tests/integer_fields.json under the helper's site
    "computer_science.py:verify_runtime_complexity:int(target_s / elapsed)#1": "test_the_repeat_factor_is_whole_windows_plus_one",
    "riemann_accel.py:_c_z:int((tmax / _TWO_PI) ** 0.5)#1": "test_the_c_table_covers_every_main_sum_below_its_height",
}


# ── the twenty roundings named in tests/integer_fields.json ───────────────────────────────────────────────────
def test_the_occupant_load_rounds_a_real_quotient_up():
    spec = {"ARCH_VERIFY": {"floor_area_m2": 100.5, "occupant_load_factor_m2_per_person": 9.3}}
    assert verdict("architecture", {"ARCH_VERIFY": dict(spec["ARCH_VERIFY"], claimed_occupant_count=11)}) == H
    assert verdict("architecture", {"ARCH_VERIFY": dict(spec["ARCH_VERIFY"], claimed_occupant_count=10)}) == B


def test_the_power_analysis_rounds_the_required_n_up():
    """n = ceil(2 ((z_a/2 + z_b) / d)^2) + 1: 62.79 at d 0.5, so 64 per group. Read through the verifier itself, not
    the 8 s verify window: its first read imports scipy.stats, which a cold Python 3.12 took past the window."""
    from concordance.verifiers import biology as BI
    def n_per_group(n):
        return str(BI.verify_sample_size_powered({"power_analysis": {"effect_size": 0.5, "n_per_group": n}}).status)
    assert n_per_group(64) == "CONFIRMED" and n_per_group(63) == "MISMATCH"


def test_the_repeat_factor_is_whole_windows_plus_one():
    from concordance.verifiers import computer_science as CS
    assert CS._repeat_factor(0.2, 0.03) == 7 and CS._repeat_factor(0.2, 0.15) == 2 and CS._repeat_factor(0.2, 0.0) == 10


def test_paint_and_tiles_round_a_real_quotient_up():
    assert verdict("construction", {"CONSTR_VERIFY": {"paint_area_m2": 101.5, "coverage_m2_per_can": 10,
                                                      "claimed_paint_cans": 11}}) == H
    tiles = {"tile_area_m2": 20.5, "tile_size_m2": 0.25, "waste_factor": 0.1}      # 82, then 90.2: 91 tiles
    assert verdict("construction", {"CONSTR_VERIFY": dict(tiles, claimed_tile_count=91)}) == H
    assert verdict("construction", {"CONSTR_VERIFY": dict(tiles, claimed_tile_count=90)}) == B


def test_the_julian_day_floors_as_meeus_writes_it():
    """Meeus, Astronomical Algorithms, examples 7.a and 7.b, with the day's fraction: 1957 Oct 4.81 (Gregorian) is
    JD 2436116.31 and 333 Jan 27.5 (Julian) is JD 1842713.0; each JD reads back as its calendar date."""
    from concordance.verifiers import ephemeris as EP
    assert abs(EP._julian_day(1957, 10, 4.81) - 2436116.31) < 1e-6 and EP._jd_to_iso_date(2436116.31) == "1957-10-04"
    assert abs(EP._julian_day(333, 1, 27.5) - 1842713.0) < 1e-6 and EP._jd_to_iso_date(1842713.0) == "0333-01-27"
    assert EP._jd_to_iso_date(2451544.75) == "2000-01-01"


def test_the_issuance_par_rounds_up_to_its_step():
    """1,000,000 net at 1.5% cost grosses up to 1,015,228.43, rounded up to the 5,000 step: 1,020,000."""
    spec = {"net_proceeds": 1000000, "issuance_cost_pct": 0.015, "round_up_to": 5000}
    assert verdict("public_finance", {"PUBFIN_VERIFY": dict(spec, claimed_par=1020000)}) == H
    assert verdict("public_finance", {"PUBFIN_VERIFY": dict(spec, claimed_par=1015000)}) == B


def test_the_c_table_covers_every_main_sum_below_its_height():
    import math
    from concordance.verifiers import riemann_accel as RA
    assert RA._table_size(1000.5) == 13 and RA._table_size(20.0) == 2
    for tmax in (600.37, 1000.5, 2500.25):
        longest = max(math.floor(math.sqrt(t / RA._TWO_PI)) for t in (tmax * k / 100 for k in range(1, 101)))
        assert longest < RA._table_size(tmax)


# ── both lists empty, and every site removed has its case ─────────────────────────────────────────────────────
def test_both_known_lists_are_empty():
    probe = json.loads((ROOT / "tests" / "integer_probe_known.json").read_text(encoding="utf-8"))["findings"]
    walk = json.loads((ROOT / "tests" / "integer_walk_known.json").read_text(encoding="utf-8"))["sites"]
    assert probe == [] and walk == []


def test_every_site_this_step_removed_from_the_walks_list_has_its_case():
    """Against the list HEAD holds (in a gate's worktree, the step's base): each site the step removed is a case
    above, or a rounding tests/integer_fields.json names, or one fix-a2's tests hold."""
    try:
        head = subprocess.run(["git", "-C", str(ROOT), "show", "HEAD:tests/integer_walk_known.json"],
                              capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("no git revision holds tests/integer_walk_known.json here")
    now = set(json.loads((ROOT / "tests" / "integer_walk_known.json").read_text(encoding="utf-8"))["sites"])
    removed = {s for s in json.loads(head.decode("utf-8"))["sites"] if s not in now and s.split(":", 1)[0] not in SIX}
    fields = json.loads((ROOT / "tests" / "integer_fields.json").read_text(encoding="utf-8"))["fields"]
    cased = (set(PROBED) | {row[0] for row in CRAFTED} | set(LOSSLESS) | set(BY_THEIR_INPUT)
             | {f["site"] for f in fields})
    assert sorted(removed - cased) == []


def test_each_site_closed_by_its_input_names_a_case_or_a_test():
    assert all(v in PROBED or v in globals() or v.startswith("tests/test_exact_integers.py::")
               for v in BY_THEIR_INPUT.values())
