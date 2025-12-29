"""
クレーム管理スキーマ

クレーム管理機能のPydanticスキーマを定義する。
"""
from datetime import date as date_type, datetime
from decimal import Decimal
from typing import Optional, List
from enum import Enum

from pydantic import BaseModel, Field


# =============================================================================
# Enum定義
# =============================================================================

class DepartmentTypeEnum(str, Enum):
    """発生部署種類"""
    STORE = "store"
    ECOMMERCE = "ecommerce"
    HEADQUARTERS = "headquarters"


class CustomerTypeEnum(str, Enum):
    """顧客種類"""
    NEW = "new"
    REPEAT = "repeat"
    UNKNOWN = "unknown"


class ComplaintTypeEnum(str, Enum):
    """クレーム種類"""
    CUSTOMER_SERVICE = "customer_service"  # 接客関連
    FACILITY = "facility"                   # 店舗設備関連
    OPERATION = "operation"                 # 操作方法関連
    PRODUCT = "product"                     # 味・商品関連
    OTHER = "other"                         # その他


class ComplaintStatusEnum(str, Enum):
    """対応状況"""
    IN_PROGRESS = "in_progress"  # 対応中
    COMPLETED = "completed"       # 対応済


# =============================================================================
# マスタデータスキーマ
# =============================================================================

class ComplaintTypeMaster(BaseModel):
    """クレーム種類マスタ"""
    code: str = Field(..., description="コード")
    name: str = Field(..., description="表示名")
    display_order: int = Field(default=0, description="表示順")

    class Config:
        from_attributes = True


class DepartmentTypeMaster(BaseModel):
    """発生部署種類マスタ"""
    code: str = Field(..., description="コード")
    name: str = Field(..., description="表示名")
    display_order: int = Field(default=0, description="表示順")

    class Config:
        from_attributes = True


class CustomerTypeMaster(BaseModel):
    """顧客種類マスタ"""
    code: str = Field(..., description="コード")
    name: str = Field(..., description="表示名")
    display_order: int = Field(default=0, description="表示順")

    class Config:
        from_attributes = True


class ComplaintMasterDataResponse(BaseModel):
    """クレームマスタデータレスポンス"""
    complaint_types: List[ComplaintTypeMaster] = Field(default_factory=list, description="クレーム種類一覧")
    department_types: List[DepartmentTypeMaster] = Field(default_factory=list, description="発生部署種類一覧")
    customer_types: List[CustomerTypeMaster] = Field(default_factory=list, description="顧客種類一覧")

    class Config:
        from_attributes = True


# =============================================================================
# クレーム登録・更新スキーマ
# =============================================================================

class ComplaintCreate(BaseModel):
    """クレーム新規登録"""
    incident_date: date_type = Field(..., description="発生日")

    # 発生部署
    department_type: DepartmentTypeEnum = Field(..., description="発生部署種類")
    segment_id: Optional[str] = Field(None, description="店舗ID（店舗の場合のみ）")

    # 顧客情報
    customer_type: CustomerTypeEnum = Field(..., description="顧客種類")
    customer_name: Optional[str] = Field(None, max_length=100, description="顧客名")
    contact_info: Optional[str] = Field(None, max_length=200, description="連絡先")

    # クレーム情報
    complaint_type: ComplaintTypeEnum = Field(..., description="クレーム種類")
    complaint_content: str = Field(..., min_length=1, description="クレーム内容")

    # 対応情報
    responder_name: Optional[str] = Field(None, max_length=100, description="対応者名")
    status: ComplaintStatusEnum = Field(default=ComplaintStatusEnum.IN_PROGRESS, description="対応状況")
    response_summary: Optional[str] = Field(None, description="対応の概要")
    resolution_cost: Decimal = Field(default=Decimal("0"), ge=0, description="対応に要した金額")


class ComplaintUpdate(BaseModel):
    """クレーム更新"""
    incident_date: Optional[date_type] = Field(None, description="発生日")

    # 発生部署
    department_type: Optional[DepartmentTypeEnum] = Field(None, description="発生部署種類")
    segment_id: Optional[str] = Field(None, description="店舗ID（店舗の場合のみ）")

    # 顧客情報
    customer_type: Optional[CustomerTypeEnum] = Field(None, description="顧客種類")
    customer_name: Optional[str] = Field(None, max_length=100, description="顧客名")
    contact_info: Optional[str] = Field(None, max_length=200, description="連絡先")

    # クレーム情報
    complaint_type: Optional[ComplaintTypeEnum] = Field(None, description="クレーム種類")
    complaint_content: Optional[str] = Field(None, description="クレーム内容")

    # 対応情報
    responder_name: Optional[str] = Field(None, max_length=100, description="対応者名")
    status: Optional[ComplaintStatusEnum] = Field(None, description="対応状況")
    response_summary: Optional[str] = Field(None, description="対応の概要")
    resolution_cost: Optional[Decimal] = Field(None, ge=0, description="対応に要した金額")


