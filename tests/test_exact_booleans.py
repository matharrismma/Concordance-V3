"""A TRUE/FALSE IS READ AS IT IS WRITTEN (verifiers/_integer.py _exact_bool, run 2026-11-27).

Verifiers read a claimed or given true/false with bool(), and bool() reads every non-empty text as true. So a claim
written "false" was read as the claim it denies: "97 is not prime", sent as claimed_prime "false", read HOLDS "97 is
prime (matches claim)" on the public door, and of the 208 true/false claims the benchmark's true cases carry, 188
written as the text of their opposite held, in 38 domains. game_theory had met this once and fixed it in its own
module; the other checks never were. Two checks never read their claim at all: agriculture.rotation_compatible held a
compatible rotation claimed NOT compatible, and the sound laws held a regular correspondence claimed not regular.

Now one reader takes a JSON true or false, or the text true, false, yes or no read as written; a number (0 and 1 among
them), any other text and null are malformed, and an optional flag names the default an absent field takes. Measured
over the same 208 claims: the real opposite and the text of the opposite each read BROKEN 208 of 208, the text of the
claim itself HOLDS 208, a number reads SYSTEM_ERROR 208; and over 2,190 other cases (the benchmark, every domain empty
and with a wrong key, the 765 stick seal steps) no verdict, status or seal moved.

These pin the reader, the cases that were wrong, the claims now read, and the WALK: no check under
src/concordance/verifiers/ reads a packet's field through bool() again, and the walk still finds each shape it looks for.
"""
from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

from concordance.derivation import verify_derivation
from concordance.verifiers._integer import _exact_bool

ROOT = Path(__file__).resolve().parents[1]
VERIFIERS = ROOT / "src" / "concordance" / "verifiers"


@pytest.fixture
def real_data(monkeypatch):
    monkeypatch.setenv("CONCORDANCE_DATA_DIR", str(ROOT / "data"))
    monkeypatch.setenv("CONCORDANCE_MEMO", "0")


# ── the reader ────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("value, read", [(True, True), (False, False), ("true", True), ("false", False),
                                         ("False", False), (" TRUE ", True), ("yes", True), ("No", False)])
def test_a_true_false_reads_as_written(value, read):
    assert _exact_bool(value, "f") is read


@pytest.mark.parametrize("value", [1, 0, 1.0, "y", "n", "1", "0", "", "falsey", "maybe", None, [], {}, [True]])
def test_anything_else_is_malformed_and_names_the_field(value):
    with pytest.raises(TypeError, match="claimed_x must be true or false"):
        _exact_bool(value, "claimed_x")


def test_an_optional_flag_names_its_default_for_absent_and_null_only():
    assert _exact_bool(None, "rna", default=False) is False
    assert _exact_bool(None, "is_below", default=True) is True
    assert _exact_bool("false", "is_below", default=True) is False
    with pytest.raises(TypeError):
        _exact_bool("maybe", "rna", default=False)


# ── the cases that were wrong, end to end ─────────────────────────────────────────────────────────────────────
def _verdict(domain, key, **fields):
    r = verify_derivation([{"id": "a", "domain": domain, "spec": {key: fields}}])
    return r["verdict"], r["trail"][0]["detail"]


@pytest.mark.parametrize("claimed, verdict", [(True, "HOLDS"), ("true", "HOLDS"), (False, "BROKEN"),
                                              ("false", "BROKEN"), ("no", "BROKEN"), (1, "SYSTEM_ERROR"),
                                              ("maybe", "SYSTEM_ERROR")])
def test_ninety_seven_is_prime_however_the_claim_is_written(real_data, claimed, verdict):
    v, detail = _verdict("number_theory", "NUM_VERIFY", n_prime=97, claimed_prime=claimed)
    assert v == verdict, detail
    if verdict == "SYSTEM_ERROR":
        assert "claimed_prime must be true or false" in detail


def test_consequentialism_does_not_stop_judging_by_outcomes_in_text(real_data):
    v, _ = _verdict("philosophy", "PHIL_VERIFY", framework_name="consequentialist", claimed_focuses_on_outcomes="false")
    assert v == "BROKEN"
    v, _ = _verdict("philosophy", "PHIL_VERIFY", claim_requires_observation="false", claimed_is_a_priori=True)
    assert v == "HOLDS"                                         # Kant's 7 + 5 = 12: no observation, so a priori


