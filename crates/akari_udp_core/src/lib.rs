mod decode;
mod debug;
mod encode;
mod error;
mod header;
mod header_v3;
mod encode_v3;
mod decode_v3;
mod hmac;
mod aead;
mod payload;
mod client;

pub use crate::decode::decode_packet;
pub use crate::decode_v3::decode_packet_v3;
pub use crate::debug::debug_dump;
pub use crate::encode::{
    encode_ack_v2, encode_error, encode_error_v2, encode_nack_v2, encode_request, encode_request_v2,
    encode_response_chunk, encode_response_chunk_v2, encode_response_first_chunk, encode_response_first_chunk_v2,
};
pub use crate::encode_v3::{
    encode_error_v3, encode_nack_body_v3, encode_nack_head_v3, encode_request_v3, encode_resp_body_v3,
    encode_resp_head_cont_v3, encode_resp_head_v3,
    encode_resp_body_v3_agg,
};
pub use crate::payload::{ParsedPacketV3, PayloadV3};
pub use crate::error::AkariError;
pub use crate::header::{Header, MessageType, FLAG_ENCRYPT, VERSION_V1, VERSION_V2};
pub use crate::header_v3::{HeaderV3, PacketTypeV3, FLAG_AGG_TAG, FLAG_SHORT_ID, FLAG_SHORT_LEN, VERSION_V3};
pub use crate::payload::{
    AckPayload, ErrorPayload, NackPayload, ParsedPacket, Payload, RequestMethod, RequestPayload, ResponseChunk,
};
pub use crate::client::{AkariClient, ClientError, HttpResponse, RequestConfig, TransferStats};

