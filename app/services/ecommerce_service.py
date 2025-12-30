"""
通販分析サービスモジュール

通販チャネル別・商品別・顧客別実績およびHPアクセス数の
データ取得・集計ロジックを提供する。
"""
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

from supabase import Client

from app.services.metrics import (
    get_fiscal_year,
    get_previous_year_month,
    normalize_to_month_start,
    calculate_yoy_rate,
)


# =============================================================================
# 定数定義
# =============================================================================

CHANNELS = ["EC", "電話", "FAX", "店舗受付"]


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


def get_previous_year_months(months: List[str]) -> List[str]:
    """前年同月リストを取得"""
    result = []
    for m in months:
        d = date.fromisoformat(m)
        prev = get_previous_year_month(d)
        result.append(prev.isoformat())
    return result


def get_two_years_ago_months(months: List[str]) -> List[str]:
    """前々年同月リストを取得"""
    result = []
    for m in months:
        d = date.fromisoformat(m)
        two_years = date(d.year - 2, d.month, 1)
        result.append(two_years.isoformat())
    return result


def safe_divide(a: Optional[float], b: Optional[float]) -> Optional[float]:
    """安全な除算（0除算防止）"""
    if a is None or b is None or b == 0:
        return None
    return round(a / b, 0)


def sum_values(values: List[Dict], key: str) -> Optional[Decimal]:
    """辞書リストから指定キーの合計を計算"""
    total = Decimal("0")
    has_value = False
    for v in values:
        if v.get(key) is not None:
            total += Decimal(str(v[key]))
            has_value = True
    return total if has_value else None


# =============================================================================
# チャネル別実績取得
# =============================================================================

def calculate_achievement_rate(actual: Optional[Decimal], target: Optional[Decimal]) -> Optional[float]:
    """達成率を計算する（%）"""
    if actual is None or target is None or target == 0:
        return None
    result = (actual / target) * 100
    return round(float(result), 1)


