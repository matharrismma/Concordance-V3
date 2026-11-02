"""The derivation tier (run 2026-11-02-halt-and-order, step derivation-tier): the ONE home of every derivation the
source tests hand to verify_derivation that has 2 or more steps or a cycle.

Gathered, never authored. Each derivation below is the one its source test wrote, moved here as written; the
source test imports it from here (never the reverse), so it lives once and nothing imports a test module. A
listing two sources wrote alike is held once and both import it. README's document stays in README.md, read by
readme_document(); audit's texts are here, and the listing audit makes of each is read back by audit_listing().

rows() names each listing once:

    name              the expression that names it here
    steps             the listing exactly as it reaches verify_derivation
    used_by           the source tests that pass it (function node ids): the citation
    asserts           what those tests assert of it, each on the path they used: an exact verdict, a set of allowed
                      verdicts ({"in": [...]}) or not HOLDS ({"not": "HOLDS"}), and the pointers they assert
                      (broken_at, gap_at, error_at); empty when no source asserts a verdict
    measurement_only  True exactly when asserts is empty: measured, never scored
    slow              True when every test that passes it is slow-marked: scored only by the slow tier test
    doc / text        the document (compose, the MCP document path) or the text (audit) the path is given

A source that sealed (compose.seal_document(DOC, C), the default seal of the MCP tool) is scored here with
seal=False: the verdict is computed before anything is sealed. EXCLUDED holds the one derivation that needs a
stubbed verifier, with the reason. tests/test_derivation_tier.py scores the rows, and captures every listing the
sources pass (tests/fixtures/derivation_capture.py) and requires each to be held here or generated from a held
listing by every test that passed it.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]

SOURCES = (
    "tests/test_derivation_order_free.py", "tests/test_derivation_laws.py", "tests/test_refutations.py",
    "tests/test_binding.py", "tests/test_derivation_docs.py", "tests/test_compose_documents.py",
    "tests/test_review_fixes.py", "tests/test_bridges.py", "tests/test_receipt_page.py",
)
PATHS = ("derivation", "compose", "mcp", "mcp-document", "audit")


# ── the steps: tests/test_derivation_order_free.py and tests/test_derivation_laws.py ──────────────────────────
def num(sid, expr, value, **kw):
    step = {"id": sid, "domain": "mathematics", "claim": f"{expr} = {value}",
            "spec": {"mode": "numeric", "params": {"numeric_expr": expr, "claimed_value": value}}}
    step.update(kw)
    return step


def rect(sid, length, width, area, **kw):
    g = {"rect_width": width, "claimed_rect_area": area}
    if length is not None:
        g["rect_length"] = length
    step = {"domain": "geometry", "spec": {"GEOM_VERIFY": g}}
    if sid is not None:
        step["id"] = sid
    step.update(kw)
    return step


def err(sid, **kw):
    step = {"id": sid, "domain": "mathematics", "spec": {"mode": "no_such_mode", "params": {}}}
    step.update(kw)
    return step


def area_of(src):
    return {"GEOM_VERIFY.rect_length": f"{src}.actual_area"}


STAT = {"STAT_VERIFY": {"claimed_p": 0.05, "tail": "two-sided", "test": "z", "z": 1.96}}   # a p-value that holds
PROOF = "therefore the theorem is proven for all n"
AREA = {"GEOM_VERIFY.rect_length": "a.actual_area"}


# ── tests/test_derivation_order_free.py ───────────────────────────────────────────────────────────────────────
# Each listed dependency-sorted (every step after the steps it uses or binds from).
ORDER_FREE: Dict[str, List[Dict[str, Any]]] = {
    # a uses edge (c uses b) and a bind (b binds a), whose sources other orders list later
    "true chain": [rect("a", 4, 6, 24), rect("b", None, 1, 24, bind=AREA), num("c", "24*2", 48, uses=["b"])],
    "false dependency": [num("a", "2+2", 5), num("b", "3+3", 6, uses=["a"])],
    "bind from a false source": [rect("a", 4, 6, 99), rect("c", None, 1, 24, bind=AREA)],
    "bridge MISMATCH": [{"id": "s", "domain": "statistics", "claim": "observed p = 0.05", "spec": STAT},
                        num("m", "1+1", 2, claim=PROOF, uses=["s"])],
    "bridge INCOMPLETE": [rect("g", 4, 6, 24),
                          num("m", "24*2", 48, claim="the area scales as the square of the side", uses=["g"])],
    "erroring dependency": [err("e"), num("b", "3+3", 6, uses=["e"])],
}
# each step's effective outcome and whether it originates it, the same in every order
OUTCOMES = {
    "true chain": {"a": ("CONFIRMED", False), "b": ("CONFIRMED", False), "c": ("CONFIRMED", False)},
    "false dependency": {"a": ("BROKEN", True), "b": ("BROKEN", False)},
    "bind from a false source": {"a": ("BROKEN", True), "c": ("GAP", True)},
    "bridge MISMATCH": {"s": ("CONFIRMED", False), "m": ("BROKEN", True)},
    "bridge INCOMPLETE": {"g": ("CONFIRMED", False), "m": ("GAP", True)},
    "erroring dependency": {"e": ("ERROR", True), "b": ("ERROR", False)},
}
VERDICT = {"true chain": "HOLDS", "false dependency": "BROKEN", "bind from a false source": "BROKEN",
           "bridge MISMATCH": "BROKEN", "bridge INCOMPLETE": "INCOMPLETE", "erroring dependency": "SYSTEM_ERROR"}
POINTERS = (("BROKEN", "broken_at"), ("GAP", "gap_at"), ("ERROR", "error_at"))

SORTED = dict(ORDER_FREE, **{
    "mixed error and missing": [err("e"), num("b", "3+3", 6, uses=["e", "z"])],
    "reference to an absent id": [num("a", "2+2", 4, uses=["z"])],
    "false middle": [num("a", "2+2", 4), num("b", "3+3", 7, uses=["a"]), num("c", "1+1", 2, uses=["b"])],
    "synthetic bond memo": [
        {"id": "par", "domain": "public_finance", "spec": {"PUBFIN_VERIFY": {
            "net_proceeds": 12_000_000, "issuance_cost_pct": 0.02, "round_up_to": 5000, "claimed_par": 12_245_000}}},
        {"id": "debt", "domain": "public_finance", "bind": {"PUBFIN_VERIFY.par": "par.actual_par"},
         "spec": {"PUBFIN_VERIFY": {"par": 0, "annual_rate": 0.045, "term_months": 240, "interest_only_months": 24,
                                    "claimed_monthly_pi": 82815.95, "claimed_total_interest": 6745294.80}}},
        {"id": "dscr", "domain": "real_estate", "bind": {"RE_VERIFY.annual_debt_service": "debt.annual_pi"},
         "spec": {"RE_VERIFY": {"net_operating_income": 1_500_000, "annual_debt_service": 0,
                                "claimed_dscr": 1.5093}}}],
    "fault locus": [
        {"id": "n", "domain": "mathematics",
         "spec": {"mode": "numeric", "params": {"numeric_expr": "12000000*0.02", "claimed_value": 240000}}},
        {"id": "par", "domain": "public_finance", "uses": ["n"], "spec": {"PUBFIN_VERIFY": {
            "net_proceeds": 12_000_000, "issuance_cost_pct": 0.02, "round_up_to": 5000, "claimed_par": 12_245_000}}},
        {"id": "bad", "domain": "public_finance", "bind": {"PUBFIN_VERIFY.par": "par.actual_par"},
         "spec": {"PUBFIN_VERIFY": {"par": 0, "annual_rate": 0.045, "term_months": 240, "interest_only_months": 24,
                                    "claimed_monthly_pi": 82900}}}],
})

REPEATED = {
    # measured at 45fcd3c, each stays as named
    "a false and a true a, b uses a": ([num("a", "2+2", 5), num("a", "2+2", 4), num("b", "3+3", 6, uses=["a"])],
                                       "BROKEN"),
    "two s, m proof uses s": ([{"id": "s", "domain": "statistics", "claim": "observed p = 0.001",
                                "spec": {"STAT_VERIFY": {}}}] * 2 + [num("m", "1+1", 2, claim=PROOF, uses=["s"])],
                              "BROKEN"),
    # the seam runs against EACH step carrying s, wherever it is listed
    "s statistics, s geometry, m proof uses s": ([{"id": "s", "domain": "statistics", "spec": STAT},
                                                 rect("s", 4, 6, 24), num("m", "1+1", 2, claim=PROOF, uses=["s"])],
                                                "BROKEN"),
    "two true a, nobody uses a": ([num("a", "2+2", 4), num("a", "3+3", 6)], "INCOMPLETE"),
    # both a agree, and the bind is still unresolved: nothing can say which a is meant
    "two true a, b binds a": ([rect("a", 4, 6, 24), rect("a", 4, 6, 24), rect("b", None, 1, 24, bind=AREA)],
                              "INCOMPLETE"),
}

# test_the_reversed_two_step_derivation_holds: [a, b uses a], and the same two listed [b, a]
TWO_STEP = [{"id": "a", "domain": "mathematics", "claim": "2+2=4",
             "spec": {"mode": "equality", "params": {"expr_a": "2+2", "expr_b": "4"}}},
            {"id": "b", "domain": "mathematics", "claim": "4*3=12", "uses": ["a"],
             "spec": {"mode": "equality", "params": {"expr_a": "4*3", "expr_b": "12"}}}]
# a cycle of holding steps (test_a_cycle_of_holding_steps_originates_its_gap_at_every_member, and the HOLDS-iff test)
CYCLE = [num("a", "2+2", 4, uses=["b"]), num("b", "3+3", 6, uses=["a"])]
# test_a_cycle_whose_members_hold_stays_incomplete_with_the_cycle_named; SELF_CYCLE also in test_derivation_laws.py
SELF_CYCLE = [num("a", "2+2", 4, uses=["a"])]
CYCLE_AND_RESTING = [num("a", "2+2", 4, uses=["b"]), num("b", "3+3", 6, uses=["a"]), num("c", "1+1", 2, uses=["a"])]
# test_a_cycle_with_a_false_member_is_broken_in_every_order; FALSE_SELF_CYCLE also in the HOLDS-iff test
FALSE_SELF_CYCLE = [num("a", "2+2", 5, uses=["a"])]
FALSE_CYCLE = [num("a", "2+2", 5, uses=["b"]), num("b", "3+3", 6, uses=["a"])]
# the HOLDS-iff test's own case: our failure beside a false step
ERROR_BESIDE_FALSE = [err("e"), num("b", "2+2", 5)]
# test_a_default_id_colliding_with_an_explicit_one_is_never_holds
DEFAULT_ID_COLLISION = [rect("s1", 5, 6, 30), rect(None, 4, 6, 24),
                        rect("b", None, 1, 24, bind={"GEOM_VERIFY.rect_length": "s1.actual_area"})]


# ── tests/test_derivation_laws.py ─────────────────────────────────────────────────────────────────────────────
DERIVATIONS = [
    ORDER_FREE["true chain"],     # written in both files alike; held once
    [num("a", "2+2", 5), num("b", "3+3", 6, uses=["a"]), num("c", "1+1", 2, uses=["b"])],
    [rect("a", 4, 6, 99), rect("c", None, 1, 24, bind=area_of("a")), err("e")],
    [num("a", "2+2", 4, uses=["b"]), num("b", "3+3", 6, uses=["a"]), num("c", "1+1", 2, uses=["a", "z"])],
    [rect("x", None, 1, 24, bind=area_of("y")), rect("y", None, 1, 24, bind=area_of("x")), num("d", "1+1", 2)],
    [num("a", "2+2", 4), num("a", "3+3", 6), num("b", "1+1", 2, uses=["a"])],
    [{"id": "s", "domain": "statistics", "spec": STAT},
     num("m", "0.05*1", 0, claim=PROOF, uses=["s"], bind={"params.claimed_value": "s.actual_p"})],
]

PART_WAY = [
    # a chain with a bind: listed against its edges it settles one link a pass
    [rect("a", 4, 6, 24), rect("b", None, 1, 24, bind=area_of("a")), num("c", "24*2", 48, uses=["b"]),
     num("d", "48+2", 50, uses=["c"])],
    # a false step behind a bind, beside our failure: cut off before the break, it must not read SYSTEM_ERROR
    [rect("y", 4, 6, 24), rect("x", None, 1, 99, bind=area_of("y")), err("e")],
]


def chain_of(k):
    """s0, s1 uses s0, ..., s(k-1) uses s(k-2): the chain test_the_closure_halts_by_settling_within_k_plus_1_passes
    (k = 6) and test_a_reverse_listed_chain_of_1500_steps_settles (k = 1,500) list forward and in reverse."""
    return [num(f"s{i}", f"{i}+1", i + 1, uses=[f"s{i - 1}"] if i else []) for i in range(k)]


CHAIN_6 = chain_of(6)
CHAIN_1500 = chain_of(1500)
# test_each_verifier_runs_exactly_once_or_never_when_its_bind_stays_unresolved, beside DERIVATIONS
BIND_CHAIN_4 = [rect("a", 4, 6, 24), rect("b", None, 1, 24, bind=area_of("a")),
                rect("c", None, 2, 48, bind=area_of("b")), num("d", "48*1", 48, uses=["c"])]
SELF_BIND = [rect("z", None, 1, 24, bind=area_of("z"))]
# test_trace_distance_and_stands_on_are_computed_without_recursion
TRACE_CYCLE = [num("a", "2+2", 4, uses=["b"]), num("b", "3+3", 6, uses=["a"]), num("c", "1+1", 2, uses=["a"]),
               num("d", "1+2", 3)]
# test_the_halting_record_rides_in_the_response_only: listed against its edge, and the document made of it
HALTING = [num("b", "3+3", 6, uses=["a"]), num("a", "2+2", 4)]
HALTING_DOC = {"title": "listed against its edge", "steps": HALTING}


def repeated_body(k):
    """checker-22's body, scaled down (test_a_repeated_id_costs_work_in_proportion_to_the_body): k steps all
    carrying id 'a', each using 'a', across domains (case variants included). EXCLUDED: its test stubs the
    verifier."""
    doms = ["statistics", "mathematics", "Statistics", "STATISTICS"]
    return [{"id": "a", "domain": doms[i % 4], "uses": ["a"], "spec": {"n": i}} for i in range(k)]


# ── tests/test_refutations.py ─────────────────────────────────────────────────────────────────────────────────
PAR = {"id": "par", "domain": "public_finance", "spec": {"PUBFIN_VERIFY": {
    "net_proceeds": 12_000_000, "issuance_cost_pct": 0.02, "round_up_to": 5000, "claimed_par": 12_245_000}}}


def debt(sid, claim):
    return {"id": sid, "domain": "public_finance", "bind": {"PUBFIN_VERIFY.par": "par.actual_par"},
            "spec": {"PUBFIN_VERIFY": {"par": 0, "annual_rate": 0.045, "term_months": 240,
                                       "interest_only_months": 24, "claimed_monthly_pi": claim}}}


OTDR = [PAR, debt("tight", 82816.00), debt("bad", 82900)]       # test_margin_and_trace_read_like_an_otdr
CLEAN = [PAR, debt("ok", 82815.95)]                               # that test, and test_energy_and_the_valve
EDGE = [PAR, debt("edge", 82816.00)]                              # test_energy_and_the_valve
MISS = [PAR, debt("bad", 82900)]                                  # test_energy_and_the_valve
FAULT_LOCUS = SORTED["fault locus"]       # test_trace_strata_and_connections_locate_the_fault wrote it alike


# ── tests/test_binding.py, and the binding docstring test in tests/test_derivation_docs.py ────────────────────
def _step(sid, domain, spec, **extra):
    d = {"id": sid, "domain": domain, "spec": spec}
    d.update(extra)
    return d


# a1 confirms a 4x6 rectangle (area 24); a2's rect_length is BUILT from a1's output
BIND = [
    _step("a1", "geometry", {"GEOM_VERIFY": {"rect_length": 4, "rect_width": 6,
                                             "claimed_rect_area": 24}}),
    _step("a2", "geometry", {"GEOM_VERIFY": {"rect_width": 1, "claimed_rect_area": 24}},
          bind={"GEOM_VERIFY.rect_length": "a1.actual_area"}),
]
# a1 is WRONG (4x6 = 24, not 99); the same a2
BIND_FALSE_SOURCE = [
    _step("a1", "geometry", {"GEOM_VERIFY": {"rect_length": 4, "rect_width": 6,
                                             "claimed_rect_area": 99}}),
    _step("a2", "geometry", {"GEOM_VERIFY": {"rect_width": 1, "claimed_rect_area": 24}},
          bind={"GEOM_VERIFY.rect_length": "a1.actual_area"}),
]
# a plain two-step derivation with no bind
NO_BIND = [
    _step("a1", "mathematics", {"mode": "equality", "params": {"expr_a": "2+2", "expr_b": "4"}}),
    _step("a2", "mathematics", {"mode": "equality", "params": {"expr_a": "3*3", "expr_b": "9"}}),
]


# ── tests/test_derivation_docs.py ─────────────────────────────────────────────────────────────────────────────
def readme_document():
    """README's Documents section and the document its curl example sends."""
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    sections = [s for s in text.split("\n## ") if s.startswith("Documents")]
    assert len(sections) == 1
    body = re.search(r"-d '(\{.*?\})'", sections[0], re.S)
    assert body, "the Documents section's curl example"
    return sections[0], json.loads(body.group(1))["document"]


