"""The completeness capture for the derivation tier (run 2026-11-02-halt-and-order, step derivation-tier).

It wraps verify_derivation under every name a caller holds it by and records every listing handed to it that
has 2 or more steps, or a cycle (a one-step listing whose step uses or binds from its own id). The names, found
by searching src/ for the import:

    concordance.derivation.verify_derivation      the definition; a direct call, and audit.audit, which
                                                  imports it inside audit() at call time (audit.py)
    concordance.compose.verify_derivation         bound at import (compose.py); compose.seal_document, and
                                                  the MCP verify tool given a document
    concordance.mcp.server.verify_derivation      bound at import (mcp/server.py); the MCP verify tool given
                                                  steps, and the HTTP /verify route through it
    concordance.scribe.core.verify_derivation     bound at import (scribe/core.py); the scribe's scoring

A test module that imports the name at its top (tests/test_refutations.py, tests/test_binding.py) holds the
definition's wrapper, because run() installs the wrappers before pytest imports any test module.

Nothing here judges a test or chooses which tests run: run() calls pytest.main in its own process and only
watches what reaches verify_derivation, keyed by the canonical hash of the listing (the one canonical form,
validate.canonical_json_bytes). In that process it also watches itertools.permutations, recording for every
listing it yields the base it was generated from and the test that generated it, so a listing a source generates
by sweeping the permutations of a base listing can be told from a listing a source writes: unaccounted() accepts
a listing as generated only when EVERY test that passed it generated it by sweeping a held base.

    python tests/fixtures/derivation_capture.py OUT.json -- <pytest args>
"""
from __future__ import annotations

import copy
import hashlib
import importlib
import itertools
import json
import os
import sys
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

# (module, attribute): every name verify_derivation is held by in src/ (see the docstring).
NAMES = (
    ("concordance.derivation", "verify_derivation"),
    ("concordance.compose", "verify_derivation"),
    ("concordance.mcp.server", "verify_derivation"),
    ("concordance.scribe.core", "verify_derivation"),
)
# the caller's module -> the path a listing came by
PATHS = {"concordance.audit": "audit", "concordance.compose": "compose", "concordance.mcp.server": "mcp",
         "concordance.scribe.core": "scribe"}


def listing_hash(steps: Any) -> str:
    """The canonical hash of a listing: SHA-256 of its one canonical form. Listed order is part of it."""
    from concordance.validate import canonical_json_bytes
    return hashlib.sha256(canonical_json_bytes(steps)).hexdigest()


def _refs(step: Dict[str, Any]) -> List[str]:
    refs = [str(u) for u in (step.get("uses") or [])]
    bind = step.get("bind")
    if isinstance(bind, dict):
        refs += [str(ref).partition(".")[0] for ref in bind.values()]
    return refs


def in_scope(steps: Any) -> bool:
    """A listing the tier must account for: 2 or more steps, or one step that uses or binds from itself."""
    if not isinstance(steps, list) or not steps or not all(isinstance(s, dict) for s in steps):
        return False
    if len(steps) >= 2:
        return True
    own = str(steps[0].get("id") or "s0")
    return own in _refs(steps[0])


def _current_test() -> str:
    """The running test's node id (parameters included), or "" outside a test."""
    return os.environ.get("PYTEST_CURRENT_TEST", "").rsplit(" ", 1)[0]


def unaccounted(listings: Dict[str, Dict[str, Any]], sweeps: Dict[str, Any], held: Set[str]) -> List[str]:
    """Every captured listing the tier does not account for, in the JSON form to_json() writes. A listing is
    accounted for when it is held (a row or an exclusion), or when EVERY test that passed it generated it by
    sweeping the permutations of a held base. A listing one test writes and another test generates is therefore
    unaccounted for, and so is one passed outside any test."""
    out = []
    for h, e in listings.items():
        if h in held:
            continue
        swept = {(b, t) for b, t in sweeps.get(h, ())}
        tests = e.get("tests") or []
        if tests and all(any(b in held and t == test for b, t in swept) for test in tests):
            continue
        out.append(h)
    return out


class Capture:
    """What reached verify_derivation: canonical hash -> the listing, the names and paths it came by, and the
    tests it came from; and, per generated permutation, each (base it was generated from, test that generated
    it)."""

    def __init__(self) -> None:
        self.seen: Dict[str, Dict[str, Any]] = {}
        self.sweeps: Dict[str, Set[Tuple[str, str]]] = {}
        self.wrapped: List[str] = []

    def record(self, steps: Any, name: str, caller: str) -> None:
        if not in_scope(steps):
            return
        listed = copy.deepcopy(steps)
        h = listing_hash(listed)
        e = self.seen.setdefault(h, {"steps": listed, "names": set(), "paths": set(), "tests": set()})
        e["names"].add(name)
        e["paths"].add(PATHS.get(caller, "direct"))
        node = _current_test()
        if node:
            e["tests"].add(node)

    def wrap(self, name: str, real: Callable) -> Callable:
        def verify_derivation(steps, *args, **kwargs):
            self.record(steps, name, sys._getframe(1).f_globals.get("__name__", ""))
            return real(steps, *args, **kwargs)
        verify_derivation.__wrapped__ = real
        verify_derivation.__doc__ = real.__doc__
        return verify_derivation

    def install(self, setattr_: Callable = setattr) -> List[str]:
        """Wrap every name in NAMES (each around the definition, so no listing is counted twice). setattr_ is
        monkeypatch.setattr in a test, so pytest undoes it; plain setattr in run()'s own process."""
        mods = [(importlib.import_module(mod), mod, attr) for mod, attr in NAMES]   # every import, then wrap
        from concordance import derivation
        real = derivation.verify_derivation
        for m, mod, attr in mods:
            assert getattr(m, attr) is real, (mod, attr)      # every name holds the definition itself
            setattr_(m, attr, self.wrap(f"{mod}.{attr}", real))
            self.wrapped.append(f"{mod}.{attr}")
        return self.wrapped

    def watch_permutations(self, setattr_: Callable = setattr) -> None:
        real = itertools.permutations
        sweeps = self.sweeps

        def permutations(iterable, r=None):
            items = list(iterable)
            out = real(items) if r is None else real(items, r)
            if not (items and all(isinstance(x, dict) for x in items)):
                return out
            base = listing_hash(items)

            def gen():
                for t in out:
                    sweeps.setdefault(listing_hash(list(t)), set()).add((base, _current_test()))
                    yield t
            return gen()
        setattr_(itertools, "permutations", permutations)

    def to_json(self) -> Dict[str, Any]:
        return {"wrapped": self.wrapped,
                "listings": {h: {"steps": e["steps"], "names": sorted(e["names"]), "paths": sorted(e["paths"]),
                                 "tests": sorted(e["tests"])} for h, e in sorted(self.seen.items())},
                "sweeps": {h: sorted([b, t] for b, t in s) for h, s in sorted(self.sweeps.items())}}


def run(out: str, args: List[str]) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path[:] = [p for p in sys.path if os.path.abspath(p or ".") != here]   # nothing here shadows a module
    cap = Capture()
    cap.install()
    cap.watch_permutations()
    import pytest
    rc = int(pytest.main(list(args)))
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(dict(cap.to_json(), rc=rc), fh)
    return rc


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    out = argv.pop(0)
    if argv and argv[0] == "--":
        argv.pop(0)
    return run(out, argv)


if __name__ == "__main__":
    raise SystemExit(main())
