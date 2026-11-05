"""THE FLOAT EDGE: band() never counts a value that is not finite as inside, and an ERROR stays an ERROR.

A claim that is not finite against a finite recomputed value is proof the claim is false: MISMATCH, which reads BROKEN.
A recomputed value that is not finite is could-not-compare: ERROR, which reads SYSTEM_ERROR and never BROKEN, and the same
goes for a window that is not finite around a finite claim, which would hold every number.

That only means something if nothing downstream undoes it, so the walk here reads every consumer of a band result, and
of bound() and merge_checks(), which fold into the same statuses, in src/concordance/verifiers. It follows each function
with the result assumed to be an ERROR. Reaching a confirm(), or a mismatch() nothing else proves, turns could-not-compare
into a pass or a BROKEN: the two defects, "tests only for MISMATCH" and "rewraps a non-pass". A mismatch() that only some
other check reaches is that check's proof, and stands. Planted consumers prove the walk can fail.
"""
from __future__ import annotations

import ast
import math
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import pytest

ROOT = Path(__file__).resolve().parents[1]
VERIFIERS = ROOT / "src" / "concordance" / "verifiers"
sys.path.insert(0, str(ROOT / "tools"))

import benchmark  # noqa: E402
from concordance.verifiers import base  # noqa: E402

INF, NAN = float("inf"), float("nan")
TOP = sys.float_info.max
MADE_BY = frozenset({"band", "bound", "merge_checks"})

# Every consumer, by file, function and name. A new one fails until someone reads it and lists it here.
CONSUMERS: Set[str] = {
    "approximation.py:verify_get_close:b",
    "approximation.py:verify_get_close:m",
    "biology.py:verify_primer:merged",
    "biology.py:verify_primer:r",
    "chess.py:verify_position:r",
    "computer_science.py:verify_runtime_complexity:b",
    "economics.py:verify_rule_of_72:r",
    "electrical.py:verify_reflection_coefficient:merged",
    "elliptic_curves.py:verify_l_value:b",
    "ephemeris.py:verify_sunrise_sunset:merged",
    "game_theory.py:verify_iterated:merged",
    "game_theory.py:verify_population:b",
    "geography.py:verify_geodesic_distance:r",
    "geometry.py:verify_circle_properties:m",
    "geometry.py:verify_cube_properties:m",
    "geometry.py:verify_cylinder_properties:m",
    "geometry.py:verify_rectangle_properties:m",
    "geometry.py:verify_sphere_properties:m",
    "history_chronology.py:verify_year_arithmetic:r",
    "linear_algebra.py:_array_bands:m",
    "linguistics.py:verify_word_count:r",
    "mathematics.py:run:r",
    "mathematics.py:verify_equality:bd",
    "mathematics.py:verify_numeric:bd",
    "medicine.py:verify_bmi:b",
    "medicine.py:verify_drug_dosage:r",
    "molecular_geometry.py:verify_vsepr:angle_band",
    "music_theory.py:verify_interval_semitones:r",
    "physical_constants.py:verify_constant_relation:r",
    "physical_constants.py:verify_physical_constant:r",
    "physics.py:run:r",
    "physics.py:verify_conservation:merged",
    "physics.py:verify_named_conservation:r",
    "physics.py:verify_named_conservation:result",
    "public_finance.py:verify_abatement_schedule:r",
    "retrieval.py:verify_recall_of_known:r",
    "spec.py:prove:r_false",
    "spec.py:prove:r_true",
    "spec.py:run_check:r",
    "spectral.py:verify_diagonalize:b",
    "spectral.py:verify_fourier_convolution:b",
    "statistics.py:verify_confidence_interval:m",
    "statistics.py:verify_measurement_consistency:b",
    "statistics.py:verify_measurement_consistency:m",
    "statistics.py:verify_pvalue_calibration:m",
    "statistics.py:verify_significance_consistency:b",
    "statistics.py:verify_trajectory:b",
    "wordcraft.py:verify_alphabet:r",
    "wordcraft.py:verify_letter_rank:r",
    "wordcraft.py:verify_letters:r",
    "wordcraft.py:verify_syllables:r",
}

