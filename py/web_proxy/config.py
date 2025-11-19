"""Backwards compatible re-export of the AKARI Web proxy config."""

from akari.web_proxy.config import ConfigError, UIConfig, WebProxyConfig, load_config  # noqa: F401

__all__ = [
    "ConfigError",
    "UIConfig",
    "WebProxyConfig",
    "load_config",
]
