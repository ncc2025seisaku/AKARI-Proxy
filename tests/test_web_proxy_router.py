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

    def test_coerce_bool_accepts_query_list_values(self):
        cfg = self._config()
        router = WebRouter(cfg)
        self.assertTrue(router._coerce_bool({"enc": ["1"]}, "enc"))
        self.assertFalse(router._coerce_bool({"enc": ["0"]}, "enc"))

    def test_location_header_is_rewritten_to_proxy(self):
        cfg = self._config()
        router = WebRouter(cfg)
        router._proxy_base = "http://localhost:8080/"

        outcome = ResponseOutcome(
            message_id=1,
            packets=[],
            body=b"",
            status_code=302,
            headers={"Location": "https://example.com/foo?x=1"},
            error=None,
            complete=True,
            timed_out=False,
            bytes_sent=1,
            bytes_received=1,
        )
        result = router._raw_response("https://example.com/search?q=a", outcome)
        self.assertEqual(result.headers["Location"], "http://localhost:8080/https%3A%2F%2Fexample.com%2Ffoo%3Fx%3D1")

    def test_html_meta_refresh_and_form_action_are_rewritten(self):
        cfg = self._config()
        router = WebRouter(cfg)
        router._proxy_base = "http://localhost:8080/"
        html = (
            '<html><head>'
            '<meta http-equiv="refresh" content="0;url=/consent?continue=https://google.com/search?q=a">'
            '</head><body>'
            '<form action="/search" method="get"><input name="q"></form>'
            '</body></html>'
        ).encode()
        rewritten = router._rewrite_html_to_proxy(html, "https://google.com/search?q=a").decode()
        self.assertIn('action="http://localhost:8080/https%3A%2F%2Fgoogle.com%2Fsearch"', rewritten)
        self.assertIn('url=http://localhost:8080/https%3A%2F%2Fgoogle.com%2Fconsent%3Fcontinue%3Dhttps%3A%2F%2Fgoogle.com%2Fsearch%3Fq%3Da', rewritten)

    def test_outer_query_params_are_merged_into_target_url(self):
        cfg = self._config()
        router = WebRouter(cfg)
        merged = router._merge_outer_params_into_url(
            "https://google.com/search?q=a", {"entry": ["1"], "sei": ["abc"], "foo": ["bar"], "_akari_ref": ["1"]}
        )
        self.assertEqual(merged, "https://google.com/search?q=a&sei=abc&foo=bar")


def load_tests(loader, tests, pattern):
    return unittest.TestSuite([loader.loadTestsFromTestCase(WebRouterEncryptionTest)])
