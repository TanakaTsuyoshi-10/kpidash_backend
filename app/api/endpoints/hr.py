"""
人事（HR）APIエンドポイント

SmartHR連携による部署別の人件費・時間外労働を提供する。
機密性の高い情報のため、役員・管理者のみアクセス可能。

注: ルーター登録時に /api/v1/hr プレフィックスを付与する想定のため、
    本ルーター内ではプレフィックスを含めない。
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.api.deps import require_page_permission
from app.schemas.hr import LaborSummaryResponse
from app.schemas.kpi import User
from app.services import smarthr_service

router = APIRouter()

# 経営指標（部署別 人件費・時間外）の閲覧権限（権限管理の "labor" キーで制御）
require_labor = require_page_permission("labor")


@router.get(
    "/labor-summary",
    response_model=LaborSummaryResponse,
    summary="部署別 人件費・時間外サマリー取得",
    description=(
        "SmartHR連携による部署別の人件費・時間外労働サマリーを取得する。"
        "認証情報が未設定の場合はサンプルデータ（is_sample=True）を返す。"
        "役員・管理者のみアクセス可能。"
    ),
)
async def get_labor_summary(
    month: Optional[str] = Query(
        default=None,
        description="対象月（YYYY-MM-DD または YYYY-MM。未指定なら最新月）",
    ),
    current_user: User = Depends(require_labor),
) -> LaborSummaryResponse:
    """部署別 人件費・時間外サマリーを取得する。"""
    data = await smarthr_service.get_labor_summary(month)
    return LaborSummaryResponse(**data)
