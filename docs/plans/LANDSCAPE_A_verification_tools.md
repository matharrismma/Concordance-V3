# Concordance — Competitive & Adjacent Landscape (Oct 2026)

**Framing.** Concordance = (1) deterministic domain recompute of a *structured* numeric claim, (2) PASS/REJECT with worked trail, (3) SHA-256 content-addressed append-only receipt, (4) MCP/HTTP surface, (5) an SVD-driven multi-writer disagreement loop. Nothing found bundles all five. Each piece individually exists, usually more mature. The honest competitive picture is "assembled from parts" vs. "integrated by one author."

## 1. Deterministic / symbolic verification of LLM outputs

| Project | What | Maturity | Has that Concordance lacks | Concordance has that it lacks |
|---|---|---|---|---|
| [Math-Verify](https://github.com/huggingface/Math-Verify) (HF) | Parses LaTeX/expr answers → SymPy, staged equivalence check vs. a **gold answer** | 1.2k★, Apache-2.0, no tagged releases | Robust answer extraction from free text; sets/intervals/matrices | Recompute from inputs (M-V needs a gold); receipts; non-math domains |
| [Wolfram MCP Service](https://www.wolfram.com/artificial-intelligence/mcp-service/) / [Claude connector](https://claude.com/marketplace/connectors/wolfram) | Wolfram Engine + Alpha knowledgebase as MCP tools; "computed results, not hallucinations" | Commercial, API keys dropped | Breadth (all of Wolfram); curated data | Deterministic PASS/REJECT verdict on a *claim*; receipts; offline; trail of the check |
| [sympy-mcp](https://mcpservers.org/en/servers/sdiehl/sympy-mcp) (S. Diehl) | 31 SymPy tools incl. unit conversion, ODE/PDE, tensors | Apache-2.0, 2025 | Symbolic solving | Computes only; no verify/ledger |
| [PrimeIntellect verifiers](https://github.com/PrimeIntellect-ai/verifiers) | RL environments with rubric/reward functions (uses Math-Verify-style parsers) | 4.7k★, MIT, very active | Training-time integration, Environments Hub | Inference-time service, receipts |
| [Neuro-symbolic PRM](https://arxiv.org/pdf/2608.26329) (2026) | Deterministic verifier: re-executes each step (rtol 1e-5) + **Pint dimensional analysis** + schema check, paired with a PRM | Paper, no code | Step-level process scoring, dimensional checks | Shipped product; receipts |
| [Lean bridges](https://neurips.cc/virtual/2025/131063): Kimina Lean Server, [lean-lsp-mcp](https://mcpservers.org/en/servers/oOo0oOo/lean-lsp-mcp), [DeepSeek-Prover-V2](https://infoq.com/news/2025/05/deepseek-prover-v2-formal-proof) | Formal proof checking at scale / Lean as MCP | Active research + OSS | Real proofs, not arithmetic | Zero formalization burden; numeric domains |
| Z3 route: [ProofOfThought](https://www.sourcepulse.org/projects/16231527) (377★, inactive), [AxiomGuard](https://pypi.org/project/axiomguard/) (v0.7.2, Apr 2026, 1 maintainer), [VERGE](https://www.alphaxiv.org/abs/2601.20055) (2026 paper) | LLM extracts claims → SMT checks consistency vs. rules | Small/solo or paper-only | Logical consistency over rule sets | Numeric recompute; receipts. AxiomGuard is the closest *spirit* ("deterministic neuro-symbolic guardrail"), also solo-built |
| [PAL](https://arxiv.org/pdf/2211.10435) / [CRITIC](https://arxiv.org/pdf/2305.11738) | The pattern: LLM writes program / calls tool to check itself | Canonical 2022–23 papers | Established prior art for "tool-interactive critique" | They are patterns, not services; no ledger |

Key evidence for the deterministic bet: [Huang et al. 2025](https://arxiv.org/pdf/2505.22203) find rule-based verifiers >99% precision, un-hackable under RL, but ~86% recall (format drift); model-based verifiers get gamed (training collapse at iter ~450). Concordance's structured-packet input sidesteps the recall problem by refusing free text — that is a real design choice, and also its adoption friction.

## 2. Guardrail / output-validation frameworks

| Project | Recomputes facts? | Notes |
|---|---|---|
| [Guardrails AI](https://github.com/guardrails-ai/guardrails) + Hub | **No** for numerics. Validators return Pass/FailResult; [provenance_llm](https://guardrailsai.com/hub/validator/guardrails/provenance_llm)/embeddings are LLM/embedding-based | $7.5M seed (Feb 2024, [DBTA](https://www.dbta.com/Editorial/News-Flashes/Guardrails-AI-Promises-to-Stop-%e2%80%98Hallucinations-Plaguing-LLMs-with-75M-in-Seed-Funding-162682.aspx)); validators ship as PyPI `guardrails-ai-<name>` ([docs](https://guardrailsai.com/guardrails/docs/concepts/validators.md)) |
| [NeMo Guardrails](https://docs.nvidia.com/nemo/guardrails/latest/configure-guardrails/guardrail-catalog/third-party/guardrails-ai) | No — Colang policy flows, self-check/fact-check rails are LLM calls; wraps Guardrails AI validators | NVIDIA-backed |
| Instructor / Pydantic | Shape + custom `field_validator` (you can put arithmetic in one) — no domain library | Widely used ([comparison](https://dev.to/thedailyagent/top-5-structured-output-libraries-for-llms-in-2026-48g0)) |
| Outlines / LMQL | Constrained decoding: grammar/shape only | — |
| [Lakera Guard](https://www.checkpoint.com/press-releases/check-point-acquires-lakera-to-deliver-end-to-end-ai-security-for-enterprises/) | Security (prompt injection), not correctness | Acquired by Check Point, Sept 2025 |
| Rebuff / LLM Guard | Injection/PII — not correctness ([comparison](https://is4.ai/blog/our-blog-1/rebuff-vs-llm-guard-comparison-2026-389)) | — |

Verdict: none recompute. All are validation *harnesses* Concordance can plug into.

## 3. Hallucination detection / fact-checking

| Project | Method | Maturity | vs. Concordance |
|---|---|---|---|
| [Cleanlab TLM](https://cleanlab.ai/blog/rag-evaluation-models/) | Self-reflection + sampled consistency + token probs; best AUROC in Cleanlab's own 6-dataset study | Commercial | Probabilistic score, any domain. No proof, no recompute |
| [Patronus Lynx](https://docs.patronus.ai/docs/research_and_differentiators/benchmarking) | Fine-tuned Llama-3 70B, PASS/FAIL + CoT | [$50M Series B, Jun 2026](https://raising.fi/news/patronus-ai-series-b-june-2026); pivoting to agent simulation | Same output shape (PASS/FAIL) but model-generated, not deterministic |
| [Vectara HHEM-2.1](https://www.vectara.com/blog/hhem-2-1-a-better-hallucination-detection-model/) | Small fine-tuned classifier, premise/hypothesis | [2M+ HF downloads](https://www.vectara.com/blog/celebrating-2-million-downloads-of-hhem) | Faithfulness-to-context, not truth; cheap |
| [Galileo Luna](https://galileo.ai/blog/galileo-luna-breakthrough-in-llm-evaluation-beating-gpt-3-5-and-ragas) | DeBERTa eval foundation model | Commercial platform | Same gap |
| [DeepEval](https://github.com/confident-ai/deepeval) | 17.5k★, Apache-2.0, custom metrics supported | Eval harness, mostly LLM-as-judge | Harness, not verifier |
| Ragas / [Braintrust autoevals](https://braintrust.dev/docs/autoevals) | autoevals has deterministic `NumericDiff`, `ExactMatch`, `JSONDiff` + custom scorer fn | Active | Needs an *expected* value; Concordance derives it |
| [Tool-MAD](https://arxiv.org/html/2601.04742v1) (2026) | Two debaters w/ different tools + judge; RAGAS stability scores | Paper | Nearest analog to the scribe loop, but resolution is an LLM judge, not a deterministic breaker; no SVD |
| [MAD survey](https://proceedings.mlr.press/v235/smit24a.html) | Multi-agent debate often ≤ self-consistency | — | Prior art the scribe loop must beat |

All grade *text against context or priors*. None recompute a number from inputs. That is the gap and also the scope limit.

## 4. MCP servers in the calculation / verification / attestation lane

- [Reexpress MCP](https://github.com/ReexpressAI/reexpress_mcp_server) — "statistical verification" via SDM estimator over GPT-4/o4-mini/embeddings; 9★, Apache-2.0, Mac-only. Closest *positioning* ("verify LLM output via MCP"), opposite method (probabilistic, model-dependent).
- [MedCalc MCP](https://glama.ai/mcp/servers/vitaldb/medcalc) (vitaldb) — 59 clinical calculators (eGFR, MELD 3.0, SOFA…), MIT, inactive. Direct overlap with Concordance's medicine verifiers; no verdict/ledger.
- [precisioncalc-mcp](https://socket.dev/npm/package/precisioncalc-mcp) — Decimal-exact NPV/IRR/amortization/depreciation/SaaS metrics, returns formula+inputs envelope; v2.1.1, 37 weekly downloads, paid hosted tiers. Direct overlap with finance verifiers; no claim-checking, no ledger.
- [mcp-units](https://glama.ai/mcp/servers/quantumleeps/mcp-units), [mcp_calculator](https://glama.ai/mcp/servers/mAd-DaWg/mcp_calculator/tools/convert_unit), [math-mcp](https://pkg.go.dev/github.com/matthewjhunter/math-mcp) — commodity unit/arithmetic servers, dozens exist.
- [fact-checker-mcp](https://glama.ai/mcp/servers/devshark/fact-checker-mcp) — Wikidata lookup, capital cities only, inactive. Category is thin and toy-grade.
- [lean-lsp-mcp](https://mcpservers.org/en/servers/oOo0oOo/lean-lsp-mcp) — Lean as MCP (see §1).
- Attestation: [AgentLedger PoB](https://datatracker.ietf.org/doc/html/draft-dembowski-agentledger-proof-of-behavior-00) (IETF I-D, Apr 2026, expired, individual author, MIT ref impl) — Ed25519-signed SHA-256 hash-chained receipts per tool_call/llm_invoke; records behavior, **does not judge correctness**. [Sigstore/Rekor + in-toto + C2PA](https://www.fast.io/resources/ai-agent-output-attestation.md) — provenance stack; Anthropic already emits [C2PA manifests](https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool) on generated media. None attest *truth*.

No registry entry found that combines recompute + verdict + content-addressed receipt. The "calculator" and "attestation" lanes exist separately; the "verifier" lane is Reexpress (statistical) and nothing else credible.

## 5. "Why not just run Python?"

- [Anthropic code execution](https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool): sandboxed Python 3.11 w/ numpy/scipy/sympy, free with web tools else $0.05/hr past 1,550 free hrs; **no determinism guarantee, no pinned versions, no execution receipt**; PTC lets Claude script tools from inside.
- [OpenAI Code Interpreter](https://developers.openai.com/api/docs/guides/tools-code-interpreter): ephemeral containers (20-min expiry), no reproducibility or hash claims.
- [E2B](https://e2b.dev/docs/quickstart/connect-llms): general sandboxes, same story.
- Finance/units libraries ([finrb](https://github.com/ncs1/finrb/wiki), [loan-calculator](https://loan-calculator.readthedocs.io/), Pint via [pint-compute skill](https://www.skills.sh/parcadei/continuous-claude-v3/pint-compute)) — any agent can import them.

The objection is strong: an agent with sympy+Pint in a sandbox can recompute anything in Concordance's 90 verifiers. The counter is not "it can't," it is "the LLM writes the checking code, so the checker is as hallucination-prone as the claim, and nothing is sealed."

---

## (a) Five closest competitors, ranked

1. **AxiomGuard** — explicitly "deterministic neuro-symbolic guardrail," Z3, solo-built, Apr 2026. Same thesis, logic not numerics, no ledger.
2. **Reexpress MCP** — "verify LLM output over MCP"; probabilistic. Will be confused with Concordance in a pitch.
3. **precisioncalc-mcp + MedCalc MCP** (as a pair) — already own the finance and medicine *calculation* surface Concordance verifies; they lack the verdict/receipt layer but a reviewer will ask why not wrap them.
4. **Wolfram MCP** — the incumbent "accurate computed results" tool with a Claude marketplace listing.
5. **Patronus Lynx / Cleanlab TLM** — the funded PASS/FAIL incumbents; different method, same buyer.

## (b) Five best fits (integrate, don't compete)

1. **Guardrails Hub validator** (`guardrails-ai-concordance`): Pass/FailResult maps 1:1 to PASS/REJECT; gets NeMo Guardrails distribution for free ([NeMo catalog](https://docs.nvidia.com/nemo/guardrails/latest/configure-guardrails/guardrail-catalog/third-party/guardrails-ai)).
2. **Braintrust autoevals / DeepEval custom metric**: both accept plain functions; Concordance as a deterministic scorer slots beside `NumericDiff` ([autoevals](https://braintrust.dev/docs/autoevals)).
3. **PrimeIntellect verifiers environment**: package the 90 verifiers as a reward env on the Environments Hub — 4.7k★ audience that explicitly wants un-hackable rule rewards ([2505.22203](https://arxiv.org/pdf/2505.22203)).
4. **AgentLedger PoB receipt format**: adopt or map the seal to its signed-receipt JSON (payload_hash/result_hash/prev_hash) so the ledger speaks an emerging interchange format rather than a private one.
5. **Math-Verify + Pint as backends**: don't reimplement answer-equivalence or dimensional analysis; wrap the best-maintained libraries and spend effort on the domain packets and the ledger.

Plus: list on Glama/PulseMCP/mcp.so and Anthropic's connector marketplace next to Wolfram.

## (c) Strongest objection, honest answer

**Objection:** "Every frontier model now has a sandbox with sympy. Concordance is 90 hand-written formulas behind an API, and the hard part — turning a prose claim into a structured packet — is still done by the LLM you don't trust. The receipt proves the *packet* was checked, not that the packet matches the sentence."

**Honest answer:** Correct on both counts, and the recall finding in [Huang et al.](https://arxiv.org/pdf/2505.22203) shows the structured-input requirement will cost coverage. What the sandbox does *not* give you: a verdict computed by code the LLM didn't write, a worked trail, pinned deterministic semantics, and a hash anyone can re-derive without trusting Anthropic/OpenAI's container ([Anthropic docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool) make no reproducibility promise). That is a real but narrow value: it matters where a third party must *audit* the number (finance, dosage, engineering sign-off), not where a chatbot needs to be roughly right. The product case lives or dies on (i) the packet extractor being auditable too (expose it, like AxiomGuard does), and (ii) the ledger using a format others can verify (PoB/in-toto), not a bespoke one. The scribe/SVD loop is novel in mechanism but unproven against [self-consistency baselines](https://proceedings.mlr.press/v235/smit24a.html); it needs a benchmark before it is a selling point.