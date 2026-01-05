"""
財務分析サービスモジュール

財務詳細データの取得・分析機能を提供する。
- 財務サマリー（売上原価・販管費の明細展開）
- 店舗別収支データ
- 前年比較
"""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, List, Dict, Any

from supabase import Client

from app.schemas.financial import (
    CostOfSalesDetail,
    SGADetail,
    FinancialSummaryWithDetails,
    FinancialAnalysisResponse,
    StorePL,
    StorePLSGADetail,
    StorePLListResponse,
)


# =============================================================================
# ヘルパー関数
# =============================================================================

def _calculate_yoy_rate(
    current: Optional[Decimal],
    previous: Optional[Decimal],
) -> Optional[Decimal]:
    """前年比（変化率）を計算する

    変化率 = (今期 - 前期) / 前期 × 100
    """
    if current is None or previous is None or previous == 0:
        return None
    result = ((current - previous) / previous) * 100
    return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _calculate_achievement_rate(
    actual: Optional[Decimal],
    target: Optional[Decimal],
) -> Optional[Decimal]:
    """達成率を計算する

    達成率 = 実績 / 目標 × 100
    """
    if actual is None or target is None or target == 0:
        return None
    result = (actual / target) * 100
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
# 売上原価明細取得
# =============================================================================

async def get_cost_of_sales_detail(
    supabase: Client,
    period: date,
    total_cost_of_sales: Optional[Decimal] = None,
    is_target: bool = False,
) -> Optional[CostOfSalesDetail]:
    """
    売上原価明細を取得する

    Args:
        supabase: Supabaseクライアント
        period: 対象月
        total_cost_of_sales: 売上原価合計（その他計算用）
        is_target: 目標フラグ

    Returns:
        CostOfSalesDetail or None
    """
    try:
        response = supabase.table("financial_cost_details").select("*").eq(
            "period", period.isoformat()
        ).eq("is_target", is_target).execute()

        if not response.data:
            return None

        row = response.data[0]

        # 明細項目を取得
        purchases = _to_decimal(row.get("purchases")) or Decimal("0")
        raw_material = _to_decimal(row.get("raw_material_purchases")) or Decimal("0")
        labor = _to_decimal(row.get("labor_cost")) or Decimal("0")
        consumables = _to_decimal(row.get("consumables")) or Decimal("0")
        rent = _to_decimal(row.get("rent")) or Decimal("0")
        repairs = _to_decimal(row.get("repairs")) or Decimal("0")
        utilities = _to_decimal(row.get("utilities")) or Decimal("0")

        # その他 = 売上原価合計 - 明細合計
        detail_total = purchases + raw_material + labor + consumables + rent + repairs + utilities
        others = Decimal("0")
        if total_cost_of_sales is not None:
            others = total_cost_of_sales - detail_total
            if others < 0:
                others = Decimal("0")

        return CostOfSalesDetail(
            purchases=purchases,
            raw_material_purchases=raw_material,
            labor_cost=labor,
            consumables=consumables,
            rent=rent,
            repairs=repairs,
            utilities=utilities,
            others=others,
            total=total_cost_of_sales or detail_total,
        )

    except Exception:
        return None


# =============================================================================
# 販管費明細取得
# =============================================================================

