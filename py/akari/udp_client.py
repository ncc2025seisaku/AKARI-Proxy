"""AKARI-UDP client used by the local proxy to talk to the remote proxy."""

from __future__ import annotations

import gzip
import logging
import random
import socket
import time
import zlib
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence, Tuple

import brotli

from akari_udp_py import (
    decode_packet_py,
    encode_ack_v2_py,
    encode_nack_v2_py,
    encode_request_py,
    encode_request_v2_py,
)

LOGGER = logging.getLogger(__name__)


def _to_native(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _to_native(val) for key, val in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_to_native(val) for val in value]
    return value


def _decompress_body(body: bytes, headers: dict[str, str] | None) -> tuple[bytes, dict[str, str] | None]:
    """Decode compressed payloads and normalize headers to the decompressed representation."""
    if not headers:
        return body, headers
    encoding = headers.get("content-encoding", headers.get("Content-Encoding", "")).lower()
    normalized_headers = dict(headers)
    if "content-encoding" in normalized_headers:
        normalized_headers.pop("content-encoding", None)
    if "Content-Encoding" in normalized_headers:
        normalized_headers.pop("Content-Encoding", None)

    try:
        if encoding == "br":
            body = brotli.decompress(body)
        elif encoding == "gzip":
            body = gzip.decompress(body)
        elif encoding == "deflate":
            body = zlib.decompress(body)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("failed to decompress body with encoding=%s: %s", encoding, exc)
    normalized_headers["content-length"] = str(len(body))
    return body, normalized_headers


@dataclass
class ResponseAccumulator:
    message_id: int
    chunks: dict[int, bytes] = field(default_factory=dict)
    seq_total: int | None = None
    status_code: int | None = None
    body_len: int | None = None
    headers_bytes: bytes | None = None
    headers: dict[str, str] | None = None

    def add_chunk(self, packet: Mapping[str, Any]) -> None:
        header = packet["header"]
        if header["message_id"] != self.message_id:
            return

        payload = packet["payload"]
        seq: int = payload["seq"]
        self.chunks[seq] = payload["chunk"]

        seq_total = payload.get("seq_total")
        if seq_total is not None:
            self.seq_total = seq_total
        if payload.get("status_code") is not None:
            self.status_code = payload["status_code"]
        if payload.get("body_len") is not None:
            self.body_len = payload["body_len"]
        hdr_bytes = payload.get("headers")
        if hdr_bytes and self.headers_bytes is None:
            self.headers_bytes = bytes(hdr_bytes)
            self.headers = decode_header_block(self.headers_bytes)

    @property
    def complete(self) -> bool:
        if self.seq_total is None:
            return False
        if len(self.chunks) >= self.seq_total:
            return True
        # FEC parity: 1 missing chunk + parity chunk present
        if len(self.chunks) == self.seq_total - 1 and (self.seq_total - 1) in self.chunks:
            return True
        return False

    def assembled_body(self) -> bytes:
        if self.seq_total is not None and len(self.chunks) == self.seq_total - 1 and (self.seq_total - 1) in self.chunks:
            # Attempt single-loss recovery using parity chunk at last seq index
            missing = [seq for seq in range(self.seq_total) if seq not in self.chunks]
            if len(missing) == 1:
                parity = bytearray(self.chunks[self.seq_total - 1])
                for seq, chunk in self.chunks.items():
                    if seq == self.seq_total - 1:
                        continue
                    padded = chunk + b"\x00" * (len(parity) - len(chunk))
                    for i, b in enumerate(padded):
                        parity[i] ^= b
                recovered = bytes(parity)
                self.chunks[missing[0]] = recovered

        return b"".join(self.chunks[seq] for seq in sorted(self.chunks))


@dataclass
class ResponseOutcome:
    message_id: int
    packets: list[Mapping[str, Any]]
    body: bytes | None
    status_code: int | None
    headers: dict[str, str] | None
    error: Mapping[str, Any] | None
    complete: bool
    timed_out: bool
    bytes_sent: int
    bytes_received: int


STATIC_HEADER_IDS = {
    1: "content-type",
    2: "content-length",
    3: "cache-control",
    4: "etag",
    5: "last-modified",
    6: "date",
    7: "server",
    8: "content-encoding",
    9: "accept-ranges",
    10: "set-cookie",
    11: "location",
}


def _read_varint_u16(buf: memoryview, offset: int) -> Tuple[int, int]:
    end = offset + 2
    if end > len(buf):
        raise ValueError("varint truncated")
    return int.from_bytes(buf[offset:end], "big"), end


def decode_header_block(block: bytes) -> dict[str, str]:
    headers: dict[str, str] = {}
    buf = memoryview(block)
    pos = 0
    while pos < len(buf):
        hid = buf[pos]
        pos += 1
        if hid == 0:
            if pos >= len(buf):
                break
            name_len = buf[pos]
            pos += 1
            end_name = pos + name_len
            if end_name > len(buf):
                break
            name = bytes(buf[pos:end_name]).decode("utf-8", errors="replace")
            pos = end_name
            val_len, pos = _read_varint_u16(buf, pos)
            end_val = pos + val_len
            if end_val > len(buf):
                break
            value = bytes(buf[pos:end_val]).decode("utf-8", errors="replace")
            pos = end_val
            headers[name] = value
        else:
            val_len, pos = _read_varint_u16(buf, pos)
            end_val = pos + val_len
            if end_val > len(buf):
                break
            value = bytes(buf[pos:end_val]).decode("utf-8", errors="replace")
            pos = end_val
            name = STATIC_HEADER_IDS.get(hid, f"x-unknown-{hid}")
            headers[name] = value
    return headers


