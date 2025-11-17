"""HTTP/HTTPSレスポンス取得ロジック.

`docs/AKARI.md` と `docs/architecture.md` で記載された「外部プロキシが
HTTPクライアントとしてWebサイトへアクセスし、レスポンスを取得する」責務の
うち、URL取得部分だけを初心者でもすぐ使えるように切り出している。
"""

from __future__ import annotations

import socket
from typing import TypedDict
from urllib import error, parse, request

DEFAULT_TIMEOUT = 5.0
MAX_BODY_BYTES = 1_000_000
USER_AGENT = "AKARI-Proxy/0.1"


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
        headers={"User-Agent": USER_AGENT},
    )

    try:
        with request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise BodyTooLargeError(max_bytes)

            headers = {key: value for key, value in resp.getheaders()}
            return {
                "status_code": resp.getcode(),
                "headers": headers,
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