async def get_sga_detail(
    supabase: Client,
    period: date,
    total_sga: Optional[Decimal] = None,
    is_target: bool = False,
) -> Optional[SGADetail]:
    """
    販管費明細を取得する

    Args:
        supabase: Supabaseクライアント
        period: 対象月
        total_sga: 販管費合計（その他計算用）
        is_target: 目標フラグ

    Returns:
        SGADetail or None
    """
    try:
        response = supabase.table("financial_sga_details").select("*").eq(
            "period", period.isoformat()
        ).eq("is_target", is_target).execute()

        if not response.data:
            return None

        row = response.data[0]

        # 明細項目を取得
        executive = _to_decimal(row.get("executive_compensation")) or Decimal("0")
        personnel = _to_decimal(row.get("personnel_cost")) or Decimal("0")
        delivery = _to_decimal(row.get("delivery_cost")) or Decimal("0")
        packaging = _to_decimal(row.get("packaging_cost")) or Decimal("0")
        payment_fees = _to_decimal(row.get("payment_fees")) or Decimal("0")
        freight = _to_decimal(row.get("freight_cost")) or Decimal("0")
        sales_comm = _to_decimal(row.get("sales_commission")) or Decimal("0")
        advertising = _to_decimal(row.get("advertising_cost")) or Decimal("0")

        # その他 = 販管費合計 - 明細合計
        detail_total = (executive + personnel + delivery + packaging +
                        payment_fees + freight + sales_comm + advertising)
        others = Decimal("0")
        if total_sga is not None:
            others = total_sga - detail_total
            if others < 0:
                others = Decimal("0")

        return SGADetail(
            executive_compensation=executive,
            personnel_cost=personnel,
            delivery_cost=delivery,
            packaging_cost=packaging,
            payment_fees=payment_fees,
            freight_cost=freight,
            sales_commission=sales_comm,
            advertising_cost=advertising,
            others=others,
            total=total_sga or detail_total,
        )

    except Exception:
        return None


# =============================================================================
# 財務サマリー取得（詳細込み）
# =============================================================================

async def get_financial_summary_with_details(
    supabase: Client,
    period: date,
    is_target: bool = False,
) -> Optional[FinancialSummaryWithDetails]:
    """
    財務サマリーを詳細込みで取得する

    Args:
        supabase: Supabaseクライアント
        period: 対象月
        is_target: 目標フラグ

    Returns:
        FinancialSummaryWithDetails or None
    """
    try:
        # 財務データ本体を取得
        response = supabase.table("financial_data").select("*").eq(
            "month", period.isoformat()
        ).eq("is_target", is_target).execute()

        if not response.data:
            return None

        row = response.data[0]

        # 基本項目
        sales_total = _to_decimal(row.get("sales_total"))
        cost_of_sales = _to_decimal(row.get("cost_of_sales"))
        sga_total = _to_decimal(row.get("sg_and_a_total"))

        # 売上原価明細を取得
        cost_detail = await get_cost_of_sales_detail(
            supabase, period, cost_of_sales, is_target
        )

        # 販管費明細を取得
        sga_detail = await get_sga_detail(
            supabase, period, sga_total, is_target
        )

        return FinancialSummaryWithDetails(
            period=period,
            sales_total=sales_total,
            sales_store=_to_decimal(row.get("sales_store")),
            sales_online=_to_decimal(row.get("sales_online")),
            cost_of_sales=cost_of_sales,
            cost_of_sales_detail=cost_detail,
            gross_profit=_to_decimal(row.get("gross_profit")),
            gross_profit_rate=_to_decimal(row.get("gross_profit_rate")),
            sga_total=sga_total,
            sga_detail=sga_detail,
            operating_profit=_to_decimal(row.get("operating_profit")),
            operating_profit_rate=_to_decimal(row.get("operating_profit_rate")),
            cf_operating=_to_decimal(row.get("cf_operating")),
            cf_investing=_to_decimal(row.get("cf_investing")),
            cf_financing=_to_decimal(row.get("cf_financing")),
            cf_free=_to_decimal(row.get("cf_free")),
        )

    except Exception as e:
        raise Exception(f"財務サマリーの取得に失敗しました: {str(e)}")


# =============================================================================
# 財務分析（前年比較込み）
# =============================================================================

