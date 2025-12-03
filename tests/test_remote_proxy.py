import sys
import threading
import unittest
from pathlib import Path
from typing import Sequence
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py"))

from akari import AkariUdpClient
from akari.remote_proxy.handler import (
    ERROR_INVALID_URL,
    ERROR_RESPONSE_TOO_LARGE,
    ERROR_TIMEOUT,
    ERROR_UNEXPECTED,
    ERROR_UNSUPPORTED_PACKET,
    ERROR_UPSTREAM_FAILURE,
    FIRST_CHUNK_CAPACITY,
    MTU_PAYLOAD_SIZE,
    RESP_CACHE,
    _handle_ack,
    _handle_nack,
    _encode_success_datagrams,
    handle_request,
)
from akari.remote_proxy.http_client import (
    BodyTooLargeError,
    FetchError,
    InvalidURLError,
    TimeoutFetchError,
)
from akari.udp_client import AkariUdpClient as AkariUdpClientClass, ResponseAccumulator, _to_native
from akari.udp_server import AkariUdpServer, IncomingRequest
from akari_udp_py import decode_packet_py


class RemoteProxyHandlerTest(unittest.TestCase):
    PSK = b"test-psk-0000-test"

    def _make_request(self, *, url: str = "https://example.com", version: int = 2) -> IncomingRequest:
        return IncomingRequest(
            header={"message_id": 0x1234, "timestamp": 0x55, "version": version},
            payload={"url": url},
            packet_type="req",
            addr=("127.0.0.1", 9000),
            parsed={},
            datagram=b"",
            psk=self.PSK,
        )

    def _decode(self, datagram: bytes) -> dict:
        parsed = decode_packet_py(bytes(datagram), self.PSK)
        return _to_native(parsed)

    def tearDown(self) -> None:
        from akari.remote_proxy.handler import clear_caches

        clear_caches()

    def test_handle_request_splits_body_into_multiple_chunks(self) -> None:
        body = b"A" * (FIRST_CHUNK_CAPACITY + MTU_PAYLOAD_SIZE + 10)
        response = {"status_code": 206, "headers": {}, "body": body}

        with patch("akari.remote_proxy.handler.fetch", return_value=response), patch(
            "akari.remote_proxy.handler._now_timestamp", return_value=0x99
        ):
            datagrams = handle_request(self._make_request())

        remaining = len(body) - FIRST_CHUNK_CAPACITY
        expected_total = 1 + ((remaining + MTU_PAYLOAD_SIZE - 1) // MTU_PAYLOAD_SIZE)

        self.assertEqual(len(datagrams), expected_total)

        parsed_packets = [self._decode(datagram) for datagram in datagrams]
        first_payload = parsed_packets[0]["payload"]
        self.assertEqual(first_payload["seq_total"], expected_total)
        self.assertEqual(first_payload["status_code"], 206)
        self.assertEqual(first_payload["body_len"], len(body))
        self.assertEqual(first_payload["chunk"], body[:FIRST_CHUNK_CAPACITY])

        assembled = b"".join(packet["payload"]["chunk"] for packet in parsed_packets)
        self.assertEqual(assembled, body)

    def test_handle_request_error_mapping(self) -> None:
        cases = [
            (InvalidURLError("bad"), ERROR_INVALID_URL, 400),
            (BodyTooLargeError(10), ERROR_RESPONSE_TOO_LARGE, 502),
            (TimeoutFetchError(5), ERROR_TIMEOUT, 504),
            (FetchError("generic failure"), ERROR_UPSTREAM_FAILURE, 502),
        ]

        for exc, code, status in cases:
            with self.subTest(exc=exc):
                with patch("akari.remote_proxy.handler.fetch", side_effect=exc):
                    datagrams = handle_request(self._make_request())
                payload = self._decode(datagrams[0])["payload"]
                self.assertEqual(payload["error_code"], code)
                self.assertEqual(payload["http_status"], status)

    def test_handle_request_missing_url(self) -> None:
        request = self._make_request()
        request.payload = {}
        datagrams = handle_request(request)
        payload = self._decode(datagrams[0])["payload"]
        self.assertEqual(payload["error_code"], ERROR_INVALID_URL)
        self.assertEqual(payload["http_status"], 400)

    def test_handle_request_rejects_non_request_packet(self) -> None:
        request = self._make_request()
        request.packet_type = "resp"
        datagrams = handle_request(request)
        payload = self._decode(datagrams[0])["payload"]
        self.assertEqual(payload["error_code"], ERROR_UNSUPPORTED_PACKET)
        self.assertEqual(payload["http_status"], 400)

    def test_error_message_is_truncated(self) -> None:
        long_message = "x" * 400
        with patch("akari.remote_proxy.handler.fetch", side_effect=FetchError(long_message)):
            datagrams = handle_request(self._make_request())
        payload = self._decode(datagrams[0])["payload"]
        self.assertTrue(payload["message"].endswith("..."))
        self.assertLessEqual(len(payload["message"]), 200)

    def test_unexpected_exception_becomes_internal_error(self) -> None:
        with patch("akari.remote_proxy.handler.fetch", side_effect=RuntimeError("boom")):
            datagrams = handle_request(self._make_request())
        payload = self._decode(datagrams[0])["payload"]
        self.assertEqual(payload["error_code"], ERROR_UNEXPECTED)
        self.assertEqual(payload["http_status"], 500)
        self.assertEqual(payload["message"], "internal server error")

    def test_handle_nack_resends_requested_sequences(self) -> None:
        body = b"A" * (FIRST_CHUNK_CAPACITY + MTU_PAYLOAD_SIZE + 5)
        response = {"status_code": 200, "headers": {}, "body": body}

        request = self._make_request()
        request.header["version"] = 2

        with patch("akari.remote_proxy.handler._now_timestamp", return_value=0x77):
            datagrams = _encode_success_datagrams(request, response)

        nack_request = self._make_request()
        nack_request.packet_type = "nack"
        nack_request.payload = {"bitmap": bytes([0b00000110])}

        resent = _handle_nack(nack_request)

        self.assertEqual(resent, list(datagrams[1:3]))

    def test_handle_ack_resends_from_first_lost_seq(self) -> None:
        body = b"A" * (FIRST_CHUNK_CAPACITY + MTU_PAYLOAD_SIZE + 5)
        response = {"status_code": 200, "headers": {}, "body": body}

        request = self._make_request()
        request.header["version"] = 2

        with patch("akari.remote_proxy.handler._now_timestamp", return_value=0x77):
            datagrams = _encode_success_datagrams(request, response)

        ack_request = self._make_request()
        ack_request.packet_type = "ack"
        ack_request.payload = {"first_lost_seq": 2}

        resent = _handle_ack(ack_request)

        self.assertEqual(resent, list(datagrams[2:]))


class RemoteProxyServerTest(unittest.TestCase):
    PSK = b"test-psk-0000-test"
    URL = "https://example.com/ok"

    def tearDown(self) -> None:
        from akari.remote_proxy.handler import clear_caches

        clear_caches()

    def _run_server(self) -> tuple[AkariUdpServer, threading.Thread]:
        server = AkariUdpServer("127.0.0.1", 0, self.PSK, handle_request, timeout=2.0)
        thread = threading.Thread(target=server.handle_next, daemon=True)
        thread.start()
        return server, thread

    def test_round_trip_success(self) -> None:
        body = b"hello world"
        response = {"status_code": 200, "headers": {}, "body": body}

        with patch("akari.remote_proxy.handler.fetch", return_value=response), patch(
            "akari.remote_proxy.handler._now_timestamp", return_value=0x44
        ):
            server, thread = self._run_server()
            try:
                client = AkariUdpClient(server.address, self.PSK, timeout=3.0)
                outcome = client.send_request(self.URL, message_id=0x1, timestamp=0x2)
            finally:
                thread.join(timeout=2.0)
                server.close()

        self.assertTrue(outcome.complete)
        self.assertEqual(outcome.body, body)
        self.assertEqual(outcome.status_code, 200)
        self.assertIsNone(outcome.error)

    def test_round_trip_timeout_error(self) -> None:
        with patch("akari.remote_proxy.handler.fetch", side_effect=TimeoutFetchError(5)):
            server, thread = self._run_server()
            try:
                client = AkariUdpClient(server.address, self.PSK, timeout=3.0)
                outcome = client.send_request(self.URL, message_id=0x10, timestamp=0x20)
            finally:
                thread.join(timeout=2.0)
                server.close()

        self.assertFalse(outcome.complete)
        self.assertIsNotNone(outcome.error)
        self.assertEqual(outcome.error["error_code"], ERROR_TIMEOUT)
        self.assertEqual(outcome.error["http_status"], 504)


class UdpClientRetransmissionTest(unittest.TestCase):
    def test_build_missing_bitmap_sets_bits_for_missing_sequences(self) -> None:
        acc = ResponseAccumulator(message_id=1)
        acc.seq_total = 5
        acc.chunks = {0: b"a", 2: b"b", 4: b"c"}

        client = AkariUdpClientClass(("127.0.0.1", 9999), b"psk", timeout=0.1)
        bitmap = client._build_missing_bitmap(acc)

        self.assertEqual(bitmap, b"\x0a")

    def test_build_missing_bitmap_returns_empty_when_complete(self) -> None:
        acc = ResponseAccumulator(message_id=1)
        acc.seq_total = 2
        acc.chunks = {0: b"a", 1: b"b"}

        client = AkariUdpClientClass(("127.0.0.1", 9999), b"psk", timeout=0.1)

        self.assertEqual(client._build_missing_bitmap(acc), b"")

    def test_build_missing_bitmap_returns_empty_without_seq_total(self) -> None:
        acc = ResponseAccumulator(message_id=1)

        client = AkariUdpClientClass(("127.0.0.1", 9999), b"psk", timeout=0.1)

        self.assertEqual(client._build_missing_bitmap(acc), b"")
