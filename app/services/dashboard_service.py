"""
ダッシュボードサービス

経営層向けダッシュボードのデータ取得と計算を行うサービス。
財務データ、店舗・通販データを統合し、前年比・予算比を計算して返す。
"""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional, Dict, Any

from supabase import Client

from app.schemas.dashboard import (
    MetricWithComparison,
    CompanySummary,
    DepartmentPerformance,
    CashFlowData,
    ManagementIndicators,
    ChartDataPoint,
    AlertItem,
    DashboardResponse,
)
from app.services.period_utils import (
    get_fiscal_year,
    get_period_range,
    get_previous_year_range,
    get_two_years_ago_range,
    get_current_period_defaults,
)
from app.services import complaint_service
from app.services.cache_service import cached, cache


# =============================================================================
# メイン関数
# =============================================================================

@cached(prefix="dashboard", ttl=300)  # 5分キャッシュ
async def get_dashboard_data(
    supabase: Client,
    period_type: str = "monthly",
    year: Optional[int] = None,
    month: Optional[int] = None,
    quarter: Optional[int] = None,
) -> DashboardResponse:
    """
    ダッシュボードの全データを取得する

    Args:
        supabase: Supabaseクライアント
        period_type: 期間タイプ（monthly/quarterly/yearly）
        year: 年度（省略時は現在の年度）
        month: 月（monthlyの場合）
        quarter: 四半期（quarterlyの場合）

    Returns:
        DashboardResponse: ダッシュボード全体のレスポンス
    """
    # デフォルト値の設定
    if year is None or month is None or quarter is None:
        default_year, default_month, default_quarter = get_current_period_defaults()
        year = year or default_year
        month = month or default_month
        quarter = quarter or default_quarter

    # 期間を計算
    start_date, end_date, period_label = get_period_range(
        period_type, year, month, quarter
    )

    # 各セクションのデータを取得
    company_summary = await get_company_summary(
        supabase, start_date, end_date, period_type, year, period_label
    )
    department_performance = await get_department_performance(
        supabase, start_date, end_date
    )
    cash_flow = await get_cash_flow(supabase, start_date, end_date)
    management_indicators = await get_management_indicators(
        supabase, start_date, end_date
    )
    chart_data = await get_chart_data(supabase, months=12)
    alerts = await get_alerts(supabase, start_date, end_date)

    # クレームサマリーを取得
    complaint_summary = await complaint_service.get_dashboard_summary(supabase, start_date)

    return DashboardResponse(
        company_summary=company_summary,
        department_performance=department_performance,
        cash_flow=cash_flow,
        management_indicators=management_indicators,
        chart_data=chart_data,
        alerts=alerts,
        complaint_summary=complaint_summary,
    )


# =============================================================================
# 全社サマリー
# =============================================================================

async def get_company_summary(
    supabase: Client,
    start_date: date,
    end_date: date,
    period_type: str,
    fiscal_year: int,
    period_label: str,
) -> CompanySummary:
    """
    全社サマリーを取得する

    Args:
        supabase: Supabaseクライアント
        start_date: 期間開始日
        end_date: 期間終了日
        period_type: 期間タイプ
        fiscal_year: 会計年度
        period_label: 期間ラベル

    Returns:
        CompanySummary: 全社サマリー
    """
    # 今期のデータを取得
    current_data = await _get_aggregated_financial_data(
        supabase, start_date, end_date, is_target=False
    )

    # 前年同期間のデータを取得
    prev_start, prev_end = get_previous_year_range(start_date, end_date)
    prev_data = await _get_aggregated_financial_data(
        supabase, prev_start, prev_end, is_target=False
    )

    # 目標データを取得
    target_data = await _get_aggregated_financial_data(
        supabase, start_date, end_date, is_target=True
    )

    # 各指標を計算
    sales_total = _create_metric(
        current_data.get("sales_total"),
        prev_data.get("sales_total"),
        target_data.get("sales_total"),
    )

    gross_profit = _create_metric(
        current_data.get("gross_profit"),
        prev_data.get("gross_profit"),
        target_data.get("gross_profit"),
    )

    # 粗利率はポイント差で計算
    gross_profit_rate = _create_rate_metric(
        current_data.get("gross_profit_rate"),
        prev_data.get("gross_profit_rate"),
    )

    operating_profit = _create_metric(
        current_data.get("operating_profit"),
        prev_data.get("operating_profit"),
        target_data.get("operating_profit"),
    )

    return CompanySummary(
        period=period_label,
        period_type=period_type,
        fiscal_year=fiscal_year,
        sales_total=sales_total,
        gross_profit=gross_profit,
        gross_profit_rate=gross_profit_rate,
        operating_profit=operating_profit,
    )


