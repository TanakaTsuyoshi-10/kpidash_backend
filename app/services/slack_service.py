"""
Slack連携サービス

Slack Web API（Botトークンによる Bearer 認証）を httpx で呼び出し、
Bot が参加する全チャンネルの「本日」「昨日」の投稿を取得する。

settings.slack_enabled が False（SLACK_BOT_TOKEN 未設定）の場合は
サンプルデータにフォールバックする。実連携が失敗した場合も同様。
"""
import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import httpx

from app.core.config import settings
from app.services.cache_service import cached

logger = logging.getLogger(__name__)

# =============================================================================
# 定数
# =============================================================================

SLACK_API_BASE = "https://slack.com/api"
API_TIMEOUT = 10.0  # seconds

# 日本時間（投稿日付の判定に使用）
JST = ZoneInfo("Asia/Tokyo")

# API呼び出しを抑制するための上限
MAX_CHANNELS = 20            # 走査するチャンネル数の上限
HISTORY_LIMIT = 20           # 1チャンネルあたりの取得件数
MAX_POSTS_PER_CHANNEL = 8    # 1チャンネルから採用する投稿数の上限

# 投稿サブタイプのうち通常メッセージとして扱わないもの
SKIP_SUBTYPES = {
    "channel_join",
    "channel_leave",
    "channel_topic",
    "channel_purpose",
    "channel_name",
    "bot_message",
}


# =============================================================================
# 公開関数
# =============================================================================

@cached(prefix="slack", ttl=600)
async def get_slack_posts() -> Dict[str, Any]:
    """Slack投稿（本日・昨日）を取得する。

    SlackPostsResponse 相当の dict を返す。
    連携未設定・失敗時はサンプルデータ（is_sample=True）を返す。
    """
    if not settings.slack_enabled:
        return _sample_posts()

    try:
        return await _fetch_from_slack()
    except Exception as e:
        logger.warning(f"Slack API取得に失敗したためサンプルにフォールバック: {e}")
        return _sample_posts()


# =============================================================================
# Slack API 連携
# =============================================================================

async def _fetch_from_slack() -> Dict[str, Any]:
    """Slack Web API から本日・昨日の投稿を取得する。"""
    today = datetime.now(JST).date()
    yesterday = today - timedelta(days=1)

    # 昨日0:00（JST）以降の投稿のみ取得対象とする
    oldest_ts = datetime(
        yesterday.year, yesterday.month, yesterday.day, tzinfo=JST
    ).timestamp()

    headers = {"Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}"}

    async with httpx.AsyncClient(timeout=API_TIMEOUT, headers=headers) as client:
        channels = await _list_channels(client)
        if not channels:
            logger.info("Bot参加チャンネルが見つからないためサンプルにフォールバック")
            return _sample_posts()

        # 投稿者名解決用のユーザーキャッシュ
        user_cache: Dict[str, str] = {}

        new_posts: List[Dict[str, Any]] = []
        yesterday_posts: List[Dict[str, Any]] = []

        for channel in channels[:MAX_CHANNELS]:
            channel_id = channel.get("id")
            channel_name = channel.get("name", "")
            if not channel_id:
                continue

            messages = await _channel_history(client, channel_id, oldest_ts)

            adopted = 0
            for msg in messages:
                if adopted >= MAX_POSTS_PER_CHANNEL:
                    break

                post = await _build_post(
                    client, channel_id, channel_name, msg,
                    today, yesterday, user_cache
                )
                if post is None:
                    continue

                post_day = _ts_to_date(msg.get("ts", ""))
                if post_day == today:
                    new_posts.append(post)
                elif post_day == yesterday:
                    yesterday_posts.append(post)
                adopted += 1

    # 新しい順に並べ替え
    new_posts.sort(key=lambda p: float(p["ts"]), reverse=True)
    yesterday_posts.sort(key=lambda p: float(p["ts"]), reverse=True)

    return {
        "new_posts": new_posts,
        "yesterday_posts": yesterday_posts,
        "is_sample": False,
    }


async def _list_channels(client: httpx.AsyncClient) -> List[Dict[str, Any]]:
    """Bot が参加しているチャンネル一覧を取得する。"""
    resp = await client.get(
        f"{SLACK_API_BASE}/users.conversations",
        params={
            "types": "public_channel,private_channel",
            "exclude_archived": "true",
            "limit": MAX_CHANNELS,
        },
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"users.conversations error: {data.get('error')}")
    return data.get("channels", [])


