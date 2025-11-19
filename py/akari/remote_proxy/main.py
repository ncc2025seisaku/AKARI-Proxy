"""本番用の AKARI Remote Proxy 起動ロジック。"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Iterable, Sequence

from .config import ConfigError, load_config
from .server import serve_remote_proxy

DEFAULT_CONFIG = Path(__file__).resolve().parents[3] / "conf" / "remote.toml"


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AKARI Remote Proxy Server")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="Path to remote proxy configuration (default: conf/remote.toml)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = _parse_args(argv)
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"設定エラー: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    logging.basicConfig(level=getattr(logging, config.log_level.upper(), logging.INFO), format="%(levelname)s %(name)s: %(message)s")
    serve_remote_proxy(
        config.host,
        config.port,
        psk=config.psk,
        timeout=config.timeout,
        buffer_size=config.buffer_size,
        logger=logging.getLogger("akari.remote_proxy.server"),
    )


def run(argv: Iterable[str] | None = None) -> None:
    main(list(argv) if argv else None)
