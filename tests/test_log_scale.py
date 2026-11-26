"""ONE LAW, MANY CONSTANTS: level = k * log_b(value / reference), written once in verifiers/log_scale.py.

Fifteen computations in eleven verifiers were the same law written out separately, each with its own constant:
decibels (k = 10 or 20), return loss (k = -20), exposure value and password strength (base 2), half-lives elapsed
(k = -1, base 2), radiometric age (k = -T/ln 2), the Nernst, Goldman and electrochemical potentials (k = RT/zF), the
Weber-Fechner law, the Clausius-Clapeyron step (k = R/L), Boltzmann entropy (k = k_B) and the Magnus dew-point term.
Each now calls log_scale.level with its own k, base and reference and records log_scale.law(...) in its data, and
the sealed record carries it, so a receipt names the law and the constants that grounded the check.

Pinned here: the shared law is the same arithmetic bit for bit; every function names the law with its own constants
and computes exactly what its old formula computed; the seal carries the law, and a record from a check that does
not use it is byte-for-byte what it was.
"""
from __future__ import annotations

import math
import random

import pytest

from concordance import receipts
from concordance.derivation import verify_derivation
from concordance.verifiers import (acoustics, archaeology, astronomy, chemistry, cybersecurity, ecology, electrical,
                                   electrochemistry, geology, information_theory, log_scale as LS, meteorology,
                                   music_theory, neuroscience, nuclear_physics, optics, photography, photonics,
                                   quantum_computing, sports_analytics, thermal_scale, thermodynamics)


def test_the_shared_law_is_the_same_arithmetic_bit_for_bit():
    r = random.Random(20261125)
    for _ in range(4000):
        v, ref, k = 10 ** r.uniform(-150, 150), 10 ** r.uniform(-150, 150), r.uniform(-50, 50)
        assert LS.level(v, ref, k=k, base=10) == k * math.log10(v / ref)
        assert LS.level(v, ref, k=k, base=2) == k * math.log2(v / ref)
        assert LS.level(v, ref, k=k, base=LS.E) == k * math.log(v / ref)
        assert LS.level(v, base=10) == math.log10(v)
        assert LS.level(v, k=-1.0, base=2) == -math.log2(v)
    big = 10 ** 400                      # an exact integer reaches the logarithm whole (big / 1.0 would overflow)
    assert LS.level(big, k=3, base=2) == 3 * math.log2(big)
    assert LS.level(big, base=LS.E) == math.log(big)


def test_a_base_the_law_does_not_hold_is_refused():
    with pytest.raises(KeyError):
        LS.level(2.0, base=3)


def _law(k, base, reference=None):
    return {"form": "log_scale", "law": "level = k * log_b(value / reference)", "base": base, "k": k,
            "reference": 1 if reference is None else reference}


_R, _F = neuroscience._R, neuroscience._F
_T14 = archaeology._C14_HALFLIFE
_z = complex(100.0, 0.0) / 50.0
_mag = abs((_z - 1) / (_z + 1))
_ghk = dict(p_k=1.0, p_na=0.04, p_cl=0.45, k_out=5.0, k_in=140.0, na_out=145.0, na_in=15.0, cl_out=110.0, cl_in=10.0)
_num = 1.0 * 5.0 + 0.04 * 145.0 + 0.45 * 10.0
_den = 1.0 * 140.0 + 0.04 * 15.0 + 0.45 * 110.0

