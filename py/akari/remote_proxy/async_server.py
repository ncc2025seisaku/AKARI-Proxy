"""非同期版リモートプロキシサーバ。

UDP受信はasyncioのDatagramProtocolで行い、HTTPフェッチを含むハンドラ処理は
デフォルトでスレッドプール上にオフロードする（fetchが同期のため）。
conf/remote.toml を読み込んで起動する。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import socket
import sys
from pathlib import Path
from typing import Iterable, Sequence, Callable, Awaitable

from akari_udp_py import decode_packet_py

from ..udp_server import IncomingRequest
from .config import ConfigError, load_config
from .handler import handle_request_async, set_require_encryption

LOGGER = logging.getLogger(__name__)
DEFAULT_CONFIG = Path(__file__).resolve().parents[3] / "conf" / "remote.toml"


class RemoteProxyProtocol(asyncio.DatagramProtocol):
    def __init__(self, psk: bytes, handler: Callable[[IncomingRequest], Awaitable[Sequence[bytes]]], loop: asyncio.AbstractEventLoop):
        self.psk = psk
        self.handler = handler
        self.loop = loop
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]
        sockname = transport.get_extra_info("sockname")
        LOGGER.info("AKARI async remote proxy listening on %s", sockname)

    def datagram_received(self, data: bytes, addr) -> None:
        # fire-and-forgetタスクで処理（送信も含む）
        LOGGER.debug("recv datagram len=%d from %s", len(data), addr)
        self.loop.create_task(self._process_datagram(data, addr))

    async def _process_datagram(self, data: bytes, addr) -> None:
        try:
            parsed = await self.loop.run_in_executor(None, decode_packet_py, data, self.psk)
        except ValueError as exc:
            message = str(exc) or exc.__class__.__name__
            if message in {"HMAC mismatch", "invalid PSK"}:
                LOGGER.warning("discard packet from %s: %s (PSK mismatch?)", addr, message)
            else:
                LOGGER.warning("discard packet from %s: %s", addr, message)
            return
        except Exception:
            LOGGER.exception("unexpected error while processing datagram from %s", addr)
            return

        try:
            request = IncomingRequest(
                header=parsed["header"],
                payload=parsed["payload"],
                packet_type=parsed["type"],
                addr=addr,
                parsed=parsed,
                datagram=data,
                psk=self.psk,
            )
            LOGGER.debug(
                "decoded packet type=%s msg=%s ver=%s from=%s",
                parsed.get("type"),
                request.header.get("message_id"),
                request.header.get("version"),
                addr,
            )
            datagrams = await self.handler(request)
            if not self.transport:
                return
            for dg in datagrams:
                try:
                    LOGGER.debug("send datagram len=%d to %s", len(dg), addr)
                    self.transport.sendto(bytes(dg), addr)
                except Exception:
                    LOGGER.exception("failed to send datagram to %s", addr)
        except Exception:
            LOGGER.exception("unexpected error while processing datagram from %s", addr)


async def serve_remote_proxy_async(
    host: str,
    port: int,
    *,
    psk: bytes,
    logger: logging.Logger | None = None,
) -> None:
    """asyncio版のリモートプロキシを起動する。"""

    logger = logger or LOGGER
    loop = asyncio.get_running_loop()

    # Windows 環境で ICMP Port Unreachable を受け取った際に ConnectionResetError で
    # トランスポートが閉じないよう無効化する。
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((host, port))
    sock.setblocking(False)
    if os.name == "nt":
        SIO_UDP_CONNRESET = getattr(socket, "SIO_UDP_CONNRESET", 0x9800000C)
        try:
            sock.ioctl(SIO_UDP_CONNRESET, b"\x00\x00\x00\x00")
        except (OSError, ValueError):
            logger.warning("could not disable UDP connreset (Windows); continuing")

    transport, _protocol = await loop.create_datagram_endpoint(
        lambda: RemoteProxyProtocol(psk, handle_request_async, loop),
        sock=sock,
        allow_broadcast=False,
    )

    try:
        await asyncio.Future()  # run forever
    finally:
        transport.close()
        logger.info("async remote proxy stopped")


def parse_psk(value: str, *, hex_mode: bool) -> bytes:
    if hex_mode:
        return bytes.fromhex(value)
    return value.encode("utf-8")


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run AKARI remote UDP server (async)")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="Path to remote proxy configuration (default: conf/remote.toml)",
    )
    parser.add_argument("--workers", type=int, default=None, help="(unused, kept for compatibility)")
    parser.add_argument("--log-level", help="override logging level (default: config.log_level)")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    log_level = args.log_level or config.log_level
    logging.basicConfig(level=getattr(logging, log_level.upper(), logging.INFO), format="%(levelname)s %(name)s: %(message)s")

    set_require_encryption(config.require_encryption)
    asyncio.run(
        serve_remote_proxy_async(
            config.host,
            config.port,
            psk=config.psk,
            # enforce encryption based on config
            logger=logging.getLogger("akari.remote_proxy.async_server"),
        )
    )


def run(argv: Iterable[str] | None = None) -> None:
    main(list(argv) if argv else None)


if __name__ == "__main__":
    main()
