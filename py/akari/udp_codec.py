"""Python UDP codec wrapper with pakcet inspection CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from akari_udp_py import decode_packet_py, debug_dump_py


def read_stdin_bytes() -> bytes:
    data = sys.stdin.buffer.read()
    if not data:
        raise SystemExit("want binary datagram from stdin")
    return data


def normalize_object(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, Mapping):
        return {key: normalize_object(val) for key, val in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [normalize_object(item) for item in value]
    return value


def parse_psk(value: str, *, hex_mode: bool) -> bytes:
    if hex_mode:
        return bytes.fromhex(value)
    return value.encode("utf-8")


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="akari-udp-dump: inspect AKARI-UDP packets")
    parser.add_argument("--psk", default="test-psk-0000-test", help="pre-shared key (plain text or hex)")
    parser.add_argument("--hex", action="store_true", help="treat --psk value as hex")
    parser.add_argument("--debug", action="store_true", help="print text dump instead of JSON")
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    args = parser.parse_args(argv)

    datagram = read_stdin_bytes()
    psk = parse_psk(args.psk, hex_mode=args.hex)

    if args.debug:
        print(debug_dump_py(datagram, psk), end="")
        return

    parsed = decode_packet_py(datagram, psk)
    normalized = normalize_object(parsed)
    indent = 2 if args.pretty else None
    print(json.dumps(normalized, ensure_ascii=False, indent=indent))


if __name__ == "__main__":
    main()
