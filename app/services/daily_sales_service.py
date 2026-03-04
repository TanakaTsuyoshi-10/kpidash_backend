"""
日次販売分析クエリサービス

hourly_salesテーブルから3つのビュー用データを取得する。
manufacturing_service.pyパターンに従い、@cachedデコレータでキャッシュ。
"""
from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, Any, List, Optional

from supabase import Client

from app.services.cache_service import cached


# =============================================================================
# ヘルパー関数
# =============================================================================

def _fetch_all(query_builder) -> list:
    """Supabaseの1000行制限を回避して全行を取得する"""
    all_data = []
    offset = 0
    batch = 1000
    while True:
        result = query_builder.range(offset, offset + batch - 1).execute()
        all_data.extend(result.data)
        if len(result.data) < batch:
            break
        offset += batch
    return all_data

def _get_month_range(month_str: str):
    """月文字列(YYYY-MM-01)から月の開始日・終了日を返す"""
    parts = month_str.split("-")
    year, month = int(parts[0]), int(parts[1])
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    return start, end


def _previous_year_date(d: date) -> date:
    """前年同日を返す（2/29→2/28にフォールバック）"""
    try:
        return d.replace(year=d.year - 1)
    except ValueError:
        return d.replace(year=d.year - 1, day=28)


async def _get_segments(supabase: Client, department_slug: str = "store"):
    """セグメント一覧を取得"""
    dept_response = supabase.table("departments").select("id").eq(
        "slug", department_slug
    ).single().execute()
    department_id = dept_response.data["id"]

    segments_response = supabase.table("segments").select(
        "id, code, name"
    ).eq("department_id", department_id).order("code").execute()

    return segments_response.data


# =============================================================================
# API 1: 日別×店舗サマリー
# =============================================================================

@cached(prefix="daily_sales", ttl=300)
async def get_daily_sales_summary(
    supabase: Client,
    month: str,
    department_slug: str = "store",
) -> Dict[str, Any]:
    """
    日別×店舗サマリーデータを取得する

    Args:
        supabase: Supabaseクライアント
        month: 対象年月 (YYYY-MM-01)
        department_slug: 部門スラッグ

    Returns:
        DailySalesSummaryResponse相当のdict
    """
    start, end = _get_month_range(month)
    prev_start = _previous_year_date(start)
    prev_end = _previous_year_date(end)

    # セグメント取得
    segments = await _get_segments(supabase, department_slug)
    segment_ids = [s["id"] for s in segments]

    if not segment_ids:
        return {
            "period": month,
            "dates": [],
            "stores": [],
            "data": [],
            "totals": [],
        }

    # 当月データ取得（1000行制限回避）
    current_data = _fetch_all(
        supabase.table("hourly_sales").select(
            "date, segment_id, sales, receipt_count"
        ).gte("date", start.isoformat()).lte(
            "date", end.isoformat()
        ).in_("segment_id", segment_ids)
    )

    # 前年同月データ取得
    prev_data = _fetch_all(
        supabase.table("hourly_sales").select(
            "date, segment_id, sales, receipt_count"
        ).gte("date", prev_start.isoformat()).lte(
            "date", prev_end.isoformat()
        ).in_("segment_id", segment_ids)
    )

    # 当月: (date, segment_id) でグループ集計
    current_agg: Dict[tuple, Dict[str, Any]] = defaultdict(
        lambda: {"sales": 0.0, "customers": 0}
    )
    for row in current_data:
        key = (row["date"], row["segment_id"])
        current_agg[key]["sales"] += float(row["sales"])
        current_agg[key]["customers"] += int(row["receipt_count"])

    # 前年: (date, segment_id) でグループ集計
    prev_agg: Dict[tuple, Dict[str, Any]] = defaultdict(
        lambda: {"sales": 0.0, "customers": 0}
    )
    for row in prev_data:
        key = (row["date"], row["segment_id"])
        prev_agg[key]["sales"] += float(row["sales"])
        prev_agg[key]["customers"] += int(row["receipt_count"])

    # 日付リスト生成
    dates = []
    d = start
    while d <= end:
        dates.append(d.isoformat())
        d += timedelta(days=1)

    # 店舗情報
    stores = [
        {"segment_id": s["id"], "segment_code": s["code"], "segment_name": s["name"]}
        for s in segments
    ]

    # データ作成
    data = []
    # 月計用
    monthly_totals: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "sales": 0.0, "customers": 0,
            "sales_py": 0.0, "customers_py": 0,
        }
    )

    for dt_str in dates:
        for seg in segments:
            seg_id = seg["id"]
            key = (dt_str, seg_id)
            cur = current_agg.get(key, {"sales": 0.0, "customers": 0})

            # 前年同日
            try:
                cur_date = date.fromisoformat(dt_str)
                prev_date = _previous_year_date(cur_date)
                prev_key = (prev_date.isoformat(), seg_id)
            except ValueError:
                prev_key = None

            prev = prev_agg.get(prev_key, {"sales": 0.0, "customers": 0}) if prev_key else {"sales": 0.0, "customers": 0}

            sales = cur["sales"]
            customers = cur["customers"]
            unit_price = round(sales / customers, 0) if customers > 0 else 0

            sales_py = prev["sales"]
            customers_py = prev["customers"]

            yoy_sales = round((sales / sales_py - 1) * 100, 1) if sales_py > 0 else None
            yoy_customers = round((customers / customers_py - 1) * 100, 1) if customers_py > 0 else None

            entry = {
                "date": dt_str,
                "segment_id": seg_id,
                "sales": sales,
                "customers": customers,
                "unit_price": unit_price,
                "sales_previous_year": sales_py if sales_py > 0 else None,
                "customers_previous_year": customers_py if customers_py > 0 else None,
                "yoy_sales_rate": yoy_sales,
                "yoy_customers_rate": yoy_customers,
            }

            # 売上か客数があるデータのみ追加
            if sales > 0 or customers > 0 or sales_py > 0:
                data.append(entry)

            # 月計に加算
            monthly_totals[seg_id]["sales"] += sales
            monthly_totals[seg_id]["customers"] += customers
            monthly_totals[seg_id]["sales_py"] += sales_py
            monthly_totals[seg_id]["customers_py"] += customers_py

    # 月計行
    totals = []
    for seg in segments:
        seg_id = seg["id"]
        mt = monthly_totals[seg_id]
        sales = mt["sales"]
        customers = mt["customers"]
        unit_price = round(sales / customers, 0) if customers > 0 else 0
        sales_py = mt["sales_py"]
        customers_py = mt["customers_py"]

        yoy_sales = round((sales / sales_py - 1) * 100, 1) if sales_py > 0 else None
        yoy_customers = round((customers / customers_py - 1) * 100, 1) if customers_py > 0 else None

        totals.append({
            "date": "total",
            "segment_id": seg_id,
            "sales": sales,
            "customers": customers,
            "unit_price": unit_price,
            "sales_previous_year": sales_py if sales_py > 0 else None,
            "customers_previous_year": customers_py if customers_py > 0 else None,
            "yoy_sales_rate": yoy_sales,
            "yoy_customers_rate": yoy_customers,
        })

    return {
        "period": month,
        "dates": dates,
        "stores": stores,
        "data": data,
        "totals": totals,
    }