AUDIT_TEXTS = ("A rectangle 4 by 6 has area 25, so 25 x 2 = 50.", "2 + 2 = 5 and 3 + 3 = 7.")


def audit_listing(text):
    """The listing audit.audit hands verify_derivation for `text`, read back as test_derivation_docs.py's audit
    test reads it: verify_derivation wrapped for the one call, then put back."""
    from concordance import audit as A
    from concordance import derivation as D
    from concordance.config import EngineConfig
    seen = []
    real = D.verify_derivation

    def captured(steps):
        seen.append(copy.deepcopy(steps))
        return real(steps)

    D.verify_derivation = captured
    try:
        A.audit(text, EngineConfig(skip_schema_validation=True), seal=False)
    finally:
        D.verify_derivation = real
    (listed,) = seen
    return listed


# ── tests/test_compose_documents.py ───────────────────────────────────────────────────────────────────────────
PF = "PUBFIN_VERIFY"
COMPOSE_DOC = {"title": "Synthetic bond memo", "steps": [
    {"id": "par", "domain": "public_finance", "label": "gross-up",
     "spec": {PF: {"net_proceeds": 12_000_000, "issuance_cost_pct": 0.02, "round_up_to": 5000, "claimed_par": 12_245_000}}},
    {"id": "debt", "domain": "public_finance", "label": "P&I after IO",
     "spec": {PF: {"par": 0, "annual_rate": 0.045, "term_months": 240, "interest_only_months": 24,
                   "claimed_monthly_pi": 82815.95, "claimed_total_interest": 6745294.80}},
     "bind": {"PUBFIN_VERIFY.par": "par.actual_par"}},
    {"id": "dscr", "domain": "real_estate", "label": "coverage",
     "spec": {"RE_VERIFY": {"net_operating_income": 1_500_000, "annual_debt_service": 0, "claimed_dscr": 1.5093}},
     "bind": {"RE_VERIFY.annual_debt_service": "debt.annual_pi"}},
], "text": "Par {par}; P&I {debt}; DSCR {dscr}."}
# test_an_upstream_change_breaks_the_root_and_starves_what_rested_on_it: the gross-up changed
COMPOSE_DOC_UPSTREAM_CHANGED = copy.deepcopy(COMPOSE_DOC)
COMPOSE_DOC_UPSTREAM_CHANGED["steps"][0]["spec"][PF]["issuance_cost_pct"] = 0.03


