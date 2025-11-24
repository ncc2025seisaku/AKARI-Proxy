#!/usr/bin/env python3
"""AKARI-UDP の災害時想定ストレステストツール."""

from __future__ import annotations

import argparse
import json
import logging
import queue
import random
import socket
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "py"))

from akari.remote_proxy.handler import ERROR_TIMEOUT
from akari.udp_client import AkariUdpClient, ResponseAccumulator, ResponseOutcome, _to_native
from akari.udp_server import AkariUdpServer, IncomingRequest, encode_error_response, encode_success_response
from akari_udp_py import (
    decode_packet_py,
    encode_ack_v2_py,
    encode_nack_v2_py,
    encode_request_py,
    encode_request_v2_py,
)

LOGGER = logging.getLogger("akari.stress")


def parse_psk(value: str, *, hex_mode: bool) -> bytes:
    if hex_mode:
        return bytes.fromhex(value)
    return value.encode("utf-8")


def normalize_object(value: object) -> object:
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, Mapping):
        return {key: normalize_object(val) for key, val in value.items()}
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, bytearray)):
        return [normalize_object(item) for item in value]
    return value


class LossyAkariClient(AkariUdpClient):
    """Base client に受信ドロップ・ジッターを足した版."""

    def __init__(self, *args, loss_rate: float = 0.0, jitter: float = 0.0, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._loss_rate = max(0.0, min(1.0, loss_rate))
        self._jitter = max(0.0, jitter)

    def send_request(  # type: ignore[override]
        self,
        url: str,
        message_id: int,
        timestamp: int,
        *,
        datagram: bytes | None = None,
    ) -> ResponseOutcome:
        if datagram is None:
            if self._version >= 2:
                datagram = encode_request_v2_py("get", url, b"", message_id, timestamp, 0, self._psk)
            else:
                datagram = encode_request_py(url, message_id, timestamp, self._psk)

        packets: list[Mapping[str, object]] = []
        accumulator = ResponseAccumulator(message_id)
        error_payload: Mapping[str, object] | None = None
        timed_out = False
        bytes_sent = len(datagram)
        bytes_received = 0

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(self._timeout)
            sock.sendto(datagram, self._remote_addr)
            last_received = time.monotonic()

            nack_sent = False
            while True:
                remaining = self._timeout - (time.monotonic() - last_received)
                if remaining <= 0:
                    if self._version >= 2 and accumulator.seq_total and not accumulator.complete and not nack_sent:
                        missing_bitmap = self._build_missing_bitmap(accumulator)
                        if missing_bitmap:
                            if self._jitter:
                                time.sleep(random.uniform(0, self._jitter))
                            nack = encode_nack_v2_py(missing_bitmap, message_id, timestamp, self._psk)
                            sock.sendto(nack, self._remote_addr)
                            nack_sent = True
                            last_received = time.monotonic()
                            continue
                    timed_out = True
                    break
                sock.settimeout(remaining)
                try:
                    data, _ = sock.recvfrom(self._buffer_size)
                except socket.timeout:
                    timed_out = True
                    break

                if self._loss_rate and random.random() < self._loss_rate:
                    LOGGER.debug("drop packet for message_id=%s", message_id)
                    continue

                bytes_received += len(data)
                if self._jitter:
                    time.sleep(random.uniform(0, self._jitter))
                parsed = decode_packet_py(data, self._psk)
                native = _to_native(parsed)
                packets.append(native)
                last_received = time.monotonic()
                payload = parsed.get("payload", {})
                chunk = payload.get("chunk")
                chunk_len = len(chunk) if isinstance(chunk, (bytes, bytearray)) else None
                LOGGER.debug(
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
            headers=accumulator.headers,
            error=error_payload,
            complete=accumulator.complete,
            timed_out=timed_out,
            bytes_sent=bytes_sent,
            bytes_received=bytes_received,
        )


@dataclass
class StressCounters:
    success: int = 0
    timeout: int = 0
    error: int = 0
    bytes_sent: int = 0
    bytes_received: int = 0
    latencies: list[float] = field(default_factory=list)


class ResultAggregator:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters = StressCounters()

    def add(self, outcome: ResponseOutcome, elapsed: float) -> None:
        with self._lock:
            if outcome.complete and not outcome.error:
                self._counters.success += 1
                self._counters.latencies.append(elapsed)
            elif outcome.timed_out or (outcome.error and outcome.error.get("error_code") == ERROR_TIMEOUT):
                self._counters.timeout += 1
            else:
                self._counters.error += 1
            self._counters.bytes_sent += outcome.bytes_sent
            self._counters.bytes_received += outcome.bytes_received

    def snapshot(self) -> StressCounters:
        with self._lock:
            copy = StressCounters(
                success=self._counters.success,
                timeout=self._counters.timeout,
                error=self._counters.error,
                bytes_sent=self._counters.bytes_sent,
                bytes_received=self._counters.bytes_received,
                latencies=list(self._counters.latencies),
            )
        return copy


class DemoServer:
    """単純に body を返す UDP サーバ (テスト環境用)."""

    def __init__(self, host: str, port: int, psk: bytes, body: bytes, timeout: float) -> None:
        self._server = AkariUdpServer(host, port, psk, self._handler, timeout=timeout)
        self._body = body
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._stop = threading.Event()

    @property
    def address(self) -> tuple[str, int]:
        return self._server.address

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join()
        self._server.close()

    def _run(self) -> None:
        while not self._stop.is_set():
            self._server.handle_next()

    def _handler(self, request: IncomingRequest) -> Sequence[bytes]:
        url = request.payload.get("url", "")
        if "error" in url:
            return encode_error_response(request, 2, 502, "demo error")
        return encode_success_response(request, self._body, status_code=200, seq_total=1)


def worker_main(
    name: str,
    client: LossyAkariClient,
    tasks: "queue.Queue[tuple[int, str]]",
    agg: ResultAggregator,
    delay: float,
) -> None:
    while True:
        try:
            idx, url = tasks.get_nowait()
        except queue.Empty:
            return
        start = time.perf_counter()
        outcome = client.send_request(url, message_id=idx, timestamp=int(time.time()))
        elapsed = time.perf_counter() - start
        agg.add(outcome, elapsed)
        LOGGER.debug("%s done url=%s elapsed=%.3fs complete=%s error=%s", name, url, elapsed, outcome.complete, outcome.error)
        if delay:
            time.sleep(delay)


def summarize(counters: StressCounters) -> dict[str, object]:
    latencies = sorted(counters.latencies)
    count = len(latencies)
    pct95 = latencies[max(int(count * 0.95) - 1, 0)] if count else 0.0
    pct99 = latencies[max(int(count * 0.99) - 1, 0)] if count else 0.0
    avg = sum(latencies) / count if count else 0.0
    return {
        "success": counters.success,
        "timeout": counters.timeout,
        "error": counters.error,
        "bytes_sent": counters.bytes_sent,
        "bytes_received": counters.bytes_received,
        "latency_avg_sec": round(avg, 4),
        "latency_p95_sec": round(pct95, 4),
        "latency_p99_sec": round(pct99, 4),
    }


def build_tasks(total: int, urls: Sequence[str]) -> "queue.Queue[tuple[int, str]]":
    q: "queue.Queue[tuple[int, str]]" = queue.Queue()
    for idx in range(total):
        url = urls[idx % len(urls)]
        q.put((idx, url))
    return q


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="AKARI-UDP stress tester (disaster-mode)")
    parser.add_argument("--host", default="127.0.0.1", help="リモートプロキシのホスト")
    parser.add_argument("--port", type=int, default=14500, help="リモートプロキシのポート")
    parser.add_argument("--psk", default="test-psk-0000-test", help="PSK (文字列)")
    parser.add_argument("--hex", action="store_true", help="PSK を 16 進として解釈")
    parser.add_argument("--url", action="append", dest="urls", help="叩く URL (複数指定可)", default=["https://example.com/"])
    parser.add_argument("--requests", type=int, default=100, help="総リクエスト数")
    parser.add_argument("--concurrency", type=int, default=8, help="同時実行スレッド数")
    parser.add_argument("--timeout", type=float, default=2.0, help="UDP タイムアウト秒")
    parser.add_argument("--loss-rate", type=float, default=0.1, help="受信ドロップ確率 (0-1)")
    parser.add_argument("--jitter", type=float, default=0.0, help="受信後に入れるジッター秒 (0 で無効)")
    parser.add_argument("--delay", type=float, default=0.0, help="各リクエスト完了後に入れる待機秒")
    parser.add_argument("--demo-server", action="store_true", help="ローカル簡易サーバを起動して自己完結でテストする")
    parser.add_argument("--log-level", default="INFO", help="ログレベル")
    args = parser.parse_args(argv)

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(levelname)s %(name)s: %(message)s")
    psk = parse_psk(args.psk, hex_mode=args.hex)
    server: DemoServer | None = None
    target = (args.host, args.port)

    if args.demo_server:
        server = DemoServer(args.host, args.port, psk, body=b"demo-stress-response", timeout=args.timeout)
        server.start()
        target = server.address
        LOGGER.info("demo server listening on %s:%s", *target)

    tasks = build_tasks(args.requests, args.urls)
    agg = ResultAggregator()
    workers = []
    for i in range(args.concurrency):
        client = LossyAkariClient(target, psk, timeout=args.timeout, loss_rate=args.loss_rate, jitter=args.jitter)
        t = threading.Thread(target=worker_main, args=(f"worker-{i+1}", client, tasks, agg, args.delay), daemon=True)
        t.start()
        workers.append(t)

    start = time.perf_counter()
    for t in workers:
        t.join()
    elapsed = time.perf_counter() - start

    if server:
        server.stop()

    counters = agg.snapshot()
    summary = summarize(counters)
    summary["elapsed_sec"] = round(elapsed, 3)
    summary["rps"] = round(args.requests / elapsed, 2) if elapsed else args.requests

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    import socket

    main()
