"""Configuration loader for the standalone Web proxy."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomllib
from local_proxy.config import ContentFilterSettings


@dataclass(frozen=True)
class UIConfig:
    portal_title: str
    welcome_message: str


@dataclass(frozen=True)
class RemoteProxyConfig:
    host: str
    port: int
    psk: bytes
    timeout: float
    protocol_version: int
    agg_tag: bool
    payload_max: int
    df: bool
    plpmtud: bool


@dataclass(frozen=True)
class WebProxyConfig:
    listen_host: str
    listen_port: int
    mode: str
    ui: UIConfig
    remote: RemoteProxyConfig
    content_filter: ContentFilterSettings


class ConfigError(ValueError):
    """Raised when configuration values are invalid."""


def load_config(path: str | Path) -> WebProxyConfig:
    data = _read_toml(path)
    proxy_data = data.get("proxy", {})
    listen_host = _require_str(proxy_data, "listen_host", default="127.0.0.1")
    listen_port = _require_port(proxy_data, "listen_port", default=8080)
    mode = proxy_data.get("mode", "web")
    if mode not in {"web", "reverse"}:
        raise ConfigError("proxy.mode must be 'web' or 'reverse'")

    ui_data = data.get("ui", {})
    ui = UIConfig(
        portal_title=_require_str(ui_data, "portal_title", default="AKARI Web Proxy"),
        welcome_message=_require_str(ui_data, "welcome_message", default="AKARI Web Proxy へようこそ"),
    )

    remote_data = data.get("remote", {})
    remote = RemoteProxyConfig(
        host=_require_str(remote_data, "host", default="127.0.0.1"),
        port=_require_port(remote_data, "port", default=9000),
        psk=_parse_psk(remote_data),
        timeout=_require_float(remote_data, "timeout", default=2.0),
        protocol_version=int(remote_data.get("protocol_version", 2)),
        agg_tag=_require_bool(remote_data, "agg_tag", default=True),
        payload_max=int(remote_data.get("payload_max", 1200)),
        df=_require_bool(remote_data, "df", default=True),
        plpmtud=_require_bool(remote_data, "plpmtud", default=False),
    )

    filter_data = data.get("content_filter", {})
    content_filter = ContentFilterSettings(
        enable_js=_require_bool(filter_data, "enable_js", default=True),
        enable_css=_require_bool(filter_data, "enable_css", default=True),
        enable_img=_require_bool(filter_data, "enable_img", default=True),
        enable_other=_require_bool(filter_data, "enable_other", default=True),
    )

    return WebProxyConfig(
        listen_host=listen_host,
        listen_port=listen_port,
        mode=mode,
        ui=ui,
        remote=remote,
        content_filter=content_filter,
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
    value = data.get(key)
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


def _require_bool(data: dict[str, Any], key: str, *, default: bool = False) -> bool:
    if key not in data:
        return default
    value = data[key]
    if isinstance(value, bool):
        return value
    raise ConfigError(f"{key} must be a boolean")


def _require_float(data: dict[str, Any], key: str, *, default: float | None = None) -> float:
    if key not in data:
        if default is None:
            raise ConfigError(f"{key} is required")
        return default
    try:
        return float(data[key])
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{key} must be a number") from exc


def _parse_psk(data: dict[str, Any]) -> bytes:
    psk_value = _require_str(data, "psk", default="test-psk-0000-test")
    as_hex = _require_bool(data, "psk_hex", default=False)
    if as_hex:
        try:
            return bytes.fromhex(psk_value.replace(" ", ""))
        except ValueError as exc:
            raise ConfigError("psk must be a valid hex string when psk_hex=true") from exc
    return psk_value.encode("utf-8")
