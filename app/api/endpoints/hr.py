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


# =============================================================================
# 人事分析（人員構成・推移・入退社・組織指標・店舗別人件費×売上）
# =============================================================================

from supabase import Client  # noqa: E402

from app.api.deps import get_supabase_admin  # noqa: E402
from app.schemas.hr import (  # noqa: E402
    HeadcountSummaryResponse,
    HeadcountTrendResponse,
    TurnoverResponse,
    OrgHealthResponse,
    StoreLaborResponse,
)
from app.services import hr_analytics_service  # noqa: E402


@router.get(
    "/headcount",
    response_model=HeadcountSummaryResponse,
    summary="店舗別・部門別 所属人数",
    description="現在の在籍者を店舗別・部門別に雇用形態内訳つきで集計する。",
)
async def get_headcount(
    current_user: User = Depends(require_labor),
    supabase: Client = Depends(get_supabase_admin),
):
    return HeadcountSummaryResponse(**await hr_analytics_service.get_headcount_summary(supabase))


@router.get(
    "/headcount-trend",
    response_model=HeadcountTrendResponse,
    summary="在籍人数の推移",
    description="月末時点の在籍人数（雇用形態別・部門別）を過去に遡って集計する。",
)
async def get_headcount_trend(
    months: int = Query(default=36, ge=6, le=60),
    current_user: User = Depends(require_labor),
):
    return HeadcountTrendResponse(**await hr_analytics_service.get_headcount_trend(months))


@router.get(
    "/turnover",
    response_model=TurnoverResponse,
    summary="入退社サマリー",
    description="直近の月別入社・退職数、離職率、退職理由の分布を集計する。",
)
async def get_turnover(
    months: int = Query(default=12, ge=3, le=36),
    current_user: User = Depends(require_labor),
):
    return TurnoverResponse(**await hr_analytics_service.get_turnover_summary(months))


@router.get(
    "/org-health",
    response_model=OrgHealthResponse,
    summary="組織の健全性",
    description="在籍者の平均年齢・平均勤続年数・年齢構成を全社／部門別に集計する。",
)
async def get_org_health(current_user: User = Depends(require_labor)):
    return OrgHealthResponse(**await hr_analytics_service.get_org_health())


@router.get(
    "/store-labor",
    response_model=StoreLaborResponse,
    summary="店舗別 人件費×売上",
    description="店舗別の人件費・残業（SmartHR給与明細）を売上実績と結合し、人件費率・1人あたり売上を算出する。",
)
async def get_store_labor(
    month: str = Query(..., description="対象月（YYYY-MM または YYYY-MM-01）"),
    current_user: User = Depends(require_labor),
    supabase: Client = Depends(get_supabase_admin),
):
    return StoreLaborResponse(**await hr_analytics_service.get_store_labor(supabase, month))
