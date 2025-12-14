#!/usr/bin/env python3
"""HTTPS 直接取得と AKARI-UDP 経由取得のネットワーク送受信バイト数を比較・検証するスクリプト."""

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
import csv
import json
import concurrent.futures
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, List
from urllib.parse import urljoin, urlsplit

# Try to import rich for better output, fallback to standard print
try:
    from rich.console import Console
    from rich.table import Table
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PY_DIR = PROJECT_ROOT / "py"
if str(PY_DIR) not in sys.path:
    sys.path.insert(0, str(PY_DIR))

from akari.udp_client import AkariUdpClient  # noqa: E402
from akari.web_proxy.config import ConfigError, WebProxyConfig, load_config  # noqa: E402

ACCEPT_ENCODING = "br, gzip, deflate"
USER_AGENT = "AKARI-Proxy/0.1"
DEFAULT_MAX_BODY_BYTES = 100_000_000  # 100MB to allow large files
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
LOGGER = logging.getLogger("akari.compare")


@dataclass
class TrafficStats:
    protocol: str
    url: str
    status_code: int | None
    payload_bytes: int
    wire_bytes_sent: int
    wire_bytes_received: int
    time_total: float
    error: str | None = None

    @property
    def total_wire_bytes(self) -> int:
        return self.wire_bytes_sent + self.wire_bytes_received

    @property
    def overhead_bytes(self) -> int:
        # Avoid negative overhead if estimation is slightly off for very small packets
        return max(0, self.total_wire_bytes - self.payload_bytes)

    @property
    def overhead_ratio(self) -> float:
        if self.payload_bytes == 0:
            return 0.0
        return (self.overhead_bytes / self.payload_bytes) * 100.0


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

    def recv_into(self, buffer, nbytes: int = 0, *args) -> int:
        read = super().recv_into(buffer, nbytes, *args)
        self.bytes_received += max(read, 0)
        return read

    def sendto(self, data: bytes, *args, **kwargs) -> int:  # type: ignore[override]
        sent = super().sendto(data, *args, **kwargs)
        self.bytes_sent += sent
        return sent

    def recvfrom(self, bufsize: int, *args, **kwargs):  # type: ignore[override]
        data, addr = super().recvfrom(bufsize, *args, **kwargs)
        self.bytes_received += len(data)
        return data, addr


