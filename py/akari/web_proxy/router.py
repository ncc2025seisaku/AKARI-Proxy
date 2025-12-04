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
from urllib.parse import parse_qs, quote, unquote, urlsplit, urljoin

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
        self._udp_client_plain = AkariUdpClient((remote.host, remote.port), remote.psk, timeout=remote.timeout)
        self._udp_client_enc = AkariUdpClient(
            (remote.host, remote.port), remote.psk, timeout=remote.timeout, use_encryption=True
        )
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
        if parsed.path == "/api/filter":
            return self._handle_filter_get()
        if parsed.path in ("/proxy", "/api/proxy"):
            return self._handle_proxy(params, {}, {})
        if parsed.path in ("/", "", "/index.html"):
            static = self._serve_static_file(self._entry_file)
            if static:
                return static
        if parsed.path == "/healthz":
            return RouteResult(status_code=200, body=b"ok", headers={"Content-Type": "text/plain; charset=utf-8"})
        path_proxy = self._handle_path_proxy(parsed.path, params)
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
        if parsed.path == "/api/filter":
            payload = json_payload or {k: v[0] for k, v in form_params.items() if v}
            return self._handle_filter_update(payload)
        return RouteResult(status_code=404, body=b"Not Found", headers={"Content-Type": "text/plain; charset=utf-8"})

    # ------------------------------- proxy core -------------------------------
    def _handle_proxy(
        self,
        query_params: Mapping[str, list[str]],
        form_params: Mapping[str, list[str]],
        json_payload: Mapping[str, Any],
    ) -> RouteResult:
        raw_url = self._extract_url(form_params, json_payload, query_params)
        skip_filter = bool(query_params.get("entry"))
        use_encryption = self._coerce_bool(query_params, "enc") or self._coerce_bool(query_params, "e") or False
        return self._execute_proxy(raw_url, skip_filter=skip_filter, use_encryption=use_encryption)

    def _handle_filter_get(self) -> RouteResult:
        current = self._content_filter.snapshot()
        payload = {
            "enable_js": current.enable_js,
            "enable_css": current.enable_css,
            "enable_img": current.enable_img,
            "enable_other": current.enable_other,
        }
        return self._json_response(200, payload)

    def _handle_filter_update(self, payload: Mapping[str, Any]) -> RouteResult:
        try:
            enable_js = self._coerce_bool(payload, "enable_js")
            enable_css = self._coerce_bool(payload, "enable_css")
            enable_img = self._coerce_bool(payload, "enable_img")
            enable_other = self._coerce_bool(payload, "enable_other")
        except ValueError as exc:
            return self._json_response(400, {"error": str(exc)})

        if enable_js is None and enable_css is None and enable_img is None and enable_other is None:
            return self._json_response(400, {"error": "enable_js/enable_css/enable_img/enable_other のいずれかを指定してください。"})

        updated = self._content_filter.update(
            enable_js=enable_js, enable_css=enable_css, enable_img=enable_img, enable_other=enable_other
        )
        payload = {
            "enable_js": updated.enable_js,
            "enable_css": updated.enable_css,
            "enable_img": updated.enable_img,
            "enable_other": updated.enable_other,
        }
        return self._json_response(200, payload)

    def _handle_path_proxy(self, raw_path: str, params: Mapping[str, list[str]]) -> RouteResult | None:
        candidate = raw_path.lstrip("/")
        if not candidate:
            return None
        url = unquote(candidate)
        if not url.startswith(("http://", "https://")):
            return None
        skip_filter = bool(params.get("entry"))
        use_encryption = self._coerce_bool(params, "enc") or self._coerce_bool(params, "e") or False
        return self._execute_proxy(url, skip_filter=skip_filter, use_encryption=use_encryption)

    def _execute_proxy(self, raw_url: str, *, skip_filter: bool = False, use_encryption: bool = False) -> RouteResult:
        if not raw_url:
            return self._text_response(400, "url パラメータを指定してください。")
        target_url = self._normalize_user_input(raw_url)
        if not target_url:
            return self._text_response(400, "HTTP/HTTPS の URL を指定してください。")

        # content filter (skip when explicitly requested for entry navigation)
        if not skip_filter:
            decision: FilterDecision = self._content_filter.evaluate(target_url)
            if decision.blocked:
                headers = dict(decision.headers)
                headers.setdefault("Content-Type", "text/plain; charset=utf-8")
                return RouteResult(status_code=decision.status_code or 204, body=decision.body, headers=headers)

        try:
            outcome = self._fetch_via_udp(target_url, use_encryption=use_encryption)
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

        return self._raw_response(target_url, outcome, skip_filter=skip_filter)

    # ------------------------------- response shaping -------------------------------
    def _raw_response(self, url: str, outcome: ResponseOutcome, *, skip_filter: bool = False) -> RouteResult:
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
        # 転送後は必ず固定長で返すため Transfer-Encoding は落とす
        headers.pop("Transfer-Encoding", None)
        headers.pop("transfer-encoding", None)
        if "Content-Type" not in headers:
            headers["Content-Type"] = "text/html; charset=utf-8"

        self._strip_security_headers(headers)
        body, decompressed = self._maybe_decompress(body, headers)

        content_type = headers.get("Content-Type", "").lower()
        # レスポンス側フィルタ（Content-Typeベース）: entry=1 のリクエストはスキップ
        if not skip_filter:
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
            body = self._rewrite_html_to_proxy(body, url)
        elif content_type.startswith("text/css") and decompressed:
            body = self._rewrite_css_to_proxy(body, url)
        elif "javascript" in content_type and decompressed:
            body = self._rewrite_js_to_proxy(body, url)
        headers["Content-Length"] = str(len(body))
        status_code = int(outcome.status_code or 200)
        return RouteResult(status_code=status_code, body=body, headers=headers)

    # ---------------------------------------------------------------------------
    # HTML rewrite: absolute URLs -> proxy pass
    # ---------------------------------------------------------------------------
    def _rewrite_html_to_proxy(self, body: bytes, source_url: str) -> bytes:
        text = body.decode("utf-8", errors="replace")
        base_url = source_url

        # Allow whitespace/case variations around href/src attributes
        attr_pattern = re.compile(r'(?P<prefix>\b(?:href|src)\s*=\s*["\'])([^"\']+)', re.IGNORECASE)

        def attr_repl(m: re.Match) -> str:
            return f'{m.group("prefix")}{self._to_proxy_url(m.group(2), base_url)}'

        text = attr_pattern.sub(attr_repl, text)

        srcset_pattern = re.compile(r'\bsrcset\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)

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
                url = self._to_proxy_url(url, base_url)
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

    def _rewrite_css_to_proxy(self, body: bytes, source_url: str) -> bytes:
        """Rewrite CSS url() references to pass through the proxy."""
        text = body.decode("utf-8", errors="replace")
        base_url = source_url

        def repl(m: re.Match) -> str:
            quote = m.group("quote") or ""
            original = m.group("url")
            rewritten = self._to_proxy_url(original, base_url)
            return f"url({quote}{rewritten}{quote})"

        pattern = re.compile(r'url\(\s*(?P<quote>[\'"]?)(?P<url>[^\'")]+)\s*(?P=quote)?\)', re.IGNORECASE)
        return pattern.sub(repl, text).encode("utf-8", errors="replace")

    def _rewrite_js_to_proxy(self, body: bytes, source_url: str) -> bytes:
        """Rewrite simple import()/fetch()/static import URLs to go through proxy."""
        text = body.decode("utf-8", errors="replace")
        base_url = source_url

        def rewrite_literal(url_literal: str) -> str:
            return self._to_proxy_url(url_literal, base_url)

        # fetch('...') / fetch("...")
        fetch_pat = re.compile(r'(fetch\s*\(\s*)([\'"])([^\'"]+)([\'"])', re.IGNORECASE)
        text = fetch_pat.sub(lambda m: f"{m.group(1)}{m.group(2)}{rewrite_literal(m.group(3))}{m.group(4)}", text)

        # import('...') dynamic
        dyn_import_pat = re.compile(r'(import\s*\(\s*)([\'"])([^\'"]+)([\'"])(\s*\))', re.IGNORECASE)
        text = dyn_import_pat.sub(
            lambda m: f"{m.group(1)}{m.group(2)}{rewrite_literal(m.group(3))}{m.group(4)}{m.group(5)}", text
        )

        # static import ... from '...';
        static_import_pat = re.compile(r'(from\s+)([\'"])([^\'"]+)([\'"])', re.IGNORECASE)
        text = static_import_pat.sub(
            lambda m: f"{m.group(1)}{m.group(2)}{rewrite_literal(m.group(3))}{m.group(4)}", text
        )

        # bare import '...';
        bare_import_pat = re.compile(r'(^|\s)(import\s+)([\'"])([^\'"]+)([\'"])', re.IGNORECASE)
        text = bare_import_pat.sub(
            lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}{rewrite_literal(m.group(4))}{m.group(5)}", text
        )

        return text.encode("utf-8", errors="replace")

    def _to_proxy_url(self, url: str, base_url: str) -> str:
        """Convert absolute/relative URL into proxied URL, preserving data/js/mailto."""
        if not url or url.startswith(("data:", "javascript:", "mailto:", "#")):
            return url
        if url.startswith(self._proxy_base):
            return url
        if url.startswith("//"):
            url = "https:" + url
        if not url.startswith(("http://", "https://")) and base_url:
            url = urljoin(base_url, url)
        return self._proxy_base + url

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
    def _fetch_via_udp(self, url: str, *, use_encryption: bool = False) -> ResponseOutcome:
        if not url.startswith(("http://", "https://")):
            raise ValueError("HTTP/HTTPS のみサポートします。")
        message_id = self._next_message_id()
        timestamp = int(time.time())
        try:
            client = self._udp_client_enc if use_encryption else self._udp_client_plain
            return client.send_request(url, message_id, timestamp)
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

    def _coerce_bool(self, payload: Mapping[str, Any], key: str) -> bool | None:
        """Accepts bool, 0/1, or typical truthy strings. Missing -> None."""
        if key not in payload:
            return None
        value = payload.get(key)
        if isinstance(value, list):
            if not value:
                return None
            value = value[0]
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and value in (0, 1):
            return bool(value)
        if isinstance(value, str):
            val = value.strip().lower()
            if val in {"1", "true", "yes", "on"}:
                return True
            if val in {"0", "false", "no", "off"}:
                return False
        raise ValueError(f"{key} は true/false で指定してください。入力値: {value!r}")

    def _normalize_user_input(self, value: str) -> str | None:
        if not value:
            return ""
        if value.startswith(("http://", "https://")):
            return value
        if "://" not in value and "." in value:
            return "https://" + value
        return None

    def _json_response(self, status: int, payload: Mapping[str, Any]) -> RouteResult:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Content-Length": str(len(body)),
        }
        return RouteResult(status_code=status, body=body, headers=headers)

    def _text_response(self, status: int, message: str) -> RouteResult:
        body = message.encode("utf-8", errors="replace")
        headers = {
            "Content-Type": "text/plain; charset=utf-8",
            "Content-Length": str(len(body)),
        }
        return RouteResult(status_code=status, body=body, headers=headers)
