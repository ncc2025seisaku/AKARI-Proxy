#!/usr/bin/env python
"""
Compare actual bytes on the wire for:
  1) Direct HTTPS fetch (TCP/TLS/HTTP stack)
  2) AKARI-UDP fetch via AkariUdpClient (UDP encapsulation)

Direct mode counts NIC-level bytes (includes IP/TCP/TLS/HTTP overhead) via psutil.
AKARI mode reports UDP payload bytes; optionally, with --akari-nic it also logs NIC-level
bytes (adds IP/UDP headers, ARP, etc.) for the AKARI path.

Note: AKARI Proxy is not an HTTP proxy. This script talks to the remote proxy
over AKARI-UDP directly.
"""

import argparse
import time
from typing import Dict, Optional, Tuple, Iterable

import psutil
import requests
import sys
from pathlib import Path

# Add repository's py/ to import akari package when run from repo root
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "py"))

from akari import AkariUdpClient  # noqa: E402


# -------- NIC helpers (direct HTTPS path) ------------------------------------
def _choose_nic(name: str, available: Iterable[str]) -> str:
    """Choose NIC by exact -> startswith -> substring (case-insensitive)."""
    names = list(available)
    lower = {n.lower(): n for n in names}
    if name in names:
        return name
    if name.lower() in lower:
        return lower[name.lower()]

    starts = [n for n in names if n.lower().startswith(name.lower())]
    if len(starts) == 1:
        return starts[0]

    contains = [n for n in names if name.lower() in n.lower()]
    if len(contains) == 1:
        return contains[0]

    raise ValueError(
        f"NIC '{name}' not found. Available: {', '.join(names)}"
        + (" / ambiguous matches: " + ", ".join(starts + contains) if starts or contains else "")
    )


def snapshot_bytes(nic: Optional[str]) -> Tuple[int, int]:
    if nic:
        pernic = psutil.net_io_counters(pernic=True)
        chosen = _choose_nic(nic, pernic.keys())
        counters = pernic[chosen]
    else:
        counters = psutil.net_io_counters()
    return counters.bytes_sent, counters.bytes_recv


def run_once_direct(url: str, timeout: float, nic: Optional[str]) -> Tuple[int, int, float]:
    sent0, recv0 = snapshot_bytes(nic)
    t0 = time.perf_counter()
    requests.get(url, timeout=timeout)
    dt = time.perf_counter() - t0
    sent1, recv1 = snapshot_bytes(nic)
    return sent1 - sent0, recv1 - recv0, dt


def run_batch_direct(url: str, n: int, timeout: float, nic: Optional[str]) -> None:
    sent_list, recv_list, dt_list = [], [], []
    for i in range(n):
        try:
            s, r, d = run_once_direct(url, timeout, nic)
        except Exception as exc:  # noqa: BLE001
            print(f"[direct] #{i+1} fail: {exc}", file=sys.stderr)
            continue
        sent_list.append(s)
        recv_list.append(r)
        dt_list.append(d)
    _print_stats("direct", n, sent_list, recv_list, dt_list)


# -------- AKARI-UDP helpers --------------------------------------------------
def run_once_akari(
    client: AkariUdpClient,
    url: str,
    message_id: int,
    timestamp: int,
    nic: Optional[str],
) -> Tuple[int, int, float, int | None, Optional[int], Optional[int]]:
    sent0 = recv0 = None
    if nic:
        sent0, recv0 = snapshot_bytes(nic)
    t0 = time.perf_counter()
    outcome = client.send_request(url, message_id, timestamp)
    dt = time.perf_counter() - t0
    nic_sent = nic_recv = None
    if nic:
        sent1, recv1 = snapshot_bytes(nic)
        nic_sent = sent1 - sent0
        nic_recv = recv1 - recv0
    return outcome.bytes_sent, outcome.bytes_received, dt, outcome.status_code, nic_sent, nic_recv


