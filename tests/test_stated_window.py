"""A claim's stated precision belongs to the claim: a literal widens nothing unless it is the number the claim states.

THE RULE (verifiers/base.py): a stated literal sets the window only when, read as stated_precision reads it, it equals the
claimed value up to float representation, compared in the claim's own unit. Any other literal can only narrow, the
threshold being the smaller of the verifier's default and what the literal earned, and the hedged flag widens only a
literal that passed. So a request cannot hand a false claim a window it never stated.

ROWS: for each caller, a claim stated to its precision reads HOLDS, a false claim with its own literal reads BROKEN, and a
false claim carrying a literal that is not its own reads BROKEN, all through tools/benchmark.py's verify. EVERY CALLER: a
walk of the source fails on a call of window_for without the claimed value and on any reader of a stated literal not
listed here with its reason; planted cases prove it can fail.
"""
from __future__ import annotations

import ast
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "concordance"
sys.path.insert(0, str(ROOT / "tools"))

import benchmark  # noqa: E402
from concordance.audit import audit, extract  # noqa: E402
from concordance.config import EngineConfig  # noqa: E402
from concordance.verifiers import base, run_for_domain  # noqa: E402

CFG = EngineConfig(skip_schema_validation=True)
WIDE = "5.0e3"                  # a readable literal with a window of 50 either side, foreign to every claim below


def verdict(domain: str, spec: Dict[str, Any]) -> str:
    return benchmark.verify(spec, domain)["verdict"]


