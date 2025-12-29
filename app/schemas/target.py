"""
目標設定スキーマ

部門別目標設定のPydanticスキーマを定義する。
"""
from datetime import date as date_type
from decimal import Decimal
from typing import Optional, List, Dict, Any
from enum import Enum

from pydantic import BaseModel, Field


# =============================================================================
# Enum定義
# =============================================================================

class DepartmentTypeEnum(str, Enum):
    """部門種類"""
    STORE = "store"
    ECOMMERCE = "ecommerce"
    FINANCIAL = "financial"


# =============================================================================
# 共通スキーマ
# =============================================================================

class TargetValueBase(BaseModel):
    """目標値ベース"""
    value: Optional[Decimal] = Field(None, description="目標値")
    last_year_actual: Optional[Decimal] = Field(None, description="前年実績")
    yoy_rate: Optional[Decimal] = Field(None, description="前年比（%）")


class TargetSettingResult(BaseModel):
    """目標設定結果"""
    created_count: int = Field(default=0, description="新規作成件数")
    updated_count: int = Field(default=0, description="更新件数")
    errors: List[str] = Field(default_factory=list, description="エラーリスト")


# =============================================================================
# 店舗部門 目標スキーマ
# =============================================================================

class StoreTargetValue(BaseModel):
    """店舗目標値（KPI別）"""
    kpi_id: str = Field(..., description="KPI ID")
    target_id: Optional[str] = Field(None, description="目標値ID（既存の場合）")
    value: Optional[Decimal] = Field(None, description="目標値")
    last_year_actual: Optional[Decimal] = Field(None, description="前年実績")
    yoy_rate: Optional[Decimal] = Field(None, description="前年比（%）")


class StoreTargetRow(BaseModel):
    """店舗別目標行"""
    segment_id: str = Field(..., description="店舗ID")
    segment_code: str = Field(..., description="店舗コード")
    segment_name: str = Field(..., description="店舗名")
    values: Dict[str, StoreTargetValue] = Field(default_factory=dict, description="KPI別目標値")


class StoreTargetKPI(BaseModel):
    """店舗目標KPI定義"""
    id: str = Field(..., description="KPI ID")
    name: str = Field(..., description="KPI名")
    unit: Optional[str] = Field(None, description="単位")


class StoreTargetMatrix(BaseModel):
    """店舗目標マトリックス"""
    fiscal_year: int = Field(..., description="年度")
    month: str = Field(..., description="対象月")
    kpis: List[StoreTargetKPI] = Field(default_factory=list, description="KPI一覧")
    rows: List[StoreTargetRow] = Field(default_factory=list, description="店舗別目標")


class StoreTargetInput(BaseModel):
    """店舗目標入力"""
    segment_id: str = Field(..., description="店舗ID")
    kpi_id: str = Field(..., description="KPI ID")
    value: Decimal = Field(..., description="目標値")


class StoreTargetBulkInput(BaseModel):
    """店舗目標一括入力"""
    month: date_type = Field(..., description="対象月")
    targets: List[StoreTargetInput] = Field(..., description="目標値リスト")


# =============================================================================
# 財務部門 目標スキーマ
# =============================================================================

class FinancialTargetSummary(BaseModel):
    """財務目標サマリー"""
    # 売上・利益
    sales_total: Optional[Decimal] = Field(None, description="売上高合計")
    sales_store: Optional[Decimal] = Field(None, description="店舗売上高")
    sales_online: Optional[Decimal] = Field(None, description="通販売上高")
    cost_of_sales: Optional[Decimal] = Field(None, description="売上原価")
    gross_profit: Optional[Decimal] = Field(None, description="売上総利益")
    sga_total: Optional[Decimal] = Field(None, description="販管費合計")
    operating_profit: Optional[Decimal] = Field(None, description="営業利益")


class FinancialCostTarget(BaseModel):
    """売上原価明細目標"""
    purchases: Optional[Decimal] = Field(None, description="仕入高")
    raw_material_purchases: Optional[Decimal] = Field(None, description="原材料仕入高")
    labor_cost: Optional[Decimal] = Field(None, description="労務費")
    consumables: Optional[Decimal] = Field(None, description="消耗品費")
    rent: Optional[Decimal] = Field(None, description="賃借料")
    repairs: Optional[Decimal] = Field(None, description="修繕費")
    utilities: Optional[Decimal] = Field(None, description="水道光熱費")


class FinancialSGATarget(BaseModel):
    """販管費明細目標"""
    executive_compensation: Optional[Decimal] = Field(None, description="役員報酬")
    personnel_cost: Optional[Decimal] = Field(None, description="人件費")
    delivery_cost: Optional[Decimal] = Field(None, description="配送費")
    packaging_cost: Optional[Decimal] = Field(None, description="包装費")
    payment_fees: Optional[Decimal] = Field(None, description="支払手数料")
    freight_cost: Optional[Decimal] = Field(None, description="荷造運賃費")
    sales_commission: Optional[Decimal] = Field(None, description="販売手数料")
    advertising_cost: Optional[Decimal] = Field(None, description="広告宣伝費")


