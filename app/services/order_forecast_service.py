"""
予想注文（発注バット数予測）サービス

hourly_salesテーブルから前年・前々年の同曜日実績を参照し、
ぎょうざの発注バット数を予測する。

1バット = ぎょうざ60個
対象: product_group IN ('ぎょうざ', 'しょうが入ぎょうざ')
宅配(product_group='宅配')は除外（本社直送のため）
"""
import re
import unicodedata
from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, Any, List, Optional

from supabase import Client

from app.services.cache_service import cached
from app.services.daily_sales_service import _fetch_all, _get_segments
from app.services.weather_service import (
    resolve_region_name, get_weather_for_dates, get_weather_for_month
)


# =============================================================================
# 定数
# =============================================================================

BATS_DIVISOR = 60  # 1バット = 60個
TARGET_PRODUCT_GROUPS = ("ぎょうざ", "しょうが入ぎょうざ")
WEEKDAY_NAMES = ["月", "火", "水", "木", "金", "土", "日"]


# =============================================================================
# ヘルパー関数
# =============================================================================

def _extract_pack_size(product_name: str) -> int:
    """商品名からパック個数を抽出する（全角数字対応）

    例: "ぎょうざ２０個" → 20, "生姜入ぎょうざ３０個" → 30
    """
    normalized = unicodedata.normalize("NFKC", product_name)
    match = re.search(r"(\d+)個", normalized)
    return int(match.group(1)) if match else 0


def _find_same_weekday(target_date: date, reference_year: int) -> date:
    """target_dateと同じ曜日で、参照年の同日に最も近い日を返す"""
    try:
        ref_date = target_date.replace(year=reference_year)
    except ValueError:
        # 2/29 → 2/28 フォールバック
        ref_date = target_date.replace(year=reference_year, day=28)
    target_dow = target_date.weekday()
    ref_dow = ref_date.weekday()
    diff = target_dow - ref_dow
    if diff > 3:
        diff -= 7
    if diff < -3:
        diff += 7
    return ref_date + timedelta(days=diff)


