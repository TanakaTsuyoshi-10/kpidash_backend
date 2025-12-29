"""
製造分析APIエンドポイント

製造部門のデータ取得・分析APIを提供する。
"""
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from supabase import Client

from app.api.deps import get_supabase_client
from app.schemas.manufacturing import (
    ManufacturingAnalysisResponse,
    ManufacturingMonthlySummary,
    ManufacturingDailySummary,
    ManufacturingComparison,
    ManufacturingChartData,
)
from app.services.manufacturing_service import (
    get_manufacturing_analysis,
    get_monthly_summary,
    get_daily_data,
    get_comparison_data,
    get_chart_data,
)
from app.services.period_utils import (
    get_period_range,
    get_current_period_defaults,
)


router = APIRouter(
    prefix="/manufacturing",
    tags=["製造分析"],
)


# =============================================================================
# 製造分析データ全体取得
# =============================================================================

@router.get(
    "",
    response_model=ManufacturingAnalysisResponse,
    summary="製造分析データ取得",
    description="""
    製造部門の分析データを取得する。

    期間タイプによって取得するデータの範囲が変わる:
    - monthly: 指定月のデータ（日次データを含む）
    - quarterly: 四半期データ
    - yearly: 年度累計データ
    """,
)
async def get_manufacturing(
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
        description="月（省略時は現在の月）",
        ge=1,
        le=12
    ),
    supabase: Client = Depends(get_supabase_client),
) -> ManufacturingAnalysisResponse:
    """
    製造分析データを取得する
    """
    try:
        return await get_manufacturing_analysis(
            supabase=supabase,
            period_type=period_type,
            year=year,
            month=month,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"製造分析データの取得に失敗しました: {str(e)}"
        )


# =============================================================================
# 月次サマリーのみ取得
# =============================================================================

@router.get(
    "/summary",
    response_model=ManufacturingMonthlySummary,
    summary="製造月次サマリー取得",
    description="製造部門の月次サマリーを取得する。",
)
async def get_manufacturing_summary(
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
    supabase: Client = Depends(get_supabase_client),
) -> ManufacturingMonthlySummary:
    """
    製造月次サマリーを取得する
    """
    try:
        # デフォルト値の設定
        default_year, default_month, _ = get_current_period_defaults()
        year = year or default_year
        month = month or default_month

        # 期間を計算
        start_date, end_date, _ = get_period_range(
            period_type, year, month, quarter=1
        )

        return await get_monthly_summary(
            supabase=supabase,
            start_date=start_date,
            end_date=end_date,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"製造月次サマリーの取得に失敗しました: {str(e)}"
        )


# =============================================================================
# 日次データ取得
# =============================================================================

@router.get(
    "/daily",
    response_model=List[ManufacturingDailySummary],
    summary="製造日次データ取得",
    description="製造部門の日次データを取得する。",
)
async def get_manufacturing_daily(
    year: Optional[int] = Query(
        default=None,
        description="年",
        ge=2020,
        le=2100
    ),
    month: Optional[int] = Query(
        default=None,
        description="月",
        ge=1,
        le=12
    ),
    supabase: Client = Depends(get_supabase_client),
) -> List[ManufacturingDailySummary]:
    """
    製造日次データを取得する
    """
    try:
        # デフォルト値の設定
        default_year, default_month, _ = get_current_period_defaults()
        year = year or default_year
        month = month or default_month

        # 月次期間を計算
        start_date, end_date, _ = get_period_range(
            "monthly", year, month, quarter=1
        )

        return await get_daily_data(
            supabase=supabase,
            start_date=start_date,
            end_date=end_date,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"製造日次データの取得に失敗しました: {str(e)}"
        )


# =============================================================================
# 前年比較データ取得
# =============================================================================

@router.get(
    "/comparison",
    response_model=ManufacturingComparison,
    summary="製造前年比較データ取得",
    description="製造部門の前年比較データを取得する。今期・前年・前々年のデータを比較。",
)
async def get_manufacturing_comparison(
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
    supabase: Client = Depends(get_supabase_client),
) -> ManufacturingComparison:
    """
    製造前年比較データを取得する
    """
    try:
        # デフォルト値の設定
        default_year, default_month, _ = get_current_period_defaults()
        year = year or default_year
        month = month or default_month

        # 期間を計算
        start_date, end_date, period_label = get_period_range(
            period_type, year, month, quarter=1
        )

        return await get_comparison_data(
            supabase=supabase,
            start_date=start_date,
            end_date=end_date,
            period_label=period_label,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"製造前年比較データの取得に失敗しました: {str(e)}"
        )


# =============================================================================
# グラフデータ取得
# =============================================================================

@router.get(
    "/chart",
    response_model=List[ManufacturingChartData],
    summary="製造グラフデータ取得",
    description="製造部門の月別推移グラフ用データを取得する。",
)
async def get_manufacturing_chart(
    months: int = Query(
        default=12,
        description="取得する月数",
        ge=1,
        le=36
    ),
    supabase: Client = Depends(get_supabase_client),
) -> List[ManufacturingChartData]:
    """
    製造グラフデータを取得する
    """
    try:
        return await get_chart_data(
            supabase=supabase,
            months=months,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"製造グラフデータの取得に失敗しました: {str(e)}"
        )
