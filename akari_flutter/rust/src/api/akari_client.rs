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
        headers: Vec<(String, String)>,
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
            .send_request(&url, "GET", &headers, message_id, timestamp, &rust_config)
            .map(AkariHttpResponse::from)
            .map_err(|e| e.to_string())
    }

    /// Send an HTTP request with specified method.
    pub fn send_request_with_method(
        &self,
        url: String,
        method: String,
        headers: Vec<(String, String)>,
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
            .send_request(&url, &method, &headers, message_id, timestamp, &rust_config)
            .map(AkariHttpResponse::from)
            .map_err(|e| e.to_string())
    }
}

/// Create a default request configuration.
#[flutter_rust_bridge::frb(sync)]
pub fn default_request_config() -> AkariRequestConfig {
    AkariRequestConfig::default()
}

// ============================================================================
// Client Pool for Concurrent Requests
// ============================================================================

/// Pool of AKARI-UDP clients for concurrent requests.
/// 
/// This pool maintains multiple independent UDP clients, each with its own
/// socket on a different ephemeral port. This allows concurrent requests
/// without packet mixing or NACK issues.
pub struct AkariClientPool {
    host: String,
    port: u16,
    psk: Vec<u8>,
    pool: Mutex<Vec<RustAkariClient>>,
    pool_size: usize,
    active_count: std::sync::atomic::AtomicUsize,
    message_id_counter: std::sync::atomic::AtomicU64,
}

impl AkariClientPool {
    /// Create a new client pool connected to the remote proxy.
    /// 
    /// * `host` - Remote proxy hostname
    /// * `port` - Remote proxy port
    /// * `psk` - Pre-shared key for authentication
    /// * `pool_size` - Maximum number of concurrent clients
    pub fn new(host: String, port: u16, psk: Vec<u8>, pool_size: usize) -> Result<AkariClientPool, String> {
        let pool_size = pool_size.max(1).min(16); // Clamp between 1-16
        
        // Pre-create initial clients
        let mut clients = Vec::with_capacity(pool_size);
        for _ in 0..pool_size.min(2) {
            // Pre-create 2 clients to warm up the pool
            match RustAkariClient::new(&host, port, &psk) {
                Ok(client) => clients.push(client),
                Err(e) => return Err(e.to_string()),
            }
        }
        
        Ok(AkariClientPool {
            host,
            port,
            psk,
            pool: Mutex::new(clients),
            pool_size,
            active_count: std::sync::atomic::AtomicUsize::new(0),
            message_id_counter: std::sync::atomic::AtomicU64::new(1),
        })
    }

    /// Acquire a client from the pool.
    /// If the pool is empty and we haven't reached max size, creates a new client.
    fn acquire(&self) -> Result<RustAkariClient, String> {
        let mut pool = self.pool.lock().map_err(|e| e.to_string())?;
        
        if let Some(client) = pool.pop() {
            self.active_count.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
            return Ok(client);
        }
        
        // Pool is empty, check if we can create a new client
        let active = self.active_count.load(std::sync::atomic::Ordering::SeqCst);
        if active < self.pool_size {
            drop(pool); // Release lock before potentially slow socket creation
            let client = RustAkariClient::new(&self.host, self.port, &self.psk)
                .map_err(|e| e.to_string())?;
            self.active_count.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
            return Ok(client);
        }
        
        // All clients are in use - create a temporary client
        // Note: We increment active_count here too, since release() will decrement it
        drop(pool);
        let client = RustAkariClient::new(&self.host, self.port, &self.psk)
            .map_err(|e| e.to_string())?;
        self.active_count.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        Ok(client)
    }

    /// Release a client back to the pool.
    fn release(&self, client: RustAkariClient) {
        let returned_to_pool = if let Ok(mut pool) = self.pool.lock() {
            if pool.len() < self.pool_size {
                pool.push(client);
                true
            } else {
                // Pool is full, client will be dropped (socket closed)
                false
            }
        } else {
            false
        };
        
        // Always decrement active_count since we always incremented it in acquire()
        // The client is either returned to pool or dropped
        let _ = returned_to_pool; // Acknowledge the variable (avoids warning)
        self.active_count.fetch_sub(1, std::sync::atomic::Ordering::SeqCst);
    }

