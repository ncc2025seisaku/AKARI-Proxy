import unittest
from collections import deque
from typing import Tuple
from unittest.mock import patch
import socket

from akari_udp_py import (
    decode_packet_py,
    encode_request_v2_py,
    encode_response_chunk_v2_py,
    encode_response_first_chunk_v2_py,
)

from akari.udp_client import AkariUdpClient


class FakeSocket:
    """Minimal UDP socket stub that replays predefined packets."""

    def __init__(self, queued_packets: deque[bytes], addr: Tuple[str, int]):
        self._queue = queued_packets
        self._addr = addr
        self.sent: list[bytes] = []
        self.timeout = None

    # context manager support
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def settimeout(self, value):
        self.timeout = value

    def sendto(self, data: bytes, addr):
        self.sent.append(data)

    def recvfrom(self, bufsize: int):
        if not self._queue:
            raise socket.timeout()
        return self._queue.popleft(), self._addr

    def close(self):
        pass


class AckSendTest(unittest.TestCase):
    PSK = b"test-psk-0000-test"
    REMOTE_ADDR = ("127.0.0.1", 9999)

    def _build_responses(self, message_id: int, timestamp: int) -> deque[bytes]:
        # seq_total = 3, intentionally send seq0 then seq2 then seq1 to create a gap
        first = encode_response_first_chunk_v2_py(
            200, 3, b"", b"a", message_id, 3, 0, timestamp, self.PSK
        )
        seq2 = encode_response_chunk_v2_py(b"c", message_id, 2, 3, 0, timestamp, self.PSK)
        seq1 = encode_response_chunk_v2_py(b"b", message_id, 1, 3, 0, timestamp, self.PSK)
        return deque([first, seq2, seq1])

    def test_ack_sent_when_gap_detected(self):
        message_id = 0x10
        timestamp = 0x20
        request = encode_request_v2_py("get", "https://example.com", b"", message_id, timestamp, 0, self.PSK)

        responses = self._build_responses(message_id, timestamp)
        socket_addr = self.REMOTE_ADDR

        last_socket_holder = {}

        def socket_factory(*args, **kwargs):
            sock = FakeSocket(responses, socket_addr)
            last_socket_holder["sock"] = sock
            return sock

        with patch("akari.udp_client.socket.socket", socket_factory):
            client = AkariUdpClient(socket_addr, self.PSK, max_ack_rounds=2, max_nack_rounds=0)
            outcome = client.send_request("https://example.com", message_id, timestamp, datagram=request)

        # ensure complete assembly
        self.assertTrue(outcome.complete)
        self.assertEqual(outcome.body, b"abc")

        # first send is request; subsequent sends should include at least one ACK
        sent_packets = last_socket_holder["sock"].sent
        # decode packets and ensure at least one ACK with first_lost_seq=1
        ack_seqs = []
        for data in sent_packets:
            parsed = decode_packet_py(data, self.PSK)
            if parsed.get("type") == "ack":
                ack_seqs.append(parsed["payload"].get("first_lost_seq"))
        self.assertIn(1, ack_seqs, "ACK for missing seq=1 should be sent")


def load_tests(loader, tests, pattern):
    # ensure unittest discovery picks this file when run via pytest
    return unittest.TestSuite([loader.loadTestsFromTestCase(AckSendTest)])
