"""設定ファイルからリモートプロキシの起動設定を読み込む。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomllib


@dataclass(frozen=True)
class RemoteProxyConfig:
    host: str
    port: int
    timeout: float | None
    buffer_size: int
    log_level: str
    psk: bytes


class ConfigError(ValueError):
    """設定がおかしいときに投げる例外。"""


def load_config(path: str | Path) -> RemoteProxyConfig:
    data = _read_toml(path)
    server_data = data.get("server", {})

    host = _require_str(server_data, "host", default="0.0.0.0")
    port = _require_port(server_data, "port", default=14500)
    timeout = _optional_float(server_data, "timeout")
    buffer_size = _require_int(server_data, "buffer_size", default=65535)
    log_level = _require_str(server_data, "log_level", default="INFO").upper()
    psk = _resolve_psk(server_data, base_dir=Path(path).resolve().parent)

    return RemoteProxyConfig(
        host=host,
        port=port,
        timeout=timeout,
        buffer_size=buffer_size,
        log_level=log_level,
        psk=psk,
    )


def _read_toml(path: str | Path) -> dict[str, Any]:
    cfg_path = Path(path)
    if not cfg_path.exists():
        raise ConfigError(f"configuration file not found: {cfg_path}")
    with cfg_path.open("rb") as fh:
        return tomllib.load(fh)


def _require_str(data: dict[str, Any], key: str, *, default: str | None = None) -> str:
    if key not in data:
        if default is None:
            raise ConfigError(f"{key} is required")
        return default
    value = data[key]
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{key} must be a non-empty string")
    return value.strip()


def _require_port(data: dict[str, Any], key: str, *, default: int | None = None) -> int:
    if key not in data:
        if default is None:
            raise ConfigError(f"{key} is required")
        return default
    try:
        port = int(data[key])
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{key} must be an integer") from exc
    if not (1 <= port <= 65535):
        raise ConfigError(f"{key} must be between 1 and 65535")
    return port


def _require_int(data: dict[str, Any], key: str, *, default: int | None = None) -> int:
    if key not in data:
        if default is None:
            raise ConfigError(f"{key} is required")
        return default
    try:
        value = int(data[key])
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{key} must be an integer") from exc
    if value <= 0:
        raise ConfigError(f"{key} must be a positive integer")
    return value


def _optional_float(data: dict[str, Any], key: str) -> float | None:
    if key not in data:
        return None
    try:
        value = float(data[key])
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{key} must be a number") from exc
    if value <= 0:
        raise ConfigError(f"{key} must be greater than 0")
    return value


def _resolve_psk(data: dict[str, Any], *, base_dir: Path) -> bytes:
    sources = [key for key in ("psk", "psk_file", "psk_env") if key in data]
    if not sources:
        raise ConfigError("server.psk, server.psk_file or server.psk_env is required")
    if len(sources) > 1:
        raise ConfigError("psk, psk_file and psk_env are mutually exclusive")

    hex_mode = bool(data.get("psk_hex", False))
    source = sources[0]

    if source == "psk":
        raw = _require_str(data, "psk")
    elif source == "psk_file":
        relative = _require_str(data, "psk_file")
        path = Path(relative)
        if not path.is_absolute():
            path = base_dir / path
        if not path.exists():
            raise ConfigError(f"psk_file not found: {path}")
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            raise ConfigError("psk_file is empty")
    else:
        env_key = _require_str(data, "psk_env")
        value = os.environ.get(env_key)
        if value is None:
            raise ConfigError(f"environment variable {env_key} is not set")
        raw = value.strip()
        if not raw:
            raise ConfigError(f"{env_key} must not be empty")

    if hex_mode:
        try:
            return bytes.fromhex(raw)
        except ValueError as exc:
            raise ConfigError("psk_hex true but value is not valid hex") from exc
    return raw.encode("utf-8")