def _math(mode: str, params: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    return "mathematics", {"mode": mode, "params": params}


def numeric(c, **x):
    return _math("numeric", {"numeric_expr": "sqrt(2)", "claimed_value": c, **x})


def equality(c, **x):
    return _math("equality", {"expr_a": "sqrt(2)", "expr_b": repr(c), **x})


def rule72(c, **x):
    return "economics", {"ECON_VERIFY": {"rate_percent": 7, "claimed_doubling_years": c, **x}}


def compound(c, **x):
    return "finance", {"FIN_VERIFY": {"principal": 1000000, "rate": 0.05, "compounding_per_year": 1, "years": 10,
                                      "claimed_future_value": c, **x}}


def hourly(c, **x):
    return "labor", {"LABOR_VERIFY": {"annual_salary": 1000000, "claimed_hourly_equivalent": c, **x}}


def annual(c, **x):
    return "labor", {"LABOR_VERIFY": {"hourly_rate": 20, "claimed_annual_salary": c, **x}}


def _geom(**fixed):
    def make(key):
        def build(c, **x):
            return "geometry", {"GEOM_VERIFY": {**fixed, key: c, **x}}
        return build
    return make


circle, rectangle, sphere = _geom(circle_radius=3), _geom(rect_length=4.1, rect_width=6.1), _geom(sphere_radius=3)
cube, cylinder, polygon = _geom(cube_side=2.1), _geom(cyl_radius=1, cyl_height=2), _geom(polygon_n=6)


def molar(c, **x):
    return "periodic_table", {"PT_VERIFY": {"formula": "NaCl", "claimed_molar_mass": c, **x}}


def constant(c, **x):
    return "physical_constants", {"CONST_VERIFY": {"constant": "speed_of_light", "claimed_value": c, **x}}


def constant_km_s(c, **x):
    return "physical_constants", {"CONST_VERIFY": {"constant": "speed_of_light", "claimed_value": c, "claimed_unit": "km/s", **x}}


def kinetic(c, **x):
    return "physics", {"PHYS_VERIFY": {"mass_kg": 2, "velocity_m_per_s": 3.1, "claimed_kinetic_energy_J": c, **x}}


def convert(c, **x):
    return "unit_conversion", {"CONV_VERIFY": {"from_value": 1, "from_unit": "mile", "to_value": c, "to_unit": "kilometers", **x}}


def escape(c, **x):
    return "astronomy", {"ASTRO_VERIFY": {"escape_mass_kg": 5.972e24, "escape_radius_m": 6.371e6,
                                          "claimed_escape_velocity_m_s": c, **x}}


def phase(c, **x):
    return "chemistry", {"CHEM_VERIFY": {"substance": "ethanol", "property": "boiling", "claimed_c": c, **x}}


LIT = "claimed_literal"
# name, packet, literal key, a claim stated to its precision, a false claim with its own literal, a foreign literal
CALLERS = [
    ("numeric", numeric, LIT, (1.41, "1.41"), (1.42, "1.42"), WIDE),
    ("equality", equality, LIT, (1.41, "1.41"), (1.42, "1.42"), WIDE),
    ("economics", rule72, "claimed_doubling_years_as_written", (10.3, "10.3"), (11.0, "11.0"), WIDE),
    ("finance", compound, "claimed_future_value_as_written", (1630000.0, "$1.63 million"), (1700000.0, "$1.70 million"), "$5.0 billion"),
    ("labor-hourly", hourly, "claimed_hourly_as_written", (480.0, "$480"), (470.0, "$470"), "$5.0 million"),
    ("labor-annual", annual, "claimed_annual_as_written", (42000.0, "$42,000"), (43000.0, "$43,000"), "$5.0 million"),
    ("geometry-circle-area", circle("claimed_circle_area"), "claimed_circle_area_as_written", (28.0, "28"), (29.0, "29"), WIDE),
    ("geometry-circle-circumference", circle("claimed_circle_circumference"), "claimed_circle_circumference_as_written", (19.0, "19"), (19.5, "19.5"), WIDE),
    ("geometry-rectangle-area", rectangle("claimed_rect_area"), "claimed_rect_area_as_written", (25.0, "25"), (26.0, "26"), WIDE),
    ("geometry-rectangle-perimeter", rectangle("claimed_rect_perimeter"), "claimed_rect_perimeter_as_written", (20.0, "2.0e1"), (21.0, "21"), WIDE),
    ("geometry-sphere-volume", sphere("claimed_sphere_volume"), "claimed_sphere_volume_as_written", (113.0, "113"), (114.0, "114"), WIDE),
    ("geometry-sphere-surface", sphere("claimed_sphere_surface_area"), "claimed_sphere_surface_area_as_written", (113.0, "113"), (114.0, "114"), WIDE),
    ("geometry-cube-volume", cube("claimed_cube_volume"), "claimed_cube_volume_as_written", (9.3, "9.3"), (9.4, "9.4"), WIDE),
    ("geometry-cube-surface", cube("claimed_cube_surface_area"), "claimed_cube_surface_area_as_written", (26.5, "26.5"), (26.6, "26.6"), WIDE),
    ("geometry-cylinder-volume", cylinder("claimed_cyl_volume"), "claimed_cyl_volume_as_written", (6.3, "6.3"), (6.4, "6.4"), WIDE),
    ("geometry-polygon", polygon("claimed_interior_angle_sum_deg"), "claimed_interior_angle_sum_deg_as_written", (720.0, "720.0"), (725.0, "725"), WIDE),
    ("periodic-table", molar, LIT, (58.0, "58"), (59.0, "59"), WIDE),
    ("physical-constants", constant, LIT, (3.00e8, "3.00e8"), (2.99e8, "2.99e8"), "3.0e8"),
    ("physical-constants-converted", constant_km_s, LIT, (299800.0, "299,800"), (290000.0, "290,000"), "5.0e6"),
    ("physics-kinetic-energy", kinetic, "claimed_kinetic_energy_as_written", (9.6, "9.6"), (9.7, "9.7"), WIDE),
    ("units", convert, LIT, (1.6, "1.6"), (1.7, "1.7"), WIDE),
    ("astronomy-scale-base", escape, "claimed_escape_velocity_as_written", (11200.0, "11.2 km/s"), (11300.0, "11.3 km/s"), "5.0e3 km/s"),
    ("chemistry", phase, LIT, (78.0, "78"), (77.6, "77.6"), "78"),
]
IDS = [c[0] for c in CALLERS]


@pytest.mark.parametrize("name, make, key, good, false, foreign", CALLERS, ids=IDS)
def test_a_claim_stated_to_its_precision_reads_holds(name, make, key, good, false, foreign):
    assert verdict(*make(good[0], **{key: good[1]})) == "HOLDS"


@pytest.mark.parametrize("name, make, key, good, false, foreign", CALLERS, ids=IDS)
def test_a_false_claim_with_its_own_literal_reads_broken(name, make, key, good, false, foreign):
    assert verdict(*make(false[0], **{key: false[1]})) == "BROKEN"


@pytest.mark.parametrize("name, make, key, good, false, foreign", CALLERS, ids=IDS)
def test_a_false_claim_with_a_literal_not_its_own_reads_broken(name, make, key, good, false, foreign):
    assert verdict(*make(false[0], **{key: foreign})) == "BROKEN"


@pytest.mark.parametrize("name, make, key, good, false, foreign", CALLERS, ids=IDS)
def test_a_hedge_widens_no_literal_that_is_not_the_claims(name, make, key, good, false, foreign):
    assert verdict(*make(false[0], **{key: foreign, "hedged": True})) == "BROKEN"


@pytest.mark.parametrize("name, make, key, good, false, foreign", CALLERS, ids=IDS)
def test_the_recorded_data_says_the_literal_was_not_the_claims(name, make, key, good, false, foreign):
    domain, spec = make(false[0], **{key: foreign})
    if domain == "mathematics":
        from concordance.verifiers import mathematics
        results = [getattr(mathematics, "verify_" + spec["mode"])(spec["params"])]
    else:
        results = run_for_domain(domain, spec)
    assert any((r.data or {}).get("literal_not_the_claim") is True for r in results)
    domain, spec = make(good[0], **{key: good[1]})
    if domain != "mathematics":
        assert not any((r.data or {}).get("literal_not_the_claim") for r in run_for_domain(domain, spec))


# ── a literal that is not the claim's can only narrow ───────────────────────────────────────────
def test_a_foreign_literal_still_narrows():
    """The moat case check:units.conversion:false: 1.609 is inside the flat default, and outside what 2.20433 earned."""
    def conv(**x):
        return convert(1.609, **x)
    assert verdict(*conv()) == "HOLDS"
    assert verdict(*conv(claimed_literal="1.609")) == "HOLDS"
    assert verdict(*conv(claimed_literal="2.20433")) == "BROKEN"
    assert verdict(*conv(claimed_literal="9")) == "BROKEN"          # one figure earned nothing: float noise only


GRID = [("numeric", numeric, LIT, 1.41421356), ("equality", equality, LIT, 1.41421356), ("economics", rule72, "claimed_doubling_years_as_written", 72 / 7),
        ("finance", compound, "claimed_future_value_as_written", 1628894.6), ("labor", hourly, "claimed_hourly_as_written", 480.769),
        ("geometry", circle("claimed_circle_area"), "claimed_circle_area_as_written", 28.2743), ("periodic-table", molar, LIT, 58.44),
        ("constants", constant, LIT, 299792458.0), ("physics", kinetic, "claimed_kinetic_energy_as_written", 9.61),
        ("units", convert, LIT, 1.609344), ("astronomy", escape, "claimed_escape_velocity_as_written", 11186.0), ("chemistry", phase, LIT, 78.37)]


@pytest.mark.parametrize("name, make, key, actual", GRID, ids=[g[0] for g in GRID])
def test_a_claim_that_holds_beside_a_foreign_literal_holds_with_none(name, make, key, actual):
    for off in (0.0, 1e-4, -3e-3, 2e-2, 1e-1):
        claim = actual * (1 + off)
        alone = verdict(*make(claim))
        for literal in ("5.0e3", "9.9e307", "1", "0.0", "-1.5", "$5.0 million", "abc", "5.0e3 km/s"):
            for hedge in ({}, {"hedged": True}):
                beside = verdict(*make(claim, **{key: literal}, **hedge))
                assert beside != "HOLDS" or alone == "HOLDS", (claim, literal, hedge, alone, beside)


# ── one check's literal lends nothing to its sibling ────────────────────────────────────────────
def test_a_literal_lends_no_window_to_a_false_sibling():
    spec = {"GEOM_VERIFY": {"circle_radius": 3, "claimed_circle_area": 28.0, "claimed_circle_area_as_written": "28",
                            "claimed_circle_circumference": 18.5}}
    assert verdict("geometry", spec) == "BROKEN"
    spec = {"GEOM_VERIFY": {"circle_radius": 3, "claimed_circle_area": 28.0, "claimed_circle_area_as_written": "28",
                            "claimed_circle_circumference": 18.85}}
    assert verdict("geometry", spec) == "HOLDS"


def test_a_key_that_names_no_check_lends_no_window():
    spec = {"GEOM_VERIFY": {"circle_radius": 3, "claimed_circle_area": 30, "zzz_as_written": WIDE}}
    assert verdict("geometry", spec) == "BROKEN"


def test_a_yes_or_no_states_no_number_so_no_literal_can_help_it():
    def triangle(c, claimed, **x):
        return {"GEOM_VERIFY": {"pyth_a": 3, "pyth_b": 4, "pyth_c": c, "claimed_right_triangle": claimed, **x}}
    assert verdict("geometry", triangle(5, True)) == "HOLDS"
    assert verdict("geometry", triangle(6, True, zzz_as_written=WIDE)) == "BROKEN"
    assert verdict("geometry", triangle(6, True, zzz_as_written="36")) == "BROKEN"
    assert verdict("geometry", triangle(5, True, zzz_as_written=WIDE)) == "HOLDS"
    assert verdict("geometry", triangle(5.0000001, True, zzz_as_written="7")) == "BROKEN"   # a literal still narrows "right"
    assert verdict("geometry", triangle(5.0000001, False, zzz_as_written="7")) == "BROKEN"  # and cannot narrow "not right"
    assert verdict("geometry", triangle(6, False)) == "HOLDS"


# ── the comparison is made in the claim's own unit, before any conversion ───────────────────────
def test_finance_and_labor_compare_the_literal_times_its_factor():
    assert verdict(*compound(1630000.0, claimed_future_value_as_written="$1.63 million")) == "HOLDS"
    assert verdict(*compound(1.63, claimed_future_value_as_written="$1.63 million")) == "BROKEN"
    assert verdict(*annual(41600.0, claimed_annual_as_written="$41,600")) == "HOLDS"
    assert verdict(*annual(41.6, claimed_annual_as_written="$41.6 thousand")) == "BROKEN"


def test_physical_constants_compares_the_claim_before_conversion():
    assert verdict(*constant_km_s(300000.0, claimed_literal="300,000", hedged=True)) == "HOLDS"
    assert verdict(*constant_km_s(290000.0, claimed_literal="300,000", hedged=True)) == "BROKEN"
    assert verdict(*constant_km_s(300000.0, claimed_literal="3.0e8", hedged=True)) == "BROKEN"   # the literal in m/s, the claim in km/s


def test_scale_base_compares_the_literal_times_its_unit_factor():
    aw = "claimed_escape_velocity_as_written"
    assert verdict(*escape(11200.0, **{aw: "11.2 km/s"})) == "HOLDS"
    assert verdict(*escape(11200.0, **{aw: "11,200 m/s"})) == "HOLDS"
    assert verdict(*escape(11200.0, **{aw: "11.2 m/s"})) == "BROKEN"
    assert verdict(*escape(11300.0, **{aw: "11.2 km/s"})) == "BROKEN"


def test_an_unknown_unit_earns_no_window_as_before():
    assert verdict(*escape(11200.0, claimed_escape_velocity_as_written="25,000 mph")) == "BROKEN"


def test_equality_ties_the_literal_to_the_claimed_side():
    """Both sides are the caller's, so a literal may not be read from the side the claim is measured against."""
    assert verdict(*_math("equality", {"expr_a": "5", "expr_b": "5.04", "claimed_literal": "5.0"})) == "BROKEN"
    assert verdict(*_math("equality", {"expr_a": "5.04", "expr_b": "5.0", "claimed_literal": "5.0"})) == "HOLDS"


# ── a hedge reads as today on the claim's own literal ───────────────────────────────────────────
def test_a_hedge_on_the_claims_own_literal_reads_as_before():
    aw = "claimed_doubling_years_as_written"
    assert verdict(*rule72(10.0, **{aw: "10", "hedged": True})) == "HOLDS"       # about 10 years; 72 / 7 = 10.29
    assert verdict(*rule72(10.0, **{aw: "10"})) == "BROKEN"                      # 10, one figure, no hedge: exact
    assert verdict(*numeric(1.4, claimed_literal="1.4", hedged=True)) == "HOLDS"
    assert verdict(*constant_km_s(300000.0, claimed_literal="300,000")) == "BROKEN"


# ── chemistry's literal ─────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("literal", ["78", None, "", "78 C", "7.8e1", "abc"], ids=["coarser", "null", "empty", "unit", "exponent", "words"])
def test_chemistry_gives_a_literal_that_is_not_the_claim_no_coarser_reading(literal):
    assert verdict(*phase(77.6, claimed_literal=literal)) == "BROKEN"


def test_chemistry_reads_no_decimals_from_an_exponent():
    assert verdict(*phase(77.5, claimed_literal="775e-1")) == "BROKEN"          # 77.5 is no boiling point of ethanol
    assert verdict(*phase("775e-1")) == "BROKEN"
    assert verdict(*phase(78.37, claimed_literal="7837e-2")) == "HOLDS"


def test_chemistry_keeps_the_spread_of_measured_values():
    assert verdict(*phase(78.3, claimed_literal="78.3")) == "HOLDS"
    assert verdict(*phase(78.0)) == "HOLDS"
    assert verdict(*phase(79.0, claimed_literal="79")) == "BROKEN"


# ── the test itself ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("literal, claimed, factor, same", [
    ("5.0", 5.0, 1.0, True), ("5.0", 5, 1.0, True), ("5", "5.0", 1.0, True), ("41,600", 41600, 1.0, True),
    ("$1.63", 1.63, 1.0, True), ("3.0e8", 3e8, 1.0, True), (".5", 0.5, 1.0, True), ("5.", 5.0, 1.0, True),
    ("-1.5", -1.5, 1.0, True), ("0", 0, 1.0, True), ("0.0", -0.0, 1.0, True), ("29.3", 29300000.0, 1e6, True),
    (5000.0, 5000, 1.0, True),
    ("5.0", 5.1, 1.0, False), ("5.0", -5.0, 1.0, False), ("29.3", 29.3, 1e6, False), ("0", 1e-300, 1.0, False),
    ("abc", 5, 1.0, False), ("", 0, 1.0, False), (None, 0, 1.0, False), ("5 m", 5, 1.0, False), ("1.0e400", float("inf"), 1.0, False),
    ("5.0", float("inf"), 1.0, False), ("5.0", float("nan"), 1.0, False), ("5.0", None, 1.0, False), ("5.0", "x", 1.0, False),
    ("nan", float("nan"), 1.0, False), ("inf", float("inf"), 1.0, False), (True, 1, 1.0, False),
])
def test_a_literal_is_the_claim_only_when_it_is_the_same_number(literal, claimed, factor, same):
    assert base.literal_is_claim(literal, claimed, factor) is same


