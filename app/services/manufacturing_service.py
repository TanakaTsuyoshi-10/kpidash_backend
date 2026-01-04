"""
製造分析サービス

製造部門のデータ取得・分析を行うサービス。
製造量、出勤者数、1人あたり製造量、有給取得状況を管理する。
"""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional

from supabase import Client

from app.schemas.manufacturing import (
    ManufacturingDailySummary,
    ManufacturingMonthlySummary,
    ManufacturingComparison,
    ManufacturingChartData,
    ManufacturingAnalysisResponse,
)
from app.services.period_utils import (
    get_period_range,
    get_previous_year_range,
    get_two_years_ago_range,
    get_current_period_defaults,
)
from app.services.cache_service import cached, cache


# =============================================================================
# メイン関数
# =============================================================================

@cached(prefix="manufacturing", ttl=300)  # 5分キャッシュ
async def get_manufacturing_analysis(
    supabase: Client,
    period_type: str = "monthly",
    year: Optional[int] = None,
    month: Optional[int] = None,
) -> ManufacturingAnalysisResponse:
    """
    製造分析データを取得する

    Args:
        supabase: Supabaseクライアント
        period_type: 期間タイプ（monthly/quarterly/yearly）
        year: 年度
        month: 月

    Returns:
        ManufacturingAnalysisResponse: 製造分析全体レスポンス
    """
    # デフォルト値の設定
    if year is None or month is None:
        default_year, default_month, _ = get_current_period_defaults()
        year = year or default_year
        month = month or default_month

    # 期間を計算
    start_date, end_date, period_label = get_period_range(
        period_type, year, month, quarter=1
    )

    # 月次サマリーを取得
    summary = await get_monthly_summary(supabase, start_date, end_date)

    # 日次データを取得（monthlyの場合のみ）
    daily_data = []
    if period_type == "monthly":
        daily_data = await get_daily_data(supabase, start_date, end_date)

    # 前年比較データを取得
    comparison = await get_comparison_data(supabase, start_date, end_date, period_label)

    # グラフ用データを取得
    chart_data = await get_chart_data(supabase, months=12)

    return ManufacturingAnalysisResponse(
        period=period_label,
        period_type=period_type,
        summary=summary,
        daily_data=daily_data,
        comparison=comparison,
        chart_data=chart_data,
    )


# =============================================================================
# 月次サマリー取得
# =============================================================================

