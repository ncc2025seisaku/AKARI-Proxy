"""Backwards compatible re-export of the AKARI Web proxy HTTP server."""

from akari.web_proxy.http_server import WebHttpServer  # noqa: F401

__all__ = ["WebHttpServer"]