def test_float_representation_stays_tight():
    """The gap allowed is float noise, not a window: two parts in a billion is already another number."""
    assert base.literal_is_claim("5.0", 5.0 * (1 + 5e-10)) is True
    assert base.literal_is_claim("5.0", 5.0 * (1 + 2e-9)) is False
    assert base.literal_is_claim("1000000.0", 1000000.002) is False
    assert base.literal_is_claim("0.1", 0.1 + 0.2 - 0.2) is True                # a real float road: 0.10000000000000003


def test_window_for_needs_the_claimed_value():
    with pytest.raises(TypeError):
        base.window_for({"k": "5.0"}, "k", 1.0)


@pytest.mark.parametrize("literal, hedged, claimed, want, foreign", [
    ("1.0", False, 1.0, 0.05, False),                # two figures: half a unit, replacing the default
    ("1.0", True, 1.0, 0.1, False),                  # a hedge doubles it
    ("1", False, 1.0, 1e-9, False),                  # one figure, no hedge: float noise only
    ("1", True, 1.0, 0.5, False),                    # a hedge grants the half unit
    ("9.0", False, 1.0, 0.04, True),                 # not the claim: the smaller of the default and 0.05
    ("9.0", True, 1.0, 0.04, True),                  # and a hedge does not widen what is not the claim's
    ("90.0", False, 1.0, 0.04, True),                # the literal earned less than the default? 0.05 again: the default
    ("9.000", False, 1.0, 0.0005, True),             # narrower than the default: it narrows
    ("9", False, 1.0, 1e-9, True),                   # earned nothing: it narrows to float noise
    ("abc", False, 1.0, 1e-9, True),                 # unreadable: earns nothing
])
def test_window_for_threshold(literal, hedged, claimed, want, foreign):
    threshold, info = base.window_for({"k": literal, "hedged": hedged}, "k", 0.04, 1.0, 1.0, claimed=claimed)
    assert threshold == pytest.approx(want)
    assert bool(info.get("literal_not_the_claim")) is foreign


