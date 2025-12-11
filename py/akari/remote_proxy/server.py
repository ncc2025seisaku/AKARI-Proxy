"""外部プロキシ用の UDP サーバランナー."""

from __future__ import annotations

import argparse
import logging
from typing import Iterable, Sequence

from ..udp_server import AkariUdpServer
from .handler import handle_request, set_require_encryption

LOGGER = logging.getLogger(__name__)


def parse_psk(value: str, *, hex_mode: bool) -> bytes:
    if hex_mode:
        return bytes.fromhex(value)
    return value.encode("utf-8")


def serve_remote_proxy(
    host: str,
    port: int,
    *,
    psk: bytes,
    timeout: float | None = None,
    buffer_size: int = 65535,
    payload_max: int | None = None,
    require_encryption: bool = False,
    df: bool = True,
    logger: logging.Logger | None = None,
) -> None:
    """AkariUdpServer を立ち上げて handle_request を呼び出す."""

    logger = logger or LOGGER
    set_require_encryption(require_encryption)
    with AkariUdpServer(
        host,
        port,
        psk,
        handle_request,
        timeout=timeout,
        buffer_size=buffer_size,
        payload_max=payload_max,
        df=df,
    ) as server:
        logger.info("AKARI remote proxy listening on %s:%s", *server.address)
        while True:
            try:
                request = server.handle_next()
            except KeyboardInterrupt:
                logger.info("shutting down (keyboard interrupt)")
                break
            except Exception:
                logger.exception("unexpected error while serving request")
                continue

            if request is None:
                continue

            logger.debug(
                "processed message_id=%s from=%s url=%s",
                request.header.get("message_id"),
                request.addr,
                request.payload.get("url"),
            )


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run AKARI remote UDP server")
    parser.add_argument("--host", default="0.0.0.0", help="bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=14500, help="bind port")
    parser.add_argument("--psk", default="test-psk-0000-test", help="pre-shared key (plain text)")
    parser.add_argument("--hex", action="store_true", help="interpret --psk as hex string")
    parser.add_argument("--timeout", type=float, help="socket timeout for recvfrom")
    parser.add_argument("--buffer-size", type=int, default=65535, help="UDP receive buffer size")
    parser.add_argument("--payload-max", type=int, help="maximum UDP datagram size for payload splitting")
    parser.add_argument("--require-encryption", action="store_true", help="reject requests without E flag")
    parser.add_argument("--no-df", action="store_true", help="allow IP fragmentation (DF off)")
    parser.add_argument("--log-level", default="INFO", help="logging level (INFO/DEBUG/...)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(levelname)s %(name)s: %(message)s")
    psk = parse_psk(args.psk, hex_mode=args.hex)
    serve_remote_proxy(
        args.host,
        args.port,
        psk=psk,
        timeout=args.timeout,
        buffer_size=args.buffer_size,
        payload_max=args.payload_max,
        require_encryption=args.require_encryption,
        df=not args.no_df,
        logger=logging.getLogger("akari.remote_proxy.server"),
    )


def run(argv: Iterable[str] | None = None) -> None:
    main(list(argv) if argv else None)


if __name__ == "__main__":
    main()