# The few the flow cannot clear on its own, each with what keeps its ERROR an ERROR.
READ: Dict[str, str] = {
    "approximation.py:verify_get_close:m":
        "merges only results already past the two ERROR routes above it, so nothing here can be an ERROR",
    "computer_science.py:verify_runtime_complexity:b":
        "kept for its detail and data; _slope_verdict decides, and a slope not finite is 'inconclusive', an abstention",
    "statistics.py:verify_significance_consistency:b":
        "kept for its data; `is_sig` decides from p and alpha, and bound() here cannot err on a literal 'max'",
}


def _judged(node: ast.AST, name: str) -> Optional[str]:
    """The attribute of `name` this node reads, if it is one that judges a result."""
    if isinstance(node, ast.Attribute) and node.attr in ("status", "passed", "failed") and \
            isinstance(node.value, ast.Name) and node.value.id == name:
        return node.attr
    return None


def _truth(test: ast.AST, name: str) -> Optional[bool]:
    """What `test` comes to if `name` holds an ERROR result: True, False, or None when it depends on something else."""
    if _judged(test, name) == "passed":
        return False
    if _judged(test, name) == "failed":
        return True
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        inner = _truth(test.operand, name)
        return None if inner is None else not inner
    if isinstance(test, ast.BoolOp):
        parts = [_truth(v, name) for v in test.values]
        stop = isinstance(test.op, ast.Or)              # or stops at the first True, and at the first False
        if stop in parts:
            return stop
        return None if None in parts else (not stop)
    if isinstance(test, ast.Compare) and len(test.ops) == 1:
        op, right = test.ops[0], test.comparators[0]
        if isinstance(test.left, ast.Name) and test.left.id == name and isinstance(right, ast.Constant) and right.value is None:
            return isinstance(op, ast.IsNot) if isinstance(op, (ast.Is, ast.IsNot)) else None
        if _judged(test.left, name) == "status":
            if isinstance(right, ast.Constant):
                same = right.value == "ERROR"
            elif isinstance(right, (ast.Tuple, ast.List, ast.Set)):
                same = any(isinstance(e, ast.Constant) and e.value == "ERROR" for e in right.elts)
            else:
                return None
            if isinstance(op, (ast.Eq, ast.In)):
                return same
            if isinstance(op, (ast.NotEq, ast.NotIn)):
                return not same
    return None


def _called(node: Optional[ast.AST]) -> str:
    """The plain name a call goes to: "band" for band(...) and for _sb.band(...)."""
    if not isinstance(node, ast.Call):
        return ""
    f = node.func
    return f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")


def _keeps(value: Optional[ast.AST], name: str) -> bool:
    """True when this return hands the result on: itself, with its own status, or folded with merge_checks."""
    if isinstance(value, ast.Name):
        return value.id == name
    if _called(value) == "merge_checks":
        return True
    if isinstance(value, ast.Call):
        if any(k.arg == "status" and _judged(k.value, name) == "status" for k in value.keywords):
            return True
        return _called(value) == "replace" and bool(value.args) and isinstance(value.args[0], ast.Name) \
            and value.args[0].id == name
    return False


def _verdicts(value: Optional[ast.AST], name: str) -> Set[str]:
    """Which of confirm and mismatch a returned value can come from, with `name` an ERROR."""
    if not isinstance(value, ast.Call):
        return set()
    if isinstance(value.func, ast.IfExp):               # (confirm if r.passed else mismatch)(...)
        t = _truth(value.func.test, name)
        arms = [value.func.body] * (t is not False) + [value.func.orelse] * (t is not True)
        return {a.id for a in arms if isinstance(a, ast.Name) and a.id in ("confirm", "mismatch")}
    return {_called(value)} & {"confirm", "mismatch"}


