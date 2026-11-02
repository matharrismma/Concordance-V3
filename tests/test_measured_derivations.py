"""MEASURED.md's numbers on the derivation closure come from the tools, and stay theirs (run 2026-11-02-halt-and-order,
step measured-record).

The section "Halting and order-freedom of the derivation closure" quotes tools/halt_telemetry.py (measurement 1),
tools/order_replica.py (measurement 2) and the measurement 3 share computed from the first. These tests read every
number and name the section quotes and compute each one again:

  fast    what the rows from fast sources and the tools' own rules decide without the slow row: every named
          INCOMPLETE and SYSTEM_ERROR of the tier with its causes, the tier's row count, the order replica's count
          of evaluation orders and listings (from its rule, which needs no verification) and the rows it runs on
          the evaluation order only, and the part of the passes distribution and of measurement 3 the fast rows
          make up
  slow    both tools over the whole benchmark and the whole tier, every quoted number compared with their output
          (about a minute: the benchmark, the 1,500-step chain and the 720-order rows)

The tools are imported inside each test, so with the section absent each test reads red.
"""
from __future__ import annotations

import importlib.util
import re
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HEADING = "## Halting and order-freedom of the derivation closure"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _int(s):
    return int(s.replace(",", ""))


def quoted():
    """Every number and name the section quotes, read from MEASURED.md."""
    text = (ROOT / "MEASURED.md").read_text(encoding="utf-8")
    assert text.count(HEADING) == 1, "the section is absent or doubled"
    sec = text.split(HEADING, 1)[1].split("\n## ", 1)[0]
    table = {}
    for line in sec.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 3 and cells[0] in ("derivations", "by halt.passes", "cap fired", "INCOMPLETE", "SYSTEM_ERROR"):
            table[cells[0]] = cells[1:]
    assert set(table) == {"derivations", "by halt.passes", "cap fired", "INCOMPLETE", "SYSTEM_ERROR"}, table

    def passes(cell):
        return {int(p): _int(n) for p, n in (x.split(":") for x in cell.split(", "))}

    q = {"benchmark": {}, "tier": {}}
    for i, key in enumerate(("benchmark", "tier")):
        q[key] = {"derivations": _int(table["derivations"][i]), "passes": passes(table["by halt.passes"][i]),
                  "cap_fired": _int(table["cap fired"][i]),
                  "counts": {k: _int(table[k][i]) for k in ("INCOMPLETE", "SYSTEM_ERROR")},
                  "each": {"INCOMPLETE": [], "SYSTEM_ERROR": []}}
    for key, kind, name, causes in re.findall(r"^- (benchmark|tier) (INCOMPLETE|SYSTEM_ERROR) `([^`]+)`: (.+)$", sec, re.M):
        q[key]["each"][kind].append({"name": name, "causes": causes.split(", ")})
    words = re.sub(r"\s+", " ", sec)                  # the prose may wrap anywhere
    m = re.search(r"([\d,]+) rows under ([\d,]+) evaluation orders and ([\d,]+) listings: ([\d,]+) compared, "
                  r"([\d,]+) identical \((\d+(?:\.\d+)?)%\)", words)
    assert m, "measurement 2's line"
    q["replica"] = {"rows": _int(m[1]), "evaluation_orders": _int(m[2]), "listings": _int(m[3]),
                    "compared": _int(m[4]), "identical": _int(m[5]), "identity_pct": float(m[6]),
                    "evaluation_only": dict(re.findall(r"^- evaluation order only `([^`]+)`: (.+)$", sec, re.M))}
    m = re.search(r"(\d+) of (\d+) tier rows \((\d+\.\d)%\) need more than 2 passes", words)
    assert m, "measurement 3's line"
    q["share"] = {"count": int(m[1]), "of": int(m[2]), "pct": float(m[3]),
                  "rows": re.findall(r"^- more than 2 passes `([^`]+)`$", sec, re.M)}
    return q


def _named(rep):
    return {k: [{"name": e["name"], "causes": e["causes"]} for e in rep["each"][k]] for k in ("INCOMPLETE", "SYSTEM_ERROR")}


def test_the_fast_part_of_the_measured_record_is_the_tools_output():
    q = quoted()
    H, R = _load("halt_telemetry"), _load("order_replica")
    rows = H.tier_rows("all")
    slow = [r for r in rows if r["slow"]]
    fast = H.run("tier", "fast")["tier"]
    # every named INCOMPLETE and SYSTEM_ERROR of the tier is a fast row's, with these causes
    assert q["tier"]["each"] == _named(fast)
    assert {k: len(v) for k, v in q["tier"]["each"].items()} == q["tier"]["counts"]
    # the rows: 63 measured, and what the replica's rule asks of each, which needs no verification
    assert q["tier"]["derivations"] == q["replica"]["rows"] == q["share"]["of"] == len(rows)
    evals = sum(len(R.orders(len(r["steps"]), 0, r["name"])) for r in rows)
    lists = sum(len(R.orders(len(r["steps"]), 1, r["name"])) for r in rows if R.unique_ids(r["steps"]))
    assert (q["replica"]["evaluation_orders"], q["replica"]["listings"]) == (evals, lists)
    assert q["replica"]["compared"] == evals + lists
    assert q["replica"]["evaluation_only"] == {r["name"]: R._skipped(r["steps"]) for r in rows if R._skipped(r["steps"])}
    # the passes and measurement 3: the fast rows' part exactly, the rest one count per slow row
    rest = Counter(q["tier"]["passes"]) - Counter({int(p): n for p, n in fast["passes"].items()})
    assert sum(rest.values()) == len(slow) and all(p > 0 for p in rest)
    assert set(fast["above_two_passes"]["rows"]) <= set(q["share"]["rows"])
    assert set(q["share"]["rows"]) - set(fast["above_two_passes"]["rows"]) <= {r["name"] for r in slow}
    assert q["share"]["count"] == len(q["share"]["rows"]) and q["share"]["pct"] == round(100 * q["share"]["count"] / q["share"]["of"], 1)


@pytest.mark.slow
def test_every_number_in_the_measured_record_is_the_tools_output():
    q = quoted()
    H, R = _load("halt_telemetry"), _load("order_replica")
    m1 = H.run()
    for key in ("benchmark", "tier"):
        rep = m1[key]
        assert q[key]["derivations"] == rep["derivations"]
        assert q[key]["passes"] == {int(p): n for p, n in rep["passes"].items()}
        assert q[key]["cap_fired"] == rep["cap_fired"] == 0
        assert q[key]["counts"] == {k: rep["verdicts"].get(k, 0) for k in ("INCOMPLETE", "SYSTEM_ERROR")}
        assert q[key]["each"] == _named(rep)
    a = m1["tier"]["above_two_passes"]
    assert (q["share"]["count"], q["share"]["of"], q["share"]["rows"]) == (a["count"], a["of"], a["rows"])
    assert q["share"]["pct"] == round(100 * a["share"], 1)
    m2 = R.run("all")
    t = m2["totals"]
    assert (q["replica"]["rows"], q["replica"]["evaluation_orders"], q["replica"]["listings"], q["replica"]["compared"],
            q["replica"]["identical"]) == (t["rows"], t["evaluation_orders"], t["listings"], t["compared"], t["identical"])
    assert q["replica"]["identity_pct"] == round(100 * t["identity"], 2) and t["mismatches"] == 0
    assert q["replica"]["evaluation_only"] == {r["name"]: r["listing_skipped"] for r in m2["rows"] if r["listing_skipped"]}
