//! Canonical JSON bytes + the SHA-256 content hash — byte-matching V3's `verify_receipt.py`:
//! `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")`.
//!
//! Numbers are reproduced from their ORIGINAL text (serde_json `arbitrary_precision`), so floats in the
//! record (e.g. 75917.92514639649) re-serialize identically to what Python wrote — no float-format drift.
//! Strings: escape `" \ \b \f \n \r \t` and other C0 controls as `\u00xx`; everything else (incl.
//! non-ASCII like "—") is emitted as raw UTF-8, matching ensure_ascii=False.

use serde_json::Value;
use sha2::{Digest, Sha256};

pub fn canonical_bytes(v: &Value) -> Vec<u8> {
    let mut out = Vec::new();
    write_canonical(v, &mut out);
    out
}

/// The hash input: the record object with the given keys removed (V3 excludes "content_hash" and "attest").
pub fn content_hash_excluding(record: &Value, exclude: &[&str]) -> String {
    let mut out = Vec::new();
    if let Value::Object(m) = record {
        let mut keys: Vec<&String> = m.keys().filter(|k| !exclude.contains(&k.as_str())).collect();
        keys.sort();
        out.push(b'{');
        for (i, k) in keys.iter().enumerate() {
            if i > 0 {
                out.push(b',');
            }
            write_json_string(k, &mut out);
            out.push(b':');
            write_canonical(&m[*k], &mut out);
        }
        out.push(b'}');
    } else {
        write_canonical(record, &mut out);
    }
    let mut h = Sha256::new();
    h.update(&out);
    hex::encode(h.finalize())
}

fn write_canonical(v: &Value, out: &mut Vec<u8>) {
    match v {
        Value::Null => out.extend_from_slice(b"null"),
        Value::Bool(b) => out.extend_from_slice(if *b { b"true" } else { b"false" }),
        Value::Number(n) => out.extend_from_slice(n.to_string().as_bytes()), // original text (arbitrary_precision)
        Value::String(s) => write_json_string(s, out),
        Value::Array(a) => {
            out.push(b'[');
            for (i, e) in a.iter().enumerate() {
                if i > 0 {
                    out.push(b',');
                }
                write_canonical(e, out);
            }
            out.push(b']');
        }
        Value::Object(m) => {
            let mut keys: Vec<&String> = m.keys().collect();
            keys.sort();
            out.push(b'{');
            for (i, k) in keys.iter().enumerate() {
                if i > 0 {
                    out.push(b',');
                }
                write_json_string(k, out);
                out.push(b':');
                write_canonical(&m[*k], out);
            }
            out.push(b'}');
        }
    }
}

fn write_json_string(s: &str, out: &mut Vec<u8>) {
    out.push(b'"');
    for c in s.chars() {
        match c {
            '"' => out.extend_from_slice(b"\\\""),
            '\\' => out.extend_from_slice(b"\\\\"),
            '\u{0008}' => out.extend_from_slice(b"\\b"),
            '\u{000c}' => out.extend_from_slice(b"\\f"),
            '\n' => out.extend_from_slice(b"\\n"),
            '\r' => out.extend_from_slice(b"\\r"),
            '\t' => out.extend_from_slice(b"\\t"),
            c if (c as u32) < 0x20 => out.extend_from_slice(format!("\\u{:04x}", c as u32).as_bytes()),
            c => {
                let mut buf = [0u8; 4];
                out.extend_from_slice(c.encode_utf8(&mut buf).as_bytes());
            }
        }
    }
    out.push(b'"');
}
