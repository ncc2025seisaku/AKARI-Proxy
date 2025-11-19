import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py"))

from local_proxy.config import ConfigError, ContentFilterSettings, LocalProxyConfig, load_config


class LocalProxyConfigTest(unittest.TestCase):
    def test_defaults_are_used_when_section_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = Path(tmpdir) / "local.toml"
            cfg_path.write_text("", encoding="utf-8")
            config = load_config(cfg_path)
        self.assertIsInstance(config, LocalProxyConfig)
        self.assertEqual(config.content_filter, ContentFilterSettings())

    def test_loading_explicit_values(self) -> None:
        content = """
        [content_filter]
        enable_js = false
        enable_css = true
        enable_img = false
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = Path(tmpdir) / "local.toml"
            cfg_path.write_text(content, encoding="utf-8")
            config = load_config(cfg_path)
        self.assertFalse(config.content_filter.enable_js)
        self.assertTrue(config.content_filter.enable_css)
        self.assertFalse(config.content_filter.enable_img)

    def test_invalid_value_raises_error(self) -> None:
        content = """
        [content_filter]
        enable_js = "yes"
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = Path(tmpdir) / "local.toml"
            cfg_path.write_text(content, encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(cfg_path)

    def test_missing_file_raises_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = Path(tmpdir) / "missing.toml"
            with self.assertRaises(ConfigError):
                load_config(cfg_path)


if __name__ == "__main__":
    unittest.main()
