"""外部プロキシ側で AKARI-UDP パケットを受信し、レスポンスを返すサーバ。"""

from __future__ import annotations

import logging
import socket
import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from akari_udp_py import (
    decode_packet_auto_py,
    decode_packet_py,
    encode_error_py,
    encode_error_v2_py,
    encode_response_first_chunk_py,
    encode_response_first_chunk_v2_py,
)

LOGGER = logging.getLogger(__name__)


@dataclass
class IncomingRequest:
    header: Mapping[str, Any]
    payload: Mapping[str, Any]
    packet_type: str
    addr: tuple[str, int]
    parsed: Mapping[str, Any]
    datagram: bytes
    psk: bytes
    buffer_size: int = 65535
    payload_max: int | None = None


class AkariUdpServer:
    """単発リクエストを処理するための簡易 UDP サーバ。"""

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
        payload_max: int | None = None,
        df: bool = True,
        plpmtud: bool = False,
    ) -> None:
        self._psk = psk
        self._handler = handler
        self.buffer_size = buffer_size
        self.payload_max = payload_max
        self._plpmtud = bool(plpmtud)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind((host, port))
        if os.name == "nt":
            SIO_UDP_CONNRESET = getattr(socket, "SIO_UDP_CONNRESET", 0x9800000C)
            try:
                self._sock.ioctl(SIO_UDP_CONNRESET, b"\x00\x00\x00\x00")
            except (OSError, ValueError):
                LOGGER.warning("could not disable UDP connreset (Windows); continuing")
        if df:
            self._set_df(self._sock)
        if timeout is not None:
            self._sock.settimeout(timeout)
        self.address = self._sock.getsockname()

    @staticmethod
    def _set_df(sock: socket.socket) -> None:
        try:
            if hasattr(socket, "IP_MTU_DISCOVER") and hasattr(socket, "IP_PMTUDISC_DO"):
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MTU_DISCOVER, socket.IP_PMTUDISC_DO)
            if hasattr(socket, "IPV6_MTU_DISCOVER") and hasattr(socket, "IPV6_PMTUDISC_DO"):
                sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MTU_DISCOVER, socket.IPV6_PMTUDISC_DO)
        except OSError:
            LOGGER.debug("could not enable PMTUD (IPv4/IPv6) on server socket")
        try:
            if hasattr(socket, "IP_DONTFRAGMENT"):
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_DONTFRAGMENT, 1)
        except OSError:
            LOGGER.debug("could not set IP_DONTFRAGMENT on server socket")

    def _dynamic_payload_cap(self) -> int | None:
        """
        簡易PLPMTUD: ソケットが報告する MTU からUDP/IP/AKARIのオーバーヘッドを差し引き、
        payload_max の上限を推定する。取得できなければ既定値を返す。
        """
        mtu: int | None = None
        try:
            if hasattr(socket, "IP_MTU"):
                mtu = self._sock.getsockopt(socket.IPPROTO_IP, socket.IP_MTU)
            elif hasattr(socket, "IPV6_MTU"):
                mtu = self._sock.getsockopt(socket.IPPROTO_IPV6, socket.IPV6_MTU)
        except OSError:
            mtu = None

        base = self.payload_max
        if mtu and mtu > 0:
            # UDP/IP(48) + AKARI固定(40相当) + 安全マージン(32) を引く
            estimated = max(256, mtu - 120)
            base = estimated if base is None else min(base, estimated)
        return base

    def handle_next(self) -> IncomingRequest | None:
        """1 回だけデータを受信してハンドラに渡す。"""

        try:
            data, client_addr = self._sock.recvfrom(self.buffer_size)
        except ConnectionResetError:
            LOGGER.debug("recvfrom ConnectionResetError (possible ICMP port unreachable); ignoring")
            return None
        except socket.timeout:
            return None

        dyn_payload_max = self._dynamic_payload_cap() if self._plpmtud else self.payload_max

        parsed = decode_packet_auto_py(data, self._psk)
        request = IncomingRequest(
            header=parsed["header"],
            payload=parsed["payload"],
            packet_type=parsed["type"],
            addr=client_addr,
            parsed=parsed,
            datagram=data,
            psk=self._psk,
            buffer_size=self.buffer_size,
            payload_max=dyn_payload_max,
        )

        for datagram in self._handler(request):
            datagram_bytes = bytes(datagram)
            try:
                parsed = decode_packet_py(datagram_bytes, self._psk)
                payload = parsed.get("payload", {})
                LOGGER.info(
                    "send packet type=%s seq=%s/%s len=%d to=%s",
                    parsed.get("type"),
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
    seq_total: int = 1,
) -> Sequence[bytes]:
    """リクエストに対する単一チャンクのレスポンスを組み立てる。"""

    is_v2 = int(request.header.get("version", 1)) >= 2
    if is_v2:
        datagram = encode_response_first_chunk_v2_py(
            status_code,
            len(body),
            b"",
            body,
            request.header["message_id"],
            seq_total,
            0,
            request.header["timestamp"],
            request.psk,
        )
    else:
        datagram = encode_response_first_chunk_py(
            status_code,
            len(body),
            body,
            request.header["message_id"],
            seq_total,
            request.header["timestamp"],
            request.psk,
        )
    return (datagram,)


def encode_error_response(
    request: IncomingRequest,
    *,
    error_code: int,
    http_status: int,
    message: str,
) -> Sequence[bytes]:
    """リクエストに対するエラーを返すパケットを組み立てる。"""

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
