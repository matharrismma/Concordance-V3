//! Self-contained conformance for the certificate re-check — needs NO golden receipt, NO V3 data.
//! These pin the mathematically substantive core: a true witness passes, a forged one fails.

use concordance_verify::certificate::check;
use serde_json::json;

#[test]
fn composite_is_rechecked() {
    let c = json!({"kind":"primality","claim":{"n":15,"verdict":"composite"},"witness":{"factor":3}});
    assert!(check(&c).0);
}

#[test]
fn forged_factor_is_rejected() {
    // 15 % 4 != 0 — not a nontrivial factor
    let c = json!({"kind":"primality","claim":{"n":15,"verdict":"composite"},"witness":{"factor":4}});
    assert!(!check(&c).0);
}

#[test]
fn primes_2_3_7_recheck() {
    let two = json!({"kind":"primality","claim":{"n":2,"verdict":"prime"},"witness":{"base":1,"factors":[]}});
    let three = json!({"kind":"primality","claim":{"n":3,"verdict":"prime"},
                       "witness":{"base":2,"factors":[[2, two]]}});
    // n-1 = 6 = 2·3 ; base 3: 3^6≡1, 3^3≡6≠1, 3^2≡2≠1 (mod 7)
    let two2 = json!({"kind":"primality","claim":{"n":2,"verdict":"prime"},"witness":{"base":1,"factors":[]}});
    let three2 = json!({"kind":"primality","claim":{"n":3,"verdict":"prime"},
                        "witness":{"base":2,"factors":[[2, two2]]}});
    let two3 = json!({"kind":"primality","claim":{"n":2,"verdict":"prime"},"witness":{"base":1,"factors":[]}});
    let seven = json!({"kind":"primality","claim":{"n":7,"verdict":"prime"},
                       "witness":{"base":3,"factors":[[2, two3],[3, three2]]}});
    assert!(check(&three).0);
    assert!(check(&seven).0);
}

#[test]
fn composite_masquerading_as_prime_is_rejected() {
    // 9 is not prime: completeness passes (n-1=8=2^3) but Lucas fails — 2^8 ≡ 4 (mod 9) ≠ 1.
    let two = json!({"kind":"primality","claim":{"n":2,"verdict":"prime"},"witness":{"base":1,"factors":[]}});
    let bogus = json!({"kind":"primality","claim":{"n":9,"verdict":"prime"},
                       "witness":{"base":2,"factors":[[2, two]]}});
    assert!(!check(&bogus).0);
}

#[test]
fn polynomial_root_exact_and_fraction() {
    // x^2 - 5x + 6 : roots 2, 3
    let r2 = json!({"kind":"polynomial_root","claim":{"coeffs":[1,-5,6],"verdict":"root"},"witness":{"root":"2"}});
    assert!(check(&r2).0);
    let bad = json!({"kind":"polynomial_root","claim":{"coeffs":[1,-5,6],"verdict":"root"},"witness":{"root":"4"}});
    assert!(!check(&bad).0);
    // 2x^2 - 3x + 1 : roots 1 and 1/2 (exact rational)
    let half = json!({"kind":"polynomial_root","claim":{"coeffs":[2,-3,1],"verdict":"root"},"witness":{"root":"1/2"}});
    assert!(check(&half).0);
}

#[test]
fn linear_system_exact() {
    let ok = json!({"kind":"linear_system",
        "claim":{"verdict":"solves","A":[["2","0"],["0","1"]],"b":["4","3"]},
        "witness":{"x":["2","3"]}});
    assert!(check(&ok).0);
    let bad = json!({"kind":"linear_system",
        "claim":{"verdict":"solves","A":[["2","0"],["0","1"]],"b":["4","3"]},
        "witness":{"x":["1","3"]}});
    assert!(!check(&bad).0);
}

#[test]
fn unknown_kind_is_rejected() {
    let c = json!({"kind":"handwave","claim":{},"witness":{}});
    assert!(!check(&c).0);
}
