"""
日次販売分析のPydanticスキーマ

3つのAPIレスポンス型 + アップロード結果型を定義する。
"""
from datetime import date
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict


# =============================================================================
# API 1: 日別×店舗サマリー
# =============================================================================

class DailyStoreSalesData(BaseModel):
    """日別×店舗の販売データ"""
    date: str = Field(description="日付 (YYYY-MM-DD)")
    comparison_date: Optional[str] = Field(None, description="前年比較先日付（同曜日）")
    segment_id: str = Field(description="セグメントID")
    sales: float = Field(description="売上金額")
    customers: int = Field(description="客数（ユニークレシート数）")
    unit_price: float = Field(description="客単価")
    sales_previous_year: Optional[float] = Field(None, description="前年売上")
    customers_previous_year: Optional[int] = Field(None, description="前年客数")
    yoy_sales_rate: Optional[float] = Field(None, description="売上前年比(%)")
    yoy_customers_rate: Optional[float] = Field(None, description="客数前年比(%)")


class StoreInfo(BaseModel):
    """店舗情報"""
    segment_id: str
    segment_code: str
    segment_name: str


class DailySalesSummaryResponse(BaseModel):
    """日別×店舗サマリーレスポンス"""
    model_config = ConfigDict(from_attributes=True)

    period: str = Field(description="対象年月 (YYYY-MM-01)")
    dates: List[str] = Field(description="日付リスト")
    stores: List[StoreInfo] = Field(description="店舗リスト")
    data: List[DailyStoreSalesData] = Field(description="日別×店舗データ")
    totals: List[DailyStoreSalesData] = Field(
        default_factory=list,
        description="月計（店舗別合計）"
    )


# =============================================================================
# API 2: 時間帯別ヒートマップ
# =============================================================================

class HourlySalesData(BaseModel):
    """時間帯別の販売データ"""
    hour: int = Field(description="時間帯 (0-23)")
    segment_id: str = Field(description="セグメントID")
    sales: float = Field(description="売上金額")
    customers: int = Field(description="客数")


class HourlySalesResponse(BaseModel):
    """時間帯別ヒートマップレスポンス"""
    model_config = ConfigDict(from_attributes=True)

    date: str = Field(description="対象日 (YYYY-MM-DD)")
    hours: List[int] = Field(description="時間帯リスト")
    stores: List[StoreInfo] = Field(description="店舗リスト")
    data: List[HourlySalesData] = Field(description="時間帯×店舗データ")
    row_totals: List[dict] = Field(
        default_factory=list,
        description="行計（店舗別合計）"
    )
    col_totals: List[dict] = Field(
        default_factory=list,
        description="列計（時間帯別合計）"
    )


# =============================================================================
# API 3: 日次推移グラフ
# =============================================================================

class DailyTrendDataPoint(BaseModel):
    """日次推移の1日分データ"""
    date: str = Field(description="日付 (YYYY-MM-DD)")
    sales: float = Field(description="売上金額")
    customers: int = Field(description="客数")


class DailyTrendResponse(BaseModel):
    """日次推移グラフレスポンス"""
    model_config = ConfigDict(from_attributes=True)

    period: str = Field(description="対象年月 (YYYY-MM-01)")
    segment_id: Optional[str] = Field(None, description="セグメントID（nullは全店舗）")
    segment_name: Optional[str] = Field(None, description="セグメント名")
    current_year: List[DailyTrendDataPoint] = Field(description="当年データ")
    previous_year: List[DailyTrendDataPoint] = Field(description="前年データ")


# =============================================================================
# アップロード結果
# =============================================================================

class ReceiptJournalUploadResult(BaseModel):
    """レシートジャーナルアップロード結果"""
    success: bool = Field(description="成功/失敗")
    start_date: Optional[str] = Field(None, description="データ開始日")
    end_date: Optional[str] = Field(None, description="データ終了日")
    imported_count: int = Field(0, description="インポートレコード数")
    stores_processed: List[str] = Field(
        default_factory=list,
        description="処理した店舗名リスト"
    )
    errors: List[str] = Field(default_factory=list, description="エラーメッセージ")
    warnings: List[str] = Field(default_factory=list, description="警告メッセージ")
