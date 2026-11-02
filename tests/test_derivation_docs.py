"""The documents say what the derivation does (run 2026-11-02-order-free-derivation, step true-docs).

Since 6c63807 a derivation resolves its steps as a monotone closure: a step may bind to, or use, a step listed
anywhere, before it or after it. These statements still put an order on that: compose.py's docstring and
README's Documents section ("bind their inputs to earlier steps' outputs"), docs/ARCHITECTURE.md and the
generator it is made from ("bind to earlier outputs"), tests/test_binding.py's docstring ("a CONFIRMED prior
step's output"), and audit.audit's docstring and the comment over its sort ("the derivation must process a used
step before the step that uses it").

Each test finds its statement by an anchor that must occur exactly once, runs on the engine what the statement
describes with the steps listed against their edges, and then holds the statement to what ran: it may not put an
order on the steps a step binds to or uses, and it must say what is true instead.
"""
from __future__ import annotations

import ast
import copy
import inspect
import re
import sys
from pathlib import Path

import pytest

from concordance import audit as A
from concordance import compose
from concordance import derivation as D
from concordance.config import EngineConfig

ROOT = Path(__file__).resolve().parent.parent
# the derivations live in the tier (tests/fixtures/derivation_tier.py), their one home; README's document stays in
# README.md, read there by readme_document()
_FIXTURES = str(ROOT / "tests" / "fixtures")
if _FIXTURES not in sys.path:
    sys.path.insert(0, _FIXTURES)
from derivation_tier import AUDIT_TEXTS, BIND, BIND_FALSE_SOURCE, readme_document  # noqa: E402
ORDERED = re.compile(r"\b(earlier|prior|previous|preceding)\b", re.I)      # an order put on a step's sources
ANYWHERE = re.compile(r"\bwherever\b[^.;]*\blisted\b", re.I)                 # what is true instead
# a processing order said to be needed: "must process a used step before", "so a `uses` ref is processed first"
REQUIRED = re.compile(r"\b(must|so)\b[^.;]*\b(process|processed|run|runs)\b[^.;]*\b(before|first)\b", re.I)


@pytest.fixture(scope="module", autouse=True)
def _warm():
    D.warm()


def flat(s):
    return re.sub(r"\s+", " ", s or "")


def clause(text, lead):
    """What a statement says a step binds to: the words after `lead`, to the end of that clause."""
    hits = re.findall(re.escape(lead) + r"\s+([^.;(]*)", flat(text))
    assert len(hits) == 1, (lead, hits)
    return hits[0]


def fields(r):
    return {s["id"]: (s["status"], s["link_ok"], s["spec_hash"], tuple(s["uses"])) for s in r["steps"]}


def against_its_edges(doc):
    """The document as written and with its steps listed in reverse: every bind source listed after its user."""
    fwd = compose.seal_document(copy.deepcopy(doc), EngineConfig(), seal=False)
    rev = compose.seal_document(dict(copy.deepcopy(doc), steps=list(reversed(doc["steps"]))), EngineConfig(),
                                seal=False)
    return fwd, rev


def test_readme_documents_say_a_step_binds_to_a_step_listed_anywhere():
    section, doc = readme_document()
    assert any(s.get("bind") for s in doc["steps"])                 # the example binds
    fwd, rev = against_its_edges(doc)
    assert fwd["verdict"] == rev["verdict"] == "HOLDS"
    assert fields(fwd) == fields(rev)
    said = clause(section, "inputs to")
    assert not ORDERED.search(said), said
    assert ANYWHERE.search(said), said


def test_compose_docstring_says_a_step_binds_to_a_step_listed_anywhere():
    _, doc = readme_document()
    fwd, rev = against_its_edges(doc)
    assert fwd["verdict"] == rev["verdict"] == "HOLDS" and fields(fwd) == fields(rev)
    said = clause(compose.__doc__, "inputs to")
    assert not ORDERED.search(said), said
    assert ANYWHERE.search(said), said


def _item_8(text):
    lines = text.split("\n")
    at = [n for n, line in enumerate(lines) if line.startswith("8. **Document**")]
    assert len(at) == 1
    n = at[0] + 1
    while n < len(lines) and lines[n].startswith("   "):
        n += 1
    return "\n".join(lines[at[0]:n])


