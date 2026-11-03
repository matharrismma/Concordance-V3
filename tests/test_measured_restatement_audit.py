"""MEASURED.md's numbers on the restatement audit come from the tools, and stay theirs (run
2026-11-03-restatement-audit, step audit-record).

The section "The restatement audit: measurement 4" quotes tools/restatement_audit.py over the 1,796 benchmark cases
and every derivation-tier row, and four facts the audit does not measure: how the MATH_VERIFY packets route, the
numeric mode's footprint in the tier, the pressure_fighting frame_seq gap and the gcd/lcm reading. These tests read
every number and name the section quotes and compute each one again:

  fast    the tool's own run() over the whole population with only its verifier runs stubbed (each returns one
          fixed response, so nothing runs a verifier and nothing changes): every restatement, decline, coverage
          count and total is the tool's. The MATH_VERIFY routing (mathematics.py's own _RULES), the numeric
          footprint (the tier's steps), and the two gaps, recomputed through the real verifiers: frame_seq 1 read
          as 1.0, and the three gcd/lcm claims renamed by R4. Those two pin today's defective readings, so the runs
          that fix them update these tests
  slow    the whole audit for real, every quoted number compared with its output exactly, its changes included

Times are this laptop's and its load's; the section says so, and no test pins them. The tools are imported inside
each test, so with the section absent each test reads red.
"""
from __future__ import annotations

import copy
import importlib.util
import re
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HEADING = "## The restatement audit: measurement 4"
FRAME_SEQ = ("golden:pressure_fighting:true", "check:pressure_fighting.observation:true")
GCD = (("gcd(y - x, x - y)", "x - y", "HOLDS", "BROKEN"), ("gcd(y**2 - x**2, x - y)", "x - y", "HOLDS", "BROKEN"),
       ("lcm(y - x, x - y)", "x - y", "BROKEN", "HOLDS"))
NAMES = {"R1": "key order", "R2": "equality swap", "R3": "whitespace between tokens", "R4": "symbol rename",
         "R5": "step-id rename"}
PATHS = ("derivation", "compose", "mcp", "mcp-document", "audit")
# what the plan requires the record to say besides its numbers
STATED = (
    "It is an audit, never a vote", "nothing in src/ reads it",
    "the audit holds no such restatement", "this run's test recomputes it",
    "the test pins today's reading, so the run that fixes it updates the test",
    "so KNOWN does not list it", "2026-11-03T14:20:34Z",
    "on this laptop with another heavy Python process running throughout", "no test pins them",
    "`PYTHONPATH=src python tools/restatement_audit.py --json audit.json`",
    "`--benchmark per-domain --tier fast`", "`PYTHONPATH=src python -m pytest tests/test_measured_restatement_audit.py",
    "Product line: finds verifier and closure defects before users do; never a verdict path.",
)


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _int(s):
    return int(s.replace(",", ""))


def _section():
    text = (ROOT / "MEASURED.md").read_text(encoding="utf-8")
    assert text.count(HEADING) == 1, f"the section {HEADING!r} is absent or doubled"
    return text.split(HEADING, 1)[1].split("\n## ", 1)[0]


def _search(pattern, text, what):
    m = re.search(pattern, text, re.M)
    assert m, what
    return m


