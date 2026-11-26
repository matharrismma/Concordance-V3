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
from concordance.verifiers import (acoustics, archaeology, cybersecurity, electrical, electrochemistry, log_scale as LS,
                                   meteorology, neuroscience, optics, photography, thermal_scale, thermodynamics)


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
