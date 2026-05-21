"""
餃子ニュースサービス

Google News の RSS フィードから「餃子」関連のニュースを取得する。
オンデマンド取得＋1時間キャッシュ。取得失敗時は空リストを返し、
ダッシュボード全体が壊れないように例外を握りつぶす。
"""
import logging
from datetime import datetime, timezone
from time import struct_time
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx

from app.services.cache_service import cache

logger = logging.getLogger(__name__)

# =============================================================================
# 定数
# =============================================================================

# Google News RSS 検索フィード（q=餃子, 日本語/日本）
_GOOGLE_NEWS_BASE = "https://news.google.com/rss/search"
_GOOGLE_NEWS_QUERY = {
    "q": "餃子",
    "hl": "ja",
    "gl": "JP",
    "ceid": "JP:ja",
}

API_TIMEOUT = 10.0  # seconds

# ブラウザ風 User-Agent（一部フィードがデフォルトUAを弾くため）
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


# =============================================================================
# 公開関数
# =============================================================================

# 取得成功した記事の全件キャッシュ（失敗時の空リストはキャッシュしない）
_NEWS_CACHE_KEY = "news:gyoza:entries"
_NEWS_CACHE_TTL = 3600  # 1時間


async def get_gyoza_news(limit: int = 8) -> List[dict]:
    """餃子関連ニュースを取得する。

    オンデマンドで RSS を取得し1時間キャッシュする。
    取得・パースに失敗した場合は空リストを返すが、**失敗結果はキャッシュしない**
    （一度の失敗で長時間ニュースが表示されないのを防ぐため、次回アクセスで再取得を試みる）。

    Args:
        limit: 返却する最大記事数

    Returns:
        記事辞書のリスト（title, link, source, published_at, category）
    """
    # 取得成功済みのキャッシュがあれば再利用
    cached_entries = cache.get(_NEWS_CACHE_KEY)
    if cached_entries:
        return cached_entries[:limit]

    try:
        raw = await _fetch_rss()
        if raw:
            entries = _parse_feed(raw)
            if entries:
                # 取得成功時のみキャッシュする
                cache.set(_NEWS_CACHE_KEY, entries, _NEWS_CACHE_TTL)
                return entries[:limit]
    except Exception as e:  # noqa: BLE001 - ダッシュボードを壊さないため全例外を握りつぶす
        logger.warning(f"Failed to get gyoza news: {e}")

    return []


# =============================================================================
# 内部関数（取得元を差し替えやすいよう分離）
# =============================================================================

def _build_feed_url() -> str:
    """Google News RSS のURLを生成する（q はURLエンコード）。"""
    return f"{_GOOGLE_NEWS_BASE}?{urlencode(_GOOGLE_NEWS_QUERY)}"


async def _fetch_rss() -> Optional[bytes]:
    """RSSフィードの生バイト列を取得する。

    Returns:
        フィードのバイト列。取得失敗時は None。
    """
    url = _build_feed_url()
    try:
        async with httpx.AsyncClient(
            timeout=API_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.content
    except (httpx.HTTPError, httpx.TimeoutException) as e:
        logger.warning(f"Google News RSS fetch error: {e}")
        return None


def _parse_feed(raw: bytes) -> List[dict]:
    """RSSバイト列を feedparser でパースし、記事辞書のリストに変換する。"""
    # feedparser は遅延importする（未インストール環境でもアプリ起動を妨げない）
    import feedparser

    parsed = feedparser.parse(raw)
    items: List[dict] = []

    for entry in parsed.entries:
        title = (getattr(entry, "title", "") or "").strip()
        link = (getattr(entry, "link", "") or "").strip()
        if not title or not link:
            continue

        source, clean_title = _extract_source(entry, title)

        items.append(
            {
                "title": clean_title,
                "link": link,
                "source": source,
                "published_at": _to_iso(getattr(entry, "published_parsed", None)),
                "category": None,
            }
        )

    return items


def _extract_source(entry: Any, title: str) -> tuple[str, str]:
    """記事の媒体名を抽出し、タイトル末尾の「 - 媒体名」を取り除く。

    feedparser の entry.source.title を優先し、なければタイトル末尾から分離する。

    Returns:
        (媒体名, 媒体名を除いたタイトル)
    """
    # feedparser の source 要素を優先
    source_obj = getattr(entry, "source", None)
    if source_obj is not None:
        source_title = ""
        if isinstance(source_obj, dict):
            source_title = (source_obj.get("title") or "").strip()
        else:
            source_title = (getattr(source_obj, "title", "") or "").strip()
        if source_title:
            return source_title, _strip_trailing_source(title, source_title)

    # タイトル末尾「 - 媒体名」から分離（Google News の標準形式）
    if " - " in title:
        head, _, tail = title.rpartition(" - ")
        tail = tail.strip()
        if head.strip() and tail:
            return tail, head.strip()

    return "Google ニュース", title


def _strip_trailing_source(title: str, source: str) -> str:
    """タイトル末尾が「 - 媒体名」で終わる場合に取り除く。"""
    suffix = f" - {source}"
    if title.endswith(suffix):
        return title[: -len(suffix)].strip()
    return title


def _to_iso(published_parsed: Optional[struct_time]) -> Optional[str]:
    """feedparser の published_parsed（time.struct_time, UTC）を ISO文字列に変換する。"""
    if not published_parsed:
        return None
    try:
        dt = datetime(*published_parsed[:6], tzinfo=timezone.utc)
        return dt.isoformat()
    except (TypeError, ValueError) as e:
        logger.debug(f"Failed to parse published date: {e}")
        return None