# (function, a spec, the data key of its value, the OLD formula computed here independently, the law it must name)
VOICES = [
    (acoustics.verify_decibel_ratio, {"value": 200.0, "reference": 2.0, "claimed_db": 40.0, "db_kind": "pressure"},
     "actual_db", 20.0 * math.log10(200.0 / 2.0), _law(20.0, 10, 2.0)),
    (optics.verify_fiber_attenuation, {"power_in_mw": 1.0, "power_out_mw": 0.5, "claimed_loss_db": 3.0103},
     "actual_loss_db", 10.0 * math.log10(1.0 / 0.5), _law(10.0, 10, 0.5)),
    (electrical.verify_reflection_coefficient, {"z_real_ohm": 100.0, "z_imag_ohm": 0.0, "z0_ohm": 50.0,
                                                "claimed_return_loss_db": 9.542},
     "return_loss_db", -20.0 * math.log10(_mag), _law(-20.0, 10)),
    (neuroscience.verify_nernst_potential, {"ion_z": 1, "c_out_mM": 5.0, "c_in_mM": 140.0, "claimed_mV": -89.0},
     "E_mV", (_R * 310.0 / (1.0 * _F)) * math.log(5.0 / 140.0) * 1000.0, _law(_R * 310.0 / (1.0 * _F), "e", 140.0)),
    (neuroscience.verify_goldman, {**_ghk, "claimed_vm_mV": (_R * 310.0 / _F) * math.log(_num / _den) * 1000.0},
     "Vm_mV", (_R * 310.0 / _F) * math.log(_num / _den) * 1000.0, _law(_R * 310.0 / _F, "e", _den)),
    (neuroscience.verify_weber_fechner, {"stimulus": 100.0, "reference": 10.0, "weber_k": 2.0, "claimed_sensation": 4.605},
     "S", 2.0 * math.log(100.0 / 10.0), _law(2.0, "e", 10.0)),
    (electrochemistry.verify_nernst, {"e0_V": 1.10, "n_electrons": 2, "reaction_quotient": 0.01, "claimed_E_V": 1.159},
     "E_V", 1.10 - (_R * 298.15 / (2.0 * _F)) * math.log(0.01), _law(_R * 298.15 / (2.0 * _F), "e")),
    (archaeology.verify_radiocarbon, {"fraction_remaining": 0.5, "claimed_age_years": 5730.0},
     "age_years", -(_T14 / archaeology._LN2) * math.log(0.5), _law(-(_T14 / archaeology._LN2), "e")),
    (archaeology.verify_radiometric, {"fraction_remaining_iso": 0.25, "half_life_years": 1.25e9, "claimed_age_years_iso": 2.5e9},
     "age_years", -(1.25e9 / archaeology._LN2) * math.log(0.25), _law(-(1.25e9 / archaeology._LN2), "e")),
    (archaeology.verify_half_lives_elapsed, {"fraction_for_halflives": 0.25, "claimed_half_lives": 2.0},
     "half_lives", -math.log2(0.25), _law(-1.0, 2)),
]


@pytest.mark.parametrize("fn, spec, key, old, law", VOICES, ids=[v[0].__name__ for v in VOICES])
def test_each_function_names_the_law_and_computes_what_its_old_formula_did(fn, spec, key, old, law):
    r = fn(dict(spec))
    assert r.status == "CONFIRMED", (r.status, r.detail)
    assert r.data[key] == old                     # bit for bit
    assert r.data["shared_law"] == law


def test_the_functions_that_keep_their_value_elsewhere_name_the_law_too():
    ev = photography.verify_exposure_value({"f_number": 8.0, "shutter_seconds": 0.004, "claimed_exposure_value": 13.97})
    assert ev.status == "CONFIRMED" and ev.data["shared_law"] == _law(1.0, 2, 0.004)
    assert photography._ev(8.0, 0.004) == math.log2((8.0 * 8.0) / 0.004)
    rec = photography.verify_reciprocity_equivalent({"settings_a": [8.0, 1 / 125], "settings_b": [5.6, 1 / 250],
                                                     "claimed_equivalent": True})
    assert rec.data["shared_law"] == _law(1.0, 2)
    pw = cybersecurity.verify_password_entropy({"password_length": 16, "charset_size": 94, "claimed_entropy_bits": 104.87})
    assert pw.status == "CONFIRMED" and pw.data["shared_law"] == _law(16, 2)
    dp = meteorology.verify_dew_point({"temperature_c": 25.0, "relative_humidity_pct": 60.0, "claimed_dew_point_c": 16.7})
    assert dp.data["shared_law"] == _law(1.0, "e", 100.0)
    cc = thermodynamics.verify_clausius_clapeyron({"latent_heat_J_per_mol": 40650.0, "t_ref_K": 373.15, "p_ref": 101325.0,
                                                   "pressure": 70000.0, "claimed_boiling_point_K": 363.0})
    assert cc.data["shared_law"] == _law(thermodynamics._R / 40650.0, "e", 101325.0)
    w = 1e23
    assert thermal_scale.boltzmann_entropy_J_per_K(w) == thermal_scale._kB * math.log(w)
    be = thermodynamics.verify_boltzmann_entropy({"microstates_W": w,
                                                  "claimed_entropy_J_per_K": thermal_scale._kB * math.log(w)})
    assert be.status == "CONFIRMED" and be.data["shared_law"] == _law(thermal_scale._kB, "e")


