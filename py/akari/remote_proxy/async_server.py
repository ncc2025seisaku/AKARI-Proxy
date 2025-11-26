"""非同期版リモートプロキシサーバ。

UDP受信はasyncioのDatagramProtocolで行い、HTTPフェッチを含むハンドラ処理は
デフォルトでスレッドプール上にオフロードする（fetchが同期のため）。
conf/remote.toml を読み込んで起動する。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Iterable, Sequence, Callable

from akari_udp_py import decode_packet_py

from ..udp_server import IncomingRequest
from .config import ConfigError, load_config
from .handler import handle_request

LOGGER = logging.getLogger(__name__)
DEFAULT_CONFIG = Path(__file__).resolve().parents[3] / "conf" / "remote.toml"


class RemoteProxyProtocol(asyncio.DatagramProtocol):
    def __init__(self, psk: bytes, handler: Callable[[IncomingRequest], Sequence[bytes]], loop: asyncio.AbstractEventLoop, executor: ThreadPoolExecutor):
        self.psk = psk
        self.handler = handler
        self.loop = loop
        self.executor = executor
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]
        sockname = transport.get_extra_info("sockname")
        LOGGER.info("AKARI async remote proxy listening on %s", sockname)

    def datagram_received(self, data: bytes, addr) -> None:
        # fire-and-forgetタスクで処理（送信も含む）
        self.loop.create_task(self._process_datagram(data, addr))

    async def _process_datagram(self, data: bytes, addr) -> None:
        try:
            parsed = await self.loop.run_in_executor(self.executor, decode_packet_py, data, self.psk)
            request = IncomingRequest(
                header=parsed["header"],
                payload=parsed["payload"],
                packet_type=parsed["type"],
                addr=addr,
                parsed=parsed,
                datagram=data,
                psk=self.psk,
            )
            datagrams = await self.loop.run_in_executor(self.executor, self.handler, request)
            if not self.transport:
                return
            for dg in datagrams:
                try:
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
    workers: int | None = None,
) -> None:
    """asyncio版のリモートプロキシを起動する。"""

    logger = logger or LOGGER
    loop = asyncio.get_running_loop()
    executor = ThreadPoolExecutor(max_workers=workers)

    transport, _protocol = await loop.create_datagram_endpoint(
        lambda: RemoteProxyProtocol(psk, handle_request, loop, executor),
        local_addr=(host, port),
        allow_broadcast=False,
    )

    try:
        await asyncio.Future()  # run forever
    finally:
        transport.close()
        executor.shutdown(wait=False)
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
    parser.add_argument("--workers", type=int, help="ThreadPool max workers for handler/fetch (default: Python executor default)")
    parser.add_argument("--log-level", help="override logging level (default: config.log_level)")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    log_level = args.log_level or config.log_level
    logging.basicConfig(level=getattr(logging, log_level.upper(), logging.INFO), format="%(levelname)s %(name)s: %(message)s")

    asyncio.run(
        serve_remote_proxy_async(
            config.host,
            config.port,
            psk=config.psk,
            workers=args.workers,
            logger=logging.getLogger("akari.remote_proxy.async_server"),
        )
    )


def run(argv: Iterable[str] | None = None) -> None:
    main(list(argv) if argv else None)


if __name__ == "__main__":
    main()
