import os
import shutil
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py"))

from akari.remote_proxy.config import ConfigError, load_config


class RemoteProxyConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_config(self, body: str) -> Path:
        path = self.temp_dir / "remote.toml"
        path.write_text(textwrap.dedent(body).strip() + "\n", encoding="utf-8")
        return path

    def test_loads_defaults(self) -> None:
        config_path = self._write_config(
            """
            [server]
            psk = "plain"
            """
        )
        config = load_config(config_path)
        self.assertEqual(config.host, "0.0.0.0")
        self.assertEqual(config.port, 14500)
        self.assertEqual(config.buffer_size, 65535)
        self.assertIsNone(config.timeout)
        self.assertEqual(config.log_level, "INFO")
        self.assertEqual(config.psk, b"plain")

    def test_loads_psk_from_file(self) -> None:
        secret_file = self.temp_dir / "secret.txt"
        secret_file.write_text(" from file \n", encoding="utf-8")

        config_path = self._write_config(
            """
            [server]
            psk_file = "secret.txt"
            """
        )
        config = load_config(config_path)
        self.assertEqual(config.psk, b"from file")

    def test_loads_psk_from_env(self) -> None:
        env_key = "AKARI_REMOTE_PSK_TEST"
        os.environ[env_key] = " env-value "
        try:
            config_path = self._write_config(
                f"""
                [server]
                psk_env = "{env_key}"
                """
            )
            config = load_config(config_path)
        finally:
            del os.environ[env_key]

        self.assertEqual(config.psk, b"env-value")

    def test_psk_hex_decoded(self) -> None:
        config_path = self._write_config(
            """
            [server]
            psk = "0a1b"
            psk_hex = true
            """
        )
        config = load_config(config_path)
        self.assertEqual(config.psk, bytes.fromhex("0a1b"))

    def test_conflicting_psk_sources(self) -> None:
        config_path = self._write_config(
            """
            [server]
            psk = "a"
            psk_env = "foo"
            """
        )
        with self.assertRaises(ConfigError):
            load_config(config_path)
