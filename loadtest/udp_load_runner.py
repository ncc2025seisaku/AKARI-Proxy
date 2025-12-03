#!/usr/bin/env python3
"""Ad-hoc load tester for the AKARI UDP proxy.

This script stays self contained so it can live outside production paths.
It spins a pool of worker threads that drive the proxy via AkariUdpClient,
optionally adding packet loss/jitter to emulate harsh networks.
"""

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

from akari.remote_proxy.handler import ERROR_TIMEOUT  # noqa: E402
from akari.udp_client import AkariUdpClient, ResponseAccumulator, ResponseOutcome  # noqa: E402
from akari.udp_server import AkariUdpServer, IncomingRequest, encode_error_response, encode_success_response  # noqa: E402
from akari_udp_py import decode_packet_py, encode_nack_v2_py, encode_request_py, encode_request_v2_py  # noqa: E402

LOGGER = logging.getLogger("akari.loadtest")


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


class LoadTestClient(AkariUdpClient):
    """AkariUdpClient with timeout/loss/jitter controls for load testing."""

    def __init__(
        self,
        *args,
        loss_rate: float = 0.0,
        jitter: float = 0.0,
        flap_interval: float = 0.0,
        flap_duration: float = 0.0,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._loss_rate = max(0.0, min(1.0, loss_rate))
        self._jitter = max(0.0, jitter)
        self._timeout = kwargs.get("timeout") or 3.0
        self._flap_interval = max(0.0, flap_interval)
        self._flap_duration = max(0.0, flap_duration)
        self._started_at = time.monotonic()

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
            nack_sent = 0
            retries = 0
            heartbeat_interval = self._heartbeat_interval
            next_probe = (
                last_received + heartbeat_interval if heartbeat_interval > 0 and self._max_retries > 0 else None
            )
            retry_delay = self._initial_retry_delay if self._initial_retry_delay > 0 else heartbeat_interval

            while True:
                if next_probe is not None and time.monotonic() >= next_probe and retries < self._max_retries:
                    sock.sendto(datagram, self._remote_addr)
                    retries += 1
                    retry_delay = retry_delay * self._heartbeat_backoff if retry_delay else heartbeat_interval
                    jitter = random.random() * self._retry_jitter if self._retry_jitter else 0.0
                    next_probe = time.monotonic() + max(retry_delay, heartbeat_interval) + jitter

                remaining = self._timeout - (time.monotonic() - last_received)
                if remaining <= 0:
                    timed_out = True
                    break
                sock.settimeout(max(min(0.5, remaining), 0.05))
                try:
                    data, _ = sock.recvfrom(self._buffer_size)
                except socket.timeout:
                    timed_out = True
                    break

                if self._flap_interval and self._flap_duration:
                    if (time.monotonic() - self._started_at) % self._flap_interval < self._flap_duration:
                        LOGGER.debug("drop packet by flap window message_id=%s", message_id)
                        continue

                if self._loss_rate and random.random() < self._loss_rate:
                    LOGGER.debug("drop packet message_id=%s", message_id)
                    continue
                bytes_received += len(data)
                if self._jitter:
                    time.sleep(random.uniform(0, self._jitter))

                parsed = decode_packet_py(data, self._psk)
                packets.append(normalize_object(parsed))
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
                    if (
                        self._version >= 2
                        and accumulator.seq_total is not None
                        and payload.get("seq") is not None
                        and nack_sent < self._max_nack_rounds
                    ):
                        missing_bitmap = self._build_missing_bitmap(accumulator)
                        if missing_bitmap:
                            nack = encode_nack_v2_py(missing_bitmap, message_id, timestamp, self._psk)
                            sock.sendto(nack, self._remote_addr)
                            nack_sent += 1
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
class Counters:
    success: int = 0
    timeout: int = 0
    error: int = 0
    bytes_sent: int = 0
    bytes_received: int = 0
    latencies: list[float] = field(default_factory=list)
    exceptions: int = 0


class Aggregator:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters = Counters()

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

    def add_exception(self, *, bytes_sent: int = 0, bytes_received: int = 0) -> None:
        with self._lock:
            self._counters.error += 1
            self._counters.exceptions += 1
            self._counters.bytes_sent += bytes_sent
            self._counters.bytes_received += bytes_received

    def snapshot(self) -> Counters:
        with self._lock:
            copy = Counters(
                success=self._counters.success,
                timeout=self._counters.timeout,
                error=self._counters.error,
                bytes_sent=self._counters.bytes_sent,
                bytes_received=self._counters.bytes_received,
                latencies=list(self._counters.latencies),
                exceptions=self._counters.exceptions,
            )
        return copy


class DemoServer:
    """Small UDP responder to avoid touching real endpoints while testing."""

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
        return encode_success_response(request, self._body, status_code=200)


class LogWriter:
    def __init__(self, path: Path, extra: Mapping[str, object] | None = None) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._extra = dict(extra) if extra else None

    def write(self, obj: dict[str, object]) -> None:
        if self._extra:
            payload = {**self._extra, **obj}
        else:
            payload = obj
        line = json.dumps(payload, ensure_ascii=False)
        with self._lock:
            with self._path.open("a", encoding="utf-8") as fp:
                fp.write(line + "\n")


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    k = max(int(len(values) * p) - 1, 0)
    return values[k]


def summarize(counters: Counters, elapsed: float, total_requests: int) -> dict[str, object]:
    avg = sum(counters.latencies) / len(counters.latencies) if counters.latencies else 0.0
    return {
        "success": counters.success,
        "timeout": counters.timeout,
        "error": counters.error,
        "exceptions": counters.exceptions,
        "bytes_sent": counters.bytes_sent,
        "bytes_received": counters.bytes_received,
        "latency_avg_sec": round(avg, 4),
        "latency_p95_sec": round(percentile(counters.latencies, 0.95), 4),
        "latency_p99_sec": round(percentile(counters.latencies, 0.99), 4),
        "elapsed_sec": round(elapsed, 3),
        "rps": round(total_requests / elapsed, 2) if elapsed else total_requests,
    }


def build_tasks(total: int, urls: Sequence[str]) -> "queue.Queue[tuple[int, str]]":
    q: "queue.Queue[tuple[int, str]]" = queue.Queue()
    for idx in range(total):
        url = urls[idx % len(urls)]
        q.put((idx, url))
    return q


def worker_main(
    name: str,
    client: LoadTestClient,
    tasks: "queue.Queue[tuple[int, str]]",
    agg: Aggregator,
    delay: float,
    logger: LogWriter | None,
) -> None:
    while True:
        try:
            idx, url = tasks.get_nowait()
        except queue.Empty:
            return
        send_count = 2 if getattr(client, "_dual_send", False) else 1
        for attempt in range(send_count):
            msg_id = idx if attempt == 0 else idx + 1000000 * (attempt + 1)
            start = time.perf_counter()
            try:
                outcome = client.send_request(url, message_id=msg_id, timestamp=int(time.time()))
            except Exception as exc:  # noqa: BLE001
                elapsed = time.perf_counter() - start
                agg.add_exception()
                if logger:
                    logger.write(
                        {
                            "event": "exception",
                            "worker": name,
                            "url": url,
                            "message_id": msg_id,
                            "elapsed_sec": round(elapsed, 4),
                            "error": f"{exc.__class__.__name__}: {exc}",
                            "timestamp": time.time(),
                        }
                    )
                continue

            elapsed = time.perf_counter() - start
            agg.add(outcome, elapsed)
            if logger:
                logger.write(
                    {
                        "event": "outcome",
                        "worker": name,
                        "url": url,
                        "message_id": msg_id,
                        "elapsed_sec": round(elapsed, 4),
                        "complete": outcome.complete,
                        "timed_out": outcome.timed_out,
                        "status_code": outcome.status_code,
                        "error": outcome.error,
                        "bytes_sent": outcome.bytes_sent,
                        "bytes_received": outcome.bytes_received,
                        "timestamp": time.time(),
                    }
                )

        if delay:
            time.sleep(delay)


def load_urls(args: argparse.Namespace) -> list[str]:
    urls: list[str] = []
    if args.url_file:
        path = Path(args.url_file)
        urls.extend([line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()])
    if args.urls:
        urls.extend(args.urls)
    return urls or ["https://example.com/"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AKARI UDP load test runner")
    parser.add_argument("--host", default="127.0.0.1", help="Remote proxy host")
    parser.add_argument("--port", type=int, default=14500, help="Remote proxy port")
    parser.add_argument("--psk", default="test-psk-0000-test", help="PSK (text or hex if --hex is set)")
    parser.add_argument("--hex", action="store_true", help="Interpret PSK as hexadecimal")
    parser.add_argument("--protocol-version", type=int, default=2, choices=[1, 2], help="AKARI protocol version")
    parser.add_argument("--url", action="append", dest="urls", help="Target URL (can specify multiple)")
    parser.add_argument("--url-file", help="Path to file that lists target URLs line by line")
    parser.add_argument("--requests", type=int, default=200, help="Total request count")
    parser.add_argument("--concurrency", type=int, default=8, help="Number of worker threads")
    parser.add_argument("--timeout", type=float, default=3.0, help="UDP timeout per request (seconds)")
    parser.add_argument("--loss-rate", type=float, default=0.0, help="Probability to drop a received packet")
    parser.add_argument("--jitter", type=float, default=0.0, help="Maximum jitter (seconds) added after a receive")
    parser.add_argument("--flap-interval", type=float, default=0.0, help="Simulate flap: interval seconds for blackout cycle")
    parser.add_argument("--flap-duration", type=float, default=0.0, help="Simulate flap: duration seconds to drop packets each interval")
    parser.add_argument("--delay", type=float, default=0.0, help="Sleep after each request (seconds)")
    parser.add_argument("--max-nack-rounds", type=int, default=3, help="How many times to send NACK when missing chunks")
    parser.add_argument("--buffer-size", type=int, default=65535, help="Socket recv buffer size")
    parser.add_argument("--heartbeat-interval", type=float, default=0.0, help="Send lightweight re-probe after this idle time (seconds)")
    parser.add_argument("--heartbeat-backoff", type=float, default=1.5, help="Backoff multiplier for heartbeat retries")
    parser.add_argument("--max-retries", type=int, default=0, help="How many proactive re-sends to attempt on silence")
    parser.add_argument(
        "--initial-retry-delay",
        type=float,
        default=0.0,
        help="First retry delay (defaults to heartbeat interval if 0)",
    )
    parser.add_argument("--retry-jitter", type=float, default=0.0, help="Random jitter added to retry scheduling (seconds)")
    parser.add_argument("--dual-send", action="store_true", help="Send each request twice with different message ids")
    parser.add_argument("--log-file", type=str, help="Append request-level JSON lines to this path")
    parser.add_argument("--summary-file", type=str, help="Write summary JSON to this path")
    parser.add_argument("--demo-server", action="store_true", help="Start a local UDP responder to avoid real traffic")
    parser.add_argument("--demo-body", default="demo-response", help="Body text returned by the demo server")
    parser.add_argument("--demo-body-size", type=int, default=0, help="Generate a dummy body of this size (bytes) instead of --demo-body")
    parser.add_argument("--demo-body-file", type=str, help="Load response body from file path (binary)")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    return parser


def run_load_test(args: argparse.Namespace, *, configure_logging: bool = False) -> dict[str, object]:
    if configure_logging:
        logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(levelname)s %(name)s: %(message)s")

    psk = parse_psk(args.psk, hex_mode=args.hex)
    urls = load_urls(args)
    log_context = getattr(args, "log_context", None)
    logger = LogWriter(Path(args.log_file), extra=log_context) if args.log_file else None

    server: DemoServer | None = None
    target = (args.host, args.port)
    if args.demo_server:
        if args.demo_body_file:
            body_bytes = Path(args.demo_body_file).read_bytes()
        elif args.demo_body_size and args.demo_body_size > 0:
            seed = args.demo_body.encode("utf-8") if args.demo_body else b"x"
            seed_byte = seed[:1] or b"x"
            body_bytes = seed_byte * args.demo_body_size  # ensure exact byte length, avoid accidental multiplier
        else:
            body_bytes = args.demo_body.encode("utf-8")
        server = DemoServer(args.host, args.port, psk, body=body_bytes, timeout=args.timeout)
        server.start()
        target = server.address
        LOGGER.info("demo server listening on %s:%s", *target)

    tasks = build_tasks(args.requests, urls)
    agg = Aggregator()
    workers = []
    for i in range(args.concurrency):
        client = LoadTestClient(
            target,
            psk,
            timeout=args.timeout,
            loss_rate=args.loss_rate,
            jitter=args.jitter,
            flap_interval=args.flap_interval,
            flap_duration=args.flap_duration,
            protocol_version=args.protocol_version,
            max_nack_rounds=args.max_nack_rounds,
            buffer_size=args.buffer_size,
            heartbeat_interval=args.heartbeat_interval,
            heartbeat_backoff=args.heartbeat_backoff,
            max_retries=args.max_retries,
            initial_retry_delay=args.initial_retry_delay,
            retry_jitter=args.retry_jitter,
        )
        client._dual_send = args.dual_send  # opt-in dual send
        t = threading.Thread(
            target=worker_main,
            args=(f"worker-{i+1}", client, tasks, agg, args.delay, logger),
            daemon=True,
        )
        t.start()
        workers.append(t)

    start = time.perf_counter()
    for t in workers:
        t.join()
    elapsed = time.perf_counter() - start

    if server:
        server.stop()

    counters = agg.snapshot()
    summary = summarize(counters, elapsed, args.requests)
    if logger:
        logger.write({"event": "summary", "timestamp": time.time(), "summary": summary})
    if args.summary_file:
        Path(args.summary_file).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    summary = run_load_test(args, configure_logging=True)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
