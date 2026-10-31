//! Cross-language conformance against the REAL V3 golden receipt (tests/fixtures/receipt_golden.json).
//! The binary must VERIFY the genuine receipt and declare a tampered / wrong-key one BROKEN — the same
//! verdicts docs/verify_receipt.py gives.

use concordance_verify::{verify_receipt, Report, Status};
use serde_json::Value;

fn golden() -> Value {
    let p = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/fixtures/receipt_golden.json");
    serde_json::from_str(&std::fs::read_to_string(p).expect("read golden")).expect("parse golden")
}

fn trace(r: &Report) -> String {
    r.checks
        .iter()
        .map(|c| {
            let m = match c.status {
                Status::Pass => "ok",
                Status::Fail => "XX",
                Status::Gap => "..",
            };
            format!("[{m}] {}: {}", c.name, c.detail)
        })
        .collect::<Vec<_>>()
        .join("  |  ")
}

#[test]
fn golden_verifies() {
    let r = verify_receipt(&golden());
    assert_eq!(r.verdict, "VERIFIED", "{}", trace(&r));
}

#[test]
fn tampered_record_is_broken() {
    let mut v = golden();
    v["overall"] = Value::String("FAIL".into()); // mutate a hashed field → hash must mismatch
    let r = verify_receipt(&v);
    assert_eq!(r.verdict, "BROKEN", "{}", trace(&r));
}

#[test]
fn wrong_issuer_key_is_broken() {
    let mut v = golden();
    // corrupt the issuer public key → the Ed25519 statement must fail to verify
    v["attest"]["envelope"]["public_key"] = Value::String("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA".into());
    let r = verify_receipt(&v);
    assert_eq!(r.verdict, "BROKEN", "{}", trace(&r));
}