class CountingSocketWrapper:
    """任意のソケット（平文/SSL問わず）をラップして送受信バイトを計測する薄いデリゲータ."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self.bytes_sent = 0
        self.bytes_received = 0

        # 元のメソッドを退避し、ファイルオブジェクト経由の呼び出しも捕捉するためにパッチする
        self._orig_send = getattr(sock, "send", None)
        self._orig_sendall = getattr(sock, "sendall", None)
        self._orig_sendto = getattr(sock, "sendto", None)
        self._orig_recv = getattr(sock, "recv", None)
        self._orig_recv_into = getattr(sock, "recv_into", None)
        self._orig_recvfrom = getattr(sock, "recvfrom", None)

        # 受信側のみ確実にカウントするためパッチ（ファイルオブジェクトが直接 sock.recv を叩くケースを拾う）
        if self._orig_recv:
            orig = self._orig_recv

            def _patched_recv(bufsize, *args, **kwargs):
                data = orig(bufsize, *args, **kwargs)
                self.bytes_received += len(data)
                return data

            sock.recv = _patched_recv  # type: ignore[assignment]

        if self._orig_recv_into:
            orig_into = self._orig_recv_into

            def _patched_recv_into(buffer, nbytes: int = 0, *args):
                read = orig_into(buffer, nbytes, *args)
                self.bytes_received += max(read, 0)
                return read

            sock.recv_into = _patched_recv_into  # type: ignore[assignment]

    # --- 送信系 ---
    def send(self, data: bytes, *args, **kwargs) -> int:  # type: ignore[override]
        if self._orig_send is None:
            return self._sock.send(data, *args, **kwargs)
        sent = self._orig_send(data, *args, **kwargs)
        self.bytes_sent += sent
        return sent

    def sendall(self, data: bytes, *args, **kwargs) -> None:  # type: ignore[override]
        if self._orig_sendall:
            self._orig_sendall(data, *args, **kwargs)
        else:
            self._sock.sendall(data, *args, **kwargs)
        self.bytes_sent += len(data)

    def sendto(self, data: bytes, *args, **kwargs) -> int:  # type: ignore[override]
        if self._orig_sendto is None:
            sent = self._sock.sendto(data, *args, **kwargs)
        else:
            sent = self._orig_sendto(data, *args, **kwargs)
        self.bytes_sent += sent
        return sent

    # --- 受信系 ---
    def recv(self, bufsize: int, *args, **kwargs) -> bytes:  # type: ignore[override]
        if self._orig_recv is None:
            data = self._sock.recv(bufsize, *args, **kwargs)
        else:
            data = self._orig_recv(bufsize, *args, **kwargs)
        self.bytes_received += len(data)
        return data

    def recv_into(self, buffer, nbytes: int = 0, *args) -> int:
        if self._orig_recv_into is None:
            read = self._sock.recv_into(buffer, nbytes, *args)
        else:
            read = self._orig_recv_into(buffer, nbytes, *args)
        self.bytes_received += max(read, 0)
        return read

    def recvfrom(self, bufsize: int, *args, **kwargs):  # type: ignore[override]
        if self._orig_recvfrom is None:
            data, addr = self._sock.recvfrom(bufsize, *args, **kwargs)
        else:
            data, addr = self._orig_recvfrom(bufsize, *args, **kwargs)
        self.bytes_received += len(data)
        return data, addr

    # --- その他の属性・メソッドは素通し ---
    def __getattr__(self, name):
        return getattr(self._sock, name)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return self._sock.__exit__(*exc) if hasattr(self._sock, "__exit__") else False


class CountingHTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._counter: CountingSocketWrapper | None = None

    def connect(self) -> None:
        raw_sock = socket.create_connection(
            (self.host, self.port),
            self.timeout,
            self.source_address,
        )
        counter = CountingSocketWrapper(raw_sock)
        self._counter = counter
        self.sock = counter

    @property
    def bytes_sent(self) -> int:
        return self._counter.bytes_sent if self._counter else 0

    @property
    def bytes_received(self) -> int:
        return self._counter.bytes_received if self._counter else 0


class CountingHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, **kwargs) -> None:
        context = kwargs.pop("context", ssl.create_default_context())
        super().__init__(*args, context=context, **kwargs)
        self._counter: CountingSocketWrapper | None = None

    def connect(self) -> None:
        base_sock = socket.create_connection(
            (self.host, self.port),
            self.timeout,
            self.source_address,
        )
        # トンネルが必要なら先に素のソケットで CONNECT する
        if self._tunnel_host:
            self.sock = base_sock
            self._tunnel()

        ssl_sock = self._context.wrap_socket(base_sock, server_hostname=self.host)
        counter = CountingSocketWrapper(ssl_sock)
        self._counter = counter
        self.sock = counter  # type: ignore[assignment]

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


def fetch_https_stats(
    url: str,
    *,
    timeout: float,
    max_body_bytes: int,
    max_redirects: int,
    context: ssl.SSLContext | None = None,
) -> TrafficStats:
    start_time = time.time()
    current = url
    total_sent = 0
    total_received = 0
    status_code: int | None = None
    payload_size = 0
    error_msg = None

    try:
        for _ in range(max_redirects + 1):
            parsed = urlsplit(current)
            host = parsed.hostname or ""
            port = parsed.port or (443 if parsed.scheme == "https" else 80)

            if parsed.scheme == "https":
                conn = CountingHTTPSConnection(host, port, timeout=timeout, context=context)
            elif parsed.scheme == "http":
                # Only if explicitly allowed or local testing
                conn = CountingHTTPConnection(host, port, timeout=timeout)
            else:
                 raise ValueError("http/https URL required")

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
                
                payload_size = len(body)
                if len(body) > max_body_bytes:
                    payload_size = max_body_bytes  # Just cap for reporting if truncated

                status_code = resp.status
                location = resp.getheader("Location")
                total_sent += conn.bytes_sent
                total_received += conn.bytes_received
            except Exception as e:
                error_msg = str(e)
                # Ensure we capture what was sent/recv even on error if possible
                if conn._counter:
                    total_sent += conn.bytes_sent
                    total_received += conn.bytes_received
                break
            finally:
                conn.close()

            # Approximation for plaintext if counter failed (shouldn't happen with our wrapper)
            if total_sent == 0 and not error_msg:
                 # Logic for manual calculation removed favoring strict socket counting
                 pass

            if status_code in REDIRECT_STATUSES and location:
                # Redirect logic - continue loop
                next_url = urljoin(current, location)
                current = next_url
                continue
            break
            
    except Exception as e:
        error_msg = str(e)

    duration = time.time() - start_time
    
    return TrafficStats(
        protocol="HTTPS",
        url=url,
        status_code=status_code,
        payload_bytes=payload_size,
        wire_bytes_sent=total_sent,
        wire_bytes_received=total_received,
        time_total=duration,
        error=error_msg,
    )


def fetch_udp_stats(
    url: str,
    config: WebProxyConfig,
    *,
    use_encryption: bool,
    timeout: float | None = None,
    retries: int = 1,
    protocol_version: int | None = None,
    agg_tag: bool = False,
    df: bool = True,
) -> TrafficStats:
    start_time = time.time()
    remote = config.remote
    message_id = (secrets.randbelow(0xFFFF) or 1)
    
    payload_size = 0
    bytes_sent = 0
    bytes_received = 0
    status_code = None
    error_msg = None

    client = AkariUdpClient(
        (remote.host, remote.port),
        remote.psk,
        timeout=timeout if timeout is not None else remote.timeout,
        max_nack_rounds=None,
        max_ack_rounds=0,
        use_encryption=use_encryption,
        protocol_version=protocol_version or getattr(remote, "protocol_version", 2),
        initial_request_retries=retries,
        agg_tag=agg_tag,
        df=df,
    )

    try:
        outcome = client.send_request(url, message_id, int(time.time()))
        bytes_sent = outcome.bytes_sent
        bytes_received = outcome.bytes_received
        status_code = outcome.status_code
        if outcome.body:
            payload_size = len(outcome.body)
        
        if outcome.error:
            error_msg = outcome.error
        elif outcome.timed_out:
            error_msg = "Timeout"
        elif not outcome.complete:
            error_msg = "Incomplete Response"

    except Exception as e:
        error_msg = str(e)

    duration = time.time() - start_time

    return TrafficStats(
        protocol="UDP",
        url=url,
        status_code=status_code,
        payload_bytes=payload_size,
        wire_bytes_sent=bytes_sent,
        wire_bytes_received=bytes_received,
        time_total=duration,
        error=error_msg,
    )


def run_comparison(
    urls: List[str],
    config: WebProxyConfig,
    args: argparse.Namespace
) -> List[dict]:
    results = []
    
    context = None
    if args.ctx_insecure:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency * 2) as executor:
        future_to_url = {}
        for url in urls:
            # Schedule HTTPS
            f_https = executor.submit(
                fetch_https_stats, 
                url, 
                timeout=args.timeout, 
                max_body_bytes=args.max_body_bytes,
                max_redirects=args.max_redirects,
                context=context
            )
            # Schedule UDP
            f_udp = executor.submit(
                fetch_udp_stats,
                url,
                config,
                use_encryption=args.enc,
                timeout=args.udp_timeout,
                retries=args.udp_retries,
                protocol_version=args.udp_version,
                agg_tag=args.agg_tag,
                df=not args.df_off,
            )
            future_to_url[url] = (f_https, f_udp)

        for url, (f_h, f_u) in future_to_url.items():
            h_stats = f_h.result()
            u_stats = f_u.result()
            
            # Calculate improvements
            sent_reduction = 0.0
            if h_stats.wire_bytes_sent > 0:
                sent_reduction = (1 - u_stats.wire_bytes_sent / h_stats.wire_bytes_sent) * 100
                
            recv_reduction = 0.0
            if h_stats.wire_bytes_received > 0:
                recv_reduction = (1 - u_stats.wire_bytes_received / h_stats.wire_bytes_received) * 100

            results.append({
                "url": url,
                "payload_bytes": h_stats.payload_bytes if h_stats.payload_bytes > 0 else u_stats.payload_bytes,
                
                "https_status": h_stats.status_code,
                "https_sent": h_stats.wire_bytes_sent,
                "https_recv": h_stats.wire_bytes_received,
                "https_time": h_stats.time_total,
                "https_overhead": h_stats.overhead_ratio,

                "udp_status": u_stats.status_code,
                "udp_sent": u_stats.wire_bytes_sent,
                "udp_recv": u_stats.wire_bytes_received,
                "udp_time": u_stats.time_total,
                "udp_overhead": u_stats.overhead_ratio,
                
                "sent_reduction_pct": sent_reduction,
                "recv_reduction_pct": recv_reduction,
                "error": h_stats.error or u_stats.error,
            })
    return results


def print_results(results: List[dict], output_format: str):
    if output_format == "json":
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return

    if output_format == "csv":
        writer = csv.writer(sys.stdout)
        header = [
            "url", "payload_bytes", 
            "https_status", "https_sent", "https_recv", "https_time", "https_overhead_pct",
            "udp_status", "udp_sent", "udp_recv", "udp_time", "udp_overhead_pct",
            "sent_reduction_pct", "recv_reduction_pct"
        ]
        writer.writerow(header)
        for r in results:
            writer.writerow([
                r["url"], r["payload_bytes"],
                r["https_status"], r["https_sent"], r["https_recv"], f"{r['https_time']:.3f}", f"{r['https_overhead']:.2f}",
                r["udp_status"], r["udp_sent"], r["udp_recv"], f"{r['udp_time']:.3f}", f"{r['udp_overhead']:.2f}",
                f"{r['sent_reduction_pct']:.2f}", f"{r['recv_reduction_pct']:.2f}"
            ])
        return

    # Text/Table output
    if RICH_AVAILABLE and output_format == "table":
        console = Console()
        table = Table(title="AKARI-UDP vs HTTPS Traffic Comparison")
        table.add_column("URL", style="cyan", no_wrap=True)
        table.add_column("Payload", justify="right")
        table.add_column("Reduce(Recv)", justify="right", style="green")
        table.add_column("HTTPS (Recv/Overhead)", justify="right")
        table.add_column("UDP (Recv/Overhead)", justify="right")
        table.add_column("Time (H/U)", justify="right")

        for r in results:
            payload_str = f"{r['payload_bytes']:,}"
            reduce_str = f"{r['recv_reduction_pct']:.1f}%"
            
            https_info = f"{r['https_recv']:,} / {r['https_overhead']:.1f}%"
            udp_info = f"{r['udp_recv']:,} / {r['udp_overhead']:.1f}%"
            time_info = f"{r['https_time']:.2f}s / {r['udp_time']:.2f}s"
            
            if r['error']:
                 table.add_row(r['url'], "ERROR", "-", r['error'], "-", "-")
            else:
                 table.add_row(r['url'], payload_str, reduce_str, https_info, udp_info, time_info)
        console.print(table)
    else:
        # Fallback text output
        for r in results:
            print(f"--- {r['url']} ---")
            if r['error']:
                print(f"Error: {r['error']}")
                continue
            print(f"Payload: {r['payload_bytes']:,} bytes")
            print(f"HTTPS: Recv {r['https_recv']:,} (Overhead {r['https_overhead']:.1f}%) Time {r['https_time']:.2f}s")
            print(f"UDP  : Recv {r['udp_recv']:,} (Overhead {r['udp_overhead']:.1f}%) Time {r['udp_time']:.2f}s")
            print(f"Reduction: {r['recv_reduction_pct']:.1f}%")
            print("")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="HTTPS vs AKARI-UDP Comparison Tool")
    parser.add_argument("--url", action="append", help="Target URL (can specify multiple)")
    parser.add_argument("--file", help="File containing URLs (one per line)")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "conf" / "web_proxy.toml"))
    parser.add_argument("--format", choices=["text", "table", "json", "csv"], default="table")
    parser.add_argument("--ctx-insecure", action="store_true", help="Skip SSL verification")
    parser.add_argument("--concurrency", type=int, default=1, help="Number of concurrent URL checks")
    
    # Tuning params
    parser.add_argument("--timeout", type=float, default=10.0, help="HTTPS timeout")
    parser.add_argument("--max-body-bytes", type=int, default=DEFAULT_MAX_BODY_BYTES)
    parser.add_argument("--max-redirects", type=int, default=3)
    parser.add_argument("--enc", action="store_true", help="Enable UDP Encryption")
    parser.add_argument("--udp-timeout", type=float, default=None)
    parser.add_argument("--udp-retries", type=int, default=1)
    parser.add_argument("--udp-version", type=int, default=None)
    parser.add_argument("--agg-tag", action="store_true")
    parser.add_argument("--df-off", action="store_true")
    
    args = parser.parse_args()
    if not args.url and not args.file:
        parser.error("At least one --url or --file must be specified")
    return args


def main() -> None:
    args = parse_args()
    
    # Load URLs
    urls = []
    if args.url:
        urls.extend(args.url)
    if args.file:
        with open(args.file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    urls.append(line)
    
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"Config load failed: {exc}")
        sys.exit(1)

    results = run_comparison(urls, config, args)
    print_results(results, args.format)


if __name__ == "__main__":
    main()
