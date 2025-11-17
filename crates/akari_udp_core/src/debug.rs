use crate::decode::decode_packet;
use crate::header::HEADER_LEN;
use crate::hmac::TAG_LEN;
use crate::{AkariError, Payload};

/// デバッグ用にパケットを文字列整形して返す。
/// - Header: フィールド一覧
/// - Payload: 種別別の内容
/// - HMAC: 先頭16byteを hex 表記
pub fn debug_dump(datagram: &[u8], psk: &[u8]) -> Result<String, AkariError> {
    if datagram.len() < HEADER_LEN + TAG_LEN {
        return Err(AkariError::InvalidPacketLength {
            expected: HEADER_LEN + TAG_LEN,
            actual: datagram.len(),
        });
    }

    let parsed = decode_packet(datagram, psk)?;
    let (header_hex, hmac_hex) = {
        let header_hex = hex::encode(&datagram[..HEADER_LEN]);
        let hmac_hex = hex::encode(&datagram[datagram.len() - TAG_LEN..]);
        (header_hex, hmac_hex)
    };

    let mut out = String::new();
    use std::fmt::Write;
    writeln!(&mut out, "=== AKARI-UDP Packet Debug ===")?;
    writeln!(&mut out, "len: {} bytes", datagram.len())?;
    writeln!(&mut out, "header ({} bytes): {}", HEADER_LEN, header_hex)?;
    writeln!(&mut out, "payload_len: {}", parsed.header.payload_len)?;
    writeln!(&mut out, "hmac ({} bytes): {}", TAG_LEN, hmac_hex)?;
    writeln!(&mut out, "-- header fields --")?;
    writeln!(
        &mut out,
        "magic=AK version={} type={:?} flags={} message_id={} seq={}/{} payload_len={} timestamp={}",
        parsed.header.version,
        parsed.header.message_type,
        parsed.header.flags,
        parsed.header.message_id,
        parsed.header.seq,
        parsed.header.seq_total,
        parsed.header.payload_len,
        parsed.header.timestamp
    )?;

    writeln!(&mut out, "-- payload --")?;
    match &parsed.payload {
        Payload::Request(req) => {
            writeln!(&mut out, "Request: url={}", req.url)?;
        }
        Payload::Response(resp) => {
            writeln!(
                &mut out,
                "Response: seq={}/{} is_first={} status_code={:?} body_len={:?} chunk_len={}",
                resp.seq,
                resp.seq_total,
                resp.is_first,
                resp.status_code,
                resp.body_len,
                resp.chunk.len()
            )?;
        }
        Payload::Error(err) => {
            writeln!(
                &mut out,
                "Error: code={} http_status={} message=\"{}\"",
                err.error_code, err.http_status, err.message
            )?;
        }
    }

    Ok(out)
}
