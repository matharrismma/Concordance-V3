"""THE MEMO: a domain's fingerprint hashes everything a verdict in it reads, so a stored verdict cannot outlive a change.

The fingerprint hashes the import closure of the domain's verifier inside src/concordance, and of the runner, verifiers/
__init__.py, whose run_for_domain drives every domain and calls verifiers/spec.py for each; so verifiers/__init__.py and
spec.py are in every closure. derivation.py, which folds every verdict, is hashed for every domain and not walked: it
imports the bridges and mathematics for all, and a domain that never reads them must not move with them. The closure is
read from each module's syntax tree, lazy imports included, and resolved through each module's __file__, so nothing is
imported to compute it, and a changed copy of a module moves the key as a ship would.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

from concordance import bucket, derivation
from concordance.derivation import verify_derivation
from concordance.verifiers import base, physical_constants, scale_base, si_units, spec as spec_module

P = "concordance."
V = P + "verifiers."
RUNNER = {P[:-1], P + "cas", P + "config", P + "layers", P + "validate", P + "derivation", V[:-1], V + "base", V + "spec"}
GRAVITY = {V + "grav_scale", V + "scale_base", V + "physical_constants", V + "si_units"}
CLOSURES = {
    "public_finance": RUNNER | {V + "public_finance"},
    "economics": RUNNER | {V + "economics"},
    "chess": RUNNER | {V + "chess", P + "chess"},
    "mathematics": RUNNER | {V + "mathematics", V + "_boolean"},
    "math": RUNNER | {V + "mathematics", V + "_boolean"},
    "astronomy": RUNNER | GRAVITY | {V + "astronomy", V + "rela_scale"},
    "physics": RUNNER | GRAVITY | {V + "physics", V + "mathematics", V + "_boolean", V + "rela_scale", V + "planck_scale"},
}


@pytest.fixture(autouse=True)
def memo_on(tmp_path, monkeypatch):
    monkeypatch.setenv("CONCORDANCE_MEMO", "1")
    monkeypatch.setenv("CONCORDANCE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("CONCORDANCE_CAS_DIR", raising=False)
    monkeypatch.setattr(bucket, "_FINGERPRINTS", {})


def _change_a_copy(monkeypatch, tmp_path, module):
    """The module's source as a ship would change it, with the per-process cache gone, as in a new process."""
    copy = tmp_path / ("changed_" + module.__name__.replace(".", "_") + ".py")
    copy.write_bytes(Path(module.__file__).read_bytes() + b"\n# a changed copy\n")
    monkeypatch.setattr(module, "__file__", str(copy))
    monkeypatch.setattr(bucket, "_FINGERPRINTS", {})


@pytest.mark.parametrize("domain", sorted(CLOSURES))
def test_the_closure_of_a_domain_is_what_its_verdict_reads(domain):
    assert set(bucket.verifier_closure(domain)) == CLOSURES[domain]


def test_an_unknown_domain_has_no_closure_and_no_fingerprint():
    assert bucket.verifier_closure("no_such_domain") == []
    assert bucket.verifier_fingerprint("no_such_domain") == "unknown"
    assert bucket.key_for("no_such_domain", "a" * 64) is None


def test_every_verifier_has_a_fingerprint_and_hashes_the_shared_comparison():
    from concordance import verifiers
    one_name_each = {module: domain for domain, module in verifiers.VERIFIERS.items()}
    for module, domain in sorted(one_name_each.items()):
        assert bucket.verifier_fingerprint(domain) != "unknown", domain
        assert {module, V + "base", V[:-1], V + "spec", P + "derivation"} <= set(bucket.verifier_closure(domain)), domain


# A shared module, a domain that reads it, and a domain that does not.
SHARED = [
    (scale_base, "astronomy", "chess"),
    (scale_base, "physics", "public_finance"),
    (si_units, "physical_constants", "economics"),
    (physical_constants, "astronomy", "economics"),
]
SHARED_IDS = ["scale_base-astronomy", "scale_base-physics", "si_units", "physical_constants"]


@pytest.mark.parametrize("module, reads, does_not", SHARED, ids=SHARED_IDS)
def test_a_changed_shared_module_moves_the_key_of_a_domain_that_reads_it_and_no_other(module, reads, does_not, tmp_path, monkeypatch):
    before = {d: (bucket.verifier_fingerprint(d), bucket.key_for(d, "a" * 64)) for d in (reads, does_not)}
    assert all(fp != "unknown" and key for fp, key in before.values())
    _change_a_copy(monkeypatch, tmp_path, module)
    assert bucket.verifier_fingerprint(reads) != before[reads][0]
    assert bucket.key_for(reads, "a" * 64) != before[reads][1]
    assert bucket.verifier_fingerprint(does_not) == before[does_not][0]
    assert bucket.key_for(does_not, "a" * 64) == before[does_not][1]


