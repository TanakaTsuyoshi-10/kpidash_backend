"""
ふるさと納税分析スキーマモジュール

ふるさと納税の販売実績・リピート情報・返品苦情・口コミの
リクエスト/レスポンススキーマを定義する。
"""
from typing import Dict, Optional

from pydantic import BaseModel, Field


# =============================================================================
# 販売実績スキーマ
# =============================================================================

class FurusatoSalesData(BaseModel):
    """販売実績データ"""
    inventory: Optional[int] = Field(None, description="在庫数")
    orders: Optional[int] = Field(None, description="単月注文数")
    sales: Optional[float] = Field(None, description="単月売上高")
    unit_price: Optional[float] = Field(None, description="単価")
    orders_kyushu: Optional[int] = Field(None, description="エリア: 九州")
    orders_chugoku_shikoku: Optional[int] = Field(None, description="エリア: 中国・四国")
    orders_kansai: Optional[int] = Field(None, description="エリア: 関西")
    orders_kanto: Optional[int] = Field(None, description="エリア: 関東")
    orders_other: Optional[int] = Field(None, description="エリア: その他")
    cumulative_orders: Optional[int] = Field(None, description="累計注文数")
    cumulative_sales: Optional[float] = Field(None, description="累計売上高")
    weekly: Optional[dict] = Field(None, description="週次データ（第1〜5週）")


# =============================================================================
# リピート情報スキーマ
# =============================================================================

class FurusatoRepeatData(BaseModel):
    """リピート情報データ"""
    new_customers: Optional[int] = Field(None, description="当月新規注文者数")
    cumulative_new_customers: Optional[int] = Field(None, description="累計新規注文者数")
    ec_site_buyers: Optional[int] = Field(None, description="ECサイトでの購入経験者")
    repeat_buyers: Optional[int] = Field(None, description="ふるさと納税複数回購入経験者")
    repeat_single_month: Optional[int] = Field(None, description="単月で複数回注文")
    repeat_multi_month: Optional[int] = Field(None, description="複数月で注文経験有")
    weekly: Optional[dict] = Field(None, description="週次データ（第1〜5週）")


# =============================================================================
# 返品・苦情スキーマ
# =============================================================================

class FurusatoComplaintData(BaseModel):
    """返品・苦情データ"""
    reshipping_count: Optional[int] = Field(None, description="再送数")
    complaint_count: Optional[int] = Field(None, description="苦情数")
    weekly: Optional[dict] = Field(None, description="週次データ（第1〜5週）")


# =============================================================================
# 口コミスキーマ
# =============================================================================

class FurusatoReviewData(BaseModel):
    """口コミデータ"""
    positive_reviews: Optional[int] = Field(None, description="ポジティブ情報")
    negative_reviews: Optional[int] = Field(None, description="ネガティブ情報")
    weekly: Optional[dict] = Field(None, description="週次データ（第1〜5週）")


# =============================================================================
# サマリーレスポンス
# =============================================================================

class FurusatoSummaryResponse(BaseModel):
    """ふるさと納税サマリーレスポンス"""
    period: str = Field(..., description="対象期間（YYYY-MM-DD）")
    period_type: str = Field(default="monthly", description="期間タイプ（monthly/cumulative）")
    fiscal_year: Optional[int] = Field(None, description="会計年度")
    sales: FurusatoSalesData = Field(..., description="販売実績")
    repeat: FurusatoRepeatData = Field(..., description="リピート情報")
    complaint: FurusatoComplaintData = Field(..., description="返品・苦情")
    review: FurusatoReviewData = Field(..., description="口コミ")
    comments: Dict[str, Optional[str]] = Field(
        default_factory=dict,
        description="コメント（sales, repeat, complaint, review）"
    )


# =============================================================================
# アップロードレスポンス
# =============================================================================

class FurusatoUploadResponse(BaseModel):
    """ふるさと納税アップロードレスポンス"""
    success: bool = Field(..., description="成功フラグ")
    message: str = Field(..., description="メッセージ")
    month: str = Field(..., description="対象月")
    records_processed: int = Field(0, description="処理レコード数")
