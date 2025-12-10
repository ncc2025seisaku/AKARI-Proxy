"""非同期版リモートプロキシサーバ。

UDP受信はasyncioのDatagramProtocolで行い、HTTPフェッチを含むハンドラ処理は
デフォルトでスレッドプール上にオフロードする（fetchが同期のため）。
conf/remote.toml を読み込んで起動する。
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import socket
import sys
from pathlib import Path
from typing import Iterable, Sequence, Callable, Awaitable

from akari_udp_py import decode_packet_auto_py

from ..udp_server import IncomingRequest
from .config import ConfigError, load_config
from .handler import handle_request_async, set_require_encryption, set_fetch_async_func
from .http_client import fetch_async, DEFAULT_TIMEOUT

LOGGER = logging.getLogger(__name__)
DEFAULT_CONFIG = Path(__file__).resolve().parents[3] / "conf" / "remote.toml"
DEFAULT_SESSION_POOL_SIZE = 64
DEFAULT_RCVBUF = 1_048_576  # 1MB


class ReusableSessionPool:
    """再利用可能な aiohttp.ClientSession を前もって複数立ち上げて使い回すプール。"""

    def __init__(self, *, size: int, timeout: float, logger: logging.Logger, connector_limit: int | None = 0) -> None:
        self.size = max(1, size)
        self.timeout = timeout
        self.logger = logger
        self.connector_limit = connector_limit
        self._queue: asyncio.Queue = asyncio.Queue()
        self._closed = False

    async def start(self) -> None:
        for _ in range(self.size):
            await self._enqueue_new()

    async def _enqueue_new(self) -> None:
        if self._closed:
            return
        try:
            import aiohttp  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("aiohttp がインストールされていません") from exc

        timeout_cfg = aiohttp.ClientTimeout(total=self.timeout, sock_read=self.timeout, sock_connect=self.timeout)
        connector = aiohttp.TCPConnector(
            limit=self.connector_limit,  # 0 なら無制限、None なら aiohttp 既定（100）
            limit_per_host=0 if self.connector_limit == 0 else None,
            ttl_dns_cache=300,
            enable_cleanup_closed=True,
        )
        session = aiohttp.ClientSession(timeout=timeout_cfg, auto_decompress=False, connector=connector)
        await self._queue.put(session)

    async def acquire(self):
        if self._closed:
            raise RuntimeError("session pool is closed")
        return await self._queue.get()

    async def recycle(self, session) -> None:
        if self._closed:
            await session.close()
            return
        if session.closed:
            await self._enqueue_new()
        else:
            await self._queue.put(session)

    async def close(self) -> None:
        self._closed = True
        while not self._queue.empty():
            session = self._queue.get_nowait()
            try:
                await session.close()
            except Exception:
                self.logger.warning("failed to close aiohttp session", exc_info=True)


async def _process_datagram(
    data: bytes,
    addr,
    *,
    psk: bytes,
    handler: Callable[[IncomingRequest], Awaitable[Sequence[bytes]]],
    payload_max: int | None = None,
    buffer_size: int | None = None,
) -> Sequence[bytes] | None:
    try:
        parsed = decode_packet_auto_py(data, psk)
    except ValueError as exc:
        message = str(exc) or exc.__class__.__name__
        if message in {"HMAC mismatch", "invalid PSK"}:
            LOGGER.warning("discard packet from %s: %s (PSK mismatch?)", addr, message)
        else:
            LOGGER.warning("discard packet from %s: %s", addr, message)
        return None
    except Exception:
        LOGGER.exception("unexpected error while processing datagram from %s", addr)
        return None

    try:
        request = IncomingRequest(
            header=parsed["header"],
            payload=parsed["payload"],
            packet_type=parsed["type"],
            addr=addr,
            parsed=parsed,
            datagram=data,
            psk=psk,
            buffer_size=buffer_size or 65535,
            payload_max=payload_max,
        )
        LOGGER.debug(
            "decoded packet type=%s msg=%s ver=%s from=%s",
            parsed.get("type"),
            request.header.get("message_id"),
            request.header.get("version"),
            addr,
        )
        return await handler(request)
    except Exception:
        LOGGER.exception("unexpected error while processing datagram from %s", addr)
        return None


async def serve_remote_proxy_async(
    host: str,
    port: int,
    *,
    psk: bytes,
    protocol_version: int = 2,
    agg_tag: bool = True,
    payload_max: int = 1200,
    df: bool = True,
    plpmtud: bool = False,
    buffer_size: int = DEFAULT_RCVBUF,
    session_pool_size: int = DEFAULT_SESSION_POOL_SIZE,
    logger: logging.Logger | None = None,
    request_timeout: float | None = None,
) -> None:
    """asyncio版のリモートプロキシを起動する。"""

    logger = logger or LOGGER
    loop = asyncio.get_running_loop()

    timeout_value = request_timeout or DEFAULT_TIMEOUT

    session_pool = ReusableSessionPool(
        size=session_pool_size,
        timeout=timeout_value,
        logger=logger,
        connector_limit=0,  # 無制限で同時接続を張れるようにする（負荷試験向け）
    )
    await session_pool.start()

    # Windows 環境で ICMP Port Unreachable を受け取った際に ConnectionResetError で
    # トランスポートが閉じないよう無効化する。
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((host, port))
    sock.setblocking(True)  # 同期受信で ConnectionResetError を握り潰す
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, buffer_size)
        actual_rcvbuf = sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)
        logger.info("UDP SO_RCVBUF set to %s bytes", actual_rcvbuf)
    except OSError:
        logger.warning("could not set SO_RCVBUF to %s", buffer_size)
    if os.name == "nt":
        SIO_UDP_CONNRESET = getattr(socket, "SIO_UDP_CONNRESET", 0x9800000C)
        try:
            sock.ioctl(SIO_UDP_CONNRESET, b"\x00\x00\x00\x00")
        except (OSError, ValueError):
            logger.warning("could not disable UDP connreset (Windows); continuing")

    async def pooled_fetch_async(url: str):
        session = await session_pool.acquire()
        try:
            return await fetch_async(url, timeout=timeout_value, session=session)
        finally:
            await session_pool.recycle(session)

    set_fetch_async_func(pooled_fetch_async)

    async def handle_and_send(data: bytes, addr) -> None:
        datagrams = await _process_datagram(
            data,
            addr,
            psk=psk,
            handler=handle_request_async,
            payload_max=payload_max,
            buffer_size=buffer_size,
        )
        if not datagrams:
            return
        for dg in datagrams:
            try:
                LOGGER.debug("send datagram len=%d to %s", len(dg), addr)
                sock.sendto(bytes(dg), addr)
            except Exception:
                LOGGER.exception("failed to send datagram to %s", addr)

    async def recv_loop() -> None:
        while True:
            try:
                data, addr = await loop.run_in_executor(None, sock.recvfrom, buffer_size)
            except ConnectionResetError:
                LOGGER.debug("recvfrom ConnectionResetError (ignored)")
                continue
            except asyncio.CancelledError:
                break
            except Exception:
                LOGGER.exception("recvfrom failed")
                await asyncio.sleep(0.1)
                continue
            LOGGER.debug("recv datagram len=%d from %s", len(data), addr)
            loop.create_task(handle_and_send(data, addr))

    recv_task = asyncio.create_task(recv_loop())

    try:
        await asyncio.Future()  # run forever
    finally:
        recv_task.cancel()
        with contextlib.suppress(Exception):
            await recv_task
        sock.close()
        await session_pool.close()
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
            protocol_version=config.protocol_version,
            agg_tag=config.agg_tag,
            payload_max=config.payload_max,
            df=config.df,
            plpmtud=config.plpmtud,
            buffer_size=config.buffer_size,
            session_pool_size=DEFAULT_SESSION_POOL_SIZE,
            request_timeout=config.timeout or DEFAULT_TIMEOUT,
            # enforce encryption based on config
            logger=logging.getLogger("akari.remote_proxy.async_server"),
        )
    )


def run(argv: Iterable[str] | None = None) -> None:
    main(list(argv) if argv else None)


if __name__ == "__main__":
    main()