async def get_financial_analysis(
    supabase: Client,
    period: date,
    period_type: str = "monthly",
) -> FinancialAnalysisResponse:
    """
    財務分析データを取得する（前年比較・目標達成率込み）

    Args:
        supabase: Supabaseクライアント
        period: 対象月
        period_type: 期間タイプ（monthly/cumulative）

    Returns:
        FinancialAnalysisResponse
    """
    # 今期データを取得（実績）
    current = await get_financial_summary_with_details(supabase, period, is_target=False)

    if current is None:
        # データがない場合はデフォルト値
        current = FinancialSummaryWithDetails(period=period)

    # 前年同月データを取得
    prev_period = date(period.year - 1, period.month, 1)
    previous_year = await get_financial_summary_with_details(supabase, prev_period, is_target=False)

    # 目標データを取得
    target = await get_financial_summary_with_details(supabase, period, is_target=True)

    # 前年比計算
    sales_yoy = _calculate_yoy_rate(current.sales_total, previous_year.sales_total if previous_year else None)
    gross_profit_yoy = _calculate_yoy_rate(current.gross_profit, previous_year.gross_profit if previous_year else None)
    operating_profit_yoy = _calculate_yoy_rate(current.operating_profit, previous_year.operating_profit if previous_year else None)

    # 達成率計算
    sales_achievement = _calculate_achievement_rate(current.sales_total, target.sales_total if target else None)
    gross_profit_achievement = _calculate_achievement_rate(current.gross_profit, target.gross_profit if target else None)
    operating_profit_achievement = _calculate_achievement_rate(current.operating_profit, target.operating_profit if target else None)

    return FinancialAnalysisResponse(
        period=period,
        period_type=period_type,
        current=current,
        previous_year=previous_year,
        target=target,
        sales_yoy_rate=sales_yoy,
        gross_profit_yoy_rate=gross_profit_yoy,
        operating_profit_yoy_rate=operating_profit_yoy,
        sales_achievement_rate=sales_achievement,
        gross_profit_achievement_rate=gross_profit_achievement,
        operating_profit_achievement_rate=operating_profit_achievement,
    )


# =============================================================================
# 店舗別収支取得
# =============================================================================