# =============================================================================
# 部門別実績
# =============================================================================

async def get_department_performance(
    supabase: Client,
    start_date: date,
    end_date: date,
) -> List[DepartmentPerformance]:
    """
    部門別実績を取得する

    Args:
        supabase: Supabaseクライアント
        start_date: 期間開始日
        end_date: 期間終了日

    Returns:
        List[DepartmentPerformance]: 部門別実績リスト
    """
    departments = []

    # 前年同期間
    prev_start, prev_end = get_previous_year_range(start_date, end_date)

    # 店舗部門
    store_current = await _get_aggregated_financial_data(
        supabase, start_date, end_date, is_target=False
    )
    store_prev = await _get_aggregated_financial_data(
        supabase, prev_start, prev_end, is_target=False
    )
    store_target = await _get_aggregated_financial_data(
        supabase, start_date, end_date, is_target=True
    )

    store_sales = store_current.get("sales_store")
    store_sales_prev = store_prev.get("sales_store")
    store_sales_target = store_target.get("sales_store")

    departments.append(DepartmentPerformance(
        department="店舗",
        sales=store_sales,
        sales_yoy_rate=_calculate_yoy_rate(store_sales, store_sales_prev),
        profit=None,  # 部門別利益は財務データに含まれない場合がある
        achievement_rate=_calculate_achievement_rate(store_sales, store_sales_target),
        budget_rate=_calculate_achievement_rate(store_sales, store_sales_target),
    ))

    # 通販部門
    online_sales = store_current.get("sales_online")
    online_sales_prev = store_prev.get("sales_online")
    online_sales_target = store_target.get("sales_online")

    departments.append(DepartmentPerformance(
        department="通販",
        sales=online_sales,
        sales_yoy_rate=_calculate_yoy_rate(online_sales, online_sales_prev),
        profit=None,
        achievement_rate=_calculate_achievement_rate(online_sales, online_sales_target),
        budget_rate=_calculate_achievement_rate(online_sales, online_sales_target),
    ))

    return departments


# =============================================================================
# キャッシュフロー
# =============================================================================

async def get_cash_flow(
    supabase: Client,
    start_date: date,
    end_date: date,
) -> CashFlowData:
    """
    キャッシュフローデータを取得する

    Args:
        supabase: Supabaseクライアント
        start_date: 期間開始日
        end_date: 期間終了日

    Returns:
        CashFlowData: キャッシュフローデータ
    """
    # 今期
    current_data = await _get_aggregated_financial_data(
        supabase, start_date, end_date, is_target=False
    )

    # 前年同期間
    prev_start, prev_end = get_previous_year_range(start_date, end_date)
    prev_data = await _get_aggregated_financial_data(
        supabase, prev_start, prev_end, is_target=False
    )

    # 前々年同期間
    prev2_start, prev2_end = get_two_years_ago_range(start_date, end_date)
    prev2_data = await _get_aggregated_financial_data(
        supabase, prev2_start, prev2_end, is_target=False
    )

    return CashFlowData(
        cf_operating=current_data.get("cf_operating"),
        cf_operating_prev=prev_data.get("cf_operating"),
        cf_operating_prev2=prev2_data.get("cf_operating"),
        cf_investing=current_data.get("cf_investing"),
        cf_investing_prev=prev_data.get("cf_investing"),
        cf_investing_prev2=prev2_data.get("cf_investing"),
        cf_financing=current_data.get("cf_financing"),
        cf_financing_prev=prev_data.get("cf_financing"),
        cf_financing_prev2=prev2_data.get("cf_financing"),
        cf_free=current_data.get("cf_free"),
        cf_free_prev=prev_data.get("cf_free"),
        cf_free_prev2=prev2_data.get("cf_free"),
    )