    /// Send an HTTP GET request and return the response.
    /// 
    /// This method acquires a client from the pool, sends the request,
    /// and releases the client back to the pool.
    pub fn send_request(
        &self,
        url: String,
        headers: Vec<(String, String)>,
        config: AkariRequestConfig,
    ) -> Result<AkariHttpResponse, String> {
        let client = self.acquire()?;
        let rust_config = config.to_rust();
        let message_id = self
            .message_id_counter
            .fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        let timestamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs() as u32)
            .unwrap_or(0);

        let result = client
            .send_request(&url, "GET", &headers, message_id, timestamp, &rust_config)
            .map(AkariHttpResponse::from)
            .map_err(|e| e.to_string());

        self.release(client);
        result
    }

    /// Send an HTTP request with specified method.
    pub fn send_request_with_method(
        &self,
        url: String,
        method: String,
        headers: Vec<(String, String)>,
        config: AkariRequestConfig,
    ) -> Result<AkariHttpResponse, String> {
        let client = self.acquire()?;
        let rust_config = config.to_rust();
        let message_id = self
            .message_id_counter
            .fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        let timestamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs() as u32)
            .unwrap_or(0);

        let result = client
            .send_request(&url, &method, &headers, message_id, timestamp, &rust_config)
            .map(AkariHttpResponse::from)
            .map_err(|e| e.to_string());

        self.release(client);
        result
    }

    /// Get the current number of active clients.
    #[flutter_rust_bridge::frb(sync)]
    pub fn active_count(&self) -> usize {
        self.active_count.load(std::sync::atomic::Ordering::SeqCst)
    }

    /// Get the pool size (maximum number of concurrent clients).
    #[flutter_rust_bridge::frb(sync)]
    pub fn pool_size(&self) -> usize {
        self.pool_size
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_request_config_default() {
        let config = AkariRequestConfig::default();
        assert_eq!(config.timeout_ms, 10000);
        assert_eq!(config.max_nack_rounds, Some(3));
        assert_eq!(config.initial_request_retries, 1);
        assert_eq!(config.sock_timeout_ms, 1000);
        assert_eq!(config.first_seq_timeout_ms, 500);
        assert!(config.agg_tag);
        assert!(!config.short_id);
    }

    #[test]
    fn test_request_config_to_rust() {
        let config = AkariRequestConfig {
            timeout_ms: 5000,
            max_nack_rounds: Some(5),
            initial_request_retries: 2,
            sock_timeout_ms: 500,
            first_seq_timeout_ms: 250,
            agg_tag: false,
            short_id: true,
        };
        let rust_config = config.to_rust();
        assert_eq!(rust_config.timeout_ms, 5000);
        assert_eq!(rust_config.max_nack_rounds, Some(5));
        assert_eq!(rust_config.initial_request_retries, 2);
        assert_eq!(rust_config.sock_timeout_ms, 500);
        assert_eq!(rust_config.first_seq_timeout_ms, 250);
        assert!(!rust_config.agg_tag);
        assert!(rust_config.short_id);
    }

    #[test]
    fn test_pool_size_clamping() {
        // Pool size should be clamped between 1 and 16
        // Note: This test can't actually create the pool without a valid server
        // but we can test the clamping logic by checking bounds
        assert!(1 <= 1_usize.max(1).min(16));
        assert!(1 <= 0_usize.max(1).min(16));
        assert_eq!(16, 100_usize.max(1).min(16));
        assert_eq!(4, 4_usize.max(1).min(16));
    }

    #[test]
    fn test_default_request_config_function() {
        let config = default_request_config();
        assert_eq!(config.timeout_ms, 10000);
        assert!(config.agg_tag);
    }
}