# ── tests/test_review_fixes.py ────────────────────────────────────────────────────────────────────────────────
# step 'a' is a domain with no verifier; 'b' genuinely CONFIRMS on its own and builds on it
GAP_DEPENDENCY = [
    {"id": "a", "domain": "__no_such_domain__", "spec": {}},
    {"id": "b", "domain": "mathematics", "uses": ["a"],
     "spec": {"mode": "equality",
              "params": {"expr_a": "x + x", "expr_b": "2*x", "variables": ["x"]}}},
]


# ── tests/test_bridges.py ─────────────────────────────────────────────────────────────────────────────────────
BRIDGE_PROOF = [
    {"id": "s1", "domain": "statistics", "claim": "observed p = 0.001",
     "spec": {"STAT_VERIFY": {}}},
    {"id": "s2", "domain": "mathematics", "claim": "therefore the theorem is proven for all n",
     "uses": ["s1"], "spec": {"mode": "identity", "params": {}}},
]


# ── tests/test_receipt_page.py ────────────────────────────────────────────────────────────────────────────────
RECEIPT_STEP = {"id": "m", "domain": "real_estate", "spec": {"RE_VERIFY": {
    "loan_principal": 12_000_000, "annual_rate": 0.045, "loan_term_months": 240, "claimed_monthly_payment": 75917.93}}}
