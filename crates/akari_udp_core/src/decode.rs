use crate::error::AkariError;
use crate::hmac::{compute_tag, TAG_LEN};
use crate::header::{Header, HEADER_LEN, MessageType};
use crate::payload::{ErrorPayload, Payload, ParsedPacket, RequestPayload, ResponseChunk};
use std::convert::TryInto;

const REQUEST_OVERHEAD: usize = 4;
const RESPONSE_FIRST_OVERHEAD: usize = 8;
const ERROR_OVERHEAD: usize = 8;

pub fn decode_packet(datagram: &[u8], psk: &[u8]) -> Result<ParsedPacket, AkariError> {
    if datagram.len() < HEADER_LEN + TAG_LEN {
        return Err(AkariError::InvalidPacketLength {
            expected: HEADER_LEN + TAG_LEN,
            actual: datagram.len(),
        });
    }

    let header = Header::from_bytes(&datagram[..HEADER_LEN])?;
    let payload_len = header.payload_len as usize;
    let expected_len = HEADER_LEN + payload_len + TAG_LEN;
    if datagram.len() != expected_len {
        return Err(AkariError::InvalidPacketLength {
            expected: expected_len,
            actual: datagram.len(),
        });
    }

    let payload_end = HEADER_LEN + payload_len;
    let payload = &datagram[HEADER_LEN..payload_end];

    let mut expected_tag = [0u8; TAG_LEN];
    expected_tag.copy_from_slice(&datagram[payload_end..payload_end + TAG_LEN]);
    let computed_tag = compute_tag(psk, &datagram[..payload_end])?;
    if computed_tag != expected_tag {
        return Err(AkariError::HmacMismatch);
    }

    let parsed_payload = decode_payload(&header, payload)?;
    Ok(ParsedPacket {
        header,
        payload: parsed_payload,
    })
}

fn decode_payload(header: &Header, payload: &[u8]) -> Result<Payload, AkariError> {
    match header.message_type {
        MessageType::Req => decode_request(payload),
        MessageType::Resp => decode_response(header, payload),
        MessageType::Error => decode_error(payload),
    }
}

fn decode_request(payload: &[u8]) -> Result<Payload, AkariError> {
    if payload.len() < REQUEST_OVERHEAD {
        return Err(AkariError::MissingPayload);
    }

    let method = payload[0];
    if method != 0 {
        return Err(AkariError::UnsupportedMethod(method));
    }

    let url_len = u16::from_be_bytes(payload[1..3].try_into().unwrap()) as usize;
    if payload.len() != REQUEST_OVERHEAD + url_len {
        return Err(AkariError::InvalidUrlLength {
            declared: url_len,
            available: payload.len() - REQUEST_OVERHEAD,
        });
    }

    let url = std::str::from_utf8(&payload[4..]).map(|s| s.to_string())?;
    Ok(Payload::Request(RequestPayload { url }))
}

fn decode_response(header: &Header, payload: &[u8]) -> Result<Payload, AkariError> {
    if header.seq == 0 {
        if payload.len() < RESPONSE_FIRST_OVERHEAD {
            return Err(AkariError::MissingPayload);
        }

        let status_code = u16::from_be_bytes(payload[0..2].try_into().unwrap());
        let body_len = u32::from_be_bytes(payload[4..8].try_into().unwrap());
        let chunk = payload[8..].to_vec();

        Ok(Payload::Response(ResponseChunk {
            seq: header.seq,
            seq_total: header.seq_total,
            is_first: true,
            status_code: Some(status_code),
            body_len: Some(body_len),
            chunk,
        }))
    } else {
        Ok(Payload::Response(ResponseChunk {
            seq: header.seq,
            seq_total: header.seq_total,
            is_first: false,
            status_code: None,
            body_len: None,
            chunk: payload.to_vec(),
        }))
    }
}

fn decode_error(payload: &[u8]) -> Result<Payload, AkariError> {
    if payload.len() < ERROR_OVERHEAD {
        return Err(AkariError::MissingPayload);
    }

    let error_code = payload[0];
    let http_status = u16::from_be_bytes(payload[2..4].try_into().unwrap());
    let msg_len = u16::from_be_bytes(payload[4..6].try_into().unwrap()) as usize;

    if payload.len() != ERROR_OVERHEAD + msg_len {
        return Err(AkariError::InvalidPacketLength {
            expected: ERROR_OVERHEAD + msg_len,
            actual: payload.len(),
        });
    }

    let message = std::str::from_utf8(&payload[8..]).map(|s| s.to_string())?;
    Ok(Payload::Error(ErrorPayload {
        error_code,
        http_status,
        message,
    }))
}
