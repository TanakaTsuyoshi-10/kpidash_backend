"""
通販分析スキーマモジュール

通販チャネル別・商品別・顧客別実績およびHPアクセス数の
リクエスト/レスポンススキーマを定義する。
"""
from datetime import date
from typing import List, Optional

from pydantic import BaseModel, Field


# =============================================================================
# チャネル別実績スキーマ
# =============================================================================

class ChannelData(BaseModel):
    """チャネル別実績データ"""
    channel: str = Field(..., description="チャネル名: EC, 電話, FAX, 店舗受付")
    sales: Optional[float] = Field(None, description="売上高")
    sales_target: Optional[float] = Field(None, description="売上高目標")
    sales_achievement_rate: Optional[float] = Field(None, description="売上高達成率（%）")
    sales_previous_year: Optional[float] = Field(None, description="前年売上高")
    sales_two_years_ago: Optional[float] = Field(None, description="前々年売上高")
    sales_yoy: Optional[float] = Field(None, description="売上高前年比（%）")
    sales_yoy_two_years: Optional[float] = Field(None, description="売上高前々年比（%）")
    buyers: Optional[int] = Field(None, description="購入者数")
    buyers_target: Optional[int] = Field(None, description="購入者数目標")
    buyers_achievement_rate: Optional[float] = Field(None, description="購入者数達成率（%）")
    buyers_previous_year: Optional[int] = Field(None, description="前年購入者数")
    buyers_two_years_ago: Optional[int] = Field(None, description="前々年購入者数")
    buyers_yoy: Optional[float] = Field(None, description="購入者数前年比（%）")
    buyers_yoy_two_years: Optional[float] = Field(None, description="購入者数前々年比（%）")
    unit_price: Optional[float] = Field(None, description="客単価")
    unit_price_previous_year: Optional[float] = Field(None, description="前年客単価")
    unit_price_two_years_ago: Optional[float] = Field(None, description="前々年客単価")
    unit_price_yoy: Optional[float] = Field(None, description="客単価前年比（%）")
    unit_price_yoy_two_years: Optional[float] = Field(None, description="客単価前々年比（%）")


class ChannelTotals(BaseModel):
    """チャネル合計データ"""
    sales: Optional[float] = Field(None, description="売上高合計")
    sales_target: Optional[float] = Field(None, description="売上高目標合計")
    sales_achievement_rate: Optional[float] = Field(None, description="売上高達成率（%）")
    sales_previous_year: Optional[float] = Field(None, description="前年売上高合計")
    sales_two_years_ago: Optional[float] = Field(None, description="前々年売上高合計")
    sales_yoy: Optional[float] = Field(None, description="売上高前年比（%）")
    sales_yoy_two_years: Optional[float] = Field(None, description="売上高前々年比（%）")
    buyers: Optional[int] = Field(None, description="購入者数合計")
    buyers_target: Optional[int] = Field(None, description="購入者数目標合計")
    buyers_achievement_rate: Optional[float] = Field(None, description="購入者数達成率（%）")
    buyers_previous_year: Optional[int] = Field(None, description="前年購入者数合計")
    buyers_two_years_ago: Optional[int] = Field(None, description="前々年購入者数合計")
    buyers_yoy: Optional[float] = Field(None, description="購入者数前年比（%）")
    buyers_yoy_two_years: Optional[float] = Field(None, description="購入者数前々年比（%）")
    unit_price: Optional[float] = Field(None, description="客単価（平均）")
    unit_price_previous_year: Optional[float] = Field(None, description="前年客単価（平均）")
    unit_price_two_years_ago: Optional[float] = Field(None, description="前々年客単価（平均）")
    unit_price_yoy: Optional[float] = Field(None, description="客単価前年比（%）")
    unit_price_yoy_two_years: Optional[float] = Field(None, description="客単価前々年比（%）")


