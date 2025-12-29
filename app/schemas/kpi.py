"""
Pydanticスキーマモジュール

APIのリクエスト/レスポンスで使用するデータモデルを定義する。
すべてのモデルはPydantic BaseModelを継承し、型安全なデータ検証を提供する。
"""
import datetime as dt
from datetime import date as DateType, datetime
from decimal import Decimal
from typing import Optional, List, Any, Dict
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict


# =============================================================================
# ユーザー関連スキーマ
# =============================================================================

class User(BaseModel):
    """
    ユーザー情報スキーマ

    JWTトークンから抽出されたユーザー情報を表す。
    """
    user_id: str = Field(..., description="ユーザーUUID")
    email: Optional[str] = Field(None, description="メールアドレス")
    department_id: Optional[str] = Field(None, description="所属部門ID")
    role: str = Field(default="authenticated", description="Supabaseロール")
    user_metadata: Dict[str, Any] = Field(default_factory=dict, description="ユーザーメタデータ")

    model_config = ConfigDict(from_attributes=True)


class UserResponse(BaseModel):
    """
    ユーザー情報レスポンススキーマ

    GET /auth/me エンドポイントのレスポンス用。
    """
    user_id: str = Field(..., description="ユーザーUUID")
    email: Optional[str] = Field(None, description="メールアドレス")
    department_id: Optional[str] = Field(None, description="所属部門ID")
    department_name: Optional[str] = Field(None, description="所属部門名")


# =============================================================================
# 部門関連スキーマ
# =============================================================================

class Department(BaseModel):
    """
    部門スキーマ

    部門マスタ（departments）テーブルのレコードを表す。
    """
    id: UUID = Field(..., description="部門UUID")
    name: str = Field(..., description="部門名（財務部門, 店舗部門, 通販部門, 工場部門）")
    slug: str = Field(..., description="部門スラッグ（finance, store, online, factory）")

    model_config = ConfigDict(from_attributes=True)


class DepartmentResponse(BaseModel):
    """
    部門レスポンススキーマ
    """
    id: str = Field(..., description="部門UUID")
    name: str = Field(..., description="部門名")
    slug: str = Field(..., description="部門スラッグ")


# =============================================================================
# 店舗・拠点関連スキーマ
# =============================================================================

class Segment(BaseModel):
    """
    店舗・拠点スキーマ

    店舗・拠点マスタ（segments）テーブルのレコードを表す。
    """
    id: UUID = Field(..., description="店舗・拠点UUID")
    department_id: UUID = Field(..., description="所属部門ID")
    code: str = Field(..., description="店舗コード")
    name: str = Field(..., description="店舗名")

    model_config = ConfigDict(from_attributes=True)


class SegmentResponse(BaseModel):
    """
    店舗・拠点レスポンススキーマ
    """
    id: str = Field(..., description="店舗・拠点UUID")
    department_id: str = Field(..., description="所属部門ID")
    code: str = Field(..., description="店舗コード")
    name: str = Field(..., description="店舗名")


# =============================================================================
# KPI定義関連スキーマ
# =============================================================================

class KPIDefinition(BaseModel):
    """
    KPI定義スキーマ

    KPI定義マスタ（kpi_definitions）テーブルのレコードを表す。
    """
    id: UUID = Field(..., description="KPI定義UUID")
    department_id: UUID = Field(..., description="対象部門ID")
    category: str = Field(..., description="カテゴリ（全体, 商品グループ, 分析）")
    name: str = Field(..., description="KPI名（売上高, 客数, 客単価など）")
    unit: str = Field(..., description="単位（円, 人, 個）")
    is_calculated: bool = Field(default=False, description="自動計算項目かどうか")
    formula: Optional[str] = Field(None, description="計算式（例: 売上高 / 客数）")
    display_order: int = Field(default=0, description="表示順")
    is_visible: bool = Field(default=True, description="表示/非表示フラグ")

    model_config = ConfigDict(from_attributes=True)


