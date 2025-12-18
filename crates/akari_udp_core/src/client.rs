//! High-level AKARI-UDP v3 client for sending requests and handling retransmission.
//!
//! This module provides `AkariClient` which encapsulates:
//! - UDP socket management
//! - Request encoding and sending
//! - Response accumulation from multiple packets
//! - NACK-based retransmission for missing headers/body chunks
//! - Timeout and retry logic
//! - Aggregate tag verification

use std::collections::HashMap;
use std::io;
use std::net::{SocketAddr, ToSocketAddrs, UdpSocket};
use std::time::{Duration, Instant};

use crate::decode_v3::decode_packet_v3;
use crate::encode_v3::{encode_nack_body_v3, encode_nack_head_v3, encode_request_v3};
use crate::header_v3::{FLAG_AGG_TAG, FLAG_SHORT_ID};
use crate::payload::{RequestMethod, RespBodyPayloadV3, RespHeadPayloadV3};
use crate::PayloadV3;

/// Configuration for a request.
#[derive(Debug, Clone)]
pub struct RequestConfig {
    /// Overall timeout in milliseconds. 0 means wait indefinitely.
    pub timeout_ms: u64,
    /// Maximum number of NACK rounds. None means unlimited.
    pub max_nack_rounds: Option<u32>,
    /// Number of initial request retries if no response is received.
    pub initial_request_retries: u32,
    /// Socket receive timeout in milliseconds.
    pub sock_timeout_ms: u64,
    /// Timeout for receiving the first sequence before retrying.
    pub first_seq_timeout_ms: u64,
    /// Enable DF (Don't Fragment) flag.
    pub df: bool,
    /// Enable aggregate tag verification.
    pub agg_tag: bool,
    /// Maximum payload size. None means default (1200).
    pub payload_max: Option<u32>,
    /// Enable short message ID (16-bit instead of 64-bit).
    pub short_id: bool,
}

impl Default for RequestConfig {
    fn default() -> Self {
        Self {
            timeout_ms: 10000,
            max_nack_rounds: Some(3),
            initial_request_retries: 1,
            sock_timeout_ms: 1000,
            first_seq_timeout_ms: 500,
            df: true,
            agg_tag: true,
            payload_max: None,
            short_id: false,
        }
    }
}

/// Transfer statistics for a completed request.
#[derive(Debug, Clone, Default)]
pub struct TransferStats {
    pub bytes_sent: u64,
    pub bytes_received: u64,
    pub nacks_sent: u32,
    pub request_retries: u32,
}

/// HTTP response from the remote proxy.
#[derive(Debug, Clone)]
pub struct HttpResponse {
    pub status_code: u16,
    pub headers: Vec<(String, String)>,
    pub body: Vec<u8>,
    pub stats: TransferStats,
}

/// Error type for client operations.
#[derive(Debug)]
pub enum ClientError {
    /// IO error (socket, etc.)
    Io(io::Error),
    /// Timeout waiting for response
    Timeout,
    /// Protocol error (decode failed, etc.)
    Protocol(String),
    /// Aggregate tag mismatch
    AggTagMismatch,
    /// Response incomplete
    Incomplete,
    /// Remote returned an error
    RemoteError { code: u8, message: String },
}

impl std::fmt::Display for ClientError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ClientError::Io(e) => write!(f, "IO error: {}", e),
            ClientError::Timeout => write!(f, "Request timed out"),
            ClientError::Protocol(msg) => write!(f, "Protocol error: {}", msg),
            ClientError::AggTagMismatch => write!(f, "Aggregate tag mismatch"),
            ClientError::Incomplete => write!(f, "Response incomplete"),
            ClientError::RemoteError { code, message } => {
                write!(f, "Remote error (code {}): {}", code, message)
            }
        }
    }
}

impl std::error::Error for ClientError {}

impl From<io::Error> for ClientError {
    fn from(e: io::Error) -> Self {
        ClientError::Io(e)
    }
}

/// Internal accumulator for response packets.
struct ResponseAccumulator {
    message_id: u64,
    /// Body chunks indexed by sequence number.
    body_chunks: HashMap<u16, Vec<u8>>,
    /// Total number of body chunks (seq_total).
    body_seq_total: Option<u16>,
    /// Status code from response head.
    status_code: Option<u16>,
    /// Body length from response head.
    body_len: Option<u32>,
    /// Header chunks indexed by hdr_idx.
    hdr_chunks: HashMap<u8, Vec<u8>>,
    /// Total number of header chunks.
    hdr_total: Option<u8>,
    /// Aggregate tag from the last body chunk.
    agg_tag: Option<Vec<u8>>,
}

