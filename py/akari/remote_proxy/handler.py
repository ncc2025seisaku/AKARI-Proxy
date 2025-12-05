"""AKARI-UDP で届いたリクエストを HTTP 取得に結び付けるハンドラ."""

from __future__ import annotations

import logging
import time
import threading
from typing import Iterable, Sequence

from akari_udp_py import (
    encode_error_py,
    encode_error_v2_py,
    encode_response_chunk_py,
    encode_response_chunk_v2_py,
    encode_response_first_chunk_py,
    encode_response_first_chunk_v2_py,
)

from ..udp_server import IncomingRequest, encode_error_response
from .http_client import (
    BodyTooLargeError,
    FetchError,
    HttpResponse,
    InvalidURLError,
    TimeoutFetchError,
    fetch,
    fetch_async,
)

LOGGER = logging.getLogger(__name__)

MTU_PAYLOAD_SIZE = 1180
FIRST_CHUNK_METADATA_LEN = 8  # status(2) + hdr_len/reserved(2) + body_len(4)
FIRST_CHUNK_CAPACITY = max(MTU_PAYLOAD_SIZE - FIRST_CHUNK_METADATA_LEN, 0)
FLAG_HAS_HEADER = 0x40
FLAG_ENCRYPT = 0x80
REQUIRE_ENCRYPTION = False


def set_require_encryption(flag: bool) -> None:
    global REQUIRE_ENCRYPTION
    REQUIRE_ENCRYPTION = bool(flag)

ERROR_INVALID_URL = 10
ERROR_RESPONSE_TOO_LARGE = 11
ERROR_TIMEOUT = 20
ERROR_UPSTREAM_FAILURE = 30
ERROR_UNEXPECTED = 255
ERROR_UNSUPPORTED_PACKET = 254

# 簡易キャッシュ: message_id -> (timestamp, [datagrams])
RESP_CACHE_TTL = 5.0
RESP_CACHE: dict[int, tuple[float, list[bytes]]] = {}
RESP_CACHE_LOCK = threading.RLock()

# HTTPレスポンスの簡易キャッシュ
HTTP_CACHE_DEFAULT_TTL = 30.0
HTTP_CACHE: dict[str, tuple[float, HttpResponse]] = {}
HTTP_CACHE_LOCK = threading.RLock()
_fetch_async_func = fetch_async


def set_fetch_async_func(func):
    """テストやプール利用のために fetch_async 相当を差し替える。"""
    global _fetch_async_func
    _fetch_async_func = func


def _now_timestamp() -> int:
    return int(time.time())


def _clone_response(response: HttpResponse) -> HttpResponse:
    return {
        "status_code": int(response["status_code"]),
        "headers": dict(response.get("headers", {})),
        "body": bytes(response.get("body", b"")),
    }


def _normalize_cache_key(url: str) -> str:
    return url.strip()


def _cache_ttl_from_headers(headers: dict[str, str]) -> float | None:
    normalized_headers = {key.lower(): value for key, value in headers.items()}
    cache_control = normalized_headers.get("cache-control", "")
    directives = [directive.strip() for directive in cache_control.split(",") if directive.strip()]
    if any(directive in {"no-store", "no-cache"} for directive in directives):
        return None
    if "private" in directives:
        return None

    for directive in directives:
        if directive.startswith("max-age="):
            try:
                value = int(directive.split("=", 1)[1])
            except ValueError:
                continue
            if value <= 0:
                return None
            return float(value)

    if "set-cookie" in normalized_headers:
        return None
    return HTTP_CACHE_DEFAULT_TTL


def _purge_http_cache(now: float | None = None) -> None:
    now = now or time.time()
    with HTTP_CACHE_LOCK:
        expired = [url for url, (expires_at, _) in HTTP_CACHE.items() if expires_at <= now]
        for url in expired:
            HTTP_CACHE.pop(url, None)


def _get_cached_http_response(url: str, *, now: float | None = None) -> HttpResponse | None:
    now = now or time.time()
    with HTTP_CACHE_LOCK:
        cached = HTTP_CACHE.get(url)
        if not cached:
            return None
        expires_at, response = cached
        if expires_at <= now:
            HTTP_CACHE.pop(url, None)
            return None
        return _clone_response(response)