def _flow(stmts: List[ast.stmt], name: str, made: bool, bound: bool, known: bool, bad: List[str]) -> Tuple[bool, bool]:
    """Follow `stmts` with `name` an ERROR once a statement binds it, noting in `bad` each verdict that turns it. With
    `made`, only band, bound or merge_checks bind it, so an earlier use of the same name for a plain number does not.
    `known` is False once a branch depends on something else, where a mismatch() is that something's proof. Gives back
    whether this block always returns, and whether the name is bound on a path that goes on."""
    for st in stmts:
        if isinstance(st, (ast.Assign, ast.AnnAssign)):
            targets = st.targets if isinstance(st, ast.Assign) else [st.target]
            if st.value is not None and any(isinstance(t, ast.Name) and t.id == name for t in targets):
                nothing = isinstance(st.value, ast.Constant) and st.value.value is None
                arms = [st.value.body, st.value.orelse] if isinstance(st.value, ast.IfExp) else [st.value]
                bound = not nothing and (not made or any(_called(a) in MADE_BY for a in arms))
                known = known or bound              # what it depended on came before this result existed
        elif isinstance(st, ast.Return):
            if bound and not _keeps(st.value, name):
                turned = _verdicts(st.value, name)
                if "confirm" in turned or ("mismatch" in turned and known):
                    bad.append(f"line {st.lineno}: {sorted(turned)} reached with {name} an ERROR")
            return True, bound
        elif isinstance(st, ast.If):
            t = _truth(st.test, name) if bound else None
            if t is None:
                a, a_bound = _flow(st.body, name, made, bound, False, bad)
                b, b_bound = _flow(st.orelse, name, made, bound, False, bad)
                if a and b:
                    return True, bound
                bound = (a_bound and not a) or (b_bound and not b)
            else:
                ended, bound = _flow(st.body if t else st.orelse, name, made, bound, known, bad)
                if ended:
                    return True, bound
        elif isinstance(st, (ast.With, ast.Try)):
            ended, bound = _flow(st.body, name, made, bound, known, bad)
            if ended:
                return True, bound
        elif isinstance(st, (ast.For, ast.While)):
            bound = _flow(st.body, name, made, bound, False, bad)[1]
    return False, bound


def _functions(tree: ast.AST) -> List[ast.FunctionDef]:
    return [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _bound(fn: ast.AST) -> Set[str]:
    """Each name a call to band, bound or merge_checks binds in this function, in either arm of a conditional."""
    out: Set[str] = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name):
            arms = [n.value.body, n.value.orelse] if isinstance(n.value, ast.IfExp) else [n.value]
            if any(_called(a) in MADE_BY for a in arms):
                out.add(n.targets[0].id)
    return out


def _merges(fn: ast.AST) -> Dict[str, str]:
    """list name -> the name its merge_checks result is bound to."""
    out: Dict[str, str] = {}
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign) and _called(n.value) == "merge_checks" and isinstance(n.targets[0], ast.Name):
            if len(n.value.args) > 1 and isinstance(n.value.args[1], ast.Name):
                out[n.value.args[1].id] = n.targets[0].id
    return out


def _comprehended(fn: ast.AST) -> Dict[str, List[ast.comprehension]]:
    """Each comprehension target that an `if` judges, with the clauses that do."""
    out: Dict[str, List[ast.comprehension]] = {}
    for n in ast.walk(fn):
        if isinstance(n, ast.comprehension) and isinstance(n.target, ast.Name):
            for test in n.ifs:
                if any(_judged(e, n.target.id) for e in ast.walk(test)):
                    out.setdefault(n.target.id, []).append(n)
    return out


