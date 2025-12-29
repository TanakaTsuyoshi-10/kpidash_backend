"""
目標値サービスモジュール

目標値の登録・更新・取得・削除を行うサービスを提供する。
店舗部門、財務部門、通販部門の目標設定に対応。
"""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, List, Optional

from supabase import Client

from app.services.metrics import get_fiscal_year, normalize_to_month_start, get_previous_year_month
from app.schemas.target import (
    FinancialTargetResponse,
    FinancialTargetItem,
    FinancialTargetInput,
    EcommerceTargetResponse,
    EcommerceChannelTarget,
    EcommerceCustomerTarget,
    EcommerceTargetInput,
    TargetOverview,
    DepartmentTargetSummary,
    TargetSettingResult,
)


# =============================================================================
# 目標値の登録・更新
# =============================================================================

async def create_target_value(
    supabase: Client,
    segment_id: str,
    kpi_id: str,
    month: date,
    value: float
) -> Dict[str, Any]:
    """
    目標値を登録する（Upsert）

    既存の目標値がある場合は更新、なければ新規作成する。

    Args:
        supabase: Supabaseクライアント
        segment_id: 店舗ID
        kpi_id: KPI定義ID
        month: 対象月
        value: 目標値

    Returns:
        dict: 登録結果
    """
    month = normalize_to_month_start(month)

    # 既存のレコードを検索
    existing = supabase.table("kpi_values").select("id").eq(
        "segment_id", segment_id
    ).eq("kpi_id", kpi_id).eq(
        "date", month.isoformat()
    ).eq("is_target", True).execute()

    data = {
        "segment_id": segment_id,
        "kpi_id": kpi_id,
        "date": month.isoformat(),
        "value": value,
        "is_target": True,
    }

    if existing.data:
        # 更新
        response = supabase.table("kpi_values").update(data).eq(
            "id", existing.data[0]["id"]
        ).execute()
        is_created = False
    else:
        # 新規作成
        response = supabase.table("kpi_values").insert(data).execute()
        is_created = True

    if not response.data:
        raise Exception("目標値の登録に失敗しました")

    return {
        "id": response.data[0]["id"],
        "is_created": is_created,
    }


async def update_target_value(
    supabase: Client,
    target_id: int,
    value: float
) -> Dict[str, Any]:
    """
    目標値を更新する

    Args:
        supabase: Supabaseクライアント
        target_id: 目標値ID
        value: 新しい目標値

    Returns:
        dict: 更新結果
    """
    response = supabase.table("kpi_values").update({
        "value": value
    }).eq("id", target_id).eq("is_target", True).execute()

    if not response.data:
        raise Exception("目標値が見つかりません")

    return response.data[0]


async def delete_target_value(
    supabase: Client,
    target_id: int
) -> bool:
    """
    目標値を削除する

    Args:
        supabase: Supabaseクライアント
        target_id: 目標値ID

    Returns:
        bool: 削除成功
    """
    response = supabase.table("kpi_values").delete().eq(
        "id", target_id
    ).eq("is_target", True).execute()

    return bool(response.data)