class KPIDefinitionResponse(BaseModel):
    """
    KPI定義レスポンススキーマ
    """
    id: str = Field(..., description="KPI定義UUID")
    department_id: str = Field(..., description="対象部門ID")
    category: str = Field(..., description="カテゴリ")
    name: str = Field(..., description="KPI名")
    unit: str = Field(..., description="単位")
    is_calculated: bool = Field(..., description="自動計算項目かどうか")
    formula: Optional[str] = Field(None, description="計算式")
    display_order: int = Field(..., description="表示順")
    is_visible: bool = Field(..., description="表示/非表示フラグ")


# =============================================================================
# KPI値関連スキーマ
# =============================================================================

class KPIValue(BaseModel):
    """
    KPI実績・目標値スキーマ

    KPI値（kpi_values）テーブルのレコードを表す。
    """
    id: int = Field(..., description="レコードID")
    segment_id: UUID = Field(..., description="店舗・拠点ID")
    kpi_id: UUID = Field(..., description="KPI定義ID")
    date: DateType = Field(..., description="対象年月（各月1日）")
    value: Decimal = Field(..., description="値")
    is_target: bool = Field(..., description="目標値(true)か実績値(false)か")

    model_config = ConfigDict(from_attributes=True)


class KPIValueResponse(BaseModel):
    """
    KPI値レスポンススキーマ
    """
    id: int = Field(..., description="レコードID")
    segment_id: str = Field(..., description="店舗・拠点ID")
    kpi_id: str = Field(..., description="KPI定義ID")
    date: DateType = Field(..., description="対象年月")
    value: float = Field(..., description="値")
    is_target: bool = Field(..., description="目標値か実績値か")


class KPIValueCreate(BaseModel):
    """
    KPI値作成リクエストスキーマ
    """
    segment_id: UUID = Field(..., description="店舗・拠点ID")
    kpi_id: UUID = Field(..., description="KPI定義ID")
    date: DateType = Field(..., description="対象年月（各月1日）")
    value: Decimal = Field(..., description="値")
    is_target: bool = Field(..., description="目標値(true)か実績値(false)か")


# =============================================================================
# 目標値関連スキーマ
# =============================================================================

class TargetValueCreate(BaseModel):
    """
    目標値作成リクエストスキーマ

    単一の目標値を登録する。
    """
    segment_id: str = Field(..., description="店舗・拠点ID")
    kpi_id: str = Field(..., description="KPI定義ID")
    month: DateType = Field(..., description="対象年月（YYYY-MM-DD形式、月初日）")
    value: float = Field(..., ge=0, description="目標値")


class TargetValueUpdate(BaseModel):
    """
    目標値更新リクエストスキーマ
    """
    value: float = Field(..., ge=0, description="目標値")


class TargetValueBulkItem(BaseModel):
    """
    目標値一括登録の1項目
    """
    segment_id: str = Field(..., description="店舗・拠点ID")
    kpi_id: str = Field(..., description="KPI定義ID")
    month: DateType = Field(..., description="対象年月")
    value: float = Field(..., ge=0, description="目標値")


class TargetValueBulkCreate(BaseModel):
    """
    目標値一括登録リクエストスキーマ

    複数の目標値を一括で登録する。
    既存の値は上書き（Upsert）される。
    """
    targets: List[TargetValueBulkItem] = Field(..., description="目標値リスト", min_length=1)


class TargetValueResponse(BaseModel):
    """
    目標値レスポンススキーマ
    """
    id: int = Field(..., description="レコードID")
    segment_id: str = Field(..., description="店舗・拠点ID")
    segment_name: Optional[str] = Field(None, description="店舗名")
    kpi_id: str = Field(..., description="KPI定義ID")
    kpi_name: Optional[str] = Field(None, description="KPI名")
    month: DateType = Field(..., description="対象年月")
    value: float = Field(..., description="目標値")


