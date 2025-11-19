"""Configuration loader for the local proxy (non-UI)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomllib


@dataclass(frozen=True)
class ContentFilterSettings:
    """Content-filter toggles loaded from the config file."""

    enable_js: bool = True
    enable_css: bool = True
    enable_img: bool = True


@dataclass(frozen=True)
class LocalProxyConfig:
    """Currently exposed portion of the local proxy config."""

    content_filter: ContentFilterSettings


class ConfigError(ValueError):
    """Raised when the configuration file cannot be parsed."""


def load_config(path: str | Path) -> LocalProxyConfig:
    """Load local proxy configuration from TOML."""

    data = _read_toml(path)
    filter_data = data.get("content_filter", {})
    content_filter = ContentFilterSettings(
        enable_js=_require_bool(filter_data, "enable_js", default=True),
        enable_css=_require_bool(filter_data, "enable_css", default=True),
        enable_img=_require_bool(filter_data, "enable_img", default=True),
    )
    return LocalProxyConfig(content_filter=content_filter)


def _read_toml(path: str | Path) -> dict[str, Any]:
    cfg_path = Path(path)
    if not cfg_path.exists():
        raise ConfigError(f"configuration file not found: {cfg_path}")
    with cfg_path.open("rb") as fh:
        return tomllib.load(fh)


def _require_bool(data: dict[str, Any], key: str, *, default: bool) -> bool:
    if key not in data:
        return default
    value = data[key]
    if isinstance(value, bool):
        return value
    raise ConfigError(f"{key} must be a boolean (true/false)")
