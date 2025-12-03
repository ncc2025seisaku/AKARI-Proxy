use crate::aead::encrypt_payload;
use crate::error::AkariError;
use crate::hmac::{compute_tag, TAG_LEN};
use crate::header::{Header, MessageType, FLAG_ENCRYPT, HEADER_LEN, VERSION_V1, VERSION_V2};
use crate::payload::{RequestMethod, ACK_PAYLOAD_LEN};
#[cfg(feature = "debug-log")]
use tracing::debug;

const MAX_PAYLOAD: usize = u16::MAX as usize;
const REQUEST_V1_OVERHEAD: usize = 4; // method(1) + url_len(2) + reserved(1)
const REQUEST_V2_OVERHEAD: usize = 5; // method(1) + url_len(2) + opt_hdr_len(2)
const RESPONSE_FIRST_OVERHEAD: usize = 8; // status(2) + hdr_len/0x0000(2) + body_len(4)
const ERROR_OVERHEAD: usize = 8;

fn finalize_packet(header: &Header, payload: &[u8], psk: &[u8]) -> Result<Vec<u8>, AkariError> {
    if payload.len() != header.payload_len as usize {
        return Err(AkariError::InvalidPacketLength {
            expected: header.payload_len as usize,
            actual: payload.len(),
        });
    }

    #[cfg(feature = "debug-log")]
    debug!(
        "finalize_packet ver={} type={:?} message_id={} seq={}/{} payload_len={}",
        header.version, header.message_type, header.message_id, header.seq, header.seq_total, header.payload_len
    );

    let encrypt = header.flags & FLAG_ENCRYPT != 0;
    let mut buffer = Vec::with_capacity(HEADER_LEN + payload.len() + TAG_LEN);
    buffer.extend_from_slice(&header.to_bytes());
    if encrypt {
        let (ciphertext, tag) = encrypt_payload(psk, header, payload)?;
        buffer.extend_from_slice(&ciphertext);
        buffer.extend_from_slice(&tag);
    } else {
        buffer.extend_from_slice(payload);
        let tag = compute_tag(psk, &buffer)?;
        buffer.extend_from_slice(&tag);
    }
    Ok(buffer)
}

fn ensure_payload_size(total: usize) -> Result<usize, AkariError> {
    if total > MAX_PAYLOAD {
        Err(AkariError::PayloadTooLarge(total))
    } else {
        Ok(total)
    }
}

// ----------------------------
// v1 helpers (従来互換)
// ----------------------------

pub fn encode_request(
    url: &str,
    message_id: u64,
    timestamp: u32,
    psk: &[u8],
) -> Result<Vec<u8>, AkariError> {
    let url_bytes = url.as_bytes();
    let payload_len = ensure_payload_size(REQUEST_V1_OVERHEAD + url_bytes.len())?;
    let header = Header {
        version: VERSION_V1,
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
    payload.push(RequestMethod::Get as u8);
    payload.extend_from_slice(&(url_bytes.len() as u16).to_be_bytes());
    payload.push(0); // reserved
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
        version: VERSION_V1,
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
    payload.extend_from_slice(&0u16.to_be_bytes()); // reserved
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
        version: VERSION_V1,
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
        version: VERSION_V1,
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

// ----------------------------
// v2 helpers
// ----------------------------

pub fn encode_request_v2(
    method: RequestMethod,
    url: &str,
    header_block: &[u8],
    message_id: u64,
    timestamp: u32,
    flags: u8,
    psk: &[u8],
) -> Result<Vec<u8>, AkariError> {
    let url_bytes = url.as_bytes();
    let payload_len = ensure_payload_size(REQUEST_V2_OVERHEAD + url_bytes.len() + header_block.len())?;
    let header = Header {
        version: VERSION_V2,
        message_type: MessageType::Req,
        flags,
        reserved: 0,
        message_id,
        seq: 0,
        seq_total: 1,
        payload_len: payload_len as u16,
        timestamp,
    };

    let mut payload = Vec::with_capacity(payload_len);
    payload.push(method as u8);
    payload.extend_from_slice(&(url_bytes.len() as u16).to_be_bytes());
    payload.extend_from_slice(&(header_block.len() as u16).to_be_bytes());
    payload.extend_from_slice(url_bytes);
    payload.extend_from_slice(header_block);

    finalize_packet(&header, &payload, psk)
}

pub fn encode_response_first_chunk_v2(
    status_code: u16,
    body_len: u32,
    header_block: &[u8],
    body_chunk: &[u8],
    message_id: u64,
    seq_total: u16,
    flags: u8,
    timestamp: u32,
    psk: &[u8],
) -> Result<Vec<u8>, AkariError> {
    let payload_len = ensure_payload_size(RESPONSE_FIRST_OVERHEAD + header_block.len() + body_chunk.len())?;
    let header = Header {
        version: VERSION_V2,
        message_type: MessageType::Resp,
        flags,
        reserved: 0,
        message_id,
        seq: 0,
        seq_total,
        payload_len: payload_len as u16,
        timestamp,
    };

    let mut payload = Vec::with_capacity(payload_len);
    payload.extend_from_slice(&status_code.to_be_bytes());
    payload.extend_from_slice(&(header_block.len() as u16).to_be_bytes());
    payload.extend_from_slice(&body_len.to_be_bytes());
    payload.extend_from_slice(header_block);
    payload.extend_from_slice(body_chunk);

    finalize_packet(&header, &payload, psk)
}

pub fn encode_response_chunk_v2(
    body_chunk: &[u8],
    message_id: u64,
    seq: u16,
    seq_total: u16,
    flags: u8,
    timestamp: u32,
    psk: &[u8],
) -> Result<Vec<u8>, AkariError> {
    let payload_len = ensure_payload_size(body_chunk.len())?;
    let header = Header {
        version: VERSION_V2,
        message_type: MessageType::Resp,
        flags,
        reserved: 0,
        message_id,
        seq,
        seq_total,
        payload_len: payload_len as u16,
        timestamp,
    };

    finalize_packet(&header, body_chunk, psk)
}

pub fn encode_ack_v2(
    first_lost_seq: u16,
    message_id: u64,
    timestamp: u32,
    psk: &[u8],
) -> Result<Vec<u8>, AkariError> {
    let payload_len = ensure_payload_size(ACK_PAYLOAD_LEN)?;
    let header = Header {
        version: VERSION_V2,
        message_type: MessageType::Ack,
        flags: 0,
        reserved: 0,
        message_id,
        seq: 0,
        seq_total: 1,
        payload_len: payload_len as u16,
        timestamp,
    };

    let mut payload = Vec::with_capacity(payload_len);
    payload.extend_from_slice(&first_lost_seq.to_be_bytes());

    finalize_packet(&header, &payload, psk)
}

pub fn encode_nack_v2(
    bitmap: &[u8],
    message_id: u64,
    timestamp: u32,
    psk: &[u8],
) -> Result<Vec<u8>, AkariError> {
    let total = 1 + bitmap.len();
    let payload_len = ensure_payload_size(total)?;
    let header = Header {
        version: VERSION_V2,
        message_type: MessageType::Nack,
        flags: 0,
        reserved: 0,
        message_id,
        seq: 0,
        seq_total: 1,
        payload_len: payload_len as u16,
        timestamp,
    };
    let mut payload = Vec::with_capacity(payload_len);
    payload.push(bitmap.len() as u8);
    payload.extend_from_slice(bitmap);
    finalize_packet(&header, &payload, psk)
}

pub fn encode_error_v2(
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
        version: VERSION_V2,
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
