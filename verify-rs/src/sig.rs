//! Signature verification wired to the V3 envelope: Ed25519 over a COSE_Sign1 `Sig_structure`
//! (RFC 9052 §4.4) and Ed25519 over a DSSE PAE (in-toto). Ported to match `docs/verify_receipt.py`.
//! ML-DSA (pq) is pending a vetted crate; `lib` surfaces it as a gap, never a false pass.

use base64::engine::general_purpose::{STANDARD, URL_SAFE_NO_PAD};
use base64::Engine;
use ciborium::value::Value as Cbor;
use ed25519_dalek::{Signature, Verifier, VerifyingKey};

fn b64_std(s: &str) -> Result<Vec<u8>, String> {
    STANDARD.decode(s.trim()).map_err(|e| e.to_string())
}

/// base64url, padding optional (the issuer key is stored unpadded raw, like verify_receipt's b64u_decode).
fn b64url(s: &str) -> Result<Vec<u8>, String> {
    URL_SAFE_NO_PAD.decode(s.trim().trim_end_matches('=')).map_err(|e| e.to_string())
}

fn ed_verify(pub_raw: &[u8], msg: &[u8], sig: &[u8]) -> Result<bool, String> {
    let pk: [u8; 32] = pub_raw.try_into().map_err(|_| "public key is not 32 bytes".to_string())?;
    let vk = VerifyingKey::from_bytes(&pk).map_err(|e| e.to_string())?;
    let s = Signature::from_slice(sig).map_err(|e| e.to_string())?;
    Ok(vk.verify(msg, &s).is_ok())
}

fn as_bytes(v: &Cbor) -> Result<Vec<u8>, String> {
    match v {
        Cbor::Bytes(b) => Ok(b.clone()),
        _ => Err("expected a CBOR byte string".into()),
    }
}

/// Verify a COSE_Sign1 (base64) under an Ed25519 public key (base64url raw). Returns (ok, payload, detail).
/// Sig_structure = ["Signature1", protected, b"", payload] (RFC 9052 §4.4); the caller checks that
/// sha256(payload) equals the record's content_hash.
pub fn verify_cose_sign1(cose_b64: &str, pubkey_b64url: &str) -> Result<(bool, Vec<u8>, String), String> {
    let raw = b64_std(cose_b64)?;
    let val: Cbor = ciborium::from_reader(&raw[..]).map_err(|e| format!("CBOR decode: {e}"))?;
    let arr = match val {
        Cbor::Tag(18, boxed) => match *boxed {
            Cbor::Array(a) => a,
            _ => return Err("COSE_Sign1 tag 18 payload is not an array".into()),
        },
        Cbor::Array(a) => a, // tolerate an untagged COSE_Sign1 array
        _ => return Err("not a COSE_Sign1 (expected CBOR tag 18)".into()),
    };
    if arr.len() != 4 {
        return Err(format!("COSE_Sign1 array has {} elements, expected 4", arr.len()));
    }
    let protected = as_bytes(&arr[0])?;
    let payload = as_bytes(&arr[2])?;
    let sig = as_bytes(&arr[3])?;

    let sig_structure = Cbor::Array(vec![
        Cbor::Text("Signature1".to_string()),
        Cbor::Bytes(protected.clone()),
        Cbor::Bytes(Vec::new()),
        Cbor::Bytes(payload.clone()),
    ]);
    let mut tbs = Vec::new();
    ciborium::into_writer(&sig_structure, &mut tbs).map_err(|e| format!("CBOR encode: {e}"))?;

    let pk = b64url(pubkey_b64url)?;
    let ok = ed_verify(&pk, &tbs, &sig)?;
    let detail = if ok {
        "EdDSA over COSE Sig_structure verifies".to_string()
    } else {
        "EdDSA signature does NOT verify under the issuer key".to_string()
    };
    Ok((ok, payload, detail))
}

/// Verify an in-toto DSSE signature: Ed25519 over PAE(payloadType, base64-decoded payload).
/// PAE = "DSSEv1" SP len(type) SP type SP len(body) SP body (the DSSE pre-authentication encoding).
pub fn verify_dsse(payload_type: &str, payload_b64: &str, sig_b64: &str, pubkey_b64url: &str) -> Result<bool, String> {
    let payload = b64_std(payload_b64)?;
    let mut pae: Vec<u8> = Vec::new();
    pae.extend_from_slice(b"DSSEv1 ");
    pae.extend_from_slice(payload_type.len().to_string().as_bytes());
    pae.push(b' ');
    pae.extend_from_slice(payload_type.as_bytes());
    pae.push(b' ');
    pae.extend_from_slice(payload.len().to_string().as_bytes());
    pae.push(b' ');
    pae.extend_from_slice(&payload);
    let pk = b64url(pubkey_b64url)?;
    let sig = b64_std(sig_b64)?;
    ed_verify(&pk, &pae, &sig)
}
