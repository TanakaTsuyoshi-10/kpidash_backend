"""
KPIデータ取得サービスモジュール

部門別・店舗別のKPIデータ取得とリアルタイム計算を行う。
"""
from datetime import date
from decimal import Decimal
from typing import Optional, List, Dict, Any

from supabase import Client

from app.services.metrics import (
    get_fiscal_year,
    get_fiscal_year_range,
    get_months_in_fiscal_year,
    get_previous_year_month,
    normalize_to_month_start,
    calculate_ytd,
    calculate_achievement_rate,
    calculate_yoy_rate,
    calculate_customer_unit_price,
    get_alert_level,
)


# 商品グループとして扱うカテゴリ
PRODUCT_GROUP_CATEGORY = "商品グループ"


# =============================================================================
# 部門サマリー取得
# =============================================================================

async def get_department_summary(
    supabase: Client,
    department_id: str,
    target_month: date,
    include_ytd: bool = True
) -> Dict[str, Any]:
    """
    部門全体のKPIサマリーを取得する

    各KPIについて、単月実績・目標、累計実績・目標、達成率、前年比を計算する。

    Args:
        supabase: Supabaseクライアント
        department_id: 部門ID
        target_month: 対象月
        include_ytd: 累計を含めるかどうか

    Returns:
        dict: 部門KPIサマリー
    """
    target_month = normalize_to_month_start(target_month)
    fiscal_year = get_fiscal_year(target_month)
    previous_month = get_previous_year_month(target_month)

    # 部門情報を取得
    dept_response = supabase.table("departments").select(
        "id, name, slug"
    ).eq("id", department_id).single().execute()
    department = dept_response.data

    # KPI定義を取得
    kpi_response = supabase.table("kpi_definitions").select(
        "id, name, unit, category, is_calculated, formula, display_order"
    ).eq("department_id", department_id).eq(
        "is_visible", True
    ).order("display_order").execute()
    kpi_definitions = kpi_response.data

    # セグメント（店舗）を取得
    segment_response = supabase.table("segments").select(
        "id"
    ).eq("department_id", department_id).execute()
    segment_ids = [seg["id"] for seg in segment_response.data]

    if not segment_ids:
        return {
            "department": {
                "id": department["id"],
                "name": department["name"],
                "slug": department["slug"],
            },
            "period": target_month.isoformat(),
            "fiscal_year": fiscal_year,
            "kpis": [],
        }

    # 年度の開始日を取得
    fiscal_start, _ = get_fiscal_year_range(fiscal_year)

    # KPI値を取得（年度開始から対象月まで）
    values_response = supabase.table("kpi_values").select(
        "kpi_id, segment_id, date, value, is_target"
    ).in_("segment_id", segment_ids).gte(
        "date", fiscal_start.isoformat()
    ).lte("date", target_month.isoformat()).execute()
    all_values = values_response.data

    # 前年同月のデータを取得
    prev_year_response = supabase.table("kpi_values").select(
        "kpi_id, segment_id, date, value, is_target"
    ).in_("segment_id", segment_ids).eq(
        "date", previous_month.isoformat()
    ).eq("is_target", False).execute()
    prev_year_values = prev_year_response.data

    # KPIごとに集計
    kpis_result = []
    for kpi_def in kpi_definitions:
        kpi_id = kpi_def["id"]

        # このKPIの値をフィルタ
        kpi_values = [v for v in all_values if v["kpi_id"] == kpi_id]
        kpi_prev_values = [v for v in prev_year_values if v["kpi_id"] == kpi_id]

        # 単月集計（全店舗合計）
        monthly_actual = sum(
            Decimal(str(v["value"]))
            for v in kpi_values
            if v["date"] == target_month.isoformat() and not v["is_target"]
        )
        monthly_target = sum(
            Decimal(str(v["value"]))
            for v in kpi_values
            if v["date"] == target_month.isoformat() and v["is_target"]
        )

        # 累計集計
        ytd_actual = Decimal("0")
        ytd_target = Decimal("0")
        if include_ytd:
            ytd_actual = calculate_ytd(kpi_values, target_month, is_target=False)
            ytd_target = calculate_ytd(kpi_values, target_month, is_target=True)

        # 前年同月（全店舗合計）
        prev_year_actual = sum(
            Decimal(str(v["value"])) for v in kpi_prev_values
        )

        # 達成率・前年比計算
        achievement_rate = None
        if ytd_target > 0:
            achievement_rate = calculate_achievement_rate(ytd_actual, ytd_target)

        yoy_rate = None
        if prev_year_actual > 0:
            yoy_rate = calculate_yoy_rate(monthly_actual, prev_year_actual)

        # アラートレベル判定
        alert_level = get_alert_level(achievement_rate)

        kpis_result.append({
            "name": kpi_def["name"],
            "unit": kpi_def["unit"],
            "category": kpi_def["category"],
            "actual": float(monthly_actual) if monthly_actual else None,
            "target": float(monthly_target) if monthly_target else None,
            "ytd_actual": float(ytd_actual) if include_ytd else None,
            "ytd_target": float(ytd_target) if include_ytd else None,
            "achievement_rate": float(achievement_rate) if achievement_rate else None,
            "yoy_rate": float(yoy_rate) if yoy_rate else None,
            "alert_level": alert_level,
        })

    return {
        "department": {
            "id": department["id"],
            "name": department["name"],
            "slug": department["slug"],
        },
        "period": target_month.isoformat(),
        "fiscal_year": fiscal_year,
        "kpis": kpis_result,
    }


# =============================================================================
# 店舗別詳細取得
# =============================================================================

async def get_segment_detail(
    supabase: Client,
    segment_id: str,
    target_month: date
) -> Dict[str, Any]:
    """
    店舗・拠点別の詳細KPIを取得する

    Args:
        supabase: Supabaseクライアント
        segment_id: セグメント（店舗）ID
        target_month: 対象月

    Returns:
        dict: 店舗詳細KPI
    """
    target_month = normalize_to_month_start(target_month)
    fiscal_year = get_fiscal_year(target_month)
    fiscal_start, _ = get_fiscal_year_range(fiscal_year)

    # セグメント情報を取得
    segment_response = supabase.table("segments").select(
        "id, code, name, department_id"
    ).eq("id", segment_id).single().execute()
    segment = segment_response.data

    department_id = segment["department_id"]

    # KPI定義を取得
    kpi_response = supabase.table("kpi_definitions").select(
        "id, name, unit, category, is_calculated, formula, display_order"
    ).eq("department_id", department_id).eq(
        "is_visible", True
    ).order("display_order").execute()
    kpi_definitions = kpi_response.data

    # KPI値を取得
    values_response = supabase.table("kpi_values").select(
        "kpi_id, date, value, is_target"
    ).eq("segment_id", segment_id).gte(
        "date", fiscal_start.isoformat()
    ).lte("date", target_month.isoformat()).execute()
    all_values = values_response.data

    # KPIごとに集計
    kpis_result = []
    sales_actual = Decimal("0")
    customers_actual = 0

    for kpi_def in kpi_definitions:
        kpi_id = kpi_def["id"]
        kpi_values = [v for v in all_values if v["kpi_id"] == kpi_id]

        # 単月
        monthly_actual = sum(
            Decimal(str(v["value"]))
            for v in kpi_values
            if v["date"] == target_month.isoformat() and not v["is_target"]
        )
        monthly_target = sum(
            Decimal(str(v["value"]))
            for v in kpi_values
            if v["date"] == target_month.isoformat() and v["is_target"]
        )

        # 累計
        ytd_actual = calculate_ytd(kpi_values, target_month, is_target=False)
        ytd_target = calculate_ytd(kpi_values, target_month, is_target=True)

        # 達成率
        achievement_rate = None
        if ytd_target > 0:
            achievement_rate = calculate_achievement_rate(ytd_actual, ytd_target)

        alert_level = get_alert_level(achievement_rate)

        # 客単価計算用に売上・客数を保持
        if kpi_def["name"] == "売上高":
            sales_actual = monthly_actual
        elif kpi_def["name"] == "客数":
            customers_actual = int(monthly_actual)

        kpis_result.append({
            "name": kpi_def["name"],
            "unit": kpi_def["unit"],
            "category": kpi_def["category"],
            "actual": float(monthly_actual) if monthly_actual else None,
            "target": float(monthly_target) if monthly_target else None,
            "ytd_actual": float(ytd_actual),
            "ytd_target": float(ytd_target),
            "achievement_rate": float(achievement_rate) if achievement_rate else None,
            "alert_level": alert_level,
        })

    # 計算指標
    customer_unit_price = calculate_customer_unit_price(sales_actual, customers_actual)

    return {
        "segment": {
            "id": segment["id"],
            "name": segment["name"],
            "code": segment["code"],
        },
        "period": target_month.isoformat(),
        "fiscal_year": fiscal_year,
        "kpis": kpis_result,
        "calculated_metrics": {
            "customer_unit_price": float(customer_unit_price) if customer_unit_price else None,
            "items_per_customer": None,  # 販売個数データがある場合に計算
        },
    }


