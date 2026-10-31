#![forbid(unsafe_code)]
//! `concordance-verify <receipt.json | -> [--json]` — exit 0 VERIFIED, 1 BROKEN, 3 INCOMPLETE/usage.

use std::io::Read;
use std::process::exit;

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let json_out = args.iter().any(|a| a == "--json");
    let path = args.iter().skip(1).find(|a| !a.starts_with("--")).cloned();

    let data = match path.as_deref() {
        None => {
            eprintln!("usage: concordance-verify <receipt.json | -> [--json]");
            exit(3);
        }
        Some("-") => {
            let mut s = String::new();
            if std::io::stdin().read_to_string(&mut s).is_err() {
                eprintln!("could not read stdin");
                exit(3);
            }
            s
        }
        Some(p) => match std::fs::read_to_string(p) {
            Ok(s) => s,
            Err(e) => {
                eprintln!("cannot read {p}: {e}");
                exit(3);
            }
        },
    };

    let value: serde_json::Value = match serde_json::from_str(&data) {
        Ok(v) => v,
        Err(e) => {
            eprintln!("invalid JSON: {e}");
            exit(3);
        }
    };

    let report = concordance_verify::verify_receipt(&value);
    if json_out {
        println!("{}", report.to_json());
    } else {
        println!("{}", report.verdict);
        for c in &report.checks {
            let mark = match c.status {
                concordance_verify::Status::Pass => "ok",
                concordance_verify::Status::Fail => "XX",
                concordance_verify::Status::Gap => "··",
            };
            println!("  [{mark}] {} — {}", c.name, c.detail);
        }
    }
    exit(report.exit_code());
}
