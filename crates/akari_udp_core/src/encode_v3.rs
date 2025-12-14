use crate::aead::encrypt_payload_v3;
use crate::error::AkariError;
use crate::header_v3::{HeaderV3, PacketTypeV3, FLAG_ENCRYPT, FLAG_SHORT_LEN};
use crate::hmac::{compute_tag, TAG_LEN};
use crate::payload::RequestMethod;

fn finalize_packet(header: &HeaderV3, payload: &[u8], psk: &[u8], include_tag: bool) -> Result<Vec<u8>, AkariError> {
    if payload.len() != header.payload_len as usize {
        return Err(AkariError::InvalidPacketLength {
            expected: header.payload_len as usize,
            actual: payload.len(),
        });
    }
    let encrypt = header.flags & FLAG_ENCRYPT != 0;
    let header_bytes = header.to_bytes();
    let mut buf = Vec::with_capacity(header_bytes.len() + payload.len() + if include_tag { TAG_LEN } else { 0 });
    buf.extend_from_slice(&header_bytes);
    if encrypt {
        let (ciphertext, tag) = encrypt_payload_v3(psk, header, payload, &header_bytes)?;
        buf.extend_from_slice(&ciphertext);
        buf.extend_from_slice(&tag);
    } else if include_tag {
        buf.extend_from_slice(payload);
        let tag = compute_tag(psk, &buf)?;
        buf.extend_from_slice(&tag);
    } else {
        // aggregate-tagなどタグ省略モード（非暗号化専用）
        buf.extend_from_slice(payload);
    }
    Ok(buf)
}

// ------------ Request ------------
pub fn encode_request_v3(
    method: RequestMethod,
    url: &str,
    header_block: &[u8],
    message_id: u64,
    timestamp: u32,
    flags: u8,
    psk: &[u8],
) -> Result<Vec<u8>, AkariError> {
    let url_bytes = url.as_bytes();
    let payload_len = 1 + 2 + 2 + url_bytes.len() + header_block.len(); // method + url_len + hdr_len + url + hdr
    let header = HeaderV3 {
        packet_type: PacketTypeV3::Req,
        flags,
        message_id,
        seq: timestamp as u16,      // reuse seq for timestamp lower bits to avoid extra field
        seq_total: (timestamp >> 16) as u16,
        payload_len: payload_len as u16,
    };
    let mut payload = Vec::with_capacity(payload_len);
    payload.push(method as u8);
    payload.extend_from_slice(&(url_bytes.len() as u16).to_be_bytes());
    payload.extend_from_slice(&(header_block.len() as u16).to_be_bytes());
    payload.extend_from_slice(url_bytes);
    payload.extend_from_slice(header_block);
    finalize_packet(&header, &payload, psk, true)
}

// ------------ Response Head ------------
pub fn encode_resp_head_v3(
    status_code: u16,
    _hdr_len: usize,
    hdr_chunk: &[u8],
    body_len: u32,
    hdr_chunks: u8,
    hdr_idx: u8,
    seq_total_body: u16,
    flags: u8,
    message_id: u64,
    psk: &[u8],
) -> Result<Vec<u8>, AkariError> {
    let len_field_bytes = if flags & FLAG_SHORT_LEN != 0 { 3 } else { 4 };
    let mut payload = Vec::with_capacity(2 + len_field_bytes + 1 + 1 + hdr_chunk.len());
    payload.extend_from_slice(&status_code.to_be_bytes());
    if flags & FLAG_SHORT_LEN != 0 {
        let len24 = (body_len & 0x00ff_ffff) as u32;
        payload.extend_from_slice(&len24.to_be_bytes()[1..]); // lower 3 bytes
    } else {
        payload.extend_from_slice(&body_len.to_be_bytes());
    }
    payload.push(hdr_chunks);
    payload.push(hdr_idx);
    payload.extend_from_slice(hdr_chunk);

    let header = HeaderV3 {
        packet_type: PacketTypeV3::RespHead,
        flags,
        message_id,
        seq: 0,
        seq_total: seq_total_body,
        payload_len: payload.len() as u16,
    };
    finalize_packet(&header, &payload, psk, true)
}