def _get_month_range(d: date):
    """日付からその月の開始日・終了日を返す"""
    start = d.replace(day=1)
    if d.month == 12:
        end = date(d.year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(d.year, d.month + 1, 1) - timedelta(days=1)
    return start, end


def _fetch_gyoza_sales(
    supabase: Client,
    start_date: date,
    end_date: date,
    segment_ids: List[str],
) -> list:
    """ぎょうざ系商品の販売データを取得する"""
    rows = _fetch_all(
        supabase.table("hourly_sales")
        .select("date, hour, segment_id, product_name, product_group, quantity")
        .gte("date", start_date.isoformat())
        .lte("date", end_date.isoformat())
        .in_("segment_id", segment_ids)
        .in_("product_group", list(TARGET_PRODUCT_GROUPS))
    )
    return rows


def _calc_daily_bats(
    rows: list,
    segments: list,
) -> Dict[str, Any]:
    """販売データから日別・店舗別バット数を計算する

    Returns:
        {
            "by_date": { "2025-03-01": { "total": 80.5, "by_store": { seg_id: 8.0, ... } } },
            "by_date_store": { ("2025-03-01", seg_id): 8.0, ... }
        }
    """
    # (date, segment_id) → 合計個数
    agg: Dict[tuple, float] = defaultdict(float)

    for row in rows:
        pack_size = _extract_pack_size(row["product_name"])
        if pack_size == 0:
            continue
        qty = int(row["quantity"])
        pieces = qty * pack_size
        key = (row["date"], row["segment_id"])
        agg[key] += pieces

    # 日別集計
    by_date: Dict[str, Dict[str, Any]] = {}
    for (dt_str, seg_id), pieces in agg.items():
        if dt_str not in by_date:
            by_date[dt_str] = {"total": 0.0, "by_store": {}}
        bats = round(pieces / BATS_DIVISOR, 1)
        by_date[dt_str]["by_store"][seg_id] = bats
        by_date[dt_str]["total"] += bats

    # total を丸め
    for dt_str in by_date:
        by_date[dt_str]["total"] = round(by_date[dt_str]["total"], 1)

    return by_date


# =============================================================================
# メインAPI関数
# =============================================================================

@cached(prefix="order_forecast", ttl=300)
async def get_order_forecast(
    supabase: Client,
    target_date_str: str,
    segment_id: Optional[str] = None,
    department_slug: str = "store",
) -> Dict[str, Any]:
    """
    予想注文データを取得する

    Args:
        supabase: Supabaseクライアント
        target_date_str: 対象日 (YYYY-MM-DD)
        segment_id: セグメントID（省略時は全店舗）
        department_slug: 部門スラッグ

    Returns:
        OrderForecastResponse相当のdict
    """
    target_date = date.fromisoformat(target_date_str)
    target_weekday = WEEKDAY_NAMES[target_date.weekday()]

    # セグメント取得
    segments = await _get_segments(supabase, department_slug)
    segment_ids = [s["id"] for s in segments]

    if not segment_ids:
        return _empty_response(target_date_str, target_weekday)

    # 前年・前々年の同月範囲を計算
    prev_year = target_date.year - 1
    two_years_ago = target_date.year - 2

    # 前年同月の範囲
    prev_month_start, prev_month_end = _get_month_range(
        target_date.replace(year=prev_year) if target_date.month != 2 or target_date.day <= 28
        else target_date.replace(year=prev_year, day=28)
    )

    # 前々年同月の範囲
    try:
        two_yr_ref = target_date.replace(year=two_years_ago)
    except ValueError:
        two_yr_ref = target_date.replace(year=two_years_ago, day=28)
    two_yr_month_start, two_yr_month_end = _get_month_range(two_yr_ref)

    # データ取得
    prev_rows = _fetch_gyoza_sales(supabase, prev_month_start, prev_month_end, segment_ids)
    two_yr_rows = _fetch_gyoza_sales(supabase, two_yr_month_start, two_yr_month_end, segment_ids)

    # バット数計算
    prev_daily = _calc_daily_bats(prev_rows, segments)
    two_yr_daily = _calc_daily_bats(two_yr_rows, segments)

    # 同曜日の参照日
    prev_same_weekday = _find_same_weekday(target_date, prev_year)
    two_yr_same_weekday = _find_same_weekday(target_date, two_years_ago)

    prev_same_day_str = prev_same_weekday.isoformat()
    two_yr_same_day_str = two_yr_same_weekday.isoformat()

    prev_day_data = prev_daily.get(prev_same_day_str, {"total": 0.0, "by_store": {}})
    two_yr_day_data = two_yr_daily.get(two_yr_same_day_str, {"total": 0.0, "by_store": {}})

    # 店舗情報
    stores = [
        {"segment_id": s["id"], "segment_code": s["code"], "segment_name": s["name"]}
        for s in segments
    ]

    # 予測サマリー
    reference_dates = [
        {
            "year": prev_year,
            "date": prev_same_day_str,
            "weekday": WEEKDAY_NAMES[prev_same_weekday.weekday()],
            "bats": prev_day_data["total"],
        },
        {
            "year": two_years_ago,
            "date": two_yr_same_day_str,
            "weekday": WEEKDAY_NAMES[two_yr_same_weekday.weekday()],
            "bats": two_yr_day_data["total"],
        },
    ]

    # 店舗別予測
    by_store = []
    for s in segments:
        sid = s["id"]
        prev_bats = prev_day_data["by_store"].get(sid, 0.0)
        two_yr_bats = two_yr_day_data["by_store"].get(sid, 0.0)
        by_store.append({
            "segment_id": sid,
            "segment_name": s["name"],
            "bats": prev_bats,  # 予測 = 前年同曜日
            "prev_year_bats": prev_bats,
            "two_years_ago_bats": two_yr_bats if two_yr_bats > 0 else None,
        })

    forecast = {
        "total_bats": prev_day_data["total"],
        "reference_dates": reference_dates,
        "by_store": by_store,
    }

    # 前年同月カレンダー
    previous_year_calendar = _build_calendar(
        prev_year, prev_month_start.month, prev_daily, segments
    )

    # 前々年同月カレンダー
    two_years_ago_calendar = _build_calendar(
        two_years_ago, two_yr_month_start.month, two_yr_daily, segments
    )

    # 天気データ取得
    region_name = await resolve_region_name(supabase, segment_id)
    weather_dates = [target_date_str, prev_same_day_str, two_yr_same_day_str]
    weather_map = await get_weather_for_dates(supabase, region_name, weather_dates)

    # 参照日に天気を付与
    reference_dates[0]["weather"] = weather_map.get(prev_same_day_str)
    reference_dates[1]["weather"] = weather_map.get(two_yr_same_day_str)

    return {
        "target_date": target_date_str,
        "target_weekday": target_weekday,
        "stores": stores,
        "forecast": forecast,
        "previous_year": previous_year_calendar,
        "two_years_ago": two_years_ago_calendar,
        "weather": weather_map.get(target_date_str),
    }


def _build_calendar(
    year: int,
    month: int,
    daily_data: Dict[str, Dict[str, Any]],
    segments: list,
) -> Dict[str, Any]:
    """カレンダー月データを構築する"""
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)

    days = []
    d = start
    while d <= end:
        dt_str = d.isoformat()
        day_data = daily_data.get(dt_str, {"total": 0.0, "by_store": {}})
        by_store = [
            {
                "segment_id": s["id"],
                "segment_name": s["name"],
                "bats": day_data["by_store"].get(s["id"], 0.0),
            }
            for s in segments
            if day_data["by_store"].get(s["id"], 0.0) > 0
        ]
        days.append({
            "date": dt_str,
            "weekday": WEEKDAY_NAMES[d.weekday()],
            "bats": day_data["total"],
            "by_store": by_store,
        })
        d += timedelta(days=1)

    return {
        "year": year,
        "month": month,
        "days": days,
    }


PRODUCT_COLUMNS = [
    "ぎょうざ20個", "ぎょうざ30個", "ぎょうざ40個", "ぎょうざ50個", "生姜入ぎょうざ30個",
]