async def get_channel_summary(
    supabase: Client,
    target_month: date,
    period_type: str = "monthly"
) -> Dict[str, Any]:
    """
    チャネル別実績を取得（目標値・達成率を含む）

    Args:
        supabase: Supabaseクライアント
        target_month: 対象月
        period_type: 期間タイプ（monthly/cumulative）

    Returns:
        dict: チャネル別実績データ
    """
    target_month = normalize_to_month_start(target_month)
    fiscal_year = get_fiscal_year(target_month)
    is_cumulative = period_type == "cumulative"

    # 対象月リストを生成
    if is_cumulative:
        current_months = get_cumulative_months(target_month)
        prev_months = get_previous_year_months(current_months)
        two_years_months = get_two_years_ago_months(current_months)
    else:
        current_months = [target_month.isoformat()]
        prev_months = [get_previous_year_month(target_month).isoformat()]
        two_years_months = [date(target_month.year - 2, target_month.month, 1).isoformat()]

    # 当年実績データ取得（is_target=False または NULL）
    current_response = supabase.table("ecommerce_channel_sales").select(
        "channel, sales, buyers, is_target"
    ).in_("month", current_months).execute()
    # is_targetがFalseまたはNULLのデータを実績として扱う
    current_data = [r for r in current_response.data if not r.get("is_target")]

    # 目標データ取得（is_target=True）
    target_response = supabase.table("ecommerce_channel_sales").select(
        "channel, sales, buyers"
    ).in_("month", current_months).eq("is_target", True).execute()
    target_data = target_response.data

    # 前年データ取得（実績のみ）
    prev_response = supabase.table("ecommerce_channel_sales").select(
        "channel, sales, buyers, is_target"
    ).in_("month", prev_months).execute()
    prev_data = [r for r in prev_response.data if not r.get("is_target")]

    # 前々年データ取得（実績のみ）
    two_years_response = supabase.table("ecommerce_channel_sales").select(
        "channel, sales, buyers, is_target"
    ).in_("month", two_years_months).execute()
    two_years_data = [r for r in two_years_response.data if not r.get("is_target")]

    # チャネル別に集計
    def aggregate_by_channel(data: List[Dict]) -> Dict[str, Dict]:
        result = {ch: {"sales": Decimal("0"), "buyers": 0} for ch in CHANNELS}
        for row in data:
            ch = row["channel"]
            if ch in result:
                if row.get("sales"):
                    result[ch]["sales"] += Decimal(str(row["sales"]))
                if row.get("buyers"):
                    result[ch]["buyers"] += row["buyers"]
        return result

    current_agg = aggregate_by_channel(current_data)
    target_agg = aggregate_by_channel(target_data)
    prev_agg = aggregate_by_channel(prev_data)
    two_years_agg = aggregate_by_channel(two_years_data)

    # チャネル別データを構築
    channels = []
    total_sales = Decimal("0")
    total_sales_target = Decimal("0")
    total_sales_prev = Decimal("0")
    total_sales_two_years = Decimal("0")
    total_buyers = 0
    total_buyers_target = 0
    total_buyers_prev = 0
    total_buyers_two_years = 0

    for ch in CHANNELS:
        sales = current_agg[ch]["sales"]
        sales_target = target_agg[ch]["sales"]
        sales_prev = prev_agg[ch]["sales"]
        sales_two_years = two_years_agg[ch]["sales"]
        buyers = current_agg[ch]["buyers"]
        buyers_target = target_agg[ch]["buyers"]
        buyers_prev = prev_agg[ch]["buyers"]
        buyers_two_years = two_years_agg[ch]["buyers"]

        unit_price = safe_divide(float(sales), buyers) if sales and buyers else None
        unit_price_prev = safe_divide(float(sales_prev), buyers_prev) if sales_prev and buyers_prev else None
        unit_price_two_years = safe_divide(float(sales_two_years), buyers_two_years) if sales_two_years and buyers_two_years else None

        # 達成率を計算
        sales_achievement = calculate_achievement_rate(sales, sales_target)
        buyers_achievement = calculate_achievement_rate(Decimal(buyers), Decimal(buyers_target)) if buyers_target else None

        channels.append({
            "channel": ch,
            "sales": float(sales) if sales else None,
            "sales_target": float(sales_target) if sales_target else None,
            "sales_achievement_rate": sales_achievement,
            "sales_previous_year": float(sales_prev) if sales_prev else None,
            "sales_two_years_ago": float(sales_two_years) if sales_two_years else None,
            "sales_yoy": calculate_yoy_rate(sales, sales_prev) if sales and sales_prev else None,
            "sales_yoy_two_years": calculate_yoy_rate(sales, sales_two_years) if sales and sales_two_years else None,
            "buyers": buyers if buyers else None,
            "buyers_target": buyers_target if buyers_target else None,
            "buyers_achievement_rate": buyers_achievement,
            "buyers_previous_year": buyers_prev if buyers_prev else None,
            "buyers_two_years_ago": buyers_two_years if buyers_two_years else None,
            "buyers_yoy": calculate_yoy_rate(Decimal(buyers), Decimal(buyers_prev)) if buyers and buyers_prev else None,
            "buyers_yoy_two_years": calculate_yoy_rate(Decimal(buyers), Decimal(buyers_two_years)) if buyers and buyers_two_years else None,
            "unit_price": unit_price,
            "unit_price_previous_year": unit_price_prev,
            "unit_price_two_years_ago": unit_price_two_years,
            "unit_price_yoy": calculate_yoy_rate(Decimal(str(unit_price)), Decimal(str(unit_price_prev))) if unit_price and unit_price_prev else None,
            "unit_price_yoy_two_years": calculate_yoy_rate(Decimal(str(unit_price)), Decimal(str(unit_price_two_years))) if unit_price and unit_price_two_years else None,
        })

        total_sales += sales
        total_sales_target += sales_target
        total_sales_prev += sales_prev
        total_sales_two_years += sales_two_years
        total_buyers += buyers
        total_buyers_target += buyers_target
        total_buyers_prev += buyers_prev
        total_buyers_two_years += buyers_two_years

    # 合計データ
    total_unit_price = safe_divide(float(total_sales), total_buyers) if total_sales and total_buyers else None
    total_unit_price_prev = safe_divide(float(total_sales_prev), total_buyers_prev) if total_sales_prev and total_buyers_prev else None
    total_unit_price_two_years = safe_divide(float(total_sales_two_years), total_buyers_two_years) if total_sales_two_years and total_buyers_two_years else None

    # 合計の達成率
    total_sales_achievement = calculate_achievement_rate(total_sales, total_sales_target)
    total_buyers_achievement = calculate_achievement_rate(Decimal(total_buyers), Decimal(total_buyers_target)) if total_buyers_target else None

    totals = {
        "sales": float(total_sales) if total_sales else None,
        "sales_target": float(total_sales_target) if total_sales_target else None,
        "sales_achievement_rate": total_sales_achievement,
        "sales_previous_year": float(total_sales_prev) if total_sales_prev else None,
        "sales_two_years_ago": float(total_sales_two_years) if total_sales_two_years else None,
        "sales_yoy": calculate_yoy_rate(total_sales, total_sales_prev) if total_sales and total_sales_prev else None,
        "sales_yoy_two_years": calculate_yoy_rate(total_sales, total_sales_two_years) if total_sales and total_sales_two_years else None,
        "buyers": total_buyers if total_buyers else None,
        "buyers_target": total_buyers_target if total_buyers_target else None,
        "buyers_achievement_rate": total_buyers_achievement,
        "buyers_previous_year": total_buyers_prev if total_buyers_prev else None,
        "buyers_two_years_ago": total_buyers_two_years if total_buyers_two_years else None,
        "buyers_yoy": calculate_yoy_rate(Decimal(total_buyers), Decimal(total_buyers_prev)) if total_buyers and total_buyers_prev else None,
        "buyers_yoy_two_years": calculate_yoy_rate(Decimal(total_buyers), Decimal(total_buyers_two_years)) if total_buyers and total_buyers_two_years else None,
        "unit_price": total_unit_price,
        "unit_price_previous_year": total_unit_price_prev,
        "unit_price_two_years_ago": total_unit_price_two_years,
        "unit_price_yoy": calculate_yoy_rate(Decimal(str(total_unit_price)), Decimal(str(total_unit_price_prev))) if total_unit_price and total_unit_price_prev else None,
        "unit_price_yoy_two_years": calculate_yoy_rate(Decimal(str(total_unit_price)), Decimal(str(total_unit_price_two_years))) if total_unit_price and total_unit_price_two_years else None,
    }

    return {
        "period": target_month.isoformat(),
        "period_type": period_type,
        "fiscal_year": fiscal_year if is_cumulative else None,
        "channels": channels,
        "totals": totals,
    }