# =============================================================================
# 時系列データ取得
# =============================================================================

async def get_comparison_data(
    supabase: Client,
    department_id: str,
    kpi_name: str,
    fiscal_year: Optional[int] = None
) -> Dict[str, Any]:
    """
    時系列比較データを取得する（グラフ用）

    会計年度（9月〜翌年8月）ベースでデータを返す。

    Args:
        supabase: Supabaseクライアント
        department_id: 部門ID
        kpi_name: KPI名（例: "売上高"）
        fiscal_year: 会計年度（省略時は現在の会計年度）

    Returns:
        dict: グラフ用データ
    """
    # 会計年度を決定
    if fiscal_year is None:
        fiscal_year = get_fiscal_year(date.today())

    # 会計年度の期間を取得（9月〜翌年8月）
    start_date, end_date = get_fiscal_year_range(fiscal_year)

    # KPI定義を取得
    kpi_response = supabase.table("kpi_definitions").select(
        "id"
    ).eq("department_id", department_id).eq("name", kpi_name).single().execute()
    kpi_id = kpi_response.data["id"]

    # セグメントを取得
    segment_response = supabase.table("segments").select(
        "id"
    ).eq("department_id", department_id).execute()
    segment_ids = [seg["id"] for seg in segment_response.data]

    # 今年度のKPI値を取得
    # 月初日ベースなので、end_dateを月初日に変換
    end_month = date(end_date.year, end_date.month, 1)
    values_response = supabase.table("kpi_values").select(
        "date, value, is_target"
    ).eq("kpi_id", kpi_id).in_(
        "segment_id", segment_ids
    ).gte("date", start_date.isoformat()).lte(
        "date", end_month.isoformat()
    ).execute()
    all_values = values_response.data

    # 前年度データを取得
    prev_start = date(start_date.year - 1, start_date.month, 1)
    prev_end = date(end_month.year - 1, end_month.month, 1)
    prev_values_response = supabase.table("kpi_values").select(
        "date, value, is_target"
    ).eq("kpi_id", kpi_id).in_(
        "segment_id", segment_ids
    ).gte("date", prev_start.isoformat()).lte(
        "date", prev_end.isoformat()
    ).eq("is_target", False).execute()
    prev_values = prev_values_response.data

    # 会計年度順で月リストを生成（9月→10月→...→7月→8月）
    month_list = get_months_in_fiscal_year(fiscal_year)

    # 月別に集計
    labels = []
    actual_data = []
    target_data = []
    previous_year_data = []

    for month_date in month_list:
        month_str = month_date.isoformat()
        label = month_date.strftime("%Y-%m")
        labels.append(label)

        # 今年の実績
        month_actual = sum(
            Decimal(str(v["value"]))
            for v in all_values
            if v["date"] == month_str and not v["is_target"]
        )
        actual_data.append(float(month_actual))

        # 今年の目標
        month_target = sum(
            Decimal(str(v["value"]))
            for v in all_values
            if v["date"] == month_str and v["is_target"]
        )
        target_data.append(float(month_target))

        # 前年の実績
        prev_month_str = date(month_date.year - 1, month_date.month, 1).isoformat()
        prev_actual = sum(
            Decimal(str(v["value"]))
            for v in prev_values
            if v["date"] == prev_month_str
        )
        previous_year_data.append(float(prev_actual))

    return {
        "kpi_name": kpi_name,
        "fiscal_year": fiscal_year,
        "labels": labels,
        "datasets": {
            "actual": actual_data,
            "target": target_data,
            "previous_year": previous_year_data,
        },
    }


# =============================================================================
# ランキング取得
# =============================================================================

async def get_ranking(
    supabase: Client,
    department_id: str,
    target_month: date,
    kpi_name: str = "売上高",
    limit: int = 10
) -> List[Dict[str, Any]]:
    """
    店舗ランキングを取得する

    Args:
        supabase: Supabaseクライアント
        department_id: 部門ID
        target_month: 対象月
        kpi_name: KPI名
        limit: 上位件数

    Returns:
        List[dict]: ランキングデータ
    """
    target_month = normalize_to_month_start(target_month)
    fiscal_year = get_fiscal_year(target_month)
    fiscal_start, _ = get_fiscal_year_range(fiscal_year)

    # KPI定義を取得
    kpi_response = supabase.table("kpi_definitions").select(
        "id"
    ).eq("department_id", department_id).eq("name", kpi_name).single().execute()
    kpi_id = kpi_response.data["id"]

    # セグメント情報を取得
    segment_response = supabase.table("segments").select(
        "id, code, name"
    ).eq("department_id", department_id).execute()
    segments = {seg["id"]: seg for seg in segment_response.data}

    # KPI値を取得
    values_response = supabase.table("kpi_values").select(
        "segment_id, date, value, is_target"
    ).eq("kpi_id", kpi_id).in_(
        "segment_id", list(segments.keys())
    ).gte("date", fiscal_start.isoformat()).lte(
        "date", target_month.isoformat()
    ).execute()
    all_values = values_response.data

    # セグメントごとに累計を計算
    segment_totals = []
    for segment_id, segment in segments.items():
        segment_values = [v for v in all_values if v["segment_id"] == segment_id]

        ytd_actual = calculate_ytd(segment_values, target_month, is_target=False)
        ytd_target = calculate_ytd(segment_values, target_month, is_target=True)

        achievement_rate = None
        if ytd_target > 0:
            achievement_rate = calculate_achievement_rate(ytd_actual, ytd_target)

        segment_totals.append({
            "segment_id": segment_id,
            "segment_name": segment["name"],
            "segment_code": segment["code"],
            "value": float(ytd_actual),
            "achievement_rate": float(achievement_rate) if achievement_rate else None,
        })

    # ソートしてランキング付け
    segment_totals.sort(key=lambda x: x["value"], reverse=True)

    result = []
    for i, item in enumerate(segment_totals[:limit], 1):
        result.append({
            "rank": i,
            "segment_id": item["segment_id"],
            "segment_name": item["segment_name"],
            "segment_code": item["segment_code"],
            "value": item["value"],
            "achievement_rate": item["achievement_rate"],
        })

    return result


# =============================================================================
# アラート取得
# =============================================================================