def test_the_rotation_claim_is_read(real_data):
    ok, bad = ["tomato", "bean", "corn"], ["tomato", "potato"]
    assert _verdict("agriculture", "AG_VERIFY", rotation=ok, claimed_rotation_compatible=True)[0] == "HOLDS"
    assert _verdict("agriculture", "AG_VERIFY", rotation=ok, claimed_rotation_compatible=False)[0] == "BROKEN"
    assert _verdict("agriculture", "AG_VERIFY", rotation=bad, claimed_rotation_compatible=False)[0] == "HOLDS"
    assert _verdict("agriculture", "AG_VERIFY", rotation=bad, claimed_rotation_compatible=True)[0] == "BROKEN"
    assert _verdict("agriculture", "AG_VERIFY", rotation=ok)[0] == "HOLDS"          # absent: the claim is compatible


def test_a_regular_law_claimed_not_regular_is_refused(real_data):
    rows = {"law": "Grimm (p > f)", "source_onset": "p", "target_onset": "f",
            "pairs": [["pater", "father"], ["pes", "foot"], ["piscis", "fish"]]}
    held, _ = _verdict("sound_law", "SOUNDLAW_VERIFY", **rows, claimed_regular=True)
    refused, detail = _verdict("sound_law", "SOUNDLAW_VERIFY", **rows, claimed_regular=False)
    assert held == "HOLDS" and refused == "BROKEN" and "claimed not regular" in detail


def test_game_theory_reads_by_the_shared_reader(real_data):
    nash = dict(row_payoff_A=[[3, 0], [5, 1]], col_payoff_B=[[3, 5], [0, 1]], profile=[1, 1])
    assert _verdict("game_theory", "GAME_VERIFY", **nash, claimed_is_nash="true")[0] == "HOLDS"
    assert _verdict("game_theory", "GAME_VERIFY", **nash, claimed_is_nash="false")[0] == "BROKEN"
    assert _verdict("game_theory", "GAME_VERIFY", **nash, claimed_is_nash="yes")[0] == "HOLDS"
    v, detail = _verdict("game_theory", "GAME_VERIFY", **nash, claimed_is_nash=1)
    assert v == "SYSTEM_ERROR" and "claimed_is_nash must be true or false" in detail


# ── THE WALK ──────────────────────────────────────────────────────────────────────────────────────────────────
def _key_of(node):
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get" and node.args:
        return "get"
    if isinstance(node, ast.Subscript):
        return "subscript"
    return None


def _base(node):
    while isinstance(node, (ast.Call, ast.Subscript, ast.Attribute)):
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Attribute):
                return None
            node = node.func.value
        else:
            node = node.value
    return node.id if isinstance(node, ast.Name) else None


def loose_reads(source: str):
    """Each bool(x) where x is a packet read: param.get(...), param[...], a name bound from one (unpacking too), or a
    parameter itself when the function reads its packet field into it by name."""
    found = []
    tree = ast.parse(source)
    for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        params = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
        bound = set()
        for node in ast.walk(fn):
            if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
                continue
            t = node.targets[0]
            pairs = ([(t, node.value)] if isinstance(t, ast.Name) else
                     list(zip(t.elts, node.value.elts)) if isinstance(t, ast.Tuple) and isinstance(node.value, ast.Tuple)
                     else [])
            for tn, v in pairs:
                v = v.values[0] if isinstance(v, ast.BoolOp) else v
                if isinstance(tn, ast.Name) and _key_of(v) and (_base(v) in params or _base(v) in bound):
                    bound.add(tn.id)
        for node in ast.walk(fn):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "bool" and node.args:
                a = node.args[0]
                if (isinstance(a, ast.Name) and a.id in bound) or (_key_of(a) and _base(a) in params):
                    found.append((fn.name, node.lineno))
    return found


def test_no_verifier_reads_a_packet_field_through_bool():
    hits = {p.name: loose_reads(p.read_text(encoding="utf-8")) for p in sorted(VERIFIERS.glob("*.py"))}
    hits = {k: v for k, v in hits.items() if v}
    assert not hits, f"read these with _exact_bool (verifiers/_integer.py): {hits}"


def test_the_walk_still_finds_each_shape():
    src = textwrap.dedent('''
        def a(spec):
            return bool(spec.get("claimed_x"))
        def b(spec):
            return bool(spec["claimed_x"])
        def c(spec):
            claimed = spec.get("claimed_x")
            return bool(claimed)
        def d(spec):
            w, claimed = spec.get("word"), spec.get("claimed_x")
            return bool(claimed)
        def e(spec):
            claimed = spec.get("claimed_x") or spec.get("claimed_y")
            return bool(claimed)
        def quiet(spec, xs):
            hits = [x for x in xs if x]
            return bool(hits) and bool(len(xs))
    ''')
    assert [f for f, _ in loose_reads(src)] == ["a", "b", "c", "d", "e"]