# =============================================================================
# 商品別実績取得
# =============================================================================

async def get_product_summary(
    supabase: Client,
    target_month: date,
    period_type: str = "monthly",
    limit: int = 20
) -> Dict[str, Any]:
    """
    商品別実績を取得

    Args:
        supabase: Supabaseクライアント
        target_month: 対象月
        period_type: 期間タイプ（monthly/cumulative）
        limit: 取得件数

    Returns:
        dict: 商品別実績データ
    """
    target_month = normalize_to_month_start(target_month)
    fiscal_year = get_fiscal_year(target_month)
    is_cumulative = period_type == "cumulative"

    # 対象月リストを生成
    if is_cumulative:
        current_months = get_cumulative_months(target_month)
        prev_months = get_previous_year_months(current_months)
        two_years_months = get_two_years_ago_months(current_months)
    else:
        current_months = [target_month.isoformat()]
        prev_months = [get_previous_year_month(target_month).isoformat()]
        two_years_months = [date(target_month.year - 2, target_month.month, 1).isoformat()]

    # 当年データ取得
    current_response = supabase.table("ecommerce_product_sales").select(
        "product_name, product_category, sales, quantity"
    ).in_("month", current_months).execute()
    current_data = current_response.data

    # 前年データ取得
    prev_response = supabase.table("ecommerce_product_sales").select(
        "product_name, product_category, sales, quantity"
    ).in_("month", prev_months).execute()
    prev_data = prev_response.data

    # 前々年データ取得
    two_years_response = supabase.table("ecommerce_product_sales").select(
        "product_name, product_category, sales, quantity"
    ).in_("month", two_years_months).execute()
    two_years_data = two_years_response.data

    # 商品別に集計
    def aggregate_by_product(data: List[Dict]) -> Dict[str, Dict]:
        result = {}
        for row in data:
            name = row["product_name"]
            if name not in result:
                result[name] = {
                    "category": row.get("product_category"),
                    "sales": Decimal("0"),
                    "quantity": 0
                }
            if row.get("sales"):
                result[name]["sales"] += Decimal(str(row["sales"]))
            if row.get("quantity"):
                result[name]["quantity"] += row["quantity"]
        return result

    current_agg = aggregate_by_product(current_data)
    prev_agg = aggregate_by_product(prev_data)
    two_years_agg = aggregate_by_product(two_years_data)

    # 売上高順でソート
    sorted_products = sorted(
        current_agg.items(),
        key=lambda x: x[1]["sales"],
        reverse=True
    )[:limit]

    # 商品別データを構築
    products = []
    total_sales = Decimal("0")
    total_sales_prev = Decimal("0")
    total_sales_two_years = Decimal("0")

    for name, data in sorted_products:
        sales = data["sales"]
        sales_prev = prev_agg.get(name, {}).get("sales", Decimal("0"))
        sales_two_years = two_years_agg.get(name, {}).get("sales", Decimal("0"))
        quantity = data["quantity"]
        quantity_prev = prev_agg.get(name, {}).get("quantity", 0)
        quantity_two_years = two_years_agg.get(name, {}).get("quantity", 0)

        products.append({
            "product_name": name,
            "product_category": data.get("category"),
            "sales": float(sales) if sales else None,
            "sales_previous_year": float(sales_prev) if sales_prev else None,
            "sales_two_years_ago": float(sales_two_years) if sales_two_years else None,
            "sales_yoy": calculate_yoy_rate(sales, sales_prev) if sales and sales_prev else None,
            "sales_yoy_two_years": calculate_yoy_rate(sales, sales_two_years) if sales and sales_two_years else None,
            "quantity": quantity if quantity else None,
            "quantity_previous_year": quantity_prev if quantity_prev else None,
            "quantity_two_years_ago": quantity_two_years if quantity_two_years else None,
        })

        total_sales += sales
        total_sales_prev += sales_prev
        total_sales_two_years += sales_two_years

    return {
        "period": target_month.isoformat(),
        "period_type": period_type,
        "fiscal_year": fiscal_year if is_cumulative else None,
        "products": products,
        "total_sales": float(total_sales) if total_sales else None,
        "total_sales_previous_year": float(total_sales_prev) if total_sales_prev else None,
        "total_sales_two_years_ago": float(total_sales_two_years) if total_sales_two_years else None,
    }


