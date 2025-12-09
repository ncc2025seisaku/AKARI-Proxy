use crate::error::AkariError;
use hmac::{Hmac, Mac};
use sha2::Sha256;

pub const TAG_LEN: usize = 16;
type HmacSha256 = Hmac<Sha256>;

pub fn compute_tag(psk: &[u8], data: &[u8]) -> Result<[u8; TAG_LEN], AkariError> {
    let mut mac = HmacSha256::new_from_slice(psk).map_err(|_| AkariError::InvalidPsk)?;
    mac.update(data);
    let result = mac.finalize().into_bytes();
    let mut tag = [0u8; TAG_LEN];
    tag.copy_from_slice(&result[..TAG_LEN]);
    Ok(tag)
}
