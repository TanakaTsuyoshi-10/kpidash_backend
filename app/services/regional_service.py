"""
地区別分析サービスモジュール

地区別売上集計・目標管理のビジネスロジックを提供する。
"""
from datetime import date
from decimal import Decimal
from typing import Dict, List, Any, Optional

from supabase import Client

from app.services.metrics import (
    get_fiscal_year,
    get_fiscal_year_range,
    get_previous_year_month,
    normalize_to_month_start,
    calculate_yoy_rate,
)


def _safe_yoy_rate(current: float, previous: float) -> Optional[float]:
    """
    前年比を安全に計算する（floatをDecimalに変換して計算）

    Args:
        current: 今期の値
        previous: 前期の値

    Returns:
        前年比（%）、計算不可の場合はNone
    """
    if not current or not previous:
        return None
    result = calculate_yoy_rate(Decimal(str(current)), Decimal(str(previous)))
    return float(result) if result is not None else None


# =============================================================================
# 地区マスタ
# =============================================================================

# 店舗名と地区のデフォルトマッピング
DEFAULT_STORE_REGION_MAPPING = {
    # 都城地区
    "三股店": "都城地区",
    "鷹尾店": "都城地区",
    "大根田店": "都城地区",
    "中町店": "都城地区",
    # 宮崎地区
    "花山手東店": "宮崎地区",
    "宮崎店": "宮崎地区",
    # 鹿児島地区
    "隼人店": "鹿児島地区",
    "中山店": "鹿児島地区",
    "吉野店": "鹿児島地区",
    "鹿屋店": "鹿児島地区",
    # 福岡地区
    "春日店": "福岡地区",
    "土井店": "福岡地区",
    "有田店": "福岡地区",
    "福岡有田店": "福岡地区",
    "空港東店": "福岡地区",
    # 熊本地区
    "長嶺店": "熊本地区",
    "熊本店": "熊本地区",
    # その他
    "本社": "その他",
}


async def get_regions(supabase: Client) -> List[Dict[str, Any]]:
    """
    地区一覧を取得

    Returns:
        地区一覧
    """
    response = supabase.table("regions").select(
        "id, name, display_order"
    ).order("display_order").execute()

    return response.data


async def get_store_region_mappings(
    supabase: Client,
    department_id: str
) -> List[Dict[str, Any]]:
    """
    店舗-地区マッピング一覧を取得

    Args:
        supabase: Supabaseクライアント
        department_id: 部門ID

    Returns:
        マッピング一覧
    """
    # 店舗一覧を取得
    segments_response = supabase.table("segments").select(
        "id, name"
    ).eq("department_id", department_id).order("name").execute()

    segments = segments_response.data

    # 既存のマッピングを取得
    segment_ids = [s["id"] for s in segments]
    if segment_ids:
        mapping_response = supabase.table("store_region_mapping").select(
            "segment_id, region_id, regions(id, name)"
        ).in_("segment_id", segment_ids).execute()
        mappings = {m["segment_id"]: m for m in mapping_response.data}
    else:
        mappings = {}

    # 結果を組み立て
    result = []
    for seg in segments:
        mapping = mappings.get(seg["id"])
        result.append({
            "segment_id": seg["id"],
            "segment_name": seg["name"],
            "region_id": mapping["region_id"] if mapping else None,
            "region_name": mapping["regions"]["name"] if mapping and mapping.get("regions") else None,
        })

    return result


async def update_store_region_mapping(
    supabase: Client,
    segment_id: str,
    region_id: str
) -> Dict[str, Any]:
    """
    店舗-地区マッピングを更新

    Args:
        supabase: Supabaseクライアント
        segment_id: 店舗ID
        region_id: 地区ID

    Returns:
        更新結果
    """
    # UPSERT
    response = supabase.table("store_region_mapping").upsert({
        "segment_id": segment_id,
        "region_id": region_id,
    }, on_conflict="segment_id").execute()

    return {"success": True, "data": response.data}


