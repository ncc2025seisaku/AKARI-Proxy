use crate::error::AkariError;
use crate::hmac::{compute_tag, TAG_LEN};
use crate::header::{Header, MessageType, CURRENT_VERSION, HEADER_LEN};
const MAX_PAYLOAD: usize = u16::MAX as usize;
const REQUEST_OVERHEAD: usize = 4;
const RESPONSE_FIRST_OVERHEAD: usize = 8;
const ERROR_OVERHEAD: usize = 8;

fn finalize_packet(header: &Header, payload: &[u8], psk: &[u8]) -> Result<Vec<u8>, AkariError> {
    if payload.len() != header.payload_len as usize {
        return Err(AkariError::InvalidPacketLength {
            expected: header.payload_len as usize,
            actual: payload.len(),
        });
    }

    let mut buffer = Vec::with_capacity(HEADER_LEN + payload.len() + TAG_LEN);
    buffer.extend_from_slice(&header.to_bytes());
    buffer.extend_from_slice(payload);
    let tag = compute_tag(psk, &buffer)?;
    buffer.extend_from_slice(&tag);
    Ok(buffer)
}

fn ensure_payload_size(total: usize) -> Result<usize, AkariError> {
    if total > MAX_PAYLOAD {
        Err(AkariError::PayloadTooLarge(total))
    } else {
        Ok(total)
    }
}

pub fn encode_request(
    url: &str,
    message_id: u64,
    timestamp: u32,
    psk: &[u8],
) -> Result<Vec<u8>, AkariError> {
    let url_bytes = url.as_bytes();
    let payload_len = ensure_payload_size(REQUEST_OVERHEAD + url_bytes.len())?;
    let header = Header {
        version: CURRENT_VERSION,
        message_type: MessageType::Req,
        flags: 0,
        reserved: 0,
        message_id,
        seq: 0,
        seq_total: 1,
        payload_len: payload_len as u16,
        timestamp,
    };

    let mut payload = Vec::with_capacity(payload_len);
    payload.push(0);
    payload.extend_from_slice(&(url_bytes.len() as u16).to_be_bytes());
    payload.push(0);
    payload.extend_from_slice(url_bytes);

    finalize_packet(&header, &payload, psk)
}

pub fn encode_response_first_chunk(
    status_code: u16,
    body_len: u32,
    body_chunk: &[u8],
    message_id: u64,
    seq_total: u16,
    timestamp: u32,
    psk: &[u8],
) -> Result<Vec<u8>, AkariError> {
    let payload_len = ensure_payload_size(RESPONSE_FIRST_OVERHEAD + body_chunk.len())?;
    let header = Header {
        version: CURRENT_VERSION,
        message_type: MessageType::Resp,
        flags: 0,
        reserved: 0,
        message_id,
        seq: 0,
        seq_total,
        payload_len: payload_len as u16,
        timestamp,
    };

    let mut payload = Vec::with_capacity(payload_len);
    payload.extend_from_slice(&status_code.to_be_bytes());
    payload.extend_from_slice(&0u16.to_be_bytes());
    payload.extend_from_slice(&body_len.to_be_bytes());
    payload.extend_from_slice(body_chunk);

    finalize_packet(&header, &payload, psk)
}

pub fn encode_response_chunk(
    body_chunk: &[u8],
    message_id: u64,
    seq: u16,
    seq_total: u16,
    timestamp: u32,
    psk: &[u8],
) -> Result<Vec<u8>, AkariError> {
    let payload_len = ensure_payload_size(body_chunk.len())?;
    let header = Header {
        version: CURRENT_VERSION,
        message_type: MessageType::Resp,
        flags: 0,
        reserved: 0,
        message_id,
        seq,
        seq_total,
        payload_len: payload_len as u16,
        timestamp,
    };

    finalize_packet(&header, body_chunk, psk)
}

pub fn encode_error(
    error_code: u8,
    http_status: u16,
    message: &str,
    message_id: u64,
    timestamp: u32,
    psk: &[u8],
) -> Result<Vec<u8>, AkariError> {
    let msg_bytes = message.as_bytes();
    let payload_len = ensure_payload_size(ERROR_OVERHEAD + msg_bytes.len())?;
    let header = Header {
        version: CURRENT_VERSION,
        message_type: MessageType::Error,
        flags: 0,
        reserved: 0,
        message_id,
        seq: 0,
        seq_total: 1,
        payload_len: payload_len as u16,
        timestamp,
    };

    let mut payload = Vec::with_capacity(payload_len);
    payload.push(error_code);
    payload.push(0);
    payload.extend_from_slice(&http_status.to_be_bytes());
    payload.extend_from_slice(&(msg_bytes.len() as u16).to_be_bytes());
    payload.extend_from_slice(&0u16.to_be_bytes());
    payload.extend_from_slice(msg_bytes);

    finalize_packet(&header, &payload, psk)
}
