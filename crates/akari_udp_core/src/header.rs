use crate::error::AkariError;
use std::convert::TryInto;

pub const HEADER_LEN: usize = 24;
pub const VERSION_V1: u8 = 0x01;
pub const VERSION_V2: u8 = 0x02;
const MAGIC: [u8; 2] = *b"AK";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MessageType {
    Req = 0,
    Resp = 1,
    Ack = 2,
    Nack = 3,
    Error = 4,
}

impl From<MessageType> for u8 {
    fn from(value: MessageType) -> Self {
        value as u8
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Header {
    pub version: u8,
    pub message_type: MessageType,
    pub flags: u8,
    pub reserved: u8,
    pub message_id: u64,
    pub seq: u16,
    pub seq_total: u16,
    pub payload_len: u16,
    pub timestamp: u32,
}

impl Header {
    pub fn to_bytes(&self) -> [u8; HEADER_LEN] {
        let mut buffer = [0u8; HEADER_LEN];
        buffer[0..2].copy_from_slice(&MAGIC);
        buffer[2] = self.version;
        buffer[3] = u8::from(self.message_type);
        buffer[4] = self.flags;
        buffer[5] = self.reserved;
        buffer[6..14].copy_from_slice(&self.message_id.to_be_bytes());
        buffer[14..16].copy_from_slice(&self.seq.to_be_bytes());
        buffer[16..18].copy_from_slice(&self.seq_total.to_be_bytes());
        buffer[18..20].copy_from_slice(&self.payload_len.to_be_bytes());
        buffer[20..24].copy_from_slice(&self.timestamp.to_be_bytes());
        buffer
    }

    pub fn from_bytes(bytes: &[u8]) -> Result<Self, AkariError> {
        if bytes.len() < HEADER_LEN {
            return Err(AkariError::InvalidHeaderLength(bytes.len()));
        }
        let mut magic = [0u8; 2];
        magic.copy_from_slice(&bytes[0..2]);
        if magic != MAGIC {
            return Err(AkariError::InvalidMagic(magic));
        }
        let version = bytes[2];
        if version != VERSION_V1 && version != VERSION_V2 {
            return Err(AkariError::UnsupportedVersion(version));
        }

        let message_type = match (version, bytes[3]) {
            (VERSION_V1, 0) => MessageType::Req,
            (VERSION_V1, 1) => MessageType::Resp,
            (VERSION_V1, 2) => MessageType::Error,
            // 一部古い実装が v1 で type=4 を送ることがあるため互換で許容する
            (VERSION_V1, 4) => MessageType::Error,
            (VERSION_V2, 0) => MessageType::Req,
            (VERSION_V2, 1) => MessageType::Resp,
            (VERSION_V2, 2) => MessageType::Ack,
            (VERSION_V2, 3) => MessageType::Nack,
            (VERSION_V2, 4) => MessageType::Error,
            (_, other) => return Err(AkariError::UnknownMessageType(other)),
        };
        let flags = bytes[4];
        let reserved = bytes[5];
        let message_id = u64::from_be_bytes(bytes[6..14].try_into().unwrap());
        let seq = u16::from_be_bytes(bytes[14..16].try_into().unwrap());
        let seq_total = u16::from_be_bytes(bytes[16..18].try_into().unwrap());
        let payload_len = u16::from_be_bytes(bytes[18..20].try_into().unwrap());
        let timestamp = u32::from_be_bytes(bytes[20..24].try_into().unwrap());

        Ok(Header {
            version,
            message_type,
            flags,
            reserved,
            message_id,
            seq,
            seq_total,
            payload_len,
            timestamp,
        })
    }
}