STEP = RECEIPT_STEP
# c uses b, b uses a, listed top-down
RECEIPT_REVERSE_CHAIN = [{**STEP, "id": "c", "uses": ["b"]}, {**STEP, "id": "b", "uses": ["a"]}, {**STEP, "id": "a"}]
# [a, b uses a, c uses b]: every id carried by one step, each listed after what it uses
RECEIPT_SORTED_CHAIN = [{**STEP, "id": "a"}, {**STEP, "id": "b", "uses": ["a"]}, {**STEP, "id": "c", "uses": ["b"]}]
# wider, still sorted with unique ids: steps using several
RECEIPT_WIDE = [{**STEP, "id": "a"}, {**STEP, "id": "b"}, {**STEP, "id": "c", "uses": ["a", "b"]},
                {**STEP, "id": "d", "uses": ["c", "a"]}, {**STEP, "id": "e", "uses": ["d"]}]
# [x, a, a uses x, b uses a]: two steps carry a
RECEIPT_REPEATED = [{**STEP, "id": "x"}, {**STEP, "id": "a"}, {**STEP, "id": "a", "uses": ["x"]},
                    {**STEP, "id": "b", "uses": ["a"]}]
# [a uses b, b uses a]
RECEIPT_CYCLE = [{**STEP, "id": "a", "uses": ["b"]}, {**STEP, "id": "b", "uses": ["a"]}]
del STEP