# =============================================================================
# クレーム詳細スキーマ
# =============================================================================

class Complaint(BaseModel):
    """クレーム詳細"""
    id: str = Field(..., description="クレームID")
    incident_date: date_type = Field(..., description="発生日")
    registered_at: datetime = Field(..., description="登録日時")

    # 発生部署
    department_type: str = Field(..., description="発生部署種類")
    department_type_name: str = Field(..., description="発生部署名")
    segment_id: Optional[str] = Field(None, description="店舗ID")
    segment_name: Optional[str] = Field(None, description="店舗名")

    # 顧客情報
    customer_type: str = Field(..., description="顧客種類")
    customer_type_name: str = Field(..., description="顧客種類名")
    customer_name: Optional[str] = Field(None, description="顧客名")
    contact_info: Optional[str] = Field(None, description="連絡先")

    # クレーム情報
    complaint_type: str = Field(..., description="クレーム種類")
    complaint_type_name: str = Field(..., description="クレーム種類名")
    complaint_content: str = Field(..., description="クレーム内容")

    # 対応情報
    responder_name: Optional[str] = Field(None, description="対応者名")
    status: str = Field(..., description="対応状況")
    status_name: str = Field(..., description="対応状況名")
    response_summary: Optional[str] = Field(None, description="対応の概要")
    resolution_cost: Decimal = Field(default=Decimal("0"), description="対応に要した金額")
    completed_at: Optional[datetime] = Field(None, description="完了日時")

    # メタデータ
    created_by_email: Optional[str] = Field(None, description="作成者メールアドレス")
    created_at: datetime = Field(..., description="作成日時")
    updated_at: datetime = Field(..., description="更新日時")

    class Config:
        from_attributes = True


# =============================================================================
# 一覧・検索スキーマ
# =============================================================================

class ComplaintListItem(BaseModel):
    """クレーム一覧アイテム（簡易版）"""
    id: str = Field(..., description="クレームID")
    incident_date: date_type = Field(..., description="発生日")
    department_type: str = Field(..., description="発生部署種類")
    department_type_name: str = Field(..., description="発生部署名")
    segment_name: Optional[str] = Field(None, description="店舗名")
    customer_type_name: str = Field(..., description="顧客種類名")
    complaint_type: str = Field(..., description="クレーム種類")
    complaint_type_name: str = Field(..., description="クレーム種類名")
    complaint_content: str = Field(..., description="クレーム内容（先頭100文字）")
    status: str = Field(..., description="対応状況")
    status_name: str = Field(..., description="対応状況名")
    responder_name: Optional[str] = Field(None, description="対応者名")
    resolution_cost: Decimal = Field(default=Decimal("0"), description="対応に要した金額")
    created_at: datetime = Field(..., description="作成日時")

    class Config:
        from_attributes = True


class ComplaintListResponse(BaseModel):
    """クレーム一覧レスポンス"""
    complaints: List[ComplaintListItem] = Field(default_factory=list, description="クレーム一覧")
    total_count: int = Field(default=0, description="総件数")
    page: int = Field(default=1, description="現在ページ")
    page_size: int = Field(default=20, description="1ページあたり件数")
    total_pages: int = Field(default=1, description="総ページ数")

    class Config:
        from_attributes = True


# =============================================================================
# 月別サマリースキーマ
# =============================================================================

class ComplaintMonthlySummary(BaseModel):
    """クレーム月別サマリー"""
    month: date_type = Field(..., description="対象月")
    total_count: int = Field(default=0, description="総件数")
    completed_count: int = Field(default=0, description="対応済件数")
    in_progress_count: int = Field(default=0, description="対応中件数")

    # 部署別内訳
    store_count: int = Field(default=0, description="店舗件数")
    ecommerce_count: int = Field(default=0, description="通販件数")
    headquarters_count: int = Field(default=0, description="本社件数")

    # 種類別内訳
    customer_service_count: int = Field(default=0, description="接客関連件数")
    facility_count: int = Field(default=0, description="店舗設備関連件数")
    operation_count: int = Field(default=0, description="操作方法関連件数")
    product_count: int = Field(default=0, description="味・商品関連件数")
    other_count: int = Field(default=0, description="その他件数")

    # コスト
    total_resolution_cost: Decimal = Field(default=Decimal("0"), description="対応費用合計")

    class Config:
        from_attributes = True


class ComplaintDashboardSummary(BaseModel):
    """ダッシュボード用クレームサマリー"""
    current_month_count: int = Field(default=0, description="今月のクレーム件数")
    previous_month_count: int = Field(default=0, description="先月のクレーム件数")
    yoy_rate: Optional[Decimal] = Field(None, description="前年比（%）")
    in_progress_count: int = Field(default=0, description="対応中件数")

    class Config:
        from_attributes = True
