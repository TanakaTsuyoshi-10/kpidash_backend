"""
財務・製造データスキーマ定義

財務データ・製造データのアップロードとレスポンス用のPydanticモデルを定義する。
"""
from datetime import date as date_type
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field


# =============================================================================
# 財務データスキーマ
# =============================================================================

class FinancialData(BaseModel):
    """財務データモデル"""
    fiscal_year: int = Field(..., description="会計年度")
    month: date_type = Field(..., description="対象月")
    is_target: bool = Field(default=False, description="目標値かどうか")

    # 売上高
    sales_total: Optional[Decimal] = Field(None, description="全社売上高")
    sales_store: Optional[Decimal] = Field(None, description="店舗部門売上高")
    sales_online: Optional[Decimal] = Field(None, description="通販部門売上高")

    # 原価・利益
    cost_of_sales: Optional[Decimal] = Field(None, description="売上原価")
    gross_profit: Optional[Decimal] = Field(None, description="売上総利益（粗利）")
    gross_profit_rate: Optional[Decimal] = Field(None, description="粗利率")

    # 販管費
    sg_and_a_total: Optional[Decimal] = Field(None, description="販管費合計")
    labor_cost: Optional[Decimal] = Field(None, description="人件費")
    labor_cost_rate: Optional[Decimal] = Field(None, description="人件費率")
    other_expenses: Optional[Decimal] = Field(None, description="その他経費")

    # 営業利益
    operating_profit: Optional[Decimal] = Field(None, description="営業利益")
    operating_profit_rate: Optional[Decimal] = Field(None, description="営業利益率")

    # キャッシュフロー
    cf_operating: Optional[Decimal] = Field(None, description="営業キャッシュフロー")
    cf_investing: Optional[Decimal] = Field(None, description="投資キャッシュフロー")
    cf_financing: Optional[Decimal] = Field(None, description="財務キャッシュフロー")
    cf_free: Optional[Decimal] = Field(None, description="フリーキャッシュフロー")

    # 目標値
    target_sales_total: Optional[Decimal] = Field(None, description="目標売上高")
    target_gross_profit: Optional[Decimal] = Field(None, description="目標粗利")
    target_operating_profit: Optional[Decimal] = Field(None, description="目標営業利益")


class FinancialParseError(BaseModel):
    """財務データパースエラー"""
    row: Optional[int] = Field(None, description="エラー行番号")
    column: Optional[str] = Field(None, description="エラー列名")
    message: str = Field(..., description="エラーメッセージ")
    value: Optional[str] = Field(None, description="エラー値")


class FinancialUploadResult(BaseModel):
    """財務データアップロード結果"""
    success: bool = Field(..., description="成功かどうか")
    message: str = Field(default="", description="結果メッセージ")
    month: Optional[str] = Field(None, description="対象月")
    data_type: Optional[str] = Field(None, description="データ区分（実績/予算）")
    action: Optional[str] = Field(None, description="実行アクション（inserted/updated）")
    errors: List[FinancialParseError] = Field(default_factory=list, description="エラー一覧")
    warnings: List[str] = Field(default_factory=list, description="警告一覧")


# =============================================================================
# 製造データスキーマ
# =============================================================================

class ManufacturingDayData(BaseModel):
    """製造日次データモデル"""
    date: date_type = Field(..., description="日付")
    production_batts: Optional[int] = Field(None, description="製造量（バット）")
    production_pieces: Optional[int] = Field(None, description="製造量（個）")
    workers_count: Optional[int] = Field(None, description="出勤者数")
    production_per_worker: Optional[Decimal] = Field(None, description="1人あたり製造量")
    paid_leave_hours: Optional[Decimal] = Field(None, description="有給取得時間")


