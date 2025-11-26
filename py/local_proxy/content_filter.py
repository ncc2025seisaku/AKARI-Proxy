"""Content filtering logic shared by the local proxy components."""

from __future__ import annotations

import threading
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
        self._lock = threading.Lock()

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
        settings = self._settings
        if category == ContentCategory.JAVASCRIPT:
            return settings.enable_js
        if category == ContentCategory.STYLESHEET:
            return settings.enable_css
        if category == ContentCategory.IMAGE:
            return settings.enable_img
        if category == ContentCategory.OTHER:
            return settings.enable_other
        return True

    def snapshot(self) -> ContentFilterSettings:
        """Return the current settings immutable snapshot."""
        return self._settings

    def update(
        self,
        *,
        enable_js: bool | None = None,
        enable_css: bool | None = None,
        enable_img: bool | None = None,
        enable_other: bool | None = None,
    ) -> ContentFilterSettings:
        """Update filter toggles atomically and return the new settings."""
        with self._lock:
            current = self._settings
            new_settings = ContentFilterSettings(
                enable_js=current.enable_js if enable_js is None else enable_js,
                enable_css=current.enable_css if enable_css is None else enable_css,
                enable_img=current.enable_img if enable_img is None else enable_img,
                enable_other=current.enable_other if enable_other is None else enable_other,
            )
            self._settings = new_settings
            return new_settings

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
        if suffix in _HTML_EXTENSIONS:
            return ContentCategory.HTML
        # 拡張子なしはページ本体として扱う（bare domain/ディレクトリへのアクセスを阻害しない）
        if not suffix:
            return ContentCategory.HTML
        # それ以外は Other とみなす
        return ContentCategory.OTHER
