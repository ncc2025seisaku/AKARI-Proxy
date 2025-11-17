"""AKARI-UDP で届いたリクエストを HTTP 取得に結び付けるハンドラ."""

from __future__ import annotations

import logging
import time
from typing import Sequence

from akari_udp_py import encode_response_chunk_py, encode_response_first_chunk_py

from ..udp_server import IncomingRequest, encode_error_response
from .http_client import (
    BodyTooLargeError,
    FetchError,
    HttpResponse,
    InvalidURLError,
    TimeoutFetchError,
    fetch,
)

LOGGER = logging.getLogger(__name__)

MTU_PAYLOAD_SIZE = 1180
FIRST_CHUNK_METADATA_LEN = 8
FIRST_CHUNK_CAPACITY = max(MTU_PAYLOAD_SIZE - FIRST_CHUNK_METADATA_LEN, 0)

ERROR_INVALID_URL = 10
ERROR_RESPONSE_TOO_LARGE = 11
ERROR_TIMEOUT = 20
ERROR_UPSTREAM_FAILURE = 30
ERROR_UNEXPECTED = 255
ERROR_UNSUPPORTED_PACKET = 254


def _now_timestamp() -> int:
    return int(time.time())


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


def _encode_success_datagrams(request: IncomingRequest, response: HttpResponse) -> Sequence[bytes]:
    body = response["body"]
    body_len = len(body)
    timestamp = _now_timestamp()
    first_chunk, tail_chunks = _split_body(body)
    seq_total = max(1, 1 + len(tail_chunks))
    message_id = request.header["message_id"]

    datagrams: list[bytes] = [
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
    return encode_error_response(
        request,
        error_code=error_code,
        http_status=http_status,
        message=safe_message,
    )


def handle_request(request: IncomingRequest) -> Sequence[bytes]:
    """AkariUdpServer から呼ばれるハンドラ本体."""

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

    LOGGER.info(
        "handling request message_id=%s url=%s from=%s",
        request.header.get("message_id"),
        url,
        request.addr,
    )

    try:
        response = fetch(url)
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
    return _encode_success_datagrams(request, response)
