use crate::error::AkariError;
use std::convert::TryInto;

pub const VERSION_V3: u8 = 0x03;
pub const FLAG_ENCRYPT: u8 = 0x80; // reuse encrypt bit
pub const FLAG_AGG_TAG: u8 = 0x40; // aggregate tag (single tag per message)
pub const FLAG_SHORT_ID: u8 = 0x20; // message_id is 16bit when set
pub const FLAG_SHORT_LEN: u8 = 0x10; // body_len / hdr_len are 24bit when set

const MAGIC: [u8; 2] = *b"AK";

/// v3 packet types (より細分化された役割ごとのパケット)
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PacketTypeV3 {
    Req = 0,
    RespHead = 1,
    RespHeadCont = 2,
    RespBody = 3,
    NackHead = 4,
    NackBody = 5,
    Error = 6,
}

impl TryFrom<u8> for PacketTypeV3 {
    type Error = AkariError;

    fn try_from(value: u8) -> Result<Self, AkariError> {
        match value {
            0 => Ok(PacketTypeV3::Req),
            1 => Ok(PacketTypeV3::RespHead),
            2 => Ok(PacketTypeV3::RespHeadCont),
            3 => Ok(PacketTypeV3::RespBody),
            4 => Ok(PacketTypeV3::NackHead),
            5 => Ok(PacketTypeV3::NackBody),
            6 => Ok(PacketTypeV3::Error),
            other => Err(AkariError::UnknownMessageType(other)),
        }
    }
}

impl From<PacketTypeV3> for u8 {
    fn from(value: PacketTypeV3) -> Self {
        value as u8
    }
}

/// v3 ヘッダの共通部
///
/// short-id の場合 message_id は下位16bitのみ有効。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct HeaderV3 {
    pub packet_type: PacketTypeV3,
    pub flags: u8,
    pub message_id: u64,
    pub seq: u16,
    pub seq_total: u16,
    pub payload_len: u16,
}

impl HeaderV3 {
    pub const FIXED_LEN: usize = 2 /*magic*/ + 1 /*ver*/ + 1 /*type*/ + 1 /*flags*/ + 1 /*reserved*/ + 2 /*seq*/
        + 2 /*seq_total*/ + 2 /*payload_len*/;

    /// message_id 長は flags の short-id で 2 or 8 バイト
    pub fn encoded_len(&self) -> usize {
        let id_len = if self.flags & FLAG_SHORT_ID != 0 { 2 } else { 8 };
        Self::FIXED_LEN + id_len
    }

    pub fn to_bytes(&self) -> Vec<u8> {
        let mut buf = Vec::with_capacity(self.encoded_len());
        buf.extend_from_slice(&MAGIC);
        buf.push(VERSION_V3);
        buf.push(u8::from(self.packet_type));
        buf.push(self.flags);
        buf.push(0); // reserved
        let id_len = if self.flags & FLAG_SHORT_ID != 0 { 2 } else { 8 };
        if id_len == 2 {
            let short_id: u16 = self.message_id as u16;
            buf.extend_from_slice(&short_id.to_be_bytes());
        } else {
            buf.extend_from_slice(&self.message_id.to_be_bytes());
        }
        buf.extend_from_slice(&self.seq.to_be_bytes());
        buf.extend_from_slice(&self.seq_total.to_be_bytes());
        buf.extend_from_slice(&self.payload_len.to_be_bytes());
        buf
    }

    pub fn from_bytes(bytes: &[u8]) -> Result<Self, AkariError> {
        if bytes.len() < Self::FIXED_LEN {
            return Err(AkariError::InvalidHeaderLength(bytes.len()));
        }
        if bytes[0..2] != MAGIC {
            return Err(AkariError::InvalidMagic([bytes[0], bytes[1]]));
        }
        let version = bytes[2];
        if version != VERSION_V3 {
            return Err(AkariError::UnsupportedVersion(version));
        }
        let packet_type = PacketTypeV3::try_from(bytes[3])?;
        let flags = bytes[4];
        let id_len = if flags & FLAG_SHORT_ID != 0 { 2 } else { 8 };
        let min_len = 2 + 1 + 1 + 1 + 1 + id_len + 2 + 2 + 2;
        if bytes.len() < min_len {
            return Err(AkariError::InvalidHeaderLength(bytes.len()));
        }
        let mut offset = 6;
        let message_id = if id_len == 2 {
            let mut id_bytes = [0u8; 2];
            id_bytes.copy_from_slice(&bytes[offset..offset + 2]);
            offset += 2;
            u16::from_be_bytes(id_bytes) as u64
        } else {
            let mut id_bytes = [0u8; 8];
            id_bytes.copy_from_slice(&bytes[offset..offset + 8]);
            offset += 8;
            u64::from_be_bytes(id_bytes)
        };
        let seq = u16::from_be_bytes(bytes[offset..offset + 2].try_into().unwrap());
        offset += 2;
        let seq_total = u16::from_be_bytes(bytes[offset..offset + 2].try_into().unwrap());
        offset += 2;
        let payload_len = u16::from_be_bytes(bytes[offset..offset + 2].try_into().unwrap());

        Ok(Self {
            packet_type,
            flags,
            message_id,
            seq,
            seq_total,
            payload_len,
        })
    }
}