def test_the_attenuation_branch_is_not_the_log_law_and_does_not_claim_it():
    r = optics.verify_fiber_attenuation({"attenuation_db_per_km": 0.2, "length_km": 10.0, "claimed_loss_db": 2.0})
    assert r.status == "CONFIRMED" and "shared_law" not in r.data


def _sealed_record(step):
    res = verify_derivation([step])
    return res, receipts.record_from_derivation(res, domain=step["domain"])


def test_the_seal_carries_the_law_and_a_record_without_it_is_unchanged():
    res, rec = _sealed_record({"id": "db", "domain": "acoustics", "spec": {"ACOUS_VERIFY": {
        "value": 200.0, "reference": 2.0, "claimed_db": 40.0, "db_kind": "pressure"}}})
    assert res["verdict"] == "HOLDS"
    assert rec.verifier_results[0].data["shared_law"] == _law(20.0, 10, 2.0)
    res, rec = _sealed_record({"id": "n", "domain": "mathematics",
                               "spec": {"mode": "numeric", "params": {"numeric_expr": "2 + 2", "claimed_value": 4.0}}})
    assert res["verdict"] == "HOLDS"
    assert "shared_law" not in rec.verifier_results[0].data      # a check that does not use the law seals as before


# ── THE LAW READ BACKWARDS: value = reference * b^(level / k) ─────────────────────────────────────────────────────
# A distance from its modulus, a Richter amplitude ratio, an Elo odds ratio, a note's frequency, a subnet's addresses,
# what remains after half-lives or e-folds (decay, Beer-Lambert, an RC charge, logistic growth), the Boltzmann factor
# and the Magnus saturation vapour pressure: each turned a level back into a quantity with its own formula. They now
# call log_scale.inverse, compute exactly what they did, and name the same form with the law's backward text.

def _inv(k, base, reference=None):
    return {**_law(k, base, reference), "law": "value = reference * b^(level / k)"}


def test_the_inverse_is_the_same_arithmetic_bit_for_bit():
    r = random.Random(20261126)
    for _ in range(4000):
        x, ref = r.uniform(-300, 300), 10 ** r.uniform(-100, 100)
        k = r.choice([r.uniform(1, 50) * r.choice([1, -1]), 400.0, 12.0, 5.0])
        assert LS.inverse(x, ref, k=k, base=10) == ref * 10.0 ** (x / k)
        assert LS.inverse(x, ref, k=k, base=2) == ref * 2.0 ** (x / k)
        assert LS.inverse(x, k=k, base=LS.E) == math.exp(x / k)
        y = r.uniform(-700, 700)
        assert LS.inverse(y, base=LS.E) == math.exp(y)
        # what remains after t in half-lives of T: geology wrote 0.5 ** (t / T); the law writes 2 ** (t / -T)
        t, T = r.uniform(0, 1e6), 10 ** r.uniform(-3, 10)
        assert LS.inverse(t, k=-T, base=2) == 0.5 ** (t / T)
    total = LS.inverse(24, k=1, base=2)            # an exact integer power stays an exact integer
    assert total == 2 ** 24 and type(total) is int
    assert type(LS.inverse(3, base=10)) is int and LS.inverse(-3, base=2) == 0.125