# =============================================================================
# API 2: 時間帯別ヒートマップ
# =============================================================================

@cached(prefix="daily_sales", ttl=300)
async def get_hourly_sales(
    supabase: Client,
    target_date: str,
    department_slug: str = "store",
) -> Dict[str, Any]:
    """
    指定日の時間帯別×店舗データを取得する

    Args:
        supabase: Supabaseクライアント
        target_date: 対象日 (YYYY-MM-DD)
        department_slug: 部門スラッグ

    Returns:
        HourlySalesResponse相当のdict
    """
    segments = await _get_segments(supabase, department_slug)
    segment_ids = [s["id"] for s in segments]

    if not segment_ids:
        return {
            "date": target_date,
            "hours": [],
            "stores": [],
            "data": [],
            "row_totals": [],
            "col_totals": [],
        }

    # データ取得（1000行制限回避）
    hourly_data = _fetch_all(
        supabase.table("hourly_sales").select(
            "hour, segment_id, sales, receipt_count"
        ).eq("date", target_date).in_("segment_id", segment_ids)
    )

    # (hour, segment_id) で集計
    agg: Dict[tuple, Dict[str, Any]] = defaultdict(
        lambda: {"sales": 0.0, "customers": 0}
    )
    hours_set = set()

    for row in hourly_data:
        key = (row["hour"], row["segment_id"])
        agg[key]["sales"] += float(row["sales"])
        agg[key]["customers"] += int(row["receipt_count"])
        hours_set.add(row["hour"])

    # 営業時間帯（9〜19時をデフォルト、データがあればそちらを使う）
    if hours_set:
        min_hour = min(hours_set)
        max_hour = max(hours_set)
        hours = list(range(min_hour, max_hour + 1))
    else:
        hours = list(range(9, 20))

    stores = [
        {"segment_id": s["id"], "segment_code": s["code"], "segment_name": s["name"]}
        for s in segments
    ]

    # データ
    data = []
    for hour in hours:
        for seg in segments:
            key = (hour, seg["id"])
            val = agg.get(key, {"sales": 0.0, "customers": 0})
            data.append({
                "hour": hour,
                "segment_id": seg["id"],
                "sales": val["sales"],
                "customers": val["customers"],
            })

    # 行計（店舗別合計）
    row_totals = []
    for seg in segments:
        total_sales = sum(
            agg.get((h, seg["id"]), {"sales": 0.0})["sales"] for h in hours
        )
        total_customers = sum(
            agg.get((h, seg["id"]), {"customers": 0})["customers"] for h in hours
        )
        row_totals.append({
            "segment_id": seg["id"],
            "sales": total_sales,
            "customers": total_customers,
        })

    # 列計（時間帯別合計）
    col_totals = []
    for hour in hours:
        total_sales = sum(
            agg.get((hour, seg["id"]), {"sales": 0.0})["sales"] for seg in segments
        )
        total_customers = sum(
            agg.get((hour, seg["id"]), {"customers": 0})["customers"] for seg in segments
        )
        col_totals.append({
            "hour": hour,
            "sales": total_sales,
            "customers": total_customers,
        })

    return {
        "date": target_date,
        "hours": hours,
        "stores": stores,
        "data": data,
        "row_totals": row_totals,
        "col_totals": col_totals,
    }