# =============================================================================
# 経営指標
# =============================================================================

async def get_management_indicators(
    supabase: Client,
    start_date: date,
    end_date: date,
) -> ManagementIndicators:
    """
    経営指標を取得する

    Args:
        supabase: Supabaseクライアント
        start_date: 期間開始日
        end_date: 期間終了日

    Returns:
        ManagementIndicators: 経営指標
    """
    # 今期のデータ
    current_data = await _get_aggregated_financial_data(
        supabase, start_date, end_date, is_target=False
    )

    # 前年同期間のデータ
    prev_start, prev_end = get_previous_year_range(start_date, end_date)
    prev_data = await _get_aggregated_financial_data(
        supabase, prev_start, prev_end, is_target=False
    )

    # 原価率（売上原価 / 売上高）を計算
    cost_rate_current = _calculate_cost_rate(
        current_data.get("cost_of_sales"),
        current_data.get("sales_total")
    )
    cost_rate_prev = _calculate_cost_rate(
        prev_data.get("cost_of_sales"),
        prev_data.get("sales_total")
    )

    # 人件費率
    labor_rate_current = current_data.get("labor_cost_rate")
    labor_rate_prev = prev_data.get("labor_cost_rate")

    # 客数・客単価はkpi_valuesから取得
    customer_data = await _get_customer_metrics(supabase, start_date, end_date)
    customer_data_prev = await _get_customer_metrics(supabase, prev_start, prev_end)

    return ManagementIndicators(
        cost_rate=_create_rate_metric(cost_rate_current, cost_rate_prev),
        labor_cost_rate=_create_rate_metric(labor_rate_current, labor_rate_prev),
        customer_count=_create_metric(
            customer_data.get("customer_count"),
            customer_data_prev.get("customer_count"),
            None,
        ),
        customer_unit_price=_create_metric(
            customer_data.get("customer_unit_price"),
            customer_data_prev.get("customer_unit_price"),
            None,
        ),
    )


# =============================================================================
# グラフデータ
# =============================================================================

