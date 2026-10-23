# Concordance v3 — the plan

Written 2026-10-20 for Claude Code. Source of truth is the v2 repo at HEAD `fix(graph): declare rests_on -> supports` (#47).
Every count below was measured on that commit; re-derive before trusting.

## 0. The decision

v3 is **one product for one user**: a deterministic verification engine that AI agents call to check numbers
and get a re-verifiable receipt. It ships as a Python package (`concordance`), an MCP server, and an HTTP API.

Everything that is not that — Scripture, the Console, the parable register, the Reading Room, the mesh,
identity/covenant, coach/decks/badges, the collective-intelligence layer, the alignment gate, the corpus and
its 880k cards — **stays in the v2 repo, which becomes the narrowhighway.org codebase** and depends on v3 as a
pip dependency. Nothing is deleted from the world; it is moved out of the core's blast radius.

Measured reasons (from the 2026-10-17 review and the 2026-10-20 scribe prototype):
- Suite 2,914 passed / 0 failed; benchmark 60/60, 0 FP. The engineering is sound. Keep it.
- The core path (`verify` with `steps`) worked on every structured packet thrown at it. The plain-text path
  (`verify {claim}`) bounced ordinary sentences ("70 kg at 5 mg/kg = 350 mg" → INCOMPLETE). Packets first.
- Scribe prototype: 5 writers × 2 rounds × 12 claims; consensus spread ≈ 0; the recompute verifier still
  caught 3/180 wrong claims consensus could not see. The verifier is the product. The convergence loop is a
  feature of it, not the other way round.
- Coverage bug: `verify` returned `coverage.complete: true, unchecked_text: []` on a sentence with an
  unchecked falsehood in it (boiling point) because the extractor claimed the whole compound sentence as one
  claim span. In a product whose pitch is honest receipts this is the one bug that matters.
- Routing is a phrase index over module docstrings (`domain_resolver.py`). It will never carry an
  "ask anything" surface. In v3 it is a hint, never the decider.
- 0 stars / 0 forks after 9 months and 438 commits; the site speaks a private vocabulary. v3 README is
  written for an agent developer and contains no words that need a glossary.

## 1. What v3 is

**User:** a developer building an agent that emits numbers (finance, engineering, dosage, statistics,
unit conversion) in a context where "the model said so" is not good enough.

**Promise:** send a packet, get `(verdict, trail, seal)`. The verdict is computed, not generated. The seal
is content-addressed and re-fetchable. The ledger is append-only. Anyone can recompute.

**MCP surface — 8 tools, down from 105:**

| tool | role |
|---|---|
| `verify` | packets in (`steps=[{id, domain, spec}]`), verdict+trail+seal out. Plain `claim` text still accepted; result is labelled `extracted: true` and never `coverage.complete` unless every material fragment was checked. |
| `discern` | plain text → proposed packets, no verdict. The de-identifying airlock runs here. |
| `find_verifier` | keyword → domain, check names, **and the JSON schema of the packet** (generated, not hand-written). |
| `seal_fetch` | hash → the sealed record. |
| `audit` | a document → every extractable claim, each verified, with explicit per-fragment coverage. |
| `scribe` | the convergence loop (§5): N drafts in, claim matrix + SVD spectrum + per-writer verdicts + feedback out. |
| `capabilities` | live counts and limits, all derived at call time. |
| `ledger_verify` | re-walk the hash chain; returns the first break or OK. |

Everything else in `tool_registry.py` moves to org (it registers its own tools on top of these eight).

**Non-goals for v3.0:** natural-language Q&A, retrieval/search over a corpus, any religious or
witness surface, identity/mesh, coaching, voice, the site beyond one landing page + API docs.

## 2. Repo strategy

- New repo `concordance-3` (clean history; v2 tagged `v2-final` and kept). Python package name stays
  `concordance`, version `3.0.0`.
- v2 repo is renamed in README to "narrowhighway.org" and, in its final phase (§4 P6), replaces its copies
  of core modules with `from concordance import ...` against the published package.
- Core vs org is decided **mechanically**: core = the import closure of the 8 MCP entrypoints after the
  overrides in §3 are applied. Compute it (`python -X importtime` or a small AST walker over `src/`),
  commit the list as `CORE_MODULES.txt`, and gate CI on "no module outside this list is imported by core."

## 3. Module disposition

Measured: 181 top-level modules, 51,666 lines in `src/concordance/*.py`; 93 verifier modules, 27,780 lines
in `verifiers/`. Expected v3 core after the carve: ~35 modules, ~18–20k lines including verifiers.

### 3a. Force-IN (core, regardless of closure)

```
verifiers/ (secular set — see 3c)      derivation.py      receipts.py       ledger.py
cas.py          validate.py      packet.py        record.py          redact.py         airlock.py
audit.py (slimmed, see P2)       discern.py       domain_resolver.py (hint only)        router.py
engine.py + config.py (single surface; drop the secular/witness switch)   capabilities.py
tool_registry.py (8 entries)     mcp/server.py    mcp/http.py        serve.py          __main__.py
ratelimit.py    guard.py         filelock.py      telemetry.py       seals.py          unchecked.py
slotfill.py     signing.py (receipt signing only)
NEW: scribe/ (orchestrate.py, packets.py, svd.py, feedback.py — ported from the 2026-10-20 prototype)
```

### 3b. Force-OUT (org), even if the closure pulls them in — sever the edge instead

| module | why it leaks into core today | what to do |
|---|---|---|
| `grid.py` (784) | `ledger.py` imports `grid` for `axis_coords_for` | ledger records carry an optional opaque `coords` dict supplied by the caller; org computes them. |
| `corpus.py` (2254), `corpus_db.py`, `corpus_cache.py`, `shelves.py`, `find.py` | `audit.py`/`verify` fall back to "found" cards when nothing verifies | core returns INCOMPLETE with `gap_at`; org wraps `verify` and adds the retrieval fallback. |
| `ask.py` (2368), `console.py`, `parable.py`, `crisis_semantic.py`, `doors.py` | the WALK surface | org. Crisis routing stays in org's `ask`; core has no human-facing text path. |
| `mesh.py`, `meshtastic_bridge.py`, `identity.py`, `covenant.py`, `consent.py`, `groups.py`, `wants.py`, `seekers.py`, `moderation.py`, `receiver.py`, `push.py` | KEEP door / fellowship | org. |
| `coach.py`, `decks.py`, `badges.py`, `attest.py`, `professions.py`, `playbook.py`, `study_index.py` | coaching / credentials | org (candidate for a separate product later; not v3's problem). |
| `stigmergy.py`, `quorum.py`, `flock.py`, `eldership.py`, `physiology.py`, `inhibition.py`, `alignment.py`, `kernel.py`, `layers.py`, `formation.py` | collective-intelligence + alignment gate | org. No test in core may reference them. |
| `timeline.py`, `harmony.py`, `teachings.py`, `canon.py`, `commentary.py`, `xrefs.py`, `bible_places.py`, `characters.py`, `prophecy*.py`, `pronounce.py`, `roots.py`, `translate.py`, `isbe.py`, `witness.py`, `foundation.py`, `disciple.py`, `mentors.py`, `faces.py`, `narratives.py`, `archetypes.py`, `lens.py`, `codex.py`, `backmatter.py` | WORD door / witness content | org. |
| `voice.py`, `tv.py`, `branding.py`, `plow.py`, `workshop.py`, `craft.py`, `manufacture.py`, `tortoise.py`, `tickstick.py`, `bookofdays.py`, `days.py`, `almanac.py`, `pins.py`, `readwith.py`, `linkdrop.py`, `cabinet.py`, `stacks.py`, `present.py`, `papers.py`, `science_cards.py`, `theories`-adjacent | site features / registers | org. |
| `lighthouse_node.py`, `node_roles.py`, `steward.py`, `lead.py`, `inlet.py`, `wayfind.py`, `path.py`, `trajectory.py`, `growth.py`, `training.py`, `engagement.py`, `community.py`, `profile.py` | node / steward / training loop | org. |
| `candidates.py` (764), `recombine.py`, `expand.py`, `replicate.py`, `distill.py`, `clarify.py`, `factfind.py`, `compendium.py` | proposal/expansion machinery | **triage**: read each; anything the `scribe` module needs is ported into `scribe/`, the rest is org. Do not import them wholesale. |
| `chess.py` (root), `chains.py`, `compute.py`, `constraints.py`, `components.py`, `systems.py`, `graph.py`, `compare.py`, `semantic.py`, `syntax.py`, `context.py`, `connect*.py`, `sources.py`, `assay.py`, `byom.py`, `providers.py`, `ops.py`, `threads.py`, `recall.py`, `address.py`, `binding.py`, `branch.py`, `principles.py`, `field_canon.py`, `warrant.py`, `repellent.py`, `frozen_cache.py`, `pdf_extract.py`, `recurring_form.py`, `seeds.py`, `floor.py`, `dates.py`, `dictionary.py`, `thesaurus.py`, `lookup.py`, `automaton.py`, `ncs_falsification.py`, `apothecary.py`, `sticks.py`, `gates.py`, `gateway.py`, `capabilities`-adjacent | unknown until read | **triage by closure**: in core only if the closure pulls them in AND the pulled-in function is < 50 lines (then inline it into the caller); otherwise org. Record each decision in `CORE_MODULES.txt` with one line of reason. |

### 3c. Verifiers

Keep every secular verifier (`acoustics … thermodynamics`, 89 modules). Move `scripture.py`,
`theology_doctrine.py`, `witness.py`, `wordcraft.py` to org as `concordance_org.verifiers.*`; org registers
them with core's dispatcher via an entry point (`concordance.verifiers` group in `pyproject.toml`), so the
engine is extensible without forking. Core's `_rs.c` stays only if a core verifier uses it.

### 3d. tools/, site/, data/, docs/, deploy/

- `tools/`: core keeps `benchmark.py`, `benchmarks.py`, `check.py`, `calibrate.py`, `domain_goldens.py`,
  `spec_verifier.py`, `verify_seal.py`, `integrity_check.py`, `dispatch_probe.py`, `routing_diff.py`,
  `live_assay.py`, `verify_deploy.py`, `quickstart.sh`, `deploy.sh`. All `seed_*`, `card_*`, `migrate_*`,
  `build_*`, `gather_*`, `hive_*`, `train_*`, `tick*`, `torus*`, `vortex*`, `shepherd*`, `ark*`,
  `export_zim.py` → org.
- `site/`: core ships **two pages**: `index.html` (what it is, one curl, one MCP config block, the receipt
  format) and `api.html` (generated from the packet schemas). Every other page → org.
- `data/`: core keeps only what a core verifier or the benchmark reads (`domain_goldens.json`,
  `elliptic_curves.jsonl`, physical-constant tables). Cards, spines, crisis, dictionary → org.
- `docs/`: core keeps **five files**: `README.md`, `ARCHITECTURE.md` (regenerated, counts derived),
  `BENCHMARK.md`, `SEAL_SPEC.md`, `RUNBOOK.md`. Also `CHANGELOG.md`. The other ~40 → `org/docs/` or
  `archive/`. No new doc may be added to core without a linked issue naming the reader.
- `deploy/`: core keeps `nh-engine.service`, `nh-mcp.service`, `nh-benchmarks.*`, the Caddyfile stanza for
  the API host, `mcp-registry/`. The rest → org.

## 4. Phases

Each phase is one Claude Code session or less, ends with a green CI and a tagged commit, and has an
acceptance gate that is a command, not a sentence. Do not start P(n+1) with P(n)'s gate red.

### P0 — freeze and measure (½ day)
1. Tag v2 `v2-final`. Record in `MEASURED_V2.md`: module count, line count, verifier count, test count,
   suite wall time (97 s on 2026-10-20), benchmark result, MCP tool count (105).
2. Write the AST import-closure script `tools/closure.py <entrypoint-modules...>` → sorted module list.
   Run it on the 8 entrypoints. Commit the raw output as `CLOSURE_V2.txt` (expect it to be large — that is
   the finding).
**Gate:** `python tools/closure.py` runs and its output is committed.

### P1 — carve the core (1–2 days)
1. Create `concordance-3`. Copy force-IN modules + secular verifiers + their tests.
2. Apply the force-OUT severances in §3b (ledger↔grid, audit↔corpus, engine surface switch).
3. Iterate: run closure; for every module outside force-IN that the closure pulls, either inline (< 50
   lines) or sever; record in `CORE_MODULES.txt`.
4. Copy only the tests whose imports resolve in core. Expect ~1,400–1,800 of the 2,914.
**Gate:** `PYTHONPATH=src pytest -q` green; `python tools/benchmark.py --json` → 60/60, 0 FP;
`python tools/closure.py` ⊆ `CORE_MODULES.txt`; `wc -l src/concordance/*.py` ≤ 22,000 (verifiers excluded).

### P2 — the two defects (1 day)
1. **Coverage.** Reproduce: `verify {claim: "Water boils at 90 degrees Celsius at sea level, and the kinetic
   energy of a 2 kg object moving at 3 m/s is 12 joules."}` must return `coverage.complete: false` with the
   boiling-point clause in `unchecked_text`. Fix in `audit.py`: extractors return the **tight span** of the
   fragment they matched (not the sentence), compound sentences are split on coordinating conjunctions and
   semicolons before extraction, and `complete` is computed over material fragments outside every matched
   span. Add the sentence as a regression test and 10 more compound sentences with one checkable and one
   unchecked clause each.
2. **Packet-first.** `find_verifier` returns the JSON schema for each check (generated from the `_RULES`
   predicates and the `spec.get(...)` keys in each verifier — write `tools/schema_gen.py`). `verify`
   validates `steps` against the schema and returns `SCHEMA_ERROR` with the field list instead of
   `NOT_APPLICABLE` when a packet is malformed (today a misnamed field silently yields NOT_APPLICABLE; the
   prototype hit this with `principal` vs `loan_principal`).
3. Plain `claim` results carry `extracted: true` and the extractor's span for every check.
**Gate:** the regression tests pass; `python tools/schema_gen.py --check` reports every verifier has a
schema; a malformed packet returns `SCHEMA_ERROR` naming the missing field.

### P3 — MCP surface to 8 tools (½ day)
1. `tool_registry.py` lists exactly the 8 tools in §1. Delete the rest from core.
2. `capabilities` reports tool count, verifier count, domain count, benchmark version, all derived.
3. Server instructions text rewritten: no house metaphor, no doors, no vocabulary that needs a glossary.
   Under 120 words.
**Gate:** `python -m concordance mcp --list-tools | wc -l` → 8; a cold MCP client can call `find_verifier`
→ `verify` → `seal_fetch` end to end on a mortgage packet.

### P4 — stage-one verifiers and a benchmark that covers them (2 days)
Port from the prototype's `packets.py` as real verifiers with tests and goldens:
- `finance.amortization` — level P&I, optional interest-only prefix, total interest, per-period schedule
  hash. (`real_estate.monthly_mortgage` becomes an alias.)
- `finance.npv` / `finance.irr` — verify `npv` handles end-of-year convention explicitly; add IRR.
- `finance.dscr`, `finance.ltv` (aliases to real_estate, re-homed).
- `public_finance.abatement_schedule` — start share, step, floor, years; returns per-year abated/paid.
- `public_finance.depreciated_value` — straight-line % of original with floor.
- `public_finance.ad_valorem` — value × assessment ratio × millage/1000, with per-year millage vector.
- `public_finance.issuance_grossup` — par from net proceeds, cost %, round-up increment.
Benchmark v2.0.0: ≥ 200 labelled cases, every core domain represented, FP and FN reported separately,
mutation check (`tools/mutate.py` flips one operator in one verifier; the gate must go red).
**Gate:** `benchmark.py --json` → 0 FP on v2.0.0; `tools/mutate.py --sample 20` → 20/20 detected.

### P5 — `scribe` as a first-class module (2 days)
Port `/home/claude/scribe2/{orchestrate,packets}.py` into `src/concordance/scribe/`:
- `Writer` protocol: `write(spec, feedback) -> {draft, claims:[{id, value, inputs, formula}]}`. Core ships
  no LLM client; a writer is anything that satisfies the protocol (the demo uses subprocess/HTTP stubs).
- `claim_matrix(drafts) -> (M, ids)`; `spectrum(M) -> {singular_values, top_axis, share, spread}`;
  `verify_matrix(M, packets) -> verdicts`; `feedback(report, writer) -> str` (engine verdicts + divergence
  values; never truth, never another writer's draft); `center(report) -> writer_id` (nearest clean draft).
- Context strip/reapply: placeholders map held by the caller; core never sees names.
- Flat-spectrum rule: if `share < 0.5` and `spread > tol`, return `INCOMPLETE: underdetermined` — do not
  average.
- One ledger entry per pass; the final seal references the pass hashes.
- MCP tool `scribe` exposes `score_pass` and `final`.
**Gate:** the two prototype rounds replay from their stored `agent*.json` and reproduce the recorded
reports byte-for-byte (modulo timestamps); a planted wrong value in one draft is BROKEN and that draft is
never chosen as center.

### P6 — org depends on core (1 day, in the v2 repo)
1. `pip install concordance==3.0.0rc1` (local index is fine). Delete org's copies of every module in
   `CORE_MODULES.txt`; replace imports.
2. Org registers its 4 witness verifiers and its extra MCP tools via the entry points.
3. Org's `verify` wrapper adds the retrieval fallback and crisis routing on top of core's result.
**Gate:** org suite green; `narrowhighway.org` MCP still lists its full tool set; core's CI has no org
module in its closure.

### P7 — docs and the front door (½ day)
1. README for the agent developer: 1 paragraph, 1 curl, 1 MCP config block, the receipt JSON, the
   benchmark line, the limits ("checks arithmetic, not clinical safety" etc. — keep the red-team caveats).
2. `ARCHITECTURE.md` regenerated by a script from `CORE_MODULES.txt`, the schema list and the benchmark.
3. Delete or move every other doc. `docs/` in core has ≤ 6 files.
**Gate:** `ls docs | wc -l` ≤ 6; README contains none of: keeping, door, witness, house, steward, covenant.

### P8 — release and the 60-day test (½ day + waiting)
1. PyPI `concordance 3.0.0`; MCP registry listing; GitHub release with the benchmark JSON attached.
2. Post once in two places where agent developers are (not a launch; a "here is a tool, here is the receipt").
3. Measure on day 60: installs, stars, issues from strangers, any paying use.
**Kill criterion (decide now, not then):** fewer than 25 stars AND zero external issues AND zero paid use at
day 60 → stop investing in v3 core beyond maintenance; the verifier set still serves the JDA memo tool and
the org site, so nothing is wasted. Above that → P9 planning.

## 5. Rules for Claude Code while executing

- No new verifier without benchmark cases and goldens in the same PR.
- No prose vocabulary from the org in core code, comments, tool descriptions or docs (keeping, door, house,
  witness, steward, covenant, cloud). CI greps for it.
- Every count in any doc is produced by a script and carries the command that produced it.
- stdlib-first stays. `sympy`/`numpy`/`scipy` remain optional and lazy; `scribe` needs `numpy` and says so.
- Suite wall time ≤ 60 s in core. Mark anything slower and move it to a nightly job.
- Commit per phase step, message starts with the phase (`P2.1 coverage: tight spans`).
- When a triage decision is unclear, choose **org**. Core can import later; org cannot shrink core later.
- Do not add a surface, register, face, role, layer or door. If the word appears in a diff, stop.

## 6. Open decisions (Matt)

1. Package name: keep `concordance` on PyPI, or namespace it (`nh-concordance`)? Check availability first.
2. License for core vs org: core should be permissive (MIT/Apache-2) if the goal is adoption; org can stay
   as-is with LICENSE-CONTENT. Confirm.
3. Does `public_finance` ship in 3.0 or 3.1? It is the JDA use case and the first real user; recommendation
   is 3.0 (P4 as written).
4. Hosting: the API host for v3 — same box as org, or separate? Recommendation: separate systemd units,
   same box, until load says otherwise.

## 7. What "best version" means, measurably

| metric | v2 (2026-10-20) | v3 target |
|---|---|---|
| core modules | 181 | ≤ 40 |
| core lines (excl. verifiers) | 51,666 | ≤ 22,000 |
| MCP tools | 105 | 8 |
| docs files | 45 | ≤ 6 |
| benchmark cases | 60 (3 modes) | ≥ 200 (every domain) |
| false positives | 0 | 0 |
| plain-claim layups routed | miss (dosage, mortgage) | hit, or SCHEMA_ERROR naming the fix |
| coverage lie | present | regression-tested gone |
| suite wall time | 97 s | ≤ 60 s |
| time from `pip install` to first sealed receipt | n/a | < 5 minutes, from README alone |
