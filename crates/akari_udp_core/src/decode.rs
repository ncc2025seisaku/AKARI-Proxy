use crate::error::AkariError;
use crate::hmac::{compute_tag, TAG_LEN};
use crate::header::{Header, MessageType, HEADER_LEN, VERSION_V1};
use crate::payload::{
    AckPayload, ErrorPayload, NackPayload, Payload, ParsedPacket, RequestMethod, RequestPayload, ResponseChunk,
};
use std::convert::TryInto;
#[cfg(feature = "debug-log")]
use tracing::debug;

const REQUEST_V1_OVERHEAD: usize = 4; // method + url_len + reserved
const REQUEST_V2_OVERHEAD: usize = 5; // method + url_len + opt_hdr_len
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
    #[cfg(feature = "debug-log")]
    debug!(
        "decode_packet ver={} type={:?} message_id={} seq={}/{} payload_len={} total_len={}",
        header.version,
        header.message_type,
        header.message_id,
        header.seq,
        header.seq_total,
        header.payload_len,
        datagram.len()
    );
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
        MessageType::Req => decode_request(header, payload),
        MessageType::Resp => decode_response(header, payload),
        MessageType::Ack => decode_ack(payload),
        MessageType::Nack => decode_nack(payload),
        MessageType::Error => decode_error(payload),
    }
}

fn parse_method(byte: u8) -> Result<RequestMethod, AkariError> {
    match byte {
        0 => Ok(RequestMethod::Get),
        1 => Ok(RequestMethod::Head),
        2 => Ok(RequestMethod::Post),
        other => Err(AkariError::UnsupportedMethod(other)),
    }
}

fn decode_request(header: &Header, payload: &[u8]) -> Result<Payload, AkariError> {
    if header.version == VERSION_V1 {
        if payload.len() < REQUEST_V1_OVERHEAD {
            return Err(AkariError::MissingPayload);
        }
        let method = parse_method(payload[0])?;
        if method != RequestMethod::Get {
            return Err(AkariError::UnsupportedMethod(payload[0]));
        }
        let url_len = u16::from_be_bytes(payload[1..3].try_into().unwrap()) as usize;
        if payload.len() != REQUEST_V1_OVERHEAD + url_len {
            return Err(AkariError::InvalidUrlLength {
                declared: url_len,
                available: payload.len() - REQUEST_V1_OVERHEAD,
            });
        }
        let url = std::str::from_utf8(&payload[4..]).map(|s| s.to_string())?;
        Ok(Payload::Request(RequestPayload {
            method,
            url,
            headers: Vec::new(),
        }))
    } else {
        if payload.len() < REQUEST_V2_OVERHEAD {
            return Err(AkariError::MissingPayload);
        }
        let method = parse_method(payload[0])?;
        let url_len = u16::from_be_bytes(payload[1..3].try_into().unwrap()) as usize;
        let hdr_len = u16::from_be_bytes(payload[3..5].try_into().unwrap()) as usize;
        if payload.len() != REQUEST_V2_OVERHEAD + url_len + hdr_len {
            return Err(AkariError::InvalidUrlLength {
                declared: url_len,
                available: payload.len() - REQUEST_V2_OVERHEAD - hdr_len,
            });
        }
        let url = std::str::from_utf8(&payload[5..5 + url_len]).map(|s| s.to_string())?;
        let headers = payload[5 + url_len..].to_vec();
        Ok(Payload::Request(RequestPayload { method, url, headers }))
    }
}

fn decode_response(header: &Header, payload: &[u8]) -> Result<Payload, AkariError> {
    if header.seq == 0 {
        if payload.len() < RESPONSE_FIRST_OVERHEAD {
            return Err(AkariError::MissingPayload);
        }

        let status_code = u16::from_be_bytes(payload[0..2].try_into().unwrap());
        let hdr_len = if header.version == VERSION_V1 {
            0usize // v1 has reserved(2) then body_len(4)
        } else {
            u16::from_be_bytes(payload[2..4].try_into().unwrap()) as usize
        };

        let body_len = u32::from_be_bytes(payload[4..8].try_into().unwrap());
        let header_block = if header.version == VERSION_V1 || hdr_len == 0 {
            None
        } else {
            let start = 8;
            let end = 8 + hdr_len;
            if payload.len() < end {
                return Err(AkariError::MissingPayload);
            }
            Some(payload[start..end].to_vec())
        };

        let body_start = 8 + hdr_len;
        if payload.len() < body_start {
            return Err(AkariError::MissingPayload);
        }
        let chunk = payload[body_start..].to_vec();

        Ok(Payload::Response(ResponseChunk {
            seq: header.seq,
            seq_total: header.seq_total,
            is_first: true,
            status_code: Some(status_code),
            body_len: Some(body_len),
            headers: header_block,
            chunk,
        }))
    } else {
        Ok(Payload::Response(ResponseChunk {
            seq: header.seq,
            seq_total: header.seq_total,
            is_first: false,
            status_code: None,
            body_len: None,
            headers: None,
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

fn decode_ack(payload: &[u8]) -> Result<Payload, AkariError> {
    if payload.len() != 2 {
        return Err(AkariError::InvalidPacketLength {
            expected: 2,
            actual: payload.len(),
        });
    }
    let first_lost_seq = u16::from_be_bytes(payload[0..2].try_into().unwrap());
    Ok(Payload::Ack(AckPayload { first_lost_seq }))
}

fn decode_nack(payload: &[u8]) -> Result<Payload, AkariError> {
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
    let bitmap = payload[1..].to_vec();
    Ok(Payload::Nack(NackPayload { bitmap }))
}
