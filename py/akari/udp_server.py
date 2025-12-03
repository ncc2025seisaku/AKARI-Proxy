"""Lightweight UDP server wrapper for AKARI-UDP (demo / load testing)."""

from __future__ import annotations

import logging
import os
import socket
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from akari_udp_py import (
    decode_packet_py,
    encode_error_py,
    encode_error_v2_py,
    encode_response_chunk_py,
    encode_response_chunk_v2_py,
    encode_response_first_chunk_py,
    encode_response_first_chunk_v2_py,
)

LOGGER = logging.getLogger(__name__)
# Approx safe UDP payload to avoid IP fragmentation
MTU_PAYLOAD_SIZE = 1180
# status(2) + hdr_len/reserved(2) + body_len(4)
FIRST_CHUNK_METADATA_LEN = 8
FIRST_CHUNK_CAPACITY = max(MTU_PAYLOAD_SIZE - FIRST_CHUNK_METADATA_LEN, 0)


@dataclass
class IncomingRequest:
    header: Mapping[str, Any]
    payload: Mapping[str, Any]
    packet_type: str
    addr: tuple[str, int]
    parsed: Mapping[str, Any]
    datagram: bytes
    psk: bytes


class AkariUdpServer:
    """Minimal UDP server that decodes AKARI-UDP and delegates to a handler."""

    buffer_size: int
    address: tuple[str, int]

    def __init__(
        self,
        host: str,
        port: int,
        psk: bytes,
        handler: Callable[[IncomingRequest], Sequence[bytes]],
        *,
        timeout: float | None = None,
        buffer_size: int = 65535,
    ) -> None:
        self._psk = psk
        self._handler = handler
        self.buffer_size = buffer_size
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind((host, port))
        if os.name == "nt":
            SIO_UDP_CONNRESET = getattr(socket, "SIO_UDP_CONNRESET", 0x9800000C)
            try:
                self._sock.ioctl(SIO_UDP_CONNRESET, b"\x00\x00\x00\x00")
            except (OSError, ValueError):
                LOGGER.warning("could not disable UDP connreset (Windows); continuing")
        if timeout is not None:
            self._sock.settimeout(timeout)
        self.address = self._sock.getsockname()

    def handle_next(self) -> IncomingRequest | None:
        """Receive one datagram, dispatch to handler, send responses."""
        try:
            data, client_addr = self._sock.recvfrom(self.buffer_size)
        except ConnectionResetError:
            LOGGER.debug("recvfrom ConnectionResetError (possible ICMP port unreachable); ignoring")
            return None
        except socket.timeout:
            return None

        parsed = decode_packet_py(data, self._psk)
        request = IncomingRequest(
            header=parsed["header"],
            payload=parsed["payload"],
            packet_type=parsed["type"],
            addr=client_addr,
            parsed=parsed,
            datagram=data,
            psk=self._psk,
        )

        for datagram in self._handler(request):
            datagram_bytes = bytes(datagram)
            try:
                parsed_resp = decode_packet_py(datagram_bytes, self._psk)
                payload = parsed_resp.get("payload", {})
                LOGGER.info(
                    "send packet type=%s seq=%s/%s len=%d to=%s",
                    parsed_resp.get("type"),
                    payload.get("seq"),
                    payload.get("seq_total"),
                    len(datagram_bytes),
                    client_addr,
                )
            except Exception:
                LOGGER.exception("failed to decode response packet for logging")
            self._sock.sendto(datagram_bytes, client_addr)

        return request

    def close(self) -> None:
        self._sock.close()

    def __enter__(self) -> "AkariUdpServer":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


def encode_success_response(
    request: IncomingRequest,
    body: bytes,
    *,
    status_code: int = 200,
) -> Sequence[bytes]:
    """Chunk and send a response body; avoids u16 payload limits."""

    is_v2 = int(request.header.get("version", 1)) >= 2
    body_len = len(body)
    first_chunk = body[:FIRST_CHUNK_CAPACITY] if FIRST_CHUNK_CAPACITY > 0 else b""
    tail = body[FIRST_CHUNK_CAPACITY:]
    tail_chunks = [tail[i : i + MTU_PAYLOAD_SIZE] for i in range(0, len(tail), MTU_PAYLOAD_SIZE)]
    if len(tail_chunks) + 1 > 0xFFFF:
        raise ValueError("response too large to fit in u16 seq_total; reduce body size or stream differently")
    seq_total = max(1, 1 + len(tail_chunks))
    message_id = request.header["message_id"]
    timestamp = request.header["timestamp"]

    if is_v2:
        first = encode_response_first_chunk_v2_py(
            status_code,
            body_len,
            b"",
            first_chunk,
            message_id,
            seq_total,
            0,
            timestamp,
            request.psk,
        )
    else:
        first = encode_response_first_chunk_py(
            status_code,
            body_len,
            first_chunk,
            message_id,
            seq_total,
            timestamp,
            request.psk,
        )

    datagrams = [first]
    for idx, chunk in enumerate(tail_chunks, start=1):
        if is_v2:
            datagrams.append(encode_response_chunk_v2_py(chunk, message_id, idx, seq_total, 0, timestamp, request.psk))
        else:
            datagrams.append(encode_response_chunk_py(chunk, message_id, idx, seq_total, timestamp, request.psk))
    return tuple(datagrams)


def encode_error_response(
    request: IncomingRequest,
    *,
    error_code: int,
    http_status: int,
    message: str,
) -> Sequence[bytes]:
    """Encode an error response packet."""

    is_v2 = int(request.header.get("version", 1)) >= 2
    if is_v2:
        datagram = encode_error_v2_py(
            error_code,
            http_status,
            message,
            request.header["message_id"],
            request.header["timestamp"],
            request.psk,
        )
    else:
        datagram = encode_error_py(
            error_code,
            http_status,
            message,
            request.header["message_id"],
            request.header["timestamp"],
            request.psk,
        )
    return (datagram,)
