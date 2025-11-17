"""テスト用のリモートプロキシサーバを起動するラッパー。"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_PY_DIR = _ROOT / "py"
if str(_PY_DIR) not in sys.path:
    sys.path.insert(0, str(_PY_DIR))

from akari.remote_proxy.server import serve_remote_proxy


def parse_psk(value: str, *, hex_mode: bool) -> bytes:
    if hex_mode:
        return bytes.fromhex(value)
    return value.encode("utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run AKARI remote proxy server for testing")
    parser.add_argument("--host", default="0.0.0.0", help="bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=14500, help="bind port (default: 14500)")
    parser.add_argument("--psk", default="test-psk-0000-test", help="pre-shared key (plain text)")
    parser.add_argument("--hex", action="store_true", help="interpret --psk as hex string")
    parser.add_argument("--timeout", type=float, help="socket timeout for recvfrom")
    parser.add_argument("--buffer-size", type=int, default=65535, help="UDP receive buffer size")
    parser.add_argument("--log-level", default="INFO", help="logging level")
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(levelname)s %(name)s: %(message)s")
    psk = parse_psk(args.psk, hex_mode=args.hex)

    serve_remote_proxy(
        args.host,
        args.port,
        psk=psk,
        timeout=args.timeout,
        buffer_size=args.buffer_size,
        logger=logging.getLogger("akari.remote_proxy.server"),
    )


if __name__ == "__main__":
    main()