class TargetValueBulkResponse(BaseModel):
    """
    目標値一括登録レスポンススキーマ
    """
    success: bool = Field(..., description="処理成功かどうか")
    created_count: int = Field(default=0, description="新規作成件数")
    updated_count: int = Field(default=0, description="更新件数")
    errors: List[str] = Field(default_factory=list, description="エラーメッセージ")


class TargetMatrixCell(BaseModel):
    """
    目標マトリックスのセル
    """
    target_id: Optional[int] = Field(None, description="目標値ID（未設定の場合null）")
    value: Optional[float] = Field(None, description="目標値")
    last_year_actual: Optional[float] = Field(None, description="前年同月実績")


class TargetMatrixRow(BaseModel):
    """
    目標マトリックスの行（店舗）
    """
    segment_id: str = Field(..., description="店舗ID")
    segment_code: str = Field(..., description="店舗コード")
    segment_name: str = Field(..., description="店舗名")
    values: Dict[str, TargetMatrixCell] = Field(..., description="KPI別目標値（キーはKPI ID）")


class TargetMatrixResponse(BaseModel):
    """
    目標マトリックスレスポンススキーマ

    店舗×KPIの目標値マトリックスを返す。
    目標値入力画面用。
    """
    fiscal_year: int = Field(..., description="年度")
    month: str = Field(..., description="対象月（YYYY-MM-DD）")
    kpis: List[Dict[str, Any]] = Field(..., description="KPI定義リスト")
    rows: List[TargetMatrixRow] = Field(..., description="店舗別データ")


# =============================================================================
# 商品マッピング関連スキーマ
# =============================================================================

class ProductMapping(BaseModel):
    """
    商品名マッピングスキーマ

    CSVの商品名とKPI定義を紐付けるマッピング。
    """
    id: UUID = Field(..., description="マッピングUUID")
    raw_product_name: str = Field(..., description="CSV上の商品名")
    kpi_id: Optional[UUID] = Field(None, description="紐付けられたKPI定義ID（NULLなら未マッピング）")

    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# ヘルスチェック関連スキーマ
# =============================================================================

class HealthResponse(BaseModel):
    """
    ヘルスチェックレスポンススキーマ

    GET /health エンドポイントのレスポンス用。
    """
    status: str = Field(..., description="ステータス（healthy）")
    environment: str = Field(..., description="実行環境")
    version: str = Field(..., description="APIバージョン")
    timestamp: datetime = Field(..., description="レスポンス時刻")


# =============================================================================
# 共通レスポンススキーマ
# =============================================================================

class APIInfo(BaseModel):
    """
    API情報レスポンススキーマ

    GET / エンドポイントのレスポンス用。
    """
    title: str = Field(..., description="APIタイトル")
    version: str = Field(..., description="APIバージョン")
    description: str = Field(..., description="API説明")
    docs_url: str = Field(..., description="Swagger UIのURL")


class ErrorResponse(BaseModel):
    """
    エラーレスポンススキーマ

    エラー発生時の共通レスポンス形式。
    """
    detail: str = Field(..., description="エラーメッセージ")
    status_code: int = Field(..., description="HTTPステータスコード")


class MessageResponse(BaseModel):
    """
    メッセージレスポンススキーマ

    単純なメッセージを返す場合に使用。
    """
    message: str = Field(..., description="メッセージ")


# =============================================================================
# Phase 3: KPIデータ取得・計算機能用スキーマ
# =============================================================================

class KPIMetric(BaseModel):
    """
    KPI指標スキーマ

    単一のKPI指標の実績・目標・達成率などを表す。
    """
    name: str = Field(..., description="KPI名")
    unit: str = Field(..., description="単位")
    category: Optional[str] = Field(None, description="カテゴリ")
    actual: Optional[float] = Field(None, description="単月実績")
    target: Optional[float] = Field(None, description="単月目標")
    ytd_actual: Optional[float] = Field(None, description="年度累計実績")
    ytd_target: Optional[float] = Field(None, description="年度累計目標")
    achievement_rate: Optional[float] = Field(None, description="達成率（%）")
    yoy_rate: Optional[float] = Field(None, description="前年比（%）")
    alert_level: str = Field(default="none", description="アラートレベル（none/warning/critical）")


