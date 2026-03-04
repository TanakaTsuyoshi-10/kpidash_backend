"""
日次販売分析エンドポイント

3つのGET APIを提供する:
- GET /daily-sales/summary - 日別×店舗サマリー
- GET /daily-sales/hourly - 時間帯別ヒートマップ
- GET /daily-sales/trend - 日次推移グラフ
"""
from fastapi import APIRouter, Depends, Query
from supabase import Client

from app.api.deps import get_current_user, get_supabase_admin
from app.schemas.kpi import User
from app.schemas.daily_sales import (
    DailySalesSummaryResponse,
    HourlySalesResponse,
    DailyTrendResponse,
)
from app.services.daily_sales_service import (
    get_daily_sales_summary,
    get_hourly_sales,
    get_daily_trend,
)


router = APIRouter(tags=["日次販売分析"])


@router.get(
    "/summary",
    response_model=DailySalesSummaryResponse,
    summary="日別×店舗サマリーを取得",
    description="""
    指定月の日別×店舗の売上サマリーを取得する。

    前年同月データも取得し、前年比（YoY）を計算する。
    """,
)
async def daily_sales_summary(
    month: str = Query(..., description="対象年月 (YYYY-MM-01)", pattern=r"^\d{4}-\d{2}-01$"),
    department_slug: str = Query("store", description="部門スラッグ"),
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
):
    return await get_daily_sales_summary(supabase, month, department_slug)


@router.get(
    "/hourly",
    response_model=HourlySalesResponse,
    summary="時間帯別ヒートマップデータを取得",
    description="""
    指定日の時間帯別×店舗の売上データを取得する。

    ヒートマップ表示用に行計・列計も返す。
    """,
)
async def hourly_sales(
    date: str = Query(..., description="対象日 (YYYY-MM-DD)", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    department_slug: str = Query("store", description="部門スラッグ"),
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
):
    return await get_hourly_sales(supabase, date, department_slug)


@router.get(
    "/trend",
    response_model=DailyTrendResponse,
    summary="日次推移データを取得",
    description="""
    指定月の日次推移データ（当年+前年同月）を取得する。

    segment_idを省略すると全店舗合計を返す。
    """,
)
async def daily_trend(
    month: str = Query(..., description="対象年月 (YYYY-MM-01)", pattern=r"^\d{4}-\d{2}-01$"),
    segment_id: str = Query(None, description="セグメントID（省略時は全店舗合計）"),
    department_slug: str = Query("store", description="部門スラッグ"),
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
):
    return await get_daily_trend(supabase, month, segment_id, department_slug)
