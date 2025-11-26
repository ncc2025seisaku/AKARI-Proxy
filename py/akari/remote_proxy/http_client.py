"""HTTP/HTTPS????????????

`docs/AKARI.md` ? `docs/architecture.md` ???????????
HTTP?????????Web???????????????????????
"""

from __future__ import annotations

import socket
from typing import Mapping, TypedDict
from urllib import error, parse, request

DEFAULT_TIMEOUT = 10.0
MAX_BODY_BYTES = 1_000_000
USER_AGENT = "AKARI-Proxy/0.1"
# Prefer Brotli for??, fallback to gzip/deflate.
ACCEPT_ENCODING = "br, gzip, deflate"


class HttpResponse(TypedDict):
    """????? AKARI-UDP ?????HTTP??????"""

    status_code: int
    headers: dict[str, str]
    body: bytes


class FetchError(Exception):
    """??????????"""


class InvalidURLError(FetchError):
    """HTTP/HTTPS???????????????"""

    def __init__(self, url: str) -> None:
        super().__init__(f"????????URL??: {url!r}")


class BodyTooLargeError(FetchError):
    """?????????????????????????"""

    def __init__(self, limit: int) -> None:
        super().__init__(f"?????????{limit}????????????")


class TimeoutFetchError(FetchError):
    """???????????"""

    def __init__(self, timeout: float) -> None:
        super().__init__(f"{timeout}?????????????????????")


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
    conditional_headers: Mapping[str, str] | None = None,
) -> HttpResponse:
    """URL?GET???????????304??????????"""

    normalized_url = _normalize_url(url)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept-Encoding": ACCEPT_ENCODING,
    }
    if conditional_headers:
        headers.update(conditional_headers)

    req = request.Request(
        normalized_url,
        method="GET",
        headers=headers,
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
        if exc.code == 304:
            headers = {key: value for key, value in exc.headers.items()} if exc.headers else {}
            return {
                "status_code": exc.code,
                "headers": headers,
                "body": b"",
            }
        raise FetchError(f"HTTP error {exc.code}: {exc.reason}") from exc
    except socket.timeout as exc:
        raise TimeoutFetchError(timeout) from exc
    except error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, socket.timeout):
            raise TimeoutFetchError(timeout) from exc
        raise FetchError(str(reason)) from exc