class CalculatedMetrics(BaseModel):
    """
    計算指標スキーマ

    派生計算される指標（客単価など）を表す。
    """
    customer_unit_price: Optional[float] = Field(None, description="客単価（円）")
    items_per_customer: Optional[float] = Field(None, description="1人あたり個数")


class DepartmentInfo(BaseModel):
    """部門情報"""
    id: str = Field(..., description="部門ID")
    name: str = Field(..., description="部門名")
    slug: str = Field(..., description="部門スラッグ")


class DepartmentSummary(BaseModel):
    """
    部門KPIサマリースキーマ

    部門全体のKPI一覧と達成状況を表す。
    """
    department: DepartmentInfo = Field(..., description="部門情報")
    period: str = Field(..., description="対象期間（YYYY-MM-DD）")
    fiscal_year: int = Field(..., description="年度")
    kpis: List[KPIMetric] = Field(default_factory=list, description="KPI指標リスト")


class SegmentInfo(BaseModel):
    """店舗・拠点情報"""
    id: str = Field(..., description="セグメントID")
    name: str = Field(..., description="店舗名")
    code: str = Field(..., description="店舗コード")


class SegmentDetail(BaseModel):
    """
    店舗詳細KPIスキーマ

    個別店舗のKPI詳細と計算指標を表す。
    """
    segment: SegmentInfo = Field(..., description="店舗情報")
    period: str = Field(..., description="対象期間（YYYY-MM-DD）")
    fiscal_year: int = Field(..., description="年度")
    kpis: List[KPIMetric] = Field(default_factory=list, description="KPI指標リスト")
    calculated_metrics: CalculatedMetrics = Field(..., description="計算指標")


class ChartDatasets(BaseModel):
    """グラフデータセット"""
    actual: List[float] = Field(default_factory=list, description="実績データ")
    target: List[float] = Field(default_factory=list, description="目標データ")
    previous_year: List[float] = Field(default_factory=list, description="前年データ")


class ChartData(BaseModel):
    """
    グラフ用データスキーマ

    時系列比較グラフ用のデータを表す（会計年度ベース：9月〜翌8月）。
    """
    kpi_name: str = Field(..., description="KPI名")
    fiscal_year: Optional[int] = Field(None, description="会計年度")
    labels: List[str] = Field(default_factory=list, description="X軸ラベル（YYYY-MM形式、9月起点）")
    datasets: ChartDatasets = Field(..., description="データセット")


class RankingItem(BaseModel):
    """
    ランキング項目スキーマ

    店舗ランキングの1項目を表す。
    """
    rank: int = Field(..., description="順位")
    segment_id: str = Field(..., description="セグメントID")
    segment_name: str = Field(..., description="店舗名")
    segment_code: str = Field(..., description="店舗コード")
    value: float = Field(..., description="値（累計）")
    achievement_rate: Optional[float] = Field(None, description="達成率（%）")


class AlertItem(BaseModel):
    """
    アラート項目スキーマ

    未達アラートの1項目を表す。
    """
    department_name: str = Field(..., description="部門名")
    segment_name: str = Field(..., description="店舗名")
    kpi_name: str = Field(..., description="KPI名")
    achievement_rate: float = Field(..., description="達成率（%）")
    alert_level: str = Field(..., description="アラートレベル（warning/critical）")
    ytd_actual: float = Field(..., description="年度累計実績")
    ytd_target: float = Field(..., description="年度累計目標")


# =============================================================================
# 商品マトリックス（一括取得用）スキーマ
# =============================================================================

class ProductValue(BaseModel):
    """商品グループの値"""
    actual: Optional[float] = Field(None, description="当月実績")
    previous_year: Optional[float] = Field(None, description="前年同月実績")
    yoy_rate: Optional[float] = Field(None, description="前年比（%）")
    two_years_ago: Optional[float] = Field(None, description="前々年同月実績（累計時のみ）")
    yoy_rate_two_years: Optional[float] = Field(None, description="前々年比（%）（累計時のみ）")


