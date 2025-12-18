use crate::error::AkariError;
use crate::header::Header;
use crate::header_v3::HeaderV3;
use chacha20poly1305::aead::{Aead, KeyInit, Payload};
use chacha20poly1305::{XChaCha20Poly1305, XNonce};
use sha2::{Digest, Sha256};

pub const AEAD_TAG_LEN: usize = 16;

fn build_nonce_common(message_id: u64, seq: u16, flags: u8) -> XNonce {
    // nonce = message_id(8) | seq(2) | flags low 2bits | zero padding to 24B
    let mut nonce = [0u8; 24];
    nonce[0..8].copy_from_slice(&message_id.to_be_bytes());
    nonce[8..10].copy_from_slice(&seq.to_be_bytes());
    nonce[10] = flags & 0x03;
    *XNonce::from_slice(&nonce)
}

fn new_cipher(psk: &[u8]) -> Result<XChaCha20Poly1305, AkariError> {
    let key_bytes: [u8; 32] = if psk.len() == 32 {
        let mut out = [0u8; 32];
        out.copy_from_slice(psk);
        out
    } else {
        let digest = Sha256::digest(psk);
        digest.into()
    };
    XChaCha20Poly1305::new_from_slice(&key_bytes).map_err(|_| AkariError::InvalidPsk)
}

pub fn encrypt_payload(psk: &[u8], header: &Header, plaintext: &[u8]) -> Result<(Vec<u8>, [u8; AEAD_TAG_LEN]), AkariError> {
    if plaintext.len() > u16::MAX as usize {
        return Err(AkariError::PayloadTooLarge(plaintext.len()));
    }
    let cipher = new_cipher(psk)?;
    let nonce = build_nonce_common(header.message_id, header.seq, header.flags);
    let aad = header.to_bytes();
    let mut ciphertext_with_tag = cipher
        .encrypt(&nonce, Payload { msg: plaintext, aad: &aad })
        .map_err(|_| AkariError::AeadFailed)?;
    if ciphertext_with_tag.len() < plaintext.len() + AEAD_TAG_LEN {
        return Err(AkariError::AeadFailed);
    }
    let tag_start = ciphertext_with_tag.len() - AEAD_TAG_LEN;
    let tag: [u8; AEAD_TAG_LEN] = ciphertext_with_tag[tag_start..].try_into().unwrap();
    ciphertext_with_tag.truncate(tag_start);
    Ok((ciphertext_with_tag, tag))
}

pub fn decrypt_payload(psk: &[u8], header: &Header, ciphertext: &[u8], tag: &[u8]) -> Result<Vec<u8>, AkariError> {
    if tag.len() != AEAD_TAG_LEN {
        return Err(AkariError::AeadFailed);
    }
    let cipher = new_cipher(psk)?;
    let nonce = build_nonce_common(header.message_id, header.seq, header.flags);
    let aad = header.to_bytes();
    let mut combined = Vec::with_capacity(ciphertext.len() + AEAD_TAG_LEN);
    combined.extend_from_slice(ciphertext);
    combined.extend_from_slice(tag);
    cipher
        .decrypt(&nonce, Payload { msg: &combined, aad: &aad })
        .map_err(|_| AkariError::AeadFailed)
}

// --- v3 variants ---
pub fn encrypt_payload_v3(
    psk: &[u8],
    header: &HeaderV3,
    plaintext: &[u8],
    aad: &[u8],
) -> Result<(Vec<u8>, [u8; AEAD_TAG_LEN]), AkariError> {
    if plaintext.len() > u16::MAX as usize {
        return Err(AkariError::PayloadTooLarge(plaintext.len()));
    }
    let cipher = new_cipher(psk)?;
    let nonce = build_nonce_common(header.message_id, header.seq, header.flags);
    let mut ciphertext_with_tag = cipher
        .encrypt(&nonce, Payload { msg: plaintext, aad })
        .map_err(|_| AkariError::AeadFailed)?;
    if ciphertext_with_tag.len() < plaintext.len() + AEAD_TAG_LEN {
        return Err(AkariError::AeadFailed);
    }
    let tag_start = ciphertext_with_tag.len() - AEAD_TAG_LEN;
    let tag: [u8; AEAD_TAG_LEN] = ciphertext_with_tag[tag_start..].try_into().unwrap();
    ciphertext_with_tag.truncate(tag_start);
    Ok((ciphertext_with_tag, tag))
}

pub fn decrypt_payload_v3(
    psk: &[u8],
    header: &HeaderV3,
    ciphertext: &[u8],
    tag: &[u8],
    aad: &[u8],
) -> Result<Vec<u8>, AkariError> {
    if tag.len() != AEAD_TAG_LEN {
        return Err(AkariError::AeadFailed);
    }
    let cipher = new_cipher(psk)?;
    let nonce = build_nonce_common(header.message_id, header.seq, header.flags);
    let mut combined = Vec::with_capacity(ciphertext.len() + AEAD_TAG_LEN);
    combined.extend_from_slice(ciphertext);
    combined.extend_from_slice(tag);
    cipher
        .decrypt(&nonce, Payload { msg: &combined, aad })
        .map_err(|_| AkariError::AeadFailed)
}