impl ResponseAccumulator {
    fn new(message_id: u64) -> Self {
        Self {
            message_id,
            body_chunks: HashMap::new(),
            body_seq_total: None,
            status_code: None,
            body_len: None,
            hdr_chunks: HashMap::new(),
            hdr_total: None,
            agg_tag: None,
        }
    }

    fn add_head(&mut self, payload: &RespHeadPayloadV3) {
        self.status_code = Some(payload.status_code);
        self.body_len = Some(payload.body_len);
        self.body_seq_total = Some(payload.seq_total_body);
        self.hdr_total = Some(payload.hdr_chunks);
        self.hdr_chunks
            .insert(payload.hdr_idx, payload.header_block.clone());
    }

    fn add_head_cont(&mut self, hdr_idx: u8, hdr_chunks: u8, header_block: Vec<u8>) {
        self.hdr_total = Some(hdr_chunks);
        self.hdr_chunks.insert(hdr_idx, header_block);
    }

    fn add_body(&mut self, payload: &RespBodyPayloadV3, seq_total_from_header: Option<u16>) {
        self.body_chunks.insert(payload.seq, payload.chunk.clone());
        // Use seq_total from payload (always present in v3), or fallback to header
        if payload.seq_total > 0 {
            self.body_seq_total = Some(payload.seq_total);
        } else if let Some(st) = seq_total_from_header {
            self.body_seq_total = Some(st);
        }
        if let Some(tag) = &payload.agg_tag {
            self.agg_tag = Some(tag.clone());
        }
    }

    fn header_complete(&self) -> bool {
        match self.hdr_total {
            Some(total) => self.hdr_chunks.len() >= total as usize,
            None => false,
        }
    }

    fn body_complete(&self) -> bool {
        match self.body_seq_total {
            Some(total) => self.body_chunks.len() >= total as usize,
            None => false,
        }
    }

    fn missing_header_indices(&self) -> Vec<u8> {
        match self.hdr_total {
            Some(total) => (0..total).filter(|i| !self.hdr_chunks.contains_key(i)).collect(),
            None => vec![],
        }
    }

    fn missing_body_seqs(&self) -> Vec<u16> {
        match self.body_seq_total {
            Some(total) => (0..total)
                .filter(|i| !self.body_chunks.contains_key(i))
                .collect(),
            None => vec![],
        }
    }

    fn assemble_headers(&self) -> Option<Vec<(String, String)>> {
        if !self.header_complete() {
            return None;
        }
        let mut indices: Vec<_> = self.hdr_chunks.keys().copied().collect();
        indices.sort();
        let mut combined = Vec::new();
        for idx in indices {
            if let Some(chunk) = self.hdr_chunks.get(&idx) {
                combined.extend_from_slice(chunk);
            }
        }
        Some(decode_header_block(&combined))
    }

    fn assemble_body(&self) -> Option<Vec<u8>> {
        if !self.body_complete() {
            return None;
        }
        let mut seqs: Vec<_> = self.body_chunks.keys().copied().collect();
        seqs.sort();
        let mut body = Vec::new();
        for seq in seqs {
            if let Some(chunk) = self.body_chunks.get(&seq) {
                body.extend_from_slice(chunk);
            }
        }
        Some(body)
    }
}

/// Static header ID mapping (same as Python version).
const STATIC_HEADER_IDS: &[(u8, &str)] = &[
    (1, "content-type"),
    (2, "content-length"),
    (3, "cache-control"),
    (4, "etag"),
    (5, "last-modified"),
    (6, "date"),
    (7, "server"),
    (8, "content-encoding"),
    (9, "accept-ranges"),
    (10, "set-cookie"),
    (11, "location"),
];

fn get_header_name(id: u8) -> String {
    STATIC_HEADER_IDS
        .iter()
        .find(|(i, _)| *i == id)
        .map(|(_, name)| name.to_string())
        .unwrap_or_else(|| format!("x-unknown-{}", id))
}

