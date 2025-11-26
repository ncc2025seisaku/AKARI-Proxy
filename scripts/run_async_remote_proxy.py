"""CLI entrypoint for the AKARI Remote proxy server (asyncio version)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PY_DIR = PROJECT_ROOT / "py"
if str(PY_DIR) not in sys.path:
    sys.path.insert(0, str(PY_DIR))

from akari.remote_proxy.async_server import main  # noqa: E402


def run() -> None:
    main()


if __name__ == "__main__":
    run()