def test_architecture_matches_its_generator_and_says_what_compose_does():
    """docs/ARCHITECTURE.md is edited by hand (regenerating it on Windows changes the module counts), so its
    Document item must be exactly the generator's."""
    made = _item_8((ROOT / "tools" / "architecture_gen.py").read_text(encoding="utf-8")).replace("{{", "{").replace("}}", "}")
    held = _item_8((ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8"))
    assert held == made
    _, doc = readme_document()
    fwd, rev = against_its_edges(doc)
    assert fwd["verdict"] == rev["verdict"] == "HOLDS" and fields(fwd) == fields(rev)
    said = clause(held, "steps bind to")
    assert not ORDERED.search(said), said
    assert ANYWHERE.search(said), said


def test_binding_docstring_holds_with_the_source_listed_after_its_user():
    doc = ast.get_docstring(ast.parse((ROOT / "tests" / "test_binding.py").read_text(encoding="utf-8")))
    src, user = BIND                              # a1: 4x6 = 24; a2 binds a1.actual_area
    # BUILD an input from a CONFIRMED output, with the source listed after its user
    r = D.verify_derivation([copy.deepcopy(user), copy.deepcopy(src)])
    assert r["verdict"] == "HOLDS" and r["trail"][0]["status"] == "CONFIRMED" and "a1" in r["trail"][0]["uses"]
    # fail-closed: a broken source leaves the step a GAP, wherever the source is listed
    bad = copy.deepcopy(BIND_FALSE_SOURCE[0])     # a1 claiming 99
    r = D.verify_derivation([copy.deepcopy(user), bad])
    assert r["verdict"] == "BROKEN" and r["trail"][0]["status"] == "NOT_APPLICABLE"
    assert r["trail"][0]["unresolved_binding"] == ["GEOM_VERIFY.rect_length<-a1.actual_area"]
    said = clause(doc, "BUILD an input from")
    assert not ORDERED.search(said), said
    assert ANYWHERE.search(said), said


def _comment_over_the_sort():
    lines = inspect.getsource(A.audit).split("\n")
    at = [n for n, line in enumerate(lines) if line.strip().startswith("order = sorted(")]
    assert len(at) == 1
    n = at[0]
    while lines[n - 1].strip().startswith("#"):
        n -= 1
    return " ".join(line.strip().lstrip("#").strip() for line in lines[n:at[0]])


def _composition_paragraph():
    paras = [p for p in A.audit.__doc__.split("\n\n") if "Composition (2026-09-25)" in p]
    assert len(paras) == 1
    return flat(paras[0])


def test_audit_says_its_text_order_is_kept_for_reading_not_needed_for_the_verdict(monkeypatch):
    """audit.audit still lists the derivation in text order, and its comment and docstring must say why: not
    because the closure needs a used claim first (it does not), but so the trail, the seal and where trust
    stopped read in the order the text states the claims."""
    seen = []
    real = D.verify_derivation

    def captured(steps):
        seen.append(copy.deepcopy(steps))
        return real(steps)

    monkeypatch.setattr(D, "verify_derivation", captured)
    for text in AUDIT_TEXTS:
        seen.clear()
        res = A.audit(text, EngineConfig(skip_schema_validation=True), seal=False)
        (listed,) = seen
        assert len(listed) >= 2
        at = {s["id"]: text.find(s["claim"]) for s in listed}
        assert all(p >= 0 for p in at.values()) and [at[s["id"]] for s in listed] == sorted(at.values())
        for s in listed:                       # a `uses` ref is always an earlier claim
            assert all(at[u] < at[s["id"]] for u in s.get("uses") or [])
        fwd, rev = real(copy.deepcopy(listed)), real(copy.deepcopy(list(reversed(listed))))
        # not needed for the verdict: listed against its edges, the same verdict, step for step
        assert fwd["verdict"] == rev["verdict"] == res["verdict"] == "BROKEN"
        by = lambda r: {t["id"]: (t["status"], t["link_ok"], t.get("builds_on_unconfirmed")) for t in r["trail"]}
        assert by(fwd) == by(rev)
        # kept for reading: the trail, and where trust stopped, follow the text
        assert [t["id"] for t in fwd["trail"]] == [s["id"] for s in listed]
        assert fwd["broken_at"] == listed[0]["id"]
    assert rev["broken_at"] == listed[-1]["id"] != fwd["broken_at"]   # two false claims: the text order names one
    for said in (_comment_over_the_sort(), _composition_paragraph()):
        assert not REQUIRED.search(said), said
        assert ANYWHERE.search(said), said