# =============================================================================
# 顧客別実績取得
# =============================================================================

async def get_customer_summary(
    supabase: Client,
    target_month: date,
    period_type: str = "monthly"
) -> Dict[str, Any]:
    """
    顧客別実績を取得（目標値・達成率を含む）

    Args:
        supabase: Supabaseクライアント
        target_month: 対象月
        period_type: 期間タイプ（monthly/cumulative）

    Returns:
        dict: 顧客別実績データ
    """
    target_month = normalize_to_month_start(target_month)
    fiscal_year = get_fiscal_year(target_month)
    is_cumulative = period_type == "cumulative"

    # 対象月リストを生成
    if is_cumulative:
        current_months = get_cumulative_months(target_month)
        prev_months = get_previous_year_months(current_months)
        two_years_months = get_two_years_ago_months(current_months)
    else:
        current_months = [target_month.isoformat()]
        prev_months = [get_previous_year_month(target_month).isoformat()]
        two_years_months = [date(target_month.year - 2, target_month.month, 1).isoformat()]

    # 当年実績データ取得（is_target=False または NULL）
    current_response = supabase.table("ecommerce_customer_stats").select(
        "new_customers, repeat_customers, total_customers, is_target"
    ).in_("month", current_months).execute()
    # is_targetがFalseまたはNULLのデータを実績として扱う
    current_data = [r for r in current_response.data if not r.get("is_target")]

    # 目標データ取得（is_target=True）
    target_response = supabase.table("ecommerce_customer_stats").select(
        "new_customers, repeat_customers, total_customers"
    ).in_("month", current_months).eq("is_target", True).execute()
    target_data = target_response.data

    # 前年データ取得（実績のみ）
    prev_response = supabase.table("ecommerce_customer_stats").select(
        "new_customers, repeat_customers, total_customers, is_target"
    ).in_("month", prev_months).execute()
    prev_data = [r for r in prev_response.data if not r.get("is_target")]

    # 前々年データ取得（実績のみ）
    two_years_response = supabase.table("ecommerce_customer_stats").select(
        "new_customers, repeat_customers, total_customers, is_target"
    ).in_("month", two_years_months).execute()
    two_years_data = [r for r in two_years_response.data if not r.get("is_target")]

    # 集計
    def sum_stats(data: List[Dict]) -> Dict:
        return {
            "new_customers": sum(r.get("new_customers", 0) or 0 for r in data),
            "repeat_customers": sum(r.get("repeat_customers", 0) or 0 for r in data),
            "total_customers": sum(r.get("total_customers", 0) or 0 for r in data),
        }

    current = sum_stats(current_data)
    target = sum_stats(target_data)
    prev = sum_stats(prev_data)
    two_years = sum_stats(two_years_data)

    # リピート率計算
    def calc_repeat_rate(repeat: int, total: int) -> Optional[float]:
        if total and total > 0:
            return round((repeat / total) * 100, 1)
        return None

    # 達成率計算（int用）
    def calc_int_achievement(actual: int, target_val: int) -> Optional[float]:
        if actual and target_val and target_val > 0:
            return round((actual / target_val) * 100, 1)
        return None

    data = {
        "new_customers": current["new_customers"] or None,
        "new_customers_target": target["new_customers"] or None,
        "new_customers_achievement_rate": calc_int_achievement(
            current["new_customers"], target["new_customers"]
        ),
        "new_customers_previous_year": prev["new_customers"] or None,
        "new_customers_two_years_ago": two_years["new_customers"] or None,
        "new_customers_yoy": calculate_yoy_rate(
            Decimal(current["new_customers"]), Decimal(prev["new_customers"])
        ) if current["new_customers"] and prev["new_customers"] else None,
        "new_customers_yoy_two_years": calculate_yoy_rate(
            Decimal(current["new_customers"]), Decimal(two_years["new_customers"])
        ) if current["new_customers"] and two_years["new_customers"] else None,
        "repeat_customers": current["repeat_customers"] or None,
        "repeat_customers_target": target["repeat_customers"] or None,
        "repeat_customers_achievement_rate": calc_int_achievement(
            current["repeat_customers"], target["repeat_customers"]
        ),
        "repeat_customers_previous_year": prev["repeat_customers"] or None,
        "repeat_customers_two_years_ago": two_years["repeat_customers"] or None,
        "repeat_customers_yoy": calculate_yoy_rate(
            Decimal(current["repeat_customers"]), Decimal(prev["repeat_customers"])
        ) if current["repeat_customers"] and prev["repeat_customers"] else None,
        "repeat_customers_yoy_two_years": calculate_yoy_rate(
            Decimal(current["repeat_customers"]), Decimal(two_years["repeat_customers"])
        ) if current["repeat_customers"] and two_years["repeat_customers"] else None,
        "total_customers": current["total_customers"] or None,
        "total_customers_target": target["total_customers"] or None,
        "total_customers_achievement_rate": calc_int_achievement(
            current["total_customers"], target["total_customers"]
        ),
        "total_customers_previous_year": prev["total_customers"] or None,
        "total_customers_two_years_ago": two_years["total_customers"] or None,
        "repeat_rate": calc_repeat_rate(current["repeat_customers"], current["total_customers"]),
        "repeat_rate_previous_year": calc_repeat_rate(prev["repeat_customers"], prev["total_customers"]),
    }

    return {
        "period": target_month.isoformat(),
        "period_type": period_type,
        "fiscal_year": fiscal_year if is_cumulative else None,
        "data": data,
    }