class ChannelSummaryResponse(BaseModel):
    """チャネル別実績レスポンス"""
    period: str = Field(..., description="対象期間（YYYY-MM-DD）")
    period_type: str = Field(default="monthly", description="期間タイプ")
    fiscal_year: Optional[int] = Field(None, description="会計年度")
    channels: List[ChannelData] = Field(..., description="チャネル別データ")
    totals: ChannelTotals = Field(..., description="合計データ")


# =============================================================================
# 商品別実績スキーマ
# =============================================================================

class ProductData(BaseModel):
    """商品別実績データ"""
    product_name: str = Field(..., description="商品名")
    product_category: Optional[str] = Field(None, description="商品カテゴリ")
    sales: Optional[float] = Field(None, description="売上高")
    sales_previous_year: Optional[float] = Field(None, description="前年売上高")
    sales_two_years_ago: Optional[float] = Field(None, description="前々年売上高")
    sales_yoy: Optional[float] = Field(None, description="売上高前年比（%）")
    sales_yoy_two_years: Optional[float] = Field(None, description="売上高前々年比（%）")
    quantity: Optional[int] = Field(None, description="販売数量")
    quantity_previous_year: Optional[int] = Field(None, description="前年販売数量")
    quantity_two_years_ago: Optional[int] = Field(None, description="前々年販売数量")


class ProductSummaryResponse(BaseModel):
    """商品別実績レスポンス"""
    period: str = Field(..., description="対象期間（YYYY-MM-DD）")
    period_type: str = Field(default="monthly", description="期間タイプ")
    fiscal_year: Optional[int] = Field(None, description="会計年度")
    products: List[ProductData] = Field(..., description="商品別データ")
    total_sales: Optional[float] = Field(None, description="売上高合計")
    total_sales_previous_year: Optional[float] = Field(None, description="前年売上高合計")
    total_sales_two_years_ago: Optional[float] = Field(None, description="前々年売上高合計")


# =============================================================================
# 顧客別実績スキーマ
# =============================================================================

class CustomerStatsData(BaseModel):
    """顧客別実績データ"""
    new_customers: Optional[int] = Field(None, description="新規顧客数")
    new_customers_target: Optional[int] = Field(None, description="新規顧客数目標")
    new_customers_achievement_rate: Optional[float] = Field(None, description="新規顧客数達成率（%）")
    new_customers_previous_year: Optional[int] = Field(None, description="前年新規顧客数")
    new_customers_two_years_ago: Optional[int] = Field(None, description="前々年新規顧客数")
    new_customers_yoy: Optional[float] = Field(None, description="新規顧客数前年比（%）")
    new_customers_yoy_two_years: Optional[float] = Field(None, description="新規顧客数前々年比（%）")
    repeat_customers: Optional[int] = Field(None, description="リピーター数")
    repeat_customers_target: Optional[int] = Field(None, description="リピーター数目標")
    repeat_customers_achievement_rate: Optional[float] = Field(None, description="リピーター数達成率（%）")
    repeat_customers_previous_year: Optional[int] = Field(None, description="前年リピーター数")
    repeat_customers_two_years_ago: Optional[int] = Field(None, description="前々年リピーター数")
    repeat_customers_yoy: Optional[float] = Field(None, description="リピーター数前年比（%）")
    repeat_customers_yoy_two_years: Optional[float] = Field(None, description="リピーター数前々年比（%）")
    total_customers: Optional[int] = Field(None, description="合計顧客数")
    total_customers_target: Optional[int] = Field(None, description="合計顧客数目標")
    total_customers_achievement_rate: Optional[float] = Field(None, description="合計顧客数達成率（%）")
    total_customers_previous_year: Optional[int] = Field(None, description="前年合計顧客数")
    total_customers_two_years_ago: Optional[int] = Field(None, description="前々年合計顧客数")
    repeat_rate: Optional[float] = Field(None, description="リピート率（%）")
    repeat_rate_previous_year: Optional[float] = Field(None, description="前年リピート率（%）")


class CustomerSummaryResponse(BaseModel):
    """顧客別実績レスポンス"""
    period: str = Field(..., description="対象期間（YYYY-MM-DD）")
    period_type: str = Field(default="monthly", description="期間タイプ")
    fiscal_year: Optional[int] = Field(None, description="会計年度")
    data: CustomerStatsData = Field(..., description="顧客統計データ")