async def bulk_upsert_targets(
    supabase: Client,
    targets: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    目標値を一括登録・更新する

    Args:
        supabase: Supabaseクライアント
        targets: 目標値リスト

    Returns:
        dict: 登録結果
    """
    result = {
        "created_count": 0,
        "updated_count": 0,
        "errors": [],
    }

    for target in targets:
        try:
            res = await create_target_value(
                supabase,
                segment_id=target["segment_id"],
                kpi_id=target["kpi_id"],
                month=target["month"],
                value=target["value"]
            )
            if res["is_created"]:
                result["created_count"] += 1
            else:
                result["updated_count"] += 1
        except Exception as e:
            result["errors"].append(
                f"店舗 {target['segment_id']}, KPI {target['kpi_id']}: {str(e)}"
            )

    return result


# =============================================================================
# 目標値の取得
# =============================================================================

async def get_target_values(
    supabase: Client,
    department_id: str,
    month: date,
    segment_id: Optional[str] = None,
    kpi_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    目標値一覧を取得する

    Args:
        supabase: Supabaseクライアント
        department_id: 部門ID
        month: 対象月
        segment_id: 店舗ID（オプション）
        kpi_id: KPI定義ID（オプション）

    Returns:
        List[dict]: 目標値リスト
    """
    month = normalize_to_month_start(month)

    # セグメントを取得
    segment_query = supabase.table("segments").select(
        "id, code, name"
    ).eq("department_id", department_id)
    if segment_id:
        segment_query = segment_query.eq("id", segment_id)
    segments_response = segment_query.execute()
    segments = {s["id"]: s for s in segments_response.data}

    if not segments:
        return []

    # KPI定義を取得
    kpi_query = supabase.table("kpi_definitions").select(
        "id, name, unit, category"
    ).eq("department_id", department_id).eq("is_visible", True)
    if kpi_id:
        kpi_query = kpi_query.eq("id", kpi_id)
    kpis_response = kpi_query.order("display_order").execute()
    kpis = {k["id"]: k for k in kpis_response.data}

    if not kpis:
        return []

    # 目標値を取得
    values_query = supabase.table("kpi_values").select(
        "id, segment_id, kpi_id, date, value"
    ).in_("segment_id", list(segments.keys())).in_(
        "kpi_id", list(kpis.keys())
    ).eq("date", month.isoformat()).eq("is_target", True)

    values_response = values_query.execute()

    result = []
    for v in values_response.data:
        segment = segments.get(v["segment_id"], {})
        kpi = kpis.get(v["kpi_id"], {})
        result.append({
            "id": v["id"],
            "segment_id": v["segment_id"],
            "segment_name": segment.get("name"),
            "kpi_id": v["kpi_id"],
            "kpi_name": kpi.get("name"),
            "month": v["date"],
            "value": float(v["value"]),
        })

    return result


async def get_target_matrix(
    supabase: Client,
    department_id: str,
    month: date
) -> Dict[str, Any]:
    """
    目標値マトリックスを取得する

    店舗×KPIの目標値マトリックスを取得する。
    目標値入力画面用。前年同月の実績も含める（daily_dataテーブルから取得）。

    Args:
        supabase: Supabaseクライアント
        department_id: 部門ID
        month: 対象月

    Returns:
        dict: 目標マトリックス
    """
    month = normalize_to_month_start(month)
    fiscal_year = get_fiscal_year(month)
    previous_month = get_previous_year_month(month)


    # セグメントを取得
    segments_response = supabase.table("segments").select(
        "id, code, name"
    ).eq("department_id", department_id).order("code").execute()
    segments = segments_response.data

    if not segments:
        return {
            "fiscal_year": fiscal_year,
            "month": month.isoformat(),
            "kpis": [],
            "rows": [],
        }

    # KPI定義を取得（全体カテゴリのみ＝売上高、客数など主要KPI）
    kpis_response = supabase.table("kpi_definitions").select(
        "id, name, unit, category"
    ).eq("department_id", department_id).eq(
        "is_visible", True
    ).in_("category", ["全体"]).order("display_order").execute()
    kpis = kpis_response.data

    if not kpis:
        return {
            "fiscal_year": fiscal_year,
            "month": month.isoformat(),
            "kpis": [],
            "rows": [],
        }

    segment_ids = [s["id"] for s in segments]
    kpi_ids = [k["id"] for k in kpis]

    # 目標値を取得
    values_response = supabase.table("kpi_values").select(
        "id, segment_id, kpi_id, value"
    ).in_("segment_id", segment_ids).in_(
        "kpi_id", kpi_ids
    ).eq("date", month.isoformat()).eq("is_target", True).execute()

    # 前年同月の実績をkpi_valuesテーブルから取得
    prev_year_response = supabase.table("kpi_values").select(
        "segment_id, kpi_id, value"
    ).in_("segment_id", segment_ids).in_(
        "kpi_id", kpi_ids
    ).eq("date", previous_month.isoformat()).eq("is_target", False).execute()

    # マッピング作成
    value_map: Dict[str, Dict[str, Dict]] = {}
    for v in values_response.data:
        seg_id = v["segment_id"]
        kpi_id = v["kpi_id"]
        if seg_id not in value_map:
            value_map[seg_id] = {}
        value_map[seg_id][kpi_id] = {
            "target_id": v["id"],
            "value": float(v["value"]),
        }

    # 前年同月実績のマッピング
    prev_year_map: Dict[str, Dict[str, float]] = {}
    for v in prev_year_response.data:
        seg_id = v["segment_id"]
        kpi_id = v["kpi_id"]
        if seg_id not in prev_year_map:
            prev_year_map[seg_id] = {}
        prev_year_map[seg_id][kpi_id] = float(v["value"])

    # 行データを構築
    rows = []
    for segment in segments:
        seg_id = segment["id"]
        seg_values = value_map.get(seg_id, {})
        seg_prev_values = prev_year_map.get(seg_id, {})

        values = {}
        for kpi in kpis:
            kpi_id = kpi["id"]
            cell = seg_values.get(kpi_id)
            prev_actual = seg_prev_values.get(kpi_id)
            values[kpi_id] = {
                "kpi_id": kpi_id,
                "target_id": cell["target_id"] if cell else None,
                "value": cell["value"] if cell else None,
                "last_year_actual": prev_actual,
            }

        rows.append({
            "segment_id": seg_id,
            "segment_code": segment["code"],
            "segment_name": segment["name"],
            "values": values,
        })

    return {
        "fiscal_year": fiscal_year,
        "month": month.isoformat(),
        "kpis": [{"id": k["id"], "name": k["name"], "unit": k["unit"]} for k in kpis],
        "rows": rows,
    }


# =============================================================================
# ヘルパー関数
# =============================================================================

def _calculate_yoy_rate(current: Optional[Decimal], previous: Optional[Decimal]) -> Optional[Decimal]:
    """前年比を計算する"""
    if current is None or previous is None or previous == 0:
        return None
    result = ((current - previous) / previous) * 100
    return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _calculate_sales_ratio(value: Optional[Decimal], sales: Optional[Decimal]) -> Optional[Decimal]:
    """売上対比を計算する"""
    if value is None or sales is None or sales == 0:
        return None
    result = (value / sales) * 100
    return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _to_decimal(value: Any) -> Optional[Decimal]:
    """値をDecimalに変換する"""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (ValueError, TypeError):
        return None


# =============================================================================
# 財務部門 目標取得
# =============================================================================

async def get_financial_targets(
    supabase: Client,
    month: date,
) -> FinancialTargetResponse:
    """
    財務目標を取得する

    Args:
        supabase: Supabaseクライアント
        month: 対象月

    Returns:
        FinancialTargetResponse: 財務目標
    """
    month = normalize_to_month_start(month)
    fiscal_year = get_fiscal_year(month)
    previous_month = get_previous_year_month(month)

    # 目標データを取得
    target_response = supabase.table("financial_data").select("*").eq(
        "month", month.isoformat()
    ).eq("is_target", True).execute()
    target_data = target_response.data[0] if target_response.data else {}

    # 前年実績を取得
    actual_response = supabase.table("financial_data").select("*").eq(
        "month", previous_month.isoformat()
    ).eq("is_target", False).execute()
    actual_data = actual_response.data[0] if actual_response.data else {}

    # 売上原価明細を取得
    cost_target_response = supabase.table("financial_cost_details").select("*").eq(
        "period", month.isoformat()
    ).eq("is_target", True).execute()
    cost_target = cost_target_response.data[0] if cost_target_response.data else {}

    cost_actual_response = supabase.table("financial_cost_details").select("*").eq(
        "period", previous_month.isoformat()
    ).eq("is_target", False).execute()
    cost_actual = cost_actual_response.data[0] if cost_actual_response.data else {}

    # 販管費明細を取得
    sga_target_response = supabase.table("financial_sga_details").select("*").eq(
        "period", month.isoformat()
    ).eq("is_target", True).execute()
    sga_target = sga_target_response.data[0] if sga_target_response.data else {}

    sga_actual_response = supabase.table("financial_sga_details").select("*").eq(
        "period", previous_month.isoformat()
    ).eq("is_target", False).execute()
    sga_actual = sga_actual_response.data[0] if sga_actual_response.data else {}

    # サマリー項目を構築
    target_sales = _to_decimal(target_data.get("sales_total"))
    summary_items = []

    # (DBカラム名, API用フィールド名, 表示名)
    summary_fields = [
        ("sales_total", "sales_total", "売上高合計"),
        ("sales_store", "sales_store", "店舗売上高"),
        ("sales_online", "sales_online", "通販売上高"),
        ("cost_of_sales", "cost_of_sales", "売上原価"),
        ("gross_profit", "gross_profit", "売上総利益"),
        ("sg_and_a_total", "sga_total", "販管費合計"),
        ("operating_profit", "operating_profit", "営業利益"),
    ]

    for db_field, api_field, name in summary_fields:
        target_val = _to_decimal(target_data.get(db_field))
        actual_val = _to_decimal(actual_data.get(db_field))
        summary_items.append(FinancialTargetItem(
            field_name=api_field,
            display_name=name,
            target_value=target_val,
            last_year_actual=actual_val,
            sales_ratio=_calculate_sales_ratio(target_val, target_sales) if api_field not in ["sales_total", "sales_store", "sales_online"] else None,
            yoy_rate=_calculate_yoy_rate(target_val, actual_val),
        ))

    # 売上原価明細を構築
    cost_items = []
    cost_fields = [
        ("purchases", "仕入高"),
        ("raw_material_purchases", "原材料仕入高"),
        ("labor_cost", "労務費"),
        ("consumables", "消耗品費"),
        ("rent", "賃借料"),
        ("repairs", "修繕費"),
        ("utilities", "水道光熱費"),
    ]

    for field, name in cost_fields:
        target_val = _to_decimal(cost_target.get(field))
        actual_val = _to_decimal(cost_actual.get(field))
        cost_items.append(FinancialTargetItem(
            field_name=field,
            display_name=name,
            target_value=target_val,
            last_year_actual=actual_val,
            sales_ratio=_calculate_sales_ratio(target_val, target_sales),
            yoy_rate=_calculate_yoy_rate(target_val, actual_val),
        ))

    # 販管費明細を構築
    sga_items = []
    sga_fields = [
        ("executive_compensation", "役員報酬"),
        ("personnel_cost", "人件費"),
        ("delivery_cost", "配送費"),
        ("packaging_cost", "包装費"),
        ("payment_fees", "支払手数料"),
        ("freight_cost", "荷造運賃費"),
        ("sales_commission", "販売手数料"),
        ("advertising_cost", "広告宣伝費"),
    ]

    for field, name in sga_fields:
        target_val = _to_decimal(sga_target.get(field))
        actual_val = _to_decimal(sga_actual.get(field))
        sga_items.append(FinancialTargetItem(
            field_name=field,
            display_name=name,
            target_value=target_val,
            last_year_actual=actual_val,
            sales_ratio=_calculate_sales_ratio(target_val, target_sales),
            yoy_rate=_calculate_yoy_rate(target_val, actual_val),
        ))

    return FinancialTargetResponse(
        fiscal_year=fiscal_year,
        month=month.isoformat(),
        summary_items=summary_items,
        cost_items=cost_items,
        sga_items=sga_items,
    )


async def save_financial_targets(
    supabase: Client,
    data: FinancialTargetInput,
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
) -> TargetSettingResult:
    """
    財務目標を保存する

    Args:
        supabase: Supabaseクライアント
        data: 財務目標入力
        user_id: ユーザーID
        user_email: ユーザーメールアドレス

    Returns:
        TargetSettingResult: 保存結果
    """
    month = normalize_to_month_start(data.month)
    result = TargetSettingResult()

    try:
        # サマリーを保存
        if data.summary:
            # API→DBカラム名マッピング
            field_mapping = {"sga_total": "sg_and_a_total"}
            summary_dict = data.summary.model_dump()

            # 年度を計算（4月始まり: 1-3月は前年度）
            fiscal_year = month.year if month.month >= 4 else month.year - 1

            summary_data = {
                "month": month.isoformat(),
                "fiscal_year": fiscal_year,
                "is_target": True,
            }
            for k, v in summary_dict.items():
                if v is not None:
                    db_key = field_mapping.get(k, k)
                    summary_data[db_key] = float(v)

            existing = supabase.table("financial_data").select("id").eq(
                "month", month.isoformat()
            ).eq("is_target", True).execute()

            if existing.data:
                supabase.table("financial_data").update(summary_data).eq(
                    "id", existing.data[0]["id"]
                ).execute()
                result.updated_count += 1
            else:
                supabase.table("financial_data").insert(summary_data).execute()
                result.created_count += 1

        # 売上原価明細を保存
        if data.cost_details:
            cost_data = {
                "period": month.isoformat(),
                "is_target": True,
                **{k: float(v) if v is not None else None for k, v in data.cost_details.model_dump().items() if v is not None},
            }

            existing = supabase.table("financial_cost_details").select("id").eq(
                "period", month.isoformat()
            ).eq("is_target", True).execute()

            if existing.data:
                supabase.table("financial_cost_details").update(cost_data).eq(
                    "id", existing.data[0]["id"]
                ).execute()
                result.updated_count += 1
            else:
                supabase.table("financial_cost_details").insert(cost_data).execute()
                result.created_count += 1

        # 販管費明細を保存
        if data.sga_details:
            sga_data = {
                "period": month.isoformat(),
                "is_target": True,
                **{k: float(v) if v is not None else None for k, v in data.sga_details.model_dump().items() if v is not None},
            }

            existing = supabase.table("financial_sga_details").select("id").eq(
                "period", month.isoformat()
            ).eq("is_target", True).execute()

            if existing.data:
                supabase.table("financial_sga_details").update(sga_data).eq(
                    "id", existing.data[0]["id"]
                ).execute()
                result.updated_count += 1
            else:
                supabase.table("financial_sga_details").insert(sga_data).execute()
                result.created_count += 1

    except Exception as e:
        result.errors.append(str(e))

    return result


# =============================================================================
# 通販部門 目標取得
# =============================================================================

async def get_ecommerce_targets(
    supabase: Client,
    month: date,
) -> EcommerceTargetResponse:
    """
    通販目標を取得する

    Args:
        supabase: Supabaseクライアント
        month: 対象月

    Returns:
        EcommerceTargetResponse: 通販目標
    """
    month = normalize_to_month_start(month)
    fiscal_year = get_fiscal_year(month)
    previous_month = get_previous_year_month(month)

    # チャネル別目標を取得
    channel_target_response = supabase.table("ecommerce_channel_sales").select("*").eq(
        "month", month.isoformat()
    ).eq("is_target", True).execute()

    # チャネル別前年実績を取得
    channel_actual_response = supabase.table("ecommerce_channel_sales").select("*").eq(
        "month", previous_month.isoformat()
    ).eq("is_target", False).execute()

    # チャネル別マッピング
    channel_actuals = {r["channel"]: r for r in (channel_actual_response.data or [])}

    channel_targets = []
    total_target_sales = Decimal("0")
    total_actual_sales = Decimal("0")

    for target in (channel_target_response.data or []):
        channel = target["channel"]
        actual = channel_actuals.get(channel, {})

        target_sales = _to_decimal(target.get("sales"))
        actual_sales = _to_decimal(actual.get("sales"))
        target_buyers = target.get("buyers")
        actual_buyers = actual.get("buyers")

        if target_sales:
            total_target_sales += target_sales
        if actual_sales:
            total_actual_sales += actual_sales

        channel_targets.append(EcommerceChannelTarget(
            channel=channel,
            target_sales=target_sales,
            target_buyers=target_buyers,
            last_year_sales=actual_sales,
            last_year_buyers=actual_buyers,
            yoy_sales_rate=_calculate_yoy_rate(target_sales, actual_sales),
            yoy_buyers_rate=_calculate_yoy_rate(
                Decimal(str(target_buyers)) if target_buyers else None,
                Decimal(str(actual_buyers)) if actual_buyers else None
            ),
        ))

    # チャネルがない場合、デフォルトチャネルを追加
    default_channels = ["EC", "電話", "FAX", "店舗受付"]
    existing_channels = {ct.channel for ct in channel_targets}
    for ch in default_channels:
        if ch not in existing_channels:
            actual = channel_actuals.get(ch, {})
            channel_targets.append(EcommerceChannelTarget(
                channel=ch,
                target_sales=None,
                target_buyers=None,
                last_year_sales=_to_decimal(actual.get("sales")),
                last_year_buyers=actual.get("buyers"),
                yoy_sales_rate=None,
                yoy_buyers_rate=None,
            ))

    # チャネル順でソート
    channel_order = {ch: i for i, ch in enumerate(default_channels)}
    channel_targets.sort(key=lambda x: channel_order.get(x.channel, 99))

    # 顧客統計目標を取得
    customer_target_response = supabase.table("ecommerce_customer_stats").select("*").eq(
        "month", month.isoformat()
    ).eq("is_target", True).execute()
    customer_target = customer_target_response.data[0] if customer_target_response.data else {}

    customer_actual_response = supabase.table("ecommerce_customer_stats").select("*").eq(
        "month", previous_month.isoformat()
    ).eq("is_target", False).execute()
    customer_actual = customer_actual_response.data[0] if customer_actual_response.data else {}

    customer_target_obj = None
    if customer_target or customer_actual:
        target_new = customer_target.get("new_customers")
        target_repeat = customer_target.get("repeat_customers")
        actual_new = customer_actual.get("new_customers")
        actual_repeat = customer_actual.get("repeat_customers")

        customer_target_obj = EcommerceCustomerTarget(
            new_customers=target_new,
            repeat_customers=target_repeat,
            last_year_new=actual_new,
            last_year_repeat=actual_repeat,
            yoy_new_rate=_calculate_yoy_rate(
                Decimal(str(target_new)) if target_new else None,
                Decimal(str(actual_new)) if actual_new else None
            ),
            yoy_repeat_rate=_calculate_yoy_rate(
                Decimal(str(target_repeat)) if target_repeat else None,
                Decimal(str(actual_repeat)) if actual_repeat else None
            ),
        )

    return EcommerceTargetResponse(
        fiscal_year=fiscal_year,
        month=month.isoformat(),
        total_target_sales=total_target_sales if total_target_sales > 0 else None,
        last_year_total_sales=total_actual_sales if total_actual_sales > 0 else None,
        yoy_total_rate=_calculate_yoy_rate(total_target_sales, total_actual_sales) if total_target_sales > 0 else None,
        channel_targets=channel_targets,
        customer_target=customer_target_obj,
    )


async def save_ecommerce_targets(
    supabase: Client,
    data: EcommerceTargetInput,
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
) -> TargetSettingResult:
    """
    通販目標を保存する

    Args:
        supabase: Supabaseクライアント
        data: 通販目標入力
        user_id: ユーザーID
        user_email: ユーザーメールアドレス

    Returns:
        TargetSettingResult: 保存結果
    """
    month = normalize_to_month_start(data.month)
    result = TargetSettingResult()

    try:
        # チャネル別目標を保存
        if data.channel_targets:
            for ct in data.channel_targets:
                channel_data = {
                    "month": month.isoformat(),
                    "channel": ct.channel,
                    "sales": float(ct.sales) if ct.sales else None,
                    "buyers": ct.buyers,
                    "is_target": True,
                }

                existing = supabase.table("ecommerce_channel_sales").select("id").eq(
                    "month", month.isoformat()
                ).eq("channel", ct.channel).eq("is_target", True).execute()

                if existing.data:
                    supabase.table("ecommerce_channel_sales").update(channel_data).eq(
                        "id", existing.data[0]["id"]
                    ).execute()
                    result.updated_count += 1
                else:
                    supabase.table("ecommerce_channel_sales").insert(channel_data).execute()
                    result.created_count += 1

        # 顧客統計目標を保存
        if data.new_customers is not None or data.repeat_customers is not None:
            customer_data = {
                "month": month.isoformat(),
                "new_customers": data.new_customers,
                "repeat_customers": data.repeat_customers,
                "total_customers": (data.new_customers or 0) + (data.repeat_customers or 0),
                "is_target": True,
            }

            existing = supabase.table("ecommerce_customer_stats").select("id").eq(
                "month", month.isoformat()
            ).eq("is_target", True).execute()

            if existing.data:
                supabase.table("ecommerce_customer_stats").update(customer_data).eq(
                    "id", existing.data[0]["id"]
                ).execute()
                result.updated_count += 1
            else:
                supabase.table("ecommerce_customer_stats").insert(customer_data).execute()
                result.created_count += 1

    except Exception as e:
        result.errors.append(str(e))

    return result


# =============================================================================
# 目標概要
# =============================================================================

async def get_target_overview(
    supabase: Client,
    month: date,
) -> TargetOverview:
    """
    目標設定概要を取得する

    Args:
        supabase: Supabaseクライアント
        month: 対象月

    Returns:
        TargetOverview: 目標設定概要
    """
    month = normalize_to_month_start(month)
    fiscal_year = get_fiscal_year(month)

    departments = []

    # 店舗部門
    store_dept = supabase.table("departments").select("id").eq("slug", "store").execute()
    if store_dept.data:
        dept_id = store_dept.data[0]["id"]
        store_targets = supabase.table("kpi_values").select("id, segment_id").eq(
            "date", month.isoformat()
        ).eq("is_target", True).execute()

        # 店舗部門のセグメントIDで絞り込み
        segments = supabase.table("segments").select("id").eq("department_id", dept_id).execute()
        seg_ids = [s["id"] for s in (segments.data or [])]

        store_count = len([v for v in (store_targets.data or []) if v.get("segment_id") in seg_ids]) if seg_ids else 0

        departments.append(DepartmentTargetSummary(
            department_type="store",
            department_name="店舗部門",
            has_targets=store_count > 0,
            target_count=store_count,
            last_updated=None,
        ))

    # 財務部門
    financial_targets = supabase.table("financial_data").select("id").eq(
        "month", month.isoformat()
    ).eq("is_target", True).execute()

    financial_count = len(financial_targets.data or [])

    departments.append(DepartmentTargetSummary(
        department_type="financial",
        department_name="財務部門",
        has_targets=financial_count > 0,
        target_count=financial_count,
        last_updated=None,
    ))

    # 通販部門
    try:
        ecommerce_targets = supabase.table("ecommerce_channel_sales").select("id").eq(
            "month", month.isoformat()
        ).eq("is_target", True).execute()
        ecommerce_count = len(ecommerce_targets.data or [])
    except Exception as e:
        # is_targetカラムが存在しない場合（マイグレーション未適用）
        print(f"Warning: ecommerce_channel_sales query failed: {e}")
        ecommerce_count = 0

    departments.append(DepartmentTargetSummary(
        department_type="ecommerce",
        department_name="通販部門",
        has_targets=ecommerce_count > 0,
        target_count=ecommerce_count,
        last_updated=None,
    ))

    return TargetOverview(
        fiscal_year=fiscal_year,
        month=month.isoformat(),
        departments=departments,
    )
