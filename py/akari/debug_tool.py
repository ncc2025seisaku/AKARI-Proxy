"""簡易デバッグスクリプト。単発で encode/decode を確認できます。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from textwrap import wrap
from typing import Iterable, Sequence

from akari_udp_py import (
    debug_dump_py,
    decode_packet_py,
    encode_error_py,
    encode_request_py,
    encode_response_first_chunk_py,
)


def read_datagram(path: str | None, *, psk: bytes, mode: str, url: str, message_id: int, timestamp: int, **kwargs) -> bytes:
    if path:
        return Path(path).read_bytes()
    if mode == "req":
        datagram = encode_request_py(url, message_id, timestamp, psk)
    elif mode == "resp":
        body = kwargs.get("body", "hello")
        status = kwargs.get("status", 200)
        seq_total = kwargs.get("seq_total", 1)
        datagram = encode_response_first_chunk_py(
            status,
            len(body),
            body.encode("utf-8"),
            message_id,
            seq_total,
            timestamp,
            psk,
        )
    elif mode == "error":
        error_code = kwargs.get("error_code", 1)
        http_status = kwargs.get("http_status", 502)
        message = kwargs.get("message", "error")
        datagram = encode_error_py(error_code, http_status, message, message_id, timestamp, psk)
    else:
        raise SystemExit(f"unsupported mode: {mode}")

    if isinstance(datagram, bytes):
        return datagram
    return bytes(datagram)


def parse_psk(value: str, *, hex_mode: bool) -> bytes:
    if hex_mode:
        return bytes.fromhex(value)
    return value.encode("utf-8")


def hex_dump(data: bytes, width: int = 16) -> str:
    return "\n".join(
        f"{i*width:04x}  " + " ".join(f"{b:02x}" for b in chunk) + "  " + "".join(
            chr(b) if 32 <= b < 127 else "." for b in chunk
        )
        for i, chunk in enumerate([data[i:i+width] for i in range(0, len(data), width)])
    )


def normalize_object(value):
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, dict):
        return {k: normalize_object(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize_object(v) for v in value]
    return value


def dump_json(datagram: bytes, psk: bytes, pretty: bool) -> dict:
    parsed = decode_packet_py(datagram, psk)
    normalized = normalize_object(parsed)
    indent = 2 if pretty else None
    print(json.dumps(normalized, ensure_ascii=False, indent=indent))
    return normalized


def dump_text(datagram: bytes, psk: bytes) -> str:
    text = debug_dump_py(datagram, psk)
    print(text)
    return text


def dict_diff(a: dict, b: dict, path: str = "") -> list[str]:
    diffs: list[str] = []
    for key in sorted(set(a.keys()) | set(b.keys())):
        new_path = f"{path}.{key}" if path else key
        if key not in a:
            diffs.append(f"{new_path} missing in expected")
            continue
        if key not in b:
            diffs.append(f"{new_path} missing in parsed")
            continue
        va, vb = a[key], b[key]
        if isinstance(va, dict) and isinstance(vb, dict):
            diffs.extend(dict_diff(va, vb, new_path))
        elif isinstance(va, list) and isinstance(vb, list):
            for idx in range(max(len(va), len(vb))):
                pa = va[idx] if idx < len(va) else None
                pb = vb[idx] if idx < len(vb) else None
                if pa != pb:
                    diffs.append(f"{new_path}[{idx}] differs: {pa!r} vs {pb!r}")
        else:
            if va != vb:
                diffs.append(f"{new_path} differs: {va!r} vs {vb!r}")
    return diffs


def expected_payload(mode: str, url: str, body: str, status: int, message: str, error_code: int) -> dict:
    if mode == "req":
        return {"payload": {"url": url}, "type": "req"}
    if mode == "resp":
        return {
            "payload": {
                "chunk": body.encode("utf-8").hex(),
                "status_code": status,
                "body_len": len(body),
                "is_first": True,
            },
            "type": "resp",
        }
    if mode == "error":
        return {
            "payload": {
                "error_code": error_code,
                "http_status": status,
                "message": message,
            },
            "type": "error",
        }
    return {}


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="akari-udp-debug: encode/sample + inspect without extra pipes"
    )
    parser.add_argument("--mode", choices=("req", "resp", "error"), default="req", help="生成するメッセージの種類")
    parser.add_argument("--psk", default="test-psk-0000-test", help="事前共有鍵（文字列）")
    parser.add_argument("--hex", action="store_true", help="--psk を hex 文字列として解釈")
    parser.add_argument("--url", default="https://example.com", help="デフォルトの URL")
    parser.add_argument("--message-id", type=lambda v: int(v, 0), default=0x1234, help="message_id")
    parser.add_argument("--timestamp", type=lambda v: int(v, 0), default=0x5f3759df, help="timestamp")
    parser.add_argument(
        "--datagram",
        help="既存 datagram ファイルを指定すると encode はスキップ",
    )
    parser.add_argument("--status", type=int, default=200, help="response/error のステータスコード")
    parser.add_argument("--body", default="hello", help="response の body chunk")
    parser.add_argument("--error-code", type=int, default=1, help="error packet の error_code")
    parser.add_argument("--message", default="error", help="error packet の message")
    parser.add_argument("--no-diff", action="store_true", help="パラメータと復元 JSON の差分を表示しない")
    parser.add_argument("--no-hex", action="store_true", help="バイト列の hex ダンプを表示しない")
    parser.add_argument("--text", action="store_true", help="テキストダンプを出力（debug_dump）")
    parser.add_argument("--pretty", action="store_true", help="JSON を整形して表示")
    args = parser.parse_args(argv)

    psk = parse_psk(args.psk, hex_mode=args.hex)
    datagram = read_datagram(
        args.datagram,
        psk=psk,
        mode=args.mode,
        url=args.url,
        message_id=args.message_id,
        timestamp=args.timestamp,
        body=args.body,
        status=args.status,
        error_code=args.error_code,
        http_status=args.status,
        message=args.message,
    )

    if args.text:
        dump_text(datagram, psk)
    else:
        parsed = dump_json(datagram, psk, pretty=args.pretty)
        if not args.no_diff:
            expected = expected_payload(
                args.mode,
                args.url,
                args.body,
                args.status,
                args.message,
                args.error_code,
            )
            diffs = dict_diff(expected, parsed)
            if diffs:
                print("\n-- diff --")
                print("\n".join(diffs))
        if not args.no_hex:
            print("\n-- hex --")
            print(hex_dump(datagram))


def run(argv: Iterable[str] | None = None) -> None:
    main(list(argv) if argv else None)


if __name__ == "__main__":
    run()
