"""CLI entry point for the AKARI Web proxy."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PY_DIR = PROJECT_ROOT / "py"
if str(PY_DIR) not in sys.path:
    sys.path.insert(0, str(PY_DIR))

from akari.web_proxy.config import ConfigError, WebProxyConfig, load_config  # noqa: E402
from akari.web_proxy.http_server import WebHttpServer  # noqa: E402
from akari.web_proxy.router import WebRouter  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AKARI Web Proxy (Web UI)")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "conf" / "web_proxy.toml"), help="Path to web proxy config")
    parser.add_argument("--static-dir", default=str(PY_DIR / "akari" / "web_proxy" / "static"))
    parser.add_argument("--entry-file", default="index.html", help="Entry HTML file under the static directory")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"設定エラー: {exc}")
        raise SystemExit(1) from exc

    router = WebRouter(config, Path(args.static_dir), args.entry_file)
    server = WebHttpServer(config, router)
    print(f"AKARI Web Proxy listening on http://{config.listen_host}:{config.listen_port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
