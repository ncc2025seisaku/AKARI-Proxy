"""Lightweight self-check runner for AKARI Proxy.

実行すると主要な挙動をざっくり検証し、期待値と実際値を表示します。
外部ネットワークアクセスや実サーバ起動は行いません。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "py"))

from akari_udp_py import decode_packet_py, encode_request_v2_py  # type: ignore
from akari.remote_proxy import handler as remote_handler  # type: ignore
from akari.udp_server import IncomingRequest  # type: ignore

PSK = b"test-psk-0000-test"
FLAG_ENCRYPT = 0x80


@dataclass
class Check:
    name: str
    fn: Callable[[], None]


def check_encrypt_round_trip() -> None:
    msg_id = 0x1234
    ts = 0x55
    datagram = encode_request_v2_py("get", "https://example.com", b"", msg_id, ts, FLAG_ENCRYPT, PSK)
    parsed = decode_packet_py(datagram, PSK)
    assert parsed["header"]["flags"] & FLAG_ENCRYPT, "E flag not set in header"
    assert parsed["payload"]["url"] == "https://example.com"


def check_require_encryption_guard() -> None:
    remote_handler.set_require_encryption(True)
    req = IncomingRequest(
        header={"message_id": 1, "timestamp": 1, "version": 2, "flags": 0},
        payload={"url": "https://example.com"},
        packet_type="req",
        addr=("127.0.0.1", 9999),
        parsed={},
        datagram=b"",
        psk=PSK,
    )
    res = remote_handler.handle_request(req)
    remote_handler.set_require_encryption(False)
    assert res, "expected error datagram"
    parsed = decode_packet_py(bytes(res[0]), PSK)
    assert parsed["payload"]["error_code"] == remote_handler.ERROR_UNSUPPORTED_PACKET, "unexpected error_code"


def main() -> int:
    checks = [
        Check("encrypt_round_trip", check_encrypt_round_trip),
        Check("require_encryption_guard", check_require_encryption_guard),
    ]
    failed = 0
    for chk in checks:
        try:
            chk.fn()
            print(f"[PASSED] {chk.name}")
        except AssertionError as exc:
            print(f"[FAILED] {chk.name}: {exc}")
            failed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"[ERROR ] {chk.name}: {exc}")
            failed += 1
    if failed:
        print(f"\nRESULT: FAILED ({failed} failed)")
    else:
        print("\nRESULT: PASSED")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
