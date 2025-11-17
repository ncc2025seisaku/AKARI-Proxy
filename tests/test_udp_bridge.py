import sys
import threading
import unittest
from pathlib import Path
from typing import Callable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py"))

from akari import (
    AkariUdpClient,
    AkariUdpServer,
    IncomingRequest,
    encode_error_response,
    encode_success_response,
)


class AkariUdpBridgeTest(unittest.TestCase):
    PSK = b"test-psk-0000-test"
    URL = "https://example.test/resource"

    def _run_server(self, handler: Callable[[IncomingRequest], Sequence[bytes]]) -> tuple[AkariUdpServer, threading.Thread]:
        server = AkariUdpServer("127.0.0.1", 0, self.PSK, handler, timeout=2.0)
        thread = threading.Thread(target=server.handle_next, daemon=True)
        thread.start()
        return server, thread

    def test_request_response_round_trip(self) -> None:
        body = b"ok"

        def handler(request: IncomingRequest) -> Sequence[bytes]:
            return encode_success_response(request, body)

        server, thread = self._run_server(handler)
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

    def test_error_packet_is_parsed(self) -> None:
        def handler(request: IncomingRequest) -> Sequence[bytes]:
            return encode_error_response(request, error_code=3, http_status=502, message="bad")

        server, thread = self._run_server(handler)
        try:
            client = AkariUdpClient(server.address, self.PSK, timeout=3.0)
            outcome = client.send_request(self.URL, message_id=0x5, timestamp=0x6)
        finally:
            thread.join(timeout=2.0)
            server.close()

        self.assertFalse(outcome.complete)
        self.assertIsNotNone(outcome.error)
        self.assertEqual(outcome.error["error_code"], 3)
        self.assertEqual(outcome.error["message"], "bad")
