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


# =============================================================================
# 人事分析スキーマ（人員構成・推移・入退社・組織指標・店舗別人件費）
# =============================================================================

class HeadcountRow(BaseModel):
    """店舗・部門別の人員（雇用形態内訳つき）"""
    name: str
    area: Optional[str] = Field(None, description='店舗のエリア名（SmartHRの部署階層から）')
    total: int
    fulltime: int = Field(0, description="正社員（役員含む）")
    contract: int = Field(0, description="契約社員（派遣・業務委託含む）")
    parttime: int = Field(0, description="パート・アルバイト等")
    unset: int = Field(0, description="雇用形態未設定")


class HeadcountSummaryResponse(BaseModel):
    as_of: Optional[str] = None
    stores: List[HeadcountRow] = Field(default_factory=list)
    others: List[HeadcountRow] = Field(default_factory=list, description="製造・本社など店舗以外")
    company: Optional[HeadcountRow] = None
    is_sample: bool = True


class HeadcountTrendResponse(BaseModel):
    months: List[str] = Field(default_factory=list, description="YYYY-MM")
    by_group: Dict[str, List[int]] = Field(default_factory=dict, description="雇用形態グループ別の月末在籍数")
    by_department: Dict[str, List[int]] = Field(default_factory=dict, description="部門別の月末在籍数")
    is_sample: bool = True


class TurnoverMonthPoint(BaseModel):
    month: str
    hires: int
    leavers: int


class TurnoverReason(BaseModel):
    reason: str
    count: int


class TurnoverResponse(BaseModel):
    monthly: List[TurnoverMonthPoint] = Field(default_factory=list)
    hires_total: int = 0
    leavers_total: int = 0
    avg_headcount: Optional[float] = None
    turnover_rate: Optional[float] = Field(None, description="期間退職者数 ÷ 平均在籍数（%）")
    reasons: List[TurnoverReason] = Field(default_factory=list)
    is_sample: bool = True


class AgeBucket(BaseModel):
    label: str
    count: int


class OrgHealthDepartmentRow(BaseModel):
    department: str
    headcount: int
    avg_age: Optional[float] = None
    avg_tenure_years: Optional[float] = None


class OrgHealthResponse(BaseModel):
    avg_age: Optional[float] = None
    avg_tenure_years: Optional[float] = None
    age_distribution: List[AgeBucket] = Field(default_factory=list)
    by_department: List[OrgHealthDepartmentRow] = Field(default_factory=list)
    is_sample: bool = True


class StoreLaborRow(BaseModel):
    store: str
    area: Optional[str] = Field(None, description='店舗のエリア名（通販事業部・未対応店舗は None）')
    headcount: int = Field(..., description="月末在籍数")
    labor_cost: int = Field(..., description="人件費（円・総支給額）")
    labor_cost_prev_year: int = 0
    labor_cost_yoy: Optional[float] = None
    sales: Optional[int] = Field(None, description="売上高実績（円）")
    labor_cost_ratio: Optional[float] = Field(None, description="人件費率（%）")
    sales_per_head: Optional[int] = Field(None, description="1人あたり売上（円）")
    overtime_per_head: Optional[float] = Field(None, description="1人あたり残業時間（h/月）")


class StoreLaborResponse(BaseModel):
    month: str
    rows: List[StoreLaborRow] = Field(default_factory=list)
    total: Optional[StoreLaborRow] = None
    unmatched_stores: List[str] = Field(default_factory=list, description="ダッシュボード店舗と対応づけできなかったSmartHR店舗名")
    is_sample: bool = True