# =============================================================================
# HPアクセス数取得
# =============================================================================

async def get_website_stats(
    supabase: Client,
    target_month: date,
    period_type: str = "monthly"
) -> Dict[str, Any]:
    """
    HPアクセス数を取得

    Args:
        supabase: Supabaseクライアント
        target_month: 対象月
        period_type: 期間タイプ（monthly/cumulative）

    Returns:
        dict: HPアクセス数データ
    """
    target_month = normalize_to_month_start(target_month)
    fiscal_year = get_fiscal_year(target_month)
    is_cumulative = period_type == "cumulative"

    # 対象月リストを生成
    if is_cumulative:
        current_months = get_cumulative_months(target_month)
        prev_months = get_previous_year_months(current_months)
        two_years_months = get_two_years_ago_months(current_months)
    else:
        current_months = [target_month.isoformat()]
        prev_months = [get_previous_year_month(target_month).isoformat()]
        two_years_months = [date(target_month.year - 2, target_month.month, 1).isoformat()]

    # 当年データ取得
    current_response = supabase.table("ecommerce_website_stats").select(
        "page_views, unique_visitors, sessions"
    ).in_("month", current_months).execute()
    current_data = current_response.data

    # 前年データ取得
    prev_response = supabase.table("ecommerce_website_stats").select(
        "page_views, unique_visitors, sessions"
    ).in_("month", prev_months).execute()
    prev_data = prev_response.data

    # 前々年データ取得
    two_years_response = supabase.table("ecommerce_website_stats").select(
        "page_views, unique_visitors, sessions"
    ).in_("month", two_years_months).execute()
    two_years_data = two_years_response.data

    # 集計
    def sum_stats(data: List[Dict]) -> Dict:
        return {
            "page_views": sum(r.get("page_views", 0) or 0 for r in data),
            "unique_visitors": sum(r.get("unique_visitors", 0) or 0 for r in data),
            "sessions": sum(r.get("sessions", 0) or 0 for r in data),
        }

    current = sum_stats(current_data)
    prev = sum_stats(prev_data)
    two_years = sum_stats(two_years_data)

    data = {
        "page_views": current["page_views"] or None,
        "page_views_previous_year": prev["page_views"] or None,
        "page_views_two_years_ago": two_years["page_views"] or None,
        "page_views_yoy": calculate_yoy_rate(
            Decimal(current["page_views"]), Decimal(prev["page_views"])
        ) if current["page_views"] and prev["page_views"] else None,
        "page_views_yoy_two_years": calculate_yoy_rate(
            Decimal(current["page_views"]), Decimal(two_years["page_views"])
        ) if current["page_views"] and two_years["page_views"] else None,
        "unique_visitors": current["unique_visitors"] or None,
        "unique_visitors_previous_year": prev["unique_visitors"] or None,
        "unique_visitors_two_years_ago": two_years["unique_visitors"] or None,
        "unique_visitors_yoy": calculate_yoy_rate(
            Decimal(current["unique_visitors"]), Decimal(prev["unique_visitors"])
        ) if current["unique_visitors"] and prev["unique_visitors"] else None,
        "unique_visitors_yoy_two_years": calculate_yoy_rate(
            Decimal(current["unique_visitors"]), Decimal(two_years["unique_visitors"])
        ) if current["unique_visitors"] and two_years["unique_visitors"] else None,
        "sessions": current["sessions"] or None,
        "sessions_previous_year": prev["sessions"] or None,
        "sessions_two_years_ago": two_years["sessions"] or None,
        "sessions_yoy": calculate_yoy_rate(
            Decimal(current["sessions"]), Decimal(prev["sessions"])
        ) if current["sessions"] and prev["sessions"] else None,
        "sessions_yoy_two_years": calculate_yoy_rate(
            Decimal(current["sessions"]), Decimal(two_years["sessions"])
        ) if current["sessions"] and two_years["sessions"] else None,
    }

    return {
        "period": target_month.isoformat(),
        "period_type": period_type,
        "fiscal_year": fiscal_year if is_cumulative else None,
        "data": data,
    }


