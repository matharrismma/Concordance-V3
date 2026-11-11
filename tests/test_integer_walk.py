"""THE WALK of run 2026-11-11-exact-integers, step measure: tools/integer_probe.py's walk parses each file under
src/concordance/verifiers/ and finds each int(), one-argument round(), math.floor, math.ceil or math.trunc call whose
first argument it marks as coming from a function's parameters.

These tests require: that its findings equal tests/integer_walk_known.json exactly, so a finding not in the list
fails and a closed one must leave it; that the list adds no site to the one HEAD holds (in a gate's worktree, the
step's base), so it may only shrink; and that the list holds every site in tests/integer_probe_known.json, so the
two measures check each other. They show the walk itself on scratch sources:
each kind of marking followed (a parameter, attribute, subscript, arithmetic, a call with a marked argument or
callee, assignment, unpacking, augmented assignment, a walrus, a with's target, a match's capture, a for loop's
target, a comprehension or generator's target, a store into a container, a nested def, a lambda), each kind of
unmarking (THE RULE's two readers by name, len(), a comparison, a literal), each of the five calls and nothing else;
that THE RULE's two readers are exempt only as the top-level functions of their shared module, and an int() of a
parameter anywhere else in that module is still found; that a site named in tests/integer_fields.json is not
counted, and an entry naming no site, no why or no test is refused; and that an int() of a parameter added to a
scratch copy of the verifiers is found, and nothing else moves.

The tool is loaded inside each test, never at module level, so with it absent each test reads red.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "integer_probe.py"


def _tool():
    spec = importlib.util.spec_from_file_location("integer_probe", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _walked(tool, tmp_path, source, name="m.py", fields=()):
    vdir = tmp_path / "verifiers"
    vdir.mkdir(exist_ok=True)
    (vdir / name).write_text(textwrap.dedent(source), encoding="utf-8")
    return tool.walk(vdir, fields=list(fields))


@pytest.fixture(scope="module")
def walked_verifiers():
    """THE WALK over src/concordance/verifiers/, once for the tests that read it."""
    return _tool().walk()


# ── the walk over the verifiers ───────────────────────────────────────────────────────────────────────────────
def test_the_walk_makes_exactly_the_known_findings(walked_verifiers):
    tool = _tool()
    found = set(walked_verifiers["findings"])
    known = tool.load_walk_known()
    assert len(known) == len(set(known)) and known == sorted(known)
    new, stale = sorted(found - set(known)), sorted(set(known) - found)
    assert not new, f"{len(new)} walk findings not in tests/integer_walk_known.json, e.g. {new[:10]}"
    assert not stale, f"{len(stale)} entries of tests/integer_walk_known.json no longer found, e.g. {stale[:10]}"


def test_the_walk_holds_every_site_the_probe_knows(walked_verifiers):
    tool = _tool()
    probe_sites = {f["site"] for f in tool.load_known()}
    missed = sorted(probe_sites - set(tool.load_walk_known()))
    assert not missed, f"sites in tests/integer_probe_known.json the walk's list does not hold: {missed}"
    assert not sorted(probe_sites - set(walked_verifiers["findings"]))


def test_the_walk_known_list_only_shrinks_from_the_one_its_base_holds():
    """In a gate's worktree HEAD is the step's base: no site may be added to the list HEAD holds (none at the base
    of step measure, which adds the list)."""
    tool = _tool()
    try:
        before = tool.tracked_json("tests/integer_walk_known.json")
    except LookupError as exc:
        pytest.skip(f"no git revision to hold the list against: {exc}")
    if before is not None:
        added = sorted(set(tool.load_walk_known()) - set(before["sites"]))
        assert not added, f"sites added to tests/integer_walk_known.json since HEAD: {added[:10]}"


def test_a_list_is_read_as_a_revision_holds_it(tmp_path):
    """The shrink checks' reader, on a scratch repository: a file the revision holds reads as it holds it, even after
    the working copy changes; one it does not hold reads None; a revision that is not there is a LookupError."""
    tool = _tool()
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "integer_walk_known.json").write_text('{"sites": ["a", "b"]}', encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for argv in (["init", "-q"], ["add", "tests/integer_walk_known.json"]):
        subprocess.run(["git", "-C", str(repo), *argv], check=True, capture_output=True, env=env)
    tree = subprocess.run(["git", "-C", str(repo), "write-tree"], check=True, capture_output=True, text=True,
                          env=env).stdout.strip()
    (repo / "tests" / "integer_walk_known.json").write_text('{"sites": ["a", "b", "c"]}', encoding="utf-8")
    assert tool.tracked_json("tests/integer_walk_known.json", repo, tree) == {"sites": ["a", "b"]}
    assert tool.tracked_json("tests/integer_probe_known.json", repo, tree) is None
    with pytest.raises(LookupError):
        tool.tracked_json("tests/integer_walk_known.json", repo, "0" * 40)
    with pytest.raises(LookupError):
        tool.tracked_json("tests/integer_walk_known.json", tmp_path / "no-repo", "HEAD")


# ── marking: each kind is followed ────────────────────────────────────────────────────────────────────────────
MARKED = {
    "a parameter": ("def f(spec):\n    return int(spec)", "m.py:f:int(spec)#1"),
    "an attribute": ("def f(spec):\n    return int(spec.value)", "m.py:f:int(spec.value)#1"),
    "a subscript": ("def f(spec):\n    return int(spec['n'])", "m.py:f:int(spec['n'])#1"),
    "arithmetic": ("def f(spec):\n    return int(-spec * 2 + 1)", "m.py:f:int(-spec * 2 + 1)#1"),
    "a call with a marked argument": ("def f(spec):\n    return int(float(spec))", "m.py:f:int(float(spec))#1"),
    "a call with a marked callee": ("def f(spec):\n    return int(spec.get('n'))", "m.py:f:int(spec.get('n'))#1"),
    "a call to another function named like a reader": (
        "def f(spec):\n    n, k = _exact_integers(spec)\n    return int(g(n, k))", "m.py:f:int(g(n, k))#1"),
    "assignment, through a chain": ("def f(spec):\n    n = spec['n']\n    m = n\n    return int(m)",
                                    "m.py:f:int(m)#1"),
    "unpacking": ("def f(spec):\n    a, b = spec\n    return int(b)", "m.py:f:int(b)#1"),
    "unpacking, paired": ("def f(spec):\n    a, b = 1, spec\n    return int(b)", "m.py:f:int(b)#1"),
    "unpacking, starred": ("def f(spec):\n    first, *rest = spec\n    return int(rest[0])",
                           "m.py:f:int(rest[0])#1"),
    "augmented assignment": ("def f(spec):\n    t = 0\n    t += spec\n    return int(t)", "m.py:f:int(t)#1"),
    "annotated assignment": ("def f(spec):\n    n: float = spec\n    return int(n)", "m.py:f:int(n)#1"),
    "a walrus": ("def f(spec):\n    if (n := spec['n']) > 0:\n        return int(n)", "m.py:f:int(n)#1"),
    "a with's target": ("def f(spec):\n    with spec as s:\n        return int(s)", "m.py:f:int(s)#1"),
    "a match's capture": ("def f(spec):\n    match spec:\n        case {'n': n}:\n            return int(n)",
                          "m.py:f:int(n)#1"),
    "a for loop's target": ("def f(spec):\n    for v in spec:\n        return int(v)", "m.py:f:int(v)#1"),
    "a comprehension's target": ("def f(spec):\n    return [int(v) for v in spec]", "m.py:f:int(v)#1"),
    "a nested comprehension's target": ("def f(spec):\n    return [int(w) for v in spec for w in v]",
                                        "m.py:f:int(w)#1"),
    "a dict comprehension's target": ("def f(spec):\n    return {k: int(v) for k, v in spec.items()}",
                                      "m.py:f:int(v)#1"),
    "a generator's target": ("def f(spec):\n    return sum(int(v) for v in spec)", "m.py:f:int(v)#1"),
    "a conditional expression": ("def f(spec):\n    return int(spec if spec else 0)",
                                 "m.py:f:int(spec if spec else 0)#1"),
    "a boolean operation": ("def f(spec):\n    return int(spec or 0)", "m.py:f:int(spec or 0)#1"),
    "a store into a container": ("def f(spec):\n    out = {}\n    out['n'] = spec\n    return int(out['n'])",
                                 "m.py:f:int(out['n'])#1"),
    "a container's filling method": ("def f(spec):\n    vals = []\n    vals.append(spec)\n    return int(vals[0])",
                                     "m.py:f:int(vals[0])#1"),
    "a nested def's free name": ("def f(spec):\n    n = spec['n']\n    def g():\n        return int(n)\n"
                                 "    return g()", "m.py:f.g:int(n)#1"),
    "a lambda's parameter": ("def f():\n    g = lambda r: int(r)\n    return g", "m.py:f:int(r)#1"),
    "a method's self": ("class C:\n    def m(self):\n        return int(self.x)", "m.py:C.m:int(self.x)#1"),
    "*args": ("def f(*args):\n    return int(args[0])", "m.py:f:int(args[0])#1"),
    "**kwargs": ("def f(**kw):\n    return int(kw['n'])", "m.py:f:int(kw['n'])#1"),
    "a keyword-only parameter": ("def f(*, n):\n    return int(n)", "m.py:f:int(n)#1"),
}


@pytest.mark.parametrize("kind", sorted(MARKED))
def test_each_kind_of_marking_is_followed(tmp_path, kind):
    tool = _tool()
    source, key = MARKED[kind]
    assert key in _walked(tool, tmp_path, source)["findings"]


# ── unmarking: each kind is followed ──────────────────────────────────────────────────────────────────────────
UNMARKED = {
    "THE RULE's input reader": "def f(spec):\n    n = _exact_integer(spec['n'])\n    return int(n)",
    "THE RULE's claim reader, as an attribute": "def f(spec):\n    c = rule._claimed_integer(spec)\n    return int(c)",
    "a reader's result through arithmetic": "def f(spec):\n    n = _exact_integer(spec)\n    return int(n / 2)",
    "a paired unpacking from a reader": "def f(spec):\n    n, c = _exact_integer(spec), spec\n    return int(n)",
    "len()": "def f(spec):\n    n = len(spec)\n    return int(n / 2) + int(len(spec))",
    "a comparison": "def f(spec):\n    ok = spec > 0\n    return int(ok) + int(spec == 1)",
    "a literal": "def f(spec):\n    x = 3\n    return int(2.5) + int(x) + int('7')",
    "a lambda": "def f(spec):\n    g = lambda: 0\n    return int(g())",
    "a call with no marked argument": "def f(spec):\n    return int(time.time())",
    "another function's parameter": "def f(spec):\n    return spec\ndef g():\n    spec = 2\n    return int(spec)",
}


@pytest.mark.parametrize("kind", sorted(UNMARKED))
def test_each_kind_of_unmarking_is_followed(tmp_path, kind):
    tool = _tool()
    walked = _walked(tool, tmp_path, UNMARKED[kind])
    assert walked["findings"] == {}, walked["findings"]


# ── the five calls, and nothing else ──────────────────────────────────────────────────────────────────────────
def test_each_of_the_five_calls_is_found_and_nothing_else(tmp_path):
    tool = _tool()
    source = """
        import math
        import math as _m
        import numpy as np
        from math import ceil as up, trunc


        def f(x):
            def inner():
                import math as m2
                return m2.trunc(x)
            return (int(x), round(x), math.floor(x), math.ceil(x), math.trunc(x), _m.floor(x), up(x), trunc(x),
                    inner(), round(x, 2), round(x, ndigits=None), float(x), abs(x), np.floor(x), math.fabs(x),
                    divmod(x, 1), x // 1)
    """
    found = _walked(tool, tmp_path, source)["findings"]
    assert found == {"m.py:f:int(x)#1": "int", "m.py:f:round(x)#1": "round", "m.py:f:math.floor(x)#1": "floor",
                     "m.py:f:math.ceil(x)#1": "ceil", "m.py:f:math.trunc(x)#1": "trunc",
                     "m.py:f:_m.floor(x)#1": "floor", "m.py:f:up(x)#1": "ceil", "m.py:f:trunc(x)#1": "trunc",
                     "m.py:f.inner:m2.trunc(x)#1": "trunc"}


def test_sites_are_keyed_by_function_text_and_occurrence(tmp_path):
    tool = _tool()
    source = """
        X = int(3.5)


        def f(x):
            return int(x) + int(x) + int(
                x
            )


        def g(x):
            return int(x)
    """
    walked = _walked(tool, tmp_path, source)["findings"]
    assert sorted(walked) == ["m.py:f:int( x )#1", "m.py:f:int(x)#1", "m.py:f:int(x)#2", "m.py:g:int(x)#1"]


# ── THE RULE's own conversion ─────────────────────────────────────────────────────────────────────────────────
READERS_MODULE = '''
import math as _math


def _exact_integer(value) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"{value!r} is not an integer")
    if isinstance(value, float) and not (_math.isfinite(value) and value.is_integer()):
        raise ValueError(f"{value!r} is not an integer")
    return int(value)


def _claimed_integer(value):
    number = float(value) if isinstance(value, str) else value
    if isinstance(number, float) and _math.isfinite(number) and not number.is_integer():
        return value
    return int(_exact_integer(value)) and int(value)


def _added(value):
    return int(value)


def _outer(value):
    def _exact_integer(v):
        return int(v)
    return _exact_integer(value)


class Reader:
    def _claimed_integer(self, value):
        return int(value)
'''


def test_the_shared_readers_are_exempt_by_name_in_their_module_and_nowhere_else(tmp_path):
    tool = _tool()
    assert set(tool.READERS) == {"_exact_integer", "_claimed_integer"}
    _walked(tool, tmp_path, READERS_MODULE, name=tool.SHARED_MODULE)
    walked = _walked(tool, tmp_path, READERS_MODULE, name="mathematics.py")
    m = tool.SHARED_MODULE
    assert walked["exempt"] == {f"{m}:_exact_integer:int(value)#1": "int", f"{m}:_claimed_integer:int(value)#1": "int"}
    assert sorted(k for k in walked["findings"] if k.startswith(m)) == [
        f"{m}:Reader._claimed_integer:int(value)#1", f"{m}:_added:int(value)#1", f"{m}:_outer._exact_integer:int(v)#1"]
    assert sorted(k for k in walked["findings"] if k.startswith("mathematics.py")) == [
        "mathematics.py:Reader._claimed_integer:int(value)#1", "mathematics.py:_added:int(value)#1",
        "mathematics.py:_claimed_integer:int(value)#1", "mathematics.py:_exact_integer:int(value)#1",
        "mathematics.py:_outer._exact_integer:int(v)#1"]



# ── tests/integer_fields.json ─────────────────────────────────────────────────────────────────────────────────
def test_a_site_named_in_integer_fields_is_not_counted(tmp_path):
    tool = _tool()
    source = "def f(spec):\n    return int(spec)\ndef g(spec):\n    return int(spec)"
    walked = _walked(tool, tmp_path, source, fields=["m.py:f:int(spec)#1"])
    assert walked["findings"] == {"m.py:g:int(spec)#1": "int"}
    assert walked["excluded"] == {"m.py:f:int(spec)#1": "int"}


def test_an_integer_fields_entry_names_a_site_a_why_and_a_test(tmp_path):
    tool = _tool()
    vdir = tmp_path / "verifiers"
    vdir.mkdir()
    (vdir / "m.py").write_text("def f(spec):\n    return int(spec)\n", encoding="utf-8")
    test = "tests/test_integer_walk.py::test_an_integer_fields_entry_names_a_site_a_why_and_a_test"
    good = {"site": "m.py:f:int(spec)#1", "why": "the check's own definition floors here", "test": test}
    assert tool.fields_problems([good], vdir) == []
    for bad, problem in ((dict(good, site="m.py:f:int(spec)#2"), "names no call in the verifiers"),
                         (dict(good, site="m.py:f:int(spec)"), "names no call in the verifiers"),
                         (dict(good, why=" "), "says no why: m.py:f:int(spec)#1"),
                         (dict(good, test="tests/test_integer_walk.py::no_such_test"), "names no test that exists"),
                         (dict(good, test="tools/integer_probe.py::main"), "names no test that exists")):
        problems = tool.fields_problems([bad], vdir)
        assert len(problems) == 1 and problems[0].startswith(problem), (bad, problems)
    assert tool.fields_problems([good, good], vdir) == ["named twice: m.py:f:int(spec)#1"]
    assert tool.fields_problems(tool.load_fields()) == []


# ── a scratch copy of the verifiers ───────────────────────────────────────────────────────────────────────────
def test_an_int_of_a_parameter_added_to_a_scratch_copy_is_found(tmp_path, walked_verifiers):
    tool = _tool()
    copy = tmp_path / "verifiers"
    shutil.copytree(tool.VERIFIERS, copy, ignore=shutil.ignore_patterns("__pycache__"))
    before = set(tool.walk(copy)["findings"])
    assert before == set(walked_verifiers["findings"])
    target = copy / "combinatorics.py"
    text = target.read_text(encoding="utf-8")
    anchor = "def verify_permutations(spec"
    assert anchor in text
    head, sep, rest = text.partition(anchor)
    signature, colon, body = rest.partition(":\n")
    text = head + sep + signature + colon + "    _added_by_the_walk_test = int(spec)\n" + body
    text += "\n\ndef _added_by_the_walk_test(value):\n    return int(value)\n"
    target.write_text(text, encoding="utf-8")
    after = set(tool.walk(copy)["findings"])
    assert after - before == {"combinatorics.py:verify_permutations:int(spec)#1",
                              "combinatorics.py:_added_by_the_walk_test:int(value)#1"}
    assert before - after == set()