def walk(source: str) -> Dict[Tuple[str, str], List[str]]:
    """(function, name) -> what turns its ERROR, for every consumer in `source`: [] when it stays an ERROR."""
    tree = ast.parse(source)
    found: Dict[Tuple[str, str], List[str]] = {}
    for fn in _functions(tree):
        made = _bound(fn)
        names = made | {n.value.id for n in ast.walk(fn) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                        and n.attr in ("status", "passed", "failed")}
        params = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
        loops = _comprehended(fn)
        merged = _merges(fn)
        for name in names:
            bad: List[str] = []
            if name in loops:
                errors = any(_truth(t, name) is True for c in loops[name] for t in c.ifs)
                carried = {merged.get(c.iter.id) for c in loops[name] if isinstance(c.iter, ast.Name)} - {None}
                routed: List[str] = []
                for m in carried:
                    _flow(fn.body, m, True, False, True, routed)
                if not (errors or (carried and not routed)):
                    bad.append(f"{name}: a filter over results that drops an ERROR, with no route for it")
                bad += routed
            else:
                _flow(fn.body, name, name in made, name in params, True, bad)
            found[(fn.name, name)] = bad
    return found


def consumers() -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for path in sorted(VERIFIERS.glob("*.py")):
        if path.name == "base.py":                      # where the results are made, and merge_checks' own fold
            continue
        for (fn, name), bad in walk(path.read_text(encoding="utf-8")).items():
            out[f"{path.name}:{fn}:{name}"] = bad
    return out


# ── the walk over the real source ───────────────────────────────────────────────────────────────
def test_the_walk_names_every_consumer():
    assert set(consumers()) == CONSUMERS


def test_no_consumer_turns_an_error_into_a_pass_or_a_broken():
    found = {k: v for k, v in consumers().items() if v and k not in READ}
    assert not found, found


def test_every_listed_exception_is_one_the_flow_really_needs():
    still = {k for k, v in consumers().items() if v}
    assert set(READ) <= CONSUMERS
    assert still == set(READ), "a READ entry the flow now clears should go; a new finding needs reading"


# ── the walk can fail ───────────────────────────────────────────────────────────────────────────
MISMATCH_THEN_CONFIRM = '''
def verify_x(spec):
    b = band("x", 1.0, 1.0, 0.0)
    if b.status == "MISMATCH":
        return mismatch("x", "no")
    return confirm("x", "yes")
'''
REWRAPS_A_NON_PASS = '''
def verify_x(spec):
    r = band("x", 1.0, 1.0, 0.0)
    if r.passed:
        return r
    return mismatch("x", r.detail, r.data)
'''
TERNARY_REWRAP = '''
def verify_x(spec):
    r = band("x", 1.0, 1.0, 0.0)
    return (confirm if r.passed else mismatch)("x", r.detail, r.data)
'''
NOT_CONFIRMED_IS_MISMATCH = '''
def verify_x(spec):
    m = merge_checks("x", [band("x", 1.0, 1.0, 0.0)], {})
    if m.status != "CONFIRMED":
        return mismatch("x", m.detail, m.data)
    return confirm("x", m.detail, m.data)
'''
FILTER_DROPS_THE_ERROR = '''
def verify_x(spec):
    results = [band("x", 1.0, 1.0, 0.0)]
    bad = [r for r in results if r.status == "MISMATCH"]
    if bad:
        return bad[0]
    return confirm("x", "yes")
'''
NESTED_REWRAP = '''
def verify_x(spec):
    if "claim" in spec:
        r = band("x", 1.0, 1.0, 0.0)
        return (confirm if r.passed else mismatch)("x", r.detail, r.data)
    return na("x")
'''
MISMATCH_BESIDE_A_PROOF_THEN_CONFIRM = '''
def verify_x(spec):
    reasons = []
    b = band("x", 1.0, 1.0, 0.0)
    if b.status == "MISMATCH":
        reasons.append(b.detail)
    if reasons:
        return mismatch("x", "; ".join(reasons))
    return confirm("x", "yes")
'''
PLANTED = [MISMATCH_THEN_CONFIRM, REWRAPS_A_NON_PASS, TERNARY_REWRAP, NOT_CONFIRMED_IS_MISMATCH, FILTER_DROPS_THE_ERROR,
           NESTED_REWRAP, MISMATCH_BESIDE_A_PROOF_THEN_CONFIRM]


