"""
Slack 投稿サービス（承認ワークフロー用）

承認完了したコンテンツを Slack の指定チャンネルへ投稿する。
- テキストは chat.postMessage（mrkdwn）
- 画像は files.getUploadURLExternal → PUT → files.completeUploadExternal の v2 フロー
  （backend が Supabase Storage から fetch してストリーム転送する。
   Slack に Storage URL を直接教えない）

必要な Bot スコープ: chat:write, files:write
SLACK_BOT_TOKEN 未設定時は投稿せずログのみ（サンプルモード）。
"""
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

SLACK_API_BASE = "https://slack.com/api"
API_TIMEOUT = 20.0


# =============================================================================
# HTML → Slack mrkdwn 簡易変換
# =============================================================================

def html_to_mrkdwn(html: str) -> str:
    """
    Tiptap が出力する HTML を Slack mrkdwn に簡易変換する。
    色は mrkdwn に存在しないため落とす（UI 側で注意文言を表示）。
    """
    if not html:
        return ""

    text = html

    # テーブル → 「セル | セル | セル」形式のテキスト行に変換
    text = re.sub(r"</t[dh]>\s*<t[dh][^>]*>", " | ", text)
    text = re.sub(r"<t[dh][^>]*>", "", text)
    text = re.sub(r"</t[dh]>", "", text)
    text = re.sub(r"</tr>", "\n", text)
    text = re.sub(r"<tr[^>]*>", "", text)
    text = re.sub(r"</?(table|thead|tbody|tfoot|colgroup|col)[^>]*>", "", text)

    # 改行系ブロック
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"</p>\s*<p[^>]*>", "\n", text)
    text = re.sub(r"<p[^>]*>", "", text)
    text = re.sub(r"</p>", "\n", text)

    # 箇条書き
    text = re.sub(r"<li[^>]*><p[^>]*>", "• ", text)
    text = re.sub(r"<li[^>]*>", "• ", text)
    text = re.sub(r"</li>", "\n", text)
    text = re.sub(r"</?[uo]l[^>]*>", "", text)

    # 装飾
    text = re.sub(r"<(strong|b)[^>]*>", "*", text)
    text = re.sub(r"</(strong|b)>", "*", text)
    text = re.sub(r"<(em|i)[^>]*>", "_", text)
    text = re.sub(r"</(em|i)>", "_", text)
    text = re.sub(r"<u[^>]*>", "_", text)
    text = re.sub(r"</u>", "_", text)
    text = re.sub(r"<(s|strike|del)[^>]*>", "~", text)
    text = re.sub(r"</(s|strike|del)>", "~", text)

    # 画像タグは除去（画像は files upload で別送）
    text = re.sub(r"<img[^>]*>", "", text)

    # 残りのタグを除去
    text = re.sub(r"<[^>]+>", "", text)

    # HTML エンティティの最低限のデコード
    for entity, char in [("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                         ("&quot;", '"'), ("&#39;", "'"), ("&nbsp;", " ")]:
        text = text.replace(entity, char)

    # 連続改行の圧縮
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# =============================================================================
# Slack API 呼び出し
# =============================================================================

def _headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}",
        "Content-Type": "application/json; charset=utf-8",
    }


async def check_bot_in_channel(channel_id: str) -> Tuple[bool, str]:
    """
    Bot がチャンネルに参加しているかを確認する。

    Returns:
        (is_member, channel_name)
    """
    if not settings.slack_enabled:
        return True, "(sample)"

    try:
        async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
            res = await client.get(
                f"{SLACK_API_BASE}/conversations.info",
                headers=_headers(),
                params={"channel": channel_id},
            )
            data = res.json()
            if not data.get("ok"):
                logger.warning("conversations.info 失敗: %s", data.get("error"))
                return False, ""
            channel = data.get("channel", {})
            return bool(channel.get("is_member")), channel.get("name", "")
    except Exception as exc:
        logger.warning("conversations.info 例外: %s", exc)
        return False, ""


async def post_approved_content(
    channel_id: str,
    title: str,
    caption_html: str,
    requester_name: str,
    type_label: str,
    image_bytes_list: Optional[List[Tuple[bytes, str]]] = None,
) -> Dict[str, Any]:
    """
    承認完了コンテンツを Slack へ投稿する。

    Args:
        channel_id: 投稿先チャンネルID
        title: 申請タイトル
        caption_html: キャプション（Tiptap HTML）
        requester_name: 申請者表示名
        type_label: 申請種別表示名
        image_bytes_list: [(bytes, filename)] 添付画像

    Returns:
        {"ok": bool, "ts": str|None, "error": str|None}
    """
    if not settings.slack_enabled:
        logger.info("[slack sample-mode] channel=%s title=%s", channel_id, title)
        return {"ok": True, "ts": None, "error": None}

    caption = html_to_mrkdwn(caption_html)
    header_text = f":white_check_mark: *{type_label}* が承認されました\n*{title}*（申請者: {requester_name}）"

    try:
        async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
            # 1) テキスト本文を投稿
            res = await client.post(
                f"{SLACK_API_BASE}/chat.postMessage",
                headers=_headers(),
                json={
                    "channel": channel_id,
                    "text": f"{header_text}\n\n{caption}",
                    "unfurl_links": False,
                },
            )
            data = res.json()
            if not data.get("ok"):
                return {"ok": False, "ts": None, "error": data.get("error", "unknown")}
            thread_ts = data.get("ts")

            # 2) 画像を同チャンネルのスレッドにアップロード（v2 フロー）
            for image_bytes, filename in (image_bytes_list or []):
                upload_ok = await _upload_file_v2(
                    client, channel_id, image_bytes, filename, thread_ts
                )
                if not upload_ok:
                    logger.warning("Slack 画像アップロード失敗: %s", filename)

            return {"ok": True, "ts": thread_ts, "error": None}
    except Exception as exc:
        logger.warning("Slack 投稿例外: %s", exc)
        return {"ok": False, "ts": None, "error": str(exc)}


async def _upload_file_v2(
    client: httpx.AsyncClient,
    channel_id: str,
    file_bytes: bytes,
    filename: str,
    thread_ts: Optional[str],
) -> bool:
    """files.getUploadURLExternal → PUT → files.completeUploadExternal"""
    try:
        # 1) アップロードURL取得
        res = await client.post(
            f"{SLACK_API_BASE}/files.getUploadURLExternal",
            headers={
                "Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"filename": filename, "length": str(len(file_bytes))},
        )
        data = res.json()
        if not data.get("ok"):
            logger.warning("getUploadURLExternal 失敗: %s", data.get("error"))
            return False

        upload_url = data["upload_url"]
        file_id = data["file_id"]

        # 2) バイナリを PUT
        put_res = await client.post(upload_url, content=file_bytes)
        if put_res.status_code != 200:
            logger.warning("upload PUT 失敗: %s", put_res.status_code)
            return False

        # 3) 完了通知（チャンネル共有）
        complete_payload: Dict[str, Any] = {
            "files": [{"id": file_id, "title": filename}],
            "channel_id": channel_id,
        }
        if thread_ts:
            complete_payload["thread_ts"] = thread_ts

        res = await client.post(
            f"{SLACK_API_BASE}/files.completeUploadExternal",
            headers=_headers(),
            json=complete_payload,
        )
        data = res.json()
        if not data.get("ok"):
            logger.warning("completeUploadExternal 失敗: %s", data.get("error"))
            return False
        return True
    except Exception as exc:
        logger.warning("ファイルアップロード例外: %s", exc)
        return False