async def get_alerts(
    supabase: Client,
    department_id: Optional[str] = None,
    target_month: Optional[date] = None
) -> List[Dict[str, Any]]:
    """
    未達アラート一覧を取得する

    Args:
        supabase: Supabaseクライアント
        department_id: 部門ID（省略時は全部門）
        target_month: 対象月（省略時は当月）

    Returns:
        List[dict]: アラート一覧
    """
    if target_month is None:
        target_month = date.today()
    target_month = normalize_to_month_start(target_month)
    fiscal_year = get_fiscal_year(target_month)
    fiscal_start, _ = get_fiscal_year_range(fiscal_year)

    # 部門を取得
    if department_id:
        dept_response = supabase.table("departments").select(
            "id, name, slug"
        ).eq("id", department_id).execute()
    else:
        dept_response = supabase.table("departments").select(
            "id, name, slug"
        ).execute()
    departments = dept_response.data

    alerts = []

    for dept in departments:
        dept_id = dept["id"]

        # KPI定義を取得
        kpi_response = supabase.table("kpi_definitions").select(
            "id, name, unit"
        ).eq("department_id", dept_id).eq("is_visible", True).execute()
        kpi_definitions = kpi_response.data

        # セグメントを取得
        segment_response = supabase.table("segments").select(
            "id, name"
        ).eq("department_id", dept_id).execute()
        segments = {seg["id"]: seg for seg in segment_response.data}

        if not segments:
            continue

        # KPI値を取得
        values_response = supabase.table("kpi_values").select(
            "kpi_id, segment_id, date, value, is_target"
        ).in_("segment_id", list(segments.keys())).gte(
            "date", fiscal_start.isoformat()
        ).lte("date", target_month.isoformat()).execute()
        all_values = values_response.data

        # KPIごと×セグメントごとにチェック
        for kpi_def in kpi_definitions:
            kpi_id = kpi_def["id"]

            for segment_id, segment in segments.items():
                segment_values = [
                    v for v in all_values
                    if v["kpi_id"] == kpi_id and v["segment_id"] == segment_id
                ]

                ytd_actual = calculate_ytd(segment_values, target_month, is_target=False)
                ytd_target = calculate_ytd(segment_values, target_month, is_target=True)

                if ytd_target > 0:
                    achievement_rate = calculate_achievement_rate(ytd_actual, ytd_target)
                    alert_level = get_alert_level(achievement_rate)

                    if alert_level in ("warning", "critical"):
                        alerts.append({
                            "department_name": dept["name"],
                            "segment_name": segment["name"],
                            "kpi_name": kpi_def["name"],
                            "achievement_rate": float(achievement_rate),
                            "alert_level": alert_level,
                            "ytd_actual": float(ytd_actual),
                            "ytd_target": float(ytd_target),
                        })

    # アラートレベル順（critical優先）、達成率昇順でソート
    alerts.sort(key=lambda x: (
        0 if x["alert_level"] == "critical" else 1,
        x["achievement_rate"]
    ))

    return alerts


# =============================================================================
# 商品マトリックス取得（一括取得用）
# =============================================================================

async def get_product_matrix(
    supabase: Client,
    department_id: str,
    target_month: date,
    period_type: str = "monthly"
) -> Dict[str, Any]:
    """
    店舗×商品グループのマトリックスデータを一括取得する

    1回のAPIコールで全店舗の商品グループ別売上データを取得する。
    前年同月データと前年比も含める。
    累計モードでは9月〜対象月の累計と前々年データも含める。

    Args:
        supabase: Supabaseクライアント
        department_id: 部門ID
        target_month: 対象月
        period_type: 期間タイプ（monthly: 単月, cumulative: 累計）

    Returns:
        dict: 商品マトリックスデータ
    """
    target_month = normalize_to_month_start(target_month)
    fiscal_year = get_fiscal_year(target_month)
    previous_month = get_previous_year_month(target_month)

    # 累計モードの場合、対象月のリストを生成
    is_cumulative = period_type == "cumulative"

    # 商品グループのKPI定義を取得
    kpi_response = supabase.table("kpi_definitions").select(
        "id, name, display_order"
    ).eq("department_id", department_id).eq(
        "category", PRODUCT_GROUP_CATEGORY
    ).eq("is_visible", True).order("display_order").execute()
    product_kpis = kpi_response.data

    if not product_kpis:
        return {
            "period": target_month.isoformat(),
            "fiscal_year": fiscal_year,
            "period_type": period_type,
            "product_groups": [],
            "stores": [],
            "totals": {},
        }

    product_groups = [kpi["name"] for kpi in product_kpis]
    kpi_ids = [kpi["id"] for kpi in product_kpis]
    kpi_id_to_name = {kpi["id"]: kpi["name"] for kpi in product_kpis}

    # セグメント（店舗）を取得
    segment_response = supabase.table("segments").select(
        "id, code, name"
    ).eq("department_id", department_id).order("code").execute()
    segments = segment_response.data

    if not segments:
        return {
            "period": target_month.isoformat(),
            "fiscal_year": fiscal_year,
            "period_type": period_type,
            "product_groups": product_groups,
            "stores": [],
            "totals": {},
        }

    segment_ids = [seg["id"] for seg in segments]

    # 累計モードの場合：9月〜対象月の範囲を取得
    if is_cumulative:
        # 会計年度開始月（9月）
        fiscal_start = date(fiscal_year, 9, 1)
        # 対象月のリストを生成
        current_months = []
        prev_months = []
        two_years_ago_months = []

        current_date = fiscal_start
        while current_date <= target_month:
            current_months.append(current_date.isoformat())
            prev_months.append(get_previous_year_month(current_date).isoformat())
            two_years_ago_months.append(date(
                current_date.year - 2, current_date.month, 1
            ).isoformat())
            if current_date.month == 12:
                current_date = date(current_date.year + 1, 1, 1)
            else:
                current_date = date(current_date.year, current_date.month + 1, 1)

        # 当年度累計のKPI値を一括取得
        current_values_response = supabase.table("kpi_values").select(
            "kpi_id, segment_id, value, date"
        ).in_("kpi_id", kpi_ids).in_(
            "segment_id", segment_ids
        ).in_("date", current_months).eq("is_target", False).execute()
        current_values = current_values_response.data

        # 前年同期累計のKPI値を一括取得
        prev_values_response = supabase.table("kpi_values").select(
            "kpi_id, segment_id, value, date"
        ).in_("kpi_id", kpi_ids).in_(
            "segment_id", segment_ids
        ).in_("date", prev_months).eq("is_target", False).execute()
        prev_values = prev_values_response.data

        # 前々年同期累計のKPI値を一括取得
        two_years_ago_response = supabase.table("kpi_values").select(
            "kpi_id, segment_id, value, date"
        ).in_("kpi_id", kpi_ids).in_(
            "segment_id", segment_ids
        ).in_("date", two_years_ago_months).eq("is_target", False).execute()
        two_years_ago_values = two_years_ago_response.data
    else:
        # 単月モード：従来通り
        # 当月のKPI値を一括取得
        current_values_response = supabase.table("kpi_values").select(
            "kpi_id, segment_id, value"
        ).in_("kpi_id", kpi_ids).in_(
            "segment_id", segment_ids
        ).eq("date", target_month.isoformat()).eq("is_target", False).execute()
        current_values = current_values_response.data

        # 前年同月のKPI値を一括取得
        prev_values_response = supabase.table("kpi_values").select(
            "kpi_id, segment_id, value"
        ).in_("kpi_id", kpi_ids).in_(
            "segment_id", segment_ids
        ).eq("date", previous_month.isoformat()).eq("is_target", False).execute()
        prev_values = prev_values_response.data

        two_years_ago_values = []

    # 店舗×KPI のマッピングを作成（累計モードでは複数月を合計）
    # current_map[segment_id][kpi_id] = value
    current_map: Dict[str, Dict[str, Decimal]] = {}
    for v in current_values:
        seg_id = v["segment_id"]
        kpi_id = v["kpi_id"]
        if seg_id not in current_map:
            current_map[seg_id] = {}
        if kpi_id not in current_map[seg_id]:
            current_map[seg_id][kpi_id] = Decimal("0")
        current_map[seg_id][kpi_id] += Decimal(str(v["value"]))

    # prev_map[segment_id][kpi_id] = value
    prev_map: Dict[str, Dict[str, Decimal]] = {}
    for v in prev_values:
        seg_id = v["segment_id"]
        kpi_id = v["kpi_id"]
        if seg_id not in prev_map:
            prev_map[seg_id] = {}
        if kpi_id not in prev_map[seg_id]:
            prev_map[seg_id][kpi_id] = Decimal("0")
        prev_map[seg_id][kpi_id] += Decimal(str(v["value"]))

    # two_years_ago_map[segment_id][kpi_id] = value（累計モードのみ）
    two_years_ago_map: Dict[str, Dict[str, Decimal]] = {}
    for v in two_years_ago_values:
        seg_id = v["segment_id"]
        kpi_id = v["kpi_id"]
        if seg_id not in two_years_ago_map:
            two_years_ago_map[seg_id] = {}
        if kpi_id not in two_years_ago_map[seg_id]:
            two_years_ago_map[seg_id][kpi_id] = Decimal("0")
        two_years_ago_map[seg_id][kpi_id] += Decimal(str(v["value"]))

    # 店舗ごとのデータを構築
    stores_data = []
    totals: Dict[str, Dict[str, Decimal]] = {
        name: {
            "actual": Decimal("0"),
            "previous_year": Decimal("0"),
            "two_years_ago": Decimal("0")
        }
        for name in product_groups
    }

    for segment in segments:
        seg_id = segment["id"]
        seg_current = current_map.get(seg_id, {})
        seg_prev = prev_map.get(seg_id, {})
        seg_two_years = two_years_ago_map.get(seg_id, {})

        products = {}
        store_total = Decimal("0")
        store_total_prev = Decimal("0")
        store_total_two_years = Decimal("0")

        for kpi in product_kpis:
            kpi_id = kpi["id"]
            kpi_name = kpi["name"]

            actual = seg_current.get(kpi_id, Decimal("0"))
            prev_year = seg_prev.get(kpi_id)
            two_years = seg_two_years.get(kpi_id) if is_cumulative else None

            # 前年比計算
            yoy_rate = None
            if prev_year and prev_year > 0:
                yoy_rate = calculate_yoy_rate(actual, prev_year)

            # 前々年比計算（累計モードのみ）
            yoy_rate_two_years = None
            if is_cumulative and two_years and two_years > 0:
                yoy_rate_two_years = calculate_yoy_rate(actual, two_years)

            products[kpi_name] = {
                "actual": float(actual) if actual else None,
                "previous_year": float(prev_year) if prev_year else None,
                "yoy_rate": float(yoy_rate) if yoy_rate else None,
                "two_years_ago": float(two_years) if two_years else None,
                "yoy_rate_two_years": float(yoy_rate_two_years) if yoy_rate_two_years else None,
            }

            store_total += actual
            if prev_year:
                store_total_prev += prev_year
            if two_years:
                store_total_two_years += two_years

            # 合計に加算
            totals[kpi_name]["actual"] += actual
            if prev_year:
                totals[kpi_name]["previous_year"] += prev_year
            if two_years:
                totals[kpi_name]["two_years_ago"] += two_years

        store_data = {
            "segment_id": seg_id,
            "segment_code": segment["code"],
            "segment_name": segment["name"],
            "products": products,
            "total": float(store_total),
        }

        # 累計モードの場合は前年・前々年合計も追加
        if is_cumulative:
            store_data["total_previous_year"] = float(store_total_prev) if store_total_prev else None
            store_data["total_two_years_ago"] = float(store_total_two_years) if store_total_two_years else None

        stores_data.append(store_data)

    # 合計の前年比・前々年比を計算
    totals_result = {}
    for name in product_groups:
        actual = totals[name]["actual"]
        prev_year = totals[name]["previous_year"]
        two_years = totals[name]["two_years_ago"]

        yoy_rate = None
        if prev_year > 0:
            yoy_rate = calculate_yoy_rate(actual, prev_year)

        yoy_rate_two_years = None
        if is_cumulative and two_years > 0:
            yoy_rate_two_years = calculate_yoy_rate(actual, two_years)

        totals_result[name] = {
            "actual": float(actual) if actual else None,
            "previous_year": float(prev_year) if prev_year > 0 else None,
            "yoy_rate": float(yoy_rate) if yoy_rate else None,
            "two_years_ago": float(two_years) if is_cumulative and two_years > 0 else None,
            "yoy_rate_two_years": float(yoy_rate_two_years) if yoy_rate_two_years else None,
        }

    return {
        "period": target_month.isoformat(),
        "fiscal_year": fiscal_year,
        "period_type": period_type,
        "product_groups": product_groups,
        "stores": stores_data,
        "totals": totals_result,
    }