def _maybe_store_http_cache(url: str, response: HttpResponse, *, now: float | None = None) -> None:
    status = int(response.get("status_code", 0))
    if status >= 500:
        return
    ttl = _cache_ttl_from_headers(response.get("headers", {}))
    if ttl is None:
        return
    expires_at = (now or time.time()) + ttl
    with HTTP_CACHE_LOCK:
        HTTP_CACHE[url] = (expires_at, _clone_response(response))
        _purge_http_cache(now=now)


def _split_body(body: bytes) -> tuple[bytes, list[bytes]]:
    if FIRST_CHUNK_CAPACITY <= 0:
        first_chunk = b""
        remaining = body
    else:
        first_chunk = body[:FIRST_CHUNK_CAPACITY]
        remaining = body[FIRST_CHUNK_CAPACITY:]

    tail_chunks = [remaining[i : i + MTU_PAYLOAD_SIZE] for i in range(0, len(remaining), MTU_PAYLOAD_SIZE)]
    if not body:
        first_chunk = b""
    return first_chunk, tail_chunks


STATIC_HEADER_IDS: dict[str, int] = {
    "content-type": 1,
    "content-length": 2,
    "cache-control": 3,
    "etag": 4,
    "last-modified": 5,
    "date": 6,
    "server": 7,
    "content-encoding": 8,
    "accept-ranges": 9,
    "set-cookie": 10,
    "location": 11,
}


def _varint_u16(value: int) -> bytes:
    if value < 0 or value > 0xFFFF:
        raise ValueError("value out of range for u16 varint")
    # simple 2-byte big endian (spec varint簡略化)
    return value.to_bytes(2, "big")


def _encode_header_items(headers: dict[str, str]) -> Iterable[bytes]:
    for name, value in headers.items():
        lname = name.lower()
        value_bytes = value.encode("utf-8", errors="replace")
        if len(value_bytes) > 0xFFFF:
            continue  # skip overly large header to keep packet small
        if lname in STATIC_HEADER_IDS:
            yield bytes([STATIC_HEADER_IDS[lname]]) + _varint_u16(len(value_bytes)) + value_bytes
        else:
            name_bytes = lname.encode("utf-8", errors="replace")
            if len(name_bytes) > 0xFF:
                continue
            yield b"\x00" + bytes([len(name_bytes)]) + name_bytes + _varint_u16(len(value_bytes)) + value_bytes


def encode_header_block(headers: dict[str, str]) -> bytes:
    """Pack HTTP headers into the v2 static-table block."""
    return b"".join(_encode_header_items(headers))


def _encode_success_datagrams(request: IncomingRequest, response: HttpResponse) -> Sequence[bytes]:
    body = response["body"]
    body_len = len(body)
    timestamp = _now_timestamp()
    first_chunk, tail_chunks = _split_body(body)
    seq_total = max(1, 1 + len(tail_chunks))
    message_id = request.header["message_id"]
    version = int(request.header.get("version", 1))
    header_block = encode_header_block(response["headers"])
    flags = FLAG_HAS_HEADER if header_block else 0
    if request.header.get("flags", 0) & FLAG_ENCRYPT:
        flags |= FLAG_ENCRYPT

    if version >= 2:
        datagrams: list[bytes] = [
            encode_response_first_chunk_v2_py(
                response["status_code"],
                body_len,
                header_block,
                first_chunk,
                message_id,
                seq_total,
                flags,
                timestamp,
                request.psk,
            )
        ]
    else:
        datagrams = [
            encode_response_first_chunk_py(
                response["status_code"],
                body_len,
                first_chunk,
                message_id,
                seq_total,
                timestamp,
                request.psk,
            )
        ]

    for index, chunk in enumerate(tail_chunks, start=1):
        if version >= 2:
            datagrams.append(
                encode_response_chunk_v2_py(
                    chunk,
                    message_id,
                    index,
                    seq_total,
                    flags,
                    timestamp,
                    request.psk,
                )
            )
        else:
            datagrams.append(
                encode_response_chunk_py(
                    chunk,
                    message_id,
                    index,
                    seq_total,
                    timestamp,
                    request.psk,
                )
            )

    # キャッシュして再送に備える
    with RESP_CACHE_LOCK:
        RESP_CACHE[message_id] = (time.time(), datagrams)
        _purge_resp_cache()
    return datagrams