@pytest.mark.parametrize("source", PLANTED, ids=["mismatch-then-confirm", "rewraps-a-non-pass", "ternary-rewrap",
                                                 "not-confirmed-is-mismatch", "filter-drops-the-error", "nested-rewrap",
                                                 "beside-a-proof"])
def test_the_walk_fails_on_a_planted_consumer(source):
    assert any(walk(source).values()), "the walk passed a consumer that loses an ERROR"


@pytest.mark.parametrize("source", [
    'def f(s):\n    r = band("x", 1, 1, 0)\n    if r.status == "ERROR":\n        return r\n'
    '    if r.status == "MISMATCH":\n        return mismatch("x", "no")\n    return confirm("x", "yes")\n',
    'def f(s):\n    r = band("x", 1, 1, 0)\n    if r.status != "MISMATCH":\n        return r\n    return mismatch("x", "no")\n',
    'def f(s):\n    r = band("x", 1, 1, 0)\n    if r.passed:\n        return confirm("x", "yes")\n    return r\n',
    'def f(s):\n    r = band("x", 1, 1, 0)\n    return VerifierResult(name="x", status=r.status, detail="d", data=r.data)\n',
    'def f(s):\n    results = [band("x", 1, 1, 0)]\n    bad = [r for r in results if r.status == "MISMATCH"] or '
    '[r for r in results if r.status == "ERROR"]\n    if bad:\n        return bad[0]\n    return confirm("x", "yes")\n',
], ids=["routes-first", "returns-a-non-mismatch", "falls-through", "keeps-the-status", "filters-both"])
def test_the_walk_passes_a_consumer_that_keeps_the_error(source):
    assert not any(walk(source).values())


# ── band() itself ───────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("claimed", [INF, -INF, NAN], ids=["inf", "-inf", "nan"])
@pytest.mark.parametrize("actual, tol", [(5.0, 0.0), (5.0, 1.0), (TOP, TOP), (TOP, 1e300), (0.0, 1e308)],
                         ids=["tight", "wide", "top-both-edges-overflow", "top-upper-edge-overflows", "wide-at-zero"])
def test_a_claim_not_finite_against_a_finite_value_is_a_mismatch(claimed, actual, tol):
    r = base.band("x", actual, claimed, tol)
    assert r.status == "MISMATCH" and r.data["band"]["inside"] is False


@pytest.mark.parametrize("actual", [INF, -INF, NAN], ids=["inf", "-inf", "nan"])
@pytest.mark.parametrize("claimed", [5.0, INF, -INF, NAN], ids=["finite", "inf", "-inf", "nan"])
def test_a_computed_value_not_finite_is_an_error_never_a_counterexample(actual, claimed):
    r = base.band("x", actual, claimed, 1.0)
    assert r.status == "ERROR" and "counterexample" not in r.data


@pytest.mark.parametrize("tol", [INF, NAN], ids=["inf", "nan"])
def test_a_window_not_finite_around_a_finite_claim_holds_nothing(tol):
    assert base.band("x", 5.0, 7.0, tol).status == "ERROR"


def test_a_finite_window_is_read_as_it_always_was():
    assert base.band("x", 5.0, 5.5, 1.0).status == "CONFIRMED"
    assert base.band("x", 5.0, 7.0, 1.0).status == "MISMATCH"
    assert base.band("x", TOP, TOP, 1e300).status == "CONFIRMED"    # finite, at an edge that overflowed


def test_merge_checks_lets_a_mismatch_govern_and_keeps_an_error():
    err = base.band("x", INF, 5.0, 1.0)
    assert base.merge_checks("x", [err, base.band("x", 5.0, 5.0, 1.0)]).status == "ERROR"
    assert base.merge_checks("x", [err, base.band("x", 5.0, 9.0, 1.0)]).status == "MISMATCH"


