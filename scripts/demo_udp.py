#!/usr/bin/env python3
"""AKARI-UDP のローカル/外部プロキシ相当を簡易構成で実行して確認するデモ。"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "py"))

from akari.udp_client import AkariUdpClient, ResponseOutcome
from akari.udp_server import (
    AkariUdpServer,
    IncomingRequest,
    encode_error_response,
    encode_success_response,
)


DEFAULT_PSK = "test-psk-0000-test"
DEFAULT_URLS = (
    "https://example.com/",
    "https://example.com/error",
)


def parse_psk(value: str, *, hex_mode: bool) -> bytes:
    if hex_mode:
        return bytes.fromhex(value)
    return value.encode("utf-8")


def normalize_object(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, Mapping):
        return {key: normalize_object(val) for key, val in value.items()}
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, bytearray)):
        return [normalize_object(item) for item in value]
    return value


class DemoServer:
    def __init__(self, host: str, port: int, psk: bytes, error_keyword: str, timeout: float) -> None:
        self._server = AkariUdpServer(host, port, psk, self._handler, timeout=timeout)
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, name="akari-demo-server", daemon=True)
        self._error_keyword = error_keyword
        self._psk = psk

    @property
    def address(self) -> tuple[str, int]:
        return self._server.address

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join()

    def _run(self) -> None:
        try:
            while not self._stop_event.is_set():
                self._server.handle_next()
        finally:
            self._server.close()

    def _handler(self, request: IncomingRequest) -> Sequence[bytes]:
        url = request.payload.get("url", "<unknown>")
        print(f"[server] req message_id={request.header['message_id']} url={url}")
        if self._error_keyword in url:
            return encode_error_response(
                request,
                error_code=2,
                http_status=502,
                message="demo error",
            )
        body = f"demo response for {url}".encode("utf-8")
        return encode_success_response(request, body, status_code=200, seq_total=1)


class DemoRunner:
    def __init__(
        self,
        server_host: str,
        server_port: int,
        psk: bytes,
        urls: Sequence[str],
        *,
        error_keyword: str,
        timeout: float,
        base_message_id: int,
    ) -> None:
        self._psk = psk
        self._urls = list(urls or DEFAULT_URLS)
        self._timeout = timeout
        self._base_message_id = base_message_id
        self._server = DemoServer(server_host, server_port, psk, error_keyword, timeout)

    def run(self) -> None:
        print("-- server starting --")
        self._server.start()
        try:
            client = AkariUdpClient(self._server.address, self._psk, timeout=self._timeout)
            for idx, url in enumerate(self._urls):
                message_id = self._base_message_id + idx
                timestamp = int(time.time())
                outcome = client.send_request(url, message_id, timestamp)
                self._report(url, outcome)
        finally:
            self._server.stop()
            print("-- server stopped --")

    def _report(self, url: str, outcome: ResponseOutcome) -> None:
        summary = {
            "message_id": outcome.message_id,
            "complete": outcome.complete,
            "timed_out": outcome.timed_out,
            "status_code": outcome.status_code,
            "body_length": len(outcome.body) if outcome.body else 0,
            "error": outcome.error,
            "packet_count": len(outcome.packets),
        }
        print(f"\n[client] {url}")
        print(json.dumps(normalize_object(summary), ensure_ascii=False, indent=2))
        if outcome.packets:
            print("packets:")
            print(json.dumps(normalize_object(outcome.packets), ensure_ascii=False, indent=2))


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="AKARI-UDP client/server demo")
    parser.add_argument("--host", default="127.0.0.1", help="UDP バインド先ホスト")
    parser.add_argument("--port", type=int, default=0, help="UDP バインド先ポート（0=OS任せ）")
    parser.add_argument("--psk", default=DEFAULT_PSK, help="事前共有鍵（文字列）")
    parser.add_argument("--hex", action="store_true", help="--psk を 16 進文字列として扱う")
    parser.add_argument(
        "--url",
        action="append",
        dest="urls",
        help="送信する URL（複数指定可、未指定時はデフォルト2件）",
    )
    parser.add_argument("--error-keyword", default="error", help="URL に含まれるとエラー応答を返すキーワード")
    parser.add_argument("--timeout", type=float, default=2.0, help="UDP タイムアウト（秒）")
    parser.add_argument("--message-id", type=lambda v: int(v, 0), default=0x1000, help="message_id の初期値")
    args = parser.parse_args(argv)

    psk = parse_psk(args.psk, hex_mode=args.hex)
    runner = DemoRunner(
        args.host,
        args.port,
        psk,
        args.urls or DEFAULT_URLS,
        error_keyword=args.error_keyword,
        timeout=args.timeout,
        base_message_id=args.message_id,
    )
    runner.run()


if __name__ == "__main__":
    main()
