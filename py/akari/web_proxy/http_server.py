"""Threaded HTTP server wrapper for the AKARI Web proxy UI."""

from __future__ import annotations

import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Mapping

from .config import WebProxyConfig
from .router import RouteResult, WebRouter


class WebHttpServer:
    """Small wrapper around ThreadingHTTPServer with router integration."""

    def __init__(self, config: WebProxyConfig, router: WebRouter) -> None:
        self._config = config
        self._router = router
        handler_cls = _make_handler(router)
        self._server = _QuietThreadingHTTPServer((config.listen_host, config.listen_port), handler_cls)

    def serve_forever(self) -> None:
        try:
            self._server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            self._server.server_close()


def _make_handler(router: WebRouter) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:  # noqa: N802
            self._dispatch("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._dispatch("POST")

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return  # suppress noisy logs

        def _dispatch(self, method: str) -> None:
            try:
                if method == "GET":
                    response = router.handle_get(self.path, self.headers)
                else:
                    length = int(self.headers.get("Content-Length", "0") or 0)
                    body = self.rfile.read(length) if length > 0 else b""
                    response = router.handle_post(self.path, self.headers, body)
            except Exception as exc:  # noqa: BLE001
                body = f"Internal Server Error: {exc}".encode("utf-8")
                self._send_response(RouteResult(status_code=500, body=body, headers={"Content-Type": "text/plain; charset=utf-8"}))
            else:
                self._send_response(response)

        def _send_response(self, result: RouteResult) -> None:
            try:
                status = HTTPStatus(result.status_code)
                self.send_response(status.value, status.phrase)
                for key, value in result.headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(result.body)))
                self.end_headers()
                self.wfile.write(result.body)
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                # クライアントが先に切断した場合は無視（ログ不要）
                return

    return Handler


class _QuietThreadingHTTPServer(ThreadingHTTPServer):
    """Suppress noisy tracebacks for client-aborted connections."""

    def handle_error(self, request, client_address) -> None:  # type: ignore[override]
        _exc = sys.exc_info()[1]
        if isinstance(_exc, (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)