class StoreProductData(BaseModel):
    """店舗別の商品データ"""
    segment_id: str = Field(..., description="店舗ID")
    segment_code: str = Field(..., description="店舗コード")
    segment_name: str = Field(..., description="店舗名")
    products: Dict[str, ProductValue] = Field(..., description="商品グループ別データ")
    total: float = Field(..., description="合計売上")
    total_previous_year: Optional[float] = Field(None, description="前年合計売上（累計時のみ）")
    total_two_years_ago: Optional[float] = Field(None, description="前々年合計売上（累計時のみ）")


class ProductMatrixResponse(BaseModel):
    """
    商品マトリックスレスポンススキーマ

    店舗×商品グループのマトリックスデータを一括取得するためのレスポンス。
    """
    period: str = Field(..., description="対象期間（YYYY-MM-DD）")
    fiscal_year: int = Field(..., description="年度")
    period_type: str = Field(default="monthly", description="期間タイプ（monthly/cumulative）")
    product_groups: List[str] = Field(..., description="商品グループ名のリスト")
    stores: List[StoreProductData] = Field(..., description="店舗別データ")
    totals: Dict[str, ProductValue] = Field(..., description="商品グループ別合計")


# =============================================================================
# 商品別月次推移（グラフ用）スキーマ
# =============================================================================

class MonthlyValue(BaseModel):
    """月別データ"""
    month: str = Field(..., description="月（YYYY-MM形式）")
    actual: Optional[float] = Field(None, description="実績")
    previous_year: Optional[float] = Field(None, description="前年同月")


class StoreMonthlyData(BaseModel):
    """店舗別月次データ"""
    segment_id: str = Field(..., description="店舗ID")
    segment_code: str = Field(..., description="店舗コード")
    segment_name: str = Field(..., description="店舗名")
    data: List[MonthlyValue] = Field(..., description="月別データ")
    total: float = Field(..., description="期間合計")


class ProductTrendResponse(BaseModel):
    """
    商品別月次推移レスポンススキーマ

    グラフ表示用の商品グループ別月次推移データ。
    全店舗合計と店舗別データの両方を含む。
    """
    product_group: str = Field(..., description="商品グループ名")
    fiscal_year: int = Field(..., description="年度")
    months: List[str] = Field(..., description="月ラベル（YYYY-MM形式）")
    summary: Dict[str, Any] = Field(..., description="全店舗合計のサマリー")
    stores: List[StoreMonthlyData] = Field(..., description="店舗別月次データ")


# =============================================================================
# 店舗詳細スキーマ
# =============================================================================

class ProductGroupDetail(BaseModel):
    """商品グループ別詳細"""
    product_group: str = Field(..., description="商品グループ名")
    sales: Optional[float] = Field(None, description="売上")
    sales_previous_year: Optional[float] = Field(None, description="前年売上")
    sales_yoy: Optional[float] = Field(None, description="売上前年比（%）")
    customers: Optional[float] = Field(None, description="客数")
    customers_previous_year: Optional[float] = Field(None, description="前年客数")
    customers_yoy: Optional[float] = Field(None, description="客数前年比（%）")
    unit_price: Optional[float] = Field(None, description="客単価")
    unit_price_previous_year: Optional[float] = Field(None, description="前年客単価")
    unit_price_yoy: Optional[float] = Field(None, description="客単価前年比（%）")


class ProductItemDetail(BaseModel):
    """個別商品販売データ"""
    product_code: str = Field(..., description="商品コード")
    product_name: str = Field(..., description="商品名")
    product_category: Optional[str] = Field(None, description="商品大分類名")
    quantity: Optional[float] = Field(None, description="件数（販売数量）")
    quantity_previous_year: Optional[float] = Field(None, description="前年件数")
    quantity_yoy: Optional[float] = Field(None, description="件数前年比（%）")
    sales: Optional[float] = Field(None, description="税込小計")
    sales_previous_year: Optional[float] = Field(None, description="前年税込小計")
    sales_yoy: Optional[float] = Field(None, description="売上前年比（%）")


