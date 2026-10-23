# Concordance — product plan

2026-10-22. Built on: the 2026-10-17 code review, the 2026-10-20 scribe prototype, the 2026-10-22 re-review
(core unchanged; `witness` is a 700-line proxy), and two landscape sweeps (`LANDSCAPE_A`, `LANDSCAPE_B`,
~120 sources). Every claim about the market cites one of those files.

## 1. What the market says (the parts that change the plan)

1. **Nothing bundles recompute + verdict + content-addressed receipt.** Each piece exists and is better
   alone: Math-Verify (answer equivalence), Pint (units), precisioncalc-mcp (finance calcs), MedCalc MCP
   (59 clinical calculators), Wolfram MCP (breadth). None return a verdict on a *claim*, none seal.
   (`LANDSCAPE_A` §1, §4.)
2. **Every attestation system attests "a model produced X." None attest "X is true."** C2PA, SynthID,
   Sigstore/Rekor, SCITT, Signet, EigenAI, zkML. Concordance's seal binds a verdict and a worked trail —
   unique in the scan, and only as good as the verifier's coverage. The self-signed private ledger is the
   weak half; Rekor/SCITT inclusion proofs fix it for free. (`LANDSCAPE_B` §B.)
3. **Consensus is nearly worthless without a verifier, and the data is one-sided.** Nine judges ≈ 2.0–2.5
   effective votes; when two models both err they give the same wrong answer 60% of the time; all-wrong
   floor 5–13%; self-agreement ≥ 0.8 still wrong 48% on GPQA. Debate rarely beats self-consistency.
   What disagreement *does* buy is localization — where to spend deterministic checking. (`LANDSCAPE_B`
   §A, §d.) This matches the prototype exactly: spread ≈ 0, verifier still caught 3/180.
4. **The SVD-over-writers×claims + deterministic breaker combination has no direct prior art.** Nearest is
   spectral crowdsourcing (Parisi 2014, Zhang 2014) and per-question PCA in DiscoUQ (2026). Patent search
   warranted before claiming novelty. (`LANDSCAPE_B` §c.)
5. **The strongest objection is real:** "a sandbox with sympy recomputes anything in your 90 verifiers, and
   the packet is still extracted by the LLM you don't trust." Honest answer: the sandbox gives no verdict
   from code the LLM didn't write, no pinned semantics, no re-derivable hash (Anthropic/OpenAI make no
   reproducibility promise). That value is **narrow**: it matters where a third party must audit the number
   (finance sign-off, dosage, engineering), not where a chatbot needs to be roughly right. (`LANDSCAPE_A` §c.)
6. **Rule-based verifiers: >99% precision, ~86% recall, un-gameable; model-based verifiers get gamed**
   (Huang 2025). Structured packets are the right bet and the adoption friction. Expose the extractor.
7. **Distribution is through other people's harnesses, not a site:** Guardrails Hub validators (NeMo picks
   them up), DeepEval/Braintrust autoevals scorers, LangGraph/AutoGen nodes, PrimeIntellect Environments
   Hub (4.7k★, explicitly wants un-hackable rule rewards), MCP registries, the Anthropic connector
   marketplace next to Wolfram. (`LANDSCAPE_A` §b, `LANDSCAPE_B` §b.)

## 2. The product

**One sentence:** *Receipts for numbers.* An AI agent (or a person) submits a number with its inputs; a
deterministic verifier recomputes it; the result is a sealed, re-derivable receipt that a third party can
check without trusting the agent, the model vendor, or us.

**Who pays and why:** anyone who has to sign their name under a number an AI produced. Bond counsel and
development-authority boards (abatement, amortization, DSCR). Pharmacists and clinical informatics
(dose arithmetic). Engineers (unit and formula sign-off). Agent developers selling into those people.
The buyer is the *signer*, the user is the *agent*. Both must be served or neither is.

**What it is not:** a chatbot, a search engine, a Bible app, a fellowship, a coach. Those live on
narrowhighway.org and are not part of this product. The core must contain no vocabulary from them.

### 2a. For agents

- `pip install concordance` — engine, 90+ verifiers, ledger, MCP server, HTTP API. Apache-2.0.
- **8 MCP tools** (`V3_PLAN.md` §1): verify, discern, find_verifier (returns packet JSON schema), seal_fetch,
  audit, scribe, capabilities, ledger_verify.
- **Receipt format = standard envelope, not bespoke:** each seal is a COSE Signed Statement per the SCITT
  agent-receipt draft (draft-noa-scitt-ai-agent-receipt, Aug 2026) with a `concordance.verdict` claim set;
  also emitted as an in-toto Statement signed keylessly and logged to Rekor so the inclusion proof is
  third-party. Map to AgentLedger PoB fields for interchange. (`LANDSCAPE_B` §b 1–2, `LANDSCAPE_A` §b 4.)