# =============================================================================
# 推移データ取得（グラフ用）
# =============================================================================

async def get_ecommerce_trend(
    supabase: Client,
    metric: str,
    fiscal_year: Optional[int] = None
) -> Dict[str, Any]:
    """
    推移データを取得（グラフ用）

    Args:
        supabase: Supabaseクライアント
        metric: 指標タイプ（channel_sales, product_sales, customers, website）
        fiscal_year: 会計年度（省略時は現在）

    Returns:
        dict: 推移データ
    """
    if fiscal_year is None:
        fiscal_year = get_fiscal_year(date.today())

    # 会計年度の月リストを生成（9月〜翌8月）
    months = []
    for i in range(12):
        m = 9 + i
        y = fiscal_year if m <= 12 else fiscal_year + 1
        if m > 12:
            m -= 12
        months.append(date(y, m, 1).isoformat())

    # 前年の月リスト
    prev_months = get_previous_year_months(months)

    month_labels = [m[:7] for m in months]  # YYYY-MM形式

    if metric == "channel_sales":
        # チャネル別売上推移（実績のみ、目標データを除外）
        current_response = supabase.table("ecommerce_channel_sales").select(
            "month, channel, sales, is_target"
        ).in_("month", months).execute()
        # is_targetがFalseまたはNULLのデータのみを実績として扱う
        current_actual = [r for r in current_response.data if not r.get("is_target")]

        prev_response = supabase.table("ecommerce_channel_sales").select(
            "month, channel, sales, is_target"
        ).in_("month", prev_months).execute()
        prev_actual = [r for r in prev_response.data if not r.get("is_target")]

        # チャネル別にデータを整形
        data = []
        for ch in CHANNELS:
            current_by_month = {r["month"]: r["sales"] for r in current_actual if r["channel"] == ch}
            prev_by_month = {r["month"]: r["sales"] for r in prev_actual if r["channel"] == ch}

            # values配列を生成（フロントエンド互換形式）
            values = []
            for i, m in enumerate(months):
                values.append(current_by_month.get(m))

            data.append({
                "name": ch,
                "values": values,
            })

    elif metric == "product_sales":
        # 商品別売上推移（上位10商品）
        current_response = supabase.table("ecommerce_product_sales").select(
            "month, product_name, sales"
        ).in_("month", months).execute()

        # 商品別合計を計算
        product_totals = {}
        for r in current_response.data:
            name = r["product_name"]
            if name not in product_totals:
                product_totals[name] = 0
            if r.get("sales"):
                product_totals[name] += r["sales"]

        # 上位10商品
        top_products = sorted(product_totals.items(), key=lambda x: x[1], reverse=True)[:10]
        top_names = [p[0] for p in top_products]

        prev_response = supabase.table("ecommerce_product_sales").select(
            "month, product_name, sales"
        ).in_("month", prev_months).in_("product_name", top_names).execute()

        data = []
        for name in top_names:
            current_by_month = {r["month"]: r["sales"] for r in current_response.data if r["product_name"] == name}

            # values配列を生成（フロントエンド互換形式）
            values = []
            for i, m in enumerate(months):
                values.append(current_by_month.get(m))

            data.append({
                "name": name,
                "values": values,
            })

    elif metric == "customers":
        # 顧客数推移（実績のみ、目標データを除外）
        current_response = supabase.table("ecommerce_customer_stats").select(
            "month, new_customers, repeat_customers, total_customers, is_target"
        ).in_("month", months).execute()
        # is_targetがFalseまたはNULLのデータのみを実績として扱う
        current_actual = [r for r in current_response.data if not r.get("is_target")]

        current_by_month = {r["month"]: r for r in current_actual}

        # 表示名マッピング
        stat_labels = {
            "new_customers": "新規顧客",
            "repeat_customers": "リピーター",
            "total_customers": "合計",
        }

        data = []
        for stat_type in ["new_customers", "repeat_customers", "total_customers"]:
            # values配列を生成（フロントエンド互換形式）
            values = []
            for i, m in enumerate(months):
                curr = current_by_month.get(m, {})
                values.append(curr.get(stat_type))
            data.append({
                "name": stat_labels[stat_type],
                "values": values,
            })

    elif metric == "website":
        # HPアクセス数推移
        current_response = supabase.table("ecommerce_website_stats").select(
            "month, page_views, unique_visitors, sessions"
        ).in_("month", months).execute()

        current_by_month = {r["month"]: r for r in current_response.data}

        # 表示名マッピング
        stat_labels = {
            "page_views": "PV",
            "unique_visitors": "UU",
            "sessions": "セッション",
        }

        data = []
        for stat_type in ["page_views", "unique_visitors", "sessions"]:
            # values配列を生成（フロントエンド互換形式）
            values = []
            for i, m in enumerate(months):
                curr = current_by_month.get(m, {})
                values.append(curr.get(stat_type))
            data.append({
                "name": stat_labels[stat_type],
                "values": values,
            })

    else:
        raise ValueError(f"不正なmetric: {metric}")

    return {
        "fiscal_year": fiscal_year,
        "metric": metric,
        "months": month_labels,
        "data": data,
    }