def _encode_error(
    request: IncomingRequest,
    *,
    error_code: int,
    http_status: int,
    message: str,
) -> Sequence[bytes]:
    safe_message = message if len(message) <= 200 else f"{message[:197]}..."
    LOGGER.warning(
        "failed to handle request message_id=%s url=%s error_code=%s status=%s message=%s",
        request.header.get("message_id"),
        request.payload.get("url"),
        error_code,
        http_status,
        safe_message,
    )
    version = int(request.header.get("version", 1))
    if version >= 2:
        datagram = encode_error_v2_py(
            error_code,
            http_status,
            safe_message,
            request.header["message_id"],
            request.header["timestamp"],
            request.psk,
        )
    else:
        datagram = encode_error_py(
            error_code,
            http_status,
            safe_message,
            request.header["message_id"],
            request.header["timestamp"],
            request.psk,
        )
    return (datagram,)


def _handle_nack(request: IncomingRequest) -> Sequence[bytes]:
    message_id = request.header.get("message_id")
    with RESP_CACHE_LOCK:
        if message_id not in RESP_CACHE:
            return ()
    bitmap = request.payload.get("bitmap")
    if not isinstance(bitmap, (bytes, bytearray)):
        return ()
    seqs = _bitmap_to_seq(bitmap)
    ts, cached = RESP_CACHE.get(message_id, (0.0, []))
    to_resend: list[bytes] = []
    for seq in seqs:
        if 0 <= seq < len(cached):
            to_resend.append(cached[seq])
    if to_resend:
        LOGGER.info("NACK resend message_id=%s seqs=%s", message_id, seqs)
    return to_resend


def _bitmap_to_seq(bitmap: bytes) -> list[int]:
    out: list[int] = []
    for idx, byte in enumerate(bitmap):
        for bit in range(8):
            if byte & (1 << bit):
                out.append(idx * 8 + bit)
    return out


def _handle_ack(request: IncomingRequest) -> Sequence[bytes]:
    """ACK で通知された first_lost_seq 以降を再送する。"""
    message_id = request.header.get("message_id")
    first_lost = request.payload.get("first_lost_seq")
    if not isinstance(first_lost, int):
        return ()
    with RESP_CACHE_LOCK:
        cached = RESP_CACHE.get(message_id)
        if not cached:
            return ()
        _, datagrams = cached
        if first_lost < 0 or first_lost >= len(datagrams):
            return ()
        return datagrams[first_lost:]


def _purge_resp_cache() -> None:
    now = time.time()
    with RESP_CACHE_LOCK:
        expired = [mid for mid, (ts, _) in RESP_CACHE.items() if now - ts > RESP_CACHE_TTL]
        for mid in expired:
            RESP_CACHE.pop(mid, None)


def clear_caches() -> None:
    """Clear in-memory response caches (for tests or debugging)."""
    with RESP_CACHE_LOCK:
        RESP_CACHE.clear()
    with HTTP_CACHE_LOCK:
        HTTP_CACHE.clear()


def handle_request(request: IncomingRequest) -> Sequence[bytes]:
    """AkariUdpServer から呼ばれるハンドラ本体."""

    if (
        REQUIRE_ENCRYPTION
        and request.packet_type == "req"
        and (int(request.header.get("flags", 0)) & FLAG_ENCRYPT) == 0
    ):
        return _encode_error(
            request,
            error_code=ERROR_UNSUPPORTED_PACKET,
            http_status=400,
            message="encryption required (set E flag)",
        )

    if request.packet_type == "nack":
        return _handle_nack(request)
    if request.packet_type == "ack":
        return _handle_ack(request)

    if request.packet_type != "req":
        return _encode_error(
            request,
            error_code=ERROR_UNSUPPORTED_PACKET,
            http_status=400,
            message=f"unsupported packet type: {request.packet_type}",
        )

    url = request.payload.get("url")
    if not isinstance(url, str) or not url:
        return _encode_error(
            request,
            error_code=ERROR_INVALID_URL,
            http_status=400,
            message="payload.url is missing",
        )

    normalized_url = _normalize_cache_key(url)

    LOGGER.info(
        "handling request message_id=%s url=%s from=%s",
        request.header.get("message_id"),
        normalized_url,
        request.addr,
    )

    now = time.time()
    _purge_http_cache(now=now)
    cached_response = _get_cached_http_response(normalized_url, now=now)
    if cached_response is not None:
        LOGGER.info("serve cached response message_id=%s url=%s", request.header.get("message_id"), normalized_url)
        return _encode_success_datagrams(request, cached_response)

    try:
        response = fetch(normalized_url)
    except InvalidURLError as exc:
        return _encode_error(
            request,
            error_code=ERROR_INVALID_URL,
            http_status=400,
            message=str(exc),
        )
    except BodyTooLargeError as exc:
        return _encode_error(
            request,
            error_code=ERROR_RESPONSE_TOO_LARGE,
            http_status=502,
            message=str(exc),
        )
    except TimeoutFetchError as exc:
        return _encode_error(
            request,
            error_code=ERROR_TIMEOUT,
            http_status=504,
            message=str(exc),
        )
    except FetchError as exc:
        return _encode_error(
            request,
            error_code=ERROR_UPSTREAM_FAILURE,
            http_status=502,
            message=str(exc),
        )
    except Exception as exc:  # noqa: BLE001 - 予期せぬ例外も握り潰してAKARIエラーで返す
        LOGGER.exception("unexpected error while fetching url=%s", url)
        return _encode_error(
            request,
            error_code=ERROR_UNEXPECTED,
            http_status=500,
            message="internal server error",
        )

    LOGGER.info(
        "success fetch message_id=%s status=%s body_len=%s",
        request.header.get("message_id"),
        response["status_code"],
        len(response["body"]),
    )
    _maybe_store_http_cache(normalized_url, response, now=time.time())
    return _encode_success_datagrams(request, response)


