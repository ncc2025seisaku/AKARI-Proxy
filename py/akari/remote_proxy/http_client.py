"""HTTP/HTTPSレスポンス取得ロジック.

`docs/AKARI.md` と `docs/architecture.md` で記載された「外部プロキシが
HTTPクライアントとしてWebサイトへアクセスし、レスポンスを取得する」責務の
うち、URL取得部分だけを初心者でもすぐ使えるように切り出している。

同期版(fetch)と非同期版(fetch_async)の双方を提供する。
"""

from __future__ import annotations

import socket
import asyncio
from typing import TypedDict
from urllib import error, parse, request

DEFAULT_TIMEOUT = 10.0
# 実験用に上限を拡大（1GB）
MAX_BODY_BYTES = 1_000_000_000
USER_AGENT = "AKARI-Proxy/0.1"
# Prefer Brotli for効率, fallback to gzip/deflate.
ACCEPT_ENCODING = "br, gzip, deflate"

# セキュリティ関連ヘッダのブラックリスト（iframe埋め込みやCSP制約を除去）
HEADERS_BLACKLIST = {
    "x-frame-options",
    "content-security-policy",
    "content-security-policy-report-only",
}


def _strip_security_headers(headers: dict[str, str]) -> dict[str, str]:
    """ブラックリストに含まれるセキュリティヘッダを除去する。"""
    return {k: v for k, v in headers.items() if k.lower() not in HEADERS_BLACKLIST}


class HttpResponse(TypedDict):
    """外部プロキシが AKARI-UDP に返却する前の素のレスポンス情報。"""

    status_code: int
    headers: dict[str, str]
    body: bytes


class FetchError(Exception):
    """取得失敗時の基底例外。"""


class InvalidURLError(FetchError):
    """HTTP/HTTPS以外やフォーマット不備を知らせる例外。"""

    def __init__(self, url: str) -> None:
        super().__init__(f"サポート外か不正なURLです: {url!r}")


class BodyTooLargeError(FetchError):
    """レスポンスボディが許容サイズを超えた場合に送出される。"""

    def __init__(self, limit: int) -> None:
        super().__init__(f"レスポンスボディが{limit}バイトの上限を超えました")


class TimeoutFetchError(FetchError):
    """タイムアウト時の例外。"""

    def __init__(self, timeout: float) -> None:
        super().__init__(f"{timeout}秒以内にレスポンスを受信できませんでした")


def _normalize_url(url: str) -> str:
    normalized = url.strip()
    if not normalized:
        raise InvalidURLError(url)

    parsed = parse.urlparse(normalized)
    if parsed.scheme not in ("http", "https"):
        raise InvalidURLError(url)
    if not parsed.netloc:
        raise InvalidURLError(url)
    return normalized


def fetch(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = MAX_BODY_BYTES,
) -> HttpResponse:
    """URLにGETアクセスしてレスポンスを返す。

    Args:
        url: 取得したいHTTP/HTTPS URL。
        timeout: 秒単位のタイムアウト。docs/architecture.mdの推奨値に合わせ5秒既定。
        max_bytes: ボディ取得の安全上限。超過時は BodyTooLargeError を送出。
    """

    normalized_url = _normalize_url(url)
    req = request.Request(
        normalized_url,
        method="GET",
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Encoding": ACCEPT_ENCODING,
        },
    )

    import os
    import ssl
    context = None
    if os.environ.get("AKARI_INSECURE_FETCH"):
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

    try:
        with request.urlopen(req, timeout=timeout, context=context) as resp:
            body = resp.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise BodyTooLargeError(max_bytes)

            headers = {key: value for key, value in resp.getheaders()}
            return {
                "status_code": resp.getcode(),
                "headers": _strip_security_headers(headers),
                "body": body,
            }
    except error.HTTPError as exc:
        raise FetchError(f"HTTPエラー {exc.code}: {exc.reason}") from exc
    except socket.timeout as exc:
        raise TimeoutFetchError(timeout) from exc
    except error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, socket.timeout):
            raise TimeoutFetchError(timeout) from exc
        raise FetchError(str(reason)) from exc


async def fetch_async(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = MAX_BODY_BYTES,
    session=None,
    ) -> HttpResponse:
    """非同期版 GET 取得。aiohttp を使用する。"""

    try:
        import aiohttp  # type: ignore
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("aiohttp がインストールされていません") from exc

    normalized_url = _normalize_url(url)
    timeout_cfg = aiohttp.ClientTimeout(total=timeout, sock_read=timeout, sock_connect=timeout)

    async def _do(session_obj: "aiohttp.ClientSession") -> HttpResponse:
        try:
            async with session_obj.get(
                normalized_url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept-Encoding": ACCEPT_ENCODING,
                },
                allow_redirects=True,
                compress=False,  # 明示的に圧縮解除をさせない（raw転送）
            ) as resp:
                body_parts: list[bytes] = []
                async for chunk in resp.content.iter_chunked(64 * 1024):
                    body_parts.append(chunk)
                    if sum(len(c) for c in body_parts) > max_bytes:
                        raise BodyTooLargeError(max_bytes)
                body = b"".join(body_parts)
                headers = {k: v for k, v in resp.headers.items()}
                return {
                    "status_code": resp.status,
                    "headers": _strip_security_headers(headers),
                    "body": body,
                }
        except asyncio.TimeoutError as exc:
            raise TimeoutFetchError(timeout) from exc
        except aiohttp.InvalidURL as exc:
            raise InvalidURLError(str(exc)) from exc
        except aiohttp.ClientResponseError as exc:
            raise FetchError(f"HTTPエラー {exc.status}: {exc.message}") from exc
        except aiohttp.ClientError as exc:
            raise FetchError(str(exc)) from exc

    if session is not None:
        return await _do(session)

    async with aiohttp.ClientSession(timeout=timeout_cfg, auto_decompress=False) as owned_session:
        return await _do(owned_session)