# =============================================================================
# データインポート
# =============================================================================

async def import_channel_data(
    supabase: Client,
    month: date,
    records: List[Dict]
) -> Dict[str, int]:
    """
    チャネル別データをインポート

    Args:
        supabase: Supabaseクライアント
        month: 対象月
        records: インポートデータ

    Returns:
        dict: 処理結果（created, updated）
    """
    month = normalize_to_month_start(month)
    created = 0
    updated = 0

    for record in records:
        channel = record.get("チャネル") or record.get("channel")
        if not channel or channel not in CHANNELS:
            continue

        data = {
            "month": month.isoformat(),
            "channel": channel,
            "sales": record.get("売上高") or record.get("sales"),
            "buyers": record.get("購入者数") or record.get("buyers"),
            "is_target": False,  # 実績データとして登録
        }

        # 既存の実績データをチェックして更新または挿入
        existing = supabase.table("ecommerce_channel_sales").select("id").eq(
            "month", month.isoformat()
        ).eq("channel", channel).eq("is_target", False).execute()

        if existing.data:
            response = supabase.table("ecommerce_channel_sales").update(data).eq(
                "id", existing.data[0]["id"]
            ).execute()
        else:
            response = supabase.table("ecommerce_channel_sales").insert(data).execute()

        if response.data:
            updated += 1

    return {"created": created, "updated": updated}