def test_window_for_with_no_literal_records_nothing():
    assert base.window_for({}, "k", 0.04, 1.0, 1.0, claimed=9) == (0.04, {})
    assert base.window_for({"k": ""}, "k", 0.04, 1.0, 1.0, claimed=9) == (0.04, {})


def test_a_literal_past_a_float_is_not_a_number_any_claim_states():
    assert base.literal_value("1.0e400") is None
    assert verdict("mathematics", {"mode": "numeric", "params": {"numeric_expr": "5", "claimed_value": 7, "claimed_literal": "1.0e400"}}) != "HOLDS"


# ── the text extractors keep their readings ─────────────────────────────────────────────────────
TEXT_HOLDS = [
    "$20 per hour is $41,600 per year", "$41,600 a year is $20 per hour", "$1,000 at 5% compounded annually for 10 years grows to $1,628.89",
    "20% of 150 is 30", "15% of $1,200 is $180", "1 mile is 1.6 km", "1 mile is about 1.6 km", "pi is 3.14", "pi is about 3.1", "euler's number is 2.718",
    "sqrt(2) is 1.414", "the square root of 2 is about 1.41", "1,000 + 2,000 = 3,000",
    "the speed of light is 299,792,458 m/s", "the speed of light is about 300,000 km/s", "earth gravity is 9.81 m/s^2",
    "the molar mass of H2O is 18.015 g/mol", "aspirin C9H8O4 is 180.16 g/mol", "the boiling point of water is 100 C", "the boiling point of ethanol is 78 C",
    "the escape velocity of earth is 11.2 km/s", "the escape velocity of earth is 11,186 m/s", "at 7% money doubles in about 10 years",
    "a circle of radius 3 has area 28.27", "a 2 kg object at 3 m/s has kinetic energy 9 J", "a rectangle 4 by 6 has area 24",
    "x^2 = 2 has solution x = 1.41421356", "x^2 = 2 has solution x = 1.41", "x^2 - 4 = 0 has solution x = 2", "x^3 = 27 has root x = 3.0000",
    "x^2 + y^2 = 25 and y = x has solution (3.5355, 3.5355)", "x^2 + y^2 = 25 and y = x has solution (3.5, 3.5)", "x + y = 2 and x - y = 0 has solution (1, 1)",
    "x^2 = 2 has solution x = 1.41421356237309505", "x^2 - 4 = 0 has solution x = 2.0000000000000000",
    "x + 1 = 1000000000000000000000 has solution x = 999999999999999999999.0",
    "x^2 = 2500000010 has solution x = 50000.00010", "x^2 = 2 has solution x = -1.41", "x^2 + x = 0 has solution x = 0.00",
]
TEXT_BROKEN = [
    "the speed of light is 3.1e8 m/s", "1 mile is 1.7 km", "the escape velocity of earth is 12.5 km/s", "pi is 3.2", "x^2 = 2 has solution x = 1.42",
    "x^2 = 2 has solution x = 1.5", "x^2 = 2 has solution x = -1.5", "x^3 = 27 has root x = 3.0001", "x + y = 1000000000000000000002.0 and x - y = 0 has solution (1000000000000000000000.0, 1000000000000000000000.0)",
    # the value is off by less than its own float can show: value + residual would swallow every one of these
    "x^2 = 2 has solution x = 1.41421356237309510", "x^2 = 2 has solution x = 1.4142135623730951", "x^2 = 2 has solution x = 1.41421356237310",
    "x^2 - 4 = 0 has solution x = 2.0000000000000001", "x + 1 = 1000000000000000000000 has solution x = 999999999999999990000.0",
    "x + 2 = 100000000000000000000 has solution x = 100000000000000000000.0",
    "0.125x^2 = 0.5000000008 has solution x = 2",                               # one figure is judged exactly, however large the value
    "x^2 + y = 3 and y = 1 has solution (1.4142135623730960, 1.0000000000000000)",
]