def test_the_inverse_undoes_the_level():
    r = random.Random(7)
    for _ in range(2000):
        v, ref = 10 ** r.uniform(-30, 30), 10 ** r.uniform(-30, 30)
        k = r.choice([10.0, 20.0, -20.0, 12.0, 5.0, 400.0, -1.0, 1.0])
        for b in (10, 2, LS.E):
            assert math.isclose(LS.inverse(LS.level(v, ref, k=k, base=b), ref, k=k, base=b), v, rel_tol=1e-9)


def test_an_inverse_base_the_law_does_not_hold_is_refused():
    with pytest.raises(KeyError):
        LS.inverse(2.0, base=3)


_kT = thermal_scale._kB * 300.0
INVERSE_VOICES = [
    (astronomy.verify_distance_modulus, {"apparent_magnitude": 11.05, "absolute_magnitude": 15.53, "claimed_distance_parsec": 1.2706},
     "actual_distance_parsec", 10.0 ** ((11.05 - 15.53 + 5.0) / 5.0), _inv(5.0, 10)),
    (geology.verify_radiometric_decay, {"isotope_half_life_years": 5730.0, "elapsed_years": 11460.0, "initial_amount": 100.0,
                                        "claimed_remaining_amount": 25.0},
     "actual_remaining", 100.0 * (0.5 ** (11460.0 / 5730.0)), _inv(-5730.0, 2, 100.0)),
    (geology.verify_richter_amplitude, {"richter_M1": 5.0, "richter_M2": 7.0, "claimed_amplitude_ratio": 100.0},
     "actual_ratio", 10.0 ** (7.0 - 5.0), _inv(1.0, 10)),
    (music_theory.verify_equal_temperament_freq, {"midi_note": 60, "claimed_frequency_hz": 261.6256},
     "actual_freq_hz", 440.0 * (2.0 ** ((60 - 69) / 12.0)), _inv(12.0, 2, 440.0)),
    (nuclear_physics.verify_radioactive_decay, {"half_life_seconds": 10.0, "elapsed_seconds": 20.0, "initial_count": 1000.0,
                                                "claimed_remaining_count": 250.0},
     "actual_remaining_count", 1000.0 * math.exp(-(nuclear_physics._LN2 / 10.0) * 20.0), _inv(1.0, "e", 1000.0)),
    (photonics.verify_beer_lambert, {"input_intensity": 2.0, "coefficient_per_m": 2.0, "path_length_m": 0.5,
                                     "claimed_output_intensity": 0.73576},
     "output_intensity", 2.0 * math.exp(-2.0 * 0.5), _inv(1.0, "e", 2.0)),
    (electrical.verify_rc_time_constant, {"resistance_ohm_rc": 2000.0, "capacitance_F": 1e-3, "elapsed_s": 1.0, "supply_V": 5.0,
                                          "claimed_capacitor_voltage_V": 1.9673},
     "actual_v", 5.0 * (1.0 - math.exp(-1.0 / (2000.0 * 1e-3))), _inv(2000.0 * 1e-3, "e")),
    (sports_analytics.verify_elo_expected_score, {"elo_a": 1600.0, "elo_b": 1400.0, "claimed_expected_score_a": 0.7597},
     "actual_expected", 1.0 / (1.0 + 10 ** ((1400.0 - 1600.0) / 400.0)), _inv(400.0, 10)),
    (sports_analytics.verify_elo_rating_update, {"elo_a_pre": 1600.0, "elo_b_pre": 1400.0, "actual_score_a": 1.0, "elo_K": 32.0,
                                                 "claimed_elo_a_post": 1607.69},
     "expected_score_a", 1.0 / (1.0 + 10 ** ((1400.0 - 1600.0) / 400.0)), _inv(400.0, 10)),
    (cybersecurity.verify_subnet_hosts, {"cidr_prefix": 24, "claimed_host_count": 254},
     "total_addresses", 2 ** (32 - 24), _inv(1, 2)),
    (ecology.verify_logistic_growth, {"carrying_capacity_K": 1000.0, "initial_population_N0": 10.0, "growth_rate_r": 0.5,
                                      "time_t": 10.0, "claimed_population": 599.86},
     "actual_population", 1000.0 / (1.0 + ((1000.0 - 10.0) / 10.0) * math.exp(-0.5 * 10.0)), _inv(1.0, "e")),
    (meteorology.verify_saturation_vapor_pressure, {"temperature_c_for_es": 25.0, "claimed_saturation_vapor_pressure_hpa": 31.7},
     "actual_es_hpa", 6.112 * math.exp((17.625 * 25.0) / (25.0 + 243.04)), _inv(1.0, "e", 6.112)),
    (chemistry.verify_boltzmann_factor, {"boltzmann_energy_J": 4.14e-21, "boltzmann_temperature_K": 300.0,
                                         "claimed_boltzmann_factor": 0.36805},
     "actual_value", math.exp(-4.14e-21 / _kT), _inv(_kT, "e")),
]


