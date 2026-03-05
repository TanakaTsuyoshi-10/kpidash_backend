"""
予想注文（発注バット数予測）のPydanticスキーマ
"""
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict


class StoreBats(BaseModel):
    """店舗別バット数"""
    segment_id: str = Field(description="セグメントID")
    segment_name: str = Field(description="店舗名")
    bats: float = Field(description="バット数")


class CalendarDay(BaseModel):
    """カレンダー1日分"""
    date: str = Field(description="日付 (YYYY-MM-DD)")
    weekday: str = Field(description="曜日 (月〜日)")
    bats: float = Field(description="バット数合計")
    by_store: List[StoreBats] = Field(default_factory=list, description="店舗別バット数")


class CalendarMonth(BaseModel):
    """カレンダー月データ"""
    year: int = Field(description="年")
    month: int = Field(description="月")
    days: List[CalendarDay] = Field(default_factory=list, description="日別データ")


class ForecastReference(BaseModel):
    """予測参照日データ"""
    year: int = Field(description="年")
    date: str = Field(description="参照日 (YYYY-MM-DD)")
    weekday: str = Field(description="曜日")
    bats: float = Field(description="バット数")


class ForecastStoreBats(BaseModel):
    """予測の店舗別バット数"""
    segment_id: str = Field(description="セグメントID")
    segment_name: str = Field(description="店舗名")
    bats: float = Field(description="予想バット数（前年同曜日）")
    prev_year_bats: float = Field(description="前年バット数")
    two_years_ago_bats: Optional[float] = Field(None, description="前々年バット数")


class ForecastSummary(BaseModel):
    """予測サマリー"""
    total_bats: float = Field(description="予想バット数合計（全店舗）")
    reference_dates: List[ForecastReference] = Field(description="参照日リスト")
    by_store: List[ForecastStoreBats] = Field(default_factory=list, description="店舗別予測")


class OrderForecastResponse(BaseModel):
    """予想注文レスポンス"""
    model_config = ConfigDict(from_attributes=True)

    target_date: str = Field(description="対象日 (YYYY-MM-DD)")
    target_weekday: str = Field(description="対象日の曜日")
    stores: List[dict] = Field(description="店舗リスト")
    forecast: ForecastSummary = Field(description="予測サマリー")
    previous_year: CalendarMonth = Field(description="前年同月カレンダー")
    two_years_ago: CalendarMonth = Field(description="前々年同月カレンダー")