async def bulk_update_store_region_mappings(
    supabase: Client,
    mappings: List[Dict[str, str]]
) -> Dict[str, Any]:
    """
    店舗-地区マッピングを一括更新

    Args:
        supabase: Supabaseクライアント
        mappings: マッピングリスト [{segment_id, region_id}, ...]

    Returns:
        更新結果
    """
    for mapping in mappings:
        await update_store_region_mapping(
            supabase,
            mapping["segment_id"],
            mapping["region_id"]
        )

    return {"success": True, "updated": len(mappings)}


async def initialize_store_region_mappings(
    supabase: Client,
    department_id: str
) -> Dict[str, Any]:
    """
    デフォルトの店舗-地区マッピングを初期化

    Args:
        supabase: Supabaseクライアント
        department_id: 部門ID

    Returns:
        初期化結果
    """
    # 地区マスタを取得
    regions_response = supabase.table("regions").select("id, name").execute()
    region_map = {r["name"]: r["id"] for r in regions_response.data}

    # 店舗一覧を取得
    segments_response = supabase.table("segments").select(
        "id, name"
    ).eq("department_id", department_id).execute()

    initialized = 0
    for segment in segments_response.data:
        store_name = segment["name"]
        # デフォルトマッピングから地区を取得
        region_name = DEFAULT_STORE_REGION_MAPPING.get(store_name)
        if region_name and region_name in region_map:
            region_id = region_map[region_name]
            # マッピングを作成（既存は無視）
            try:
                supabase.table("store_region_mapping").upsert({
                    "segment_id": segment["id"],
                    "region_id": region_id,
                }, on_conflict="segment_id").execute()
                initialized += 1
            except Exception:
                pass

    return {"success": True, "initialized": initialized}


# =============================================================================
# 地区別集計
# =============================================================================