# ── the rows ──────────────────────────────────────────────────────────────────────────────────────────────────
_OF, _LAWS, _REF, _BIND, _DOCS, _COMP, _FIX, _BRI, _PAGE = (s + "::" for s in SOURCES)
_EVERY = _OF + "test_every_listing_order_gives_the_same_fields_by_step_id"
_ORACLE = _OF + "test_a_dependency_sorted_listing_returns_every_field_45fcd3c_returns"
_IFF = _OF + "test_holds_if_and_only_if_no_step_originates_a_break_a_gap_or_an_error"
_WIRING = _OF + "test_verify_derivation_computes_through_transfer_meet_and_readout"
_LAWS3 = (_LAWS + "test_each_verifier_runs_exactly_once_or_never_when_its_bind_stays_unresolved",
          _LAWS + "test_order_replica_every_evaluation_order_gives_the_same_result",
          _LAWS + "test_the_closure_halts_by_settling_within_k_plus_1_passes")
_README3 = (_DOCS + "test_readme_documents_say_a_step_binds_to_a_step_listed_anywhere",
            _DOCS + "test_compose_docstring_says_a_step_binds_to_a_step_listed_anywhere",
            _DOCS + "test_architecture_matches_its_generator_and_says_what_compose_does")
_AUDIT = _DOCS + "test_audit_says_its_text_order_is_kept_for_reading_not_needed_for_the_verdict"
_COMPOSE4 = (_COMP + "test_a_chained_document_seals_as_one_root_that_rehashes",
             _COMP + "test_a_document_can_stand_on_a_document_and_walk_back",
             _COMP + "test_tree_page_renders_steps_binds_and_parents",
             _COMP + "test_verify_tool_takes_a_document_and_validates_its_packets")