async def import_product_data(
    supabase: Client,
    month: date,
    records: List[Dict]
) -> Dict[str, int]:
    """
    商品別データをインポート

    Args:
        supabase: Supabaseクライアント
        month: 対象月
        records: インポートデータ

    Returns:
        dict: 処理結果（created, updated）
    """
    month = normalize_to_month_start(month)
    created = 0
    updated = 0

    for record in records:
        product_name = record.get("商品名") or record.get("product_name")
        if not product_name:
            continue

        data = {
            "month": month.isoformat(),
            "product_name": product_name,
            "product_category": record.get("商品カテゴリ") or record.get("product_category"),
            "sales": record.get("売上高") or record.get("sales"),
            "quantity": record.get("販売数量") or record.get("quantity"),
        }

        # Upsert
        response = supabase.table("ecommerce_product_sales").upsert(
            data,
            on_conflict="month,product_name"
        ).execute()

        if response.data:
            updated += 1

    return {"created": created, "updated": updated}


async def import_customer_data(
    supabase: Client,
    month: date,
    records: List[Dict]
) -> Dict[str, int]:
    """
    顧客別データをインポート

    Args:
        supabase: Supabaseクライアント
        month: 対象月
        records: インポートデータ

    Returns:
        dict: 処理結果（created, updated）
    """
    month = normalize_to_month_start(month)

    # 顧客データは月に1レコード
    record = records[0] if records else {}

    new_customers = record.get("新規顧客数") or record.get("new_customers") or 0
    repeat_customers = record.get("リピーター数") or record.get("repeat_customers") or 0
    total_customers = new_customers + repeat_customers

    data = {
        "month": month.isoformat(),
        "new_customers": new_customers,
        "repeat_customers": repeat_customers,
        "total_customers": total_customers,
        "is_target": False,  # 実績データとして登録
    }

    # 既存の実績データをチェックして更新または挿入
    existing = supabase.table("ecommerce_customer_stats").select("id").eq(
        "month", month.isoformat()
    ).eq("is_target", False).execute()

    if existing.data:
        supabase.table("ecommerce_customer_stats").update(data).eq(
            "id", existing.data[0]["id"]
        ).execute()
    else:
        supabase.table("ecommerce_customer_stats").insert(data).execute()

    return {"created": 0, "updated": 1}


async def import_website_data(
    supabase: Client,
    month: date,
    records: List[Dict]
) -> Dict[str, int]:
    """
    HPアクセスデータをインポート

    Args:
        supabase: Supabaseクライアント
        month: 対象月
        records: インポートデータ

    Returns:
        dict: 処理結果（created, updated）
    """
    month = normalize_to_month_start(month)

    # HPデータは月に1レコード
    record = records[0] if records else {}

    data = {
        "month": month.isoformat(),
        "page_views": record.get("ページビュー数") or record.get("page_views"),
        "unique_visitors": record.get("ユニークビジター数") or record.get("unique_visitors"),
        "sessions": record.get("セッション数") or record.get("sessions"),
    }

    # 既存のデータをチェックして更新または挿入
    existing = supabase.table("ecommerce_website_stats").select("id").eq(
        "month", month.isoformat()
    ).execute()

    if existing.data:
        supabase.table("ecommerce_website_stats").update(data).eq(
            "id", existing.data[0]["id"]
        ).execute()
    else:
        supabase.table("ecommerce_website_stats").insert(data).execute()

    return {"created": 0, "updated": 1}
