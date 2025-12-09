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
from urllib.parse import parse_qs, quote, unquote, urlsplit, urljoin, urlencode, urlunsplit

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
            return self._handle_proxy(params, {}, {}, headers)
        if parsed.path in ("/", "", "/index.html"):
            static = self._serve_static_file(self._entry_file)
            if static:
                return static
        if parsed.path == "/healthz":
            return RouteResult(status_code=200, body=b"ok", headers={"Content-Type": "text/plain; charset=utf-8"})
        path_proxy = self._handle_path_proxy(parsed.path, params, headers)
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
            return self._handle_proxy(query_params, form_params, json_payload, headers)
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
        headers: Mapping[str, str],
    ) -> RouteResult:
        raw_url = self._extract_url(form_params, json_payload, query_params)
        skip_filter = bool(query_params.get("entry"))
        use_encryption = self._coerce_bool(query_params, "enc") or self._coerce_bool(query_params, "e")
        if use_encryption is None:
            use_encryption = self._has_enc_cookie(headers)
        use_encryption = bool(use_encryption)
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

    def _handle_path_proxy(self, raw_path: str, params: Mapping[str, list[str]], headers: Mapping[str, str]) -> RouteResult | None:
        candidate = raw_path.lstrip("/")
        if not candidate:
            return None
        url = unquote(candidate)
        if not url.startswith(("http://", "https://")):
            return None
        skip_filter = bool(params.get("entry"))
        use_encryption = self._coerce_bool(params, "enc") or self._coerce_bool(params, "e")
        if use_encryption is None:
            use_encryption = self._has_enc_cookie(headers)
        use_encryption = bool(use_encryption)
        merged_url = self._merge_outer_params_into_url(url, params)
        return self._execute_proxy(merged_url, skip_filter=skip_filter, use_encryption=use_encryption)

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
            client = self._new_udp_client(use_encryption=use_encryption)
            outcome = self._fetch_via_udp(target_url, use_encryption=use_encryption, udp_client=client)
        except ValueError as exc:
            return self._text_response(502, str(exc))
        finally:
            try:
                client.close()
            except Exception:
                self._logger.warning("failed to close udp client", exc_info=True)

        self._logger.info(
            "udp outcome msg_id=0x%x nacks=%d retries=%d bytes_sent=%d bytes_recv=%d complete=%s timed_out=%s",
            outcome.message_id,
            outcome.nacks_sent,
            outcome.request_retries,
            outcome.bytes_sent,
            outcome.bytes_received,
            outcome.complete,
            outcome.timed_out,
        )

        if outcome.error:
            payload = outcome.error
            message = payload.get("message") or f"AKARI error code={payload.get('error_code')}"
            status = int(payload.get("http_status", 502) or 502)
            return self._text_response(status, message)
        if outcome.timed_out:
            return self._text_response(504, "AKARI-UDP レスポンスがタイムアウトしました。")
        if not outcome.complete or outcome.body is None:
            return self._text_response(502, "レスポンスが揃いませんでした。")

        return self._raw_response(target_url, outcome, skip_filter=skip_filter, use_encryption=use_encryption)

    def _new_udp_client(self, *, use_encryption: bool) -> AkariUdpClient:
        remote = self._config.remote
        return AkariUdpClient(
            (remote.host, remote.port),
            remote.psk,
            timeout=remote.timeout,
            use_encryption=use_encryption,
        )

    # ------------------------------- response shaping -------------------------------
    def _raw_response(
        self, url: str, outcome: ResponseOutcome, *, skip_filter: bool = False, use_encryption: bool = False
    ) -> RouteResult:
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
        if use_encryption and "Set-Cookie" not in headers:
            headers["Set-Cookie"] = "akari_enc=1; Path=/; SameSite=Lax"
        # 転送後は必ず固定長で返すため Transfer-Encoding は落とす
        headers.pop("Transfer-Encoding", None)
        headers.pop("transfer-encoding", None)
        if "Content-Type" not in headers:
            headers["Content-Type"] = "text/html; charset=utf-8"

        self._strip_security_headers(headers)
        # Location リダイレクトも必ずプロキシ経由に書き換える
        location = headers.get("Location") or headers.get("location")
        if location:
            headers["Location"] = self._to_proxy_url(location, url, use_encryption=use_encryption)
            headers.pop("location", None)
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
            body = self._rewrite_html_to_proxy(body, url, use_encryption=use_encryption)
        elif content_type.startswith("text/css") and decompressed:
            body = self._rewrite_css_to_proxy(body, url, use_encryption=use_encryption)
        elif "javascript" in content_type and decompressed:
            body = self._rewrite_js_to_proxy(body, url, use_encryption=use_encryption)
        headers["Content-Length"] = str(len(body))
        status_code = int(outcome.status_code or 200)
        return RouteResult(status_code=status_code, body=body, headers=headers)

    # ---------------------------------------------------------------------------
    # HTML rewrite: absolute URLs -> proxy pass
    # ---------------------------------------------------------------------------
    def _rewrite_html_to_proxy(self, body: bytes, source_url: str, *, use_encryption: bool = False) -> bytes:
        text = body.decode("utf-8", errors="replace")
        base_url = source_url

        # Allow whitespace/case variations around href/src/action attributes
        attr_pattern = re.compile(r'(?P<prefix>\b(?:href|src|action)\s*=\s*["\'])([^"\']+)', re.IGNORECASE)

        def attr_repl(m: re.Match) -> str:
            return f'{m.group("prefix")}{self._to_proxy_url(m.group(2), base_url, use_encryption=use_encryption)}'

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
                url = self._to_proxy_url(url, base_url, use_encryption=use_encryption)
                parts.append(" ".join([url, rest]).strip())
            return f'srcset="{", ".join(parts)}"'

        text = srcset_pattern.sub(srcset_repl, text)

        # <meta http-equiv="refresh" content="0;url=...">
        meta_refresh_pattern = re.compile(
            r'(<meta\s+[^>]*http-equiv\s*=\s*["\']refresh["\'][^>]*content\s*=\s*["\'])([^"\']+)',
            re.IGNORECASE,
        )
        # ループ防止: 一度リダイレクトしたら次回は meta refresh を除去するためのフラグ
        already_refreshed = False
        try:
            parsed_src = urlsplit(source_url)
            qs = parse_qs(parsed_src.query)
            already_refreshed = "_akari_ref" in qs
        except Exception:
            already_refreshed = False

        def meta_refresh_repl(m: re.Match) -> str:
            if already_refreshed:
                # すでに1回リダイレクト済みなら meta refresh を除去してループを断つ
                return ""
            prefix = m.group(1)
            content = m.group(2)
            parts = content.split(";", 1)
            if len(parts) == 2:
                delay, url_part = parts[0].strip(), parts[1].strip()
                if url_part.lower().startswith("url="):
                    url_literal = url_part[4:].strip()
                    proxied = self._to_proxy_url(url_literal, base_url, use_encryption=use_encryption)
                    separator = "&" if "?" in proxied else "?"
                    proxied = f"{proxied}{separator}_akari_ref=1"
                    return f'{prefix}{delay};url={proxied}'
            return m.group(0)

        text = meta_refresh_pattern.sub(meta_refresh_repl, text)

        sw_path = "/sw-akari.js"
        if use_encryption:
            sw_path += "?enc=1"
        registration_snippet = (
            '<script>(function(){'
            "if('serviceWorker' in navigator){"
            f"navigator.serviceWorker.register('{sw_path}',{{scope:'/'}}).catch(()=>{{}});"
            "}"
            "})();</script>"
        )
        runtime_rewrite_snippet = (
            "<script>(function(){"
            "const proxy=location.origin+'/';"
            "const enc=/[?&]enc=1(?:&|$)/.test(location.search)||document.cookie.includes('akari_enc=1');"
            "let base=null;try{base=decodeURIComponent(location.pathname.slice(1));}catch(e){}"
            "const invalid=/^(?:data:|javascript:|mailto:|#)/i;"
            "function toProxy(u){"
            "if(!u||invalid.test(u)||u.startsWith(proxy))return null;"
            "if(u.startsWith('//'))u='https:'+u;"
            "try{const abs=base?new URL(u,base).href:new URL(u).href;"
            "let p=proxy+encodeURIComponent(abs);"
            "if(enc&&p.indexOf('?')===-1)p+='?enc=1';"
            "return p;}catch(e){return null;}"
            "}"
            "function rewrite(el,attr){const v=el.getAttribute(attr);const p=toProxy(v);if(p)el.setAttribute(attr,p);}"
            "function scan(root){root.querySelectorAll('a[href],form[action],img[src],script[src],link[href],iframe[src]').forEach(el=>{rewrite(el,el.hasAttribute('href')?'href':'src');});}"
            "function onClick(e){const a=e.target.closest&&e.target.closest('a[href]');if(!a)return;const p=toProxy(a.getAttribute('href'));if(p){e.preventDefault();location.assign(p);}}"
            "function onSubmit(e){const f=e.target.closest&&e.target.closest('form[action]');if(!f)return;const p=toProxy(f.getAttribute('action'));if(p)f.action=p;}"
            "scan(document);"
            "document.addEventListener('click',onClick,true);"
            "document.addEventListener('submit',onSubmit,true);"
            "new MutationObserver(ms=>{ms.forEach(m=>m.addedNodes.forEach(n=>{if(n.nodeType===1)scan(n);}));}).observe(document.documentElement,{childList:true,subtree:true});"
            "function normalize(u){if(!u)return'';if(/^[a-zA-Z][a-zA-Z0-9+.-]*:\\/\\//.test(u))return u;if(u.startsWith('//'))return'https:'+u;if(u.includes('.'))return'https://'+u;return u;}"
            "function installUrlPanel(){"
            "if(!document.body||document.getElementById('akari-url-panel'))return;"
            "const style=document.createElement('style');"
            "style.id='akari-url-panel-style';"
            "style.textContent="
            "'#akari-url-panel{position:fixed;top:12px;left:50%;transform:translateX(-50%);z-index:2147483000;display:flex;align-items:center;gap:10px;padding:8px 10px;"
            "background:rgba(6,8,15,0.78);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);"
            "border:1px solid rgba(255,255,255,0.18);border-radius:14px;box-shadow:0 10px 40px rgba(0,0,0,0.45);"
            "width:min(760px,calc(100vw - 28px));font-family:\"Inter\",\"SF Pro Display\",\"Yu Gothic\",system-ui,sans-serif;color:#f6f2ea;}"
            "#akari-url-panel .akari-chip{font-size:12px;letter-spacing:0.18em;color:rgba(246,242,234,0.78);}"
            "#akari-url-panel input{flex:1;min-width:0;border:1px solid rgba(255,255,255,0.18);border-radius:10px;background:rgba(255,255,255,0.06);"
            "color:#f6f2ea;padding:8px 10px;font-size:14px;}"
            "#akari-url-panel input:focus{outline:none;border-color:rgba(243,196,92,0.9);box-shadow:0 0 0 2px rgba(243,196,92,0.25);background:rgba(0,0,0,0.35);}"
            "#akari-url-panel button{border:none;border-radius:10px;background:linear-gradient(135deg,#ffd889,#bf8d29);color:#08060a;font-weight:700;padding:8px 14px;cursor:pointer;box-shadow:0 10px 22px rgba(223,140,41,0.35);}"
            "#akari-url-panel button:active{transform:translateY(1px);}"
            "@media(max-width:540px){#akari-url-panel{flex-direction:column;align-items:stretch;top:10px;width:min(520px,calc(100vw - 16px));}#akari-url-panel button{width:100%;}}';"
            "(document.head||document.documentElement).appendChild(style);"
            "const form=document.createElement('form');"
            "form.id='akari-url-panel';"
            "form.setAttribute('role','navigation');"
            "form.innerHTML=\"<span class='akari-chip'>AKARI</span><input id='akari-url-input' type='text' spellcheck='false' autocomplete='off' /><button type='submit' id='akari-url-go'>GO</button>\";"
            "document.body.appendChild(form);"
            "const input=form.querySelector('#akari-url-input');"
            "const btn=form.querySelector('#akari-url-go');"
            "if(input){input.value=base||location.href;}"
            "function navigate(evt){if(evt)evt.preventDefault();if(!input)return;const raw=(input.value||'').trim();if(!raw){input.focus();return;}const normalized=normalize(raw);const prox=toProxy(normalized);if(prox){location.assign(prox);return;}try{const abs=new URL(normalized,base||undefined).href;let p=proxy+encodeURIComponent(abs);if(enc&&p.indexOf('?')===-1)p+='?enc=1';location.assign(p);}catch(e){alert('URL形式が正しくありません');}}"
            "form.addEventListener('submit',navigate);"
            "btn&&btn.addEventListener('click',navigate);"
            "}"
            "if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',installUrlPanel);}else{installUrlPanel();}"
            "})();</script>"
        )
        text += registration_snippet + runtime_rewrite_snippet

        return text.encode("utf-8", errors="replace")

    def _rewrite_css_to_proxy(self, body: bytes, source_url: str, *, use_encryption: bool = False) -> bytes:
        """Rewrite CSS url() references to pass through the proxy."""
        text = body.decode("utf-8", errors="replace")
        base_url = source_url

        def repl(m: re.Match) -> str:
            quote = m.group("quote") or ""
            original = m.group("url")
            rewritten = self._to_proxy_url(original, base_url, use_encryption=use_encryption)
            return f"url({quote}{rewritten}{quote})"

        pattern = re.compile(r'url\(\s*(?P<quote>[\'"]?)(?P<url>[^\'")]+)\s*(?P=quote)?\)', re.IGNORECASE)
        return pattern.sub(repl, text).encode("utf-8", errors="replace")

    def _rewrite_js_to_proxy(self, body: bytes, source_url: str, *, use_encryption: bool = False) -> bytes:
        """Rewrite simple import()/fetch()/static import URLs to go through proxy."""
        text = body.decode("utf-8", errors="replace")
        base_url = source_url

        def rewrite_literal(url_literal: str) -> str:
            return self._to_proxy_url(url_literal, base_url, use_encryption=use_encryption)

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

    def _to_proxy_url(self, url: str, base_url: str, *, use_encryption: bool = False) -> str:
        """Convert absolute/relative URL into proxied URL, preserving data/js/mailto."""
        if not url or url.startswith(("data:", "javascript:", "mailto:", "#")):
            return url
        if url.startswith(self._proxy_base):
            return url
        if url.startswith("//"):
            url = "https:" + url
        if not url.startswith(("http://", "https://")) and base_url:
            url = urljoin(base_url, url)
        # URL 全体をパスに埋め込むため、クエリを含めてエンコードして外側のクエリと衝突させない
        encoded = quote(url, safe="")
        proxied = self._proxy_base + encoded
        if use_encryption:
            parsed = urlsplit(proxied)
            params = parse_qs(parsed.query)
            if "enc" not in params and "e" not in params:
                sep = "&" if parsed.query else "?"
                proxied = proxied + f"{sep}enc=1"
        return proxied

    def _has_enc_cookie(self, headers: Mapping[str, str]) -> bool:
        cookie = headers.get("cookie") or headers.get("Cookie") or ""
        return "akari_enc=1" in cookie

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
    def _fetch_via_udp(
        self, url: str, *, use_encryption: bool = False, udp_client: AkariUdpClient | None = None
    ) -> ResponseOutcome:
        if not url.startswith(("http://", "https://")):
            raise ValueError("HTTP/HTTPS のみサポートします。")
        message_id = self._next_message_id()
        timestamp = int(time.time())
        client = udp_client or self._new_udp_client(use_encryption=use_encryption)
        try:
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

    def _merge_outer_params_into_url(self, url: str, outer_params: Mapping[str, list[str]]) -> str:
        """Move non-control query parameters from outer query back into the inner target URL.

        Browsers may append parameters (e.g., Google の `sei`) to the visible URL. Those should
        accompany the upstream request, not stay as control params. Control flags (entry/enc/_akari_ref)
        remain外側のまま。
        """
        control_keys = {"entry", "enc", "e", "_akari_ref"}
        extras = {k: v for k, v in outer_params.items() if k not in control_keys}
        if not extras:
            return url
        parsed = urlsplit(url)
        inner_qs = parse_qs(parsed.query)
        for k, vals in extras.items():
            if not vals:
                continue
            inner_qs.setdefault(k, [])
            inner_qs[k].extend(vals)
        new_query = urlencode(inner_qs, doseq=True)
        parsed = parsed._replace(query=new_query)
        return urlunsplit(parsed)

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
