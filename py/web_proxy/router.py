"""Backwards compatible re-export of the AKARI Web proxy router."""

from akari.web_proxy.router import RouteResult, WebRouter  # noqa: F401

__all__ = ["RouteResult", "WebRouter"]