def _normalize_product_name(raw: str) -> str:
    """商品名を正規化する（全角数字→半角、表記揺れ吸収）"""
    return unicodedata.normalize("NFKC", raw)


@cached(prefix="order_forecast_daily_product", ttl=300)
async def get_daily_product_breakdown(
    supabase: Client,
    year: int,
    month: int,
    segment_id: Optional[str] = None,
    department_slug: str = "store",
) -> Dict[str, Any]:
    """
    日別×商品別パック数を返す

    Args:
        supabase: Supabaseクライアント
        year: 対象年
        month: 対象月
        segment_id: セグメントID（省略時は全店舗合算）
        department_slug: 部門スラッグ
    """
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)

    segments = await _get_segments(supabase, department_slug)
    segment_ids = [s["id"] for s in segments]
    if not segment_ids:
        return {"year": year, "month": month, "product_columns": PRODUCT_COLUMNS, "rows": []}

    rows = _fetch_gyoza_sales(supabase, start, end, segment_ids)

    # 日付×商品名別集計
    # key: (date, normalized_product_name) -> quantity合計
    agg: Dict[tuple, int] = defaultdict(int)
    for row in rows:
        if segment_id and row["segment_id"] != segment_id:
            continue
        norm_name = _normalize_product_name(row["product_name"])
        if norm_name not in PRODUCT_COLUMNS:
            continue
        agg[(row["date"], norm_name)] += int(row["quantity"])

    # 日付リスト
    result_rows = []
    d = start
    while d <= end:
        dt_str = d.isoformat()
        products = {}
        total_pieces = 0
        for col in PRODUCT_COLUMNS:
            qty = agg.get((dt_str, col), 0)
            products[col] = qty
            pack_size = _extract_pack_size(col)
            total_pieces += qty * pack_size

        result_rows.append({
            "date": dt_str,
            "weekday": WEEKDAY_NAMES[d.weekday()],
            "products": products,
            "total_bats": round(total_pieces / BATS_DIVISOR, 1),
        })
        d += timedelta(days=1)

    # 天気データ取得
    region_name = await resolve_region_name(supabase, segment_id)
    month_weather = await get_weather_for_month(supabase, region_name, year, month)
    for row in result_rows:
        row["weather"] = month_weather.get(row["date"])

    return {
        "year": year,
        "month": month,
        "product_columns": PRODUCT_COLUMNS,
        "rows": result_rows,
    }


@cached(prefix="order_forecast_hourly_product", ttl=300)
async def get_hourly_product_breakdown(
    supabase: Client,
    target_date: str,
    segment_id: Optional[str] = None,
    department_slug: str = "store",
) -> Dict[str, Any]:
    """
    特定日の時間帯×商品別パック数を返す

    Args:
        supabase: Supabaseクライアント
        target_date: 対象日 (YYYY-MM-DD)
        segment_id: セグメントID（省略時は全店舗合算）
        department_slug: 部門スラッグ
    """
    d = date.fromisoformat(target_date)

    segments = await _get_segments(supabase, department_slug)
    segment_ids = [s["id"] for s in segments]
    if not segment_ids:
        return {
            "date": target_date,
            "weekday": WEEKDAY_NAMES[d.weekday()],
            "product_columns": PRODUCT_COLUMNS,
            "rows": [],
        }

    rows = _fetch_gyoza_sales(supabase, d, d, segment_ids)

    # 時間帯×商品名別集計
    agg: Dict[tuple, int] = defaultdict(int)
    hours_seen: set = set()
    for row in rows:
        if segment_id and row["segment_id"] != segment_id:
            continue
        if row["date"] != target_date:
            continue
        norm_name = _normalize_product_name(row["product_name"])
        if norm_name not in PRODUCT_COLUMNS:
            continue
        hour = int(row["hour"])
        hours_seen.add(hour)
        agg[(hour, norm_name)] += int(row["quantity"])

    # 時間帯リスト（存在する時間のみ、ソート済み）
    result_rows = []
    for hour in sorted(hours_seen):
        products = {}
        total_pieces = 0
        for col in PRODUCT_COLUMNS:
            qty = agg.get((hour, col), 0)
            products[col] = qty
            pack_size = _extract_pack_size(col)
            total_pieces += qty * pack_size

        result_rows.append({
            "hour": hour,
            "products": products,
            "total_bats": round(total_pieces / BATS_DIVISOR, 1),
        })

    return {
        "date": target_date,
        "weekday": WEEKDAY_NAMES[d.weekday()],
        "product_columns": PRODUCT_COLUMNS,
        "rows": result_rows,
    }


def _empty_response(target_date_str: str, target_weekday: str) -> Dict[str, Any]:
    """空レスポンスを返す"""
    return {
        "target_date": target_date_str,
        "target_weekday": target_weekday,
        "stores": [],
        "forecast": {
            "total_bats": 0.0,
            "reference_dates": [],
            "by_store": [],
        },
        "previous_year": {"year": 0, "month": 0, "days": []},
        "two_years_ago": {"year": 0, "month": 0, "days": []},
    }
