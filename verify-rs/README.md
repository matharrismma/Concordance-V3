# concordance-verify (Rust) — DRAFT

An independent, dependency-light re-checker for `concordance-receipt/3.x` seals: recompute the canonical
SHA-256 content hash, verify the Ed25519 COSE_Sign1 (then ML-DSA), and re-check the embedded exact-arithmetic
certificate. The compiled sibling of `docs/verify_receipt.py` — a *second implementation in a second
language*, so the receipt has an independent witness, not just a faster one.

## Status (read before trusting a verdict)

**Un-compiled draft.** Written with no Rust toolchain in the authoring environment, so first `cargo build`
may need minor crate-API adjustments. More importantly, it is **honest-by-construction**:

- **`certificate.rs` — faithful + testable now.** A direct port of the engine's `verifiers/certificate.py::check`
  (primality via Lucas/Pratt with the completeness check, polynomial Horner, linear matvec — all exact over
  `BigInt`/`BigRational`). `tests/certificate_tests.rs` pins it with no external data: a true witness passes, a
  forged one fails, a composite masquerading as prime fails.
- **`canonical.rs`, `sig.rs` — real primitives, binding unverified.** Canonical JSON→SHA-256 and Ed25519 verify
  are real, but *where they bind into a V3 receipt* (which object is hashed, the exact COSE `Sig_structure`/PAE
  bytes, the field paths) is marked `// VERIFY` and must be confirmed against `receipt_golden.json` +
  `docs/verify_receipt.py` in the Concordance-V3 repo.
- Until the signature is wired, `verify_receipt` returns **INCOMPLETE** — it never reports VERIFIED on an
  unchecked signature. A certificate that fails re-check returns **BROKEN**.

## Layout

```
Cargo.toml
src/main.rs          CLI: concordance-verify <receipt.json | -> [--json]
src/lib.rs           verify_receipt(): orchestration + verdict (worst-wins)
src/certificate.rs   the independent certificate re-check (faithful port; the trust anchor)
src/canonical.rs     canonical JSON bytes + SHA-256 content hash   // VERIFY parity
src/sig.rs           Ed25519 verify (real); ML-DSA TODO            // VERIFY signed-byte assembly
tests/certificate_tests.rs   self-contained conformance, no golden needed
```

## Finishing it (in Concordance-V3, where the golden lives)

1. `rustup`/`cargo` installed; drop this crate in as `verify-rs/` (isolated — touches no Python lean-core gate).
2. `cargo test` — the certificate tests must pass as-is.
3. Open `tests/fixtures/receipt_golden.json` and `docs/verify_receipt.py`; resolve every `// VERIFY`:
   - which object the content hash covers, and canonicalization parity (sorted keys, separators, ensure_ascii);
   - the exact bytes the COSE_Sign1 Ed25519 signature covers; wire `sig::verify_ed25519` to them;
   - enable an ML-DSA crate and verify `attest.pq` over the same record bytes.
4. Add an integration test that runs the binary against the golden (must VERIFY) and against tampered /
   wrong-key / forged-certificate copies (must BROKEN) — the **same verdicts** as `verify_receipt.py`.
5. CI: a `verify-rs` job beside the Python gates. Owner publishes per-platform release binaries.

## Parity targets (vs the measured Python baseline, 2026-10-30)

| | Python (measured) | Rust (target) |
|---|---|---|
| cold start | 6.70 s (mostly scipy/sympy) | ≤ 5 ms |
| peak RSS | 138 MB | ≤ 10 MB |
| per-verify warm | 0.41 ms | ≤ 1 ms (parity — not the point) |
| deps | interpreter + scipy/sympy | one static binary, 0 runtime deps |

The win is cold start, footprint, no-GIL concurrency, a single auditable binary, and the independent witness —
not raw per-verify speed, which is already negligible.
