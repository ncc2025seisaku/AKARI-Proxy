"""テスト用クライアントから外部プロキシへ AKARI-UDP リクエストを送る。"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

_ROOT = Path(__file__).resolve().parents[2]
_PY_DIR = _ROOT / "py"
if str(_PY_DIR) not in sys.path:
    sys.path.insert(0, str(_PY_DIR))

from akari.udp_client import AkariUdpClient


@dataclass
class HttpCompareResult:
    status_code: int | None
    reason: str | None
    header_bytes: int
    body_bytes: int
    duration: float
    error: str | None

    @property
    def total_bytes(self) -> int:
        return self.header_bytes + self.body_bytes


def _iso_encode(value: str | None) -> bytes:
    return value.encode("iso-8859-1", errors="replace") if value else b""


def _calculate_header_bytes(status_line: str, headers: list[tuple[str, str]]) -> int:
    header_bytes = len(status_line.encode("iso-8859-1")) + 2  # status line + CRLF
    for name, value in headers:
        header_bytes += len(_iso_encode(name)) + 2  # ": "
        header_bytes += len(_iso_encode(value)) + 2  # CRLF
    header_bytes += 2  # final CRLF after headers
    return header_bytes


def fetch_direct_http(url: str, timeout: float) -> HttpCompareResult:
    parsed = urlparse(url)
    headers = {
        "User-Agent": "akari-udp-client/0.1",
        "Accept": "*/*",
        "Accept-Encoding": "identity",
        "Connection": "close",
    }
    request = Request(url, headers=headers, method="GET")
    if parsed.netloc:
        request.add_header("Host", parsed.netloc)

    try:
        start = time.monotonic()
        with urlopen(request, timeout=timeout) as response:
            body = response.read()
            duration = time.monotonic() - start
            version = response.version
            version_text = "1.1" if version == 11 else "1.0" if version == 10 else "1.1"
            status_line = f"HTTP/{version_text} {response.status} {response.reason or ''}".rstrip()
            header_bytes = _calculate_header_bytes(status_line, response.getheaders())
            return HttpCompareResult(
                status_code=response.status,
                reason=response.reason,
                header_bytes=header_bytes,
                body_bytes=len(body),
                duration=duration,
                error=None,
            )
    except (URLError, ValueError) as exc:
        return HttpCompareResult(
            status_code=None,
            reason=None,
            header_bytes=0,
            body_bytes=0,
            duration=0.0,
            error=str(exc),
        )


def parse_psk(value: str, *, hex_mode: bool) -> bytes:
    if hex_mode:
        return bytes.fromhex(value)
    return value.encode("utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Send a single request to the AKARI remote proxy")
    parser.add_argument("--host", default="127.0.0.1", help="remote proxy host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=14500, help="remote proxy port (default: 14500)")
    parser.add_argument("--url", default="https://example.com/ping", help="request URL")
    parser.add_argument("--psk", default="test-psk-0000-test", help="pre-shared key (plain text)")
    parser.add_argument("--hex", action="store_true", help="interpret --psk as hex string")
    parser.add_argument("--message-id", type=int, help="message_id to use (default: timestamp & 0xffff_ffff)")
    parser.add_argument("--timestamp", type=int, help="timestamp to embed (default: current time & 0xffff_ffff)")
    parser.add_argument("--timeout", type=float, default=10.0, help="receive timeout in seconds")
    parser.add_argument("--buffer-size", type=int, default=65535, help="UDP read buffer size")
    parser.add_argument(
        "--output-file",
        "-o",
        default="test/output/response_body.bin",
        help="保存先ファイル (デフォルト: response_body.bin)",
    )
    parser.add_argument(
        "--compare-http",
        action="store_true",
        help="HTTP 直接アクセスとのデータ量比較を行う",
    )
    parser.add_argument("--http-timeout", type=float, default=10.0, help="HTTP 比較のタイムアウト秒数")
    parser.add_argument("--log-level", default="INFO", help="logging level")
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(levelname)s %(message)s")
    psk = parse_psk(args.psk, hex_mode=args.hex)

    timestamp = args.timestamp if args.timestamp is not None else int(time.time()) & 0xFFFF_FFFF
    message_id = args.message_id if args.message_id is not None else timestamp

    client = AkariUdpClient((args.host, args.port), psk, timeout=args.timeout, buffer_size=args.buffer_size)
    result = client.send_request(args.url, message_id=message_id, timestamp=timestamp)

    output_path = Path(args.output_file)
    if result.body is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(result.body)
        print("saved body to:", output_path)
    else:
        print("saved body to: <none> (no body received)")

    http_stats = fetch_direct_http(args.url, timeout=args.http_timeout) if args.compare_http else None

    print("message_id:", result.message_id)
    print("complete:", result.complete)
    print("timed_out:", result.timed_out)
    print("status:", result.status_code)
    print("error:", result.error)
    print("bytes sent:", result.bytes_sent)
    print("bytes received:", result.bytes_received)
    print("total bytes (send + recv):", result.bytes_sent + result.bytes_received)
    # if result.body is not None:
    #     print("body:", result.body)
    print("received packets:", len(result.packets))
    if result.packets:
        print("--- packet dump ---")
        for index, packet in enumerate(result.packets, start=1):
            header = packet.get("header", {})
            payload = packet.get("payload", {})
            seq = payload.get("seq")
            chunk = payload.get("chunk")
            chunk_len = len(chunk) if isinstance(chunk, (bytes, bytearray)) else None
            print(
                f"{index:02d}: type={packet.get('type')} "
                f"message_id={header.get('message_id')} seq={seq} "
                f"seq_total={payload.get('seq_total')} chunk_len={chunk_len}",
            )

    if http_stats:
        if http_stats.error:
            print("HTTP compare failed:", http_stats.error)
        else:
            print("HTTP status:", http_stats.status_code, http_stats.reason)
            print("HTTP headers:", http_stats.header_bytes)
            print("HTTP body bytes:", http_stats.body_bytes)
            print("HTTP total bytes (headers + body):", http_stats.total_bytes)
            print(f"HTTP fetch duration: {http_stats.duration:.3f}s")
            akari_total = result.bytes_sent + result.bytes_received
            print("AKARI total bytes - HTTP total bytes:", akari_total - http_stats.total_bytes)


if __name__ == "__main__":
    main()