# =============================================================================
# 商品別月次推移取得（グラフ用）
# =============================================================================

async def get_product_trend(
    supabase: Client,
    department_id: str,
    product_group: str,
    fiscal_year: Optional[int] = None
) -> Dict[str, Any]:
    """
    商品グループ別の月次推移データを取得する

    グラフ表示用に、指定した商品グループの月次推移データを取得する。
    全店舗合計と店舗別データの両方を返す。
    会計年度（9月〜翌年8月）ベースでデータを返す。

    Args:
        supabase: Supabaseクライアント
        department_id: 部門ID
        product_group: 商品グループ名（例: "ぎょうざ"）
        fiscal_year: 会計年度（省略時は現在の会計年度）

    Returns:
        dict: 月次推移データ
    """
    # 会計年度を決定
    if fiscal_year is None:
        fiscal_year = get_fiscal_year(date.today())

    # 会計年度の期間を取得（9月〜翌年8月）
    start_date, end_date = get_fiscal_year_range(fiscal_year)
    end_month = date(end_date.year, end_date.month, 1)

    # 商品グループのKPI定義を取得
    kpi_response = supabase.table("kpi_definitions").select(
        "id, name"
    ).eq("department_id", department_id).eq(
        "category", PRODUCT_GROUP_CATEGORY
    ).eq("name", product_group).single().execute()

    if not kpi_response.data:
        return {
            "product_group": product_group,
            "fiscal_year": fiscal_year,
            "months": [],
            "summary": {"actual": [], "previous_year": [], "total": 0},
            "stores": [],
        }

    kpi_id = kpi_response.data["id"]

    # セグメント（店舗）を取得
    segment_response = supabase.table("segments").select(
        "id, code, name"
    ).eq("department_id", department_id).order("code").execute()
    segments = segment_response.data

    if not segments:
        return {
            "product_group": product_group,
            "fiscal_year": fiscal_year,
            "months": [],
            "summary": {"actual": [], "previous_year": [], "total": 0},
            "stores": [],
        }

    segment_ids = [seg["id"] for seg in segments]

    # 当年度のKPI値を一括取得
    current_values_response = supabase.table("kpi_values").select(
        "segment_id, date, value"
    ).eq("kpi_id", kpi_id).in_(
        "segment_id", segment_ids
    ).gte("date", start_date.isoformat()).lte(
        "date", end_month.isoformat()
    ).eq("is_target", False).execute()
    current_values = current_values_response.data

    # 前年度のKPI値を一括取得
    prev_start = date(start_date.year - 1, start_date.month, 1)
    prev_end = date(end_month.year - 1, end_month.month, 1)
    prev_values_response = supabase.table("kpi_values").select(
        "segment_id, date, value"
    ).eq("kpi_id", kpi_id).in_(
        "segment_id", segment_ids
    ).gte("date", prev_start.isoformat()).lte(
        "date", prev_end.isoformat()
    ).eq("is_target", False).execute()
    prev_values = prev_values_response.data

    # 会計年度順で月リストを生成（9月→10月→...→7月→8月）
    month_list = get_months_in_fiscal_year(fiscal_year)
    month_labels = [m.strftime("%Y-%m") for m in month_list]

    # データをマッピング
    # current_map[segment_id][YYYY-MM] = value
    current_map: Dict[str, Dict[str, Decimal]] = {}
    for v in current_values:
        seg_id = v["segment_id"]
        month_key = v["date"][:7]  # "YYYY-MM"
        if seg_id not in current_map:
            current_map[seg_id] = {}
        current_map[seg_id][month_key] = Decimal(str(v["value"]))

    # prev_map[segment_id][YYYY-MM] = value (前年のキーで格納)
    prev_map: Dict[str, Dict[str, Decimal]] = {}
    for v in prev_values:
        seg_id = v["segment_id"]
        # 前年の日付を当年に変換してキーにする
        prev_date = date.fromisoformat(v["date"])
        current_year_month = date(prev_date.year + 1, prev_date.month, 1).strftime("%Y-%m")
        if seg_id not in prev_map:
            prev_map[seg_id] = {}
        prev_map[seg_id][current_year_month] = Decimal(str(v["value"]))

    # 店舗別データを構築
    stores_data = []
    summary_actual = {m: Decimal("0") for m in month_labels}
    summary_prev = {m: Decimal("0") for m in month_labels}

    for segment in segments:
        seg_id = segment["id"]
        seg_current = current_map.get(seg_id, {})
        seg_prev = prev_map.get(seg_id, {})

        monthly_data = []
        store_total = Decimal("0")

        for month in month_labels:
            actual = seg_current.get(month, Decimal("0"))
            prev_year = seg_prev.get(month)

            monthly_data.append({
                "month": month,
                "actual": float(actual) if actual else None,
                "previous_year": float(prev_year) if prev_year else None,
            })

            store_total += actual
            summary_actual[month] += actual
            if prev_year:
                summary_prev[month] += prev_year

        stores_data.append({
            "segment_id": seg_id,
            "segment_code": segment["code"],
            "segment_name": segment["name"],
            "data": monthly_data,
            "total": float(store_total),
        })

    # サマリーデータを構築
    summary = {
        "actual": [float(summary_actual[m]) for m in month_labels],
        "previous_year": [float(summary_prev[m]) for m in month_labels],
        "total": float(sum(summary_actual.values())),
        "total_previous_year": float(sum(summary_prev.values())),
    }

    # 前年比を計算
    if summary["total_previous_year"] > 0:
        yoy_rate = calculate_yoy_rate(
            Decimal(str(summary["total"])),
            Decimal(str(summary["total_previous_year"]))
        )
        summary["yoy_rate"] = float(yoy_rate) if yoy_rate else None
    else:
        summary["yoy_rate"] = None

    return {
        "product_group": product_group,
        "fiscal_year": fiscal_year,
        "months": month_labels,
        "summary": summary,
        "stores": stores_data,
    }


