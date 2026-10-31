//! Independent re-check of concordance certificates — a faithful Rust port of
//! `verifiers/certificate.py::check` (the bbchallenge FAR/WFAR trust anchor). Pure, exact
//! (BigInt / BigRational), no I/O, no network. A forged certificate fails here — that is the point.
//!
//! This module is the mathematically substantive, fully-testable heart of `concordance-verify`:
//! it never calls a producer or a primality routine; it re-derives the verdict from the witness.

use num_bigint::BigInt;
use num_rational::BigRational;
use num_traits::{One, Zero};
use serde_json::Value;
use std::str::FromStr;

/// (ok, detail) — re-confirm a certificate WITHOUT trusting or re-running the producer.
pub fn check(cert: &Value) -> (bool, String) {
    match cert.get("kind").and_then(|v| v.as_str()).unwrap_or("") {
        "polynomial_root" => check_polynomial_root(cert),
        "linear_system" => check_linear_system(cert),
        "primality" => check_primality(cert),
        other => (false, format!("unknown certificate kind {other:?}")),
    }
}

fn is_bool(v: &Value) -> bool {
    v.is_boolean()
}

/// A BigInt from a JSON integer or an integer string. Bools and non-integers yield None.
fn big_from_json(v: &Value) -> Option<BigInt> {
    if is_bool(v) {
        return None;
    }
    if let Some(i) = v.as_i64() {
        return Some(BigInt::from(i));
    }
    if let Some(u) = v.as_u64() {
        return Some(BigInt::from(u));
    }
    if let Some(s) = v.as_str() {
        return BigInt::from_str(s.trim()).ok();
    }
    if v.is_number() {
        return BigInt::from_str(&v.to_string()).ok();
    }
    None
}

fn rat_from_str(s: &str) -> Option<BigRational> {
    let s = s.trim();
    if let Some((n, d)) = s.split_once('/') {
        let num = BigInt::from_str(n.trim()).ok()?;
        let den = BigInt::from_str(d.trim()).ok()?;
        if den.is_zero() {
            return None;
        }
        return Some(BigRational::new(num, den));
    }
    Some(BigRational::from(BigInt::from_str(s).ok()?))
}

/// An exact rational from a JSON string ("p" or "p/q") or a JSON integer. The engine stores
/// certificate rationals as strings and coefficients as ints; floats are never written, so a
/// float here would be a malformed (non-exact) witness and is rejected.
fn rat_from_json(v: &Value) -> Option<BigRational> {
    if is_bool(v) {
        return None;
    }
    if let Some(s) = v.as_str() {
        return rat_from_str(s);
    }
    if let Some(i) = v.as_i64() {
        return Some(BigRational::from(BigInt::from(i)));
    }
    if let Some(u) = v.as_u64() {
        return Some(BigRational::from(BigInt::from(u)));
    }
    if v.is_i64() || v.is_u64() {
        return Some(BigRational::from(BigInt::from_str(&v.to_string()).ok()?));
    }
    None // a float is not an exact witness
}

fn poly_eval(coeffs: &[BigInt], x: &BigRational) -> BigRational {
    // Horner, highest degree first — exact.
    let mut acc = BigRational::zero();
    for c in coeffs {
        acc = &acc * x + BigRational::from(c.clone());
    }
    acc
}

fn check_polynomial_root(c: &Value) -> (bool, String) {
    let coeffs_v = match c.get("claim").and_then(|cl| cl.get("coeffs")).and_then(|v| v.as_array()) {
        Some(a) => a,
        None => return (false, "malformed polynomial-root certificate".into()),
    };
    let mut coeffs = Vec::with_capacity(coeffs_v.len());
    for v in coeffs_v {
        match big_from_json(v) {
            Some(b) => coeffs.push(b),
            None => return (false, "non-integer coefficient".into()),
        }
    }
    let root = match c.get("witness").and_then(|w| w.get("root")).and_then(rat_from_json) {
        Some(r) => r,
        None => return (false, "malformed polynomial-root certificate".into()),
    };
    if poly_eval(&coeffs, &root).is_zero() {
        (true, format!("p(root) = 0 — exact rational root (degree {})", coeffs.len().saturating_sub(1)))
    } else {
        (false, "p(root) != 0 — not a root".into())
    }
}

fn parse_rat_matrix(v: Option<&Value>) -> Option<Vec<Vec<BigRational>>> {
    let arr = v?.as_array()?;
    let mut out = Vec::with_capacity(arr.len());
    for row in arr {
        let r = row.as_array()?;
        let mut rr = Vec::with_capacity(r.len());
        for cell in r {
            rr.push(rat_from_json(cell)?);
        }
        out.push(rr);
    }
    Some(out)
}

fn parse_rat_vec(v: Option<&Value>) -> Option<Vec<BigRational>> {
    let arr = v?.as_array()?;
    let mut out = Vec::with_capacity(arr.len());
    for cell in arr {
        out.push(rat_from_json(cell)?);
    }
    Some(out)
}

