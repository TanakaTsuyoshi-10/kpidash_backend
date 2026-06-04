"""
Slack連携APIエンドポイント

Slack投稿（本日の新着・昨日）の取得エンドポイントを定義する。
ルーター登録時に /api/v1/slack プレフィックスを付与する想定。
"""
from fastapi import APIRouter, Depends

from app.api.deps import require_page_permission
from app.schemas.slack import SlackPostsResponse
from app.services import slack_service

router = APIRouter()

# ダッシュボード上の Slack 投稿表示の閲覧権限（権限管理の "slack" キーで制御）。
# 管理者・役員は常に許可、一般利用者は user_page_permissions で個別付与。
require_slack = require_page_permission("slack")


@router.get(
    "/posts",
    response_model=SlackPostsResponse,
    summary="Slack投稿取得",
    description=(
        "Bot が参加する全チャンネルの本日・昨日の投稿を取得する。"
        "Slack連携が未設定の場合はサンプルデータを返す。"
        "権限管理の 'slack' キーで閲覧可否を制御する。"
    ),
)
async def get_slack_posts(
    current_user=Depends(require_slack),
) -> SlackPostsResponse:
    """Slack投稿（本日・昨日）を取得する。"""
    data = await slack_service.get_slack_posts()
    return SlackPostsResponse(**data)