async def _channel_history(
    client: httpx.AsyncClient,
    channel_id: str,
    oldest_ts: float,
) -> List[Dict[str, Any]]:
    """指定チャンネルの最近の投稿履歴を取得する。"""
    resp = await client.get(
        f"{SLACK_API_BASE}/conversations.history",
        params={
            "channel": channel_id,
            "oldest": str(oldest_ts),
            "limit": HISTORY_LIMIT,
        },
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        # 1チャンネル失敗で全体を止めない
        logger.warning(
            f"conversations.history error ({channel_id}): {data.get('error')}"
        )
        return []
    return data.get("messages", [])


async def _build_post(
    client: httpx.AsyncClient,
    channel_id: str,
    channel_name: str,
    msg: Dict[str, Any],
    today: date,
    yesterday: date,
    user_cache: Dict[str, str],
) -> Optional[Dict[str, Any]]:
    """Slackメッセージを SlackPost 相当の dict に変換する。

    通常メッセージでない、または本文が空の場合は None を返す。
    """
    if msg.get("type") != "message":
        return None
    if msg.get("subtype") in SKIP_SUBTYPES:
        return None

    text = (msg.get("text") or "").strip()
    if not text:
        return None

    ts = msg.get("ts", "")
    post_day = _ts_to_date(ts)
    if post_day not in (today, yesterday):
        return None

    author = await _resolve_user_name(client, msg.get("user", ""), user_cache)
    permalink = await _get_permalink(client, channel_id, ts)

    return {
        "channel": f"#{channel_name}" if channel_name else "#unknown",
        "author": author,
        "text": _clean_text(text),
        "ts": ts,
        "time_label": _format_time_label(ts, today),
        "permalink": permalink,
    }


async def _resolve_user_name(
    client: httpx.AsyncClient,
    user_id: str,
    user_cache: Dict[str, str],
) -> str:
    """ユーザーIDから表示名を解決する（キャッシュ付き）。"""
    if not user_id:
        return "不明"
    if user_id in user_cache:
        return user_cache[user_id]

    name = user_id
    try:
        resp = await client.get(
            f"{SLACK_API_BASE}/users.info",
            params={"user": user_id},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("ok"):
            user = data.get("user", {})
            profile = user.get("profile", {})
            name = (
                profile.get("display_name")
                or profile.get("real_name")
                or user.get("real_name")
                or user.get("name")
                or user_id
            )
    except Exception as e:
        logger.warning(f"users.info error ({user_id}): {e}")

    user_cache[user_id] = name
    return name


async def _get_permalink(
    client: httpx.AsyncClient,
    channel_id: str,
    ts: str,
) -> Optional[str]:
    """メッセージのパーマリンクを取得する。失敗時は None。"""
    if not channel_id or not ts:
        return None
    try:
        resp = await client.get(
            f"{SLACK_API_BASE}/chat.getPermalink",
            params={"channel": channel_id, "message_ts": ts},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("ok"):
            return data.get("permalink")
    except Exception as e:
        logger.warning(f"chat.getPermalink error: {e}")
    return None


# =============================================================================
# ユーティリティ
# =============================================================================

def _ts_to_date(ts: str) -> Optional[date]:
    """Slackタイムスタンプ（unix秒.連番）を JST の日付に変換する。"""
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=JST).date()
    except (ValueError, OverflowError, OSError):
        return None


def _format_time_label(ts: str, today: date) -> str:
    """表示用の時刻ラベルを生成する（本日: HH:MM / 昨日: 昨 HH:MM）。"""
    if not ts:
        return ""
    try:
        dt = datetime.fromtimestamp(float(ts), tz=JST)
    except (ValueError, OverflowError, OSError):
        return ""
    time_str = dt.strftime("%H:%M")
    if dt.date() == today:
        return time_str
    return f"昨 {time_str}"


def _clean_text(text: str) -> str:
    """本文の前後の空白のみ除去する（全文を表示するため切り詰めない。改行は保持）。"""
    return text.strip()


# =============================================================================
# サンプルデータ
# =============================================================================

def _sample_posts() -> Dict[str, Any]:
    """Slack連携未設定時のサンプルデータ（design-demo 準拠）。"""
    today = datetime.now(JST).date()
    yesterday = today - timedelta(days=1)

    def make(
        day: date, hour: int, minute: int, channel: str, author: str, text: str
    ) -> Dict[str, Any]:
        dt = datetime(day.year, day.month, day.day, hour, minute, tzinfo=JST)
        ts = f"{dt.timestamp():.6f}"
        return {
            "channel": channel,
            "author": author,
            "text": text,
            "ts": ts,
            "time_label": _format_time_label(ts, today),
            "permalink": None,
        }

    new_posts = [
        make(today, 10, 32, "#全社連絡", "山田", "来週の全体会議は14時開始に変更します"),
        make(today, 9, 15, "#クレーム報告", "佐藤", "福岡店の梱包ミス、対応完了しました"),
        make(today, 8, 48, "#通販チーム", "鈴木", "ふるさと納税の在庫補充を依頼します"),
    ]
    yesterday_posts = [
        make(yesterday, 18, 20, "#製造部", "田中", "明日の生産ラインは通常稼働です"),
        make(yesterday, 15, 5, "#全社連絡", "高橋", "経費精算の締め日は今月末です"),
        make(yesterday, 11, 30, "#店舗運営", "伊藤", "都城店のPOS不具合は復旧済みです"),
    ]

    return {
        "new_posts": new_posts,
        "yesterday_posts": yesterday_posts,
        "is_sample": True,
    }
