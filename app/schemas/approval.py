"""
承認ワークフロースキーマ

申請種別マスタ・申請・承認ステップ・監査証跡・代理設定・Slack投稿先の
Pydanticスキーマを定義する。
"""
from datetime import datetime
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field


# =============================================================================
# 共通サブスキーマ
# =============================================================================

class ApprovalAttachment(BaseModel):
    """添付画像（Storage 上のオブジェクト）"""
    path: str = Field(..., description="Storage オブジェクトパス")
    url: str = Field(..., description="公開URL")
    filename: str = Field(default="", description="元ファイル名")


class ApproverInput(BaseModel):
    """申請時に指定する承認者1名"""
    step_no: int = Field(..., ge=1, description="承認順（parallel系は全員1）")
    assignee_id: str = Field(..., description="承認者ユーザーID")


# =============================================================================
# 申請種別マスタ
# =============================================================================

class RequestTypeBase(BaseModel):
    label: str = Field(..., min_length=1, description="表示名")
    description: Optional[str] = Field(None, description="起票画面に出す説明")
    default_approver_ids: List[str] = Field(default_factory=list, description="既定の承認者候補")
    default_approval_mode: str = Field(default="sequential", description="既定の承認モード")
    is_active: bool = Field(default=True)
    display_order: int = Field(default=100)


class RequestTypeCreate(RequestTypeBase):
    code: str = Field(..., min_length=1, pattern=r"^[a-z0-9_]+$", description="種別コード")


class RequestTypeUpdate(BaseModel):
    label: Optional[str] = Field(None, min_length=1)
    description: Optional[str] = None
    default_approver_ids: Optional[List[str]] = None
    default_approval_mode: Optional[str] = None
    is_active: Optional[bool] = None
    display_order: Optional[int] = None


class RequestType(RequestTypeBase):
    code: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# Slack 投稿先バインディング
# =============================================================================

class SlackChannelBindingCreate(BaseModel):
    request_type: str = Field(..., description="申請種別コード")
    label: str = Field(..., min_length=1, description="UI表示名")
    channel_id: str = Field(..., min_length=1, description="SlackチャンネルID")
    channel_name: str = Field(default="", description="チャンネル名（表示用）")
    is_default: bool = Field(default=False)


class SlackChannelBinding(SlackChannelBindingCreate):
    id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# 承認ステップ
# =============================================================================

class ApprovalStep(BaseModel):
    id: str
    request_id: str
    step_no: int
    assignee_id: str
    original_assignee_id: str
    assignee_email: str = ""
    assignee_name: Optional[str] = Field(None, description="表示名（user_profiles から解決）")
    status: str
    acted_at: Optional[datetime] = None
    comment: Optional[str] = None
    notified_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# 監査証跡
# =============================================================================

class ApprovalAction(BaseModel):
    id: str
    request_id: str
    step_id: Optional[str] = None
    actor_id: str
    actor_email: str = ""
    actor_name: Optional[str] = None
    on_behalf_of_id: Optional[str] = None
    action: str
    before_state: Dict[str, Any] = Field(default_factory=dict)
    after_state: Dict[str, Any] = Field(default_factory=dict)
    comment: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# 申請本体
# =============================================================================

class ApprovalRequestCreate(BaseModel):
    """下書き作成 / 下書き更新"""
    request_type: str = Field(..., description="申請種別コード")
    title: str = Field(default="", description="タイトル（下書き中は空可）")
    content: Dict[str, Any] = Field(default_factory=dict, description="申請コンテンツ")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="メタ（slack_channel_id 等）")
    approval_mode: Optional[str] = Field(None, description="承認モード（省略時は種別デフォルト）")
    approvers: List[ApproverInput] = Field(default_factory=list, description="承認者指定")


class ApprovalRequestSubmit(BaseModel):
    """申請（submit）時の最終確定パラメータ。下書き内容を上書きして申請する"""
    title: str = Field(..., min_length=1, description="タイトル")
    content: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    approval_mode: str = Field(default="sequential")
    approvers: List[ApproverInput] = Field(..., min_length=1, description="承認者（1名以上）")


class ApprovalActionRequest(BaseModel):
    """承認/却下/差戻のリクエストボディ"""
    comment: Optional[str] = Field(None, description="コメント")


class ApprovalReassignRequest(BaseModel):
    """承認者差替（admin/executive のみ）"""
    step_id: str = Field(..., description="対象ステップID")
    new_assignee_id: str = Field(..., description="新しい承認者ユーザーID")
    comment: Optional[str] = Field(None, description="差替理由")


class ApprovalRequestSummary(BaseModel):
    """一覧アイテム"""
    id: str
    request_type: str
    request_type_label: str = ""
    title: str
    status: str
    approval_mode: str
    requester_id: str
    requester_email: str = ""
    requester_name: Optional[str] = None
    current_step_no: int = 1
    my_step_pending: bool = Field(default=False, description="自分にアクションが回ってきているか")
    stalled: bool = Field(default=False, description="停滞フラグ")
    submitted_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ApprovalRequestDetail(ApprovalRequestSummary):
    """詳細（コンテンツ・ステップ・履歴込み）"""
    content: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    approved_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    steps: List[ApprovalStep] = Field(default_factory=list)
    actions: List[ApprovalAction] = Field(default_factory=list)
    can_act: bool = Field(default=False, description="操作ユーザーが承認アクション可能か")
    can_edit: bool = Field(default=False, description="操作ユーザーが編集可能か（起票者かつdraft）")


class ApprovalRequestListResponse(BaseModel):
    requests: List[ApprovalRequestSummary] = Field(default_factory=list)
    total: int = 0


class PendingCountResponse(BaseModel):
    count: int = 0


# =============================================================================
# 代理承認設定
# =============================================================================

class ApprovalDelegateCreate(BaseModel):
    user_id: Optional[str] = Field(None, description="委任元（省略時は自分）")
    delegate_id: str = Field(..., description="委任先ユーザーID")
    starts_at: datetime = Field(..., description="開始日時")
    ends_at: datetime = Field(..., description="終了日時")
    note: Optional[str] = None


class ApprovalDelegate(BaseModel):
    id: str
    user_id: str
    user_email: Optional[str] = None
    user_name: Optional[str] = None
    delegate_id: str
    delegate_email: Optional[str] = None
    delegate_name: Optional[str] = None
    starts_at: datetime
    ends_at: datetime
    note: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# 添付アップロード
# =============================================================================

class AttachmentUploadResponse(BaseModel):
    path: str
    url: str
    filename: str