@pytest.mark.parametrize("text", TEXT_HOLDS)
def test_a_true_text_claim_keeps_reading_holds(text):
    assert audit(text, CFG, seal=False)["verdict"] == "HOLDS"


@pytest.mark.parametrize("text", TEXT_BROKEN)
def test_a_false_text_claim_keeps_reading_broken(text):
    assert audit(text, CFG, seal=False)["verdict"] == "BROKEN"


def _packet(text: str) -> Dict[str, Any]:
    return next(s["spec"]["params"] for s in extract(text) if s["domain"] == "mathematics")


def test_a_stated_solution_is_the_claim_and_its_literal_is_the_claim():
    for text, value in (("x^2 = 2 has solution x = 1.41", "1.41"), ("x^2 + y^2 = 25 and y = x has solution (3.5355, 3.5355)", "3.5355")):
        p = _packet(text)
        assert p["claimed_literal"] == value and p["claimed_value"] == float(value)
        assert base.literal_is_claim(p["claimed_literal"], p["claimed_value"])


def test_where_the_sum_cannot_carry_the_residual_no_literal_is_sent():
    for text in ("x^2 - 4 = 0 has solution x = 2", "x + 2 = 100000000000000000000 has solution x = 100000000000000000000.0",
                 "x^2 = 2 has solution x = 1.41421356237309510", "x + y = 2 and x - y = 0 has solution (1, 1)"):
        p = _packet(text)
        assert "claimed_literal" not in p and p["claimed_value"] == 0


