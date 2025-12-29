"""
地区別分析スキーマモジュール

地区別売上集計・目標設定のリクエスト/レスポンススキーマを定義する。
"""
from datetime import date
from typing import List, Optional

from pydantic import BaseModel, Field


# =============================================================================
# 地区マスタスキーマ
# =============================================================================

class Region(BaseModel):
    """地区情報"""
    id: str = Field(..., description="地区ID")
    name: str = Field(..., description="地区名")
    display_order: int = Field(0, description="表示順")


class RegionListResponse(BaseModel):
    """地区一覧レスポンス"""
    regions: List[Region] = Field(..., description="地区一覧")


# =============================================================================
# 店舗-地区マッピングスキーマ
# =============================================================================

class StoreRegionMapping(BaseModel):
    """店舗-地区マッピング"""
    segment_id: str = Field(..., description="店舗ID")
    segment_name: str = Field(..., description="店舗名")
    region_id: Optional[str] = Field(None, description="地区ID")
    region_name: Optional[str] = Field(None, description="地区名")


class StoreRegionMappingListResponse(BaseModel):
    """店舗-地区マッピング一覧レスポンス"""
    mappings: List[StoreRegionMapping] = Field(..., description="マッピング一覧")


class UpdateStoreRegionRequest(BaseModel):
    """店舗-地区マッピング更新リクエスト"""
    segment_id: str = Field(..., description="店舗ID")
    region_id: str = Field(..., description="地区ID")


class BulkUpdateStoreRegionRequest(BaseModel):
    """店舗-地区マッピング一括更新リクエスト"""
    mappings: List[UpdateStoreRegionRequest] = Field(..., description="マッピングリスト")


# =============================================================================
# 地区別集計スキーマ
# =============================================================================

class RegionalStoreData(BaseModel):
    """地区内店舗データ"""
    segment_id: str = Field(..., description="店舗ID")
    segment_name: str = Field(..., description="店舗名")
    sales: Optional[float] = Field(None, description="売上高")
    sales_previous_year: Optional[float] = Field(None, description="前年売上高")
    sales_yoy_rate: Optional[float] = Field(None, description="売上高前年比（%）")
    customers: Optional[int] = Field(None, description="客数")
    customers_previous_year: Optional[int] = Field(None, description="前年客数")
    customers_yoy_rate: Optional[float] = Field(None, description="客数前年比（%）")
    unit_price: Optional[float] = Field(None, description="客単価")
    unit_price_previous_year: Optional[float] = Field(None, description="前年客単価")


class RegionalProductData(BaseModel):
    """地区別商品データ"""
    product_name: str = Field(..., description="商品名")
    sales: Optional[float] = Field(None, description="売上高")
    sales_previous_year: Optional[float] = Field(None, description="前年売上高")
    sales_yoy_rate: Optional[float] = Field(None, description="売上高前年比（%）")


class RegionalSummaryData(BaseModel):
    """地区別集計データ"""
    region_id: str = Field(..., description="地区ID")
    region_name: str = Field(..., description="地区名")
    # 売上高
    total_sales: Optional[float] = Field(None, description="合計売上高")
    total_sales_previous_year: Optional[float] = Field(None, description="前年合計売上高")
    sales_yoy_rate: Optional[float] = Field(None, description="売上高前年比（%）")
    sales_yoy_diff: Optional[float] = Field(None, description="売上高前年差")
    # 目標
    target_sales: Optional[float] = Field(None, description="目標売上高")
    target_diff: Optional[float] = Field(None, description="目標差異")
    target_achievement_rate: Optional[float] = Field(None, description="目標達成率（%）")
    # 客数
    total_customers: Optional[int] = Field(None, description="合計客数")
    total_customers_previous_year: Optional[int] = Field(None, description="前年合計客数")
    customers_yoy_rate: Optional[float] = Field(None, description="客数前年比（%）")
    target_customers: Optional[int] = Field(None, description="目標客数")
    # 客単価
    avg_unit_price: Optional[float] = Field(None, description="平均客単価")
    avg_unit_price_previous_year: Optional[float] = Field(None, description="前年平均客単価")
    # 店舗データ
    stores: List[RegionalStoreData] = Field(default_factory=list, description="店舗別データ")
    # 商品データ
    products: List[RegionalProductData] = Field(default_factory=list, description="商品別データ")


class RegionalSummaryResponse(BaseModel):
    """地区別集計レスポンス"""
    period: str = Field(..., description="対象期間（YYYY-MM-DD）")
    period_type: str = Field(default="monthly", description="期間タイプ")
    fiscal_year: Optional[int] = Field(None, description="会計年度")
    regions: List[RegionalSummaryData] = Field(..., description="地区別データ")
    grand_total: Optional[RegionalSummaryData] = Field(None, description="全体合計")


# =============================================================================
# 地区別目標スキーマ
# =============================================================================

class RegionalTarget(BaseModel):
    """地区別目標"""
    region_id: str = Field(..., description="地区ID")
    region_name: Optional[str] = Field(None, description="地区名")
    month: str = Field(..., description="対象月（YYYY-MM-DD）")
    target_sales: Optional[float] = Field(None, description="目標売上高")
    target_customers: Optional[int] = Field(None, description="目標客数")


class RegionalTargetListResponse(BaseModel):
    """地区別目標一覧レスポンス"""
    month: str = Field(..., description="対象月")
    targets: List[RegionalTarget] = Field(..., description="目標一覧")


class SaveRegionalTargetRequest(BaseModel):
    """地区別目標保存リクエスト"""
    region_id: str = Field(..., description="地区ID")
    month: str = Field(..., description="対象月（YYYY-MM-DD）")
    target_sales: Optional[float] = Field(None, description="目標売上高")
    target_customers: Optional[int] = Field(None, description="目標客数")


class BulkSaveRegionalTargetRequest(BaseModel):
    """地区別目標一括保存リクエスト"""
    targets: List[SaveRegionalTargetRequest] = Field(..., description="目標リスト")
