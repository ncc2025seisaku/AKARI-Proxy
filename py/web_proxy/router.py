"""Routing and rendering logic for the AKARI Web proxy WebUI."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Mapping
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

from .config import WebProxyConfig

MAX_FETCH_BYTES = 512 * 1024  # 512KB
HTTP_TIMEOUT = 5
USER_AGENT = "AKARI-WebProxy/0.1"


@dataclass
class RouteResult:
    status_code: int
    body: bytes
    headers: Mapping[str, str]


class TemplateRenderer:
    """Very small template renderer that performs {{ placeholder }} replacement."""

    def __init__(self, template_dir: Path):
        self._template_dir = template_dir

    def render(self, name: str, context: Mapping[str, str]) -> str:
        tpl_path = self._template_dir / name
        text = tpl_path.read_text(encoding="utf-8")
        rendered = text
        for key, value in context.items():
            rendered = rendered.replace(f"{{{{ {key} }}}}", value)
        return rendered


class WebRouter:
    """HTTP router for the browser-facing Web proxy UI."""

    def __init__(self, config: WebProxyConfig, template_dir: Path):
        self._config = config
        self._renderer = TemplateRenderer(template_dir)

    def handle_get(self, path: str, headers: Mapping[str, str]) -> RouteResult:
        parsed = urlsplit(path)
        params = parse_qs(parsed.query)
        if parsed.path in ("/", ""):
            return self._render_portal(params)
        if parsed.path == "/healthz":
            return RouteResult(status_code=200, body=b"ok", headers={"Content-Type": "text/plain; charset=utf-8"})
        return RouteResult(status_code=404, body=b"Not Found", headers={"Content-Type": "text/plain; charset=utf-8"})

    def handle_post(self, path: str, headers: Mapping[str, str], body: bytes) -> RouteResult:
        parsed = urlsplit(path)
        content_type = headers.get("content-type", "")
        params: dict[str, list[str]] = {}
        if content_type.startswith("application/x-www-form-urlencoded"):
            params = parse_qs(body.decode("utf-8", errors="replace"))
        if parsed.path in ("/", "/proxy"):
            return self._render_portal(params)
        return RouteResult(status_code=404, body=b"Not Found", headers={"Content-Type": "text/plain; charset=utf-8"})

    def _render_portal(self, params: Mapping[str, list[str]]) -> RouteResult:
        raw_url = (params.get("url") or [""])[0].strip()
        target_url = self._normalize_user_input(raw_url)

        error_html = ""
        result_html = ""
        if raw_url:
            if target_url is None:
                error_html = self._render_error("URL は http:// または https:// で始めてください。")
            else:
                result_html = self._render_fetch_result(target_url)

        body = self._renderer.render(
            "portal.html",
            {
                "portal_title": escape(self._config.ui.portal_title),
                "welcome_message": escape(self._config.ui.welcome_message),
                "url_value": escape(raw_url),
                "result_section": result_html or error_html,
            },
        ).encode("utf-8")
        return RouteResult(status_code=200, body=body, headers={"Content-Type": "text/html; charset=utf-8"})

    def _render_error(self, message: str) -> str:
        return f'<div class="alert">{escape(message)}</div>'

    def _render_fetch_result(self, url: str) -> str:
        try:
            fetch_result = self._fetch_url(url)
        except ValueError as exc:
            return self._render_error(str(exc))

        info_block = (
            "<div class='result-info'>"
            f"<p><strong>URL:</strong> {escape(url)}</p>"
            f"<p><strong>Status:</strong> {fetch_result['status']} ({escape(fetch_result['reason'])})</p>"
            f"<p><strong>Content-Type:</strong> {escape(fetch_result['content_type'])}</p>"
            f"<p><strong>Size:</strong> {fetch_result['length']} bytes"
            + (" (truncated)" if fetch_result["truncated"] else "")
            + "</p>"
            "</div>"
        )

        preview_html = ""
        if fetch_result["content_preview"]:
            preview_html = (
                "<details class='preview'>"
                "<summary>プレビューを表示</summary>"
                "<textarea readonly>"
                + escape(fetch_result["content_preview"])
                + "</textarea>"
                "</details>"
            )

        return "<section class='result'>" + info_block + preview_html + "</section>"

    def _fetch_url(self, url: str) -> dict[str, str | int | bool]:
        if not url.startswith(("http://", "https://")):
            raise ValueError("HTTP/HTTPS のみサポートしています。")

        request = Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urlopen(request, timeout=HTTP_TIMEOUT) as resp:
                data = resp.read(MAX_FETCH_BYTES + 1)
                truncated = len(data) > MAX_FETCH_BYTES
                body = data[:MAX_FETCH_BYTES]
                content_type = resp.headers.get("Content-Type", "application/octet-stream")
                reason = resp.reason or ""
                preview = ""
                if content_type.startswith("text/"):
                    preview = body.decode(resp.headers.get_content_charset() or "utf-8", errors="replace")
                elif content_type == "application/json":
                    preview = body.decode("utf-8", errors="replace")
                return {
                    "status": resp.status,
                    "reason": reason,
                    "content_type": content_type,
                    "length": len(body),
                    "truncated": truncated,
                    "content_preview": preview,
                }
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"取得に失敗しました: {exc}") from exc

        raise ValueError("未知のエラーが発生しました。")

    def _normalize_user_input(self, value: str) -> str | None:
        if not value:
            return ""
        if value.startswith(("http://", "https://")):
            return value
        if "://" not in value and "." in value:
            return "https://" + value
        return None
