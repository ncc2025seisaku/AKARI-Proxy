"""Content filtering logic shared by the local proxy components."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from typing import Mapping
from urllib.parse import urlsplit

from .config import ContentFilterSettings


class ContentCategory(str, Enum):
    """Simple classification used for filtering decisions."""

    HTML = "html"
    JAVASCRIPT = "javascript"
    STYLESHEET = "css"
    IMAGE = "image"
    OTHER = "other"


@dataclass(frozen=True)
class FilterDecision:
    """Result of running the filter against a single URL."""

    allowed: bool
    category: ContentCategory
    status_code: int | None = None
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""
    reason: str | None = None

    @property
    def blocked(self) -> bool:
        return not self.allowed


_JS_EXTENSIONS = {".js", ".mjs", ".cjs"}
_CSS_EXTENSIONS = {".css"}
_IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".webp",
    ".svg",
    ".ico",
    ".avif",
    ".apng",
}
_HTML_EXTENSIONS = {".html", ".htm", ".shtml", ".xhtml", ".php", ".asp", ".aspx", ".jsp"}


class ContentFilter:
    """Decides whether a request should be proxied or short-circuited."""

    def __init__(self, settings: ContentFilterSettings):
        self._settings = settings

    def evaluate(self, url: str) -> FilterDecision:
        """Check if the target URL should be proxied or blocked locally."""

        category = self._classify(url)
        if self._is_allowed(category):
            return FilterDecision(True, category)

        headers = {
            "Content-Length": "0",
            "Cache-Control": "no-cache",
            "X-AKARI-Filtered": category.value,
        }
        reason = f"{category.value} disabled by content filter"
        return FilterDecision(
            allowed=False,
            category=category,
            status_code=204,
            headers=headers,
            body=b"",
            reason=reason,
        )

    def _is_allowed(self, category: ContentCategory) -> bool:
        if category == ContentCategory.JAVASCRIPT:
            return self._settings.enable_js
        if category == ContentCategory.STYLESHEET:
            return self._settings.enable_css
        if category == ContentCategory.IMAGE:
            return self._settings.enable_img
        return True

    def _classify(self, url: str) -> ContentCategory:
        parsed = urlsplit(url)
        path = parsed.path or ""
        suffix = PurePosixPath(path).suffix.lower()

        if suffix in _JS_EXTENSIONS:
            return ContentCategory.JAVASCRIPT
        if suffix in _CSS_EXTENSIONS:
            return ContentCategory.STYLESHEET
        if suffix in _IMAGE_EXTENSIONS:
            return ContentCategory.IMAGE
        if not suffix or suffix in _HTML_EXTENSIONS:
            return ContentCategory.HTML
        return ContentCategory.OTHER