EXCLUDED = [
    {"name": "repeated_body(800)", "steps": repeated_body(800),
     "used_by": [_LAWS + "test_a_repeated_id_costs_work_in_proportion_to_the_body"],
     "reason": "needs a stubbed verifier: its test replaces derivation.verify_step with a stub that confirms every "
               "step (each spec is {'n': i}, no real packet), so its verdict is the stub's, not the verifiers'"},
]


def _a(tests, path, verdict, **pointers):
    return {"tests": [tests] if isinstance(tests, str) else list(tests), "path": path, "verdict": verdict,
            "pointers": pointers}


def _row(name, steps, used_by, *asserts, slow=False, doc=None, text=None):
    return {"name": name, "steps": steps, "used_by": sorted(set([used_by] if isinstance(used_by, str) else used_by)),
            "asserts": list(asserts), "measurement_only": not asserts, "slow": slow, "doc": doc, "text": text}


def _first_originators(steps, outcomes):
    """The pointers test_every_listing_order_gives_the_same_fields_by_step_id asserts for a listing: each names
    the first listed step originating its kind, with each step's outcome and origin asserted as OUTCOMES."""
    return {field: next((s["id"] for s in steps if outcomes[s["id"]] == (k, True)), None) for k, field in POINTERS}


def _build() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    # test_derivation_order_free.py: ORDER_FREE, scored by the every-order test; DERIVATIONS[0] is "true chain"
    for name, steps in ORDER_FREE.items():
        used = (_EVERY, _ORACLE, _IFF, _WIRING) + (_LAWS3 if name == "true chain" else ())
        out.append(_row(f"ORDER_FREE[{name!r}]", steps, used,
                        _a(_EVERY, "derivation", VERDICT[name], **_first_originators(steps, OUTCOMES[name]))))
    # SORTED's own rows ("reference to an absent id" is one step and no cycle: not a tier derivation)
    out.append(_row("SORTED['mixed error and missing']", SORTED["mixed error and missing"],
                    (_ORACLE, _IFF, _OF + "test_an_error_beneath_a_missing_reference_stays_where_45fcd3c_put_it"),
                    _a(_OF + "test_an_error_beneath_a_missing_reference_stays_where_45fcd3c_put_it", "derivation",
                       "SYSTEM_ERROR", error_at="e", gap_at=None, broken_at=None)))
    for name in ("false middle", "synthetic bond memo"):
        out.append(_row(f"SORTED[{name!r}]", SORTED[name], (_ORACLE, _IFF)))
    out.append(_row("SORTED['fault locus']", FAULT_LOCUS,
                    (_ORACLE, _IFF, _REF + "test_trace_strata_and_connections_locate_the_fault")))
    two = _OF + "test_the_reversed_two_step_derivation_holds"
    out.append(_row("TWO_STEP", TWO_STEP, two, _a(two, "derivation", "HOLDS")))
    out.append(_row("TWO_STEP, listed in reverse", list(reversed(TWO_STEP)), two, _a(two, "derivation", "HOLDS")))
    held = _OF + "test_a_cycle_of_holding_steps_originates_its_gap_at_every_member"
    out.append(_row("CYCLE", CYCLE, (held, _IFF),
                    _a(held, "derivation", "INCOMPLETE", gap_at=CYCLE[0]["id"], broken_at=None, error_at=None)))
    named = _OF + "test_a_cycle_whose_members_hold_stays_incomplete_with_the_cycle_named"
    out.append(_row("SELF_CYCLE", SELF_CYCLE, (named, _LAWS + "test_trace_distance_and_stands_on_are_computed_without_recursion"),
                    _a(named, "derivation", "INCOMPLETE")))
    out.append(_row("CYCLE_AND_RESTING", CYCLE_AND_RESTING, named,
                    _a(named, "derivation", "INCOMPLETE", gap_at={"in": ["a", "b"]})))
    false = _OF + "test_a_cycle_with_a_false_member_is_broken_in_every_order"
    out.append(_row("FALSE_SELF_CYCLE", FALSE_SELF_CYCLE, (false, _IFF), _a(false, "derivation", "BROKEN", broken_at="a")))
    out.append(_row("FALSE_CYCLE", FALSE_CYCLE, false, _a(false, "derivation", "BROKEN", broken_at="a")))
    out.append(_row("ERROR_BESIDE_FALSE", ERROR_BESIDE_FALSE, _IFF))
    rep = _OF + "test_a_repeated_id_is_never_holds"
    for name, (steps, verdict) in REPEATED.items():
        ptr = {"broken_at": "m"} if steps[-1].get("claim") == PROOF else {}
        out.append(_row(f"REPEATED[{name!r}]", steps, (rep, _IFF) if name == "two true a, nobody uses a" else rep,
                        _a(rep, "derivation", verdict, **ptr)))
    dflt = _OF + "test_a_default_id_colliding_with_an_explicit_one_is_never_holds"
    out.append(_row("DEFAULT_ID_COLLISION", DEFAULT_ID_COLLISION, dflt, _a(dflt, "derivation", {"not": "HOLDS"})))
    # test_derivation_laws.py: no verdict asserted, save the reverse-listed chains and the halting record
    for i, steps in enumerate(DERIVATIONS[1:], 1):
        out.append(_row(f"DERIVATIONS[{i}]", steps, _LAWS3))
    halts = _LAWS + "test_the_closure_halts_by_settling_within_k_plus_1_passes"
    out.append(_row("chain_of(6)", CHAIN_6, halts))
    out.append(_row("chain_of(6), listed in reverse", list(reversed(CHAIN_6)), halts, _a(halts, "derivation", "HOLDS")))
    once = _LAWS3[0]
    out.append(_row("BIND_CHAIN_4", BIND_CHAIN_4, once))
    out.append(_row("SELF_BIND", SELF_BIND, once))
    cap = _LAWS + "test_a_cap_that_stops_part_way_keeps_what_settled_and_never_says_more"
    for i, steps in enumerate(PART_WAY):
        out.append(_row(f"PART_WAY[{i}]", steps, cap))
    out.append(_row("TRACE_CYCLE", TRACE_CYCLE, _LAWS + "test_trace_distance_and_stands_on_are_computed_without_recursion"))
    rides = _LAWS + "test_the_halting_record_rides_in_the_response_only"
    out.append(_row("HALTING", HALTING, rides, _a(rides, "derivation", "HOLDS"), _a(rides, "compose", "HOLDS"),
                    doc=HALTING_DOC))
    long = _LAWS + "test_a_reverse_listed_chain_of_1500_steps_settles"
    out.append(_row("chain_of(1500), listed in reverse", list(reversed(CHAIN_1500)), long,
                    _a(long, "derivation", "HOLDS"), slow=True))
    # test_refutations.py: trace, budget and energy asserted, never a verdict
    margin, energy = _REF + "test_margin_and_trace_read_like_an_otdr", _REF + "test_energy_and_the_valve"
    out.append(_row("OTDR", OTDR, margin))
    out.append(_row("CLEAN", CLEAN, (margin, energy)))
    out.append(_row("EDGE", EDGE, energy))
    out.append(_row("MISS", MISS, energy))
    # test_binding.py
    for name, steps, test, verdict in (
            ("BIND", BIND, "test_bind_builds_an_input_from_a_confirmed_output", "HOLDS"),
            ("BIND_FALSE_SOURCE", BIND_FALSE_SOURCE, "test_bind_to_a_broken_source_does_not_fabricate", "BROKEN"),
            ("NO_BIND", NO_BIND, "test_no_bind_is_unchanged", "HOLDS")):
        out.append(_row(name, steps, _BIND + test, _a(_BIND + test, "derivation", verdict)))
    # test_derivation_docs.py: README's document as written and listed against its edges, through compose
    doc = readme_document()[1]
    rev = dict(copy.deepcopy(doc), steps=list(reversed(doc["steps"])))
    out.append(_row("README document", doc["steps"], _README3, _a(_README3, "compose", "HOLDS"), doc=doc))
    out.append(_row("README document, listed in reverse", rev["steps"], _README3, _a(_README3, "compose", "HOLDS"),
                    doc=rev))
    after = _DOCS + "test_binding_docstring_holds_with_the_source_listed_after_its_user"
    out.append(_row("BIND, listed in reverse", list(reversed(BIND)), after, _a(after, "derivation", "HOLDS")))
    out.append(_row("BIND_FALSE_SOURCE, listed in reverse", list(reversed(BIND_FALSE_SOURCE)), after,
                    _a(after, "derivation", "BROKEN")))
    for i, text in enumerate(AUDIT_TEXTS):
        listed = audit_listing(text)
        out.append(_row(f"AUDIT_TEXTS[{i}], as audit lists it", listed, _AUDIT, _a(_AUDIT, "audit", "BROKEN"),
                        _a(_AUDIT, "derivation", "BROKEN", broken_at=listed[0]["id"]), text=text))
        # the last text's reverse listing names its last claim (the assertion after the test's loop)
        ptr = {"broken_at": listed[-1]["id"]} if i == len(AUDIT_TEXTS) - 1 else {}
        out.append(_row(f"AUDIT_TEXTS[{i}], listed in reverse", list(reversed(listed)), _AUDIT,
                        _a(_AUDIT, "derivation", "BROKEN", **ptr), text=text))
    # test_compose_documents.py
    out.append(_row("COMPOSE_DOC", COMPOSE_DOC["steps"], _COMPOSE4, _a(_COMPOSE4[0], "compose", "HOLDS"),
                    _a(_COMPOSE4[3], "mcp-document", "HOLDS"), doc=COMPOSE_DOC))
    up = _COMP + "test_an_upstream_change_breaks_the_root_and_starves_what_rested_on_it"
    out.append(_row("COMPOSE_DOC_UPSTREAM_CHANGED", COMPOSE_DOC_UPSTREAM_CHANGED["steps"], up,
                    _a(up, "compose", "BROKEN"), doc=COMPOSE_DOC_UPSTREAM_CHANGED))
    # test_review_fixes.py, test_bridges.py
    gap = _FIX + "test_derivation_error_or_gap_dependency_is_never_rendered_broken"
    out.append(_row("GAP_DEPENDENCY", GAP_DEPENDENCY, gap,
                    _a(gap, "derivation", {"in": ["INCOMPLETE", "SYSTEM_ERROR"]})))
    seam = _BRI + "test_derivation_breaks_at_the_seam_when_a_p_value_is_claimed_as_proof"
    out.append(_row("BRIDGE_PROOF", BRIDGE_PROOF, seam, _a(seam, "derivation", "BROKEN", broken_at="s2")))
    # test_receipt_page.py: the MCP verify tool with seal=False
    rev_t = _PAGE + "test_receipt_page_stands_on_matches_the_trace_for_a_reverse_listed_chain"
    sorted_t = _PAGE + "test_receipt_page_renders_a_sorted_chain_of_unique_ids_exactly_as_at_d47d692"
    out.append(_row("RECEIPT_REVERSE_CHAIN", RECEIPT_REVERSE_CHAIN, rev_t, _a(rev_t, "mcp", "HOLDS")))
    out.append(_row("RECEIPT_SORTED_CHAIN", RECEIPT_SORTED_CHAIN, sorted_t, _a(sorted_t, "mcp", "HOLDS")))
    out.append(_row("RECEIPT_WIDE", RECEIPT_WIDE, sorted_t))
    out.append(_row("RECEIPT_REPEATED", RECEIPT_REPEATED, _PAGE + "test_receipt_page_repeated_id_stands_on_reads_as_the_trace"))
    out.append(_row("RECEIPT_CYCLE", RECEIPT_CYCLE, _PAGE + "test_receipt_page_cycle_stands_on_reads_as_the_trace"))
    return out


