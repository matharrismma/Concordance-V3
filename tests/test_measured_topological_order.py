"""MEASURED.md's numbers on a topological evaluation order come from the tools, and stay theirs (run
2026-11-03-topological-order, step topo-record).

The section "A topological evaluation order: measurement 3" quotes tools/topo_order.py over the derivation tier,
one derivation outside it (the cycle the floor does not hold on, measured with the same tool and with
order_replica's _run), and the benchmark's single steps (tools/benchmark.py's case builders and
tools/halt_telemetry.py). These tests read every number and name the section quotes and compute each one again:

  fast    the tool over the rows from fast sources, which must match every quoted number that does not include
          the 1,500-step chain, the one row from a slow source; the totals that do include it are the fast rows'
          part plus the chain's quoted row. The cycle, the benchmark's count of single steps, and the passes the
          section takes from measurement 1 (the halting section's table, which its own slow test pins)
  slow    the tool over the whole tier and halt_telemetry over the whole benchmark, every quoted number compared
          with their output exactly

The tools are imported inside each test, so with the section absent each test reads red.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
HEADING = "## A topological evaluation order: measurement 3"
HALTING = "## Halting and order-freedom of the derivation closure"
COUNTER = "[b uses a, a false uses b]"
# the plan's rule for this record: statements it must make besides its numbers
STATED = ("The unit is closure passes saved, with verifier calls unchanged", "the tool measures no time or cost",
          "not callers' traffic", "The benchmark gains nothing", "no ranker, learned or not, could beat it",
          "is a separate decision, not made here", "Product line: cheaper derivations for callers who list against "
          "their edges, with no model, where cheaper means fewer closure passes and nothing more")


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _int(s):
    return int(s.replace(",", ""))


def _section(heading):
    text = (ROOT / "MEASURED.md").read_text(encoding="utf-8")
    assert text.count(heading) == 1, f"the section {heading!r} is absent or doubled"
    return text.split(heading, 1)[1].split("\n## ", 1)[0]


def _search(pattern, text, what):
    m = re.search(pattern, text, re.M)
    assert m, what
    return m


def quoted():
    """Every number and name the section quotes, read from MEASURED.md."""
    sec = _section(HEADING)
    words = re.sub(r"\s+", " ", sec)                  # the prose may wrap anywhere
    q = {}
    m = _search(r"^\| all (\d+) tier rows \| ([\d,]+) \| ([\d,]+) \| ([\d,]+) \|$", sec, "the passes over all rows")
    q["all"] = {"rows": int(m[1]), "listed": _int(m[2]), "topological": _int(m[3]), "saved": _int(m[4])}
    m = _search(r"^\| without the reversed ([\d,]+)-step chain \| ([\d,]+) \| ([\d,]+) \| ([\d,]+) \|$", sec,
                "the passes without the chain")
    q["without"] = {"steps": _int(m[1]), "listed": _int(m[2]), "topological": _int(m[3]), "saved": _int(m[4])}
    q["differ"] = {name: (_int(a), _int(b))
                   for name, a, b in re.findall(r"^\| `([^`]+)` \| ([\d,]+) \| ([\d,]+) \|$", sec, re.M)}
    m = _search(r"These are the (\d+) rows measurement 3 found above 2 passes; the other (\d+) were at the floor as "
                r"listed", words, "the rows measurement 3 named")
    q["m3"] = (int(m[1]), int(m[2]))
    m = _search(r"Under the topological order (\d+) of (\d+) tier rows reach the floor: (\d+) in 2 passes, and "
                r"`([^`]+)` in 1", words, "the floor")
    q["floor"] = {"reach": int(m[1]), "of": int(m[2]), "two": int(m[3]), "one": m[4]}
    q["acyclic"] = int(_search(r"For the (\d+) acyclic rows the floor is guaranteed by construction", words,
                               "the acyclic rows")[1])
    m = _search(r"For the (\d+) rows with a cycle in `below` it is measured, not proven: ((?:`[^`]+`(?:, )?)+)\.",
                words, "the cyclic rows")
    q["cyclic"] = {"count": int(m[1]), "rows": re.findall(r"`([^`]+)`", m[2])}
    m = _search(re.escape(f"`{COUNTER}`") + r", which is not a tier row, takes (\d+) passes under both orders.*?"
                r"visiting a first takes (\d+)", words, "the cycle the floor does not hold on")
    q["counter"] = (int(m[1]), int(m[2]))
    m = _search(r"(\d+) of (\d+) rows \((\d+)%\) give the same response except `halt.passes`", words, "identity")
    q["identity"] = (int(m[1]), int(m[2]), int(m[3]))
    q["calls"] = _int(_search(r"([\d,]+) under each order, the same multiset on every row", words, "the calls")[1])
    m = _search(r"its ([\d,]+) derivations are single steps, a single step has only one order, and each takes (\d+) "
                r"passes", words, "the benchmark")
    q["benchmark"] = (_int(m[1]), int(m[2]))
    q["stated"] = [s for s in STATED if s not in words]
    return q


def _measurement3_rows():
    return re.findall(r"^- more than 2 passes `([^`]+)`$", _section(HALTING), re.M)


def _benchmark_steps(B):
    """Every benchmark case as the steps it hands the closure: the derivation-moat claims go through
    derivation.verify, which is verify_derivation over one step; every other tier hands its steps as built."""
    return ([[spec] for _, spec, _ in B.CLAIMS]
            + [steps for build in (B._domain_cases, B._lighthouse_cases, B._check_cases) for _, steps, _ in build()])


def test_the_fast_part_of_the_topological_order_record_is_the_tools_output():
    q = quoted()
    assert q["stated"] == [], q["stated"]
    tool, H = _load("topo_order"), _load("halt_telemetry")
    rows = H.tier_rows("all")
    (chain,) = [r for r in rows if r["slow"]]
    rep = tool.run("fast")
    t, fast = rep["totals"], rep["rows"]
    assert tool.exit_code(rep) == 0 and rep["failures"] == [] and t["rows"] == len(rows) - 1
    # without the chain: the fast rows, exactly
    assert q["without"] == {"steps": len(chain["steps"]), "listed": t["passes"]["listed"],
                            "topological": t["passes"]["topological"], "saved": t["saving"]["all"]}
    # every row that differs: each fast one exactly, and the chain
    fast_differ = {r["name"]: (r["passes"]["listed"], r["passes"]["topological"]) for r in fast if r["saving"]}
    assert {n: v for n, v in q["differ"].items() if n != chain["name"]} == fast_differ
    assert set(q["differ"]) == set(fast_differ) | {chain["name"]}
    listed, topological = q["differ"][chain["name"]]
    # all rows: the fast part plus the chain's quoted row
    assert q["all"] == {"rows": len(rows), "listed": t["passes"]["listed"] + listed,
                        "topological": t["passes"]["topological"] + topological,
                        "saved": t["saving"]["all"] + listed - topological}
    # the rows that differ are measurement 3's, and the rest were at the floor as listed
    assert sorted(q["differ"]) == sorted(_measurement3_rows())
    assert q["m3"] == (len(q["differ"]), t["listed_at_floor"]) and t["listed_at_floor"] == len(rows) - len(q["differ"])
    # the floor: every fast row reaches it, and the chain's quoted passes are 2
    one = [r["name"] for r in fast if r["floor"] == 1]
    assert t["at_floor"] == len(fast) and topological == 2
    assert q["floor"] == {"reach": len(rows), "of": len(rows), "one": one[0],
                          "two": sum(1 for r in fast if r["passes"]["topological"] == 2) + 1} and len(one) == 1
    # every cyclic row is a fast row; the acyclic ones are the rest
    assert q["cyclic"] == {"count": len(t["cyclic"]), "rows": t["cyclic"]}
    assert q["acyclic"] == t["acyclic"] + 1 == len(rows) - len(t["cyclic"])
    # identity and calls: the fast rows' part, and the chain's one call per step
    assert t["identity"] == {"compared": len(fast), "identical": len(fast), "share": 1.0}
    assert q["identity"] == (len(rows), len(rows), 100)
    assert t["calls"]["listed"] == t["calls"]["topological"] and t["calls"]["equal_rows"] == len(fast)
    assert t["over_bound_rows"] == 0 and q["calls"] == t["calls"]["listed"] + len(chain["steps"])


def test_the_cycle_and_the_benchmark_are_as_the_record_says():
    """The cycle the floor does not hold on, through the tool and under order_replica's _run with a visited
    first; and the benchmark's derivations, every one a single step, at measurement 1's passes."""
    q = quoted()
    tool, H, R = _load("topo_order"), _load("halt_telemetry"), _load("order_replica")
    if str(FIXTURES) not in sys.path:
        sys.path.insert(0, str(FIXTURES))
    from derivation_tier import num
    steps = [num("b", "3+3", 6, uses=["a"]), num("a", "2+2", 5, uses=["b"])]
    rep = tool.run_rows([{"name": COUNTER, "steps": steps}])
    (row,) = rep["rows"]
    both, first_a = q["counter"]
    assert row["passes"] == {"listed": both, "topological": both} and row["leftovers"] == [0, 1]
    assert tool.exit_code(rep) == 0
    with H.isolated():
        from concordance import derivation as D
        r, _ = R._run(D, steps, [1, 0])
    assert r["halt"]["passes"] == first_a < both
    B = H._load_benchmark()
    cases = _benchmark_steps(B)
    count, passes = q["benchmark"]
    assert count == len(cases) == len(H.benchmark_cases()) and {len(s) for s in cases} == {1}
    # the passes are measurement 1's: the halting section's benchmark cell
    cell = _search(r"^\| by halt\.passes \| ([^|]+) \|", _section(HALTING), "measurement 1's passes")[1].strip()
    assert cell == f"{passes}: {count:,}"


@pytest.mark.slow
def test_every_number_in_the_topological_order_record_is_the_tools_output():
    """The whole tier, the 1,500-step chain included, and the whole benchmark: every quoted number exactly."""
    q = quoted()
    tool, H = _load("topo_order"), _load("halt_telemetry")
    rep = tool.run("all")
    t, rows = rep["totals"], rep["rows"]
    assert tool.exit_code(rep) == 0 and rep["failures"] == []
    fast = [r for r in rows if not r["slow"]]
    (chain,) = [r for r in rows if r["slow"]]
    assert q["all"] == {"rows": t["rows"], "listed": t["passes"]["listed"], "topological": t["passes"]["topological"],
                        "saved": t["saving"]["all"]}
    assert q["without"] == {"steps": chain["steps"], "listed": sum(r["passes"]["listed"] for r in fast),
                            "topological": sum(r["passes"]["topological"] for r in fast), "saved": t["saving"]["fast_rows"]}
    assert q["differ"] == {r["name"]: (r["passes"]["listed"], r["passes"]["topological"]) for r in rows if r["saving"]}
    assert q["m3"] == (len(t["differing"]), t["listed_at_floor"])
    assert q["floor"] == {"reach": t["at_floor"], "of": t["rows"],
                          "two": sum(1 for r in rows if r["passes"]["topological"] == 2),
                          "one": next(r["name"] for r in rows if r["floor"] == 1 and r["at_floor"])}
    assert sum(1 for r in rows if r["floor"] == 1) == 1
    assert q["acyclic"] == t["acyclic"] and q["cyclic"] == {"count": len(t["cyclic"]), "rows": t["cyclic"]}
    i = t["identity"]
    assert q["identity"] == (i["identical"], i["compared"], round(100 * i["share"]))
    assert q["calls"] == t["calls"]["listed"] == t["calls"]["topological"]
    assert t["calls"]["equal_rows"] == t["rows"] and t["over_bound_rows"] == 0
    bench = H.run("benchmark")["benchmark"]
    count, passes = q["benchmark"]
    assert (count, {str(passes): count}) == (bench["derivations"], bench["passes"])