- **Harness packages (distribution, not engineering):** `guardrails-ai-concordance` validator;
  `concordance.evals` scorer for DeepEval and autoevals (sits beside `NumericDiff`, but derives the expected
  value instead of needing one); `concordance-langgraph` node; a PrimeIntellect `verifiers` environment
  exposing the benchmark as un-hackable rewards.
- **Scribe** ships as a library (`concordance.scribe`) with a provider-agnostic `Writer` protocol and the
  flat-spectrum rule (underdetermined → INCOMPLETE, never averaged). It is positioned as *triage*: the
  disagreement axis tells the verifier where to look. It is **not** marketed as a truth signal until it has a
  benchmark against self-consistency (§5, M2).

### 2b. For people

- **The receipt page** (`/s/<hash>`) is the whole people-facing product in v1. One page: the claim, the
  inputs, the formula, the recomputed value, PASS/REJECT, the seal, a Rekor inclusion link, and a
  **"re-check" button that recomputes in the browser** with editable inputs (a JS port of the numeric
  evaluator and the ~20 most-used verifiers). A board member who can't read JSON can still move a slider
  from 4.5% to 5.0% and watch the payment change. No login, no vocabulary.
- **Check-It** (`/check`): paste a memo, a resolution, a spreadsheet export, or one sentence. Every
  extractable claim is listed with its tight span, verdict, and receipt; everything *not* checked is shown
  in grey, explicitly. This is the coverage bug turned into the feature: honesty about what wasn't
  checked is the differentiator against every PASS/FAIL model in `LANDSCAPE_A` §3.
- **Packs** are the people-facing SKUs and the first revenue:
  - **Public Finance pack** — amortization with IO periods, issuance gross-up, abatement ladders,
    depreciated-value ad valorem, millage vectors, DSCR/LTV, NPV/IRR with explicit conventions. Ported
    from the prototype's `packets.py`. First customer: NWGA JDA — Matt is the signer. Second: every other
    development authority and bond counsel in Georgia, reachable by one person in one quarter.
  - **Clinical arithmetic pack** — dose × weight, BSA, eGFR, unit conversions, with the red-team caveat
    carried in the receipt headline (already in `medicine.py`). Overlaps MedCalc MCP; the difference is the
    receipt. Sell to informatics, not clinicians, and never imply clinical safety.
  - **Engineering pack** — units/dimensional analysis via Pint, the existing physics/thermo/electrical set.
- **Scribe for memos** — the JDA use case from the prototype: five writers, the verifier as datum, a
  sealed memo whose every number carries a receipt. This is a *workflow* product for one buyer type
  (staff writing board memos). Ship it inside the Public Finance pack, not as a general tool.

### 2c. The bridge between the two

Agents mint receipts; people read them. The receipt page is the contract. Every integration above ends
in a URL a human can open, and every human-facing page ends in a JSON a machine can fetch. One object,
two faces — that part of v2's instinct was right; the mistake was putting the engine *behind* the human
face instead of beside it.

## 3. Business model

Open core, self-funded, debt if needed — no equity (your constraint, and it fits: this is a tools
business with a long slow adoption curve, not a venture-shaped one).

| tier | what | price (starting) |
|---|---|---|
| OSS | engine, verifiers, local ledger, MCP, all harness packages | $0 |
| Hosted API | seals with Rekor inclusion, hosted receipt pages, rate limits | free to 1k seals/mo; $0.002/seal after |
| Packs | public finance / clinical / engineering verifier sets + schemas + goldens | $49–$199/mo per org |
| Workspace | org ledger, retention, SSO, audit export, signed PDF receipts | $500–$2k/mo |
| Services | a pack built for one buyer (a county's own abatement policy, a hospital's own dose rules) | project |

Honest revenue shape: year 1 is packs sold by hand to people you already know (authorities, counsel,
the FQHC board) — tens of customers, not thousands — plus a long tail of hosted-API developers who mostly
stay free. The hosted API is a distribution channel; the packs are the business. If no pack sells by day
90, the engine still serves the JDA and narrowhighway.org and nothing is lost but the hosting bill.

## 4. Brand and surface

- **Engine and product: `Concordance`.** Neutral, already the package name, means "agreement of
  sources," which is what a receipt is. Check PyPI availability first (`V3_PLAN.md` §6).
- **Domain:** a neutral one for the product (`concordance.dev` / `getreceipts.*` — pick after a
  trademark check). `narrowhighway.com` redirects to it for the engine; `narrowhighway.org` keeps the witness.
- **Vocabulary rule, enforced by CI grep:** none of keeping / door / house / witness / steward / covenant /
  cloud / palace / face / register in the product repo, docs, tool descriptions, or receipt pages. The
  re-review found "palace" and "tensor" back in the new repo within a day; this rule is the only thing
  that has worked.
