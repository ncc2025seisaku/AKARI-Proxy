#!/usr/bin/env python3
"""HTTPS 直接取得と AKARI-UDP 経由取得のネットワーク送受信バイト数を比較するスクリプト."""

from __future__ import annotations

import argparse
import logging
import os
import http.client
import secrets
import socket
import ssl
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PY_DIR = PROJECT_ROOT / "py"
if str(PY_DIR) not in sys.path:
    sys.path.insert(0, str(PY_DIR))

from akari.udp_client import AkariUdpClient  # noqa: E402
from akari.web_proxy.config import ConfigError, WebProxyConfig, load_config  # noqa: E402

ACCEPT_ENCODING = "br, gzip, deflate"
USER_AGENT = "AKARI-Proxy/0.1"
DEFAULT_MAX_BODY_BYTES = 1_000_000
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
LOGGER = logging.getLogger("akari.compare")


@dataclass
class TrafficSample:
    url: str
    status_code: int | None
    bytes_sent: int
    bytes_received: int
    truncated: bool
    redirects: list[str]


class CountingSocket(socket.socket):
    """send/recv をフックするソケットサブクラス。"""

    def __init__(self, sock: socket.socket) -> None:
        super().__init__(sock.family, sock.type, sock.proto, fileno=sock.detach())
        self.bytes_sent = 0
        self.bytes_received = 0

    def send(self, data: bytes, *args, **kwargs) -> int:  # type: ignore[override]
        sent = super().send(data, *args, **kwargs)
        self.bytes_sent += sent
        return sent

    def sendall(self, data: bytes, *args, **kwargs) -> None:  # type: ignore[override]
        super().sendall(data, *args, **kwargs)
        self.bytes_sent += len(data)

    def recv(self, bufsize: int, *args, **kwargs) -> bytes:  # type: ignore[override]
        data = super().recv(bufsize, *args, **kwargs)
        self.bytes_received += len(data)
        return data

    def recv_into(self, buffer, nbytes: int | None = None, *args, **kwargs) -> int:  # type: ignore[override]
        read = super().recv_into(buffer, nbytes, *args, **kwargs)
        self.bytes_received += max(read, 0)
        return read

    def sendto(self, data: bytes, *args, **kwargs) -> int:  # type: ignore[override]
        sent = super().sendto(data, *args, **kwargs)
        self.bytes_sent += sent
        return sent

    def sendmsg(self, buffers, *args, **kwargs) -> int:  # type: ignore[override]
        sent = super().sendmsg(buffers, *args, **kwargs)
        self.bytes_sent += sent
        return sent

    def recvfrom(self, bufsize: int, *args, **kwargs):  # type: ignore[override]
        data, addr = super().recvfrom(bufsize, *args, **kwargs)
        self.bytes_received += len(data)
        return data, addr

    def recvfrom_into(self, buffer, nbytes: int | None = None, *args, **kwargs):  # type: ignore[override]
        read, addr = super().recvfrom_into(buffer, nbytes, *args, **kwargs)
        self.bytes_received += max(read, 0)
        return read, addr


class CountingHTTPSConnection(http.client.HTTPSConnection):
    """TLS ハンドシェイクを含む送受信バイト数を採取する HTTPSConnection."""

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        context = kwargs.pop("context", ssl.create_default_context())
        super().__init__(*args, context=context, **kwargs)
        self._counter: CountingSocket | None = None

    def connect(self) -> None:
        raw_sock = socket.create_connection(
            (self.host, self.port),
            self.timeout,
            self.source_address,
        )
        counter = CountingSocket(raw_sock)  # TLS 前の生ソケットをラップ
        self._counter = counter
        if self._tunnel_host:
            self.sock = counter  # type: ignore[assignment]
            self._tunnel()
        # http.client.HTTPSConnection は _context に SSLContext を保持する
        self.sock = self._context.wrap_socket(counter, server_hostname=self.host)  # type: ignore[assignment]

    @property
    def bytes_sent(self) -> int:
        return self._counter.bytes_sent if self._counter else 0

    @property
    def bytes_received(self) -> int:
        return self._counter.bytes_received if self._counter else 0


