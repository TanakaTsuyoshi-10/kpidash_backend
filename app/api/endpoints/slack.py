"""
Slack連携APIエンドポイント

Slack投稿（本日の新着・昨日）の取得エンドポイントを定義する。
ルーター登録時に /api/v1/slack プレフィックスを付与する想定。
"""
from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.schemas.slack import SlackPostsResponse
from app.services import slack_service

router = APIRouter()


@router.get(
    "/posts",
    response_model=SlackPostsResponse,
    summary="Slack投稿取得",
    description=(
        "Bot が参加する全チャンネルの本日・昨日の投稿を取得する。"
        "Slack連携が未設定の場合はサンプルデータを返す。"
    ),
)
async def get_slack_posts(
    current_user=Depends(get_current_user),
) -> SlackPostsResponse:
    """Slack投稿（本日・昨日）を取得する。"""
    data = await slack_service.get_slack_posts()
    return SlackPostsResponse(**data)