# =============================================================================
# API 3: 日次推移グラフ
# =============================================================================

@cached(prefix="daily_sales", ttl=300)
async def get_daily_trend(
    supabase: Client,
    month: str,
    segment_id: Optional[str] = None,
    department_slug: str = "store",
) -> Dict[str, Any]:
    """
    日次推移データ（当年+前年同月）を取得する

    Args:
        supabase: Supabaseクライアント
        month: 対象年月 (YYYY-MM-01)
        segment_id: セグメントID（省略時は全店舗合計）
        department_slug: 部門スラッグ

    Returns:
        DailyTrendResponse相当のdict
    """
    start, end = _get_month_range(month)
    prev_start = _previous_year_date(start)
    prev_end = _previous_year_date(end)

    # セグメント名を取得
    segment_name = None
    if segment_id:
        seg_response = supabase.table("segments").select(
            "name"
        ).eq("id", segment_id).single().execute()
        segment_name = seg_response.data["name"]

    # 当月データ（1000行制限回避）
    query = supabase.table("hourly_sales").select(
        "date, sales, receipt_count"
    ).gte("date", start.isoformat()).lte("date", end.isoformat())

    if segment_id:
        query = query.eq("segment_id", segment_id)
    else:
        segments = await _get_segments(supabase, department_slug)
        segment_ids = [s["id"] for s in segments]
        if segment_ids:
            query = query.in_("segment_id", segment_ids)

    current_data = _fetch_all(query)

    # 前年同月データ
    prev_query = supabase.table("hourly_sales").select(
        "date, sales, receipt_count"
    ).gte("date", prev_start.isoformat()).lte("date", prev_end.isoformat())

    if segment_id:
        prev_query = prev_query.eq("segment_id", segment_id)
    else:
        if segment_ids:
            prev_query = prev_query.in_("segment_id", segment_ids)

    prev_data = _fetch_all(prev_query)

    # 日別に集計
    current_daily: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"sales": 0.0, "customers": 0}
    )
    for row in current_data:
        current_daily[row["date"]]["sales"] += float(row["sales"])
        current_daily[row["date"]]["customers"] += int(row["receipt_count"])

    prev_daily: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"sales": 0.0, "customers": 0}
    )
    for row in prev_data:
        prev_daily[row["date"]]["sales"] += float(row["sales"])
        prev_daily[row["date"]]["customers"] += int(row["receipt_count"])

    # 日次データ作成
    current_year = []
    d = start
    while d <= end:
        dt_str = d.isoformat()
        val = current_daily.get(dt_str, {"sales": 0.0, "customers": 0})
        current_year.append({
            "date": dt_str,
            "sales": val["sales"],
            "customers": val["customers"],
        })
        d += timedelta(days=1)

    previous_year = []
    d = prev_start
    while d <= prev_end:
        dt_str = d.isoformat()
        val = prev_daily.get(dt_str, {"sales": 0.0, "customers": 0})
        previous_year.append({
            "date": dt_str,
            "sales": val["sales"],
            "customers": val["customers"],
        })
        d += timedelta(days=1)

    return {
        "period": month,
        "segment_id": segment_id,
        "segment_name": segment_name,
        "current_year": current_year,
        "previous_year": previous_year,
    }