pub fn encode_resp_head_cont_v3(
    hdr_chunk: &[u8],
    hdr_idx: u8,
    hdr_chunks: u8,
    flags: u8,
    message_id: u64,
    psk: &[u8],
) -> Result<Vec<u8>, AkariError> {
    let mut payload = Vec::with_capacity(2 + hdr_chunk.len());
    payload.push(hdr_chunks);
    payload.push(hdr_idx);
    payload.extend_from_slice(hdr_chunk);
    let header = HeaderV3 {
        packet_type: PacketTypeV3::RespHeadCont,
        flags,
        message_id,
        seq: 0,            // independent space
        seq_total: 0,      // unused
        payload_len: payload.len() as u16,
    };
    // 非暗号化でも per-packet HMAC を付ける（ヘッダ継続も欠損検知対象）
    finalize_packet(&header, &payload, psk, true)
}

pub fn encode_resp_body_v3(
    body_chunk: &[u8],
    seq: u16,
    seq_total: u16,
    flags: u8,
    message_id: u64,
    psk: &[u8],
) -> Result<Vec<u8>, AkariError> {
    let payload_len = body_chunk.len();
    let header = HeaderV3 {
        packet_type: PacketTypeV3::RespBody,
        flags,
        message_id,
        seq,
        seq_total,
        payload_len: payload_len as u16,
    };
    finalize_packet(&header, body_chunk, psk, true)
}

/// aggregate-tag 用。非暗号化を想定し、include_tag=false でパケット個別タグを付けない。
pub fn encode_resp_body_v3_agg(
    body_chunk: &[u8],
    seq: u16,
    seq_total: u16,
    flags: u8,
    message_id: u64,
    psk: &[u8],
    agg_tag: Option<&[u8]>,
) -> Result<Vec<u8>, AkariError> {
    let payload_len = body_chunk.len() + agg_tag.map(|t| t.len()).unwrap_or(0);
    let header = HeaderV3 {
        packet_type: PacketTypeV3::RespBody,
        flags,
        message_id,
        seq,
        seq_total,
        payload_len: payload_len as u16,
    };
    let mut payload = Vec::with_capacity(payload_len);
    payload.extend_from_slice(body_chunk);
    if let Some(tag) = agg_tag {
        payload.extend_from_slice(tag);
    }
    let include_tag = flags & FLAG_ENCRYPT != 0; // 暗号化時は従来どおり per-packet タグを付ける
    finalize_packet(&header, &payload, psk, include_tag)
}

// ------------ NACKs ------------
pub fn encode_nack_head_v3(bitmap: &[u8], message_id: u64, flags: u8, psk: &[u8]) -> Result<Vec<u8>, AkariError> {
    let mut payload = Vec::with_capacity(1 + bitmap.len());
    payload.push(bitmap.len() as u8);
    payload.extend_from_slice(bitmap);
    let header = HeaderV3 {
        packet_type: PacketTypeV3::NackHead,
        flags,
        message_id,
        seq: 0,
        seq_total: 1,
        payload_len: payload.len() as u16,
    };
    finalize_packet(&header, &payload, psk, true)
}

pub fn encode_nack_body_v3(bitmap: &[u8], message_id: u64, flags: u8, psk: &[u8]) -> Result<Vec<u8>, AkariError> {
    let mut payload = Vec::with_capacity(1 + bitmap.len());
    payload.push(bitmap.len() as u8);
    payload.extend_from_slice(bitmap);
    let header = HeaderV3 {
        packet_type: PacketTypeV3::NackBody,
        flags,
        message_id,
        seq: 0,
        seq_total: 1,
        payload_len: payload.len() as u16,
    };
    finalize_packet(&header, &payload, psk, true)
}

// ------------ Error ------------
pub fn encode_error_v3(message: &str, code: u8, http_status: u16, message_id: u64, flags: u8, psk: &[u8]) -> Result<Vec<u8>, AkariError> {
    let msg_bytes = message.as_bytes();
    let payload_len = 1 + 2 + msg_bytes.len();
    let mut payload = Vec::with_capacity(payload_len);
    payload.push(code);
    payload.extend_from_slice(&http_status.to_be_bytes());
    payload.extend_from_slice(msg_bytes);
    let header = HeaderV3 {
        packet_type: PacketTypeV3::Error,
        flags,
        message_id,
        seq: 0,
        seq_total: 1,
        payload_len: payload_len as u16,
    };
    finalize_packet(&header, &payload, psk, true)
}

// helper to compute max chunk size given MTU (payload part only)
pub fn max_body_chunk_len(mtu: usize, header_len: usize) -> usize {
    // mtu >= header + payload + tag; tag fixed 16B
    mtu.saturating_sub(header_len + TAG_LEN)
}
