"""外部プロキシ側で AKARI-UDP パケットを受信し、レスポンスを返すサーバ。"""

from __future__ import annotations

import socket
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from akari_udp_py import (
    decode_packet_py,
    encode_error_py,
    encode_response_first_chunk_py,
)


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
    ) -> None:
        self._psk = psk
        self._handler = handler
        self.buffer_size = buffer_size
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind((host, port))
        if timeout is not None:
            self._sock.settimeout(timeout)
        self.address = self._sock.getsockname()

    def handle_next(self) -> IncomingRequest | None:
        """1 回だけデータを受信してハンドラに渡す。"""

        try:
            data, client_addr = self._sock.recvfrom(self.buffer_size)
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
            self._sock.sendto(bytes(datagram), client_addr)

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

    datagram = encode_error_py(
        error_code,
        http_status,
        message,
        request.header["message_id"],
        request.header["timestamp"],
        request.psk,
    )
    return (datagram,)
