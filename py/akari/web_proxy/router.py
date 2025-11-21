"""Routing for the AKARI Web proxy UI backed by AKARI-UDP."""

from __future__ import annotations

import json
import logging
import mimetypes
import re
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, quote, unquote, urlsplit

from akari.udp_client import AkariUdpClient, ResponseOutcome
from .config import WebProxyConfig
from local_proxy.content_filter import ContentCategory, ContentFilter, FilterDecision


@dataclass
class RouteResult:
    status_code: int
    body: bytes
    headers: Mapping[str, str]


class WebRouter:
    """HTTP router that serves the static UI and exposes an AKARI-backed proxy endpoint."""

    def __init__(self, config: WebProxyConfig, static_dir: Path | None = None, entry_file: str = "index.html"):
        self._logger = logging.getLogger(__name__)
        self._config = config
        remote = config.remote
        self._udp_client = AkariUdpClient((remote.host, remote.port), remote.psk, timeout=remote.timeout)
        self._message_lock = threading.Lock()
        self._message_counter = secrets.randbelow(0xFFFF) or 1
        self._static_dir = (static_dir or Path(__file__).with_name("static")).resolve()
        self._entry_file = entry_file
        self._proxy_base = f"http://{config.listen_host}:{config.listen_port}/"
        self._content_filter = ContentFilter(config.content_filter)

    # ------------------------------- HTTP handlers -------------------------------
    def handle_get(self, path: str, headers: Mapping[str, str]) -> RouteResult:
        parsed = urlsplit(path)
        params = parse_qs(parsed.query)
        if parsed.path in ("/proxy", "/api/proxy"):
            return self._handle_proxy(params, {}, {})
        if parsed.path in ("/", "", "/index.html"):
            static = self._serve_static_file(self._entry_file)
            if static:
                return static
        if parsed.path == "/healthz":
            return RouteResult(status_code=200, body=b"ok", headers={"Content-Type": "text/plain; charset=utf-8"})
        path_proxy = self._handle_path_proxy(parsed.path)
        if path_proxy:
            return path_proxy
        static = self._serve_static_asset(parsed.path)
        if static:
            return static
        return RouteResult(status_code=404, body=b"Not Found", headers={"Content-Type": "text/plain; charset=utf-8"})

    def handle_post(self, path: str, headers: Mapping[str, str], body: bytes) -> RouteResult:
        parsed = urlsplit(path)
        content_type = headers.get("content-type", "")
        form_params: dict[str, list[str]] = {}
        json_payload: dict[str, Any] = {}
        text_body = body.decode("utf-8", errors="replace") if body else ""
        if content_type.startswith("application/x-www-form-urlencoded"):
            form_params = parse_qs(text_body)
        elif content_type.startswith("application/json"):
            try:
                data = json.loads(text_body or "{}")
                if isinstance(data, dict):
                    json_payload = data
            except json.JSONDecodeError:
                json_payload = {}
        if parsed.path in ("/", "/proxy", "/api/proxy"):
            query_params = parse_qs(parsed.query)
            return self._handle_proxy(query_params, form_params, json_payload)
        return RouteResult(status_code=404, body=b"Not Found", headers={"Content-Type": "text/plain; charset=utf-8"})

    # ------------------------------- proxy core -------------------------------
    def _handle_proxy(
        self,
        query_params: Mapping[str, list[str]],
        form_params: Mapping[str, list[str]],
        json_payload: Mapping[str, Any],
    ) -> RouteResult:
        raw_url = self._extract_url(form_params, json_payload, query_params)
        return self._execute_proxy(raw_url)

    def _handle_path_proxy(self, raw_path: str) -> RouteResult | None:
        candidate = raw_path.lstrip("/")
        if not candidate:
            return None
        url = unquote(candidate)
        if not url.startswith(("http://", "https://")):
            return None
        return self._execute_proxy(url)

    def _execute_proxy(self, raw_url: str) -> RouteResult:
        if not raw_url:
            return self._text_response(400, "url パラメータを指定してください。")
        target_url = self._normalize_user_input(raw_url)
        if not target_url:
            return self._text_response(400, "HTTP/HTTPS の URL を指定してください。")

        # content filter
        decision: FilterDecision = self._content_filter.evaluate(target_url)
        if decision.blocked:
            headers = dict(decision.headers)
            headers.setdefault("Content-Type", "text/plain; charset=utf-8")
            return RouteResult(status_code=decision.status_code or 204, body=decision.body, headers=headers)

        try:
            outcome = self._fetch_via_udp(target_url)
        except ValueError as exc:
            return self._text_response(502, str(exc))

        if outcome.error:
            payload = outcome.error
            message = payload.get("message") or f"AKARI error code={payload.get('error_code')}"
            status = int(payload.get("http_status", 502) or 502)
            return self._text_response(status, message)
        if outcome.timed_out:
            return self._text_response(504, "AKARI-UDP レスポンスがタイムアウトしました。")
        if not outcome.complete or outcome.body is None:
            return self._text_response(502, "レスポンスが揃いませんでした。")

        return self._raw_response(target_url, outcome)

    # ------------------------------- response shaping -------------------------------
    def _raw_response(self, url: str, outcome: ResponseOutcome) -> RouteResult:
        body = outcome.body or b""
        headers = {
            "X-AKARI-Message-Id": f"0x{outcome.message_id:x}",
            "X-AKARI-Bytes-Sent": str(outcome.bytes_sent),
            "X-AKARI-Bytes-Received": str(outcome.bytes_received),
            "X-AKARI-Target": url,
        }
        if outcome.headers:
            for k, v in outcome.headers.items():
                headers[k.title()] = v
        if "Content-Type" not in headers:
            headers["Content-Type"] = "text/html; charset=utf-8"

        self._strip_security_headers(headers)
        body, decompressed = self._maybe_decompress(body, headers)

        content_type = headers.get("Content-Type", "").lower()
        # レスポンス側フィルタ（Content-Typeベース）
        blocked = self._apply_response_filter(content_type)
        if blocked:
            headers_filtered = {
                "Content-Length": "0",
                "Cache-Control": "no-cache",
                "X-AKARI-Filtered": blocked.value,
            }
            headers_filtered.setdefault("Content-Type", "text/plain; charset=utf-8")
            return RouteResult(
                status_code=204,
                body=b"",
                headers=headers_filtered,
            )

        if content_type.startswith("text/html") and decompressed:
            body = self._rewrite_html_to_proxy(body)
        headers["Content-Length"] = str(len(body))
        status_code = int(outcome.status_code or 200)
        return RouteResult(status_code=status_code, body=body, headers=headers)

    # ---------------------------------------------------------------------------
    # HTML rewrite: absolute URLs -> proxy pass
    # ---------------------------------------------------------------------------
    def _rewrite_html_to_proxy(self, body: bytes) -> bytes:
        text = body.decode("utf-8", errors="replace")

        def to_proxy(u: str) -> str:
            if u.startswith("//"):
                u = "https:" + u
            return self._proxy_base + u

        attr_pattern = re.compile(r'(?P<prefix>\b(?:href|src)=["\'])(https?://[^"\']+)')

        def attr_repl(m: re.Match) -> str:
            return f'{m.group("prefix")}{to_proxy(m.group(2))}'

        text = attr_pattern.sub(attr_repl, text)

        srcset_pattern = re.compile(r'\bsrcset=["\']([^"\']+)["\']')

        def srcset_repl(m: re.Match) -> str:
            parts = []
            for entry in m.group(1).split(","):
                ent = entry.strip()
                if not ent:
                    continue
                tokens = ent.split()
                if not tokens:
                    continue
                url = tokens[0]
                rest = " ".join(tokens[1:])
                if url.startswith("http"):
                    url = to_proxy(url)
                parts.append(" ".join([url, rest]).strip())
            return f'srcset="{", ".join(parts)}"'

        text = srcset_pattern.sub(srcset_repl, text)

        registration_snippet = (
            '<script>(function(){'
            "if('serviceWorker' in navigator){"
            "navigator.serviceWorker.register('/sw-akari.js',{scope:'/'}).catch(()=>{});"
            "}"
            "})();</script>"
        )
        text += registration_snippet

        return text.encode("utf-8", errors="replace")

    # ---------------------------------------------------------------------------
    # Strip security headers (CSP etc.)
    # ---------------------------------------------------------------------------
    def _strip_security_headers(self, headers: dict[str, str]) -> None:
        for key in list(headers.keys()):
            lk = key.lower()
            if lk in ("content-security-policy", "content-security-policy-report-only"):
                headers.pop(key, None)

    def _apply_response_filter(self, content_type: str) -> ContentCategory | None:
        """Decide whether to block based on Content-Type."""
        ct = content_type.split(";")[0].strip()
        if ct.startswith("text/javascript") or ct == "application/javascript" or ct == "application/x-javascript":
            return ContentCategory.JAVASCRIPT if not self._content_filter._is_allowed(ContentCategory.JAVASCRIPT) else None
        if ct == "text/css":
            return ContentCategory.STYLESHEET if not self._content_filter._is_allowed(ContentCategory.STYLESHEET) else None
        if ct.startswith("image/"):
            return ContentCategory.IMAGE if not self._content_filter._is_allowed(ContentCategory.IMAGE) else None
        return None

    # ---------------------------------------------------------------------------
    # Content-Encoding decode
    # ---------------------------------------------------------------------------
    def _maybe_decompress(self, body: bytes, headers: dict[str, str]) -> tuple[bytes, bool]:
        enc = headers.get("Content-Encoding", "").lower()
        if not enc:
            return body, True
        try:
            if enc in ("br", "brotli"):
                import brotli  # type: ignore

                body = brotli.decompress(body)
            elif enc == "gzip":
                import gzip

                body = gzip.decompress(body)
            elif enc == "deflate":
                import zlib

                body = zlib.decompress(body)
            else:
                return body, False
            headers.pop("Content-Encoding", None)
            return body, True
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("failed to decompress body (encoding=%s): %s", enc, exc)
            return body, False

    # ------------------------------- utilities -------------------------------
    def _fetch_via_udp(self, url: str) -> ResponseOutcome:
        if not url.startswith(("http://", "https://")):
            raise ValueError("HTTP/HTTPS のみサポートします。")
        message_id = self._next_message_id()
        timestamp = int(time.time())
        try:
            return self._udp_client.send_request(url, message_id, timestamp)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"AKARI-UDP リクエストに失敗: {exc}") from exc

    def _next_message_id(self) -> int:
        with self._message_lock:
            self._message_counter = (self._message_counter + 1) & 0xFFFFFFFF
            if self._message_counter == 0:
                self._message_counter = 1
            return self._message_counter

    def _serve_static_asset(self, raw_path: str) -> RouteResult | None:
        relative = raw_path.lstrip("/")
        if not relative:
            relative = self._entry_file
        return self._serve_static_file(relative)

    def _serve_static_file(self, relative_path: str) -> RouteResult | None:
        candidate = (self._static_dir / relative_path).resolve()
        try:
            candidate.relative_to(self._static_dir)
        except ValueError:
            return None
        if not candidate.exists() or not candidate.is_file():
            return None
        body = candidate.read_bytes()
        mime_type, _ = mimetypes.guess_type(str(candidate))
        if not mime_type:
            mime_type = "application/octet-stream"
        headers = {"Content-Type": mime_type}
        if mime_type.startswith("text/"):
            headers["Content-Type"] = f"{mime_type}; charset=utf-8"
        return RouteResult(status_code=200, body=body, headers=headers)

    def _extract_url(self, *sources: Mapping[str, Any]) -> str:
        for source in sources:
            if not source:
                continue
            value = source.get("url")
            if isinstance(value, list):
                value = value[0] if value else ""
            if isinstance(value, str):
                candidate = value.strip()
                if candidate:
                    return candidate
        return ""

    def _normalize_user_input(self, value: str) -> str | None:
        if not value:
            return ""
        if value.startswith(("http://", "https://")):
            return value
        if "://" not in value and "." in value:
            return "https://" + value
        return None

    def _text_response(self, status: int, message: str) -> RouteResult:
        body = message.encode("utf-8", errors="replace")
        headers = {
            "Content-Type": "text/plain; charset=utf-8",
            "Content-Length": str(len(body)),
        }
        return RouteResult(status_code=status, body=body, headers=headers)
