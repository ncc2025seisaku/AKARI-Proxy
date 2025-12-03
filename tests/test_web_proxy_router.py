import unittest
from unittest.mock import MagicMock, patch

from akari.udp_client import ResponseOutcome
from akari.web_proxy.config import WebProxyConfig, UIConfig, RemoteProxyConfig
from akari.web_proxy.router import WebRouter
from local_proxy.config import ContentFilterSettings


class WebRouterEncryptionTest(unittest.TestCase):
    def _config(self) -> WebProxyConfig:
        return WebProxyConfig(
            listen_host="127.0.0.1",
            listen_port=8080,
            mode="web",
            ui=UIConfig(portal_title="t", welcome_message="m"),
            remote=RemoteProxyConfig(host="127.0.0.1", port=9000, psk=b"test-psk-0000-test", timeout=1.0),
            content_filter=ContentFilterSettings(True, True, True, True),
        )

    def test_execute_proxy_uses_encrypted_client_when_requested(self):
        cfg = self._config()
        with patch("akari.web_proxy.router.AkariUdpClient") as mock_client_cls:
            plain_client = MagicMock()
            enc_client = MagicMock()
            # send_request returns dummy outcome
            dummy_outcome = ResponseOutcome(
                message_id=1,
                packets=[],
                body=b"ok",
                status_code=200,
                headers={},
                error=None,
                complete=True,
                timed_out=False,
                bytes_sent=1,
                bytes_received=1,
            )
            plain_client.send_request.return_value = dummy_outcome
            enc_client.send_request.return_value = dummy_outcome
            mock_client_cls.side_effect = [plain_client, enc_client]

            router = WebRouter(cfg)
            router._proxy_base = "http://localhost:8080/"  # avoid actual host diff

            # direct call to _execute_proxy with use_encryption=True
            result = router._execute_proxy("https://example.com", use_encryption=True)

            self.assertEqual(result.status_code, 200)
            enc_client.send_request.assert_called_once()
            plain_client.send_request.assert_not_called()


def load_tests(loader, tests, pattern):
    return unittest.TestSuite([loader.loadTestsFromTestCase(WebRouterEncryptionTest)])