class ManufacturingSummary(BaseModel):
    """製造月次サマリー"""
    total_batts: int = Field(default=0, description="月間製造量（バット）")
    total_pieces: int = Field(default=0, description="月間製造量（個）")
    total_workers: int = Field(default=0, description="月間延べ出勤者数")
    avg_production_per_worker: Optional[Decimal] = Field(None, description="平均1人あたり製造量")
    total_paid_leave_hours: Decimal = Field(default=Decimal("0"), description="月間有給取得時間")
    working_days: int = Field(default=0, description="稼働日数")


class ManufacturingParseError(BaseModel):
    """製造データパースエラー"""
    row: Optional[int] = Field(None, description="エラー行番号")
    column: Optional[str] = Field(None, description="エラー列名")
    message: str = Field(..., description="エラーメッセージ")
    value: Optional[str] = Field(None, description="エラー値")


class ManufacturingUploadResult(BaseModel):
    """製造データアップロード結果"""
    success: bool = Field(..., description="成功かどうか")
    message: str = Field(default="", description="結果メッセージ")
    month: Optional[str] = Field(None, description="対象月")
    imported_count: int = Field(default=0, description="インポート件数")
    summary: Optional[ManufacturingSummary] = Field(None, description="月次サマリー")
    errors: List[ManufacturingParseError] = Field(default_factory=list, description="エラー一覧")
    warnings: List[str] = Field(default_factory=list, description="警告一覧")


# =============================================================================
# サンプルデータスキーマ（テスト用）
# =============================================================================

class FinancialSampleData(BaseModel):
    """財務データサンプル"""
    template_structure: dict = Field(..., description="テンプレート構造")
    sample_values: dict = Field(..., description="サンプル値")


class ManufacturingSampleData(BaseModel):
    """製造データサンプル"""
    template_structure: dict = Field(..., description="テンプレート構造")
    sample_values: List[dict] = Field(..., description="サンプル値")


# =============================================================================
# 売上原価明細
# =============================================================================

class CostOfSalesDetail(BaseModel):
    """売上原価明細"""
    purchases: Decimal = Field(default=Decimal("0"), description="仕入高")
    raw_material_purchases: Decimal = Field(default=Decimal("0"), description="原材料仕入高")
    labor_cost: Decimal = Field(default=Decimal("0"), description="労務費")
    consumables: Decimal = Field(default=Decimal("0"), description="消耗品費")
    rent: Decimal = Field(default=Decimal("0"), description="賃借料")
    repairs: Decimal = Field(default=Decimal("0"), description="修繕費")
    utilities: Decimal = Field(default=Decimal("0"), description="水道光熱費")
    others: Decimal = Field(default=Decimal("0"), description="その他（差額計算）")
    total: Decimal = Field(default=Decimal("0"), description="売上原価合計")

    class Config:
        from_attributes = True


class CostOfSalesDetailInput(BaseModel):
    """売上原価明細入力"""
    period: date_type = Field(..., description="対象月")
    purchases: Optional[Decimal] = Field(None, description="仕入高")
    raw_material_purchases: Optional[Decimal] = Field(None, description="原材料仕入高")
    labor_cost: Optional[Decimal] = Field(None, description="労務費")
    consumables: Optional[Decimal] = Field(None, description="消耗品費")
    rent: Optional[Decimal] = Field(None, description="賃借料")
    repairs: Optional[Decimal] = Field(None, description="修繕費")
    utilities: Optional[Decimal] = Field(None, description="水道光熱費")
    is_target: bool = Field(default=False, description="目標フラグ")


# =============================================================================
# 販管費明細
# =============================================================================

class SGADetail(BaseModel):
    """販管費明細"""
    executive_compensation: Decimal = Field(default=Decimal("0"), description="役員報酬")
    personnel_cost: Decimal = Field(default=Decimal("0"), description="人件費（販管費）")
    delivery_cost: Decimal = Field(default=Decimal("0"), description="配送費")
    packaging_cost: Decimal = Field(default=Decimal("0"), description="包装費")
    payment_fees: Decimal = Field(default=Decimal("0"), description="支払手数料")
    freight_cost: Decimal = Field(default=Decimal("0"), description="荷造運賃費")
    sales_commission: Decimal = Field(default=Decimal("0"), description="販売手数料")
    advertising_cost: Decimal = Field(default=Decimal("0"), description="広告宣伝費")
    others: Decimal = Field(default=Decimal("0"), description="その他（差額計算）")
    total: Decimal = Field(default=Decimal("0"), description="販管費合計")

    class Config:
        from_attributes = True


