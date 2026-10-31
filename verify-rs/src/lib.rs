#![forbid(unsafe_code)]
//! concordance-verify — an INDEPENDENT re-check of a `concordance-receipt/3.x` seal.
//!
//! Wired to V3's envelope and validated against `tests/fixtures/receipt_golden.json`:
//!   HASH       canonical(record minus content_hash+attest) re-hashes (SHA-256) to content_hash.
//!   SIGNATURE  Ed25519 COSE_Sign1 over Sig_structure; its payload hashes to the content_hash.
//!   IN-TOTO    the DSSE Ed25519 statement verifies over its PAE.
//!   CERTIFICATE any independently-checkable certificate carried in the record re-checks (concordance-2
//!              style; V3 receipts carry refutation bands instead, so this is usually absent).
//! Surfaced but not asserted by this build: PQ (ML-DSA present → gap, pending crate) and the Rekor log
//! (needs network). Honest-by-construction: VERIFIED only when HASH and SIGNATURE both pass; any provable
//! failure → BROKEN; otherwise INCOMPLETE. A gap never becomes a false VERIFIED.

pub mod canonical;
pub mod certificate;
pub mod sig;

use serde_json::Value;
use sha2::{Digest, Sha256};

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Status {
    Pass,
    Fail,
    Gap,
}

pub struct Check {
    pub name: String,
    pub status: Status,
    pub detail: String,
}

pub struct Report {
    pub verdict: String,
    pub checks: Vec<Check>,
}

impl Report {
    pub fn exit_code(&self) -> i32 {
        match self.verdict.as_str() {
            "VERIFIED" => 0,
            "BROKEN" => 1,
            _ => 3,
        }
    }

    pub fn to_json(&self) -> String {
        let checks: Vec<Value> = self
            .checks
            .iter()
            .map(|c| {
                serde_json::json!({
                    "name": c.name,
                    "ok": match c.status {
                        Status::Pass => Value::Bool(true),
                        Status::Fail => Value::Bool(false),
                        Status::Gap => Value::Null,
                    },
                    "detail": c.detail,
                })
            })
            .collect();
        serde_json::json!({ "verdict": self.verdict, "checks": checks }).to_string()
    }
}

fn sha256_hex(b: &[u8]) -> String {
    let mut h = Sha256::new();
    h.update(b);
    hex::encode(h.finalize())
}

fn head(s: &str) -> &str {
    &s[..16.min(s.len())]
}

pub fn verify_receipt(data: &Value) -> Report {
    let mut checks: Vec<Check> = Vec::new();
    let record = data.get("record").unwrap_or(data);
    let att = data.get("attest").unwrap_or(data);
    let record_hash = record.get("content_hash").and_then(|v| v.as_str()).map(|s| s.to_string());

    // 1. HASH — canonical(record minus content_hash, attest) == content_hash
    match record_hash.as_deref() {
        None => checks.push(Check { name: "hash".into(), status: Status::Gap, detail: "record has no content_hash".into() }),
        Some(claimed) => {
            let got = canonical::content_hash_excluding(record, &["content_hash", "attest"]);
            let ok = got == claimed;
            checks.push(Check {
                name: "hash".into(),
                status: if ok { Status::Pass } else { Status::Fail },
                detail: format!("sha256(canonical record) {}… vs claimed {}…", head(&got), head(claimed)),
            });
        }
    }

    // 2. SIGNATURE — Ed25519 COSE_Sign1; payload must hash to the content_hash
    let env = att.get("envelope");
    match env.and_then(|e| e.get("cose_sign1_b64")).and_then(|v| v.as_str()) {
        Some(cose) => {
            let pubkey = env.and_then(|e| e.get("public_key")).and_then(|v| v.as_str()).unwrap_or("");
            match sig::verify_cose_sign1(cose, pubkey) {
                Ok((ok, payload, detail)) => {
                    let ph = sha256_hex(&payload);
                    let hash_binds = record_hash.as_deref().map_or(true, |rh| rh == ph);
                    let pass = ok && hash_binds;
                    let d = if !ok {
                        detail
                    } else if !hash_binds {
                        format!("signature verifies, but payload sha256 {}… != record content_hash — a different record", head(&ph))
                    } else {
                        format!("{detail}; payload sha256 = {}…", head(&ph))
                    };
                    checks.push(Check { name: "signature".into(), status: if pass { Status::Pass } else { Status::Fail }, detail: d });
                }
                Err(e) => checks.push(Check { name: "signature".into(), status: Status::Fail, detail: format!("COSE parse/verify error: {e}") }),
            }
        }
        None => checks.push(Check { name: "signature".into(), status: Status::Gap, detail: "no envelope — record is self-attested (content-addressed only)".into() }),
    }

    // 3. IN-TOTO DSSE — a second Ed25519 statement over the PAE
    if let Some(it) = att.get("in_toto") {
        let pt = it.get("payloadType").and_then(|v| v.as_str()).unwrap_or("");
        let payload_b64 = it.get("payload").and_then(|v| v.as_str()).unwrap_or("");
        let pubkey = it.get("public_key").and_then(|v| v.as_str()).unwrap_or("");
        let sig0 = it
            .get("signatures")
            .and_then(|v| v.as_array())
            .and_then(|a| a.first())
            .and_then(|s| s.get("sig"))
            .and_then(|v| v.as_str())
            .unwrap_or("");
        match sig::verify_dsse(pt, payload_b64, sig0, pubkey) {
            Ok(true) => checks.push(Check { name: "in_toto".into(), status: Status::Pass, detail: "DSSE Ed25519 over PAE verifies".into() }),
            Ok(false) => checks.push(Check { name: "in_toto".into(), status: Status::Fail, detail: "DSSE signature does not verify".into() }),
            Err(e) => checks.push(Check { name: "in_toto".into(), status: Status::Fail, detail: format!("DSSE error: {e}") }),
        }
    }

    // 4. PQ (ML-DSA) — present but not checked by this build (honest gap, never a false pass)
    if att.get("pq").and_then(|p| p.get("signature")).is_some() {
        checks.push(Check {
            name: "pq".into(),
            status: Status::Gap,
            detail: "ML-DSA-65 signature present; not verified by this build (ml-dsa crate wiring pending)".into(),
        });
    }

    // 5. CERTIFICATES — any independently-checkable certificate carried in the record
    for r in certificate::recheck_all(data) {
        let label = if r.name.is_empty() { r.kind.clone() } else { r.name.clone() };
        checks.push(Check {
            name: format!("certificate:{label}"),
            status: if r.ok { Status::Pass } else { Status::Fail },
            detail: r.detail,
        });
    }

    // verdict: any provable failure => BROKEN; else VERIFIED iff hash AND signature both passed; else INCOMPLETE.
    let any_fail = checks.iter().any(|c| c.status == Status::Fail);
    let hash_ok = checks.iter().any(|c| c.name == "hash" && c.status == Status::Pass);
    let sig_ok = checks.iter().any(|c| c.name == "signature" && c.status == Status::Pass);
    let verdict = if any_fail {
        "BROKEN"
    } else if hash_ok && sig_ok {
        "VERIFIED"
    } else {
        "INCOMPLETE"
    };
    Report { verdict: verdict.to_string(), checks }
}
