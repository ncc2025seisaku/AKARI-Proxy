use crate::header::Header;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RequestPayload {
    pub url: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ResponseChunk {
    pub seq: u16,
    pub seq_total: u16,
    pub is_first: bool,
    pub status_code: Option<u16>,
    pub body_len: Option<u32>,
    pub chunk: Vec<u8>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ErrorPayload {
    pub error_code: u8,
    pub http_status: u16,
    pub message: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Payload {
    Request(RequestPayload),
    Response(ResponseChunk),
    Error(ErrorPayload),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ParsedPacket {
    pub header: Header,
    pub payload: Payload,
}