# =============================================================================
# HPアクセス数スキーマ
# =============================================================================

class WebsiteStatsData(BaseModel):
    """HPアクセス数データ"""
    page_views: Optional[int] = Field(None, description="ページビュー数")
    page_views_previous_year: Optional[int] = Field(None, description="前年ページビュー数")
    page_views_two_years_ago: Optional[int] = Field(None, description="前々年ページビュー数")
    page_views_yoy: Optional[float] = Field(None, description="ページビュー数前年比（%）")
    page_views_yoy_two_years: Optional[float] = Field(None, description="ページビュー数前々年比（%）")
    unique_visitors: Optional[int] = Field(None, description="ユニークビジター数")
    unique_visitors_previous_year: Optional[int] = Field(None, description="前年ユニークビジター数")
    unique_visitors_two_years_ago: Optional[int] = Field(None, description="前々年ユニークビジター数")
    unique_visitors_yoy: Optional[float] = Field(None, description="ユニークビジター数前年比（%）")
    unique_visitors_yoy_two_years: Optional[float] = Field(None, description="ユニークビジター数前々年比（%）")
    sessions: Optional[int] = Field(None, description="セッション数")
    sessions_previous_year: Optional[int] = Field(None, description="前年セッション数")
    sessions_two_years_ago: Optional[int] = Field(None, description="前々年セッション数")
    sessions_yoy: Optional[float] = Field(None, description="セッション数前年比（%）")
    sessions_yoy_two_years: Optional[float] = Field(None, description="セッション数前々年比（%）")


class WebsiteStatsResponse(BaseModel):
    """HPアクセス数レスポンス"""
    period: str = Field(..., description="対象期間（YYYY-MM-DD）")
    period_type: str = Field(default="monthly", description="期間タイプ")
    fiscal_year: Optional[int] = Field(None, description="会計年度")
    data: WebsiteStatsData = Field(..., description="アクセス統計データ")


# =============================================================================
# 推移データスキーマ（グラフ用）
# =============================================================================

class TrendSeriesData(BaseModel):
    """推移データ系列（フロントエンドグラフ互換形式）"""
    name: str = Field(..., description="系列名（チャネル名、商品名等）")
    values: List[Optional[float]] = Field(..., description="月次値の配列")


class TrendResponse(BaseModel):
    """推移データレスポンス"""
    fiscal_year: int = Field(..., description="会計年度")
    metric: str = Field(..., description="指標タイプ")
    months: List[str] = Field(..., description="月ラベル（YYYY-MM形式）")
    data: List[TrendSeriesData] = Field(..., description="推移データ系列")


# =============================================================================
# アップロード関連スキーマ
# =============================================================================

class EcommerceUploadResponse(BaseModel):
    """通販データアップロードレスポンス"""
    success: bool = Field(..., description="成功フラグ")
    message: str = Field(..., description="メッセージ")
    data_type: str = Field(..., description="データタイプ")
    month: str = Field(..., description="対象月")
    records_processed: int = Field(..., description="処理レコード数")
    records_created: int = Field(0, description="新規作成レコード数")
    records_updated: int = Field(0, description="更新レコード数")


class EcommerceBulkUploadResponse(BaseModel):
    """通販データ一括アップロードレスポンス"""
    success: bool = Field(..., description="成功フラグ")
    message: str = Field(..., description="メッセージ")
    month: str = Field(..., description="対象月")
    channel_records: int = Field(0, description="チャネル別レコード数")
    product_records: int = Field(0, description="商品別レコード数")
    customer_records: int = Field(0, description="顧客別レコード数")
    website_records: int = Field(0, description="HPアクセスレコード数")


class TemplateInfo(BaseModel):
    """テンプレート情報"""
    data_type: str = Field(..., description="データタイプ")
    filename: str = Field(..., description="ファイル名")
    description: str = Field(..., description="説明")
