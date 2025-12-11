"""AKARI-UDP で届いたリクエストを HTTP 取得に結び付けるハンドラ."""

from __future__ import annotations

import logging
import time
import threading
import hmac
import hashlib
from typing import Iterable, Sequence

from akari_udp_py import (
    encode_error_py,
    encode_error_v2_py,
    encode_error_v3_py,
    encode_nack_body_v3_py,
    encode_nack_head_v3_py,
    encode_resp_body_v3_py,
    encode_resp_head_cont_v3_py,
    encode_resp_head_v3_py,
    encode_resp_body_v3_agg_py,
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

# MTU 1200B を前提に「IP/UDPヘッダ + AKARIヘッダ + HMACタグ + ペイロード」が収まるようにする。
# これまで PROTO_OVERHEAD のみを引いており、実際のワイヤサイズが 1200B を超えて断片化→ロス→NACK 多発していた。
DEFAULT_MAX_DATAGRAM = 1150  # 1200B MTU想定から少し余裕を削って断片化を更に回避
PROTO_OVERHEAD = 24 + 16  # AKARI 固定ヘッダ + HMAC/AEAD tag (v2まで)
UDP_IP_OVERHEAD = 48  # IPv6 worst-case を前提にしてより保守的に
SAFETY_MARGIN = 32  # 余白を拡大して計算ズレや NIC オフロード差分を吸収
RESPONSE_FIRST_OVERHEAD = 8  # status(2) + hdr_len/0x0000(2) + body_len(4)
FLAG_HAS_HEADER = 0x40
FLAG_ENCRYPT = 0x80
REQUIRE_ENCRYPTION = False

# v3 固定ヘッダ/タグ（短縮ヘッダ想定）
V3_FIXED_HDR = 8  # magic(2)+ver/type/flags/res(2?) + short-id(2) + seq/seq_total/payload_len(6) ざっくり
V3_TAG = 16  # aggregateでもタグ自体は1回


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


def _max_datagram_size(buffer_size: int | None, payload_max: int | None = None) -> int:
    """送信可能な datagram 最大サイズを決める（MTU 1200B を上限）。"""
    cap = payload_max if payload_max and payload_max > 0 else DEFAULT_MAX_DATAGRAM
    if buffer_size and buffer_size > 0:
        return min(buffer_size, cap)
    return cap


def _calc_payload_caps(buffer_size: int | None, header_block_len: int, payload_max: int | None) -> tuple[int, int]:
    """先頭チャンク/後続チャンクの最大ペイロード長を計算する."""

    base_cap = _payload_cap(buffer_size, payload_max)
    cap_tail = base_cap
    # 先頭チャンクは status/hdr_len/body_len の 8B 固定オーバーヘッドを差し引いた上でヘッダブロック長を考慮
    # payload_first = 8 + header_block_len + chunk_first <= base_cap
    cap_first = max(base_cap - RESPONSE_FIRST_OVERHEAD - header_block_len, 1)
    return cap_first, cap_tail


def _payload_cap(buffer_size: int | None, payload_max: int | None) -> int:
    """ペイロードに割ける最大バイト数（seq>=1 のチャンク上限）"""
    max_dgram = _max_datagram_size(buffer_size, payload_max)
    return max(max_dgram - UDP_IP_OVERHEAD - PROTO_OVERHEAD - SAFETY_MARGIN, 1)


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


def _split_body(body: bytes, *, buffer_size: int | None, header_block_len: int, payload_max: int | None) -> tuple[bytes, list[bytes]]:
    cap_first, cap_tail = _calc_payload_caps(buffer_size, header_block_len, payload_max)

    first_chunk = body[:cap_first]
    remaining = body[cap_first:]
    tail_chunks = [remaining[i : i + cap_tail] for i in range(0, len(remaining), cap_tail)] if remaining else []

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


HEADERS_WHITELIST = {
    "content-type",
    "content-length",
    "cache-control",
    "etag",
    "last-modified",
    "date",
    "server",
    "content-encoding",
    "accept-ranges",
    "location",
}


def _shrink_headers(headers: dict[str, str], *, value_max: int = 256) -> dict[str, str]:
    """ヘッダを安全な短い集合に縮約する。長すぎる値は切り詰める。"""
    out: dict[str, str] = {}
    for name, value in headers.items():
        lname = name.lower()
        if lname not in HEADERS_WHITELIST:
            continue
        vbytes = value.encode("utf-8", errors="replace")
        if len(vbytes) > value_max:
            vbytes = vbytes[:value_max]
        out[lname] = vbytes.decode("utf-8", errors="replace")
    return out


def _encode_header_block_limited(headers: dict[str, str], cap: int) -> tuple[bytes, bool]:
    """ヘッダブロックを cap バイト以内に収める。重要ヘッダ優先で詰め、超えたら残りを落とす。

    戻り値: (block, truncated_flag)
    """
    normalized = {k.lower(): v for k, v in headers.items()}
    priority = [
        "content-type",
        "content-length",
        "cache-control",
        "etag",
        "last-modified",
        "date",
        "server",
        "content-encoding",
        "accept-ranges",
        "location",
    ]
    block_headers: dict[str, str] = {}

    # 優先ヘッダを先に詰める
    for key in priority:
        if key in normalized:
            block_headers[key] = normalized.pop(key)

    # 残りから大きい/不要なものを除外（Cookie 系は落とす）
    for key in list(normalized.keys()):
        if key in {"set-cookie", "cookie"}:
            continue
        block_headers[key] = normalized[key]

    encoded = b""
    truncated = False
    for k, v in block_headers.items():
        trial = encode_header_block({k: v})
        if len(encoded) + len(trial) > cap:
            truncated = True
            break
        encoded += trial

    return encoded, truncated


def _encode_success_datagrams(request: IncomingRequest, response: HttpResponse) -> Sequence[bytes]:
    body = response["body"]
    body_len = len(body)
    timestamp = _now_timestamp()
    buffer_size = getattr(request, "buffer_size", None)
    payload_max = getattr(request, "payload_max", None)
    base_cap = _payload_cap(buffer_size, payload_max)
    header_cap = max(base_cap - RESPONSE_FIRST_OVERHEAD - 64, 1)  # 先頭チャンクに 64B 余白を残す

    # 1) ヘッダを白リスト・長さ上限で縮約
    shrunk_headers = _shrink_headers(response["headers"])
    # 2) cap に収める
    header_block, truncated = _encode_header_block_limited(shrunk_headers, header_cap)
    if truncated:
        LOGGER.warning(
            "header block truncated to %dB (cap=%dB) message_id=%s",
            len(header_block),
            header_cap,
            request.header.get("message_id"),
        )

    first_chunk, tail_chunks = _split_body(body, buffer_size=buffer_size, header_block_len=len(header_block), payload_max=payload_max)
    seq_total = max(1, 1 + len(tail_chunks))
    message_id = request.header["message_id"]
    version = int(request.header.get("version", 1))
    flags = FLAG_HAS_HEADER if header_block else 0
    if request.header.get("flags", 0) & FLAG_ENCRYPT:
        flags |= FLAG_ENCRYPT

    if version >= 3:
        datagrams = _encode_success_datagrams_v3(
            request,
            response,
            header_block=header_block,
            body_len=body_len,
            first_chunk=first_chunk,
            tail_chunks=tail_chunks,
            seq_total=seq_total,
        )
    elif version >= 2:
        datagrams = [
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
        for index, chunk in enumerate(tail_chunks, start=1):
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

    # 安全チェック: 送信datagramがバッファ/MTU想定を超えていないか
    max_dgram = _max_datagram_size(buffer_size)
    for idx, datagram in enumerate(datagrams):
        if len(datagram) > max_dgram:
            LOGGER.warning(
                "response datagram too large len=%d max=%d message_id=%s seq=%s/%s",
                len(datagram),
                max_dgram,
                message_id,
                idx,
                seq_total,
            )

    # キャッシュして再送に備える
    with RESP_CACHE_LOCK:
        RESP_CACHE[message_id] = (time.time(), datagrams)
        _purge_resp_cache()

    LOGGER.info(
        "encode success message_id=%s status=%s body_len=%s seq_total=%s header_len=%s",
        message_id,
        response.get("status_code"),
        body_len,
        seq_total,
        len(header_block),
    )
    return datagrams


def _encode_success_datagrams_v3(
    request: IncomingRequest,
    response: HttpResponse,
    *,
    header_block: bytes,
    body_len: int,
    first_chunk: bytes,
    tail_chunks: list[bytes],
    seq_total: int,
) -> list[bytes]:
    """v3レスポンスを組み立てる（現状はパケットごとタグ、集約タグは後続）。"""
    flags = 0x40  # agg-tag要望フラグ（サーバ非対応でも無害）
    encrypt = (request.header.get("flags", 0) & FLAG_ENCRYPT) != 0
    if encrypt:
        flags |= FLAG_ENCRYPT
    message_id = request.header["message_id"]
    payload_max = getattr(request, "payload_max", None)
    buffer_size = getattr(request, "buffer_size", None)

    # ヘッダ分割（capは先頭チャンクを想定し、固定8Bくらいを引く簡易計算）
    base_cap = _payload_cap(buffer_size, payload_max)
    cap_header = max(base_cap - 8, 1)
    hdr_chunks_list = [header_block[i : i + cap_header] for i in range(0, len(header_block), cap_header)] or [b""]
    hdr_chunks_count = len(hdr_chunks_list)

    datagrams: list[bytes] = []
    # ヘッダ最初のチャンク
    datagrams.append(
        encode_resp_head_v3_py(
            response["status_code"],
            hdr_chunks_list[0],
            body_len,
            hdr_chunks_count,
            0,
            seq_total,
            flags,
            message_id,
            request.psk,
        )
    )
    # 継続ヘッダ
    for idx, hdr_chunk in enumerate(hdr_chunks_list[1:], start=1):
        datagrams.append(
            encode_resp_head_cont_v3_py(
                hdr_chunk,
                idx,
                hdr_chunks_count,
                flags,
                message_id,
                request.psk,
            )
        )
    body_chunks = [first_chunk] + tail_chunks
    if flags & 0x40:
        # aggregateタグを計算（ボディ平文でHMAC-SHA256の先頭16B）
        agg_tag = hmac.new(request.psk, b"".join(body_chunks), hashlib.sha256).digest()[:16]
        for idx, chunk in enumerate(body_chunks):
            is_last = idx == len(body_chunks) - 1
            datagrams.append(
                encode_resp_body_v3_agg_py(
                    chunk,
                    idx,
                    seq_total,
                    flags,
                    message_id,
                    agg_tag if is_last else None,
                    request.psk,
                )
            )
    else:
        for idx, chunk in enumerate(body_chunks):
            datagrams.append(
                encode_resp_body_v3_py(
                    chunk,
                    idx,
                    seq_total,
                    flags,
                    message_id,
                    request.psk,
                )
            )
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
    if version >= 3:
        datagram = encode_error_v3_py(
            safe_message,
            error_code,
            http_status,
            request.header["message_id"],
            0,
            request.psk,
        )
    elif version >= 2:
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
    # v3のbody NACKは body seq を指す。キャッシュの0番目はヘッダなので +1 でずらす。
    offset = 1 if request.packet_type == "nack-body" else 0
    for seq in seqs:
        idx = seq + offset
        if 0 <= idx < len(cached):
            to_resend.append(cached[idx])
    if to_resend:
        LOGGER.info("NACK resend message_id=%s seqs=%s offset=%s", message_id, seqs, offset)
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

    if request.packet_type in {"nack", "nack-body", "nack-head"}:
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

    if request.packet_type in {"nack", "nack-body", "nack-head"}:
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