def _build_path(path: str, query: str) -> str:
    normalized_path = path or "/"
    if query:
        return f"{normalized_path}?{query}"
    return normalized_path


def fetch_https_with_count(
    url: str,
    *,
    timeout: float,
    max_body_bytes: int,
    max_redirects: int,
) -> TrafficSample:
    """HTTPS で実際に送受信された総バイト数を（ハンドシェイク込みで）計測."""
    current = url
    redirects: list[str] = []
    total_sent = 0
    total_received = 0
    status_code: int | None = None
    truncated = False

    for _ in range(max_redirects + 1):
        parsed = urlsplit(current)
        if parsed.scheme != "https":
            raise ValueError("HTTPS URL を指定してください。リダイレクト先が HTTP の場合は --max-redirects を下げてください。")

        host = parsed.hostname or ""
        port = parsed.port or 443
        conn = CountingHTTPSConnection(host, port, timeout=timeout)
        headers = {
            "Host": f"{host}:{port}" if port not in (443, None) else host,
            "User-Agent": USER_AGENT,
            "Accept-Encoding": ACCEPT_ENCODING,
            "Connection": "close",
        }
        path = _build_path(parsed.path, parsed.query)

        try:
            conn.request("GET", path, headers=headers)
            resp = conn.getresponse()
            body = resp.read(max_body_bytes + 1)
            if len(body) > max_body_bytes:
                truncated = True
            status_code = resp.status
            location = resp.getheader("Location")
            total_sent += conn.bytes_sent
            total_received += conn.bytes_received
        finally:
            conn.close()

        # 平文サイズを算出し、計測値がそれ未満なら平文サイズで近似
        req_line = f"GET {path} HTTP/1.1\r\n"
        req_plain_len = len((req_line + "".join(f"{k}: {v}\r\n" for k, v in headers.items()) + "\r\n").encode("utf-8"))
        if total_sent < req_plain_len:
            total_sent = req_plain_len

        status_line = f"HTTP/1.1 {status_code} OK\r\n"
        resp_header_bytes = sum(len(f"{k}: {v}\r\n".encode("utf-8")) for k, v in resp.headers.items())
        resp_plain_len = len(status_line.encode("utf-8")) + resp_header_bytes + len(b"\r\n") + len(body)
        if total_received < resp_plain_len:
            total_received = resp_plain_len

        if status_code in REDIRECT_STATUSES and location and len(redirects) < max_redirects:
            next_url = urljoin(current, location)
            redirects.append(next_url)
            current = next_url
            continue
        break

    return TrafficSample(
        url=current,
        status_code=status_code,
        bytes_sent=total_sent,
        bytes_received=total_received,
        truncated=truncated,
        redirects=redirects,
    )


def fetch_udp_with_count(
    url: str,
    config: WebProxyConfig,
    *,
    use_encryption: bool,
    message_id: int | None = None,
    timeout_override: float | None = None,
    initial_request_retries: int = 1,
) -> TrafficSample:
    """AKARI-UDP 経由で取得し、送受信バイト数を計測."""
    remote = config.remote
    LOGGER.debug(
        "udp fetch start url=%s host=%s port=%s enc=%s timeout=%.2f retries=%d",
        url,
        remote.host,
        remote.port,
        use_encryption,
        timeout_override if timeout_override is not None else remote.timeout,
        initial_request_retries,
    )
    client = AkariUdpClient(
        (remote.host, remote.port),
        remote.psk,
        timeout=timeout_override if timeout_override is not None else remote.timeout,
        max_nack_rounds=None,  # 無制限に NACK を送って欠損を埋める
        max_ack_rounds=3,
        use_encryption=use_encryption,
        initial_request_retries=initial_request_retries,
    )
    mid = message_id or (secrets.randbelow(0xFFFF) or 1)
    ts = int(time.time())
    LOGGER.debug("sending message_id=%s timestamp=%s", mid, ts)
    outcome = client.send_request(url, mid, int(time.time()))
    if outcome.error:
        LOGGER.error("udp error message_id=%s payload=%s", mid, outcome.error)
        raise RuntimeError(f"AKARI-UDP error: {outcome.error}")
    if outcome.timed_out:
        LOGGER.error("udp timeout message_id=%s bytes_sent=%d bytes_recv=%d", mid, outcome.bytes_sent, outcome.bytes_received)
        raise TimeoutError("AKARI-UDP レスポンスがタイムアウトしました。")
    if not outcome.complete:
        LOGGER.error(
            "udp incomplete message_id=%s seq_total=%s chunks=%d bytes_sent=%d bytes_recv=%d",
            mid,
            outcome.packets[-1]["payload"].get("seq_total") if outcome.packets else None,
            len(outcome.packets),
            outcome.bytes_sent,
            outcome.bytes_received,
        )
        raise RuntimeError("AKARI-UDP レスポンスが揃いませんでした。")

    return TrafficSample(
        url=url,
        status_code=outcome.status_code,
        bytes_sent=outcome.bytes_sent,
        bytes_received=outcome.bytes_received,
        truncated=False,
        redirects=[],
    )