class SGADetailInput(BaseModel):
    """販管費明細入力"""
    period: date_type = Field(..., description="対象月")
    executive_compensation: Optional[Decimal] = Field(None, description="役員報酬")
    personnel_cost: Optional[Decimal] = Field(None, description="人件費（販管費）")
    delivery_cost: Optional[Decimal] = Field(None, description="配送費")
    packaging_cost: Optional[Decimal] = Field(None, description="包装費")
    payment_fees: Optional[Decimal] = Field(None, description="支払手数料")
    freight_cost: Optional[Decimal] = Field(None, description="荷造運賃費")
    sales_commission: Optional[Decimal] = Field(None, description="販売手数料")
    advertising_cost: Optional[Decimal] = Field(None, description="広告宣伝費")
    is_target: bool = Field(default=False, description="目標フラグ")


# =============================================================================
# 財務サマリー（詳細込み）
# =============================================================================

class FinancialSummaryWithDetails(BaseModel):
    """財務サマリー（詳細展開可能）"""
    period: date_type = Field(..., description="対象月")

    # 売上高
    sales_total: Optional[Decimal] = Field(None, description="売上高合計")
    sales_store: Optional[Decimal] = Field(None, description="店舗部門売上高")
    sales_online: Optional[Decimal] = Field(None, description="通販部門売上高")

    # 売上原価（展開可能）
    cost_of_sales: Optional[Decimal] = Field(None, description="売上原価")
    cost_of_sales_detail: Optional[CostOfSalesDetail] = Field(None, description="売上原価明細")

    # 売上総利益
    gross_profit: Optional[Decimal] = Field(None, description="売上総利益")
    gross_profit_rate: Optional[Decimal] = Field(None, description="粗利率")

    # 販管費（展開可能）
    sga_total: Optional[Decimal] = Field(None, description="販管費合計")
    sga_detail: Optional[SGADetail] = Field(None, description="販管費明細")

    # 営業利益
    operating_profit: Optional[Decimal] = Field(None, description="営業利益")
    operating_profit_rate: Optional[Decimal] = Field(None, description="営業利益率")

    # キャッシュフロー
    cf_operating: Optional[Decimal] = Field(None, description="営業CF")
    cf_investing: Optional[Decimal] = Field(None, description="投資CF")
    cf_financing: Optional[Decimal] = Field(None, description="財務CF")
    cf_free: Optional[Decimal] = Field(None, description="フリーCF")

    class Config:
        from_attributes = True


# =============================================================================
# 店舗別収支
# =============================================================================

class StorePLSGADetail(BaseModel):
    """店舗別販管費明細"""
    personnel_cost: Decimal = Field(default=Decimal("0"), description="人件費")
    land_rent: Decimal = Field(default=Decimal("0"), description="地代家賃")
    lease_cost: Decimal = Field(default=Decimal("0"), description="賃借料")
    utilities: Decimal = Field(default=Decimal("0"), description="水道光熱費")
    others: Decimal = Field(default=Decimal("0"), description="その他（差額計算）")

    class Config:
        from_attributes = True