async def get_regional_summary(
    supabase: Client,
    department_id: str,
    target_month: date,
    period_type: str = "monthly"
) -> Dict[str, Any]:
    """
    地区別集計を取得

    Args:
        supabase: Supabaseクライアント
        department_id: 部門ID
        target_month: 対象月
        period_type: 期間タイプ（monthly/cumulative）

    Returns:
        地区別集計データ
    """
    target_month = normalize_to_month_start(target_month)
    fiscal_year = get_fiscal_year(target_month)
    prev_month = get_previous_year_month(target_month)

    # 累計の場合は年度開始から
    if period_type == "cumulative":
        fiscal_start, _ = get_fiscal_year_range(fiscal_year)
        prev_fiscal_start, _ = get_fiscal_year_range(fiscal_year - 1)
    else:
        fiscal_start = target_month
        prev_fiscal_start = prev_month

    # 地区一覧を取得
    regions = await get_regions(supabase)
    region_map = {r["id"]: r for r in regions}

    # 店舗一覧とマッピングを取得
    segments_response = supabase.table("segments").select(
        "id, name"
    ).eq("department_id", department_id).execute()
    segments = {s["id"]: s for s in segments_response.data}
    segment_ids = list(segments.keys())

    if not segment_ids:
        return {
            "period": target_month.isoformat(),
            "period_type": period_type,
            "fiscal_year": fiscal_year if period_type == "cumulative" else None,
            "regions": [],
            "grand_total": None,
        }

    # マッピングを取得
    mapping_response = supabase.table("store_region_mapping").select(
        "segment_id, region_id"
    ).in_("segment_id", segment_ids).execute()
    segment_to_region = {m["segment_id"]: m["region_id"] for m in mapping_response.data}

    # KPI定義を取得（売上高と客数）
    kpi_response = supabase.table("kpi_definitions").select(
        "id, name"
    ).eq("department_id", department_id).in_(
        "name", ["売上高", "客数"]
    ).execute()
    kpi_map = {k["name"]: k["id"] for k in kpi_response.data}

    sales_kpi_id = kpi_map.get("売上高")
    customers_kpi_id = kpi_map.get("客数")

    # 当期データを取得
    current_response = supabase.table("kpi_values").select(
        "kpi_id, segment_id, date, value"
    ).in_("segment_id", segment_ids).eq(
        "is_target", False
    ).gte("date", fiscal_start.isoformat()).lte(
        "date", target_month.isoformat()
    ).execute()

    # 前年データを取得
    prev_response = supabase.table("kpi_values").select(
        "kpi_id, segment_id, date, value"
    ).in_("segment_id", segment_ids).eq(
        "is_target", False
    ).gte("date", prev_fiscal_start.isoformat()).lte(
        "date", prev_month.isoformat()
    ).execute()

    # 店舗別目標を取得（is_target=trueのkpi_valuesから）
    # 単月の場合は当月のみ、累計の場合は年度開始からの合計
    store_targets_response = supabase.table("kpi_values").select(
        "kpi_id, segment_id, date, value"
    ).in_("segment_id", segment_ids).eq(
        "is_target", True
    ).gte("date", fiscal_start.isoformat()).lte(
        "date", target_month.isoformat()
    ).execute()

    # 店舗別目標を集計
    store_target_sales = {}  # {segment_id: target_sales}
    store_target_customers = {}  # {segment_id: target_customers}
    for v in store_targets_response.data:
        seg_id = v["segment_id"]
        kpi_id = v["kpi_id"]
        value = v["value"] or 0
        if kpi_id == sales_kpi_id:
            store_target_sales[seg_id] = store_target_sales.get(seg_id, 0) + value
        elif kpi_id == customers_kpi_id:
            store_target_customers[seg_id] = store_target_customers.get(seg_id, 0) + value

    # 地区別目標を店舗目標から集計
    regional_target_sales = {}  # {region_id: target_sales}
    regional_target_customers = {}  # {region_id: target_customers}
    for seg_id, target_val in store_target_sales.items():
        region_id = segment_to_region.get(seg_id)
        if region_id:
            regional_target_sales[region_id] = regional_target_sales.get(region_id, 0) + target_val
    for seg_id, target_val in store_target_customers.items():
        region_id = segment_to_region.get(seg_id)
        if region_id:
            regional_target_customers[region_id] = regional_target_customers.get(region_id, 0) + target_val

    # targets_mapを構築（従来のregional_targets形式に変換）
    targets_map = {}
    all_region_ids = set(regional_target_sales.keys()) | set(regional_target_customers.keys())
    for region_id in all_region_ids:
        targets_map[region_id] = {
            "target_sales": regional_target_sales.get(region_id),
            "target_customers": int(regional_target_customers.get(region_id, 0)) if regional_target_customers.get(region_id) else None,
        }

    # データを集計
    # 店舗別・KPI別に集計
    store_sales = {}  # {segment_id: total_sales}
    store_sales_prev = {}
    store_customers = {}
    store_customers_prev = {}

    for v in current_response.data:
        seg_id = v["segment_id"]
        kpi_id = v["kpi_id"]
        value = v["value"] or 0

        if kpi_id == sales_kpi_id:
            store_sales[seg_id] = store_sales.get(seg_id, 0) + value
        elif kpi_id == customers_kpi_id:
            store_customers[seg_id] = store_customers.get(seg_id, 0) + value

    for v in prev_response.data:
        seg_id = v["segment_id"]
        kpi_id = v["kpi_id"]
        value = v["value"] or 0

        if kpi_id == sales_kpi_id:
            store_sales_prev[seg_id] = store_sales_prev.get(seg_id, 0) + value
        elif kpi_id == customers_kpi_id:
            store_customers_prev[seg_id] = store_customers_prev.get(seg_id, 0) + value

    # 地区別に集計
    regional_data = {}
    for region in regions:
        regional_data[region["id"]] = {
            "region_id": region["id"],
            "region_name": region["name"],
            "stores": [],
            "total_sales": 0,
            "total_sales_previous_year": 0,
            "total_customers": 0,
            "total_customers_previous_year": 0,
        }

    # 未分類用
    unassigned_region_id = None
    for r in regions:
        if r["name"] == "その他":
            unassigned_region_id = r["id"]
            break

    # 店舗データを地区に振り分け
    for seg_id, seg in segments.items():
        region_id = segment_to_region.get(seg_id, unassigned_region_id)
        if region_id not in regional_data:
            continue

        sales = store_sales.get(seg_id, 0)
        sales_prev = store_sales_prev.get(seg_id, 0)
        customers = store_customers.get(seg_id, 0)
        customers_prev = store_customers_prev.get(seg_id, 0)

        unit_price = sales / customers if customers > 0 else None
        unit_price_prev = sales_prev / customers_prev if customers_prev > 0 else None

        store_data = {
            "segment_id": seg_id,
            "segment_name": seg["name"],
            "sales": sales if sales > 0 else None,
            "sales_previous_year": sales_prev if sales_prev > 0 else None,
            "sales_yoy_rate": _safe_yoy_rate(sales, sales_prev),
            "customers": int(customers) if customers > 0 else None,
            "customers_previous_year": int(customers_prev) if customers_prev > 0 else None,
            "customers_yoy_rate": _safe_yoy_rate(customers, customers_prev),
            "unit_price": round(unit_price, 0) if unit_price else None,
            "unit_price_previous_year": round(unit_price_prev, 0) if unit_price_prev else None,
        }

        regional_data[region_id]["stores"].append(store_data)
        regional_data[region_id]["total_sales"] += sales
        regional_data[region_id]["total_sales_previous_year"] += sales_prev
        regional_data[region_id]["total_customers"] += customers
        regional_data[region_id]["total_customers_previous_year"] += customers_prev

    # 地区別の計算値を追加
    result_regions = []
    grand_total_sales = 0
    grand_total_sales_prev = 0
    grand_total_customers = 0
    grand_total_customers_prev = 0

    for region in regions:
        rd = regional_data[region["id"]]

        # 店舗がない地区はスキップ
        if not rd["stores"]:
            continue

        total_sales = rd["total_sales"]
        total_sales_prev = rd["total_sales_previous_year"]
        total_customers = rd["total_customers"]
        total_customers_prev = rd["total_customers_previous_year"]

        # 目標
        target = targets_map.get(region["id"], {})
        target_sales = target.get("target_sales")
        target_customers = target.get("target_customers")

        # 計算値
        sales_yoy_rate = _safe_yoy_rate(total_sales, total_sales_prev)
        sales_yoy_diff = total_sales - total_sales_prev if total_sales and total_sales_prev else None
        customers_yoy_rate = _safe_yoy_rate(total_customers, total_customers_prev)

        target_diff = total_sales - target_sales if total_sales and target_sales else None
        target_achievement_rate = (total_sales / target_sales * 100) if total_sales and target_sales else None

        avg_unit_price = total_sales / total_customers if total_customers > 0 else None
        avg_unit_price_prev = total_sales_prev / total_customers_prev if total_customers_prev > 0 else None

        result_regions.append({
            "region_id": region["id"],
            "region_name": region["name"],
            "total_sales": total_sales if total_sales > 0 else None,
            "total_sales_previous_year": total_sales_prev if total_sales_prev > 0 else None,
            "sales_yoy_rate": sales_yoy_rate,
            "sales_yoy_diff": sales_yoy_diff,
            "target_sales": target_sales,
            "target_diff": target_diff,
            "target_achievement_rate": round(target_achievement_rate, 1) if target_achievement_rate else None,
            "total_customers": int(total_customers) if total_customers > 0 else None,
            "total_customers_previous_year": int(total_customers_prev) if total_customers_prev > 0 else None,
            "customers_yoy_rate": customers_yoy_rate,
            "target_customers": target_customers,
            "avg_unit_price": round(avg_unit_price, 0) if avg_unit_price else None,
            "avg_unit_price_previous_year": round(avg_unit_price_prev, 0) if avg_unit_price_prev else None,
            "stores": rd["stores"],
            "products": [],  # 商品別は別途取得
        })

        grand_total_sales += total_sales
        grand_total_sales_prev += total_sales_prev
        grand_total_customers += total_customers
        grand_total_customers_prev += total_customers_prev

    # 全体合計
    grand_total = None
    if grand_total_sales > 0:
        grand_unit_price = grand_total_sales / grand_total_customers if grand_total_customers > 0 else None
        grand_unit_price_prev = grand_total_sales_prev / grand_total_customers_prev if grand_total_customers_prev > 0 else None

        grand_total = {
            "region_id": "total",
            "region_name": "全体合計",
            "total_sales": grand_total_sales,
            "total_sales_previous_year": grand_total_sales_prev if grand_total_sales_prev > 0 else None,
            "sales_yoy_rate": _safe_yoy_rate(grand_total_sales, grand_total_sales_prev),
            "sales_yoy_diff": grand_total_sales - grand_total_sales_prev if grand_total_sales_prev else None,
            "target_sales": None,
            "target_diff": None,
            "target_achievement_rate": None,
            "total_customers": int(grand_total_customers) if grand_total_customers > 0 else None,
            "total_customers_previous_year": int(grand_total_customers_prev) if grand_total_customers_prev > 0 else None,
            "customers_yoy_rate": _safe_yoy_rate(grand_total_customers, grand_total_customers_prev),
            "target_customers": None,
            "avg_unit_price": round(grand_unit_price, 0) if grand_unit_price else None,
            "avg_unit_price_previous_year": round(grand_unit_price_prev, 0) if grand_unit_price_prev else None,
            "stores": [],
            "products": [],
        }

    return {
        "period": target_month.isoformat(),
        "period_type": period_type,
        "fiscal_year": fiscal_year if period_type == "cumulative" else None,
        "regions": result_regions,
        "grand_total": grand_total,
    }


