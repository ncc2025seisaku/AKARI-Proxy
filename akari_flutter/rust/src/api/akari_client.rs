//! AKARI Client API for Flutter
//!
//! This module exposes the Rust AkariClient to Dart via flutter_rust_bridge.

use akari_udp_core::{
    AkariClient as RustAkariClient, ClientError, HttpResponse as RustHttpResponse,
    RequestConfig as RustRequestConfig, TransferStats as RustTransferStats,
};
use std::sync::Mutex;

/// Request configuration for AKARI-UDP client.
#[flutter_rust_bridge::frb(dart_metadata=("freezed"))]
pub struct AkariRequestConfig {
    pub timeout_ms: u64,
    pub max_nack_rounds: Option<u32>,
    pub initial_request_retries: u32,
    pub sock_timeout_ms: u64,
    pub first_seq_timeout_ms: u64,
    pub agg_tag: bool,
    pub short_id: bool,
}

impl Default for AkariRequestConfig {
    fn default() -> Self {
        Self {
            timeout_ms: 10000,
            max_nack_rounds: Some(3),
            initial_request_retries: 1,
            sock_timeout_ms: 1000,
            first_seq_timeout_ms: 500,
            agg_tag: true,
            short_id: false,
        }
    }
}

impl AkariRequestConfig {
    fn to_rust(&self) -> RustRequestConfig {
        RustRequestConfig {
            timeout_ms: self.timeout_ms,
            max_nack_rounds: self.max_nack_rounds,
            initial_request_retries: self.initial_request_retries,
            sock_timeout_ms: self.sock_timeout_ms,
            first_seq_timeout_ms: self.first_seq_timeout_ms,
            df: true,
            agg_tag: self.agg_tag,
            payload_max: None,
            short_id: self.short_id,
        }
    }
}

/// Transfer statistics from a completed request.
#[flutter_rust_bridge::frb(dart_metadata=("freezed"))]
pub struct AkariTransferStats {
    pub bytes_sent: u64,
    pub bytes_received: u64,
    pub nacks_sent: u32,
    pub request_retries: u32,
}

impl From<RustTransferStats> for AkariTransferStats {
    fn from(s: RustTransferStats) -> Self {
        Self {
            bytes_sent: s.bytes_sent,
            bytes_received: s.bytes_received,
            nacks_sent: s.nacks_sent,
            request_retries: s.request_retries,
        }
    }
}

/// HTTP response from the remote proxy.
#[flutter_rust_bridge::frb(dart_metadata=("freezed"))]
pub struct AkariHttpResponse {
    pub status_code: u16,
    pub headers: Vec<(String, String)>,
    pub body: Vec<u8>,
    pub stats: AkariTransferStats,
}

impl From<RustHttpResponse> for AkariHttpResponse {
    fn from(r: RustHttpResponse) -> Self {
        Self {
            status_code: r.status_code,
            headers: r.headers,
            body: r.body,
            stats: AkariTransferStats::from(r.stats),
        }
    }
}

/// AKARI-UDP v3 client for sending requests through the proxy.
pub struct AkariClient {
    inner: Mutex<RustAkariClient>,
    message_id_counter: std::sync::atomic::AtomicU64,
}

impl AkariClient {
    /// Create a new client connected to the remote proxy.
    pub fn new(host: String, port: u16, psk: Vec<u8>) -> Result<AkariClient, String> {
        let client = RustAkariClient::new(&host, port, &psk).map_err(|e| e.to_string())?;
        Ok(AkariClient {
            inner: Mutex::new(client),
            message_id_counter: std::sync::atomic::AtomicU64::new(1),
        })
    }

    /// Send an HTTP GET request and return the response.
    pub fn send_request(
        &self,
        url: String,
        config: AkariRequestConfig,
    ) -> Result<AkariHttpResponse, String> {
        let guard = self.inner.lock().map_err(|e| e.to_string())?;
        let rust_config = config.to_rust();
        let message_id = self
            .message_id_counter
            .fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        let timestamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs() as u32)
            .unwrap_or(0);

        guard
            .send_request(&url, "GET", &[], message_id, timestamp, &rust_config)
            .map(AkariHttpResponse::from)
            .map_err(|e| e.to_string())
    }

    /// Send an HTTP request with specified method.
    pub fn send_request_with_method(
        &self,
        url: String,
        method: String,
        config: AkariRequestConfig,
    ) -> Result<AkariHttpResponse, String> {
        let guard = self.inner.lock().map_err(|e| e.to_string())?;
        let rust_config = config.to_rust();
        let message_id = self
            .message_id_counter
            .fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        let timestamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs() as u32)
            .unwrap_or(0);

        guard
            .send_request(&url, &method, &[], message_id, timestamp, &rust_config)
            .map(AkariHttpResponse::from)
            .map_err(|e| e.to_string())
    }
}

/// Create a default request configuration.
#[flutter_rust_bridge::frb(sync)]
pub fn default_request_config() -> AkariRequestConfig {
    AkariRequestConfig::default()
}