# ── through the verdict: every row a request can send ───────────────────────────────────────────
APPROX = "APPROX_VERIFY"
OVERFLOWED_ESTIMATE = {"anchor": 0, "target": 10, "anchor_value": 1e308, "slope": 1e308, "second_bound": 0}
ROWS_BROKEN = [
    ("physics", {"PHYS_VERIFY": {"v0": TOP, "a": 0, "t": 1, "claimed_displacement": INF}}),
    ("physics", {"PHYS_VERIFY": {"before": {"p": TOP}, "after": {"p": INF}}}),
    ("physics", {"PHYS_VERIFY": {"mass_kg": 2, "velocity_m_per_s": 3, "claimed_kinetic_energy_J": INF}}),
    ("economics", {"ECON_VERIFY": {"rate_percent": 8, "claimed_doubling_years": INF}}),
    ("finance", {"FIN_VERIFY": {"principal": 1000, "rate": 0.05, "compounding_per_year": 1, "years": 1, "claimed_future_value": INF}}),
    ("unit_conversion", {"CONV_VERIFY": {"from_value": 1, "from_unit": "mile", "to_value": INF, "to_unit": "kilometers"}}),
    ("approximation", {APPROX: {"anchor": 0, "target": 1, "anchor_value": 1, "slope": 0, "second_bound": 0, "true_value": INF}}),
    ("statistics", {"STAT_VERIFY": {"trajectory": {"successes": 9, "trials": 10, "claimed_floor": INF}}}),
]
ROWS_ERROR = [
    ("physics", {"PHYS_VERIFY": {"before": {"p": INF}, "after": {"p": 1.0}}}),
    ("physics", {"PHYS_VERIFY": {"law": "momentum", "before": {"p_x": 1e308, "p_y": 1e308}, "after": {"p_x": 1.0, "p_y": 1.0}}}),
    ("economics", {"ECON_VERIFY": {"rate_percent": 5e-324, "claimed_doubling_years": 11}}),
    ("approximation", {APPROX: dict(OVERFLOWED_ESTIMATE, true_value=5)}),
    ("approximation", {APPROX: dict(OVERFLOWED_ESTIMATE, claimed_value=5, claimed_error=1)}),
    ("approximation", {APPROX: {"anchor": 0, "target": 1e308, "anchor_value": 0, "lipschitz": 1e308, "true_value": 5}}),  # the window itself overflowed
    ("finance", {"FIN_VERIFY": {"principal": 1e308, "rate": 1.0, "compounding_per_year": 1, "years": 2, "claimed_future_value": 5}}),
]


@pytest.mark.parametrize("domain, spec", ROWS_BROKEN, ids=[f"{d}-{i}" for i, (d, _) in enumerate(ROWS_BROKEN)])
def test_a_finite_value_against_an_infinite_claim_reads_broken(domain, spec):
    assert benchmark.verify(spec, domain)["verdict"] == "BROKEN"


@pytest.mark.parametrize("domain, spec", ROWS_ERROR, ids=[f"{d}-{i}" for i, (d, _) in enumerate(ROWS_ERROR)])
def test_a_value_past_a_float_reads_could_not_compare(domain, spec):
    assert benchmark.verify(spec, domain)["verdict"] == "SYSTEM_ERROR"


@pytest.mark.parametrize("consume, make", [
    ("approximation", lambda: {APPROX: dict(OVERFLOWED_ESTIMATE, true_value=5)}),
    ("economics", lambda: {"ECON_VERIFY": {"rate_percent": 5e-324, "claimed_doubling_years": 11}}),
], ids=["confirm-after-a-mismatch-test", "rewrap-as-mismatch"])
def test_the_two_consumers_the_plan_names_keep_an_error_an_error(consume, make):
    from concordance.verifiers import run_for_domain
    assert [r.status for r in run_for_domain(consume, make())] == ["ERROR"]


def test_the_reading_is_the_same_on_a_true_claim_at_the_top_of_the_range():
    spec = {"PHYS_VERIFY": {"v0": TOP, "a": 0, "t": 1, "claimed_displacement": TOP}}
    assert math.isfinite(TOP) and benchmark.verify(spec, "physics")["verdict"] == "HOLDS"