def quoted():
    """Every number and name the section quotes, read from MEASURED.md."""
    sec = _section()
    words = re.sub(r"\s+", " ", sec)                  # the prose may wrap anywhere
    q = {}
    m = _search(r"([\d,]+) benchmark cases and (\d+) tier rows, measured on (\d+) row-paths", words, "what was audited")
    q["audited"] = {"cases": _int(m[1]), "rows": int(m[2]), "row_paths": int(m[3])}
    m = _search(r"\((\d+) derivation, (\d+) compose, (\d+) mcp, (\d+) mcp-document, (\d+) audit\)", words, "the paths")
    q["paths"] = dict(zip(PATHS, map(int, m.groups())))
    q["compared"] = _int(_search(r"([\d,]+) restated runs were compared", words, "the compared runs")[1])
    q["by_restatement"] = {k: {"name": n, "benchmark": _int(b), "tier": _int(t), "declined": _int(d)}
                           for k, n, b, t, d in re.findall(r"^\| (R\d) ([^|]+?) \| ([\d,]+) \| ([\d,]+) \| ([\d,]+) \|$",
                                                           sec, re.M)}
    m = _search(r"None: (\d+) changes of any kind. Exit-1 changes first \([^)]*\): (\d+), and KNOWN holds (\d+) "
                r"entries. Wants: (\d+), and among them, listed first, a verdict that became HOLDS on a tier row no "
                r"source asserts a verdict on: (\d+). No run raised, and no change rests on a timed-out run. The tool "
                r"exits (\d)", words,
                "every change")
    q["changes"] = dict(zip(("all", "exit_one", "known", "wants", "unasserted_holds", "exit"), map(int, m.groups())))
    m = _search(r"R2, R3 and R4 reach (\d+), (\d+) and (\d+) benchmark cases", words, "R2-R4 on the benchmark")
    q["r234_benchmark"] = tuple(map(int, m.groups()))
    m = _search(r"(\d+) of the (\d+) benchmark domains are reached only by R1", words, "the R1-only domains")
    q["only_r1"] = (int(m[1]), int(m[2]))
    m = _search(r"All (\d+) MATH_VERIFY packets are declined.*?(\d+) of them route to verifier functions R2-R4 map", words,
                "the MATH_VERIFY packets")
    q["math_verify"] = (int(m[1]), int(m[2]))
    m = _search(r"([\d,]+) of the tier's steps are, in (\d+) of its (\d+) rows \((\d+) fast rows and the reversed "
                r"([\d,]+)-step chain\)", words, "the numeric footprint")
    q["numeric"] = {"steps": _int(m[1]), "rows": int(m[2]), "of": int(m[3]), "fast_rows": int(m[4]),
                    "chain": _int(m[5])}
    q["numeric_benchmark"] = "No benchmark case is in it" in words
    m = _search(r"On the tier, R2 and R3 reach (\d+) row-paths and R4 (\d+)\. The (\d+) rows audit\.audit builds from "
                r"text are reached only by R5.*?tools/restate\.py alone would restate (\d+) with R2 and R3", words,
                "R2-R4 on the tier")
    q["r234_tier"] = {"r2_r3": int(m[1]), "r4": int(m[2]), "text_rows": int(m[3]), "alone": int(m[4])}
    q["domains"] = {d: {"cases": _int(n), **{k: _int(v) for k, v in zip(NAMES, vals)}}
                    for d, n, *vals in re.findall(r"^\| ([a-z_]+) \| ([\d,]+) \| ([\d,]+) \| ([\d,]+) \| ([\d,]+) \| "
                                                  r"([\d,]+) \| ([\d,]+) \|$", sec, re.M)}
    q["frame_seq"] = [c for c in FRAME_SEQ if c in words]
    q["frame_seq_cited"] = all(s in words for s in ('"NO_MATCH: frame_seq must be an integer >= 1"',
                                                    "pressure_fighting.py:92", "frame_seq 1 rewritten as 1.0"))
    q["gcd"] = re.findall(r"(gcd|lcm)\(([^)]*)\) = x - y (?:and gcd\(([^)]*)\) = x - y )?reads? (HOLDS|BROKEN) and, "
                          r"renamed(?: by R4)?, (HOLDS|BROKEN)", words.replace("`", ""))
    m = _search(r"the benchmark took ([\d.]+) s and the tier ([\d.]+) s.*?between ([\d.]+) s and ([\d.]+) s for the "
                r"benchmark", words, "the times")
    q["times"] = tuple(map(float, m.groups()))
    q["stated"] = [s for s in STATED if s not in words]
    return q


def _stubbed(tool, monkeypatch):
    """tools/restatement_audit.py's own run() over the whole population, with only the verifier runs stubbed."""
    fixed = {"verdict": "HOLDS", "trail": []}
    real_b, real_t = tool.benchmark_population, tool.tier_population

    def stub(subject):
        return dict(fixed)
    monkeypatch.setattr(tool, "benchmark_population", lambda *a, **k: [dict(c, run=stub) for c in real_b(*a, **k)])
    monkeypatch.setattr(tool, "tier_population", lambda *a, **k: [dict(c, run=stub) for c in real_t(*a, **k)])
    return tool.run("all", "all")


def _counts(rep):
    """What the record quotes of an audit report, in the shape quoted() reads."""
    cov = rep["coverage"]["by_domain"]
    bench = {k: sum(row[k]["applied"] for row in cov.values()) for k in NAMES}
    tier = rep["tier_coverage"]
    return {
        "audited": {"cases": rep["populations"]["benchmark"]["cases"], "row_paths": rep["populations"]["tier"]["cases"]},
        "paths": {p: tier[p]["rows"] for p in PATHS},
        "compared": rep["compared"],
        "by_restatement": {k: {"name": NAMES[k], "benchmark": bench[k], "tier": rep["by_restatement"][k]["applied"]
                               - bench[k], "declined": rep["by_restatement"][k]["declined"]} for k in NAMES},
        "r234_benchmark": (bench["R2"], bench["R3"], bench["R4"]),
        "only_r1": (len(rep["coverage"]["reached_only_by_R1"]), len(cov)),
        "domains": {d: {"cases": row["R1"]["applied"] + row["R1"]["declined"], **{k: row[k]["applied"] for k in NAMES}}
                    for d, row in cov.items()},
        "tier_r2_r3": (sum(r["R2"] for r in tier.values()), sum(r["R3"] for r in tier.values())),
        "tier_r4": sum(r["R4"] for r in tier.values()),
    }


