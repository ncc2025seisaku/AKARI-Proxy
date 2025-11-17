mod decode;
mod encode;
mod error;
mod header;
mod hmac;
mod payload;

pub use crate::decode::decode_packet;
pub use crate::encode::{encode_error, encode_request, encode_response_chunk, encode_response_first_chunk};
pub use crate::error::AkariError;
pub use crate::header::{Header, MessageType};
pub use crate::payload::{ErrorPayload, Payload, ParsedPacket, RequestPayload, ResponseChunk};

#[cfg(test)]
mod tests {
    use crate::{decode_packet, encode_request, AkariError, MessageType, Payload, RequestPayload};

    const PSK: &[u8] = b"test-psk-0000-test";

    #[test]
    fn request_round_trip() {
        let message_id = 0x0102030405060708;
        let timestamp = 0x64636261;
        let url = "https://example.com/search?q=akari";
        let datagram = encode_request(url, message_id, timestamp, PSK).expect("encode");
        let parsed = decode_packet(&datagram, PSK).expect("decode");

        assert_eq!(parsed.header.message_type, MessageType::Req);
        assert_eq!(parsed.payload, Payload::Request(RequestPayload { url: url.to_string() }));
    }

    #[test]
    fn hmac_mismatch_rejected() {
        let message_id = 0xfeedfacecafebabe;
        let timestamp = 0x12345678;
        let url = "https://example.org/foo";
        let mut datagram = encode_request(url, message_id, timestamp, PSK).expect("encode");
        let len = datagram.len();
        datagram[len - 1] ^= 0xff;

        let err = decode_packet(&datagram, PSK).unwrap_err();
        assert!(matches!(err, AkariError::HmacMismatch));
    }
}