@pytest.mark.parametrize("fn, spec, key, old, law", INVERSE_VOICES, ids=[v[0].__name__ for v in INVERSE_VOICES])
def test_each_inverse_names_the_law_and_computes_what_its_old_formula_did(fn, spec, key, old, law):
    r = fn(dict(spec))
    assert r.status == "CONFIRMED", (r.status, r.detail)
    assert r.data[key] == old and type(r.data[key]) is type(old)      # bit for bit, and an exact count stays an int
    assert r.data["shared_law"] == law


def test_the_shared_helper_reads_backwards_too():
    for E, T in ((4.14e-21, 300.0), (-1e-22, 77.0), (0.0, 1.0), (1e-20, 1.0 / thermal_scale._kB)):
        assert thermal_scale.boltzmann_factor(E, T) == math.exp(-E / (thermal_scale._kB * T))


def test_the_seal_carries_the_law_read_backwards():
    res, rec = _sealed_record({"id": "c14", "domain": "geology", "spec": {"GEO_VERIFY": {
        "isotope_half_life_years": 5730.0, "elapsed_years": 11460.0, "initial_amount": 100.0, "claimed_remaining_amount": 25.0}}})
    assert res["verdict"] == "HOLDS"
    assert rec.verifier_results[0].data["shared_law"] == _inv(-5730.0, 2, 100.0)


# ── THE LAW SUMMED: H = k * sum(p * log_b(p)) ─────────────────────────────────────────────────────────────────────
# Shannon entropy, the binary entropy inside a channel's capacity, the Shannon diversity index and the von Neumann
# entropy each summed p * log(p) their own way. They now call log_scale.entropy: each term is p * (k * log_b(p)), the
# p-weighted level of p with k = -1, added by Python's compensated sum() from 0.0.

def _ent(base):
    return {**_law(-1.0, base), "law": "level = k * sum(p * log_b(p))"}


def _dist(r):
    n = r.randint(1, 300)
    w = [r.expovariate(1.0) * (0 if r.random() < 0.1 else 1) for _ in range(n)]
    tot = sum(w) or 1.0
    return [x / tot for x in w]


def test_the_entropy_is_the_negated_sum_it_was_bit_for_bit_except_the_sign_of_a_zero():
    r = random.Random(20261127)
    for _ in range(3000):
        ps = _dist(r)
        for b, log in ((2, math.log2), (LS.E, math.log), (10, math.log10)):
            old = -sum(p * log(p) for p in ps if p > 0)
            new = LS.entropy(ps, base=b)
            assert new == old
            if old == 0:                          # one certain outcome: the old sums wrote -0.0
                assert math.copysign(1.0, new) == 1.0
    assert math.copysign(1.0, LS.entropy([1.0])) == 1.0 and LS.entropy([0.0, 1.0, 0.0], base=LS.E) == 0.0
    assert LS.entropy([0.5, 0.5]) == 1.0 and LS.entropy([0.25] * 4) == 2.0