def _check_counts(q, c, rows):
    assert q["audited"] == {"cases": c["audited"]["cases"], "rows": len(rows), "row_paths": c["audited"]["row_paths"]}
    assert q["paths"] == c["paths"] and sum(q["paths"].values()) == q["audited"]["row_paths"]
    assert q["compared"] == c["compared"] == sum(r["benchmark"] + r["tier"] for r in q["by_restatement"].values())
    assert q["by_restatement"] == c["by_restatement"]
    for k, r in q["by_restatement"].items():           # every restatement is applied or declined on every case
        assert r["benchmark"] + r["tier"] + r["declined"] == q["audited"]["cases"] + q["audited"]["row_paths"], k
    assert q["r234_benchmark"] == c["r234_benchmark"] and q["only_r1"] == c["only_r1"]
    assert q["domains"] == c["domains"] and len(q["domains"]) == q["only_r1"][1]
    assert sum(d["cases"] for d in q["domains"].values()) == q["audited"]["cases"]
    assert c["tier_r2_r3"] == (q["r234_tier"]["r2_r3"],) * 2 and c["tier_r4"] == q["r234_tier"]["r4"]


def test_the_section_states_what_the_plan_requires():
    q = quoted()
    assert q["stated"] == [], q["stated"]
    assert q["frame_seq"] == list(FRAME_SEQ) and q["frame_seq_cited"]
    assert sorted(q["by_restatement"]) == sorted(NAMES)
    assert [q["by_restatement"][k]["name"] for k in NAMES] == list(NAMES.values())
    assert q["numeric_benchmark"]
    assert len(q["times"]) == 4 and q["times"][2] <= q["times"][0] <= q["times"][3]


def test_the_fast_part_of_the_restatement_audit_record_is_the_tools_output(monkeypatch):
    """Every count the record quotes, from the tool's own run() with only its verifier runs stubbed; the MATH_VERIFY
    routing from mathematics.py's _RULES; the numeric footprint and the text rows from the tier."""
    q = quoted()
    tool, R = _load("restatement_audit"), _load("restate")
    H = tool._telemetry()
    rep = _stubbed(tool, monkeypatch)
    assert rep["errors"] == [] and rep["changes"] == [] and rep["exit_one"] == []
    rows = H._tier().rows()
    _check_counts(q, _counts(rep), rows)
    # the tier rows audit.audit builds from text, and what restate alone would do with R2 and R3 on the tier
    text_rows = [r for r in rows if r["text"]]
    alone = Counter(k for c in tool.tier_population(H) if c["path"] != "audit" for k in ("R2", "R3")
                    if R.restate(k, c["subject"]).applied)
    assert q["r234_tier"]["text_rows"] == len(text_rows) and q["r234_tier"]["alone"] == alone["R2"] == alone["R3"]
    assert alone["R2"] - q["r234_tier"]["r2_r3"] == len(text_rows)
    # the MATH_VERIFY packets, routed by mathematics.py's own dispatch table to the modes R2-R4 map
    from concordance import derivation as D
    from concordance.verifiers import mathematics as M
    mode_of = {f.__name__: m for m, f in D._MATH_MODES.items()}
    with H.isolated():
        packets = [s["spec"]["MATH_VERIFY"] for c in tool.benchmark_population(H) for s in c["subject"]
                   if isinstance(s.get("spec"), dict) and "MATH_VERIFY" in s["spec"]]
    fired = [[fn.__name__ for req, fn in M._RULES if (req(p) if callable(req) else all(k in p for k in req))]
             for p in packets]
    mapped = sum(1 for f in fired if f and all(mode_of.get(n) in R.MODES for n in f))
    assert q["math_verify"] == (len(packets), mapped)
    declined = [d for d in rep["declines"] if "MATH_VERIFY packet" in d["reason"]]
    assert {d["restatement"] for d in declined} == {"R2", "R3", "R4"} and len(declined) == 3 * len(packets)
    # the numeric mode: unmapped, in no benchmark case, and in the tier's steps
    def numeric(s):
        spec = s.get("spec")
        return (str(s.get("domain", "")).strip().lower() in ("mathematics", "math") and isinstance(spec, dict)
                and "MATH_VERIFY" not in spec and str(spec.get("mode") or "").strip().lower() == "numeric")
    assert "numeric" not in R.MODES
    with H.isolated():
        assert q["numeric_benchmark"] and not any(numeric(s) for c in tool.benchmark_population(H) for s in c["subject"])
    with_numeric = [r for r in rows if any(numeric(s) for s in r["steps"])]
    (chain,) = [r for r in rows if r["slow"]]
    assert q["numeric"] == {"steps": sum(1 for r in rows for s in r["steps"] if numeric(s)), "rows": len(with_numeric),
                            "of": len(rows), "fast_rows": sum(1 for r in with_numeric if not r["slow"]),
                            "chain": len(chain["steps"])}
    # every change is the slow test's to recompute; here, the record's zeros agree with KNOWN
    assert q["changes"]["known"] == len(tool.KNOWN) and q["changes"]["exit_one"] == len(tool.KNOWN)


