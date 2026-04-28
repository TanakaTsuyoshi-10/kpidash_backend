"""
洞察・データ鮮度スキーマ定義

ハイライト・インサイト・データ鮮度のレスポンス用Pydanticモデルを定義する。
"""
from typing import List, Optional

from pydantic import BaseModel, Field


# =============================================================================
# ハイライト（今日のハイライトカード用）
# =============================================================================

class HighlightItem(BaseModel):
    """ハイライト項目"""
    icon: str = Field(..., description="アイコン名（lucide-react準拠）")
    text: str = Field(..., description="ハイライトテキスト")
    severity: str = Field(
        default="info",
        description="深刻度（info/good/warning/critical）"
    )
    link: Optional[str] = Field(None, description="詳細ページへのリンク")


class HighlightResponse(BaseModel):
    """ハイライトレスポンス"""
    date: str = Field(..., description="対象日（YYYY-MM-DD）")
    items: List[HighlightItem] = Field(
        default_factory=list, description="ハイライト項目リスト"
    )
    data_freshness: Optional[str] = Field(
        None, description="データの鮮度（例: '昨日'）"
    )


# =============================================================================
# インサイト（注目ポイントカード用）
# =============================================================================

class InsightItem(BaseModel):
    """インサイト項目"""
    category: str = Field(
        ..., description="カテゴリ（good/warning/critical）"
    )
    severity: str = Field(
        ..., description="深刻度（good/warning/critical）"
    )
    text: str = Field(..., description="インサイトテキスト")
    link: Optional[str] = Field(None, description="詳細ページへのリンク")


class InsightsResponse(BaseModel):
    """インサイトレスポンス"""
    period: str = Field(..., description="対象期間（YYYY-MM形式）")
    items: List[InsightItem] = Field(
        default_factory=list, description="インサイト項目リスト"
    )


# =============================================================================
# データ鮮度
# =============================================================================

class DataFreshnessResponse(BaseModel):
    """データ鮮度レスポンス"""
    financial_latest: Optional[str] = Field(
        None, description="財務データの最新月（YYYY-MM形式）"
    )
    store_latest: Optional[str] = Field(
        None, description="店舗売上データの最新日（YYYY-MM-DD形式）"
    )
    ecommerce_latest: Optional[str] = Field(
        None, description="通販データの最新月（YYYY-MM形式）"
    )