# =============================================================================
# 店舗詳細取得
# =============================================================================

async def get_store_detail(
    supabase: Client,
    segment_id: str,
    target_month: date
) -> Dict[str, Any]:
    """
    店舗の詳細データを取得する

    店舗全体のサマリー（売上・客数・客単価）と商品グループ別の詳細を返す。

    Args:
        supabase: Supabaseクライアント
        segment_id: 店舗ID
        target_month: 対象月

    Returns:
        dict: 店舗詳細データ
    """
    target_month = normalize_to_month_start(target_month)
    previous_month = get_previous_year_month(target_month)

    # 店舗情報を取得
    segment_response = supabase.table("segments").select(
        "id, code, name, department_id"
    ).eq("id", segment_id).single().execute()

    if not segment_response.data:
        return None

    segment = segment_response.data
    department_id = segment["department_id"]

    # 商品グループのKPI定義を取得
    product_kpis_response = supabase.table("kpi_definitions").select(
        "id, name"
    ).eq("department_id", department_id).eq(
        "category", PRODUCT_GROUP_CATEGORY
    ).eq("is_visible", True).order("display_order").execute()
    product_kpis = product_kpis_response.data

    # 全体KPI（売上高、客数）を取得
    overall_kpis_response = supabase.table("kpi_definitions").select(
        "id, name"
    ).eq("department_id", department_id).eq(
        "category", "全体"
    ).in_("name", ["売上高", "客数"]).execute()
    overall_kpis = {k["name"]: k["id"] for k in overall_kpis_response.data}

    # 当月の商品グループ別データを取得
    product_kpi_ids = [k["id"] for k in product_kpis]
    all_kpi_ids = product_kpi_ids + list(overall_kpis.values())

    current_values_response = supabase.table("kpi_values").select(
        "kpi_id, value"
    ).eq("segment_id", segment_id).in_(
        "kpi_id", all_kpi_ids
    ).eq("date", target_month.isoformat()).eq("is_target", False).execute()
    current_values = {v["kpi_id"]: float(v["value"]) for v in current_values_response.data}

    # 前年同月のデータを取得
    prev_values_response = supabase.table("kpi_values").select(
        "kpi_id, value"
    ).eq("segment_id", segment_id).in_(
        "kpi_id", all_kpi_ids
    ).eq("date", previous_month.isoformat()).eq("is_target", False).execute()
    prev_values = {v["kpi_id"]: float(v["value"]) for v in prev_values_response.data}

    # 全体サマリーを計算
    sales_kpi_id = overall_kpis.get("売上高")
    customers_kpi_id = overall_kpis.get("客数")

    total_sales = current_values.get(sales_kpi_id)
    total_sales_prev = prev_values.get(sales_kpi_id)
    total_customers = current_values.get(customers_kpi_id)
    total_customers_prev = prev_values.get(customers_kpi_id)

    # 前年比計算（変化率: (今期-前期)/前期 × 100）
    def calc_yoy(current: Optional[float], previous: Optional[float]) -> Optional[float]:
        if current is not None and previous and previous > 0:
            return round(((current - previous) / previous) * 100, 1)
        return None

    # 客単価計算
    def calc_unit_price(sales: Optional[float], customers: Optional[float]) -> Optional[float]:
        if sales is not None and customers and customers > 0:
            return round(sales / customers)
        return None

    avg_unit_price = calc_unit_price(total_sales, total_customers)
    avg_unit_price_prev = calc_unit_price(total_sales_prev, total_customers_prev)

    # 商品グループ別データを構築
    products = []
    for kpi in product_kpis:
        kpi_id = kpi["id"]
        kpi_name = kpi["name"]

        sales = current_values.get(kpi_id)
        sales_prev = prev_values.get(kpi_id)

        # 商品グループ別客単価を計算（商品グループ売上 ÷ 店舗全体客数）
        # これは「1人あたりの当該商品グループ購入額」を意味する
        group_unit_price = calc_unit_price(sales, total_customers)
        group_unit_price_prev = calc_unit_price(sales_prev, total_customers_prev)

        products.append({
            "product_group": kpi_name,
            "sales": sales,
            "sales_previous_year": sales_prev,
            "sales_yoy": calc_yoy(sales, sales_prev),
            # 商品グループ別の客数データは存在しないためNone
            "customers": None,
            "customers_previous_year": None,
            "customers_yoy": None,
            # 客単価は店舗全体客数を使用して計算
            "unit_price": group_unit_price,
            "unit_price_previous_year": group_unit_price_prev,
            "unit_price_yoy": calc_yoy(group_unit_price, group_unit_price_prev),
        })

    # 個別商品販売データを取得（product_salesテーブルから）
    product_items = []
    try:
        # 当月の期間を計算
        if target_month.month == 12:
            next_month = date(target_month.year + 1, 1, 1)
        else:
            next_month = date(target_month.year, target_month.month + 1, 1)

        # 前年同月の期間
        if previous_month.month == 12:
            prev_next_month = date(previous_month.year + 1, 1, 1)
        else:
            prev_next_month = date(previous_month.year, previous_month.month + 1, 1)

        # 当月の個別商品データを取得
        current_items_response = supabase.table("product_sales").select(
            "product_code, product_name, product_category_name, quantity, sales_with_tax"
        ).eq("segment_id", segment_id).gte(
            "sale_date", target_month.isoformat()
        ).lt("sale_date", next_month.isoformat()).execute()

        # 前年同月の個別商品データを取得
        prev_items_response = supabase.table("product_sales").select(
            "product_code, product_name, product_category_name, quantity, sales_with_tax"
        ).eq("segment_id", segment_id).gte(
            "sale_date", previous_month.isoformat()
        ).lt("sale_date", prev_next_month.isoformat()).execute()

        # 当月データを商品コード別に集計
        current_items_map: Dict[str, Dict[str, Any]] = {}
        for item in current_items_response.data:
            code = item["product_code"]
            if code not in current_items_map:
                current_items_map[code] = {
                    "product_code": code,
                    "product_name": item["product_name"],
                    "product_category": item.get("product_category_name"),
                    "quantity": 0,
                    "sales": 0,
                }
            current_items_map[code]["quantity"] += float(item["quantity"] or 0)
            current_items_map[code]["sales"] += float(item["sales_with_tax"] or 0)

        # 前年データを商品コード別に集計
        prev_items_map: Dict[str, Dict[str, float]] = {}
        for item in prev_items_response.data:
            code = item["product_code"]
            if code not in prev_items_map:
                prev_items_map[code] = {"quantity": 0, "sales": 0}
            prev_items_map[code]["quantity"] += float(item["quantity"] or 0)
            prev_items_map[code]["sales"] += float(item["sales_with_tax"] or 0)

        # 商品アイテムリストを構築
        for code, current_data in current_items_map.items():
            prev_data = prev_items_map.get(code, {})
            quantity_prev = prev_data.get("quantity")
            sales_prev = prev_data.get("sales")

            product_items.append({
                "product_code": current_data["product_code"],
                "product_name": current_data["product_name"],
                "product_category": current_data["product_category"],
                "quantity": current_data["quantity"],
                "quantity_previous_year": quantity_prev,
                "quantity_yoy": calc_yoy(current_data["quantity"], quantity_prev),
                "sales": current_data["sales"],
                "sales_previous_year": sales_prev,
                "sales_yoy": calc_yoy(current_data["sales"], sales_prev),
            })

        # 商品コード順にソート
        product_items.sort(key=lambda x: x["product_code"])

    except Exception:
        # product_salesテーブルが存在しない場合は空配列
        product_items = []

    return {
        "segment_id": segment["id"],
        "segment_code": segment["code"],
        "segment_name": segment["name"],
        "month": target_month.isoformat(),
        "total_sales": total_sales,
        "total_sales_previous_year": total_sales_prev,
        "total_sales_yoy": calc_yoy(total_sales, total_sales_prev),
        "total_customers": total_customers,
        "total_customers_previous_year": total_customers_prev,
        "total_customers_yoy": calc_yoy(total_customers, total_customers_prev),
        "avg_unit_price": avg_unit_price,
        "avg_unit_price_previous_year": avg_unit_price_prev,
        "avg_unit_price_yoy": calc_yoy(avg_unit_price, avg_unit_price_prev),
        "products": products,
        "product_items": product_items,
    }


