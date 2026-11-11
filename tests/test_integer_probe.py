"""THE PROBE of run 2026-11-11-exact-integers, step measure: tools/integer_probe.py varies each integer leaf of each
check's true spec in data/check_goldens.jsonl to v+0.25 and v-0.25, and a 0 or 1 to its bool, and watches with
sys.monitoring which int(), one-argument round(), math.floor, math.ceil and math.trunc calls in the verifiers drop a
fraction or take a bool for an integer.

These tests run the probe once over every check, in its own child process (the memo off, the verify timeout raised),
and require: that its findings equal tests/integer_probe_known.json exactly, so a finding not in the list fails and a
closed one must leave it, and that the list adds no entry to the one HEAD holds (in a gate's worktree, the step's
base), so it may only shrink; that the five leaves the plan names are among them while their files still have
findings; that every site it finds is a finding of THE WALK, so the two measures check each other; that it writes
nothing into data/; and that no site named in tests/integer_fields.json receives an injected value. They show it
fails, never skips, when a read times out (a read of most of a second given 1 ms) and when a true spec does not read
HOLDS clean. They hold the finding rule on reads given by the test (direct, derived, a site lossy in the clean read,
the leaves varied, the verdict recorded, a named site excluded), and the watch itself on a scratch module: each of
the five calls placed at its site by function, text and occurrence, never a line, a call from any other file not
watched, and a call it cannot place a problem, never a guess. sys.monitoring needs Python 3.12, so every test that
watches skips below it.

The tool is loaded inside each test, never at module level, so with it absent each test reads red.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "integer_probe.py"
DATA = ROOT / "data"
WATCHES = pytest.mark.skipif(sys.version_info < (3, 12), reason="sys.monitoring needs Python 3.12")

# The leaves the plan requires among the base findings: (check, leaf, the file of the site they reach).
FIVE = [("combinatorics.permutations", "COMB_VERIFY/claimed_permutations", "combinatorics.py"),
        ("combinatorics.permutations", "COMB_VERIFY/perm_n", "combinatorics.py"),
        ("combinatorics.permutations", "COMB_VERIFY/perm_k", "combinatorics.py"),
        ("periodic_table.element", "PT_VERIFY/claimed_atomic_number", "periodic_table.py"),
        ("atomic.quantum_numbers", "ATOM_VERIFY/n", "atomic.py")]


def _tool():
    spec = importlib.util.spec_from_file_location("integer_probe", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tree(path):
    out = {}
    for p in sorted(Path(path).rglob("*")):
        rel = p.relative_to(path).as_posix()
        out[rel] = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "dir"
    return out


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    """One run of the probe over every check: (exit code, report, data/ before, data/ after)."""
    tool = _tool()
    out = tmp_path_factory.mktemp("integer-probe") / "report.json"
    before = _tree(DATA)
    rc = tool.main(["--json", str(out)])
    return rc, json.loads(out.read_text(encoding="utf-8")), before, _tree(DATA)


# ── the probe over every check ────────────────────────────────────────────────────────────────────────────────
@WATCHES
def test_the_probe_makes_exactly_the_known_findings(base):
    tool = _tool()
    rc, rep, _, _ = base
    assert rep["failure"] is None, rep["failure"]
    rows = tool.check_rows()
    assert rep["checks"] == len(rows) and rep["runs"] > len(rows)
    new, stale = tool.compare(rep["findings"], tool.load_known())
    assert not new, f"{len(new)} findings not in tests/integer_probe_known.json, e.g. {new[:10]}"
    assert not stale, f"{len(stale)} entries of tests/integer_probe_known.json no longer found, e.g. {stale[:10]}"
    assert rc == 0


@WATCHES
def test_the_five_leaves_the_plan_names_are_found_while_their_files_have_findings(base):
    """At the base each of the five reaches its file's lossy call; a fix step removes a file's findings whole."""
    _, rep, _, _ = base
    found = {(f["check"], f["leaf"]) for f in rep["findings"]}
    files = {f["site"].split(":", 1)[0] for f in rep["findings"]}
    for check, leaf, file in FIVE:
        if file in files:
            assert (check, leaf) in found, f"{check} {leaf} is not a finding while {file} has findings"


@WATCHES
def test_every_site_the_probe_finds_is_a_finding_of_the_walk(base):
    tool = _tool()
    _, rep, _, _ = base
    walked = set(tool.walk()["findings"])
    missed = sorted({f["site"] for f in rep["findings"]} - walked)
    assert not missed, f"sites the probe finds and the walk does not: {missed}"


def test_the_probe_known_list_only_shrinks_from_the_one_its_base_holds():
    """In a gate's worktree HEAD is the step's base: no entry may be added to the list HEAD holds (none at the base
    of step measure, which adds the list)."""
    tool = _tool()
    try:
        before = tool.tracked_json("tests/integer_probe_known.json")
    except LookupError as exc:
        pytest.skip(f"no git revision to hold the list against: {exc}")
    if before is not None:
        added = sorted({tool.finding_key(f) for f in tool.load_known()}
                       - {tool.finding_key(f) for f in before["findings"]})
        assert not added, f"entries added to tests/integer_probe_known.json since HEAD: {added[:10]}"


@WATCHES
def test_the_probe_writes_nothing_into_data(base):
    _, rep, before, after = base
    assert rep["failure"] is None and before == after


@WATCHES
def test_no_named_field_is_a_site_that_receives_an_injected_value(base):
    tool = _tool()
    _, rep, _, _ = base
    assert tool.fields_direct(rep["excluded"]) == []
    assert tool.fields_problems(tool.load_fields()) == []


# ── it fails, never skips ─────────────────────────────────────────────────────────────────────────────────────
@WATCHES
def test_the_probe_fails_when_a_read_times_out(tmp_path):
    """number_theory.schoenfeld's clean read sieves to 100000 and takes most of a second warm on the laptop where
    this was measured (0.7 to 1.0 s), several hundred times the 1 ms window given here, so the read is always shed."""
    tool = _tool()
    out = tmp_path / "report.json"
    rc = tool.main(["--check", "number_theory.schoenfeld", "--timeout-s", "0.001", "--known", "none",
                    "--json", str(out)])
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rc == 3, rep
    assert rep["failure"].startswith("number_theory.schoenfeld clean: a read was shed (verify timed out")


@WATCHES
def test_the_probe_fails_when_a_true_spec_does_not_read_holds(tmp_path):
    tool = _tool()
    goldens = tmp_path / "goldens.jsonl"
    goldens.write_text(json.dumps({"check": "planted.permutations", "domain": "combinatorics", "true": {
        "COMB_VERIFY": {"perm_n": 5, "perm_k": 2, "claimed_permutations": 21}}}) + "\n", encoding="utf-8")
    out = tmp_path / "report.json"
    rc = tool.main(["--goldens", str(goldens), "--known", "none", "--json", str(out)])
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rc == 3 and rep["failure"] == "planted.permutations: the true spec reads BROKEN clean, not HOLDS"


def test_below_python_3_12_the_probe_refuses_with_that_reason(monkeypatch, capsys):
    tool = _tool()
    monkeypatch.setattr(tool, "MIN_PYTHON", (99, 0))
    assert tool.main(["--known", "none"]) == 2
    assert "sys.monitoring needs Python 3.12" in capsys.readouterr().err


def test_the_child_reads_with_the_memo_off_the_timeout_raised_and_no_caller_setting(monkeypatch):
    tool = _tool()
    monkeypatch.setenv("CONCORDANCE_ALLOW_CODE_EXEC", "1")
    monkeypatch.setenv("CONCORDANCE_DATA_DIR", str(DATA))
    monkeypatch.setenv("CONCORDANCE_MEMO", "1")
    env = tool.child_env(600)
    assert env["CONCORDANCE_MEMO"] == "0" and float(env["CONCORDANCE_VERIFY_TIMEOUT_S"]) == 600.0
    assert env["PYTHONHASHSEED"] == "0" and env["PYTHONPATH"].split(os.pathsep)[0] == str(ROOT / "src")
    assert sorted(k for k in env if k.startswith("CONCORDANCE_")) == ["CONCORDANCE_MEMO",
                                                                      "CONCORDANCE_VERIFY_TIMEOUT_S"]
    assert tool.TIMEOUT_S >= 600


# ── the finding rule, on reads the test gives ─────────────────────────────────────────────────────────────────
def _planted_read(tool, log):
    """A verifier the test writes: int(a) at one site, int(a * 2) at another, round(b) on a real b (lossy clean),
    int(c[0]) only when c[0] is a bool. It reads HOLDS unless a is 7."""
    def read(domain, spec):
        log.append(json.loads(json.dumps(spec)))
        x = spec["X"]
        events = []
        for site, arg in (("f.py:g:int(a)#1", x["a"]), ("f.py:g:int(a * 2)#1", x["a"] * 2),
                          ("f.py:g:round(b)#1", x["b"] + 1.0 if isinstance(x["a"], float) else x["b"])):
            if isinstance(arg, bool):
                events.append((site, "bool", arg))
            elif isinstance(arg, float) and not arg.is_integer():
                events.append((site, "frac", arg))
        if isinstance(x["c"][0], bool):
            events.append(("f.py:g:int(c[0])#1", "bool", x["c"][0]))
        return tool.Read("BROKEN" if x["a"] == 7 else "HOLDS", events, [])
    return read


def test_the_finding_rule_on_planted_reads():
    tool = _tool()
    log = []
    true = {"X": {"a": 1, "b": 2.5, "c": [0, True], "s": "1", "n": None}}
    rep = tool.probe([("planted", "d", true)], _planted_read(tool, log))
    # varied: a (1: +0.25, -0.25, bool) and c/0 (0: +0.25, -0.25, bool); never b (a float), c/1 (a bool), s, n
    assert rep["runs"] == 1 + 3 + 3 == len(log)
    assert [k for k, v in log[1]["X"].items() if v != true["X"][k]] == ["a"] and log[1]["X"]["a"] == 1.25
    got = {(f["leaf"], f["variant"], f["site"], f["how"], f["verdict"]) for f in rep["findings"]}
    assert got == {
        ("X/a", "+0.25", "f.py:g:int(a)#1", "direct", "HOLDS"),      # the injected value itself
        ("X/a", "+0.25", "f.py:g:int(a * 2)#1", "derived", "HOLDS"),  # 2.5: a site with no lossy call clean
        ("X/a", "-0.25", "f.py:g:int(a)#1", "direct", "HOLDS"),
        ("X/a", "-0.25", "f.py:g:int(a * 2)#1", "derived", "HOLDS"),  # 1.5
        ("X/a", "bool", "f.py:g:int(a)#1", "direct", "HOLDS"),
        ("X/c/0", "bool", "f.py:g:int(c[0])#1", "direct", "HOLDS"),
    }, got                                                            # round(b) is lossy clean: never a finding
    assert rep["excluded"] == [] and rep["counts"]["findings"] == 6 and rep["counts"]["leaves"] == 2
    named = tool.probe([("planted", "d", true)], _planted_read(tool, []), named={"f.py:g:int(a)#1"})
    assert {f["site"] for f in named["findings"]} == {"f.py:g:int(a * 2)#1", "f.py:g:int(c[0])#1"}
    assert {(f["variant"], f["how"]) for f in named["excluded"]} == {("+0.25", "direct"), ("-0.25", "direct"),
                                                                      ("bool", "direct")}
    assert len(tool.fields_direct(named["excluded"])) == 3


def test_the_finding_rule_counts_a_finding_whatever_its_verdict():
    tool = _tool()
    rep = tool.probe([("planted", "d", {"X": {"a": 7, "b": 1.0, "c": [2]}})],
                     lambda d, s: tool.Read("HOLDS" if s["X"]["a"] == 7 else "BROKEN",
                                            [("f.py:g:int(a)#1", "frac", s["X"]["a"])]
                                            if isinstance(s["X"]["a"], float) else [], []))
    assert {(f["variant"], f["verdict"]) for f in rep["findings"]} == {("+0.25", "BROKEN"), ("-0.25", "BROKEN")}


def test_the_finding_rule_fails_on_a_shed_read_and_on_a_true_spec_not_reading_holds():
    tool = _tool()
    shed = lambda d, s: tool.Read("SYSTEM_ERROR", [], ["verify timed out (>8s) domain=d"])  # noqa: E731
    with pytest.raises(tool.ProbeFailure, match="a read was shed"):
        tool.probe([("planted", "d", {"X": {"a": 1}})], shed)
    later = lambda d, s: tool.Read("HOLDS", [], [] if s["X"]["a"] == 1 else ["verify pool saturated"])  # noqa: E731
    with pytest.raises(tool.ProbeFailure, match="X/a"):
        tool.probe([("planted", "d", {"X": {"a": 1}})], later)
    broken = lambda d, s: tool.Read("BROKEN", [], [])  # noqa: E731
    with pytest.raises(tool.ProbeFailure, match="reads BROKEN clean, not HOLDS"):
        tool.probe([("planted", "d", {"X": {"a": 1}})], broken)


def test_a_check_name_carried_twice_reads_with_its_ordinal():
    tool = _tool()
    rows = [r[0] for r in tool.check_rows()]
    assert len(rows) == len(set(rows))
    assert "soil_science.soil_texture" in rows and "soil_science.soil_texture #2" in rows


# ── the watch, on a scratch module ────────────────────────────────────────────────────────────────────────────
SCRATCH = '''
import math
import math as _m
from math import trunc


def f(x, flag):
    a = int(x)
    b = int(x)
    c = round(x)
    d = round(x, 1)
    e = math.floor(x) + _m.ceil(
        x) + trunc(x)
    g = int(flag)
    h = int(2.0) + int("3") + int(4)
    return [int(v) for v in (x,)], (lambda r: int(r))(x)


class K:
    def m(self, x):
        return int(x)
'''


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@WATCHES
def test_the_watch_places_each_lossy_call_at_its_site(tmp_path):
    tool = _tool()
    vdir = tmp_path / "verifiers"
    vdir.mkdir()
    (vdir / "m.py").write_text(SCRATCH, encoding="utf-8")
    mod = _load(vdir / "m.py", "integer_probe_scratch_m")
    with tool.Monitor(vdir) as mon:
        mod.f(2.5, True)
        mod.K().m(-0.5)
        mod.f(3.0, 1)                     # whole floats and ints are not lossy
        int(0.5)                          # a call from this file is not watched
    assert mon.problems == []
    assert sorted((site, kind) for site, kind, _ in mon.events) == sorted([
        ("m.py:f:int(x)#1", "frac"), ("m.py:f:int(x)#2", "frac"), ("m.py:f:round(x)#1", "frac"),
        ("m.py:f:math.floor(x)#1", "frac"), ("m.py:f:_m.ceil( x)#1", "frac"), ("m.py:f:trunc(x)#1", "frac"),
        ("m.py:f:int(flag)#1", "bool"), ("m.py:f:int(v)#1", "frac"), ("m.py:f:int(r)#1", "frac"),
        ("m.py:K.m:int(x)#1", "frac")])  # round(x, 1) has two arguments; int(2.0), int("3"), int(4) drop nothing
    assert [arg for site, _, arg in mon.events if site == "m.py:K.m:int(x)#1"] == [-0.5]


def test_a_site_is_never_a_line(tmp_path):
    tool = _tool()
    a, b = tmp_path / "a", tmp_path / "b"
    for d, pad in ((a, ""), (b, "\n\n\n# moved down\n\n")):
        d.mkdir()
        (d / "m.py").write_text(pad + SCRATCH, encoding="utf-8")
    keys = [sorted(s.key for s in tool.site_index(d / "m.py").sites) for d in (a, b)]
    assert keys[0] == keys[1] and "m.py:f:int(x)#2" in keys[0]


@WATCHES
def test_a_lossy_call_the_watch_cannot_place_is_a_problem_never_a_guess(tmp_path):
    tool = _tool()
    vdir = tmp_path / "verifiers"
    vdir.mkdir()
    (vdir / "m.py").write_text(SCRATCH, encoding="utf-8")
    mod = _load(vdir / "m.py", "integer_probe_scratch_moved")
    (vdir / "m.py").write_text("\n\n" + SCRATCH.replace("int(x)", "int( x )"), encoding="utf-8")  # the source moved
    with tool.Monitor(vdir) as mon:
        mod.K().m(0.5)
    assert mon.events == [] and len(mon.problems) == 1 and "is at no site" in mon.problems[0]