def test_the_frame_seq_gap_is_recomputed():
    """The gap the audit does not measure, read through the benchmark's own path: each named case holds as given,
    and with frame_seq 1 rewritten as 1.0 it reads BROKEN, by the check at pressure_fighting.py:92. Today's
    defective reading, pinned: the run that fixes it updates this test."""
    q = quoted()
    tool = _load("restatement_audit")
    H = tool._telemetry()
    line = (ROOT / "src" / "concordance" / "verifiers" / "pressure_fighting.py").read_text(encoding="utf-8").splitlines()[91]
    assert 'isinstance(spec["frame_seq"], int)' in line
    with H.isolated():
        from concordance import derivation as D
        D.warm()
        cases = {c["case"]: c for c in tool.benchmark_population(H, names=FRAME_SEQ)}
        assert sorted(cases) == sorted(q["frame_seq"])
        for name in FRAME_SEQ:
            c = cases[name]
            as_given = c["run"](c["subject"])
            retyped = copy.deepcopy(c["subject"])
            obs = retyped[0]["spec"]["PFS_VERIFY"]["observation"]
            assert obs["frame_seq"] == 1 and type(obs["frame_seq"]) is int
            obs["frame_seq"] = 1.0
            read = c["run"](retyped)
            assert as_given["verdict"] == "HOLDS" and read["verdict"] == "BROKEN", name
            assert read["trail"][0]["detail"].endswith("NO_MATCH: frame_seq must be an integer >= 1"), name


def test_the_gcd_and_lcm_readings_are_recomputed():
    """Outside the audit's population: each claim, as given and renamed by R4, through benchmark.verify. The two
    verdicts cannot both be right; today's defective readings are pinned, so the run that fixes them updates this."""
    q = quoted()
    R = _load("restate")
    spec = importlib.util.spec_from_file_location("_measured_restatement_benchmark", ROOT / "tools" / "benchmark.py")
    B = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(B)
    readings = []
    for a, b, *_ in GCD:
        claim = {"mode": "equality", "params": {"expr_a": a, "expr_b": b, "variables": ["x", "y"]}}
        o = R.restate("R4", [{"id": "b", "domain": "mathematics", "spec": claim}])
        assert o.applied and o.mapping == {0: {"y": "v0", "x": "v1"}}
        readings.append((a, b, B.verify(copy.deepcopy(claim))["verdict"], B.verify(o.after[0]["spec"])["verdict"]))
    assert readings == list(GCD)
    # the record names each: gcd(y - x, x - y) and gcd(y**2 - x**2, x - y) HOLDS then BROKEN, lcm BROKEN then HOLDS
    assert [(f, args, also, before, after) for f, args, also, before, after in q["gcd"]] == [
        ("gcd", "y - x, x - y", "y**2 - x**2, x - y", "HOLDS", "BROKEN"), ("lcm", "y - x, x - y", "", "BROKEN", "HOLDS")]


@pytest.mark.slow
def test_every_number_in_the_restatement_audit_record_is_the_tools_output():
    """The whole audit for real: every quoted count, and every change (none), exactly."""
    q = quoted()
    tool = _load("restatement_audit")
    rep = tool.run("all", "all")
    rows = tool._telemetry()._tier().rows()
    _check_counts(q, _counts(rep), rows)
    unasserted = [c for c in rep["changes"] if "into_holds_unasserted" in c["kinds"]]
    assert q["changes"] == {"all": len(rep["changes"]), "exit_one": len(rep["exit_one"]), "known": len(tool.KNOWN),
                            "wants": len(rep["changes"]) - len(rep["exit_one"]), "unasserted_holds": len(unasserted),
                            "exit": tool.exit_code(rep)}
    assert rep["errors"] == [] and not any(c["timed_out"] for c in rep["changes"])
    assert {tuple(k) for k in rep["exit_one"]} == set(tool.KNOWN)