# =============================================================================
# 地区別目標
# =============================================================================

async def get_regional_targets(
    supabase: Client,
    month: date,
    department_slug: str = "store"
) -> List[Dict[str, Any]]:
    """
    地区別目標を取得（店舗目標から自動集計）

    Args:
        supabase: Supabaseクライアント
        month: 対象月
        department_slug: 部門スラッグ

    Returns:
        目標一覧
    """
    month = normalize_to_month_start(month)

    # 地区一覧
    regions = await get_regions(supabase)
    region_map = {r["id"]: r for r in regions}

    # 部門IDを取得
    dept_response = supabase.table("departments").select(
        "id"
    ).eq("slug", department_slug).execute()
    if not dept_response.data:
        return []
    department_id = dept_response.data[0]["id"]

    # 店舗一覧を取得
    segments_response = supabase.table("segments").select(
        "id, name"
    ).eq("department_id", department_id).execute()
    segment_ids = [s["id"] for s in segments_response.data]

    if not segment_ids:
        return []

    # 店舗-地区マッピングを取得
    mapping_response = supabase.table("store_region_mapping").select(
        "segment_id, region_id"
    ).in_("segment_id", segment_ids).execute()
    segment_to_region = {m["segment_id"]: m["region_id"] for m in mapping_response.data}

    # KPI定義を取得
    kpi_response = supabase.table("kpi_definitions").select(
        "id, name"
    ).eq("department_id", department_id).in_(
        "name", ["売上高", "客数"]
    ).execute()
    kpi_map = {k["name"]: k["id"] for k in kpi_response.data}
    sales_kpi_id = kpi_map.get("売上高")
    customers_kpi_id = kpi_map.get("客数")

    # 店舗別目標を取得（当月のみ）
    store_targets_response = supabase.table("kpi_values").select(
        "kpi_id, segment_id, value"
    ).in_("segment_id", segment_ids).eq(
        "is_target", True
    ).eq("date", month.isoformat()).execute()

    # 地区別に目標を集計
    regional_target_sales = {}
    regional_target_customers = {}
    for v in store_targets_response.data:
        seg_id = v["segment_id"]
        region_id = segment_to_region.get(seg_id)
        if not region_id:
            continue
        kpi_id = v["kpi_id"]
        value = v["value"] or 0
        if kpi_id == sales_kpi_id:
            regional_target_sales[region_id] = regional_target_sales.get(region_id, 0) + value
        elif kpi_id == customers_kpi_id:
            regional_target_customers[region_id] = regional_target_customers.get(region_id, 0) + value

    # 結果を組み立て
    result = []
    for region in regions:
        result.append({
            "region_id": region["id"],
            "region_name": region["name"],
            "month": month.isoformat(),
            "target_sales": regional_target_sales.get(region["id"]),
            "target_customers": int(regional_target_customers.get(region["id"], 0)) if regional_target_customers.get(region["id"]) else None,
        })

    return result


# 注意: 地区別目標は店舗目標から自動集計されるため、
# save_regional_target / bulk_save_regional_targets は廃止されました。
# 目標設定は「目標設定」ページ (/targets) から店舗別に行ってください。
