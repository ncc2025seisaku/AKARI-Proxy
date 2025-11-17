use crate::error::AkariError;
use std::convert::{TryFrom, TryInto};

pub const HEADER_LEN: usize = 24;
pub const CURRENT_VERSION: u8 = 0x01;
const MAGIC: [u8; 2] = *b"AK";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MessageType {
    Req = 0,
    Resp = 1,
    Error = 2,
}

impl TryFrom<u8> for MessageType {
    type Error = AkariError;

    fn try_from(value: u8) -> Result<Self, <MessageType as TryFrom<u8>>::Error> {
        match value {
            0 => Ok(MessageType::Req),
            1 => Ok(MessageType::Resp),
            2 => Ok(MessageType::Error),
            other => Err(AkariError::UnknownMessageType(other)),
        }
    }
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
        if version != CURRENT_VERSION {
            return Err(AkariError::UnsupportedVersion(version));
        }

        let message_type = MessageType::try_from(bytes[3])?;
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
