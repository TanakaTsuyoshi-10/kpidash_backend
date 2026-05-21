"""
Slack連携スキーマ

Slack投稿（新着・昨日）機能のPydanticスキーマを定義する。
"""
from typing import List, Optional

from pydantic import BaseModel, Field


class SlackPost(BaseModel):
    """Slack投稿1件"""
    channel: str = Field(..., description="チャンネル名（先頭#付き）")
    author: str = Field(..., description="投稿者の表示名")
    text: str = Field(..., description="本文抜粋")
    ts: str = Field(..., description="Slackメッセージタイムスタンプ（unix秒.連番）")
    time_label: str = Field(..., description="表示用時刻ラベル（例: 10:32 / 昨 18:20）")
    permalink: Optional[str] = Field(None, description="Slackパーマリンク（クリックで開く）")

    class Config:
        from_attributes = True


class SlackPostsResponse(BaseModel):
    """Slack投稿一覧レスポンス"""
    new_posts: List[SlackPost] = Field(default_factory=list, description="本日の新着投稿")
    yesterday_posts: List[SlackPost] = Field(default_factory=list, description="昨日の投稿")
    is_sample: bool = Field(default=False, description="サンプルデータか（Slack連携未設定時True）")

    class Config:
        from_attributes = True
