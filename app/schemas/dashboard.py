"""
ダッシュボードスキーマ定義

経営層向けダッシュボードのレスポンス用Pydanticモデルを定義する。
"""
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field

from app.schemas.complaint import ComplaintDashboardSummary


# =============================================================================
# 基本モデル
# =============================================================================

class MetricWithComparison(BaseModel):
    """
    単一指標と比較値を持つモデル

    各指標について、実績値、前年比較、目標比較を含む。
    """
    value: Optional[Decimal] = Field(None, description="実績値")
    previous_year: Optional[Decimal] = Field(None, description="前年実績")
    yoy_rate: Optional[Decimal] = Field(None, description="前年比（%）")
    yoy_diff: Optional[Decimal] = Field(None, description="前年差（実額またはポイント）")
    target: Optional[Decimal] = Field(None, description="目標値")
    achievement_rate: Optional[Decimal] = Field(None, description="達成率（%）")


# =============================================================================
# セクション別モデル
# =============================================================================

class CompanySummary(BaseModel):
    """
    全社サマリー

    全社の売上高、粗利益、営業利益などの主要指標を含む。
    """
    period: str = Field(..., description="期間表示（例: '2025年11月'）")
    period_type: str = Field(..., description="期間タイプ（monthly/quarterly/yearly）")
    fiscal_year: int = Field(..., description="会計年度")
    sales_total: MetricWithComparison = Field(..., description="全社売上高")
    gross_profit: MetricWithComparison = Field(..., description="粗利益")
    gross_profit_rate: MetricWithComparison = Field(..., description="粗利率")
    operating_profit: MetricWithComparison = Field(..., description="営業利益")


class DepartmentPerformance(BaseModel):
    """
    部門別実績

    店舗・通販など部門ごとの売上・利益実績を含む。
    """
    department: str = Field(..., description="部門名（店舗/通販）")
    sales: Optional[Decimal] = Field(None, description="売上高")
    sales_yoy_rate: Optional[Decimal] = Field(None, description="前年比（%）")
    profit: Optional[Decimal] = Field(None, description="利益")
    achievement_rate: Optional[Decimal] = Field(None, description="達成率（%）")
    budget_rate: Optional[Decimal] = Field(None, description="予算比（%）")


class CashFlowData(BaseModel):
    """
    キャッシュフローデータ

    営業CF、投資CF、財務CF、フリーCFの今期・前年・前々年の実績を含む。
    """
    # 営業キャッシュフロー
    cf_operating: Optional[Decimal] = Field(None, description="営業CF（今期）")
    cf_operating_prev: Optional[Decimal] = Field(None, description="営業CF（前年）")
    cf_operating_prev2: Optional[Decimal] = Field(None, description="営業CF（前々年）")

    # 投資キャッシュフロー
    cf_investing: Optional[Decimal] = Field(None, description="投資CF（今期）")
    cf_investing_prev: Optional[Decimal] = Field(None, description="投資CF（前年）")
    cf_investing_prev2: Optional[Decimal] = Field(None, description="投資CF（前々年）")

    # 財務キャッシュフロー
    cf_financing: Optional[Decimal] = Field(None, description="財務CF（今期）")
    cf_financing_prev: Optional[Decimal] = Field(None, description="財務CF（前年）")
    cf_financing_prev2: Optional[Decimal] = Field(None, description="財務CF（前々年）")

    # フリーキャッシュフロー
    cf_free: Optional[Decimal] = Field(None, description="フリーCF（今期）")
    cf_free_prev: Optional[Decimal] = Field(None, description="フリーCF（前年）")
    cf_free_prev2: Optional[Decimal] = Field(None, description="フリーCF（前々年）")


class ManagementIndicators(BaseModel):
    """
    経営指標

    原価率、人件費率、客数、客単価などの経営指標を含む。
    """
    cost_rate: MetricWithComparison = Field(..., description="原価率")
    labor_cost_rate: MetricWithComparison = Field(..., description="人件費率")
    customer_count: MetricWithComparison = Field(..., description="客数")
    customer_unit_price: MetricWithComparison = Field(..., description="客単価")


class ChartDataPoint(BaseModel):
    """
    グラフ用データポイント

    月次の売上・営業利益推移データを含む。
    """
    month: str = Field(..., description="月（YYYY-MM形式）")
    sales: Optional[Decimal] = Field(None, description="売上高")
    operating_profit: Optional[Decimal] = Field(None, description="営業利益")
    sales_target: Optional[Decimal] = Field(None, description="売上目標")
    operating_profit_target: Optional[Decimal] = Field(None, description="営業利益目標")


class AlertItem(BaseModel):
    """
    アラート項目

    予算未達など注意が必要な項目を含む。
    """
    category: str = Field(..., description="カテゴリ（売上/利益/部門）")
    name: str = Field(..., description="項目名")
    achievement_rate: Decimal = Field(..., description="達成率（%）")
    actual: Decimal = Field(..., description="実績値")
    target: Decimal = Field(..., description="目標値")
    severity: str = Field(..., description="深刻度（warning/critical）")


# =============================================================================
# 統合レスポンスモデル
# =============================================================================

class DashboardResponse(BaseModel):
    """
    ダッシュボード全体レスポンス

    全セクションのデータを含むダッシュボード完全レスポンス。
    """
    company_summary: CompanySummary = Field(..., description="全社サマリー")
    department_performance: List[DepartmentPerformance] = Field(
        default_factory=list,
        description="部門別実績"
    )
    cash_flow: CashFlowData = Field(..., description="キャッシュフロー")
    management_indicators: ManagementIndicators = Field(..., description="経営指標")
    chart_data: List[ChartDataPoint] = Field(
        default_factory=list,
        description="推移グラフデータ"
    )
    alerts: List[AlertItem] = Field(default_factory=list, description="アラート一覧")
    complaint_summary: Optional[ComplaintDashboardSummary] = Field(
        None,
        description="クレームサマリー"
    )


# =============================================================================
# クエリパラメータモデル
# =============================================================================

class DashboardQueryParams(BaseModel):
    """
    ダッシュボードAPIのクエリパラメータ
    """
    period_type: str = Field(
        default="monthly",
        description="期間タイプ（monthly/quarterly/yearly）"
    )
    year: Optional[int] = Field(None, description="年度（省略時は現在の年度）")
    month: Optional[int] = Field(None, description="月（monthlyの場合）")
    quarter: Optional[int] = Field(None, description="四半期（quarterlyの場合）")