# =============================================================================
# 店舗別売上集計取得
# =============================================================================

async def get_store_summary(
    supabase: Client,
    department_id: str,
    target_month: date,
    period_type: str = "monthly"
) -> Dict[str, Any]:
    """
    店舗別売上集計を取得する

    全店舗の売上高・客数・客単価と前年比を計算して返す。
    単月モードと累計モードに対応。

    Args:
        supabase: Supabaseクライアント
        department_id: 部門ID
        target_month: 対象月
        period_type: 期間タイプ（'monthly' or 'cumulative'）

    Returns:
        dict: 店舗別売上集計データ
    """
    target_month = normalize_to_month_start(target_month)
    fiscal_year = get_fiscal_year(target_month)

    # 部門情報を取得
    dept_response = supabase.table("departments").select(
        "slug"
    ).eq("id", department_id).single().execute()
    department_slug = dept_response.data["slug"]

    # セグメント（店舗）を取得
    segments_response = supabase.table("segments").select(
        "id, code, name"
    ).eq("department_id", department_id).order("code").execute()
    segments = segments_response.data

    # 空の結果を返すための共通構造
    empty_totals = {
        "sales": None,
        "sales_previous_year": None,
        "sales_yoy": None,
        "sales_two_years_ago": None,
        "sales_yoy_two_years": None,
        "customers": None,
        "customers_previous_year": None,
        "customers_yoy": None,
        "customers_two_years_ago": None,
        "customers_yoy_two_years": None,
        "unit_price": None,
        "unit_price_previous_year": None,
        "unit_price_yoy": None,
        "unit_price_two_years_ago": None,
        "unit_price_yoy_two_years": None,
    }

    if not segments:
        return {
            "period": target_month.isoformat(),
            "department_slug": department_slug,
            "period_type": period_type,
            "fiscal_year": fiscal_year if period_type == "cumulative" else None,
            "stores": [],
            "totals": empty_totals,
        }

    segment_ids = [seg["id"] for seg in segments]

    # KPI定義（売上高、客数）を取得
    kpi_response = supabase.table("kpi_definitions").select(
        "id, name"
    ).eq("department_id", department_id).in_(
        "name", ["売上高", "客数"]
    ).execute()
    kpi_map = {kpi["name"]: kpi["id"] for kpi in kpi_response.data}

    sales_kpi_id = kpi_map.get("売上高")
    customers_kpi_id = kpi_map.get("客数")

    if not sales_kpi_id or not customers_kpi_id:
        raise ValueError("売上高または客数のKPI定義が見つかりません")

    kpi_ids = [sales_kpi_id, customers_kpi_id]

    # YoY計算ヘルパー（変化率: (今期-前期)/前期 × 100）
    def calc_yoy(current: Optional[float], previous: Optional[float]) -> Optional[float]:
        if current is None or previous is None or previous == 0:
            return None
        return round(((current - previous) / previous) * 100, 1)

    # 客単価計算ヘルパー
    def calc_unit_price(sales: Optional[float], customers: Optional[float]) -> Optional[float]:
        if sales is None or customers is None or customers == 0:
            return None
        return round(sales / customers, 0)

    if period_type == "cumulative":
        # 累計モード: 会計年度の9月〜対象月までの累計
        fiscal_start = date(fiscal_year, 9, 1)

        # 3年分の日付範囲を計算
        # 当年: fiscal_year年9月〜target_month
        # 前年: (fiscal_year-1)年9月〜(target_month - 1年)
        # 前々年: (fiscal_year-2)年9月〜(target_month - 2年)
        prev_fiscal_start = date(fiscal_year - 1, 9, 1)
        prev_target_month = date(target_month.year - 1, target_month.month, 1)
        two_years_fiscal_start = date(fiscal_year - 2, 9, 1)
        two_years_target_month = date(target_month.year - 2, target_month.month, 1)

        # 3年分のKPI値を一括取得
        values_response = supabase.table("kpi_values").select(
            "segment_id, kpi_id, date, value"
        ).in_("segment_id", segment_ids).in_(
            "kpi_id", kpi_ids
        ).gte("date", two_years_fiscal_start.isoformat()).lte(
            "date", target_month.isoformat()
        ).eq("is_target", False).execute()

        # データを年度別にマップ: {segment_id: {year_offset: {kpi_id: sum}}}
        # year_offset: 0=当年, 1=前年, 2=前々年
        cumulative_map: Dict[str, Dict[int, Dict[str, float]]] = {}

        for v in values_response.data:
            seg_id = v["segment_id"]
            kpi_id = v["kpi_id"]
            val = float(v["value"]) if v["value"] else 0
            v_date = date.fromisoformat(v["date"])

            # どの年度に属するか判定
            year_offset = None
            if fiscal_start <= v_date <= target_month:
                year_offset = 0
            elif prev_fiscal_start <= v_date <= prev_target_month:
                year_offset = 1
            elif two_years_fiscal_start <= v_date <= two_years_target_month:
                year_offset = 2

            if year_offset is not None:
                if seg_id not in cumulative_map:
                    cumulative_map[seg_id] = {0: {}, 1: {}, 2: {}}
                if kpi_id not in cumulative_map[seg_id][year_offset]:
                    cumulative_map[seg_id][year_offset][kpi_id] = 0
                cumulative_map[seg_id][year_offset][kpi_id] += val

        # 店舗別データを構築
        stores = []
        total_sales = [0, 0, 0]  # 当年, 前年, 前々年
        total_customers = [0, 0, 0]

        for segment in segments:
            seg_id = segment["id"]
            seg_data = cumulative_map.get(seg_id, {0: {}, 1: {}, 2: {}})

            sales = seg_data.get(0, {}).get(sales_kpi_id)
            sales_prev = seg_data.get(1, {}).get(sales_kpi_id)
            sales_two = seg_data.get(2, {}).get(sales_kpi_id)
            customers = seg_data.get(0, {}).get(customers_kpi_id)
            customers_prev = seg_data.get(1, {}).get(customers_kpi_id)
            customers_two = seg_data.get(2, {}).get(customers_kpi_id)

            unit_price = calc_unit_price(sales, customers)
            unit_price_prev = calc_unit_price(sales_prev, customers_prev)
            unit_price_two = calc_unit_price(sales_two, customers_two)

            stores.append({
                "segment_id": seg_id,
                "segment_code": segment["code"],
                "segment_name": segment["name"],
                "sales": sales,
                "sales_previous_year": sales_prev,
                "sales_yoy": calc_yoy(sales, sales_prev),
                "sales_two_years_ago": sales_two,
                "sales_yoy_two_years": calc_yoy(sales, sales_two),
                "customers": customers,
                "customers_previous_year": customers_prev,
                "customers_yoy": calc_yoy(customers, customers_prev),
                "customers_two_years_ago": customers_two,
                "customers_yoy_two_years": calc_yoy(customers, customers_two),
                "unit_price": unit_price,
                "unit_price_previous_year": unit_price_prev,
                "unit_price_yoy": calc_yoy(unit_price, unit_price_prev),
                "unit_price_two_years_ago": unit_price_two,
                "unit_price_yoy_two_years": calc_yoy(unit_price, unit_price_two),
            })

            # 合計値を集計
            if sales:
                total_sales[0] += sales
            if sales_prev:
                total_sales[1] += sales_prev
            if sales_two:
                total_sales[2] += sales_two
            if customers:
                total_customers[0] += customers
            if customers_prev:
                total_customers[1] += customers_prev
            if customers_two:
                total_customers[2] += customers_two

        # 合計の客単価を計算
        total_unit_price = calc_unit_price(total_sales[0], total_customers[0])
        total_unit_price_prev = calc_unit_price(total_sales[1], total_customers[1])
        total_unit_price_two = calc_unit_price(total_sales[2], total_customers[2])

        return {
            "period": target_month.isoformat(),
            "department_slug": department_slug,
            "period_type": period_type,
            "fiscal_year": fiscal_year,
            "stores": stores,
            "totals": {
                "sales": total_sales[0] if total_sales[0] > 0 else None,
                "sales_previous_year": total_sales[1] if total_sales[1] > 0 else None,
                "sales_yoy": calc_yoy(total_sales[0], total_sales[1]),
                "sales_two_years_ago": total_sales[2] if total_sales[2] > 0 else None,
                "sales_yoy_two_years": calc_yoy(total_sales[0], total_sales[2]),
                "customers": total_customers[0] if total_customers[0] > 0 else None,
                "customers_previous_year": total_customers[1] if total_customers[1] > 0 else None,
                "customers_yoy": calc_yoy(total_customers[0], total_customers[1]),
                "customers_two_years_ago": total_customers[2] if total_customers[2] > 0 else None,
                "customers_yoy_two_years": calc_yoy(total_customers[0], total_customers[2]),
                "unit_price": total_unit_price,
                "unit_price_previous_year": total_unit_price_prev,
                "unit_price_yoy": calc_yoy(total_unit_price, total_unit_price_prev),
                "unit_price_two_years_ago": total_unit_price_two,
                "unit_price_yoy_two_years": calc_yoy(total_unit_price, total_unit_price_two),
            },
        }

    else:
        # 単月モード（従来の処理）
        previous_month = get_previous_year_month(target_month)

        # 当月のKPI値を取得
        current_response = supabase.table("kpi_values").select(
            "segment_id, kpi_id, value"
        ).in_("segment_id", segment_ids).in_(
            "kpi_id", kpi_ids
        ).eq("date", target_month.isoformat()).eq("is_target", False).execute()

        # 前年同月のKPI値を取得
        prev_response = supabase.table("kpi_values").select(
            "segment_id, kpi_id, value"
        ).in_("segment_id", segment_ids).in_(
            "kpi_id", kpi_ids
        ).eq("date", previous_month.isoformat()).eq("is_target", False).execute()

        # データをマップに整理
        current_map: Dict[str, Dict[str, float]] = {}
        for v in current_response.data:
            if v["segment_id"] not in current_map:
                current_map[v["segment_id"]] = {}
            current_map[v["segment_id"]][v["kpi_id"]] = float(v["value"]) if v["value"] else 0

        prev_map: Dict[str, Dict[str, float]] = {}
        for v in prev_response.data:
            if v["segment_id"] not in prev_map:
                prev_map[v["segment_id"]] = {}
            prev_map[v["segment_id"]][v["kpi_id"]] = float(v["value"]) if v["value"] else 0

        # 店舗別データを構築
        stores = []
        total_sales = 0
        total_sales_prev = 0
        total_customers = 0
        total_customers_prev = 0

        for segment in segments:
            seg_id = segment["id"]
            current_data = current_map.get(seg_id, {})
            prev_data = prev_map.get(seg_id, {})

            sales = current_data.get(sales_kpi_id)
            sales_prev = prev_data.get(sales_kpi_id)
            customers = current_data.get(customers_kpi_id)
            customers_prev = prev_data.get(customers_kpi_id)

            unit_price = calc_unit_price(sales, customers)
            unit_price_prev = calc_unit_price(sales_prev, customers_prev)

            stores.append({
                "segment_id": seg_id,
                "segment_code": segment["code"],
                "segment_name": segment["name"],
                "sales": sales,
                "sales_previous_year": sales_prev,
                "sales_yoy": calc_yoy(sales, sales_prev),
                "sales_two_years_ago": None,
                "sales_yoy_two_years": None,
                "customers": customers,
                "customers_previous_year": customers_prev,
                "customers_yoy": calc_yoy(customers, customers_prev),
                "customers_two_years_ago": None,
                "customers_yoy_two_years": None,
                "unit_price": unit_price,
                "unit_price_previous_year": unit_price_prev,
                "unit_price_yoy": calc_yoy(unit_price, unit_price_prev),
                "unit_price_two_years_ago": None,
                "unit_price_yoy_two_years": None,
            })

            # 合計値を集計
            if sales is not None:
                total_sales += sales
            if sales_prev is not None:
                total_sales_prev += sales_prev
            if customers is not None:
                total_customers += customers
            if customers_prev is not None:
                total_customers_prev += customers_prev

        # 合計の客単価を計算
        total_unit_price = calc_unit_price(total_sales, total_customers)
        total_unit_price_prev = calc_unit_price(total_sales_prev, total_customers_prev)

        return {
            "period": target_month.isoformat(),
            "department_slug": department_slug,
            "period_type": period_type,
            "fiscal_year": None,
            "stores": stores,
            "totals": {
                "sales": total_sales if total_sales > 0 else None,
                "sales_previous_year": total_sales_prev if total_sales_prev > 0 else None,
                "sales_yoy": calc_yoy(total_sales, total_sales_prev),
                "sales_two_years_ago": None,
                "sales_yoy_two_years": None,
                "customers": total_customers if total_customers > 0 else None,
                "customers_previous_year": total_customers_prev if total_customers_prev > 0 else None,
                "customers_yoy": calc_yoy(total_customers, total_customers_prev),
                "customers_two_years_ago": None,
                "customers_yoy_two_years": None,
                "unit_price": total_unit_price,
                "unit_price_previous_year": total_unit_price_prev,
                "unit_price_yoy": calc_yoy(total_unit_price, total_unit_price_prev),
                "unit_price_two_years_ago": None,
                "unit_price_yoy_two_years": None,
            },
        }