fn check_linear_system(c: &Value) -> (bool, String) {
    let a = parse_rat_matrix(c.get("claim").and_then(|cl| cl.get("A")));
    let b = parse_rat_vec(c.get("claim").and_then(|cl| cl.get("b")));
    let x = parse_rat_vec(c.get("witness").and_then(|w| w.get("x")));
    let (a, b, x) = match (a, b, x) {
        (Some(a), Some(b), Some(x)) => (a, b, x),
        _ => return (false, "malformed linear-system certificate".into()),
    };
    if a.is_empty() || a.len() != b.len() || a.iter().any(|row| row.len() != x.len()) {
        return (false, "shape mismatch".into());
    }
    for (i, row) in a.iter().enumerate() {
        let mut acc = BigRational::zero();
        for j in 0..x.len() {
            acc = acc + &row[j] * &x[j];
        }
        if acc != b[i] {
            return (false, "A·x != b — x does not solve the system".into());
        }
    }
    (true, format!("A·x == b exactly ({}x{} system)", a.len(), x.len()))
}

fn check_primality(c: &Value) -> (bool, String) {
    let claim = &c["claim"];
    let n = match claim.get("n").and_then(big_from_json) {
        Some(n) => n,
        None => return (false, "malformed claim".into()),
    };
    let two = BigInt::from(2);
    let one = BigInt::one();
    if n < two {
        return (false, "n < 2 is neither prime nor composite".into());
    }
    let verdict = claim.get("verdict").and_then(|v| v.as_str()).unwrap_or("");
    let witness = &c["witness"];

    if verdict == "composite" {
        let d = witness.get("factor").filter(|v| !is_bool(v)).and_then(big_from_json);
        return match d {
            Some(d) if d > one && d < n && (&n % &d).is_zero() => {
                let q = &n / &d;
                (true, format!("{n} = {d} x {q} (composite)"))
            }
            _ => (false, format!("not a nontrivial factor of {n}")),
        };
    }

    if verdict == "prime" {
        if n == two {
            return (true, "2 is prime (base case)".into());
        }
        let a = match witness.get("base").filter(|v| !is_bool(v)).and_then(big_from_json) {
            Some(a) => a,
            None => return (false, "malformed prime witness".into()),
        };
        let factors = match witness.get("factors").and_then(|v| v.as_array()) {
            Some(f) => f,
            None => return (false, "malformed prime witness".into()),
        };
        let mut qs: Vec<BigInt> = Vec::new();
        for item in factors {
            let arr = match item.as_array() {
                Some(a) if a.len() >= 2 => a,
                _ => return (false, "malformed factor entry".into()),
            };
            let q = match big_from_json(&arr[0]) {
                Some(q) => q,
                None => return (false, "malformed factor entry".into()),
            };
            let sub = &arr[1];
            let (ok, why) = check(sub); // the factor must itself be a certified prime
            if !ok {
                return (false, format!("factor {q} not certified prime: {why}"));
            }
            let sub_n = sub.get("claim").and_then(|cl| cl.get("n")).and_then(big_from_json);
            let sub_v = sub.get("claim").and_then(|cl| cl.get("verdict")).and_then(|v| v.as_str()).unwrap_or("");
            if sub_n.as_ref() != Some(&q) || sub_v != "prime" {
                return (false, format!("factor entry {q} does not certify its own primality"));
            }
            qs.push(q);
        }
        // completeness: the listed primes must be EXACTLY the prime divisors of n-1 (none omitted)
        let nm1 = &n - &one;
        let mut m = nm1.clone();
        for q in &qs {
            if q < &two || !(&m % q).is_zero() {
                return (false, format!("{q} does not divide n-1"));
            }
            while (&m % q).is_zero() {
                m = &m / q;
            }
        }
        if m != one {
            return (false, "listed factors do not generate n-1 — a prime divisor is missing".into());
        }
        // Lucas: a^(n-1) == 1 (mod n), and a^((n-1)/q) != 1 for each prime q | n-1
        if a.modpow(&nm1, &n) != one {
            return (false, "a^(n-1) != 1 (mod n)".into());
        }
        let mut seen: Vec<BigInt> = Vec::new();
        for q in &qs {
            if !seen.contains(q) {
                seen.push(q.clone());
            }
        }
        for q in &seen {
            if a.modpow(&(&nm1 / q), &n) == one {
                return (false, format!("a^((n-1)/{q}) == 1 (mod n): base {a} is not a witness"));
            }
        }
        return (true, format!("{n} is prime by Lucas (base {a})"));
    }

    (false, format!("unknown verdict {verdict:?}"))
}

/// One row per certificate found in a sealed record's `verifier_results`.
pub struct CertRow {
    pub name: String,
    pub kind: String,
    pub ok: bool,
    pub detail: String,
}

/// Re-verify every independently-checkable certificate carried in a sealed record.
/// // VERIFY: the engine stores certs at `record.verifier_results[].data.certificate`. The record is
/// taken from `receipt["record"]` when present, else the receipt root — confirm against receipt_golden.json.
pub fn recheck_all(receipt: &Value) -> Vec<CertRow> {
    let record = receipt.get("record").unwrap_or(receipt);
    let mut out = Vec::new();
    if let Some(vrs) = record.get("verifier_results").and_then(|v| v.as_array()) {
        for vr in vrs {
            if let Some(cert) = vr.get("data").and_then(|d| d.get("certificate")) {
                if cert.is_object() {
                    let (ok, detail) = check(cert);
                    out.push(CertRow {
                        name: vr.get("name").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                        kind: cert.get("kind").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                        ok,
                        detail,
                    });
                }
            }
        }
    }
    out
}
