use crate::aead::decrypt_payload_v3;
use crate::error::AkariError;
use crate::hmac::{compute_tag, TAG_LEN};
use crate::header_v3::{HeaderV3, PacketTypeV3};
use crate::payload::{
    ErrorPayload, NackPayloadV3, ParsedPacketV3, PayloadV3, RequestMethod, RequestPayload, RespBodyPayloadV3,
    RespHeadPayloadV3,
};
use std::convert::TryInto;

/// Request payload overhead: method(1) + url_len(2) + hdr_len(2)
const REQUEST_OVERHEAD: usize = 1 + 2 + 2;
/// Offset where URL starts in request payload
const REQUEST_PAYLOAD_OFFSET: usize = 5;
/// Minimum length for RespHead payload: status_code(2) + body_len(at least 3)
const RESP_HEAD_MIN_LEN: usize = 4;
/// Minimum length for RespHeadCont payload: hdr_chunks(1) + hdr_idx(1)
const RESP_HEAD_CONT_MIN_LEN: usize = 2;
/// Minimum length for Error payload: code(1) + http_status(2)
const ERROR_MIN_LEN: usize = 3;
/// Body length field offset in RespHead (short mode): status_code(2) + body_len(3)
const RESP_HEAD_OFFSET_SHORT: usize = 5;
/// Body length field offset in RespHead (full mode): status_code(2) + body_len(4)
const RESP_HEAD_OFFSET_FULL: usize = 6;

pub fn decode_packet_v3(datagram: &[u8], psk: &[u8]) -> Result<ParsedPacketV3, AkariError> {
    if datagram.len() < HeaderV3::FIXED_LEN {
        return Err(AkariError::InvalidPacketLength {
            expected: HeaderV3::FIXED_LEN,
            actual: datagram.len(),
        });
    }
    // header length is dynamic (short-id)
    let header = HeaderV3::from_bytes(datagram)?;
    let header_len = header.encoded_len();
    let encrypt = header.flags & crate::header_v3::FLAG_ENCRYPT != 0;
    let agg_mode = (header.flags & crate::header_v3::FLAG_AGG_TAG != 0) && (header.packet_type == PacketTypeV3::RespBody);
    
    // Encryption and aggregate-tag mode are incompatible.
    // Encryption requires per-packet AEAD authentication, which cannot be aggregated.
    if encrypt && agg_mode {
        return Err(AkariError::UnsupportedFlagCombination {
            flag1: "FLAG_ENCRYPT",
            flag2: "FLAG_AGG_TAG",
        });
    }
    
    let min_tag = if !encrypt && agg_mode { 0 } else { TAG_LEN };
    if datagram.len() < header_len + min_tag {
        return Err(AkariError::InvalidPacketLength {
            expected: header_len + min_tag,
            actual: datagram.len(),
        });
    }
    let payload_len = header.payload_len as usize;
    let expected_len = header_len
        + payload_len
        + if encrypt {
            TAG_LEN
        } else if agg_mode {
            0
        } else {
            TAG_LEN
        };
    if datagram.len() != expected_len {
        return Err(AkariError::InvalidPacketLength {
            expected: expected_len,
            actual: datagram.len(),
        });
    }
    let payload = &datagram[header_len..header_len + payload_len];
    let tag_bytes = if agg_mode { &[][..] } else { &datagram[header_len + payload_len..] };

    let header_bytes = &datagram[..header_len];
    let encrypt = header.flags & crate::header_v3::FLAG_ENCRYPT != 0;
    let plain_payload = if encrypt {
        decrypt_payload_v3(psk, &header, payload, tag_bytes, header_bytes)?
    } else if !agg_mode {
        let computed_tag = compute_tag(psk, &datagram[..header_len + payload_len])?;
        if computed_tag.as_slice() != tag_bytes {
            return Err(AkariError::HmacMismatch);
        }
        payload.to_vec()
    } else {
        // aggregate-tag モード（タグは後段で検証する）
        payload.to_vec()
    };

    let parsed_payload = decode_payload_v3(&header, &plain_payload)?;
    Ok(ParsedPacketV3 {
        header,
        payload: parsed_payload,
    })
}

fn parse_method(byte: u8) -> Result<RequestMethod, AkariError> {
    match byte {
        0 => Ok(RequestMethod::Get),
        1 => Ok(RequestMethod::Head),
        2 => Ok(RequestMethod::Post),
        other => Err(AkariError::UnsupportedMethod(other)),
    }
}

fn decode_payload_v3(header: &HeaderV3, payload: &[u8]) -> Result<PayloadV3, AkariError> {
    match header.packet_type {
        PacketTypeV3::Req => decode_request(payload),
        PacketTypeV3::RespHead => decode_resp_head(header, payload),
        PacketTypeV3::RespHeadCont => decode_resp_head_cont(payload),
        PacketTypeV3::RespBody => decode_resp_body(header, payload),
        PacketTypeV3::NackHead => decode_nack(payload).map(PayloadV3::NackHead),
        PacketTypeV3::NackBody => decode_nack(payload).map(PayloadV3::NackBody),
        PacketTypeV3::Error => decode_error(payload),
    }
}