# =============================================================================
# 利用可能な月一覧取得
# =============================================================================

async def get_available_months(
    supabase: Client,
    department_id: Optional[str] = None
) -> List[str]:
    """
    データベースに格納されている利用可能な月の一覧を取得する

    kpi_valuesテーブルからDISTINCTで月を取得し、降順で返す。

    Args:
        supabase: Supabaseクライアント
        department_id: 部門ID（指定時はその部門のセグメントのみ対象）

    Returns:
        List[str]: 利用可能な月のリスト（YYYY-MM-DD形式、降順）
    """
    try:
        # kpi_valuesテーブルから日付を取得
        query = supabase.table("kpi_values").select("date")

        # 部門IDが指定されている場合、その部門のセグメントに絞る
        if department_id:
            segments_response = supabase.table("segments").select(
                "id"
            ).eq("department_id", department_id).execute()
            segment_ids = [seg["id"] for seg in segments_response.data]
            if segment_ids:
                query = query.in_("segment_id", segment_ids)

        response = query.execute()

        if not response.data:
            return []

        # DISTINCTで月を取得し、降順でソート
        months_set = set()
        for row in response.data:
            if row.get("date"):
                months_set.add(row["date"])

        # 降順でソート
        months = sorted(list(months_set), reverse=True)

        return months

    except Exception as e:
        # エラー時は空リストを返す
        return []