async def get_monthly_summary(
    supabase: Client,
    start_date: date,
    end_date: date,
) -> ManufacturingMonthlySummary:
    """
    指定期間の月次サマリーを取得する

    Args:
        supabase: Supabaseクライアント
        start_date: 期間開始日
        end_date: 期間終了日

    Returns:
        ManufacturingMonthlySummary: 月次サマリー
    """
    # manufacturing_data から直接集計
    response = supabase.table("manufacturing_data").select(
        "production_batts, production_pieces, workers_count, paid_leave_hours"
    ).gte(
        "date", start_date.isoformat()
    ).lte(
        "date", end_date.isoformat()
    ).execute()

    total_batts = 0
    total_pieces = 0
    total_workers = 0
    total_paid_leave = Decimal("0")
    working_days = 0

    if response.data:
        for row in response.data:
            batts = row.get("production_batts") or 0
            pieces = row.get("production_pieces") or 0
            workers = row.get("workers_count") or 0
            leave = row.get("paid_leave_hours") or 0

            total_batts += batts
            total_pieces += pieces
            total_workers += workers
            total_paid_leave += Decimal(str(leave))

            # 製造があった日を稼働日としてカウント
            if batts > 0 or workers > 0:
                working_days += 1

    # 平均1人あたり製造量を計算
    avg_production = None
    if total_workers > 0:
        avg_production = (
            Decimal(str(total_batts)) / Decimal(str(total_workers))
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return ManufacturingMonthlySummary(
        month=start_date.strftime("%Y-%m"),
        total_batts=total_batts,
        total_pieces=total_pieces,
        total_workers=total_workers,
        avg_production_per_worker=avg_production,
        total_paid_leave_hours=total_paid_leave,
        working_days=working_days,
    )


# =============================================================================
# 日次データ取得
# =============================================================================

async def get_daily_data(
    supabase: Client,
    start_date: date,
    end_date: date,
) -> List[ManufacturingDailySummary]:
    """
    日次データを取得する

    Args:
        supabase: Supabaseクライアント
        start_date: 期間開始日
        end_date: 期間終了日

    Returns:
        List[ManufacturingDailySummary]: 日次データリスト
    """
    response = supabase.table("manufacturing_data").select(
        "date, production_batts, production_pieces, workers_count, "
        "production_per_worker, paid_leave_hours"
    ).gte(
        "date", start_date.isoformat()
    ).lte(
        "date", end_date.isoformat()
    ).order(
        "date"
    ).execute()

    daily_data = []
    if response.data:
        for row in response.data:
            # 製造量（個数）の計算（未設定の場合）
            batts = row.get("production_batts")
            pieces = row.get("production_pieces")
            if batts and not pieces:
                pieces = batts * 60

            # 1人あたり製造量の計算（未設定の場合）
            workers = row.get("workers_count") or 0
            per_worker = row.get("production_per_worker")
            if batts and workers > 0 and not per_worker:
                per_worker = round(batts / workers, 2)

            daily_data.append(ManufacturingDailySummary(
                date=date.fromisoformat(row["date"]),
                production_batts=batts,
                production_pieces=pieces,
                workers_count=workers if workers > 0 else None,
                production_per_worker=Decimal(str(per_worker)) if per_worker else None,
                paid_leave_hours=Decimal(str(row.get("paid_leave_hours") or 0)),
            ))

    return daily_data


# =============================================================================
# 前年比較データ取得
# =============================================================================

async def get_comparison_data(
    supabase: Client,
    start_date: date,
    end_date: date,
    period_label: str,
) -> ManufacturingComparison:
    """
    前年比較データを取得する

    Args:
        supabase: Supabaseクライアント
        start_date: 期間開始日
        end_date: 期間終了日
        period_label: 期間ラベル

    Returns:
        ManufacturingComparison: 前年比較データ
    """
    # 今期データ
    current = await get_monthly_summary(supabase, start_date, end_date)

    # 前年同期間
    prev_start, prev_end = get_previous_year_range(start_date, end_date)
    previous_year = await get_monthly_summary(supabase, prev_start, prev_end)

    # 前々年同期間
    prev2_start, prev2_end = get_two_years_ago_range(start_date, end_date)
    previous_year2 = await get_monthly_summary(supabase, prev2_start, prev2_end)

    # 前年差・前年比を計算
    yoy_batts_diff = None
    yoy_batts_rate = None
    yoy_productivity_diff = None

    if previous_year.total_batts > 0:
        yoy_batts_diff = current.total_batts - previous_year.total_batts
        # 変化率 = (今期 - 前期) / 前期 × 100
        yoy_batts_rate = (
            (Decimal(str(current.total_batts)) - Decimal(str(previous_year.total_batts)))
            / Decimal(str(previous_year.total_batts)) * 100
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    if current.avg_production_per_worker and previous_year.avg_production_per_worker:
        yoy_productivity_diff = (
            current.avg_production_per_worker - previous_year.avg_production_per_worker
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return ManufacturingComparison(
        period=period_label,
        current=current,
        previous_year=previous_year if previous_year.total_batts > 0 else None,
        previous_year2=previous_year2 if previous_year2.total_batts > 0 else None,
        yoy_batts_diff=yoy_batts_diff,
        yoy_batts_rate=yoy_batts_rate,
        yoy_productivity_diff=yoy_productivity_diff,
    )


# =============================================================================
# グラフ用データ取得
# =============================================================================

async def get_chart_data(
    supabase: Client,
    months: int = 12,
) -> List[ManufacturingChartData]:
    """
    グラフ用データを取得する

    Args:
        supabase: Supabaseクライアント
        months: 取得する月数

    Returns:
        List[ManufacturingChartData]: グラフ用データリスト
    """
    chart_data = []
    today = date.today()

    for i in range(months - 1, -1, -1):
        # i ヶ月前の月を計算
        month_offset = today.month - i - 1
        year = today.year + (month_offset // 12)
        month = (month_offset % 12) + 1
        if month <= 0:
            month += 12
            year -= 1

        target_month = date(year, month, 1)

        # 月末日を計算
        if month == 12:
            next_month = date(year + 1, 1, 1)
        else:
            next_month = date(year, month + 1, 1)
        end_of_month = date(next_month.year, next_month.month, 1)
        end_of_month = date(
            end_of_month.year,
            end_of_month.month,
            1
        )
        # 1日前が月末
        import calendar
        _, last_day = calendar.monthrange(year, month)
        end_of_month = date(year, month, last_day)

        # 月次サマリーを取得
        summary = await get_monthly_summary(supabase, target_month, end_of_month)

        chart_data.append(ManufacturingChartData(
            month=target_month.strftime("%Y-%m"),
            total_batts=summary.total_batts,
            avg_production_per_worker=summary.avg_production_per_worker,
            total_workers=summary.total_workers,
        ))

    return chart_data
