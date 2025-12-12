"""AKARI-UDP client used by the local proxy to talk to the remote proxy."""

from __future__ import annotations

import logging
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence, Tuple

from akari_udp_py import (
    decode_packet_auto_py,
    encode_ack_v2_py,
    encode_nack_v2_py,
    encode_nack_body_v3_py,
    encode_nack_head_v3_py,
    encode_request_py,
    encode_request_v2_py,
    encode_request_v3_py,
)
import hmac
import hashlib

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
    chunks: dict[int, bytes] = field(default_factory=dict)  # body chunks
    seq_total: int | None = None  # body seq_total
    status_code: int | None = None
    body_len: int | None = None
    headers_bytes: bytes | None = None
    headers: dict[str, str] | None = None
    # v3 header chunks
    hdr_chunks: dict[int, bytes] = field(default_factory=dict)
    hdr_total: int | None = None
    agg_tag: bytes | None = None

    def add_chunk_v2(self, packet: Mapping[str, Any]) -> None:
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

    def add_head_v3(self, payload: Mapping[str, Any]) -> None:
        self.status_code = payload["status_code"]
        self.body_len = payload["body_len"]
        self.seq_total = payload["seq_total_body"]
        hdr_idx = payload["hdr_idx"]
        hdr_chunks = payload["hdr_chunks"]
        self.hdr_total = hdr_chunks
        self.hdr_chunks[hdr_idx] = bytes(payload["headers"])

    def add_head_cont_v3(self, payload: Mapping[str, Any]) -> None:
        hdr_idx = payload["hdr_idx"]
        hdr_chunks = payload["hdr_chunks"]
        self.hdr_total = hdr_chunks
        self.hdr_chunks[hdr_idx] = bytes(payload["headers"])

    def add_body_v3(self, header: Mapping[str, Any], payload: Mapping[str, Any]) -> None:
        seq = payload["seq"]
        self.chunks[seq] = payload["chunk"]
        seq_total = payload.get("seq_total") or header.get("seq_total")
        if seq_total is not None:
            self.seq_total = seq_total
        if payload.get("agg_tag") is not None:
            self.agg_tag = bytes(payload["agg_tag"])

    @property
    def header_complete(self) -> bool:
        if self.hdr_total is None:
            return False
        return len(self.hdr_chunks) >= self.hdr_total

    def assemble_headers(self) -> None:
        if self.headers_bytes is not None or not self.header_complete:
            return
        ordered = [self.hdr_chunks[idx] for idx in sorted(self.hdr_chunks)]
        self.headers_bytes = b"".join(ordered)
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
        df: bool = True,
    ):
        self._remote_addr = remote_addr
        self._psk = psk
        # timeout=None のときは無限待ち
        # 無指定なら10秒、0以下なら無制限
        self._timeout = None if (timeout is not None and timeout <= 0) else (10.0 if timeout is None else timeout)
        self._buffer_size = buffer_size
        self._max_nack_rounds = None if max_nack_rounds is None else max(0, int(max_nack_rounds))
        self._max_ack_rounds = max(0, int(max_ack_rounds))
        self._use_encryption = use_encryption
        self._version = protocol_version
        self._initial_request_retries = max(0, int(initial_request_retries))
        self._sock_timeout = sock_timeout
        # seq_total が不明のまま先頭チャンクを待つ許容時間。超えたら捨てて再リクエスト。
        self._first_seq_timeout = max(0.0, float(first_seq_timeout)) if first_seq_timeout is not None else None
        # 同一ソケットを複数スレッドで共有するとパケットを奪い合うため直列化用ロックを用意
        self._lock = threading.Lock()
        self._df = bool(df)

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.settimeout(self._sock_timeout)
        try:
            target_rcvbuf = max(int(rcvbuf_bytes), buffer_size)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, target_rcvbuf)
            actual = self._sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)
            LOGGER.info("UDP SO_RCVBUF set to %s bytes", actual)
        except OSError:
            LOGGER.warning("could not set UDP SO_RCVBUF to %s", rcvbuf_bytes)
        self._apply_df(self._sock)

    def _apply_df(self, sock: socket.socket) -> None:
        """DF（Don't Fragment）フラグを可能な範囲で適用する。失敗しても致命ではない。"""
        if not self._df:
            return
        # Linux では IP_MTU_DISCOVER を DO に、Windows では IP_DONTFRAGMENT を使う
        try:
            if hasattr(socket, "IP_MTU_DISCOVER") and hasattr(socket, "IP_PMTUDISC_DO"):
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MTU_DISCOVER, socket.IP_PMTUDISC_DO)
            if hasattr(socket, "IPV6_MTU_DISCOVER") and hasattr(socket, "IPV6_PMTUDISC_DO"):
                sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MTU_DISCOVER, socket.IPV6_PMTUDISC_DO)
        except OSError:
            LOGGER.debug("could not enable DF/PMTUD on socket (IPv4/IPv6)")
        try:
            if hasattr(socket, "IP_DONTFRAGMENT"):
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_DONTFRAGMENT, 1)
        except OSError:
            LOGGER.debug("could not set IP_DONTFRAGMENT on socket")

    def send_request(
        self,
        url: str,
        message_id: int,
        timestamp: int,
        *,
        datagram: bytes | None = None,
    ) -> ResponseOutcome:
        """Send a request and wait for resp/error. timeout=None means wait indefinitely."""

        # ソケット共有によるパケット取り違えを防ぐため直列化
        with self._lock:
            return self._send_request_unlocked(url, message_id, timestamp, datagram=datagram)

    def _send_request_unlocked(
        self,
        url: str,
        message_id: int,
        timestamp: int,
        *,
        datagram: bytes | None = None,
    ) -> ResponseOutcome:
        """Internal send; caller must hold _lock."""

        if datagram is None:
            flags = 0x80 if self._use_encryption else 0
            if self._version >= 3:
                # v3はagg-tagデフォルト（0x40）、short-idはまだ未使用
                flags |= 0x40  # agg-tag
                datagram = encode_request_v3_py("get", url, b"", message_id, flags, timestamp, self._psk)
            elif self._version >= 2:
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
        agg_mode = False

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
                now = time.monotonic()
                elapsed = now - last_activity

                # 初回無応答: リトライを優先
                if not packets:
                    if req_retries_left > 0:
                        sock.sendto(datagram, self._remote_addr)
                        bytes_sent += len(datagram)
                        req_retries_left -= 1
                        last_activity = now
                        LOGGER.debug("retry request (no response yet) message_id=%s (%d left)", message_id, req_retries_left)
                        continue
                    # リトライ尽きたらタイムアウト判定へ

                # ヘッダ未完ならヘッダNACKを優先
                if self._version >= 3 and accumulator.hdr_total and not accumulator.header_complete:
                    missing_hdrs = [i for i in range(accumulator.hdr_total) if i not in accumulator.hdr_chunks]
                    allow_nack_head = self._max_nack_rounds is None or nacks_sent < self._max_nack_rounds
                    if allow_nack_head and missing_hdrs:
                        bitmap = self._build_missing_bitmap_from_list(missing_hdrs)
                        nack = encode_nack_head_v3_py(bitmap, message_id, 0, self._psk)
                        sock.sendto(nack, self._remote_addr)
                        bytes_sent += len(nack)
                        nacks_sent += 1
                        last_activity = now
                        LOGGER.debug(
                            "send NACK-HEAD message_id=%s missing=%s bitmap_len=%d nacks_sent=%d (timeout)",
                            message_id,
                            missing_hdrs,
                            len(bitmap),
                            nacks_sent,
                        )
                        continue

                # ヘッダ完了後はボディNACK
                if accumulator.seq_total is not None and not accumulator.complete:
                    allow_nack = self._max_nack_rounds is None or nacks_sent < self._max_nack_rounds
                    if allow_nack:
                        missing_seqs = self._sanitize_missing(self._missing_seq_list(accumulator), accumulator)
                        if missing_seqs:
                            missing_bitmap = self._build_missing_bitmap_from_list(missing_seqs)
                            nack = (
                                encode_nack_body_v3_py(missing_bitmap, message_id, 0, self._psk)
                                if self._version >= 3
                                else encode_nack_v2_py(missing_bitmap, message_id, timestamp, self._psk)
                            )
                            sock.sendto(nack, self._remote_addr)
                            bytes_sent += len(nack)
                            nacks_sent += 1
                            last_activity = now
                            LOGGER.debug(
                                "send NACK-BODY message_id=%s missing=%s bitmap_len=%d nacks_sent=%d (timeout)",
                                message_id,
                                missing_seqs,
                                len(missing_bitmap),
                                nacks_sent,
                            )
                            continue

                # 最終的なタイムアウト判定
                if self._timeout is not None and elapsed >= self._timeout:
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
            parsed = decode_packet_auto_py(data, self._psk)
            native = _to_native(parsed)
            packets.append(native)
            last_activity = time.monotonic()
            payload = native.get("payload", {})
            header_flags = native.get("header", {}).get("flags", 0)
            if header_flags & 0x40:
                agg_mode = True
            chunk = payload.get("chunk")
            chunk_len = len(chunk) if isinstance(chunk, (bytes, bytearray)) else None
            LOGGER.info(
                "recv packet type=%s message_id=%s seq=%s/%s chunk=%sB",
                native.get("type"),
                native.get("header", {}).get("message_id"),
                payload.get("seq"),
                payload.get("seq_total") or native.get("header", {}).get("seq_total"),
                chunk_len,
            )

            packet_type = native["type"]
            if packet_type == "resp":
                accumulator.add_chunk_v2(native)
                seq_total = accumulator.seq_total
                seq = payload.get("seq")

                if seq_total is not None:
                    first_seq_deadline = None

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
            elif packet_type == "resp-head":
                accumulator.add_head_v3(payload)
                if accumulator.header_complete:
                    accumulator.assemble_headers()
            elif packet_type == "resp-head-cont":
                accumulator.add_head_cont_v3(payload)
                if accumulator.header_complete:
                    accumulator.assemble_headers()
            elif packet_type == "resp-body":
                accumulator.add_body_v3(native.get("header", {}), payload)
                if accumulator.seq_total is not None and accumulator.complete:
                    break
                allow_nack = self._max_nack_rounds is None or nacks_sent < self._max_nack_rounds
                seq_total = accumulator.seq_total
                seq = payload.get("seq")
                if allow_nack and seq_total is not None and seq is not None and seq_total > 0 and seq == seq_total - 1:
                    missing_seqs = self._sanitize_missing(self._missing_seq_list(accumulator), accumulator)
                    if missing_seqs:
                        missing_bitmap = self._build_missing_bitmap_from_list(missing_seqs)
                        nack = encode_nack_body_v3_py(missing_bitmap, message_id, 0, self._psk)
                        sock.sendto(nack, self._remote_addr)
                        bytes_sent += len(nack)
                        nacks_sent += 1
                        LOGGER.debug(
                            "send NACK-BODY message_id=%s missing=%s bitmap_len=%d nacks_sent=%d (after tail chunk)",
                            message_id,
                            missing_seqs,
                            len(missing_bitmap),
                            nacks_sent,
                        )
            elif packet_type == "nack-head":
                # ignore on client side (not expected)
                pass
            elif packet_type == "error":
                error_payload = native["payload"]
                break

        body = accumulator.assembled_body() if accumulator.complete else None
        # 集約タグ検証（非暗号化のみ想定）
        if agg_mode and accumulator.complete and body is not None:
            if accumulator.agg_tag is None:
                error_payload = {"message": "aggregate tag missing"}
            else:
                calc_tag = hmac.new(self._psk, body, hashlib.sha256).digest()[:16]
                if calc_tag != accumulator.agg_tag:
                    error_payload = {"message": "aggregate tag mismatch"}
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