# =============================================================================
# 店舗別推移取得
# =============================================================================

async def get_store_trend_all(
    supabase: Client,
    department_id: str,
    fiscal_year: int
) -> Dict[str, Any]:
    """
    全店舗の月別売上推移を取得する

    Args:
        supabase: Supabaseクライアント
        department_id: 部門ID
        fiscal_year: 会計年度（9月起点）

    Returns:
        dict: 全店舗の月別推移データ
    """
    # 会計年度の月リストを生成（9月〜翌8月）
    months = []
    for i in range(12):
        month_num = 9 + i
        year = fiscal_year if month_num <= 12 else fiscal_year + 1
        month_num = month_num if month_num <= 12 else month_num - 12
        months.append(f"{year}-{month_num:02d}")

    # 会計年度の範囲
    start_date = date(fiscal_year, 9, 1)
    end_date = date(fiscal_year + 1, 8, 1)

    # セグメント（店舗）を取得
    segments_response = supabase.table("segments").select(
        "id, code, name"
    ).eq("department_id", department_id).order("code").execute()
    segments = segments_response.data

    if not segments:
        return {
            "fiscal_year": fiscal_year,
            "months": months,
            "stores": [],
        }

    segment_ids = [seg["id"] for seg in segments]

    # 売上高KPIを取得
    kpi_response = supabase.table("kpi_definitions").select(
        "id"
    ).eq("department_id", department_id).eq("name", "売上高").execute()

    if not kpi_response.data:
        raise ValueError("売上高のKPI定義が見つかりません")

    sales_kpi_id = kpi_response.data[0]["id"]

    # KPI値を取得
    values_response = supabase.table("kpi_values").select(
        "segment_id, date, value"
    ).in_("segment_id", segment_ids).eq(
        "kpi_id", sales_kpi_id
    ).gte("date", start_date.isoformat()).lte(
        "date", end_date.isoformat()
    ).eq("is_target", False).execute()

    # データをマップに整理: {segment_id: {month: value}}
    values_map: Dict[str, Dict[str, float]] = {}
    for v in values_response.data:
        seg_id = v["segment_id"]
        if seg_id not in values_map:
            values_map[seg_id] = {}
        # dateをYYYY-MM形式に変換
        date_str = v["date"][:7]
        values_map[seg_id][date_str] = float(v["value"]) if v["value"] else None

    # 店舗別データを構築
    stores = []
    for segment in segments:
        seg_id = segment["id"]
        seg_values = values_map.get(seg_id, {})
        values = [seg_values.get(m) for m in months]
        stores.append({
            "segment_id": seg_id,
            "segment_name": segment["name"],
            "values": values,
        })

    return {
        "fiscal_year": fiscal_year,
        "months": months,
        "stores": stores,
    }


async def get_store_trend_single(
    supabase: Client,
    segment_id: str,
    fiscal_year: int
) -> Dict[str, Any]:
    """
    単一店舗の月別売上推移を取得する（前年・前々年比較付き）

    Args:
        supabase: Supabaseクライアント
        segment_id: セグメント（店舗）ID
        fiscal_year: 会計年度（9月起点）

    Returns:
        dict: 店舗の月別推移データ（当年・前年・前々年）
    """
    # セグメント情報を取得
    segment_response = supabase.table("segments").select(
        "id, name, department_id"
    ).eq("id", segment_id).single().execute()

    if not segment_response.data:
        raise ValueError(f"店舗が見つかりません: {segment_id}")

    segment = segment_response.data

    # 会計年度の月リストを生成（9月〜翌8月）
    months = []
    for i in range(12):
        month_num = 9 + i
        year = fiscal_year if month_num <= 12 else fiscal_year + 1
        month_num = month_num if month_num <= 12 else month_num - 12
        months.append(f"{year}-{month_num:02d}")

    # 3年分の日付範囲
    current_start = date(fiscal_year, 9, 1)
    current_end = date(fiscal_year + 1, 8, 1)
    prev_start = date(fiscal_year - 1, 9, 1)
    prev_end = date(fiscal_year, 8, 1)
    two_years_start = date(fiscal_year - 2, 9, 1)
    two_years_end = date(fiscal_year - 1, 8, 1)

    # 売上高KPIを取得
    kpi_response = supabase.table("kpi_definitions").select(
        "id"
    ).eq("department_id", segment["department_id"]).eq("name", "売上高").execute()

    if not kpi_response.data:
        raise ValueError("売上高のKPI定義が見つかりません")

    sales_kpi_id = kpi_response.data[0]["id"]

    # 3年分のKPI値を取得
    values_response = supabase.table("kpi_values").select(
        "date, value"
    ).eq("segment_id", segment_id).eq(
        "kpi_id", sales_kpi_id
    ).gte("date", two_years_start.isoformat()).lte(
        "date", current_end.isoformat()
    ).eq("is_target", False).execute()

    # データをマップに整理: {date: value}
    values_map: Dict[str, float] = {}
    for v in values_response.data:
        values_map[v["date"][:7]] = float(v["value"]) if v["value"] else None

    # 年度別のデータを構築
    actual = []
    previous_year = []
    two_years_ago = []

    for i, month in enumerate(months):
        # 当年
        actual.append(values_map.get(month))

        # 前年（月は同じ、年を-1）
        prev_month = months[i].replace(str(fiscal_year + 1), str(fiscal_year)).replace(
            f"{fiscal_year}-", f"{fiscal_year - 1}-"
        )
        # 正しい前年月を計算
        month_num = int(month.split("-")[1])
        if month_num >= 9:
            prev_year_str = f"{fiscal_year - 1}-{month_num:02d}"
        else:
            prev_year_str = f"{fiscal_year}-{month_num:02d}"
        previous_year.append(values_map.get(prev_year_str))

        # 前々年
        if month_num >= 9:
            two_years_str = f"{fiscal_year - 2}-{month_num:02d}"
        else:
            two_years_str = f"{fiscal_year - 1}-{month_num:02d}"
        two_years_ago.append(values_map.get(two_years_str))

    # サマリー計算
    total = sum(v for v in actual if v is not None)
    total_prev = sum(v for v in previous_year if v is not None)
    total_two = sum(v for v in two_years_ago if v is not None)

    yoy_rate = None
    if total_prev and total_prev > 0:
        yoy_rate = round(((total - total_prev) / total_prev) * 100, 1)

    return {
        "segment_id": segment["id"],
        "segment_name": segment["name"],
        "fiscal_year": fiscal_year,
        "months": months,
        "actual": actual,
        "previous_year": previous_year,
        "two_years_ago": two_years_ago,
        "summary": {
            "total": total if total > 0 else None,
            "total_previous_year": total_prev if total_prev > 0 else None,
            "total_two_years_ago": total_two if total_two > 0 else None,
            "yoy_rate": yoy_rate,
        },
    }