class AkariUdpClient:
    """Send AKARI-UDP requests to a remote proxy and gather responses."""

    def __init__(
        self,
        remote_addr: tuple[str, int],
        psk: bytes,
        *,
        timeout: float | None = None,
        buffer_size: int = 65535,
        protocol_version: int = 2,
        max_nack_rounds: int = 3,
        heartbeat_interval: float = 0.0,
        heartbeat_backoff: float = 1.5,
        max_retries: int = 0,
        initial_retry_delay: float = 0.0,
        retry_jitter: float = 0.0,
    ):
        self._remote_addr = remote_addr
        self._psk = psk
        # timeout: Noneなら待ち続ける。指定があれば全体の締め切りとして使う
        self._timeout = timeout
        self._buffer_size = buffer_size
        self._max_nack_rounds = max(0, int(max_nack_rounds))
        self._version = protocol_version
        self._heartbeat_interval = max(0.0, heartbeat_interval)
        self._heartbeat_backoff = heartbeat_backoff if heartbeat_backoff > 0 else 1.0
        self._max_retries = max(0, int(max_retries))
        self._initial_retry_delay = max(0.0, initial_retry_delay if initial_retry_delay > 0 else heartbeat_interval)
        self._retry_jitter = max(0.0, retry_jitter)

    def send_request(
        self,
        url: str,
        message_id: int,
        timestamp: int,
        *,
        datagram: bytes | None = None,
    ) -> ResponseOutcome:
        """Send a request and wait for resp/error. timeout=None means wait indefinitely."""

        timed_out = False
        if datagram is None:
            if self._version >= 2:
                datagram = encode_request_v2_py("get", url, b"", message_id, timestamp, 0, self._psk)
            else:
                datagram = encode_request_py(url, message_id, timestamp, self._psk)

        packets: list[Mapping[str, Any]] = []
        accumulator = ResponseAccumulator(message_id)
        error_payload: Mapping[str, Any] | None = None
        bytes_sent = len(datagram)
        bytes_received = 0
        last_received = time.monotonic()
        expires_at = last_received + self._timeout if self._timeout else None

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(None)
            sock.sendto(datagram, self._remote_addr)
            nacks_sent = 0
            retries = 0
            heartbeat_interval = self._heartbeat_interval
            next_probe = (
                last_received + heartbeat_interval if heartbeat_interval > 0 and self._max_retries > 0 else None
            )
            retry_delay = self._initial_retry_delay if self._initial_retry_delay > 0 else heartbeat_interval
            while True:
                now = time.monotonic()
                if expires_at is not None and now >= expires_at:
                    timed_out = True
                    break

                # ハートビート再送を適応的に送る（フラップ対策）
                if next_probe is not None and now >= next_probe and retries < self._max_retries:
                    sock.sendto(datagram, self._remote_addr)
                    retries += 1
                    retry_delay = retry_delay * self._heartbeat_backoff if retry_delay else heartbeat_interval
                    jitter = random.random() * self._retry_jitter if self._retry_jitter else 0.0
                    next_probe = time.monotonic() + max(retry_delay, heartbeat_interval) + jitter

                remaining = None
                if expires_at is not None:
                    remaining = max(expires_at - now, 0.0)
                sock.settimeout(0.5 if remaining is None else max(min(0.5, remaining), 0.05))
                try:
                    data, _ = sock.recvfrom(self._buffer_size)
                except socket.timeout:
                    if expires_at is not None and time.monotonic() >= expires_at:
                        timed_out = True
                        break
                    continue

                bytes_received += len(data)
                parsed = decode_packet_py(data, self._psk)
                native = _to_native(parsed)
                packets.append(native)
                last_received = time.monotonic()
                if self._timeout is not None:
                    expires_at = last_received + self._timeout
                payload = parsed.get("payload", {})
                chunk = payload.get("chunk")
                chunk_len = len(chunk) if isinstance(chunk, (bytes, bytearray)) else None
                LOGGER.info(
                    "recv packet type=%s message_id=%s seq=%s/%s chunk=%sB",
                    parsed.get("type"),
                    parsed.get("header", {}).get("message_id"),
                    payload.get("seq"),
                    payload.get("seq_total"),
                    chunk_len,
                )

                packet_type = parsed["type"]
                if packet_type == "resp":
                    accumulator.add_chunk(parsed)
                    if accumulator.complete:
                        break
                    if (
                        self._version >= 2
                        and nacks_sent < self._max_nack_rounds
                        and accumulator.seq_total is not None
                        and payload.get("seq") is not None
                    ):
                        missing_bitmap = self._build_missing_bitmap(accumulator)
                        if missing_bitmap:
                            nack = encode_nack_v2_py(missing_bitmap, message_id, timestamp, self._psk)
                            sock.sendto(nack, self._remote_addr)
                            nacks_sent += 1
                elif packet_type == "error":
                    error_payload = parsed["payload"]
                    break

        body = accumulator.assembled_body() if accumulator.complete else None
        headers = accumulator.headers
        if body is not None:
            body, headers = _decompress_body(body, headers)
        return ResponseOutcome(
            message_id=message_id,
            packets=packets,
            body=body,
            status_code=accumulator.status_code,
            headers=headers,
            error=error_payload,
            complete=accumulator.complete,
            timed_out=timed_out,
            bytes_sent=bytes_sent,
            bytes_received=bytes_received,
        )

    def _build_missing_bitmap(self, acc: ResponseAccumulator) -> bytes:
        if acc.seq_total is None:
            return b""
        missing = [i for i in range(acc.seq_total) if i not in acc.chunks]
        if not missing:
            return b""
        max_seq = max(missing)
        length = (max_seq // 8) + 1
        bitmap = bytearray(length)
        for seq in missing:
            idx = seq // 8
            bit = seq % 8
            bitmap[idx] |= 1 << bit
        return bytes(bitmap)

