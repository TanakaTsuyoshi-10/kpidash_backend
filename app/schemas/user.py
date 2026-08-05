"""
利用者管理スキーマ

利用者管理のPydanticスキーマを定義する。
"""
from datetime import datetime
from typing import Optional, List
from enum import Enum

from pydantic import BaseModel, Field, field_validator
import re


# =============================================================================
# Enum定義
# =============================================================================

class UserRole(str, Enum):
    """ユーザー権限"""
    ADMIN = "admin"
    EXECUTIVE = "executive"
    USER = "user"


class PageKey(str, Enum):
    """ページキー"""
    DASHBOARD = "dashboard"
    FINANCE = "finance"
    ECOMMERCE = "ecommerce"
    MANUFACTURING = "manufacturing"
    COMPLAINTS = "complaints"
    PRODUCTS = "products"
    UPLOAD = "upload"
    TARGETS = "targets"
    BOARD = "board"          # 取締役会資料・議事録
    LABOR = "labor"          # 経営指標（部署別 人件費・時間外）
    SLACK = "slack"          # ダッシュボードの Slack 投稿表示
    APPROVALS = "approvals"  # 承認ワークフロー


ALL_PAGE_KEYS: List[str] = [k.value for k in PageKey]


# =============================================================================
# ユーザー情報スキーマ
# =============================================================================

class UserProfileBase(BaseModel):
    """ユーザープロファイル基本情報"""
    display_name: Optional[str] = Field(None, description="表示名", max_length=100)
    role: UserRole = Field(default=UserRole.USER, description="権限")
    is_active: bool = Field(default=True, description="有効フラグ")


class UserProfileCreate(BaseModel):
    """ユーザー新規登録"""
    email: str = Field(..., description="メールアドレス")
    password: str = Field(..., description="パスワード", min_length=8)
    display_name: Optional[str] = Field(None, description="表示名", max_length=100)
    role: UserRole = Field(default=UserRole.USER, description="権限")
    org_department_id: Optional[str] = Field(None, description="部署ID")
    position: Optional[str] = Field(None, description="役職", max_length=100)
    can_approve: bool = Field(default=False, description="承認権限（承認者に指定可能か）")
    approval_view_all: bool = Field(default=False, description="稟議の全社閲覧権限")

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        """メールアドレスの形式を検証する"""
        email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        if not re.match(email_pattern, v):
            raise ValueError("有効なメールアドレスを入力してください")
        return v


class UserProfileUpdate(BaseModel):
    """ユーザー情報更新

    org_department_id は空文字 "" を渡すと部署未設定にクリアされる。
    """
    display_name: Optional[str] = Field(None, description="表示名", max_length=100)
    role: Optional[UserRole] = Field(None, description="権限")
    is_active: Optional[bool] = Field(None, description="有効フラグ")
    org_department_id: Optional[str] = Field(None, description="部署ID（\"\"でクリア）")
    position: Optional[str] = Field(None, description="役職", max_length=100)
    can_approve: Optional[bool] = Field(None, description="承認権限")
    approval_view_all: Optional[bool] = Field(None, description="稟議の全社閲覧権限")


class UserProfileResponse(BaseModel):
    """ユーザープロファイルレスポンス"""
    id: str = Field(..., description="ユーザーID")
    email: str = Field(..., description="メールアドレス")
    display_name: Optional[str] = Field(None, description="表示名")
    role: str = Field(..., description="権限")
    role_name: Optional[str] = Field(None, description="権限名")
    is_active: bool = Field(default=True, description="有効フラグ")
    org_department_id: Optional[str] = Field(None, description="部署ID")
    org_department_name: Optional[str] = Field(None, description="部署名")
    position: Optional[str] = Field(None, description="役職")
    can_approve: bool = Field(default=False, description="承認権限")
    approval_view_all: bool = Field(default=False, description="稟議の全社閲覧権限")
    created_at: Optional[datetime] = Field(None, description="作成日時")
    updated_at: Optional[datetime] = Field(None, description="更新日時")
    last_sign_in_at: Optional[datetime] = Field(None, description="最終ログイン日時")


class UserListResponse(BaseModel):
    """ユーザー一覧レスポンス"""
    users: List[UserProfileResponse] = Field(default_factory=list, description="ユーザー一覧")
    total: int = Field(default=0, description="総件数")


# =============================================================================
# 権限マスタスキーマ
# =============================================================================

class UserRoleInfo(BaseModel):
    """権限情報"""
    code: str = Field(..., description="権限コード")
    name: str = Field(..., description="権限名")
    description: Optional[str] = Field(None, description="説明")


class UserRoleListResponse(BaseModel):
    """権限一覧レスポンス"""
    roles: List[UserRoleInfo] = Field(default_factory=list, description="権限一覧")


# =============================================================================
# 操作結果スキーマ
# =============================================================================

class UserOperationResult(BaseModel):
    """ユーザー操作結果"""
    success: bool = Field(..., description="成功フラグ")
    message: str = Field(..., description="メッセージ")
    user_id: Optional[str] = Field(None, description="ユーザーID")


# =============================================================================
# 現在のユーザー情報スキーマ
# =============================================================================

class CurrentUserResponse(BaseModel):
    """現在のユーザー情報"""
    id: str = Field(..., description="ユーザーID")
    email: str = Field(..., description="メールアドレス")
    display_name: Optional[str] = Field(None, description="表示名")
    role: str = Field(..., description="権限")
    is_admin: bool = Field(default=False, description="管理者フラグ")
    is_active: bool = Field(default=True, description="アカウント有効フラグ")
    allowed_pages: List[str] = Field(default_factory=list, description="閲覧許可ページ一覧")
    org_department_id: Optional[str] = Field(None, description="部署ID")
    org_department_name: Optional[str] = Field(None, description="部署名")
    position: Optional[str] = Field(None, description="役職")
    can_approve: bool = Field(default=False, description="承認権限")
    approval_view_all: bool = Field(default=False, description="稟議の全社閲覧権限")


# =============================================================================
# ページ権限スキーマ
# =============================================================================

class UserPagePermissionsUpdate(BaseModel):
    """ページ権限更新リクエスト"""
    page_keys: List[PageKey] = Field(default_factory=list, description="許可するページキー一覧")


class UserPagePermissionsResponse(BaseModel):
    """ページ権限レスポンス"""
    user_id: str = Field(..., description="ユーザーID")
    allowed_pages: List[str] = Field(default_factory=list, description="閲覧許可ページ一覧")


# =============================================================================
# 部署マスタスキーマ
# =============================================================================

class OrgDepartment(BaseModel):
    """部署"""
    id: str = Field(..., description="部署ID")
    name: str = Field(..., description="部署名")
    display_order: int = Field(default=0, description="表示順")
    is_active: bool = Field(default=True, description="有効フラグ")


class OrgDepartmentCreate(BaseModel):
    """部署作成"""
    name: str = Field(..., description="部署名", min_length=1, max_length=100)
    display_order: int = Field(default=0, description="表示順")


class OrgDepartmentUpdate(BaseModel):
    """部署更新"""
    name: Optional[str] = Field(None, description="部署名", min_length=1, max_length=100)
    display_order: Optional[int] = Field(None, description="表示順")
    is_active: Optional[bool] = Field(None, description="有効フラグ")


class OrgDepartmentListResponse(BaseModel):
    """部署一覧レスポンス"""
    departments: List[OrgDepartment] = Field(default_factory=list, description="部署一覧")