class StoreDetailResponse(BaseModel):
    """
    店舗詳細レスポンススキーマ

    店舗の売上・客数・客単価サマリーと商品グループ別詳細。
    """
    segment_id: str = Field(..., description="店舗ID")
    segment_code: str = Field(..., description="店舗コード")
    segment_name: str = Field(..., description="店舗名")
    month: str = Field(..., description="対象月（YYYY-MM-DD形式）")

    # 店舗全体サマリー
    total_sales: Optional[float] = Field(None, description="売上合計")
    total_sales_previous_year: Optional[float] = Field(None, description="前年売上合計")
    total_sales_yoy: Optional[float] = Field(None, description="売上前年比（%）")

    total_customers: Optional[float] = Field(None, description="客数合計")
    total_customers_previous_year: Optional[float] = Field(None, description="前年客数合計")
    total_customers_yoy: Optional[float] = Field(None, description="客数前年比（%）")

    avg_unit_price: Optional[float] = Field(None, description="客単価")
    avg_unit_price_previous_year: Optional[float] = Field(None, description="前年客単価")
    avg_unit_price_yoy: Optional[float] = Field(None, description="客単価前年比（%）")

    # 商品グループ別データ
    products: List[ProductGroupDetail] = Field(default_factory=list, description="商品グループ別詳細")

    # 個別商品販売データ
    product_items: List[ProductItemDetail] = Field(default_factory=list, description="個別商品販売データ")


# =============================================================================
# 店舗別売上集計スキーマ
# =============================================================================

class StoreSummaryItem(BaseModel):
    """店舗別売上集計アイテム"""
    segment_id: str = Field(..., description="店舗ID")
    segment_code: str = Field(..., description="店舗コード")
    segment_name: str = Field(..., description="店舗名")
    sales: Optional[float] = Field(None, description="売上高（当月/累計実績）")
    sales_previous_year: Optional[float] = Field(None, description="売上高（前年同月/累計）")
    sales_yoy: Optional[float] = Field(None, description="売上高前年比（%）")
    sales_two_years_ago: Optional[float] = Field(None, description="売上高（前々年累計）※累計時のみ")
    sales_yoy_two_years: Optional[float] = Field(None, description="売上高前々年比（%）※累計時のみ")
    customers: Optional[float] = Field(None, description="客数（当月/累計実績）")
    customers_previous_year: Optional[float] = Field(None, description="客数（前年同月/累計）")
    customers_yoy: Optional[float] = Field(None, description="客数前年比（%）")
    customers_two_years_ago: Optional[float] = Field(None, description="客数（前々年累計）※累計時のみ")
    customers_yoy_two_years: Optional[float] = Field(None, description="客数前々年比（%）※累計時のみ")
    unit_price: Optional[float] = Field(None, description="客単価（当月/累計）")
    unit_price_previous_year: Optional[float] = Field(None, description="客単価（前年同月/累計）")
    unit_price_yoy: Optional[float] = Field(None, description="客単価前年比（%）")
    unit_price_two_years_ago: Optional[float] = Field(None, description="客単価（前々年累計）※累計時のみ")
    unit_price_yoy_two_years: Optional[float] = Field(None, description="客単価前々年比（%）※累計時のみ")


