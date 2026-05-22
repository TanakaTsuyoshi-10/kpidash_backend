"""
人事（HR）スキーマ

SmartHR連携による部署別の人件費・時間外労働のPydanticスキーマを定義する。
認証情報未手配の間はサンプルデータを返すため is_sample フラグを持つ。
"""
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


# =============================================================================
# 部署別 指標スキーマ
# =============================================================================

class DepartmentLaborCost(BaseModel):
    """部署別 人件費（当月・前年同月・前年比）"""
    department: str = Field(..., description="部署名")
    current: float = Field(..., description="当月人件費（百万円）")
    previous_year: float = Field(..., description="前年同月人件費（百万円）")
    yoy_rate: float = Field(..., description="前年比（%）。増加=コスト増")

    class Config:
        from_attributes = True


class DepartmentOvertime(BaseModel):
    """部署別 時間外労働（当月・前年同月・前年比）"""
    department: str = Field(..., description="部署名")
    current: float = Field(..., description="当月の時間外労働（時間/月、1人あたり平均）")
    previous_year: float = Field(..., description="前年同月の時間外労働（時間/月）")
    yoy_rate: float = Field(..., description="前年比（%）。増加=負担増")

    class Config:
        from_attributes = True


class LaborCostTrendPoint(BaseModel):
    """部署別 人件費の月次推移ポイント"""
    month: str = Field(..., description="対象月（例: '11月'）")
    values: Dict[str, float] = Field(
        default_factory=dict,
        description="部署名 → 人件費（百万円）のマップ",
    )

    class Config:
        from_attributes = True


# =============================================================================
# レスポンススキーマ
# =============================================================================

class LaborSummaryResponse(BaseModel):
    """部署別 人件費・時間外サマリーレスポンス"""
    labor_costs: List[DepartmentLaborCost] = Field(
        default_factory=list, description="部署別 人件費一覧"
    )
    overtime: List[DepartmentOvertime] = Field(
        default_factory=list, description="部署別 時間外労働一覧"
    )
    labor_cost_trend: List[LaborCostTrendPoint] = Field(
        default_factory=list, description="部署別 人件費の月次推移"
    )
    labor_cost_total: Optional[DepartmentLaborCost] = Field(
        default=None, description="人件費の全部署合計（その他含む）"
    )
    overtime_total: Optional[DepartmentOvertime] = Field(
        default=None, description="時間外労働の全社合計（1人あたり平均）"
    )
    is_sample: bool = Field(
        default=True,
        description="サンプルデータかどうか（True=サンプル、False=SmartHR実データ）",
    )

    class Config:
        from_attributes = True
