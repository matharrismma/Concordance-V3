"""The public contract, pinned — the semver tripwire (docs/VERSIONING.md).

Concordance versions three surfaces together: the Python library (concordance.__version__), the
MCP tool set, and the receipt format (concordance-receipt/<version>). This test states each one so
a change cannot land silently: renaming, removing, or adding a tool, changing the receipt spec id,
or bumping the library version forces an edit here — which is the moment to choose the version bump
and write the CHANGELOG entry. It is a cheap, deterministic gate, not a behaviour test.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import concordance  # noqa: E402
from concordance import transparency  # noqa: E402
from concordance.mcp.server import list_tools  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# The agent surface. Order is not contractual; the SET is. Changing it is a breaking change.
PUBLIC_TOOLS = frozenset({
    "verify", "discern", "find_verifier", "seal_fetch",
    "audit", "scribe", "capabilities", "ledger_verify",
})


def test_mcp_tool_set_is_exactly_the_published_set():
    names = {t["name"] for t in list_tools()}
    assert names == PUBLIC_TOOLS, (
        "the MCP tool set changed — a breaking change to the agent surface. Bump the version "
        "(docs/VERSIONING.md), add a CHANGELOG entry, then update PUBLIC_TOOLS here.")


def test_every_tool_declares_an_input_schema():
    for t in list_tools():
        assert t.get("name") and isinstance(t.get("inputSchema"), dict), t.get("name")


def test_receipt_spec_version_is_pinned():
    # The receipt format is its own versioned contract; verify_receipt.py and the golden pin its shape.
    assert transparency.SPEC_VERSION == "concordance-receipt/3.1"


def test_library_version_is_semver_and_has_a_changelog_entry():
    v = concordance.__version__
    assert re.match(r"^\d+\.\d+\.\d+([ab]\d+)?$", v), f"not a semver: {v!r}"
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert v in changelog, f"version {v} has no CHANGELOG.md entry — changelog discipline"


def test_public_library_exports_are_stable():
    assert set(concordance.__all__) >= {"EngineConfig", "SURFACES", "__version__"}