async def get_store_pl_list(
    supabase: Client,
    period: date,
    department_slug: str = "store",
    is_target: bool = False,
) -> StorePLListResponse:
    """
    店舗別収支一覧を取得する（目標・達成率込み）

    Args:
        supabase: Supabaseクライアント
        period: 対象月
        department_slug: 部門スラッグ
        is_target: 目標フラグ

    Returns:
        StorePLListResponse
    """
    try:
        # 部門IDを取得
        dept_response = supabase.table("departments").select("id").eq(
            "slug", department_slug
        ).execute()

        if not dept_response.data:
            return StorePLListResponse(period=period, stores=[])

        dept_id = dept_response.data[0]["id"]

        # 店舗一覧を取得
        segments_response = supabase.table("segments").select(
            "id, code, name"
        ).eq("department_id", dept_id).order("code").execute()

        if not segments_response.data:
            return StorePLListResponse(period=period, stores=[])

        segment_map = {s["id"]: s for s in segments_response.data}
        segment_ids = list(segment_map.keys())

        # 店舗別収支データを取得（実績）
        pl_response = supabase.table("store_pl").select(
            "*, store_pl_sga_details(*)"
        ).eq("period", period.isoformat()).eq(
            "is_target", False
        ).in_("segment_id", segment_ids).execute()

        pl_map = {p["segment_id"]: p for p in (pl_response.data or [])}

        # 目標データを取得
        target_response = supabase.table("store_pl").select(
            "segment_id, sales, operating_profit"
        ).eq("period", period.isoformat()).eq(
            "is_target", True
        ).in_("segment_id", segment_ids).execute()

        target_map = {p["segment_id"]: p for p in (target_response.data or [])}

        # 前年データを取得（前年比計算用）
        prev_period = date(period.year - 1, period.month, 1)
        prev_response = supabase.table("store_pl").select("*").eq(
            "period", prev_period.isoformat()
        ).eq("is_target", False).in_("segment_id", segment_ids).execute()

        prev_map = {p["segment_id"]: p for p in (prev_response.data or [])}

        # レスポンス構築
        stores: List[StorePL] = []
        total_sales = Decimal("0")
        total_cost = Decimal("0")
        total_gross = Decimal("0")
        total_sga = Decimal("0")
        total_op = Decimal("0")

        for segment_id, segment in segment_map.items():
            pl_data = pl_map.get(segment_id)
            target_data = target_map.get(segment_id)
            prev_data = prev_map.get(segment_id)

            if pl_data:
                sales = _to_decimal(pl_data.get("sales")) or Decimal("0")
                cost = _to_decimal(pl_data.get("cost_of_sales")) or Decimal("0")
                gross = _to_decimal(pl_data.get("gross_profit")) or (sales - cost)
                sga = _to_decimal(pl_data.get("sga_total")) or Decimal("0")
                op = _to_decimal(pl_data.get("operating_profit")) or (gross - sga)

                # 目標値
                sales_target = _to_decimal(target_data.get("sales")) if target_data else None
                op_target = _to_decimal(target_data.get("operating_profit")) if target_data else None

                # 販管費明細
                sga_detail = None
                sga_details_list = pl_data.get("store_pl_sga_details", [])
                if sga_details_list:
                    sd = sga_details_list[0] if isinstance(sga_details_list, list) else sga_details_list
                    personnel = _to_decimal(sd.get("personnel_cost")) or Decimal("0")
                    land_rent = _to_decimal(sd.get("land_rent")) or Decimal("0")
                    lease = _to_decimal(sd.get("lease_cost")) or Decimal("0")
                    utilities = _to_decimal(sd.get("utilities")) or Decimal("0")
                    detail_total = personnel + land_rent + lease + utilities
                    others = sga - detail_total if sga > detail_total else Decimal("0")

                    sga_detail = StorePLSGADetail(
                        personnel_cost=personnel,
                        land_rent=land_rent,
                        lease_cost=lease,
                        utilities=utilities,
                        others=others,
                    )

                # 前年比
                prev_sales = _to_decimal(prev_data.get("sales")) if prev_data else None
                prev_op = _to_decimal(prev_data.get("operating_profit")) if prev_data else None
                sales_yoy = _calculate_yoy_rate(sales, prev_sales)
                op_yoy = _calculate_yoy_rate(op, prev_op)

                # 達成率
                sales_achievement = _calculate_achievement_rate(sales, sales_target)
                op_achievement = _calculate_achievement_rate(op, op_target)

                stores.append(StorePL(
                    store_id=str(segment_id),
                    store_code=segment.get("code"),
                    store_name=segment.get("name", ""),
                    period=period,
                    sales=sales,
                    cost_of_sales=cost,
                    gross_profit=gross,
                    sga_total=sga,
                    operating_profit=op,
                    sales_target=sales_target,
                    operating_profit_target=op_target,
                    sga_detail=sga_detail,
                    sales_yoy_rate=sales_yoy,
                    operating_profit_yoy_rate=op_yoy,
                    sales_achievement_rate=sales_achievement,
                    operating_profit_achievement_rate=op_achievement,
                ))

                total_sales += sales
                total_cost += cost
                total_gross += gross
                total_sga += sga
                total_op += op
            else:
                # データがない店舗も一覧に含める
                # 目標値のみある場合も取得
                sales_target = _to_decimal(target_data.get("sales")) if target_data else None
                op_target = _to_decimal(target_data.get("operating_profit")) if target_data else None

                stores.append(StorePL(
                    store_id=str(segment_id),
                    store_code=segment.get("code"),
                    store_name=segment.get("name", ""),
                    period=period,
                    sales=Decimal("0"),
                    cost_of_sales=Decimal("0"),
                    gross_profit=Decimal("0"),
                    sga_total=Decimal("0"),
                    operating_profit=Decimal("0"),
                    sales_target=sales_target,
                    operating_profit_target=op_target,
                ))

        return StorePLListResponse(
            period=period,
            stores=stores,
            total_sales=total_sales,
            total_cost_of_sales=total_cost,
            total_gross_profit=total_gross,
            total_sga=total_sga,
            total_operating_profit=total_op,
        )

    except Exception as e:
        raise Exception(f"店舗別収支の取得に失敗しました: {str(e)}")