# ── the moat's own literal cases ────────────────────────────────────────────────────────────────
def _has_literal(value: Any) -> bool:
    if isinstance(value, dict):
        return any(k == LIT or str(k).endswith("_as_written") or _has_literal(v) for k, v in value.items())
    return isinstance(value, list) and any(_has_literal(v) for v in value)


def _literal_cases():
    cases = [(label, spec, desc) for label, spec, desc in benchmark._domain_cases() if _has_literal(spec)]
    cases += [(label, spec, desc) for label, spec, desc in benchmark._check_cases() if _has_literal(spec)]
    return cases


def test_every_moat_case_with_a_literal_keeps_its_reading():
    from concordance.derivation import verify_derivation
    cases = _literal_cases()
    assert len(cases) >= 10, "the moat holds literal cases, among them check:units.conversion:false"
    wrong = [desc for label, spec, desc in cases if (verify_derivation(spec).get("verdict") == "HOLDS") != label]
    assert not wrong, wrong
    assert any("units.conversion:false" in desc for _, _, desc in cases)


# ── EVERY CALLER: the walk ──────────────────────────────────────────────────────────────────────
READERS = frozenset({"stated_window", "stated_tolerance_abs", "stated_precision", "literal_scale"})
CARRIERS = frozenset({"hedged", "as_written", LIT})        # the same things under a name: a parameter, or a local


def _literal_key(value: Any) -> bool:
    return isinstance(value, str) and (value in (LIT, "hedged") or value.endswith("_as_written"))


