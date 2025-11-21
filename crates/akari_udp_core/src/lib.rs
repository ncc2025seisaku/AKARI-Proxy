mod decode;
mod debug;
mod encode;
mod error;
mod header;
mod hmac;
mod payload;

pub use crate::decode::decode_packet;
pub use crate::debug::debug_dump;
pub use crate::encode::{
    encode_ack_v2, encode_error, encode_error_v2, encode_nack_v2, encode_request, encode_request_v2,
    encode_response_chunk, encode_response_chunk_v2, encode_response_first_chunk, encode_response_first_chunk_v2,
};
pub use crate::error::AkariError;
pub use crate::header::{Header, MessageType, VERSION_V1, VERSION_V2};
pub use crate::payload::{
    AckPayload, ErrorPayload, NackPayload, ParsedPacket, Payload, RequestMethod, RequestPayload, ResponseChunk,
};

#[cfg(test)]
mod tests {
    use crate::{
        decode_packet, encode_ack_v2, encode_nack_v2, encode_request, encode_request_v2, encode_response_first_chunk_v2,
        AkariError, MessageType, Payload, RequestMethod, RequestPayload,
    };

    const PSK: &[u8] = b"test-psk-0000-test";

    #[test]
    fn request_round_trip_v1() {
        let message_id = 0x0102030405060708;
        let timestamp = 0x64636261;
        let url = "https://example.com/search?q=akari";
        let datagram = encode_request(url, message_id, timestamp, PSK).expect("encode");
        let parsed = decode_packet(&datagram, PSK).expect("decode");

        assert_eq!(parsed.header.message_type, MessageType::Req);
        assert_eq!(
            parsed.payload,
            Payload::Request(RequestPayload {
                method: RequestMethod::Get,
                url: url.to_string(),
                headers: Vec::new()
            })
        );
    }

    #[test]
    fn request_round_trip_v2_with_headers() {
        let message_id = 0x0a0b0c0d0e0f1011;
        let timestamp = 0x01020304;
        let url = "https://example.com/index.html";
        let hdr = [0x01, 0x05, b't', b'e', b's', b't', b'/'];
        let datagram =
            encode_request_v2(RequestMethod::Get, url, &hdr, message_id, timestamp, 0x40, PSK).expect("encode");
        let parsed = decode_packet(&datagram, PSK).expect("decode");
        match parsed.payload {
            Payload::Request(req) => {
                assert_eq!(req.method, RequestMethod::Get);
                assert_eq!(req.url, url);
                assert_eq!(req.headers, hdr);
            }
            _ => panic!("unexpected payload"),
        }
    }

    #[test]
    fn ack_nack_round_trip_v2() {
        let datagram = encode_ack_v2(3, 0x33, 0x44, PSK).expect("encode ack");
        let parsed = decode_packet(&datagram, PSK).expect("decode");
        assert!(matches!(parsed.payload, Payload::Ack(_)));

        let bitmap = [0b0001_0100];
        let nack = encode_nack_v2(&bitmap, 0x55, 0x66, PSK).expect("encode nack");
        let parsed = decode_packet(&nack, PSK).expect("decode");
        match parsed.payload {
            Payload::Nack(n) => assert_eq!(n.bitmap, bitmap),
            _ => panic!("unexpected payload"),
        }
    }

    #[test]
    fn response_first_chunk_v2_contains_headers() {
        let hdr_block = b"hdr-block";
        let body0 = b"hello";
        let datagram = encode_response_first_chunk_v2(
            200,
            10,
            hdr_block,
            body0,
            0x99,
            2,
            0,
            0x77,
            PSK,
        )
        .expect("encode");
        let parsed = decode_packet(&datagram, PSK).expect("decode");
        match parsed.payload {
            Payload::Response(resp) => {
                assert_eq!(resp.headers.as_ref().unwrap(), hdr_block);
                assert_eq!(resp.chunk, body0);
                assert_eq!(resp.status_code, Some(200));
            }
            _ => panic!("unexpected payload"),
        }
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
