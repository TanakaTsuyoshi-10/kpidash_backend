"""
製造分析スキーマ定義

製造部門（工場）のデータ分析用レスポンススキーマを定義する。
"""
from datetime import date as date_type
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field


# =============================================================================
# 日次データ
# =============================================================================

class ManufacturingDailySummary(BaseModel):
    """製造日次データ"""
    date: date_type = Field(..., description="日付")
    production_batts: Optional[int] = Field(None, description="製造量（バット）")
    production_pieces: Optional[int] = Field(None, description="製造量（個）= バット × 60")
    workers_count: Optional[int] = Field(None, description="出勤者数（延べ）")
    production_per_worker: Optional[Decimal] = Field(None, description="1人あたり製造量（バット）")
    paid_leave_hours: Optional[Decimal] = Field(None, description="有給取得時間")


# =============================================================================
# 月次サマリー
# =============================================================================

class ManufacturingMonthlySummary(BaseModel):
    """製造月次サマリー"""
    month: str = Field(..., description="対象月（YYYY-MM形式）")
    total_batts: int = Field(default=0, description="総製造量（バット）")
    total_pieces: int = Field(default=0, description="総製造量（個）")
    total_workers: int = Field(default=0, description="総出勤者数（延べ）")
    avg_production_per_worker: Optional[Decimal] = Field(None, description="平均1人あたり製造量")
    total_paid_leave_hours: Decimal = Field(default=Decimal("0"), description="総有給取得時間")
    working_days: int = Field(default=0, description="稼働日数")


# =============================================================================
# 前年比較
# =============================================================================

class ManufacturingComparison(BaseModel):
    """製造前年比較データ"""
    period: str = Field(..., description="期間表示")
    current: ManufacturingMonthlySummary = Field(..., description="今期データ")
    previous_year: Optional[ManufacturingMonthlySummary] = Field(None, description="前年データ")
    previous_year2: Optional[ManufacturingMonthlySummary] = Field(None, description="前々年データ")
    yoy_batts_diff: Optional[int] = Field(None, description="前年差（製造量）")
    yoy_batts_rate: Optional[Decimal] = Field(None, description="前年比（%）")
    yoy_productivity_diff: Optional[Decimal] = Field(None, description="前年差（1人あたり製造量）")


# =============================================================================
# グラフ用データ
# =============================================================================

class ManufacturingChartData(BaseModel):
    """製造グラフ用データ"""
    month: str = Field(..., description="対象月（YYYY-MM形式）")
    total_batts: int = Field(default=0, description="総製造量（バット）")
    avg_production_per_worker: Optional[Decimal] = Field(None, description="平均1人あたり製造量")
    total_workers: int = Field(default=0, description="総出勤者数（延べ）")


# =============================================================================
# 製造分析全体レスポンス
# =============================================================================

class ManufacturingAnalysisResponse(BaseModel):
    """製造分析全体レスポンス"""
    period: str = Field(..., description="期間表示")
    period_type: str = Field(..., description="期間タイプ（monthly/quarterly/yearly）")
    summary: ManufacturingMonthlySummary = Field(..., description="月次サマリー")
    daily_data: List[ManufacturingDailySummary] = Field(
        default_factory=list,
        description="日次データ（monthlyの場合のみ）"
    )
    comparison: ManufacturingComparison = Field(..., description="前年比較データ")
    chart_data: List[ManufacturingChartData] = Field(
        default_factory=list,
        description="グラフ用データ"
    )