fn decode_request(payload: &[u8]) -> Result<PayloadV3, AkariError> {
    if payload.len() < REQUEST_OVERHEAD {
        return Err(AkariError::MissingPayload);
    }
    let method = parse_method(payload[0])?;
    let url_len = u16::from_be_bytes(payload[1..3].try_into().unwrap()) as usize;
    let hdr_len = u16::from_be_bytes(payload[3..5].try_into().unwrap()) as usize;
    if payload.len() != REQUEST_OVERHEAD + url_len + hdr_len {
        return Err(AkariError::InvalidUrlLength {
            declared: url_len,
            available: payload.len() - REQUEST_OVERHEAD - hdr_len,
        });
    }
    let url = std::str::from_utf8(&payload[REQUEST_PAYLOAD_OFFSET..REQUEST_PAYLOAD_OFFSET + url_len]).map(|s| s.to_string())?;
    let headers = payload[REQUEST_PAYLOAD_OFFSET + url_len..].to_vec();
    Ok(PayloadV3::Request(RequestPayload { method, url, headers }))
}

fn decode_resp_head(header: &HeaderV3, payload: &[u8]) -> Result<PayloadV3, AkariError> {
    if payload.len() < RESP_HEAD_MIN_LEN {
        return Err(AkariError::MissingPayload);
    }
    let status_code = u16::from_be_bytes(payload[0..2].try_into().unwrap());
    let (body_len, offset_len) = if header.flags & crate::header_v3::FLAG_SHORT_LEN != 0 {
        let mut buf = [0u8; 4];
        buf[1..].copy_from_slice(&payload[2..RESP_HEAD_OFFSET_SHORT]); // 3 bytes
        (u32::from_be_bytes(buf), RESP_HEAD_OFFSET_SHORT)
    } else {
        (u32::from_be_bytes(payload[2..RESP_HEAD_OFFSET_FULL].try_into().unwrap()), RESP_HEAD_OFFSET_FULL)
    };
    if payload.len() < offset_len + 2 {
        return Err(AkariError::MissingPayload);
    }
    let hdr_chunks = payload[offset_len];
    let hdr_idx = payload[offset_len + 1];
    let header_block = payload[offset_len + 2..].to_vec();
    Ok(PayloadV3::RespHead(RespHeadPayloadV3 {
        status_code,
        body_len,
        hdr_chunks,
        hdr_idx,
        header_block,
        seq_total_body: header.seq_total,
    }))
}

fn decode_resp_head_cont(payload: &[u8]) -> Result<PayloadV3, AkariError> {
    if payload.len() < RESP_HEAD_CONT_MIN_LEN {
        return Err(AkariError::MissingPayload);
    }
    let hdr_chunks = payload[0];
    let hdr_idx = payload[1];
    let header_block = payload[2..].to_vec();
    Ok(PayloadV3::RespHeadCont {
        hdr_idx,
        hdr_chunks,
        header_block,
    })
}

fn decode_resp_body(header: &HeaderV3, payload: &[u8]) -> Result<PayloadV3, AkariError> {
    let agg_mode = header.flags & crate::header_v3::FLAG_AGG_TAG != 0;
    if agg_mode && header.seq_total > 0 && header.seq == header.seq_total - 1 {
        if payload.len() < TAG_LEN {
            return Err(AkariError::MissingPayload);
        }
        let split = payload.len() - TAG_LEN;
        Ok(PayloadV3::RespBody(RespBodyPayloadV3 {
            seq: header.seq,
            seq_total: header.seq_total,
            chunk: payload[..split].to_vec(),
            agg_tag: Some(payload[split..].to_vec()),
        }))
    } else {
        Ok(PayloadV3::RespBody(RespBodyPayloadV3 {
            seq: header.seq,
            seq_total: header.seq_total,
            chunk: payload.to_vec(),
            agg_tag: None,
        }))
    }
}

fn decode_nack(payload: &[u8]) -> Result<NackPayloadV3, AkariError> {
    if payload.is_empty() {
        return Err(AkariError::MissingPayload);
    }
    let bitmap_len = payload[0] as usize;
    if payload.len() != 1 + bitmap_len {
        return Err(AkariError::InvalidPacketLength {
            expected: 1 + bitmap_len,
            actual: payload.len(),
        });
    }
    Ok(NackPayloadV3 {
        bitmap: payload[1..].to_vec(),
    })
}

fn decode_error(payload: &[u8]) -> Result<PayloadV3, AkariError> {
    if payload.len() < ERROR_MIN_LEN {
        return Err(AkariError::MissingPayload);
    }
    let code = payload[0];
    let http_status = u16::from_be_bytes(payload[1..3].try_into().unwrap());
    let message = std::str::from_utf8(&payload[3..]).map(|s| s.to_string())?;
    Ok(PayloadV3::Error(ErrorPayload {
        error_code: code,
        http_status,
        message,
    }))
}