class StoreSummaryTotals(BaseModel):
    """店舗別売上集計合計"""
    sales: Optional[float] = Field(None, description="売上高合計（当月/累計）")
    sales_previous_year: Optional[float] = Field(None, description="売上高合計（前年同月/累計）")
    sales_yoy: Optional[float] = Field(None, description="売上高前年比（%）")
    sales_two_years_ago: Optional[float] = Field(None, description="売上高合計（前々年累計）※累計時のみ")
    sales_yoy_two_years: Optional[float] = Field(None, description="売上高前々年比（%）※累計時のみ")
    customers: Optional[float] = Field(None, description="客数合計（当月/累計）")
    customers_previous_year: Optional[float] = Field(None, description="客数合計（前年同月/累計）")
    customers_yoy: Optional[float] = Field(None, description="客数前年比（%）")
    customers_two_years_ago: Optional[float] = Field(None, description="客数合計（前々年累計）※累計時のみ")
    customers_yoy_two_years: Optional[float] = Field(None, description="客数前々年比（%）※累計時のみ")
    unit_price: Optional[float] = Field(None, description="客単価（当月/累計）")
    unit_price_previous_year: Optional[float] = Field(None, description="客単価（前年同月/累計）")
    unit_price_yoy: Optional[float] = Field(None, description="客単価前年比（%）")
    unit_price_two_years_ago: Optional[float] = Field(None, description="客単価（前々年累計）※累計時のみ")
    unit_price_yoy_two_years: Optional[float] = Field(None, description="客単価前々年比（%）※累計時のみ")


class StoreSummaryResponse(BaseModel):
    """
    店舗別売上集計レスポンススキーマ

    全店舗の売上高・客数・客単価と前年比を一覧表示する。
    単月モードと累計モードに対応。
    """
    period: str = Field(..., description="対象期間（YYYY-MM-DD形式）")
    department_slug: str = Field(..., description="部門スラッグ")
    period_type: str = Field(default="monthly", description="期間タイプ（monthly/cumulative）")
    fiscal_year: Optional[int] = Field(None, description="会計年度（累計時のみ）")
    stores: List[StoreSummaryItem] = Field(default_factory=list, description="店舗別データ")
    totals: StoreSummaryTotals = Field(..., description="合計")


class AvailableMonthsResponse(BaseModel):
    """
    利用可能な月一覧レスポンススキーマ

    データベースに格納されている全ての月を返す。
    """
    months: List[str] = Field(default_factory=list, description="利用可能な月のリスト（YYYY-MM-DD形式、降順）")


# =============================================================================
# 店舗別推移スキーマ
# =============================================================================

class StoreTrendItem(BaseModel):
    """全店舗推移の店舗別データ"""
    segment_id: str = Field(..., description="店舗ID")
    segment_name: str = Field(..., description="店舗名")
    values: List[Optional[float]] = Field(default_factory=list, description="月別売上（monthsと同じ順序・長さ）")


class StoreTrendAllResponse(BaseModel):
    """
    全店舗推移レスポンススキーマ

    全店舗の月別売上推移を返す。
    """
    fiscal_year: int = Field(..., description="会計年度")
    months: List[str] = Field(default_factory=list, description="月ラベル（YYYY-MM形式）")
    stores: List[StoreTrendItem] = Field(default_factory=list, description="店舗別データ")


class StoreTrendSummary(BaseModel):
    """単一店舗推移のサマリー"""
    total: Optional[float] = Field(None, description="当年合計")
    total_previous_year: Optional[float] = Field(None, description="前年合計")
    total_two_years_ago: Optional[float] = Field(None, description="前々年合計")
    yoy_rate: Optional[float] = Field(None, description="前年比（%）")


class StoreTrendSingleResponse(BaseModel):
    """
    単一店舗推移レスポンススキーマ

    単一店舗の月別売上推移と前年・前々年比較を返す。
    """
    segment_id: str = Field(..., description="店舗ID")
    segment_name: str = Field(..., description="店舗名")
    fiscal_year: int = Field(..., description="会計年度")
    months: List[str] = Field(default_factory=list, description="月ラベル（YYYY-MM形式）")
    actual: List[Optional[float]] = Field(default_factory=list, description="当年売上")
    previous_year: List[Optional[float]] = Field(default_factory=list, description="前年売上")
    two_years_ago: List[Optional[float]] = Field(default_factory=list, description="前々年売上")
    summary: StoreTrendSummary = Field(..., description="サマリー")