_ROWS: Optional[List[Dict[str, Any]]] = None


def rows() -> List[Dict[str, Any]]:
    """Every row, built once (the audit rows run audit.audit on their text, nothing sealed)."""
    global _ROWS
    if _ROWS is None:
        _ROWS = _build()
    return _ROWS


def run(row: Dict[str, Any], path: str) -> Dict[str, Any]:
    """The row through the path its source used, nothing sealed: verify_derivation; compose.seal_document with
    seal=False; the MCP verify tool with seal=False, given the steps or the document; or audit.audit."""
    from concordance.config import EngineConfig
    if path == "derivation":
        from concordance import derivation
        return derivation.verify_derivation(copy.deepcopy(row["steps"]))
    if path == "compose":
        from concordance import compose
        return compose.seal_document(copy.deepcopy(row["doc"]), EngineConfig(), seal=False)
    if path in ("mcp", "mcp-document"):
        from concordance.mcp.server import _call_tool
        given = {"steps": copy.deepcopy(row["steps"])} if path == "mcp" else {"document": copy.deepcopy(row["doc"])}
        return _call_tool("verify", dict(given, seal=False), EngineConfig())
    if path == "audit":
        from concordance import audit
        return audit.audit(row["text"], EngineConfig(skip_schema_validation=True), seal=False)
    raise ValueError(f"no such path: {path}")
