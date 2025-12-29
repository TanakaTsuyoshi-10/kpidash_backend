"""
ダッシュボードAPIエンドポイント

経営層向けダッシュボードのデータ取得APIを提供する。
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from supabase import Client

from app.api.deps import get_supabase_client
from app.schemas.dashboard import (
    DashboardResponse,
    CompanySummary,
    CashFlowData,
    ChartDataPoint,
    AlertItem,
)
from app.services.dashboard_service import (
    get_dashboard_data,
    get_company_summary as service_get_company_summary,
    get_cash_flow as service_get_cash_flow,
    get_chart_data as service_get_chart_data,
    get_alerts as service_get_alerts,
)
from app.services.period_utils import (
    get_period_range,
    get_current_period_defaults,
    get_fiscal_year,
)


router = APIRouter(
    prefix="/api/v1/dashboard",
    tags=["ダッシュボード"],
)


# =============================================================================
# ダッシュボード全体データ取得
# =============================================================================

@router.get(
    "",
    response_model=DashboardResponse,
    summary="ダッシュボードデータ取得",
    description="""
    経営層向けダッシュボードの全データを取得する。

    期間タイプによって取得するデータの範囲が変わる:
    - monthly: 指定月のデータ
    - quarterly: 四半期（Q1:9-11月, Q2:12-2月, Q3:3-5月, Q4:6-8月）
    - yearly: 年度累計（9月〜翌8月）
    """,
)
async def get_dashboard(
    period_type: str = Query(
        default="monthly",
        description="期間タイプ（monthly/quarterly/yearly）",
        regex="^(monthly|quarterly|yearly)$"
    ),
    year: Optional[int] = Query(
        default=None,
        description="年度（省略時は現在の年度）",
        ge=2020,
        le=2100
    ),
    month: Optional[int] = Query(
        default=None,
        description="月（monthlyの場合、省略時は現在の月）",
        ge=1,
        le=12
    ),
    quarter: Optional[int] = Query(
        default=None,
        description="四半期（quarterlyの場合、省略時は現在の四半期）",
        ge=1,
        le=4
    ),
    supabase: Client = Depends(get_supabase_client),
) -> DashboardResponse:
    """
    ダッシュボードの全データを取得する

    Args:
        period_type: 期間タイプ
        year: 年度
        month: 月
        quarter: 四半期
        supabase: Supabaseクライアント

    Returns:
        DashboardResponse: ダッシュボード全体のレスポンス
    """
    try:
        return await get_dashboard_data(
            supabase=supabase,
            period_type=period_type,
            year=year,
            month=month,
            quarter=quarter,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"ダッシュボードデータの取得に失敗しました: {str(e)}"
        )


# =============================================================================
# 全社サマリーのみ取得
# =============================================================================

@router.get(
    "/summary",
    response_model=CompanySummary,
    summary="全社サマリー取得",
    description="全社の売上高、粗利益、営業利益などの主要指標を取得する。",
)
async def get_summary(
    period_type: str = Query(
        default="monthly",
        description="期間タイプ（monthly/quarterly/yearly）",
        regex="^(monthly|quarterly|yearly)$"
    ),
    year: Optional[int] = Query(
        default=None,
        description="年度",
        ge=2020,
        le=2100
    ),
    month: Optional[int] = Query(
        default=None,
        description="月",
        ge=1,
        le=12
    ),
    quarter: Optional[int] = Query(
        default=None,
        description="四半期",
        ge=1,
        le=4
    ),
    supabase: Client = Depends(get_supabase_client),
) -> CompanySummary:
    """
    全社サマリーを取得する
    """
    try:
        # デフォルト値の設定
        default_year, default_month, default_quarter = get_current_period_defaults()
        year = year or default_year
        month = month or default_month
        quarter = quarter or default_quarter

        # 期間を計算
        start_date, end_date, period_label = get_period_range(
            period_type, year, month, quarter
        )

        return await service_get_company_summary(
            supabase=supabase,
            start_date=start_date,
            end_date=end_date,
            period_type=period_type,
            fiscal_year=year,
            period_label=period_label,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"全社サマリーの取得に失敗しました: {str(e)}"
        )


# =============================================================================
# キャッシュフローのみ取得
# =============================================================================

@router.get(
    "/cashflow",
    response_model=CashFlowData,
    summary="キャッシュフロー取得",
    description="営業CF、投資CF、財務CF、フリーCFの今期・前年・前々年実績を取得する。",
)
async def get_cashflow(
    period_type: str = Query(
        default="monthly",
        description="期間タイプ（monthly/quarterly/yearly）",
        regex="^(monthly|quarterly|yearly)$"
    ),
    year: Optional[int] = Query(
        default=None,
        description="年度",
        ge=2020,
        le=2100
    ),
    month: Optional[int] = Query(
        default=None,
        description="月",
        ge=1,
        le=12
    ),
    quarter: Optional[int] = Query(
        default=None,
        description="四半期",
        ge=1,
        le=4
    ),
    supabase: Client = Depends(get_supabase_client),
) -> CashFlowData:
    """
    キャッシュフローデータを取得する
    """
    try:
        # デフォルト値の設定
        default_year, default_month, default_quarter = get_current_period_defaults()
        year = year or default_year
        month = month or default_month
        quarter = quarter or default_quarter

        # 期間を計算
        start_date, end_date, _ = get_period_range(
            period_type, year, month, quarter
        )

        return await service_get_cash_flow(
            supabase=supabase,
            start_date=start_date,
            end_date=end_date,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"キャッシュフローの取得に失敗しました: {str(e)}"
        )


# =============================================================================
# グラフデータ取得
# =============================================================================

@router.get(
    "/chart",
    response_model=List[ChartDataPoint],
    summary="推移グラフデータ取得",
    description="過去N ヶ月の売上高・営業利益の推移データを取得する。",
)
async def get_chart(
    months: int = Query(
        default=12,
        description="取得する月数",
        ge=1,
        le=36
    ),
    supabase: Client = Depends(get_supabase_client),
) -> List[ChartDataPoint]:
    """
    推移グラフ用データを取得する
    """
    try:
        return await service_get_chart_data(
            supabase=supabase,
            months=months,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"グラフデータの取得に失敗しました: {str(e)}"
        )


# =============================================================================
# アラート取得
# =============================================================================

@router.get(
    "/alerts",
    response_model=List[AlertItem],
    summary="アラート取得",
    description="予算未達の項目をアラートとして取得する。達成率80%未満はcritical、80-99%はwarning。",
)
async def get_dashboard_alerts(
    period_type: str = Query(
        default="monthly",
        description="期間タイプ（monthly/quarterly/yearly）",
        regex="^(monthly|quarterly|yearly)$"
    ),
    year: Optional[int] = Query(
        default=None,
        description="年度",
        ge=2020,
        le=2100
    ),
    month: Optional[int] = Query(
        default=None,
        description="月",
        ge=1,
        le=12
    ),
    quarter: Optional[int] = Query(
        default=None,
        description="四半期",
        ge=1,
        le=4
    ),
    supabase: Client = Depends(get_supabase_client),
) -> List[AlertItem]:
    """
    アラート項目を取得する
    """
    try:
        # デフォルト値の設定
        default_year, default_month, default_quarter = get_current_period_defaults()
        year = year or default_year
        month = month or default_month
        quarter = quarter or default_quarter

        # 期間を計算
        start_date, end_date, _ = get_period_range(
            period_type, year, month, quarter
        )

        return await service_get_alerts(
            supabase=supabase,
            start_date=start_date,
            end_date=end_date,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"アラートの取得に失敗しました: {str(e)}"
        )