class FinancialTargetItem(BaseModel):
    """財務目標項目（比較付き）"""
    field_name: str = Field(..., description="フィールド名")
    display_name: str = Field(..., description="表示名")
    target_value: Optional[Decimal] = Field(None, description="目標値")
    last_year_actual: Optional[Decimal] = Field(None, description="前年実績")
    sales_ratio: Optional[Decimal] = Field(None, description="売上対比（%）")
    yoy_rate: Optional[Decimal] = Field(None, description="前年比（%）")


class FinancialTargetResponse(BaseModel):
    """財務目標レスポンス"""
    fiscal_year: int = Field(..., description="年度")
    month: str = Field(..., description="対象月")

    # サマリー項目
    summary_items: List[FinancialTargetItem] = Field(default_factory=list, description="サマリー項目")

    # 売上原価明細
    cost_items: List[FinancialTargetItem] = Field(default_factory=list, description="売上原価明細")

    # 販管費明細
    sga_items: List[FinancialTargetItem] = Field(default_factory=list, description="販管費明細")


class FinancialTargetInput(BaseModel):
    """財務目標入力"""
    month: date_type = Field(..., description="対象月")

    # サマリー
    summary: Optional[FinancialTargetSummary] = Field(None, description="サマリー目標")

    # 売上原価明細
    cost_details: Optional[FinancialCostTarget] = Field(None, description="売上原価明細目標")

    # 販管費明細
    sga_details: Optional[FinancialSGATarget] = Field(None, description="販管費明細目標")


# =============================================================================
# 通販部門 目標スキーマ
# =============================================================================

class EcommerceChannelTarget(BaseModel):
    """チャネル別目標"""
    channel: str = Field(..., description="チャネル名")
    target_sales: Optional[Decimal] = Field(None, description="目標売上")
    target_buyers: Optional[int] = Field(None, description="目標購入者数")
    last_year_sales: Optional[Decimal] = Field(None, description="前年売上")
    last_year_buyers: Optional[int] = Field(None, description="前年購入者数")
    yoy_sales_rate: Optional[Decimal] = Field(None, description="売上前年比（%）")
    yoy_buyers_rate: Optional[Decimal] = Field(None, description="購入者数前年比（%）")


class EcommerceCustomerTarget(BaseModel):
    """顧客統計目標"""
    new_customers: Optional[int] = Field(None, description="新規顧客数目標")
    repeat_customers: Optional[int] = Field(None, description="リピーター数目標")
    last_year_new: Optional[int] = Field(None, description="前年新規顧客数")
    last_year_repeat: Optional[int] = Field(None, description="前年リピーター数")
    yoy_new_rate: Optional[Decimal] = Field(None, description="新規前年比（%）")
    yoy_repeat_rate: Optional[Decimal] = Field(None, description="リピーター前年比（%）")


class EcommerceTargetResponse(BaseModel):
    """通販目標レスポンス"""
    fiscal_year: int = Field(..., description="年度")
    month: str = Field(..., description="対象月")

    # 売上サマリー
    total_target_sales: Optional[Decimal] = Field(None, description="売上目標合計")
    last_year_total_sales: Optional[Decimal] = Field(None, description="前年売上合計")
    yoy_total_rate: Optional[Decimal] = Field(None, description="売上前年比（%）")

    # チャネル別目標
    channel_targets: List[EcommerceChannelTarget] = Field(default_factory=list, description="チャネル別目標")

    # 顧客統計目標
    customer_target: Optional[EcommerceCustomerTarget] = Field(None, description="顧客統計目標")


class EcommerceChannelTargetInput(BaseModel):
    """チャネル別目標入力"""
    channel: str = Field(..., description="チャネル名")
    sales: Optional[Decimal] = Field(None, description="売上目標")
    buyers: Optional[int] = Field(None, description="購入者数目標")


class EcommerceTargetInput(BaseModel):
    """通販目標入力"""
    month: date_type = Field(..., description="対象月")

    # チャネル別目標
    channel_targets: Optional[List[EcommerceChannelTargetInput]] = Field(None, description="チャネル別目標")

    # 顧客統計
    new_customers: Optional[int] = Field(None, description="新規顧客数目標")
    repeat_customers: Optional[int] = Field(None, description="リピーター数目標")


# =============================================================================
# 統合レスポンス
# =============================================================================

class DepartmentTargetSummary(BaseModel):
    """部門別目標サマリー（一覧画面用）"""
    department_type: str = Field(..., description="部門種類")
    department_name: str = Field(..., description="部門名")
    has_targets: bool = Field(default=False, description="目標設定済み")
    target_count: int = Field(default=0, description="設定済み項目数")
    last_updated: Optional[str] = Field(None, description="最終更新日時")


class TargetOverview(BaseModel):
    """目標設定概要"""
    fiscal_year: int = Field(..., description="年度")
    month: str = Field(..., description="対象月")
    departments: List[DepartmentTargetSummary] = Field(default_factory=list, description="部門別サマリー")