async def handle_request_async(request: IncomingRequest) -> Sequence[bytes]:
    """非同期サーバ用のハンドラ。fetch を async 版で行う以外は同じ。"""

    if (
        REQUIRE_ENCRYPTION
        and request.packet_type == "req"
        and (int(request.header.get("flags", 0)) & FLAG_ENCRYPT) == 0
    ):
        return _encode_error(
            request,
            error_code=ERROR_UNSUPPORTED_PACKET,
            http_status=400,
            message="encryption required (set E flag)",
        )

    if request.packet_type == "nack":
        return _handle_nack(request)
    if request.packet_type == "ack":
        return _handle_ack(request)

    if request.packet_type != "req":
        return _encode_error(
            request,
            error_code=ERROR_UNSUPPORTED_PACKET,
            http_status=400,
            message=f"unsupported packet type: {request.packet_type}",
        )

    url = request.payload.get("url")
    if not isinstance(url, str) or not url:
        return _encode_error(
            request,
            error_code=ERROR_INVALID_URL,
            http_status=400,
            message="payload.url is missing",
        )

    normalized_url = _normalize_cache_key(url)

    LOGGER.info(
        "handling request message_id=%s url=%s from=%s",
        request.header.get("message_id"),
        normalized_url,
        request.addr,
    )
    LOGGER.debug(
        "packet detail type=%s ver=%s flags=0x%x seq_total=%s",
        request.packet_type,
        request.header.get("version"),
        request.header.get("flags", 0),
        request.header.get("seq_total"),
    )

    now = time.time()
    _purge_http_cache(now=now)
    cached_response = _get_cached_http_response(normalized_url, now=now)
    if cached_response is not None:
        LOGGER.info("serve cached response message_id=%s url=%s", request.header.get("message_id"), normalized_url)
        return _encode_success_datagrams(request, cached_response)

    try:
        response = await _fetch_async_func(normalized_url)
    except InvalidURLError as exc:
        return _encode_error(
            request,
            error_code=ERROR_INVALID_URL,
            http_status=400,
            message=str(exc),
        )
    except BodyTooLargeError as exc:
        return _encode_error(
            request,
            error_code=ERROR_RESPONSE_TOO_LARGE,
            http_status=502,
            message=str(exc),
        )
    except TimeoutFetchError as exc:
        return _encode_error(
            request,
            error_code=ERROR_TIMEOUT,
            http_status=504,
            message=str(exc),
        )
    except FetchError as exc:
        return _encode_error(
            request,
            error_code=ERROR_UPSTREAM_FAILURE,
            http_status=502,
            message=str(exc),
        )
    except Exception:  # noqa: BLE001
        LOGGER.exception("unexpected error while fetching url=%s", url)
        return _encode_error(
            request,
            error_code=ERROR_UNEXPECTED,
            http_status=500,
            message="internal server error",
        )

    LOGGER.info(
        "success fetch message_id=%s status=%s body_len=%s",
        request.header.get("message_id"),
        response["status_code"],
        len(response["body"]),
    )
    _maybe_store_http_cache(normalized_url, response, now=time.time())
    return _encode_success_datagrams(request, response)
