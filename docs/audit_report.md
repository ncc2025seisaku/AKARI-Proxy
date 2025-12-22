# Code Audit Report

This document lists potential bugs, defects, and refactoring proposals identified during a codebase audit of the AKARI-UDP project.

## Potential Bugs & Defects

### 1. Incompatibility between Encryption and Aggregate Tag (V3)
**Severity**: High
**Location**: `crates/akari_udp_core/src/decode_v3.rs`
**Description**:
The V3 protocol implementation has a logic conflict when both `encrypt` (0x80) and `agg_mode` (0x40) flags are enabled.
- In `decode_packet_v3`, if `encrypt` is true, `decrypt_payload_v3` is called.
- `decrypt_payload_v3` expects a 16-byte AEAD authentication tag at the end of the packet.
- However, if `agg_mode` is also true, `tag_bytes` is set to an empty slice (as the tag is assumed to be aggregated elsewhere).
- This causes `decrypt_payload_v3` to return `AkariError::AeadFailed` immediately because `tag.len() != AEAD_TAG_LEN`.
**Impact**: Enabling both features causes all packets to fail decryption.
**Recommendation**: Clarify the spec. If encryption is used, per-packet authentication (AEAD) is generally required for security. If the goal is to reduce overhead by removing per-packet tags, a different encryption scheme (e.g., stream cipher with whole-message authentication) is needed, but this compromises security against malleability attacks on individual packets.

### 2. Unsafe `unwrap()` Usage
**Severity**: Medium
**Location**: `crates/akari_udp_core/src/decode_v3.rs`, `crates/akari_udp_core/src/aead.rs`
**Description**:
Several places use `unwrap()` on `try_into()` results.
- `decode_v3.rs`: `u16::from_be_bytes(bytes[offset..offset + 2].try_into().unwrap())`
- `aead.rs`: `let tag: [u8; AEAD_TAG_LEN] = ciphertext_with_tag[tag_start..].try_into().unwrap();`
While these are currently preceded by length checks, they remain potential panic points if logic changes or checks are refactored incorrectly.
**Recommendation**: Replace `unwrap()` with proper error handling or unreachable markers.

### 3. Incomplete Aggregate Tag Logic
**Severity**: Medium
**Location**: `crates/akari_udp_core/src/decode_v3.rs`
**Description**:
The `agg_mode` logic in `decode_packet_v3` checks:
```rust
let agg_mode = (header.flags & crate::header_v3::FLAG_AGG_TAG != 0) && (header.packet_type == PacketTypeV3::RespBody);
```
This implies `agg_mode` handling only applies to `RespBody` packets. However, the V3 plan suggests the aggregate tag might be at the beginning or end. If it is at the beginning (e.g., in `RespHead`), the current decoder might not handle it or verify it correctly.
Additionally, `decode_resp_body` expects the tag at the end of the *last* sequence. If packets arrive out of order, or if `RespHead` carries the tag, the logic needs to be more robust.

### 4. Client Configuration vs Implementation
**Severity**: Low
**Location**: `crates/akari_udp_core/src/client.rs`
**Description**:
The Rust client's `RequestConfig` has an `agg_tag` boolean. However, the client logic for verifying the aggregate tag:
```rust
} else if accumulator.body_seq_total.map(|t| t > 0).unwrap_or(false) {
    // Aggregate tag expected but not received
    return Err(ClientError::AggTagMismatch);
}
```
This assumes that if `agg_tag` is enabled, there *must* be a body sequence total > 0. For empty bodies or header-only responses, this logic might be flawed or ambiguous.

## Refactoring Proposals

### 1. Unified Packet Parsing
**Proposal**: Merge `decode.rs` (V1/V2) and `decode_v3.rs` (V3).
**Benefit**: Currently, there are `ParsedPacket` and `ParsedPacketV3` structs. This forces consumer code to handle two distinct types. A unified `ParsedPacket` enum (e.g., `ParsedPacket::V2(...)`, `ParsedPacket::V3(...)`) or a trait would simplify the public API and reduce code duplication in `akari_udp_py`.

### 2. Remove Magic Numbers
**Proposal**: Define constants for all protocol offsets and fixed values.
**Benefit**: `decode_v3.rs` uses literal numbers like `1 + 2 + 2` or `5`, `6`. Named constants (e.g., `OFFSET_BODY_LEN`, `MIN_HEADER_LEN`) improve readability and maintainability.

### 3. Consistent Error Handling
**Proposal**: Standardize on `thiserror` definitions in `error.rs`.
**Benefit**: Ensure all errors provide useful context. Currently `AkariError` covers most cases, but some `unwrap`s could be converted to specific error variants like `InternalError`.

### 4. Improve Logging Strategy
**Proposal**: Align Rust and Python logging.
**Benefit**: `akari_udp_core` uses `tracing` (behind a feature flag), while Python uses `logging`. Ensuring that Rust logs can be captured and propagated to Python's logging system (e.g., via `pyo3-log`) would make debugging easier.

### 5. Client Builder Pattern
**Proposal**: Use a Builder pattern for `RequestConfig`.
**Benefit**: `RequestConfig` has many fields. A builder would make client instantiation in Rust more ergonomic and allow for better default management.

## Other Observations

- **`RespHead` Aggregate Tag**: The V3 spec mentions the tag could be at the beginning. If so, `RespHead` needs a field for it, or the payload structure needs to accommodate it. The current implementation seems to favor placing it at the end of the last body chunk.
- **Python-Rust Boundary**: The separation of `akari_udp_core` and `akari_udp_py` is clean, but ensure that all `AkariError` variants are correctly mapped to Python exceptions.