@pytest.mark.parametrize("module", [base, derivation, spec_module, sys.modules["concordance.verifiers"]],
                         ids=["base", "derivation", "spec", "verifiers-init"])
@pytest.mark.parametrize("domain", ["public_finance", "chess", "mathematics", "physics", "geometry", "astronomy"])
def test_what_every_verdict_reads_moves_every_domains_key(module, domain, tmp_path, monkeypatch):
    key = bucket.key_for(domain, "a" * 64)
    _change_a_copy(monkeypatch, tmp_path, module)
    assert bucket.key_for(domain, "a" * 64) != key


FALSE_ESCAPE = {"id": "s", "domain": "astronomy", "spec": {"ASTRO_VERIFY": {
    "escape_mass_kg": 5.972e24, "escape_radius_m": 6.371e6, "claimed_escape_velocity_m_s": 12000.0}}}
FALSE_AREA = {"id": "s", "domain": "geometry", "spec": {"GEOM_VERIFY": {"circle_radius": 3, "claimed_circle_area": 30}}}


@pytest.mark.parametrize("step, module", [(FALSE_ESCAPE, scale_base), (FALSE_ESCAPE, base), (FALSE_AREA, base)],
                         ids=["astronomy-scale_base", "astronomy-base", "geometry-base"])
def test_a_verdict_stored_before_a_shared_module_changed_is_not_served(step, module, tmp_path, monkeypatch):
    """A stored CONFIRMED seals as HOLDS, so this one is planted on a false claim: the older verdict must not come back."""
    t = verify_derivation([step])["trail"][0]
    key, domain, spec_hash = t["memo"]["key"], step["domain"], t["spec_hash"]
    assert bucket.store(key, {"status": "CONFIRMED", "detail": "as an older verifier read it"}, domain, spec_hash)
    assert verify_derivation([step])["trail"][0]["memo"]["hit"] is True      # the memo is on, and it serves this entry
    _change_a_copy(monkeypatch, tmp_path, module)
    r = verify_derivation([step])
    assert r["trail"][0]["memo"]["hit"] is False and r["trail"][0]["memo"]["key"] != key
    assert r["verdict"] == "BROKEN"
    assert (bucket._dir() / (key + ".json")).exists()                        # it stays on disk, unread


def test_a_lazy_import_counts():
    """physical_constants reads si_units from inside a function: the walk sees what the import lines at the top do not."""
    source = Path(physical_constants.__file__).read_text(encoding="utf-8")
    top = [a.name for n in ast.parse(source).body if isinstance(n, ast.ImportFrom) for a in n.names]
    assert "si_units" not in top and V + "si_units" in bucket.verifier_closure("physical_constants")


def test_the_closure_imports_nothing(monkeypatch):
    """A module the source names but no one has imported is read from its file, not loaded."""
    from concordance.verifiers import astronomy  # noqa: F401 — the root is loaded, as the registry would load it
    gone = V + "rela_scale"
    monkeypatch.delitem(sys.modules, gone, raising=False)
    assert gone in bucket.verifier_closure("astronomy") and gone not in sys.modules


def test_a_name_that_is_no_module_is_left_out():
    assert bucket._source(V + "base.band") is None and bucket._source(P + "no_such_module") is None
    assert not any(m.endswith((".band", ".error", ".confirm")) for m in bucket.verifier_closure("economics"))


def test_a_file_that_cannot_be_read_means_no_memo_never_a_guessed_key(tmp_path, monkeypatch):
    monkeypatch.setattr(scale_base, "__file__", str(tmp_path / "gone.py"))
    monkeypatch.setattr(bucket, "_FINGERPRINTS", {})
    assert bucket.verifier_fingerprint("astronomy") == "unknown"
    assert bucket.key_for("astronomy", "a" * 64) is None


def test_the_fingerprint_is_cached_per_process(monkeypatch):
    first = bucket.verifier_fingerprint("economics")
    monkeypatch.setattr(bucket, "_sources", lambda d: pytest.fail("the cache was not used"))
    assert bucket.verifier_fingerprint("economics") == first