def _percent_delta(baseline: int, target: int) -> float:
    if baseline <= 0:
        return 0.0
    return (1.0 - (target / baseline)) * 100.0


def _format_redirects(chain: Iterable[str]) -> str:
    items = list(chain)
    if not items:
        return "-"
    return " -> ".join(items)


def print_summary(https: TrafficSample, udp: TrafficSample, *, body_limit: int) -> None:
    print("=== Direct HTTPS ===")
    print(f"URL: {https.url}")
    print(f"Status: {https.status_code}")
    print(f"Sent (client -> server): {https.bytes_sent:,} bytes")
    print(f"Recv (server -> client): {https.bytes_received:,} bytes")
    print(f"Redirects: {_format_redirects(https.redirects)}")
    if https.truncated:
        print(f"Note: ボディが {body_limit} バイトを超えたため計測途中で打ち切り")
    print()
    print("=== AKARI-UDP ===")
    print(f"Status: {udp.status_code}")
    print(f"Sent (client -> remote): {udp.bytes_sent:,} bytes")
    print(f"Recv (remote -> client): {udp.bytes_received:,} bytes")
    print()
    print("=== Reduction vs HTTPS ===")
    print(f"Sent: {_percent_delta(https.bytes_sent, udp.bytes_sent):.1f}% 減")
    print(f"Recv: {_percent_delta(https.bytes_received, udp.bytes_received):.1f}% 減")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="HTTPS と AKARI-UDP の送受信バイト数を比較する")
    parser.add_argument("--url", required=True, help="計測対象の HTTPS URL")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "conf" / "web_proxy.toml"), help="web_proxy.toml のパス")
    parser.add_argument("--timeout", type=float, default=10.0, help="HTTPS 側のタイムアウト秒数")
    parser.add_argument("--max-body-bytes", type=int, default=DEFAULT_MAX_BODY_BYTES, help="HTTPS 取得時のボディ上限（超過すると打ち切り）")
    parser.add_argument("--max-redirects", type=int, default=3, help="フォローするリダイレクト回数の上限")
    parser.add_argument("--enc", action="store_true", help="AKARI-UDP で暗号化フラグを立てて計測")
    parser.add_argument("--udp-timeout", type=float, default=None, help="AKARI-UDP 側のタイムアウト秒数（config の値を上書き）")
    parser.add_argument("--udp-retries", type=int, default=1, help="AKARI-UDP リクエスト初回再送回数")
    parser.add_argument("--log-level", default=os.environ.get("AKARI_COMPARE_LOG_LEVEL", "INFO"), help="ログレベル (DEBUG/INFO/...)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"設定読み込みに失敗しました: {exc}")
        raise SystemExit(1) from exc

    if not args.url.startswith("https://"):
        print("URL は https:// から始まるものを指定してください。")
        raise SystemExit(1)

    https_sample = fetch_https_with_count(
        args.url,
        timeout=args.timeout,
        max_body_bytes=args.max_body_bytes,
        max_redirects=args.max_redirects,
    )
    udp_sample = fetch_udp_with_count(
        args.url,
        config,
        use_encryption=args.enc,
        timeout_override=args.udp_timeout,
        initial_request_retries=args.udp_retries,
    )
    print_summary(https_sample, udp_sample, body_limit=args.max_body_bytes)


if __name__ == "__main__":
    main()
