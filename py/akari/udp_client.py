"""AKARI-UDP client used by the local proxy to talk to the remote proxy."""

from __future__ import annotations

import logging
import socket
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence, Tuple

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
        return len(self.chunks) >= self.seq_total

    def assembled_body(self) -> bytes:
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
    nacks_sent: int = 0
    request_retries: int = 0


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
        rcvbuf_bytes: int = 1_048_576,
        protocol_version: int = 2,
        max_nack_rounds: int | None = 3,
        max_ack_rounds: int = 0,
        use_encryption: bool = False,
        initial_request_retries: int = 1,
        sock_timeout: float = 1.0,
        first_seq_timeout: float = 0.5,
    ):
        self._remote_addr = remote_addr
        self._psk = psk
        # timeout=None のときは無限待ち
        self._timeout = timeout
        self._buffer_size = buffer_size
        self._max_nack_rounds = None if max_nack_rounds is None else max(0, int(max_nack_rounds))
        self._max_ack_rounds = max(0, int(max_ack_rounds))
        self._use_encryption = use_encryption
        self._version = protocol_version
        self._initial_request_retries = max(0, int(initial_request_retries))
        self._sock_timeout = sock_timeout
        # seq_total が不明のまま先頭チャンクを待つ許容時間。超えたら捨てて再リクエスト。
        self._first_seq_timeout = max(0.0, float(first_seq_timeout)) if first_seq_timeout is not None else None

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.settimeout(self._sock_timeout)
        try:
            target_rcvbuf = max(int(rcvbuf_bytes), buffer_size)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, target_rcvbuf)
            actual = self._sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)
            LOGGER.info("UDP SO_RCVBUF set to %s bytes", actual)
        except OSError:
            LOGGER.warning("could not set UDP SO_RCVBUF to %s", rcvbuf_bytes)

    def send_request(
        self,
        url: str,
        message_id: int,
        timestamp: int,
        *,
        datagram: bytes | None = None,
    ) -> ResponseOutcome:
        """Send a request and wait for resp/error. timeout=None means wait indefinitely."""

        if datagram is None:
            flags = 0x80 if (self._use_encryption and self._version >= 2) else 0
            if self._version >= 2:
                datagram = encode_request_v2_py("get", url, b"", message_id, timestamp, flags, self._psk)
            else:
                datagram = encode_request_py(url, message_id, timestamp, self._psk)

        packets: list[Mapping[str, Any]] = []
        accumulator = ResponseAccumulator(message_id)
        error_payload: Mapping[str, Any] | None = None
        bytes_sent = len(datagram)
        bytes_received = 0
        acks_sent = 0
        first_seq_deadline: float | None = None

        sock = self._sock
        sock.sendto(datagram, self._remote_addr)
        last_activity = time.monotonic()  # 送信時点からタイマー開始
        nacks_sent = 0
        req_retries_left = self._initial_request_retries
        while True:
            try:
                data, _ = sock.recvfrom(self._buffer_size)
            except ConnectionResetError:
                LOGGER.debug("recvfrom ConnectionResetError (ignored)")
                continue
            except socket.timeout:
                # 先頭チャンク（seq_total 情報）がないまま一定時間経過したら破棄して再リクエスト
                now = time.monotonic()
                waiting_first = accumulator.seq_total is None and accumulator.chunks
                allow_first_retry = self._first_seq_timeout is not None and req_retries_left > 0
                if waiting_first and allow_first_retry:
                    if first_seq_deadline is None:
                        first_seq_deadline = now + self._first_seq_timeout
                    if now >= first_seq_deadline:
                        accumulator = ResponseAccumulator(message_id)
                        first_seq_deadline = None
                        nacks_sent = 0
                        sock.sendto(datagram, self._remote_addr)
                        bytes_sent += len(datagram)
                        req_retries_left -= 1
                        last_activity = now
                        LOGGER.debug("retry request (missing seq0) message_id=%s (%d left)", message_id, req_retries_left)
                        continue

                # 何も受信できていない場合はリクエスト自体を限定回数で再送
                if not packets and req_retries_left > 0:
                    sock.sendto(datagram, self._remote_addr)
                    bytes_sent += len(datagram)
                    req_retries_left -= 1
                    last_activity = time.monotonic()
                    LOGGER.debug("retry request message_id=%s (%d left)", message_id, req_retries_left)
                    continue

                # 一定時間受信がなく、欠損がある場合のみNACKを送って再送を促す
                allow_nack = self._max_nack_rounds is None or nacks_sent < self._max_nack_rounds
                if (
                    self._version >= 2
                    and allow_nack
                    and accumulator.seq_total is not None
                    and not accumulator.complete
                ):
                    missing_seqs = self._sanitize_missing(self._missing_seq_list(accumulator), accumulator)
                    if missing_seqs:
                        missing_bitmap = self._build_missing_bitmap_from_list(missing_seqs)
                        nack = encode_nack_v2_py(missing_bitmap, message_id, timestamp, self._psk)
                        sock.sendto(nack, self._remote_addr)
                        bytes_sent += len(nack)
                        nacks_sent += 1
                        last_activity = time.monotonic()
                        LOGGER.debug(
                            "send NACK message_id=%s missing=%s bitmap_len=%d nacks_sent=%d",
                            message_id,
                            missing_seqs,
                            len(missing_bitmap),
                            nacks_sent,
                        )
                        continue

                if self._timeout is not None and (time.monotonic() - last_activity) >= self._timeout:
                    return ResponseOutcome(
                        message_id=message_id,
                        packets=packets,
                        body=None,
                        status_code=None,
                        headers=None,
                        error=None,
                        complete=False,
                        timed_out=True,
                        bytes_sent=bytes_sent,
                        bytes_received=bytes_received,
                        nacks_sent=nacks_sent,
                        request_retries=self._initial_request_retries - req_retries_left,
                    )
                continue

            bytes_received += len(data)
            parsed = decode_packet_py(data, self._psk)
            native = _to_native(parsed)
            packets.append(native)
            last_activity = time.monotonic()
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
                seq_total = accumulator.seq_total
                seq = payload.get("seq")

                # seq_total が取れたら先頭待ちタイマーを解除
                if seq_total is not None:
                    first_seq_deadline = None

                # 欠損があれば ACK を送って最初の欠損シーケンスを通知
                if (
                    self._version >= 2
                    and self._max_ack_rounds > acks_sent
                    and seq_total is not None
                    and not accumulator.complete
                ):
                    first_missing = self._first_missing_seq(accumulator)
                    if first_missing is not None:
                        ack = encode_ack_v2_py(first_missing, message_id, timestamp, self._psk)
                        sock.sendto(ack, self._remote_addr)
                        bytes_sent += len(ack)
                        acks_sent += 1
                        LOGGER.debug(
                            "send ACK message_id=%s first_missing=%s acks_sent=%d",
                            message_id,
                            first_missing,
                            acks_sent,
                        )

                if accumulator.complete:
                    break

                # 欠損があり、かつ最後のチャンク（seq_total-1）を受信したタイミングでのみNACKを再送
                allow_nack = self._max_nack_rounds is None or nacks_sent < self._max_nack_rounds
                if (
                    self._version >= 2
                    and allow_nack
                    and seq_total is not None
                    and seq is not None
                    and seq_total > 0
                    and seq == seq_total - 1
                ):
                    missing_seqs = self._sanitize_missing(self._missing_seq_list(accumulator), accumulator)
                    if missing_seqs:
                        missing_bitmap = self._build_missing_bitmap_from_list(missing_seqs)
                        nack = encode_nack_v2_py(missing_bitmap, message_id, timestamp, self._psk)
                        sock.sendto(nack, self._remote_addr)
                        bytes_sent += len(nack)
                        nacks_sent += 1
                        LOGGER.debug(
                            "send NACK message_id=%s missing=%s bitmap_len=%d nacks_sent=%d (after tail chunk)",
                            message_id,
                            missing_seqs,
                            len(missing_bitmap),
                            nacks_sent,
                        )
            elif packet_type == "error":
                error_payload = parsed["payload"]
                break

        body = accumulator.assembled_body() if accumulator.complete else None
        return ResponseOutcome(
            message_id=message_id,
            packets=packets,
            body=body,
            status_code=accumulator.status_code,
            headers=accumulator.headers,
            error=error_payload,
            complete=accumulator.complete,
            timed_out=False,
            bytes_sent=bytes_sent,
            bytes_received=bytes_received,
            nacks_sent=nacks_sent,
            request_retries=self._initial_request_retries - req_retries_left,
        )

    def close(self) -> None:
        try:
            self._sock.close()
        except Exception:
            LOGGER.warning("failed to close udp client socket", exc_info=True)

    def __enter__(self) -> "AkariUdpClient":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def _missing_seq_list(self, acc: ResponseAccumulator) -> list[int]:
        if acc.seq_total is None:
            return []
        return [i for i in range(acc.seq_total) if i not in acc.chunks]

    def _build_missing_bitmap_from_list(self, missing: list[int]) -> bytes:
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

    def _sanitize_missing(self, missing: list[int], acc: ResponseAccumulator) -> list[int]:
        # 念のため、受信済みが混ざっていたら除外しログに残す
        filtered = [seq for seq in missing if seq not in acc.chunks]
        if len(filtered) != len(missing):
            dup = sorted(set(missing) - set(filtered))
            LOGGER.warning(
                "NACK missing list contained already received seqs; filtered=%s duplicates=%s message_id=%s",
                filtered,
                dup,
                acc.message_id,
            )
        return filtered

    def _first_missing_seq(self, acc: ResponseAccumulator) -> int | None:
        """Return the smallest missing sequence number if any."""
        if acc.seq_total is None:
            return None
        for seq in range(acc.seq_total):
            if seq not in acc.chunks:
                return seq
        return None