#[cfg(test)]
mod tests {
    use crate::{
        decode_packet, decode_packet_v3, encode_ack_v2, encode_nack_v2, encode_request, encode_request_v2,
        encode_request_v3, encode_resp_body_v3, encode_resp_body_v3_agg, encode_resp_head_cont_v3,
        encode_resp_head_v3, encode_response_first_chunk_v2, AkariError, MessageType, PacketTypeV3, Payload, PayloadV3,
        RequestMethod, RequestPayload, FLAG_AGG_TAG, FLAG_ENCRYPT, FLAG_SHORT_ID, FLAG_SHORT_LEN,
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
    fn request_round_trip_v2_encrypted() {
        let message_id = 0xabcddcba11223344;
        let timestamp = 0x0f0e0d0c;
        let url = "https://example.net/secure";
        let flags = FLAG_ENCRYPT;
        let datagram =
            encode_request_v2(RequestMethod::Get, url, &[], message_id, timestamp, flags, PSK).expect("encode");
        let parsed = decode_packet(&datagram, PSK).expect("decode");
        match parsed.payload {
            Payload::Request(req) => {
                assert_eq!(req.url, url);
                assert_eq!(req.headers, Vec::<u8>::new());
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

    // ---------- v3 tests ----------

    fn build_headers(count: usize) -> Vec<u8> {
        // simple repeated header block
        let mut buf = Vec::new();
        for i in 0..count {
            buf.push(0); // literal name
            buf.push(3);
            buf.extend_from_slice(b"key");
            let val = format!("v{}", i);
            buf.extend_from_slice(&(val.len() as u16).to_be_bytes());
            buf.extend_from_slice(val.as_bytes());
        }
        buf
    }

    #[test]
    fn v3_request_round_trip_short_id() {
        let message_id = 0x1234; // short-id適用を確認
        let flags = FLAG_SHORT_ID;
        let url = "https://example.com/api";
        let hdr = b"\x01\x03abc";
        let dg = encode_request_v3(RequestMethod::Get, url, hdr, message_id, 0x55667788, flags, PSK).expect("encode");
        let parsed = decode_packet_v3(&dg, PSK).expect("decode");
        assert_eq!(parsed.header.packet_type, PacketTypeV3::Req);
        assert_eq!(parsed.header.flags & FLAG_SHORT_ID, FLAG_SHORT_ID);
        match parsed.payload {
            PayloadV3::Request(req) => {
                assert_eq!(req.url, url);
                assert_eq!(req.headers, hdr);
            }
            _ => panic!("unexpected payload"),
        }
    }

    #[test]
    fn v3_response_head_short_len_and_split() {
        let flags = FLAG_SHORT_LEN;
        let headers = build_headers(10); // 大きめヘッダで分割を誘発
        let body_len = 0x00FF_F0; // 24bit で収まる値
        let seq_total_body = 5;
        let head0 = encode_resp_head_v3(200, headers.len(), &headers[..16], body_len, 3, 0, seq_total_body, flags, 0x55, PSK)
            .expect("encode head");
        let head1 = encode_resp_head_cont_v3(&headers[16..32], 1, 3, flags, 0x55, PSK).expect("encode head cont");
        let head2 = encode_resp_head_cont_v3(&headers[32..], 2, 3, flags, 0x55, PSK).expect("encode head cont");

        for dg in [&head0, &head1, &head2] {
            let parsed = decode_packet_v3(dg, PSK).expect("decode");
            match parsed.payload {
                PayloadV3::RespHead(h) => {
                    assert_eq!(h.status_code, 200);
                    assert_eq!(h.body_len, body_len);
                    assert_eq!(h.hdr_chunks, 3);
                    assert_eq!(h.hdr_idx, 0);
                }
                PayloadV3::RespHeadCont { hdr_idx, hdr_chunks, header_block } => {
                    assert!(matches!(hdr_idx, 1 | 2));
                    assert_eq!(hdr_chunks, 3);
                    assert!(!header_block.is_empty());
                }
                _ => panic!("unexpected payload"),
            }
        }
    }

    #[test]
    fn v3_response_body_agg_tag_last_chunk() {
        let flags = FLAG_AGG_TAG;
        let body_chunks = [b"hello".as_ref(), b"world".as_ref()];
        let agg_tag = hmac_sha256_tag(&body_chunks.concat());

        let b0 = encode_resp_body_v3_agg(body_chunks[0], 0, 2, flags, 0xAA, PSK, None).expect("encode body0");
        let b1 =
            encode_resp_body_v3_agg(body_chunks[1], 1, 2, flags, 0xAA, PSK, Some(&agg_tag)).expect("encode body1");

        let p0 = decode_packet_v3(&b0, PSK).expect("decode body0");
        let p1 = decode_packet_v3(&b1, PSK).expect("decode body1");

        match p0.payload {
            PayloadV3::RespBody(b) => {
                assert_eq!(b.seq, 0);
                assert_eq!(b.agg_tag, None);
            }
            _ => panic!("unexpected payload"),
        }
        match p1.payload {
            PayloadV3::RespBody(b) => {
                assert_eq!(b.seq, 1);
                assert_eq!(b.agg_tag.as_deref(), Some(agg_tag.as_slice()));
            }
            _ => panic!("unexpected payload"),
        }
    }

    #[test]
    fn v3_response_body_per_packet_tag_when_encrypted() {
        let flags = FLAG_ENCRYPT;
        let chunk = b"encrypted-body";
        let dg = encode_resp_body_v3(chunk, 0, 1, flags, 0x66, PSK).expect("encode");
        let parsed = decode_packet_v3(&dg, PSK).expect("decode");
        match parsed.payload {
            PayloadV3::RespBody(b) => assert_eq!(b.chunk, chunk),
            _ => panic!("unexpected payload"),
        }
    }

    fn hmac_sha256_tag(body: &[u8]) -> Vec<u8> {
        use hmac::{Hmac, Mac};
        use sha2::Sha256;
        let mut mac = Hmac::<Sha256>::new_from_slice(PSK).unwrap();
        mac.update(body);
        mac.finalize().into_bytes()[..16].to_vec()
    }
}