# =============================================================================
# 特定店舗の収支取得（店舗詳細ページ用）
# =============================================================================

async def get_store_pl_by_segment_id(
    supabase: Client,
    segment_id: str,
    period: date,
    is_target: bool = False,
) -> Optional[StorePL]:
    """
    特定店舗の収支を取得する

    Args:
        supabase: Supabaseクライアント
        segment_id: 店舗ID
        period: 対象月
        is_target: 目標フラグ

    Returns:
        StorePL or None
    """
    try:
        # 店舗情報を取得
        seg_response = supabase.table("segments").select(
            "id, code, name"
        ).eq("id", segment_id).execute()

        if not seg_response.data:
            return None

        segment = seg_response.data[0]

        # 店舗別収支データを取得
        pl_response = supabase.table("store_pl").select(
            "*, store_pl_sga_details(*)"
        ).eq("segment_id", segment_id).eq(
            "period", period.isoformat()
        ).eq("is_target", is_target).execute()

        if not pl_response.data:
            return StorePL(
                store_id=str(segment_id),
                store_code=segment.get("code"),
                store_name=segment.get("name", ""),
                period=period,
            )

        pl_data = pl_response.data[0]

        # 前年データを取得
        prev_period = date(period.year - 1, period.month, 1)
        prev_response = supabase.table("store_pl").select("*").eq(
            "segment_id", segment_id
        ).eq("period", prev_period.isoformat()).eq("is_target", is_target).execute()

        prev_data = prev_response.data[0] if prev_response.data else None

        # データ変換
        sales = _to_decimal(pl_data.get("sales")) or Decimal("0")
        cost = _to_decimal(pl_data.get("cost_of_sales")) or Decimal("0")
        gross = _to_decimal(pl_data.get("gross_profit")) or (sales - cost)
        sga = _to_decimal(pl_data.get("sga_total")) or Decimal("0")
        op = _to_decimal(pl_data.get("operating_profit")) or (gross - sga)

        # 販管費明細
        sga_detail = None
        sga_details_list = pl_data.get("store_pl_sga_details", [])
        if sga_details_list:
            sd = sga_details_list[0] if isinstance(sga_details_list, list) else sga_details_list
            personnel = _to_decimal(sd.get("personnel_cost")) or Decimal("0")
            land_rent = _to_decimal(sd.get("land_rent")) or Decimal("0")
            lease = _to_decimal(sd.get("lease_cost")) or Decimal("0")
            utilities = _to_decimal(sd.get("utilities")) or Decimal("0")
            detail_total = personnel + land_rent + lease + utilities
            others = sga - detail_total if sga > detail_total else Decimal("0")

            sga_detail = StorePLSGADetail(
                personnel_cost=personnel,
                land_rent=land_rent,
                lease_cost=lease,
                utilities=utilities,
                others=others,
            )

        # 前年比
        prev_sales = _to_decimal(prev_data.get("sales")) if prev_data else None
        prev_op = _to_decimal(prev_data.get("operating_profit")) if prev_data else None
        sales_yoy = _calculate_yoy_rate(sales, prev_sales)
        op_yoy = _calculate_yoy_rate(op, prev_op)

        return StorePL(
            store_id=str(segment_id),
            store_code=segment.get("code"),
            store_name=segment.get("name", ""),
            period=period,
            sales=sales,
            cost_of_sales=cost,
            gross_profit=gross,
            sga_total=sga,
            operating_profit=op,
            sga_detail=sga_detail,
            sales_yoy_rate=sales_yoy,
            operating_profit_yoy_rate=op_yoy,
        )

    except Exception as e:
        raise Exception(f"店舗収支の取得に失敗しました: {str(e)}")
