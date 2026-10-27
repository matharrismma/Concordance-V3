"""The schema a caller FILLS must describe the question, not the answer (2026-10-27).

`_analyse` collects a deliberately wide field set so `validate_steps` never rejects a valid packet —
but that set includes keys a verify_* function writes into its result `data` dict (actual_*, diff,
a_sq_plus_b_sq, …). `schema_for` is read by the edge translator and by find_verifier to BUILD a
packet, so it must serve only the fields a claim provides (those a verifier reads from its spec).

The geometry domain is the proof case: before the fix its schema advertised a_sq_plus_b_sq /
actual_right_triangle / CONFIRMED, so the translator asked the model to fill the answer. These pin
that the input schema is clean for geometry and that validation stays loose for every golden.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from concordance import schema, verifiers as V  # noqa: E402


def _input_props(domain):
    s = schema.schema_for(domain)
    ak = s["artifact_key"] or "SPEC"
    return set(s["packet"]["properties"][ak]["properties"])


def test_geometry_schema_serves_inputs_not_outputs():
    props = _input_props("geometry")
    # the question's fields are present
    for need in ("pyth_a", "pyth_b", "pyth_c", "claimed_right_triangle",
                 "rect_length", "rect_width", "claimed_rect_area", "circle_radius",
                 "claimed_circle_area", "polygon_n", "sphere_radius"):
        assert need in props, f"missing input field {need}"
    # the answer's fields are gone
    for banned in ("a_sq_plus_b_sq", "c_sq", "actual_right_triangle", "actual_area",
                   "actual_perimeter", "actual_surface_area", "CONFIRMED", "diff"):
        assert banned not in props, f"computed-output key leaked into the input schema: {banned}"


def test_every_domain_has_a_nonempty_input_schema():
    V._load_plugins()
    for mod in sorted({v.rsplit(".", 1)[-1] for v in V.VERIFIERS.values()}):
        if mod in ("mathematics", "math"):
            continue
        props = _input_props(mod)
        assert props, f"{mod} has an empty input schema (nothing to fill)"


def test_real_estate_keeps_its_claim_inputs():
    props = _input_props("real_estate")
    assert "loan_principal" in props   # the field the mortgage golden fills