- **README for the agent developer:** one paragraph, one curl, one MCP block, one receipt, the benchmark
  line, the limits (checks arithmetic, not clinical safety). Five minutes to first sealed receipt.

## 5. Roadmap — 90 days, three gates

### M1 (days 0–30): the lean core exists and speaks a standard
- Execute `V3_PLAN.md` P0–P3 in a fresh `concordance-3` repo (NOT a reinterpretation inside
  `concordance-2`; that produced the proxy). Gates: ≤40 modules, 8 tools, coverage bug regression-tested
  gone, packet schemas generated, suite ≤60 s.
- Receipt envelope: SCITT/COSE signed statement + in-toto/Rekor publication. Gate: an outsider verifies
  a seal with `rekor-cli` and no Concordance code.
- Listings: PyPI, MCP registries (Glama, PulseMCP, mcp.so, official servers list), Anthropic connector
  submission, `guardrails-ai-concordance` on the Hub.
- Receipt page v1 with in-browser re-check for `numeric` mode + mortgage/DSCR/LTV.
**Gate M1:** a stranger can `pip install`, mint a receipt, open its page, and re-check it on Rekor, in
under 5 minutes from the README. Measured with one person who has never seen the project.

### M2 (days 31–60): the first pack and the first signer
- Public Finance pack as real verifiers (`V3_PLAN.md` P4) with ≥200-case benchmark v2 and mutation
  testing. Check-It page with grey "not checked" spans.
- **JDA pilot:** one real board memo per meeting goes through Scribe + Check-It; every number on the
  memo carries a receipt URL in a footnote. You are the signer. Record what the board asks.
- Scribe benchmark: replay the two prototype rounds plus 20 new specs with **at least two non-Claude
  writers** (`LANDSCAPE_B` §A correlated-error data makes an all-Claude panel inadmissible). Report
  spread, BROKEN count, and — the test that matters — whether SVD localization beats random order for
  finding the broken claims. Publish the result whatever it says.
- DeepEval + autoevals scorer packages; LangGraph node.
**Gate M2:** one memo sealed and presented to a real board; one external developer has opened an issue
or PR; the scribe benchmark is published with a number, positive or negative.

### M3 (days 61–90): second buyer type and the decision
- Clinical arithmetic pack (informatics buyer; caveats in headline). Engineering pack via Pint.
- Three design-partner conversations outside Georgia: one bond counsel, one agent-platform team, one
  clinical-informatics group. Ask for money, not feedback.
- Patent/prior-art search on the writers×claims spectral triage (`LANDSCAPE_B` §c) — file a provisional
  only if the M2 benchmark showed localization works.
- Hosted tiers live; Workspace as a manual-onboarding beta.
**Gate M3 / kill criteria (decided now):** by day 90, at least one of: a paid pack, ≥50 stars with ≥3
external issues, or a signed design partner. None → maintenance mode: the engine keeps serving the JDA
memos and narrowhighway.org, you stop investing, and the time goes to the next venture. Any → M4
planning (second region, second pack, hire or contract one maintainer).

## 6. Risks, stated plainly

| risk | evidence | mitigation |
|---|---|---|
| Solo maintainer; AI-amplified scope creep | 181 modules, 45 docs, "palace" within a day | CI vocabulary gate; no module without a benchmark case; the 90-day kill criterion |
| Free-text extraction recall (~86%) → "it bounced my sentence" | Huang 2025; own probes (dosage, mortgage missed) | Packets first; `SCHEMA_ERROR` names the field; Check-It shows grey spans instead of silence |
| "Just run Python" | Anthropic/OpenAI sandboxes, sympy, Pint | Sell the receipt and the third-party proof, not the arithmetic; only to buyers who must sign |
| Incumbent calculators own the surface | precisioncalc-mcp, MedCalc MCP, Wolfram | Wrap, don't rebuild: Math-Verify + Pint as backends; offer the receipt layer *over* their outputs |
| Scribe is unproven vs. self-consistency | Smit 2024, Zhang 2025 | M2 benchmark with non-Claude writers, published either way; market as triage until then |
| Brand carries the witness vocabulary into a secular market | site review 2026-10-17; `V3_BOUNDARY.md` | Neutral product name/domain; .org keeps the witness whole |
| Self-attested ledger is weaker than it sounds | `LANDSCAPE_B` §B | Rekor/SCITT inclusion from M1 |
| The core doesn't actually shrink (again) | 2026-10-22 re-review | Fresh repo; the plan's gates are commands; no "reinterpretation" commits |

## 7. What to do this week

1. Decide §4 name/domain and §3 pricing in one sitting; don't revisit for 90 days.
2. `git init concordance-3`; run `V3_PLAN.md` P0 (freeze, measure, closure script). Half a day.
3. Write the five-minute README before any code moves — it is the spec for M1.
4. Pick the first real JDA memo for the M2 pilot and list its numbers; that list is the Public Finance
   pack's acceptance test.