def test_the_sum_is_the_exactly_rounded_sum_of_its_terms():
    """Ecology added its terms one by one; the law's compensated sum lands where the exact sum of the same terms
    rounds, which the plain loop missed in most distributions (5,403 of 22,867 measured)."""
    r = random.Random(3)
    for _ in range(3000):
        ps = _dist(r)
        assert LS.entropy(ps, base=LS.E) == math.fsum(-(p * math.log(p)) for p in ps if p > 0)


def test_the_floor_leaves_out_what_is_at_or_below_it():
    lam = [0.5, 0.5 - 1e-16, 1e-16, 1e-15, 0.0]
    assert LS.entropy(lam, base=2, floor=1e-15) == -sum(x * math.log2(x) for x in lam if x > 1e-15)


def test_the_binary_entropy_is_the_two_term_sum_it_was_bit_for_bit():
    r = random.Random(11)
    for _ in range(20000):
        q = r.choice([r.random(), 10 ** r.uniform(-300, 0), 1 - 10 ** r.uniform(-15, -1)])
        assert information_theory._h2(q) == -q * math.log2(q) - (1 - q) * math.log2(1 - q)
    assert information_theory._h2(0.0) == 0.0 == information_theory._h2(1.0)


_PS = [0.5, 0.25, 0.125, 0.125]
ENTROPY_VOICES = [
    (information_theory.verify_shannon_entropy, {"probabilities": _PS, "claimed_entropy_bits": 1.75},
     "actual_entropy_bits", 1.75, _ent(2)),
    (information_theory.verify_bsc_capacity, {"bsc_error_rate": 0.11, "claimed_capacity_bits": 0.5},
     "actual_capacity_bits", 1.0 - (-0.11 * math.log2(0.11) - 0.89 * math.log2(0.89)), _ent(2)),
    (ecology.verify_shannon_diversity, {"species_proportions": _PS, "claimed_shannon_index": 1.2130},
     "actual_shannon_index", math.fsum(-(p * math.log(p)) for p in _PS), _ent("e")),
    (quantum_computing.verify_von_neumann_entropy, {"density_eigenvalues": [0.5, 0.5], "claimed_entropy_bits": 1.0},
     "computed_entropy_bits", 1.0, _ent(2)),
]


@pytest.mark.parametrize("fn, spec, key, old, law", ENTROPY_VOICES, ids=[v[0].__name__ for v in ENTROPY_VOICES])
def test_each_entropy_names_the_law_summed(fn, spec, key, old, law):
    r = fn(dict(spec))
    assert r.status == "CONFIRMED", (r.status, r.detail)
    assert r.data[key] == old
    assert r.data["shared_law"] == law


def test_a_certain_outcome_reads_zero_bits_not_minus_zero():
    r = information_theory.verify_shannon_entropy({"probabilities": [1.0, 0.0], "claimed_entropy_bits": 0.0})
    assert r.status == "CONFIRMED" and "-0.000000" not in r.detail
    q = quantum_computing.verify_von_neumann_entropy({"density_eigenvalues": [1.0, 0.0], "claimed_entropy_bits": 0.0})
    assert q.status == "CONFIRMED" and "-0.000000" not in q.detail


def test_the_seal_carries_the_law_summed():
    res, rec = _sealed_record({"id": "h", "domain": "information_theory", "spec": {"INFO_VERIFY": {
        "probabilities": _PS, "claimed_entropy_bits": 1.75}}})
    assert res["verdict"] == "HOLDS"
    assert rec.verifier_results[0].data["shared_law"] == _ent(2)