class StorePL(BaseModel):
    """店舗別収支"""
    store_id: str = Field(..., description="店舗ID")
    store_code: Optional[str] = Field(None, description="店舗コード")
    store_name: str = Field(..., description="店舗名")
    period: date_type = Field(..., description="対象月")

    # 収支項目（実績）
    sales: Decimal = Field(default=Decimal("0"), description="売上高")
    cost_of_sales: Decimal = Field(default=Decimal("0"), description="売上原価")
    gross_profit: Decimal = Field(default=Decimal("0"), description="売上総利益")
    sga_total: Decimal = Field(default=Decimal("0"), description="販管費合計")
    operating_profit: Decimal = Field(default=Decimal("0"), description="営業利益")

    # 目標値
    sales_target: Optional[Decimal] = Field(None, description="売上高目標")
    operating_profit_target: Optional[Decimal] = Field(None, description="営業利益目標")

    # 販管費明細（展開可能）
    sga_detail: Optional[StorePLSGADetail] = Field(None, description="販管費明細")

    # 前年比較
    sales_yoy_rate: Optional[Decimal] = Field(None, description="売上高前年比")
    operating_profit_yoy_rate: Optional[Decimal] = Field(None, description="営業利益前年比")

    # 達成率
    sales_achievement_rate: Optional[Decimal] = Field(None, description="売上高達成率（%）")
    operating_profit_achievement_rate: Optional[Decimal] = Field(None, description="営業利益達成率（%）")

    class Config:
        from_attributes = True


class StorePLInput(BaseModel):
    """店舗別収支入力"""
    store_code: str = Field(..., description="店舗コード")
    period: date_type = Field(..., description="対象月")
    sales: Decimal = Field(..., description="売上高")
    cost_of_sales: Decimal = Field(..., description="売上原価")
    sga_total: Decimal = Field(..., description="販管費合計")

    # 販管費明細（オプション）
    sga_personnel_cost: Optional[Decimal] = Field(None, description="人件費")
    sga_land_rent: Optional[Decimal] = Field(None, description="地代家賃")
    sga_lease_cost: Optional[Decimal] = Field(None, description="賃借料")
    sga_utilities: Optional[Decimal] = Field(None, description="水道光熱費")

    is_target: bool = Field(default=False, description="目標フラグ")


class StorePLListResponse(BaseModel):
    """店舗別収支一覧レスポンス"""
    period: date_type = Field(..., description="対象月")
    stores: List[StorePL] = Field(default_factory=list, description="店舗別収支リスト")

    # 合計
    total_sales: Decimal = Field(default=Decimal("0"), description="売上高合計")
    total_cost_of_sales: Decimal = Field(default=Decimal("0"), description="売上原価合計")
    total_gross_profit: Decimal = Field(default=Decimal("0"), description="売上総利益合計")
    total_sga: Decimal = Field(default=Decimal("0"), description="販管費合計")
    total_operating_profit: Decimal = Field(default=Decimal("0"), description="営業利益合計")

    class Config:
        from_attributes = True


# =============================================================================
# 財務分析レスポンス
# =============================================================================

class FinancialAnalysisResponse(BaseModel):
    """財務分析レスポンス"""
    period: date_type = Field(..., description="対象月")
    period_type: str = Field(..., description="期間タイプ（monthly/cumulative）")

    # 財務サマリー（今期）
    current: FinancialSummaryWithDetails = Field(..., description="今期データ")

    # 前年データ
    previous_year: Optional[FinancialSummaryWithDetails] = Field(None, description="前年データ")

    # 目標データ
    target: Optional[FinancialSummaryWithDetails] = Field(None, description="目標データ")

    # 前年比
    sales_yoy_rate: Optional[Decimal] = Field(None, description="売上高前年比")
    gross_profit_yoy_rate: Optional[Decimal] = Field(None, description="売上総利益前年比")
    operating_profit_yoy_rate: Optional[Decimal] = Field(None, description="営業利益前年比")

    # 達成率
    sales_achievement_rate: Optional[Decimal] = Field(None, description="売上高達成率（%）")
    gross_profit_achievement_rate: Optional[Decimal] = Field(None, description="売上総利益達成率（%）")
    operating_profit_achievement_rate: Optional[Decimal] = Field(None, description="営業利益達成率（%）")

    class Config:
        from_attributes = True
