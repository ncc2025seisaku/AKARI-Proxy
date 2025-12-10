#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RequestMethod {
    Get = 0,
    Head = 1,
    Post = 2,
}

pub const ACK_PAYLOAD_LEN: usize = 2;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RequestPayload {
    pub method: RequestMethod,
    pub url: String,
    pub headers: Vec<u8>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ResponseChunk {
    pub seq: u16,
    pub seq_total: u16,
    pub is_first: bool,
    pub status_code: Option<u16>,
    pub body_len: Option<u32>,
    pub headers: Option<Vec<u8>>,
    pub chunk: Vec<u8>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ErrorPayload {
    pub error_code: u8,
    pub http_status: u16,
    pub message: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AckPayload {
    pub first_lost_seq: u16,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NackPayload {
    pub bitmap: Vec<u8>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Payload {
    Request(RequestPayload),
    Response(ResponseChunk),
    Ack(AckPayload),
    Nack(NackPayload),
    Error(ErrorPayload),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ParsedPacket {
    pub header: crate::header::Header,
    pub payload: Payload,
}

// ---------- v3 ----------
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RespHeadPayloadV3 {
    pub status_code: u16,
    pub body_len: u32,
    pub hdr_chunks: u8,
    pub hdr_idx: u8,
    pub header_block: Vec<u8>,
    pub seq_total_body: u16,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RespBodyPayloadV3 {
    pub seq: u16,
    pub seq_total: u16,
    pub chunk: Vec<u8>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NackPayloadV3 {
    pub bitmap: Vec<u8>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PayloadV3 {
    Request(RequestPayload),
    RespHead(RespHeadPayloadV3),
    RespHeadCont { hdr_idx: u8, hdr_chunks: u8, header_block: Vec<u8> },
    RespBody(RespBodyPayloadV3),
    NackHead(NackPayloadV3),
    NackBody(NackPayloadV3),
    Error(ErrorPayload),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ParsedPacketV3 {
    pub header: crate::header_v3::HeaderV3,
    pub payload: PayloadV3,
}