/// Decode header block into key-value pairs.
fn decode_header_block(block: &[u8]) -> Vec<(String, String)> {
    let mut headers = Vec::new();
    let mut pos = 0;
    while pos < block.len() {
        let hid = block[pos];
        pos += 1;
        if hid == 0 {
            // Literal name
            if pos >= block.len() {
                break;
            }
            let name_len = block[pos] as usize;
            pos += 1;
            if pos + name_len > block.len() {
                break;
            }
            let name = String::from_utf8_lossy(&block[pos..pos + name_len]).to_string();
            pos += name_len;
            if pos + 2 > block.len() {
                break;
            }
            let val_len = u16::from_be_bytes([block[pos], block[pos + 1]]) as usize;
            pos += 2;
            if pos + val_len > block.len() {
                break;
            }
            let value = String::from_utf8_lossy(&block[pos..pos + val_len]).to_string();
            pos += val_len;
            headers.push((name, value));
        } else {
            // Static header ID
            if pos + 2 > block.len() {
                break;
            }
            let val_len = u16::from_be_bytes([block[pos], block[pos + 1]]) as usize;
            pos += 2;
            if pos + val_len > block.len() {
                break;
            }
            let value = String::from_utf8_lossy(&block[pos..pos + val_len]).to_string();
            pos += val_len;
            headers.push((get_header_name(hid), value));
        }
    }
    headers
}

/// Build a bitmap from a list of missing sequence numbers.
fn build_missing_bitmap(missing: &[u16]) -> Vec<u8> {
    if missing.is_empty() {
        return vec![];
    }
    let max_seq = *missing.iter().max().unwrap();
    let length = (max_seq / 8) as usize + 1;
    let mut bitmap = vec![0u8; length];
    for &seq in missing {
        let idx = (seq / 8) as usize;
        let bit = seq % 8;
        bitmap[idx] |= 1 << bit;
    }
    bitmap
}

/// Build a bitmap from a list of missing header indices.
fn build_missing_hdr_bitmap(missing: &[u8]) -> Vec<u8> {
    if missing.is_empty() {
        return vec![];
    }
    let max_idx = *missing.iter().max().unwrap();
    let length = (max_idx / 8) as usize + 1;
    let mut bitmap = vec![0u8; length];
    for &idx in missing {
        let byte_idx = (idx / 8) as usize;
        let bit = idx % 8;
        bitmap[byte_idx] |= 1 << bit;
    }
    bitmap
}

/// AKARI-UDP v3 client.
pub struct AkariClient {
    remote_addr: SocketAddr,
    psk: Vec<u8>,
    socket: UdpSocket,
    buffer_size: usize,
}

impl AkariClient {
    /// Create a new client connected to the remote proxy.
    pub fn new(remote_host: &str, remote_port: u16, psk: &[u8]) -> Result<Self, ClientError> {
        let addr_str = format!("{}:{}", remote_host, remote_port);
        let remote_addr = addr_str
            .to_socket_addrs()?
            .next()
            .ok_or_else(|| ClientError::Protocol(format!("Cannot resolve {}", addr_str)))?;

        let socket = UdpSocket::bind("0.0.0.0:0")?;
        socket.connect(&remote_addr)?;

        Ok(Self {
            remote_addr,
            psk: psk.to_vec(),
            socket,
            buffer_size: 65535,
        })
    }

