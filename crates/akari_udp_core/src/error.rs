use thiserror::Error;

#[derive(Debug, Error)]
pub enum AkariError {
    #[error("invalid header length {0}")]
    InvalidHeaderLength(usize),
    #[error("invalid magic {0:?}")]
    InvalidMagic([u8; 2]),
    #[error("unsupported version {0}")]
    UnsupportedVersion(u8),
    #[error("unknown message type {0}")]
    UnknownMessageType(u8),
    #[error("payload size {0} exceeds u16::MAX")]
    PayloadTooLarge(usize),
    #[error("invalid packet length: expected {expected}, got {actual}")]
    InvalidPacketLength { expected: usize, actual: usize },
    #[error("invalid url length: declared {declared} but only {available} bytes available")]
    InvalidUrlLength { declared: usize, available: usize },
    #[error("invalid UTF-8 in payload: {0}")]
    InvalidUtf8(#[from] std::str::Utf8Error),
    #[error("format error: {0}")]
    Fmt(#[from] std::fmt::Error),
    #[error("HMAC mismatch")]
    HmacMismatch,
    #[error("invalid PSK")]
    InvalidPsk,
    #[error("unsupported method {0}")]
    UnsupportedMethod(u8),
    #[error("missing payload data")]
    MissingPayload,
}