def run_batch_akari(
    client: AkariUdpClient,
    url: str,
    n: int,
    nic: Optional[str],
) -> None:
    sent_list, recv_list, dt_list = [], [], []
    nic_sent_list, nic_recv_list = [], []
    codes = []
    base_ts = int(time.time())
    for i in range(n):
        try:
            s, r, d, code, ns, nr = run_once_akari(
                client, url, message_id=i + 1, timestamp=base_ts + i, nic=nic
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[akari-udp] #{i+1} fail: {exc}", file=sys.stderr)
            continue
        sent_list.append(s)
        recv_list.append(r)
        dt_list.append(d)
        codes.append(code)
        if ns is not None and nr is not None:
            nic_sent_list.append(ns)
            nic_recv_list.append(nr)
    _print_stats("akari-udp", n, sent_list, recv_list, dt_list, codes, nic_sent_list, nic_recv_list)


# -------- util ---------------------------------------------------------------
def _print_stats(
    label: str,
    n_expected: int,
    sent,
    recv,
    dt,
    codes=None,
    nic_sent=None,
    nic_recv=None,
) -> None:
    if not sent:
        print(f"[{label}] all attempts failed", file=sys.stderr)
        return
    avg = lambda xs: sum(xs) / len(xs)
    print(f"[{label}] n={len(sent)} / {n_expected} success")
    print(f"  sent avg={avg(sent):.0f}B  min={min(sent)}  max={max(sent)}")
    print(f"  recv avg={avg(recv):.0f}B  min={min(recv)}  max={max(recv)}")
    print(f"  time avg={avg(dt):.3f}s  min={min(dt):.3f}  max={max(dt):.3f}")
    if codes:
        ok = sum(1 for c in codes if c and 200 <= c < 400)
        print(f"  http status: {ok}/{len(codes)} in 2xx/3xx")
    if nic_sent:
        print(f"  nic-sent avg={avg(nic_sent):.0f}B  min={min(nic_sent)}  max={max(nic_sent)}")
    if nic_recv:
        print(f"  nic-recv avg={avg(nic_recv):.0f}B  min={min(nic_recv)}  max={max(nic_recv)}")
    print()


# -------- main ---------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Compare direct HTTPS vs AKARI-UDP bytes on the wire")
    ap.add_argument("--url", default="https://example.com", help="Target URL for fetching")
    ap.add_argument("-n", type=int, default=5, help="Repeat count per mode")
    ap.add_argument("--timeout", type=float, default=10, help="Timeout seconds for direct HTTPS")
    ap.add_argument("--nic", help="NIC name to measure (default: all NICs aggregate)")
    ap.add_argument("--remote-host", required=True, help="AKARI remote proxy host")
    ap.add_argument("--remote-port", type=int, required=True, help="AKARI remote proxy UDP port")
    ap.add_argument("--psk", help="Pre-shared key (utf-8 string)")
    ap.add_argument("--psk-hex", help="Pre-shared key (hex string). Overrides --psk when set.")
    ap.add_argument("--akari-version", type=int, choices=[1, 2], default=2, help="AKARI-UDP protocol version")
    ap.add_argument("--buffer-size", type=int, default=65535, help="UDP recv buffer size")
    ap.add_argument("--max-nack-rounds", type=int, default=3, help="Max NACK rounds for v2")
    ap.add_argument("--skip-direct", action="store_true", help="Skip direct HTTPS baseline")
    ap.add_argument("--akari-nic", help="NIC name to measure for AKARI path (optional, adds IP/UDP overhead)")
    ap.add_argument("--list-nic", action="store_true", help="Show available NIC names and exit")
    return ap.parse_args()


def build_psk(args: argparse.Namespace) -> bytes:
    if args.psk_hex:
        return bytes.fromhex(args.psk_hex)
    if args.psk is not None:
        return args.psk.encode("utf-8")
    raise SystemExit("PSK is required (use --psk or --psk-hex)")


def main() -> None:
    args = parse_args()
    if args.list_nic:
        pernic = psutil.net_io_counters(pernic=True)
        print("Available NICs:")
        for name in pernic.keys():
            print(f"- {name}")
        return
    psk = build_psk(args)

    if not args.skip_direct:
        run_batch_direct(args.url, args.n, args.timeout, args.nic)

    client = AkariUdpClient(
        (args.remote_host, args.remote_port),
        psk,
        timeout=args.timeout,
        buffer_size=args.buffer_size,
        protocol_version=args.akari_version,
        max_nack_rounds=args.max_nack_rounds,
    )
    run_batch_akari(client, args.url, args.n, args.akari_nic)


if __name__ == "__main__":
    main()
