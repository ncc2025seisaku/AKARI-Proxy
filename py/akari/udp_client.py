"""ローカルプロキシが外部プロキシへ UDP パケットを送受信するためのユーティリティ。"""

from __future__ import annotations

import logging
import socket
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from akari_udp_py import decode_packet_py, encode_request_py, encode_request_v2_py

LOGGER = logging.getLogger(__name__)


def _to_native(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _to_native(val) for key, val in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_to_native(val) for val in value]
    return value


@dataclass
class ResponseAccumulator:
    message_id: int
    chunks: dict[int, bytes] = field(default_factory=dict)
    seq_total: int | None = None
    status_code: int | None = None
    body_len: int | None = None

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

    @property
    def complete(self) -> bool:
        if self.seq_total is None:
            return False
        return len(self.chunks) >= self.seq_total

    def assembled_body(self) -> bytes:
        return b"".join(self.chunks[seq] for seq in sorted(self.chunks))


@dataclass
class ResponseOutcome:
    message_id: int
    packets: list[Mapping[str, Any]]
    body: bytes | None
    status_code: int | None
    error: Mapping[str, Any] | None
    complete: bool
    timed_out: bool
    bytes_sent: int
    bytes_received: int


class AkariUdpClient:
    """AKARI-UDP リクエストを外部プロキシへ送信し、レスポンス/エラーを集約する。"""

    def __init__(
        self,
        remote_addr: tuple[str, int],
        psk: bytes,
        *,
        timeout: float = 2.0,
        buffer_size: int = 65535,
        protocol_version: int = 2,
    ):
        self._remote_addr = remote_addr
        self._psk = psk
        self._timeout = timeout
        self._buffer_size = buffer_size
        self._version = protocol_version

    def send_request(
        self,
        url: str,
        message_id: int,
        timestamp: int,
        *,
        datagram: bytes | None = None,
    ) -> ResponseOutcome:
        """Request を送信し、resp/error を受信してまとめる。"""

        if datagram is None:
            if self._version >= 2:
                datagram = encode_request_v2_py("get", url, b"", message_id, timestamp, 0, self._psk)
            else:
                datagram = encode_request_py(url, message_id, timestamp, self._psk)

        packets: list[Mapping[str, Any]] = []
        accumulator = ResponseAccumulator(message_id)
        error_payload: Mapping[str, Any] | None = None
        timed_out = False
        bytes_sent = len(datagram)
        bytes_received = 0

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(self._timeout)
            sock.sendto(datagram, self._remote_addr)
            last_received = time.monotonic()

            while True:
                remaining = self._timeout - (time.monotonic() - last_received)
                if remaining <= 0:
                    timed_out = True
                    break
                sock.settimeout(remaining)
                try:
                    data, _ = sock.recvfrom(self._buffer_size)
                except socket.timeout:
                    timed_out = True
                    break

                bytes_received += len(data)
                parsed = decode_packet_py(data, self._psk)
                native = _to_native(parsed)
                packets.append(native)
                last_received = time.monotonic()
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
                elif packet_type == "error":
                    error_payload = parsed["payload"]
                    break

        body = accumulator.assembled_body() if accumulator.complete else None
        return ResponseOutcome(
            message_id=message_id,
            packets=packets,
            body=body,
            status_code=accumulator.status_code,
            error=error_payload,
            complete=accumulator.complete,
            timed_out=timed_out,
            bytes_sent=bytes_sent,
            bytes_received=bytes_received,
        )
