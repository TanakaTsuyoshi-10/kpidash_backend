"""
ふるさと納税分析サービスモジュール

ふるさと納税の販売実績・リピート情報・返品苦情・口コミの
データ取得・集計ロジックを提供する。
"""
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

from supabase import Client

from app.services.metrics import get_fiscal_year


# =============================================================================
# ヘルパー関数
# =============================================================================

def get_cumulative_months(target_month: date) -> List[str]:
    """累計対象月のリストを取得（会計年度開始〜対象月）"""
    fiscal_year = get_fiscal_year(target_month)
    fiscal_start = date(fiscal_year, 9, 1)

    months = []
    current = fiscal_start
    while current <= target_month:
        months.append(current.isoformat())
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)

    return months


def _safe_int(value: Any) -> Optional[int]:
    """安全にint変換"""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _safe_float(value: Any) -> Optional[float]:
    """安全にfloat変換"""
    if value is None:
        return None
    try:
        if isinstance(value, Decimal):
            return float(value)
        return float(value)
    except (ValueError, TypeError):
        return None


def _sum_field(records: List[Dict], field: str) -> Optional[int]:
    """レコードリストの指定フィールドを合計（int）"""
    values = [_safe_int(r.get(field)) for r in records]
    values = [v for v in values if v is not None]
    return sum(values) if values else None


def _sum_field_float(records: List[Dict], field: str) -> Optional[float]:
    """レコードリストの指定フィールドを合計（float）"""
    values = [_safe_float(r.get(field)) for r in records]
    values = [v for v in values if v is not None]
    return sum(values) if values else None


# =============================================================================
# サマリー取得
# =============================================================================

async def get_furusato_summary(
    supabase: Client,
    month: date,
    period_type: str,
) -> Dict[str, Any]:
    """
    ふるさと納税サマリーを取得

    Args:
        supabase: Supabaseクライアント
        month: 対象月
        period_type: 'monthly' or 'cumulative'

    Returns:
        サマリーデータ辞書
    """
    fiscal_year = get_fiscal_year(month)

    if period_type == "monthly":
        return await _get_monthly_summary(supabase, month, fiscal_year)
    else:
        return await _get_cumulative_summary(supabase, month, fiscal_year)


async def _get_monthly_summary(
    supabase: Client,
    month: date,
    fiscal_year: int,
) -> Dict[str, Any]:
    """単月サマリーを取得"""
    result = supabase.table("furusato_nozei_stats") \
        .select("*") \
        .eq("month", month.isoformat()) \
        .execute()

    record = result.data[0] if result.data else {}

    return {
        "period": month.isoformat(),
        "period_type": "monthly",
        "fiscal_year": fiscal_year,
        "sales": {
            "inventory": _safe_int(record.get("inventory")),
            "orders": _safe_int(record.get("orders")),
            "sales": _safe_float(record.get("sales")),
            "unit_price": _safe_float(record.get("unit_price")),
            "orders_kyushu": _safe_int(record.get("orders_kyushu")),
            "orders_chugoku_shikoku": _safe_int(record.get("orders_chugoku_shikoku")),
            "orders_kansai": _safe_int(record.get("orders_kansai")),
            "orders_kanto": _safe_int(record.get("orders_kanto")),
            "orders_other": _safe_int(record.get("orders_other")),
            "cumulative_orders": None,
            "cumulative_sales": None,
            "weekly": record.get("weekly_sales"),
        },
        "repeat": {
            "new_customers": _safe_int(record.get("new_customers")),
            "cumulative_new_customers": None,
            "ec_site_buyers": _safe_int(record.get("ec_site_buyers")),
            "repeat_buyers": _safe_int(record.get("repeat_buyers")),
            "repeat_single_month": _safe_int(record.get("repeat_single_month")),
            "repeat_multi_month": _safe_int(record.get("repeat_multi_month")),
            "weekly": record.get("weekly_repeat"),
        },
        "complaint": {
            "reshipping_count": _safe_int(record.get("reshipping_count")),
            "complaint_count": _safe_int(record.get("complaint_count")),
            "weekly": record.get("weekly_complaint"),
        },
        "review": {
            "positive_reviews": _safe_int(record.get("positive_reviews")),
            "negative_reviews": _safe_int(record.get("negative_reviews")),
            "weekly": record.get("weekly_review"),
        },
        "comments": {
            "sales": record.get("comment_sales"),
            "repeat": record.get("comment_repeat"),
            "complaint": record.get("comment_complaint"),
            "review": record.get("comment_review"),
        },
    }


async def _get_cumulative_summary(
    supabase: Client,
    month: date,
    fiscal_year: int,
) -> Dict[str, Any]:
    """累計サマリーを取得"""
    months = get_cumulative_months(month)

    result = supabase.table("furusato_nozei_stats") \
        .select("*") \
        .in_("month", months) \
        .execute()

    records = result.data or []

    # 当月レコード（在庫数・単価・リピート詳細は当月値を使用）
    current_record = {}
    for r in records:
        if r.get("month") == month.isoformat():
            current_record = r
            break

    return {
        "period": month.isoformat(),
        "period_type": "cumulative",
        "fiscal_year": fiscal_year,
        "sales": {
            "inventory": _safe_int(current_record.get("inventory")),
            "orders": _safe_int(current_record.get("orders")),
            "sales": _safe_float(current_record.get("sales")),
            "unit_price": _safe_float(current_record.get("unit_price")),
            "orders_kyushu": _sum_field(records, "orders_kyushu"),
            "orders_chugoku_shikoku": _sum_field(records, "orders_chugoku_shikoku"),
            "orders_kansai": _sum_field(records, "orders_kansai"),
            "orders_kanto": _sum_field(records, "orders_kanto"),
            "orders_other": _sum_field(records, "orders_other"),
            "cumulative_orders": _sum_field(records, "orders"),
            "cumulative_sales": _sum_field_float(records, "sales"),
            "weekly": current_record.get("weekly_sales"),
        },
        "repeat": {
            "new_customers": _safe_int(current_record.get("new_customers")),
            "cumulative_new_customers": _sum_field(records, "new_customers"),
            "ec_site_buyers": _safe_int(current_record.get("ec_site_buyers")),
            "repeat_buyers": _safe_int(current_record.get("repeat_buyers")),
            "repeat_single_month": _safe_int(current_record.get("repeat_single_month")),
            "repeat_multi_month": _safe_int(current_record.get("repeat_multi_month")),
            "weekly": current_record.get("weekly_repeat"),
        },
        "complaint": {
            "reshipping_count": _sum_field(records, "reshipping_count"),
            "complaint_count": _sum_field(records, "complaint_count"),
            "weekly": current_record.get("weekly_complaint"),
        },
        "review": {
            "positive_reviews": _sum_field(records, "positive_reviews"),
            "negative_reviews": _sum_field(records, "negative_reviews"),
            "weekly": current_record.get("weekly_review"),
        },
        "comments": {
            "sales": current_record.get("comment_sales"),
            "repeat": current_record.get("comment_repeat"),
            "complaint": current_record.get("comment_complaint"),
            "review": current_record.get("comment_review"),
        },
    }


# =============================================================================
# データインポート
# =============================================================================

async def import_furusato_data(
    supabase: Client,
    month: date,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    ふるさと納税データをupsert

    Args:
        supabase: Supabaseクライアント
        month: 対象月
        data: 取り込みデータ

    Returns:
        処理結果
    """
    record = {
        "month": month.isoformat(),
        **data,
    }

    supabase.table("furusato_nozei_stats") \
        .upsert(record, on_conflict="month") \
        .execute()

    return {"created": 1, "updated": 0}