    /// Send an HTTP request through the AKARI-UDP proxy.
    pub fn send_request(
        &self,
        url: &str,
        method: &str,
        _body: &[u8], // Currently unused, GET only
        message_id: u64,
        timestamp: u32,
        config: &RequestConfig,
    ) -> Result<HttpResponse, ClientError> {
        // Build request flags
        let mut flags = 0u8;
        if config.agg_tag {
            flags |= FLAG_AGG_TAG;
        }
        if config.short_id {
            flags |= FLAG_SHORT_ID;
        }

        // Parse method
        let req_method = match method.to_uppercase().as_str() {
            "GET" => RequestMethod::Get,
            "POST" => RequestMethod::Post,
            "HEAD" => RequestMethod::Head,
            _ => return Err(ClientError::Protocol(format!("Unsupported method: {}", method))),
        };

        // Encode request
        let datagram = encode_request_v3(req_method, url, &[], message_id, timestamp, flags, &self.psk)
            .map_err(|e| ClientError::Protocol(format!("Encode error: {:?}", e)))?;

        // Set socket timeout
        let sock_timeout = Duration::from_millis(config.sock_timeout_ms);
        self.socket.set_read_timeout(Some(sock_timeout))?;

        // Send request
        self.socket.send(&datagram)?;
        let mut stats = TransferStats {
            bytes_sent: datagram.len() as u64,
            ..Default::default()
        };

        let mut accumulator = ResponseAccumulator::new(message_id);
        let mut nacks_sent = 0u32;
        let mut req_retries_left = config.initial_request_retries;
        let start_time = Instant::now();
        let overall_timeout = if config.timeout_ms > 0 {
            Some(Duration::from_millis(config.timeout_ms))
        } else {
            None
        };

        let mut buffer = vec![0u8; self.buffer_size];
        let mut last_activity = Instant::now();

        loop {
            // Check overall timeout
            if let Some(timeout) = overall_timeout {
                if start_time.elapsed() >= timeout {
                    return Err(ClientError::Timeout);
                }
            }

            // Receive packet
            match self.socket.recv(&mut buffer) {
                Ok(len) => {
                    stats.bytes_received += len as u64;
                    last_activity = Instant::now();

                    // Decode packet
                    let parsed = match decode_packet_v3(&buffer[..len], &self.psk) {
                        Ok(p) => p,
                        Err(e) => {
                            // Skip invalid packets
                            continue;
                        }
                    };

                    // Check message ID
                    if parsed.header.message_id != message_id {
                        continue;
                    }

                    // Process by packet type
                    match parsed.payload {
                        PayloadV3::RespHead(ref head) => {
                            accumulator.add_head(head);
                        }
                        PayloadV3::RespHeadCont {
                            hdr_idx,
                            hdr_chunks,
                            ref header_block,
                        } => {
                            accumulator.add_head_cont(hdr_idx, hdr_chunks, header_block.clone());
                        }
                        PayloadV3::RespBody(ref body) => {
                            let seq_total = Some(parsed.header.seq_total);
                            accumulator.add_body(body, seq_total);

                            // Check if complete
                            if accumulator.body_complete() && accumulator.header_complete() {
                                break;
                            }

                            // Send NACK if this is the last expected chunk and we're missing some
                            if let Some(total) = accumulator.body_seq_total {
                                if body.seq == total - 1 {
                                    let can_nack = config
                                        .max_nack_rounds
                                        .map(|max| nacks_sent < max)
                                        .unwrap_or(true);
                                    if can_nack {
                                        let missing = accumulator.missing_body_seqs();
                                        if !missing.is_empty() {
                                            let bitmap = build_missing_bitmap(&missing);
                                            let nack = encode_nack_body_v3(&bitmap, message_id, flags, &self.psk)
                                                .map_err(|e| ClientError::Protocol(format!("NACK encode: {:?}", e)))?;
                                            self.socket.send(&nack)?;
                                            stats.bytes_sent += nack.len() as u64;
                                            nacks_sent += 1;
                                        }
                                    }
                                }
                            }
                        }
                        PayloadV3::Error(ref err) => {
                            return Err(ClientError::RemoteError {
                                code: err.error_code,
                                message: err.message.clone(),
                            });
                        }
                        _ => {
                            // Ignore other packet types (Req, Ack, Nack, etc.)
                        }
                    }
                }
                Err(ref e) if e.kind() == io::ErrorKind::WouldBlock || e.kind() == io::ErrorKind::TimedOut => {
                    // Socket timeout - check what to do
                    let elapsed = last_activity.elapsed();

                    // If no packets received yet, retry request
                    if accumulator.body_chunks.is_empty()
                        && accumulator.hdr_chunks.is_empty()
                        && accumulator.status_code.is_none()
                    {
                        if req_retries_left > 0 {
                            self.socket.send(&datagram)?;
                            stats.bytes_sent += datagram.len() as u64;
                            req_retries_left -= 1;
                            stats.request_retries += 1;
                            last_activity = Instant::now();
                            continue;
                        }
                    }

                    // Send NACK for missing headers
                    if accumulator.hdr_total.is_some() && !accumulator.header_complete() {
                        let can_nack = config
                            .max_nack_rounds
                            .map(|max| nacks_sent < max)
                            .unwrap_or(true);
                        if can_nack {
                            let missing = accumulator.missing_header_indices();
                            if !missing.is_empty() {
                                let bitmap = build_missing_hdr_bitmap(&missing);
                                let nack = encode_nack_head_v3(&bitmap, message_id, flags, &self.psk)
                                    .map_err(|e| ClientError::Protocol(format!("NACK head encode: {:?}", e)))?;
                                self.socket.send(&nack)?;
                                stats.bytes_sent += nack.len() as u64;
                                nacks_sent += 1;
                                last_activity = Instant::now();
                                continue;
                            }
                        }
                    }

                    // Send NACK for missing body chunks
                    if accumulator.body_seq_total.is_some() && !accumulator.body_complete() {
                        let can_nack = config
                            .max_nack_rounds
                            .map(|max| nacks_sent < max)
                            .unwrap_or(true);
                        if can_nack {
                            let missing = accumulator.missing_body_seqs();
                            if !missing.is_empty() {
                                let bitmap = build_missing_bitmap(&missing);
                                let nack = encode_nack_body_v3(&bitmap, message_id, flags, &self.psk)
                                    .map_err(|e| ClientError::Protocol(format!("NACK body encode: {:?}", e)))?;
                                self.socket.send(&nack)?;
                                stats.bytes_sent += nack.len() as u64;
                                nacks_sent += 1;
                                last_activity = Instant::now();
                                continue;
                            }
                        }
                    }

                    // Check overall timeout
                    if let Some(timeout) = overall_timeout {
                        if start_time.elapsed() >= timeout {
                            return Err(ClientError::Timeout);
                        }
                    }
                }
                Err(e) => {
                    // Connection reset or other error - continue
                    if e.kind() == io::ErrorKind::ConnectionReset {
                        continue;
                    }
                    return Err(ClientError::Io(e));
                }
            }
        }

        // Assemble response
        stats.nacks_sent = nacks_sent;

        let headers = accumulator.assemble_headers().unwrap_or_default();
        let body = accumulator.assemble_body().ok_or(ClientError::Incomplete)?;
        let status_code = accumulator.status_code.ok_or(ClientError::Incomplete)?;

        // Verify aggregate tag if enabled
        if config.agg_tag {
            if let Some(received_tag) = &accumulator.agg_tag {
                use hmac::{Hmac, Mac};
                use sha2::Sha256;
                let mut mac = Hmac::<Sha256>::new_from_slice(&self.psk)
                    .map_err(|_| ClientError::Protocol("HMAC init failed".to_string()))?;
                mac.update(&body);
                let expected_tag = &mac.finalize().into_bytes()[..16];
                if received_tag.as_slice() != expected_tag {
                    return Err(ClientError::AggTagMismatch);
                }
            } else if accumulator.body_seq_total.map(|t| t > 0).unwrap_or(false) {
                // Aggregate tag expected but not received
                return Err(ClientError::AggTagMismatch);
            }
        }

        Ok(HttpResponse {
            status_code,
            headers,
            body,
            stats,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_decode_header_block_static() {
        // Header ID 1 (content-type) with value "text/html"
        let block = [0x01, 0x00, 0x09, b't', b'e', b'x', b't', b'/', b'h', b't', b'm', b'l'];
        let headers = decode_header_block(&block);
        assert_eq!(headers.len(), 1);
        assert_eq!(headers[0].0, "content-type");
        assert_eq!(headers[0].1, "text/html");
    }

    #[test]
    fn test_decode_header_block_literal() {
        // Literal name "x-custom" with value "foo"
        let block = [
            0x00, 0x08, b'x', b'-', b'c', b'u', b's', b't', b'o', b'm', 0x00, 0x03, b'f', b'o', b'o',
        ];
        let headers = decode_header_block(&block);
        assert_eq!(headers.len(), 1);
        assert_eq!(headers[0].0, "x-custom");
        assert_eq!(headers[0].1, "foo");
    }

    #[test]
    fn test_build_missing_bitmap() {
        let missing = vec![0u16, 2, 5];
        let bitmap = build_missing_bitmap(&missing);
        // bit 0, 2, 5 set = 0b00100101 = 0x25
        assert_eq!(bitmap, vec![0x25]);
    }

    #[test]
    fn test_build_missing_bitmap_multi_byte() {
        let missing = vec![0u16, 8, 15];
        let bitmap = build_missing_bitmap(&missing);
        // byte 0: bit 0 = 0x01
        // byte 1: bit 0 (seq 8), bit 7 (seq 15) = 0x81
        assert_eq!(bitmap, vec![0x01, 0x81]);
    }
}
