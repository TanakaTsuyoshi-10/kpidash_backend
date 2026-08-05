"""
日次販売分析エンドポイント

5つのGET APIを提供する:
- GET /daily-sales/summary - 日別×店舗サマリー
- GET /daily-sales/hourly - 時間帯別ヒートマップ（日別）
- GET /daily-sales/hourly-month - 時間帯別ヒートマップ（月間合計）
- GET /daily-sales/trend - 日次推移グラフ
- GET /daily-sales/weekday-analysis - 曜日別分析（平日/土日祝）
"""
from fastapi import APIRouter, Depends, Query
from supabase import Client

from app.api.deps import get_current_user, get_supabase_admin
from app.schemas.kpi import User
from app.schemas.daily_sales import (
    DailySalesSummaryResponse,
    HourlySalesResponse,
    DailyTrendResponse,
    WeekdayAnalysisResponse,
    StoreHourlyCustomersResponse,
)
from app.services.daily_sales_service import (
    get_store_hourly_customers,
    get_daily_sales_summary,
    get_hourly_sales,
    get_hourly_sales_month,
    get_daily_trend,
    get_weekday_analysis,
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
    "/hourly-month",
    response_model=HourlySalesResponse,
    summary="時間帯別ヒートマップデータ（月間合計）を取得",
    description="指定月の時間帯別×店舗の売上合計を取得する（月間合計ヒートマップ用）。",
)
async def hourly_sales_month(
    month: str = Query(..., description="対象年月 (YYYY-MM-01)", pattern=r"^\d{4}-\d{2}-01$"),
    department_slug: str = Query("store", description="部門スラッグ"),
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
):
    return await get_hourly_sales_month(supabase, month, department_slug)


@router.get(
    "/weekday-analysis",
    response_model=WeekdayAnalysisResponse,
    summary="曜日別分析（平日/土日祝）を取得",
    description="""
    指定月の平日/土日祝それぞれの平均売上・バット数・来客数・客単価と
    前年同月比を取得する。土日祝には日本の祝日（振替休日含む）を含める。
    """,
)
async def weekday_analysis(
    month: str = Query(..., description="対象年月 (YYYY-MM-01)", pattern=r"^\d{4}-\d{2}-01$"),
    department_slug: str = Query("store", description="部門スラッグ"),
    segment_id: str | None = Query(None, description="店舗ID（指定時はその店舗のみ）"),
    period_type: str = Query("monthly", description="期間タイプ（monthly: 単月, cumulative: 年度累計）"),
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
):
    return await get_weekday_analysis(supabase, month, department_slug, segment_id, period_type)


@router.get(
    "/hourly-customers-daily",
    response_model=StoreHourlyCustomersResponse,
    summary="店舗の日別×時間帯 来客ヒートマップを取得",
    description="""
    指定店舗・指定月の日別×時間帯の来客数マトリクスを取得する。
    行=日付、列=時間帯。col_totals が時間帯別合計（最終行用）、
    row_totals が日計。進行中の月は当日までを返す。
    """,
)
async def store_hourly_customers(
    month: str = Query(..., description="対象年月 (YYYY-MM-01)", pattern=r"^\d{4}-\d{2}-01$"),
    segment_id: str = Query(..., description="店舗ID"),
    period_type: str = Query("monthly", description="期間タイプ（monthly: 単月, cumulative: 年度累計）"),
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
):
    return await get_store_hourly_customers(supabase, month, segment_id, period_type)


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
