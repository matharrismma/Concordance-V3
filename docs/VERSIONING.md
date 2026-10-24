# Versioning and deprecation

Concordance is meant to be built on, so what it promises has to be stable and its breaks have to
be loud. Three surfaces carry a version, and they move together under [semver](https://semver.org):

1. **The Python library** — `concordance.__version__`, the `pip install concordance` package. The
   importable API: `EngineConfig`, `SURFACES`, and the modules the eight tools reach.
2. **The tool set** — the eight MCP tools (`verify`, `discern`, `find_verifier`, `seal_fetch`,
   `audit`, `scribe`, `capabilities`, `ledger_verify`) and their input schemas. This is the agent
   surface; `server.json` and the MCP registry entry track the same version.
3. **The receipt format** — `concordance-receipt/<MAJOR>.<MINOR>`, carried in the attestation's
   `spec` field (see `RECEIPT_SPEC.md`). It is versioned on its own so a consumer knows which rules
   apply, and a record's `content_hash` is independent of it.

## What a change means

| change | library / tool surface | receipt format |
|---|---|---|
| **major** | remove or rename a tool; remove a public symbol; change a schema so an old call stops validating | change the envelope or attestation shape so an existing verifier stops reading a receipt |
| **minor** | add a tool, a field, or a public symbol, backward-compatibly | add a field or an attestation form a current verifier ignores (the CWT claims and the in-toto form were such additions) |
| **patch** | a fix with no surface change | a documentation or wording fix with no shape change |

A verdict's meaning (`HOLDS` / `BROKEN` / `INCOMPLETE`), a verifier's tolerance, and the
content-addressing rule are part of the major contract: they do not change without a major bump.
Adding or widening a verifier's recall is a minor change — it lets more claims be checked but never
re-labels one that already was.

## Deprecation

Nothing in the list above is removed without first being deprecated for one minor release:

- A tool or field kept working, marked deprecated in its description and in the CHANGELOG, with the
  replacement named. Removal lands only on the next major.
- A receipt-format change that would break a reader is a new MAJOR of the format; the old format
  keeps validating under its own version id, and `verify_receipt.py` reads both.
- A key is rotated, never retired: old receipts stay valid under the public key carried in each
  envelope. `kid` only says which key to pin.

## How it is enforced

- `tests/test_public_api.py` pins the tool set, the receipt spec id, the semver shape of
  `__version__`, and the public exports. A change to any of them fails the test — the moment to
  decide the bump and write the entry. It also fails if the current version has no `CHANGELOG.md`
  entry.
- `CHANGELOG.md` keeps an `Unreleased` section; a release moves it under the new version and date.
  The library version, `server.json`, and the git tag `v<version>` move together (RUNBOOK.md,
  "Publishing and listings").
- The schemas are generated and checked in CI (`tools/schema_gen.py --check`), so a schema drifts
  from its generator only on purpose.

An alpha (`3.0.0a0`) is pre-stable: the surface may still move between alphas, but each move is
still recorded here and in the CHANGELOG. The promises above become firm at `3.0.0`.