class _Readers(ast.NodeVisitor):
    """What one module reads of a stated literal, each finding as (function, what). A key written into a packet, a docstring
    and a comment are not reads; `claimed=` missing from a window_for call is a finding of its own."""

    def __init__(self) -> None:
        self.stack: List[str] = []
        self.found: Set[Tuple[str, str]] = set()
        self.unclaimed: Set[Tuple[str, str]] = set()

    def _hit(self, what: str) -> None:
        self.found.add((".".join(self.stack) or "<module>", what))

    def _scope(self, node) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_ClassDef = _scope

    def visit_FunctionDef(self, node) -> None:
        self.stack.append(node.name)
        for a in node.args.args + node.args.kwonlyargs:
            if a.arg in CARRIERS:
                self._hit(a.arg)
        self.generic_visit(node)
        self.stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ImportFrom(self, node) -> None:
        for alias in node.names:
            if alias.name in READERS:
                self._hit(alias.name)

    def visit_Name(self, node) -> None:
        if node.id in READERS or (node.id in CARRIERS and isinstance(node.ctx, ast.Load)):
            self._hit(node.id)

    def visit_Attribute(self, node) -> None:
        if node.attr in READERS:
            self._hit(node.attr)
        self.generic_visit(node)

    def visit_Dict(self, node) -> None:
        for v in node.values:                           # the keys of a literal dict are written, not read
            self.visit(v)

    def visit_Subscript(self, node) -> None:
        if isinstance(node.ctx, ast.Store):             # holder["hedged"] = True writes it
            self.visit(node.value)
            return
        self.generic_visit(node)

    def visit_Expr(self, node) -> None:
        if not (isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
            self.generic_visit(node)

    def visit_Constant(self, node) -> None:
        if _literal_key(node.value):
            self._hit(node.value)

    def visit_keyword(self, node) -> None:
        if node.arg in CARRIERS:
            self._hit(node.arg)
        self.generic_visit(node)

    def visit_Call(self, node) -> None:
        f = node.func
        name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")
        if name in ("window_for", "stated_threshold"):
            given = [k.value for k in node.keywords if k.arg == "claimed"]
            if not given or (isinstance(given[0], ast.Constant) and given[0].value is None):
                self.unclaimed.add((".".join(self.stack) or "<module>", name))
        self.generic_visit(node)


def read(source: str) -> _Readers:
    r = _Readers()
    r.visit(ast.parse(source))
    return r


AS_WRITTEN_GEOMETRY = "the first *_as_written key, tested against the check's own claim by window_for"
# (file, function) -> (what it reads, why that is safe). A new read fails until it is listed; a stale one fails too.
ALLOWED: Dict[Tuple[str, str], Tuple[Set[str], str]] = {
    ("verifiers/base.py", "stated_window"): ({"hedged", "stated_precision"}, "the rule itself: how a literal that has passed widens"),
    ("verifiers/base.py", "stated_threshold"): ({"hedged", "stated_precision", "stated_window"},
                                                "the one test: literal_is_claim decides before any of it counts"),
    ("verifiers/base.py", "window_for"): ({"hedged"}, "carries the flag to stated_threshold"),
    ("verifiers/base.py", "stated_tolerance_abs"): ({"stated_precision"}, "a definition; nothing in src calls it"),
    ("verifiers/astronomy.py", "verify_gravitational_scale"): (
        {"as_written", "claimed_escape_velocity_as_written", "hedged"},
        "splits the number from its unit and hands both to scale_base.compare, which tests them against the claim"),
    ("verifiers/chemistry.py", "_matches_at_precision"): ({LIT}, "called on a literal verify_phase_point has tested, or beside the claim's own"),
    ("verifiers/chemistry.py", "verify_phase_point"): ({LIT}, "literal_is_claim, then the literal can only narrow"),
    ("verifiers/economics.py", "verify_rule_of_72"): ({"claimed_doubling_years_as_written"}, "window_for, and the detail of a mismatch"),
    ("verifiers/finance.py", "verify_compound_interest"): ({"claimed_future_value_as_written", "literal_scale"},
                                                           "window_for, with the literal's scale as literal_factor"),
    ("verifiers/geometry.py", "_literal_key"): ({"_as_written"}, AS_WRITTEN_GEOMETRY),
    ("verifiers/grav_scale.py", "compare"): ({"as_written", "hedged"}, "passes them through to scale_base.compare"),
    ("verifiers/labor.py", "verify_annual_to_hourly"): ({"claimed_hourly_as_written", "literal_scale"},
                                                        "window_for, with the literal's scale as literal_factor"),
    ("verifiers/labor.py", "verify_hourly_to_annual"): ({"claimed_annual_as_written", "literal_scale"},
                                                        "window_for, with the literal's scale as literal_factor"),
    ("verifiers/mathematics.py", "<module>"): ({"stated_precision", "stated_window"}, "the import"),
    ("verifiers/mathematics.py", "verify_equality"): ({LIT, "hedged", "stated_precision", "stated_window"},
                                                      "the window is used only after literal_is_claim against the claimed side"),
    ("verifiers/mathematics.py", "verify_numeric"): ({LIT}, "window_for, and the detail of a confirm the test allowed"),
    ("verifiers/periodic_table.py", "verify_molar_mass"): ({LIT}, "window_for"),
    ("verifiers/physical_constants.py", "verify_physical_constant"): ({LIT}, "window_for, against the claim as written"),
    ("verifiers/physics.py", "verify_kinetic_energy_basic"): ({"claimed_kinetic_energy_as_written"}, "window_for"),
    ("verifiers/scale_base.py", "compare"): ({"as_written", "hedged"}, "stated_threshold, with the unit factor as literal_factor"),
    ("verifiers/units.py", "verify_conversion"): ({LIT}, "window_for"),
    # audit.py's reads at extraction build the literal from the claim: each takes the literal from the same match as the value
    ("audit.py", "_f"): ({"literal_scale"}, "reads the claimed value; the literal beside it is the same text"),
    ("audit.py", "_x_sqrt"): ({"stated_window"}, "declines a one-figure value; the literal and the claimed value are one match"),
    ("audit.py", "_x_equation_solution"): ({"stated_window"}, "the window _residual_params is told, read from the claimed value"),
    ("audit.py", "_x_equation_system"): ({"stated_precision", "stated_window"}, "the same, and the two values must share a precision"),
    ("audit.py", "_literal_holder"): ({LIT, "_as_written"}, "finds the literal for the hedge mark"),
}


def _sources() -> Dict[str, str]:
    paths = sorted((SRC / "verifiers").glob("*.py")) + [SRC / "audit.py"]
    return {p.relative_to(SRC).as_posix(): p.read_text(encoding="utf-8") for p in paths}


def walked() -> Tuple[Dict[Tuple[str, str], Set[str]], Set[Tuple[str, str, str]]]:
    found: Dict[Tuple[str, str], Set[str]] = {}
    unclaimed: Set[Tuple[str, str, str]] = set()
    for path, source in _sources().items():
        r = read(source)
        for fn, what in r.found:
            found.setdefault((path, fn), set()).add(what)
        unclaimed |= {(path, fn, name) for fn, name in r.unclaimed}
    return found, unclaimed


def test_no_reader_of_a_stated_literal_goes_unlisted():
    found, _ = walked()
    new = {k: sorted(v - ALLOWED.get(k, (set(), ""))[0]) for k, v in found.items() if v - ALLOWED.get(k, (set(), ""))[0]}
    assert not new, f"a new reader of a stated literal: send it through literal_is_claim, then list it: {new}"


def test_no_listed_reader_is_stale():
    found, _ = walked()
    stale = {k: sorted(v[0] - found.get(k, set())) for k, v in ALLOWED.items() if v[0] - found.get(k, set())}
    assert not stale, stale


def test_every_caller_of_window_for_gives_the_claimed_value():
    _, unclaimed = walked()
    assert unclaimed == {("verifiers/geometry.py", "verify_pythagorean", "window_for")}, unclaimed     # a yes or a no: no number


@pytest.mark.parametrize("source, what", [
    ('def f(spec):\n    return spec.get("claimed_literal")\n', LIT),
    ('def f(spec):\n    return spec["claimed_force_as_written"]\n', "claimed_force_as_written"),
    ('def f(spec):\n    return next(k for k in spec if k.endswith("_as_written"))\n', "_as_written"),
    ('def f(spec):\n    return bool(spec.get("hedged"))\n', "hedged"),
    ('from .base import stated_window\n', "stated_window"),
    ('def f(lit):\n    return base.stated_precision(lit)\n', "stated_precision"),
    ('def f(lit):\n    return stated_tolerance_abs(lit)\n', "stated_tolerance_abs"),
    ('def f(lit):\n    return literal_scale(lit)\n', "literal_scale"),
    ('def f(name, hedged=False):\n    return name\n', "hedged"),
], ids=["literal", "as-written", "as-written-pattern", "hedged", "import", "attribute", "tolerance", "scale", "parameter"])
def test_the_walk_fails_on_a_planted_reader(source, what):
    found = {w for _, w in read(source).found}
    assert what in found and what not in ALLOWED.get(("verifiers/planted.py", "f"), (set(), ""))[0]


@pytest.mark.parametrize("call", ['window_for(spec, "k", 1.0)', 'window_for(spec, "k", 1.0, claimed=None)',
                                  'base.window_for(spec, "k", 1.0, 1.0, 5.0)', 'stated_threshold("1.0", 1.0, 1e-9)'],
                         ids=["no-claim", "none", "attribute", "the-test-itself"])
def test_the_walk_fails_on_a_planted_caller_without_the_claim(call):
    assert read(f"def f(spec):\n    return {call}\n").unclaimed


def test_a_packet_built_by_an_extractor_is_not_a_read():
    source = 'def f(m):\n    """claimed_literal in a docstring."""\n    return {"claimed_literal": m, "x_as_written": m, "hedged": True}\n'
    assert not read(source).found


def test_a_finite_float_stays_a_finite_float():
    assert math.isfinite(base.literal_value("1.7976931348623157e308"))
