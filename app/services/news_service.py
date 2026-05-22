"""
餃子ニュースサービス

Google News の RSS フィードから「餃子」関連のニュースを取得する。
オンデマンド取得＋1時間キャッシュ。取得失敗時は空リストを返し、
ダッシュボード全体が壊れないように例外を握りつぶす。
"""
import asyncio
import logging
from datetime import datetime, timezone
from time import struct_time
from typing import Any, Dict, List, Optional, Tuple
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

# RSS取得のリトライ（一時的な失敗・レート制限を吸収する）
_FETCH_MAX_ATTEMPTS = 3
_FETCH_RETRY_DELAY = 1.0  # seconds

# ブラウザ風 User-Agent（一部フィードがデフォルトUAを弾くため）
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


# =============================================================================
# 公開関数
# =============================================================================

# 取得成功した記事のインメモリキャッシュ（同一インスタンス内・高速なL1）
_NEWS_CACHE_KEY = "news:gyoza:entries"
_NEWS_CACHE_TTL = 3600  # 1時間（インメモリ）

# Supabase 永続キャッシュ（インスタンス再生成・デプロイ・スケールをまたいで保持）
_DB_TABLE = "news_cache"
_DB_CACHE_KEY = "gyoza"
_DB_CACHE_TTL = 3600  # この秒数以内なら fresh とみなす（1時間）
# ライブ取得失敗時に古い永続キャッシュを返した際の、インメモリ保持秒数（短め）
_STALE_MEMORY_TTL = 600  # 10分


async def get_gyoza_news(limit: int = 8) -> List[dict]:
    """餃子関連ニュースを取得する（多段キャッシュ構成）。

    1. インメモリキャッシュ（同一インスタンス内・高速）
    2. Supabase 永続キャッシュ（インスタンス再生成・デプロイをまたいで保持）
    3. Google News RSS のライブ取得

    ライブ取得に失敗しても、永続キャッシュに過去の取得結果があればそれを返すため、
    ニュースが空表示になりにくい。

    Args:
        limit: 返却する最大記事数

    Returns:
        記事辞書のリスト（title, link, source, published_at, category）
    """
    # 1. インメモリキャッシュ（L1）
    cached_entries = cache.get(_NEWS_CACHE_KEY)
    if cached_entries:
        return cached_entries[:limit]

    # 2. 永続キャッシュ（L2 / Supabase）。fresh ならそのまま採用
    db_entries, db_fresh = _read_db_cache()
    if db_entries and db_fresh:
        cache.set(_NEWS_CACHE_KEY, db_entries, _NEWS_CACHE_TTL)
        return db_entries[:limit]

    # 3. ライブ取得（永続キャッシュが古い、または存在しない場合）
    try:
        raw = await _fetch_rss()
        if raw:
            entries = _parse_feed(raw)
            if entries:
                cache.set(_NEWS_CACHE_KEY, entries, _NEWS_CACHE_TTL)
                _write_db_cache(entries)  # 永続化
                return entries[:limit]
    except Exception as e:  # noqa: BLE001 - ダッシュボードを壊さないため全例外を握りつぶす
        logger.warning(f"Failed to get gyoza news: {e}")

    # 4. ライブ取得失敗 → 永続キャッシュの古いデータでも返す（空表示にしない）
    if db_entries:
        cache.set(_NEWS_CACHE_KEY, db_entries, _STALE_MEMORY_TTL)
        return db_entries[:limit]

    return []


# =============================================================================
# 永続キャッシュ（Supabase news_cache テーブル）
# =============================================================================


def _is_fresh(fetched_at: Any, ttl_seconds: int) -> bool:
    """fetched_at（ISO日時文字列）が ttl_seconds 以内かどうかを返す。"""
    if not fetched_at:
        return False
    try:
        text = str(fetched_at).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - dt).total_seconds()
        return 0 <= age < ttl_seconds
    except (TypeError, ValueError):
        return False


def _read_db_cache() -> Tuple[List[dict], bool]:
    """Supabase 永続キャッシュからニュースを読む。

    Returns:
        (記事リスト, fresh かどうか)。テーブル未作成・接続失敗時は ([], False)。
    """
    try:
        from app.api.deps import get_supabase_admin

        supabase = get_supabase_admin()
        res = (
            supabase.table(_DB_TABLE)
            .select("payload, fetched_at")
            .eq("cache_key", _DB_CACHE_KEY)
            .limit(1)
            .execute()
        )
        if res.data:
            row = res.data[0]
            payload = row.get("payload") or []
            if isinstance(payload, list) and payload:
                return payload, _is_fresh(row.get("fetched_at"), _DB_CACHE_TTL)
    except Exception as e:  # noqa: BLE001 - 未作成・失敗時はライブ取得にフォールバック
        logger.warning(f"news_cache 読み込み失敗（ライブ取得にフォールバック）: {e}")
    return [], False


def _write_db_cache(entries: List[dict]) -> None:
    """取得成功したニュースを Supabase 永続キャッシュに保存する。"""
    try:
        from app.api.deps import get_supabase_admin

        supabase = get_supabase_admin()
        supabase.table(_DB_TABLE).upsert(
            {
                "cache_key": _DB_CACHE_KEY,
                "payload": entries,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="cache_key",
        ).execute()
    except Exception as e:  # noqa: BLE001 - 保存失敗してもニュース表示は継続する
        logger.warning(f"news_cache 保存失敗: {e}")


# =============================================================================
# 内部関数（取得元を差し替えやすいよう分離）
# =============================================================================

def _build_feed_url() -> str:
    """Google News RSS のURLを生成する（q はURLエンコード）。"""
    return f"{_GOOGLE_NEWS_BASE}?{urlencode(_GOOGLE_NEWS_QUERY)}"


async def _fetch_rss() -> Optional[bytes]:
    """RSSフィードの生バイト列を取得する（一時的失敗に備えてリトライする）。

    Returns:
        フィードのバイト列。全リトライ失敗時は None。
    """
    url = _build_feed_url()
    last_error: Optional[Exception] = None

    for attempt in range(1, _FETCH_MAX_ATTEMPTS + 1):
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
            last_error = e
            if attempt < _FETCH_MAX_ATTEMPTS:
                await asyncio.sleep(_FETCH_RETRY_DELAY)

    logger.warning(
        f"Google News RSS fetch error ({_FETCH_MAX_ATTEMPTS}回試行後): {last_error}"
    )
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