async def get_chart_data(
    supabase: Client,
    months: int = 12,
) -> List[ChartDataPoint]:
    """
    推移グラフ用データを取得する

    Args:
        supabase: Supabaseクライアント
        months: 取得する月数

    Returns:
        List[ChartDataPoint]: グラフデータリスト
    """
    chart_data = []

    # 現在の月から過去N ヶ月のデータを取得
    today = date.today()
    current_month = date(today.year, today.month, 1)

    for i in range(months - 1, -1, -1):
        # i ヶ月前の月を計算
        month_offset = current_month.month - i - 1
        year = current_month.year + (month_offset // 12)
        month = (month_offset % 12) + 1
        if month <= 0:
            month += 12
            year -= 1

        target_month = date(year, month, 1)

        # 月次の財務データを取得
        response = supabase.table("financial_data").select(
            "sales_total, operating_profit"
        ).eq(
            "month", target_month.isoformat()
        ).eq(
            "is_target", False
        ).execute()

        # 目標データを取得
        target_response = supabase.table("financial_data").select(
            "sales_total, operating_profit"
        ).eq(
            "month", target_month.isoformat()
        ).eq(
            "is_target", True
        ).execute()

        sales = None
        operating_profit = None
        sales_target = None
        operating_profit_target = None

        if response.data:
            row = response.data[0]
            sales = Decimal(str(row["sales_total"])) if row.get("sales_total") else None
            operating_profit = Decimal(str(row["operating_profit"])) if row.get("operating_profit") else None

        if target_response.data:
            row = target_response.data[0]
            sales_target = Decimal(str(row["sales_total"])) if row.get("sales_total") else None
            operating_profit_target = Decimal(str(row["operating_profit"])) if row.get("operating_profit") else None

        chart_data.append(ChartDataPoint(
            month=target_month.strftime("%Y-%m"),
            sales=sales,
            operating_profit=operating_profit,
            sales_target=sales_target,
            operating_profit_target=operating_profit_target,
        ))

    return chart_data


# =============================================================================
# アラート
# =============================================================================

async def get_alerts(
    supabase: Client,
    start_date: date,
    end_date: date,
) -> List[AlertItem]:
    """
    アラート項目を取得する

    予算未達の項目を抽出し、達成率に応じてwarning/criticalを設定する。

    Args:
        supabase: Supabaseクライアント
        start_date: 期間開始日
        end_date: 期間終了日

    Returns:
        List[AlertItem]: アラート項目リスト
    """
    alerts = []

    # 実績と目標を取得
    current_data = await _get_aggregated_financial_data(
        supabase, start_date, end_date, is_target=False
    )
    target_data = await _get_aggregated_financial_data(
        supabase, start_date, end_date, is_target=True
    )

    # チェック対象項目
    check_items = [
        ("売上", "全社売上高", "sales_total"),
        ("利益", "粗利益", "gross_profit"),
        ("利益", "営業利益", "operating_profit"),
        ("部門", "店舗売上", "sales_store"),
        ("部門", "通販売上", "sales_online"),
    ]

    for category, name, key in check_items:
        actual = current_data.get(key)
        target = target_data.get(key)

        if actual is not None and target is not None and target > 0:
            achievement_rate = _calculate_achievement_rate(actual, target)
            if achievement_rate is not None and achievement_rate < 100:
                severity = "critical" if achievement_rate < 80 else "warning"
                alerts.append(AlertItem(
                    category=category,
                    name=name,
                    achievement_rate=achievement_rate,
                    actual=actual,
                    target=target,
                    severity=severity,
                ))

    return alerts


# =============================================================================
# ヘルパー関数
# =============================================================================

async def _get_aggregated_financial_data(
    supabase: Client,
    start_date: date,
    end_date: date,
    is_target: bool = False,
) -> Dict[str, Optional[Decimal]]:
    """
    期間内の財務データを集計する

    Args:
        supabase: Supabaseクライアント
        start_date: 期間開始日
        end_date: 期間終了日
        is_target: 目標データかどうか

    Returns:
        Dict[str, Optional[Decimal]]: 集計された財務データ
    """
    response = supabase.table("financial_data").select(
        "sales_total, sales_store, sales_online, "
        "cost_of_sales, gross_profit, gross_profit_rate, "
        "labor_cost, labor_cost_rate, "
        "operating_profit, operating_profit_rate, "
        "cf_operating, cf_investing, cf_financing, cf_free"
    ).gte(
        "month", start_date.isoformat()
    ).lte(
        "month", end_date.isoformat()
    ).eq(
        "is_target", is_target
    ).execute()

    if not response.data:
        return {}

    # 複数月の場合は合計を計算（率は最新月を使用）
    result: Dict[str, Optional[Decimal]] = {}
    sum_fields = [
        "sales_total", "sales_store", "sales_online",
        "cost_of_sales", "gross_profit", "labor_cost", "operating_profit",
        "cf_operating", "cf_investing", "cf_financing", "cf_free"
    ]
    rate_fields = ["gross_profit_rate", "labor_cost_rate", "operating_profit_rate"]

    for field in sum_fields:
        total = Decimal("0")
        has_value = False
        for row in response.data:
            if row.get(field) is not None:
                total += Decimal(str(row[field]))
                has_value = True
        result[field] = total if has_value else None

    # 率は期間内の加重平均または最新月の値を使用
    # ここでは売上高ベースで再計算
    if result.get("sales_total") and result["sales_total"] > 0:
        if result.get("gross_profit"):
            result["gross_profit_rate"] = (
                result["gross_profit"] / result["sales_total"] * 100
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if result.get("labor_cost"):
            result["labor_cost_rate"] = (
                result["labor_cost"] / result["sales_total"] * 100
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if result.get("operating_profit"):
            result["operating_profit_rate"] = (
                result["operating_profit"] / result["sales_total"] * 100
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return result


async def _get_customer_metrics(
    supabase: Client,
    start_date: date,
    end_date: date,
) -> Dict[str, Optional[Decimal]]:
    """
    客数・客単価を kpi_values から取得する

    Args:
        supabase: Supabaseクライアント
        start_date: 期間開始日
        end_date: 期間終了日

    Returns:
        Dict[str, Optional[Decimal]]: 客数・客単価
    """
    # 店舗部門のIDを取得
    dept_response = supabase.table("departments").select(
        "id"
    ).eq("slug", "store").execute()

    if not dept_response.data:
        return {}

    department_id = dept_response.data[0]["id"]

    # KPI定義を取得（客数と売上高）
    kpi_response = supabase.table("kpi_definitions").select(
        "id, name"
    ).eq(
        "department_id", department_id
    ).in_(
        "name", ["客数", "売上高"]
    ).execute()

    if not kpi_response.data:
        return {}

    kpi_ids = {row["name"]: row["id"] for row in kpi_response.data}

    # セグメントIDを取得
    segment_response = supabase.table("segments").select(
        "id"
    ).eq("department_id", department_id).execute()

    if not segment_response.data:
        return {}

    segment_ids = [seg["id"] for seg in segment_response.data]

    # KPI値を取得
    values_response = supabase.table("kpi_values").select(
        "kpi_id, value"
    ).in_(
        "segment_id", segment_ids
    ).gte(
        "date", start_date.isoformat()
    ).lte(
        "date", end_date.isoformat()
    ).eq(
        "is_target", False
    ).execute()

    if not values_response.data:
        return {}

    # 集計
    customer_count = Decimal("0")
    sales_total = Decimal("0")

    customer_kpi_id = kpi_ids.get("客数")
    sales_kpi_id = kpi_ids.get("売上高")

    for row in values_response.data:
        if row.get("value") is not None:
            if row["kpi_id"] == customer_kpi_id:
                customer_count += Decimal(str(row["value"]))
            elif row["kpi_id"] == sales_kpi_id:
                sales_total += Decimal(str(row["value"]))

    result = {
        "customer_count": customer_count if customer_count > 0 else None,
    }

    # 客単価を計算
    if customer_count > 0 and sales_total > 0:
        result["customer_unit_price"] = (
            sales_total / customer_count
        ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    else:
        result["customer_unit_price"] = None

    return result


def _create_metric(
    current: Optional[Decimal],
    previous: Optional[Decimal],
    target: Optional[Decimal],
) -> MetricWithComparison:
    """MetricWithComparison を作成する"""
    return MetricWithComparison(
        value=current,
        previous_year=previous,
        yoy_rate=_calculate_yoy_rate(current, previous),
        yoy_diff=_calculate_diff(current, previous),
        target=target,
        achievement_rate=_calculate_achievement_rate(current, target),
    )


def _create_rate_metric(
    current: Optional[Decimal],
    previous: Optional[Decimal],
) -> MetricWithComparison:
    """率指標用の MetricWithComparison を作成する（ポイント差で比較）"""
    return MetricWithComparison(
        value=current,
        previous_year=previous,
        yoy_rate=None,  # 率の前年比は使用しない
        yoy_diff=_calculate_diff(current, previous),  # ポイント差
        target=None,
        achievement_rate=None,
    )


def _calculate_yoy_rate(
    current: Optional[Decimal],
    previous: Optional[Decimal],
) -> Optional[Decimal]:
    """前年比（変化率）を計算する（%）

    変化率 = (今期 - 前期) / 前期 × 100
    """
    if current is None or previous is None or previous == 0:
        return None
    result = ((current - previous) / previous) * 100
    return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _calculate_diff(
    current: Optional[Decimal],
    previous: Optional[Decimal],
) -> Optional[Decimal]:
    """前年差を計算する"""
    if current is None or previous is None:
        return None
    return current - previous


def _calculate_achievement_rate(
    actual: Optional[Decimal],
    target: Optional[Decimal],
) -> Optional[Decimal]:
    """達成率を計算する（%）"""
    if actual is None or target is None or target == 0:
        return None
    result = (actual / target) * 100
    return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _calculate_cost_rate(
    cost: Optional[Decimal],
    sales: Optional[Decimal],
) -> Optional[Decimal]:
    """原価率を計算する（%）"""
    if cost is None or sales is None or sales == 0:
        return None
    result = (cost / sales) * 100
    return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
