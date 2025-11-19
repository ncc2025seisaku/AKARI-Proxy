import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py"))

from local_proxy.config import ContentFilterSettings
from local_proxy.content_filter import ContentCategory, ContentFilter


class ContentFilterTest(unittest.TestCase):
    def _make_filter(
        self,
        *,
        enable_js: bool = True,
        enable_css: bool = True,
        enable_img: bool = True,
    ) -> ContentFilter:
        settings = ContentFilterSettings(enable_js=enable_js, enable_css=enable_css, enable_img=enable_img)
        return ContentFilter(settings)

    def test_allows_html_when_everything_enabled(self) -> None:
        flt = self._make_filter()
        decision = flt.evaluate("https://example.com/index.html")
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.category, ContentCategory.HTML)
        self.assertIsNone(decision.status_code)

    def test_blocks_javascript_when_disabled(self) -> None:
        flt = self._make_filter(enable_js=False)
        decision = flt.evaluate("https://cdn.example.com/app.min.js?version=3")
        self.assertTrue(decision.blocked)
        self.assertEqual(decision.category, ContentCategory.JAVASCRIPT)
        self.assertEqual(decision.status_code, 204)
        self.assertEqual(decision.headers.get("Content-Length"), "0")
        self.assertIn("javascript", decision.reason or "")

    def test_allows_stylesheet_when_enabled(self) -> None:
        flt = self._make_filter()
        decision = flt.evaluate("https://cdn.example.com/assets/normalize.CSS")
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.category, ContentCategory.STYLESHEET)

    def test_blocks_stylesheet_when_disabled(self) -> None:
        flt = self._make_filter(enable_css=False)
        decision = flt.evaluate("https://cdn.example.com/assets/site.css")
        self.assertTrue(decision.blocked)
        self.assertEqual(decision.category, ContentCategory.STYLESHEET)

    def test_blocks_images_when_disabled(self) -> None:
        flt = self._make_filter(enable_img=False)
        decision = flt.evaluate("https://img.example.com/photo.WEBP?size=small")
        self.assertTrue(decision.blocked)
        self.assertEqual(decision.category, ContentCategory.IMAGE)

    def test_treats_extensionless_path_as_html(self) -> None:
        flt = self._make_filter(enable_js=False, enable_css=False, enable_img=False)
        decision = flt.evaluate("https://example.com/dashboard")
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.category, ContentCategory.HTML)


if __name__ == "__main__":
    unittest.main()
