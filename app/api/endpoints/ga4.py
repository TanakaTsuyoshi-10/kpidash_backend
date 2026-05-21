"""
EC Web分析（GA4連携）APIエンドポイント

GoogleアナリティクスGA4から取得したEC主要数値を提供する。
ルーターのプレフィックスは含めない（include_router 側で /api/v1/ga4 を付与する想定）。
"""
from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.schemas.ga4 import GA4EcSummary
from app.services.ga4_service import get_ec_summary

router = APIRouter()


@router.get(
    "/ec-summary",
    response_model=GA4EcSummary,
    summary="EC Web分析サマリー取得",
    description=(
        "GoogleアナリティクスGA4から前日のEC主要数値（流入数・離脱率・"
        "流入経路・地区別流入）を取得する。GA4連携が無効な場合はサンプルデータを返す。"
    ),
)
async def read_ec_summary(
    current_user=Depends(get_current_user),
) -> GA4EcSummary:
    """EC Web分析サマリーを取得する。"""
    data = await get_ec_summary()
    return GA4EcSummary(**data)
