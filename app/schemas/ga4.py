"""
EC Web分析（GA4連携）スキーマ

GoogleアナリティクスGA4から取得したEC主要数値のPydanticスキーマを定義する。
"""
from typing import List

from pydantic import BaseModel, Field


class MetricComparison(BaseModel):
    """指標と前月比・前年比

    vs_prev_month / vs_prev_year は変化率（%）を表す。
    ただし離脱率（bounce_rate）はポイント差（pt）として扱う。
    """
    value: float = Field(..., description="指標値")
    vs_prev_month: float = Field(..., description="前月比（変化率% / 離脱率はpt差）")
    vs_prev_year: float = Field(..., description="前年比（変化率% / 離脱率はpt差）")

    class Config:
        from_attributes = True


class ChannelShare(BaseModel):
    """流入経路の構成比"""
    channel: str = Field(..., description="流入経路名")
    share: float = Field(..., description="構成比（%）")

    class Config:
        from_attributes = True


class RegionTraffic(BaseModel):
    """地区別の流入セッション数"""
    region: str = Field(..., description="地区名")
    sessions: int = Field(..., description="流入セッション数")

    class Config:
        from_attributes = True


class GA4EcSummary(BaseModel):
    """EC Web分析サマリー（GA4連携）"""
    sessions: MetricComparison = Field(..., description="前日の流入数（セッション）")
    bounce_rate: MetricComparison = Field(..., description="離脱率（%）")
    channels: List[ChannelShare] = Field(default_factory=list, description="流入経路の構成比一覧")
    regions: List[RegionTraffic] = Field(default_factory=list, description="地区別流入一覧")
    comment: str = Field(..., description="自動生成された簡易コメント")
    is_sample: bool = Field(..., description="サンプルデータかどうか")
    date_label: str = Field(..., description="対象日ラベル")

    class Config:
        from_attributes = True
