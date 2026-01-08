"""AKARI検索モジュール - Brave Searchスクレイピング + JSON返却."""

from __future__ import annotations

import json
import logging
from typing import TypedDict
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from .http_client import FetchError, TimeoutFetchError

LOGGER = logging.getLogger(__name__)

# Brave Search URL
BRAVE_SEARCH_URL = "https://search.brave.com/search"

# HTTPクライアント設定
DEFAULT_TIMEOUT = 10.0
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# 検索結果の最大件数
MAX_RESULTS = 10


class SearchResult(TypedDict):
    """検索結果の型."""

    title: str
    url: str
    snippet: str
    domain: str
    favicon: str


class SearchError(FetchError):
    """検索処理のエラー."""


class SearchParseError(SearchError):
    """検索結果のパースエラー."""


def search_brave(query: str, *, timeout: float = DEFAULT_TIMEOUT) -> list[SearchResult]:
    """Brave Searchをスクレイピングして検索結果を取得.

    Args:
        query: 検索クエリ
        timeout: タイムアウト秒数

    Returns:
        検索結果のリスト

    Raises:
        TimeoutFetchError: タイムアウト時
        SearchError: その他のHTTPエラー時
        SearchParseError: パースエラー時
    """
    results: list[SearchResult] = []

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
        "Accept-Encoding": "gzip, deflate",  # brotli除外（デコードエラー回避）
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(
                BRAVE_SEARCH_URL,
                params={"q": query},
                headers=headers,
            )
            if response.status_code != 200:
                LOGGER.warning("Brave Search returned status %d", response.status_code)
                raise SearchError(f"Brave Search returned HTTP {response.status_code}")
            html_content = response.text
    except httpx.TimeoutException as exc:
        LOGGER.error("Brave Search timeout: %s", exc)
        raise TimeoutFetchError(f"Search timeout: {exc}") from exc
    except httpx.HTTPError as exc:
        LOGGER.error("Brave Search HTTP error: %s", exc)
        raise SearchError(f"Search HTTP error: {exc}") from exc

    # BeautifulSoupでパース
    try:
        soup = BeautifulSoup(html_content, "html.parser")

        # Brave Search の検索結果を取得
        for item in soup.select('div[data-type="web"]'):
            # タイトルとURLを取得
            title_el = item.select_one("a")
            if not title_el:
                continue

            link = title_el.get("href", "")
            if not link or not link.startswith("http"):
                continue

            title = title_el.get_text(strip=True)
            if not title:
                continue

            # スニペットを取得
            snippet = ""
            snippet_el = item.select_one("p.snippet-description, div.snippet-description, p.snippet-content")
            if snippet_el:
                snippet = snippet_el.get_text(strip=True)

            # ドメインを抽出
            parsed_url = urlparse(link)
            domain = parsed_url.netloc

            # faviconはDuckDuckGoのサービスを流用（汎用的）
            favicon = f"https://icons.duckduckgo.com/ip3/{domain}.ico"

            results.append(SearchResult(
                title=title,
                url=link,
                snippet=snippet,
                domain=domain,
                favicon=favicon,
            ))

            if len(results) >= MAX_RESULTS:
                break

    except Exception as exc:
        LOGGER.exception("Failed to parse Brave Search HTML")
        raise SearchParseError(f"Failed to parse search results: {exc}") from exc

    LOGGER.info("search query=%s results=%d", query, len(results))
    return results


# 後方互換性のためのエイリアス
def search_duckduckgo(query: str, *, timeout: float = DEFAULT_TIMEOUT) -> list[SearchResult]:
    """DuckDuckGo互換エイリアス（実際はBrave Searchを使用）."""
    return search_brave(query, timeout=timeout)


def search_to_json(query: str, *, timeout: float = DEFAULT_TIMEOUT) -> bytes:
    """検索してJSON形式で返す.

    Args:
        query: 検索クエリ
        timeout: タイムアウト秒数

    Returns:
        JSON形式のバイト列

    Raises:
        TimeoutFetchError: タイムアウト時
        SearchError: その他のエラー時
    """
    results = search_brave(query, timeout=timeout)
    data = {
        "query": query,
        "results": results,
    }
    return json.dumps(data, ensure_ascii=False).encode("utf-8")
