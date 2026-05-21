"""
取締役会資料・議事録スキーマ

取締役会の資料・議事録機能のPydanticスキーマを定義する。
"""
from datetime import date as date_type, datetime
from typing import Optional, List

from pydantic import BaseModel, Field


# =============================================================================
# 共通サブスキーマ
# =============================================================================

class BoardMaterial(BaseModel):
    """取締役会資料（リンク）"""
    label: str = Field(..., description="資料ラベル（表示名）")
    url: str = Field(..., description="資料URL（GoogleスライドURLなど）")


class BoardTopic(BaseModel):
    """決議・報告トピック"""
    category: str = Field(..., description="区分（'決議' または '報告'）")
    title: str = Field(..., description="トピックの内容")


# =============================================================================
# 取締役会 登録・更新スキーマ
# =============================================================================

class BoardMeetingCreate(BaseModel):
    """取締役会 新規登録"""
    meeting_date: date_type = Field(..., description="開催日")
    title: str = Field(..., min_length=1, description="タイトル")
    materials: List[BoardMaterial] = Field(default_factory=list, description="資料一覧")
    topics: List[BoardTopic] = Field(default_factory=list, description="決議・報告トピック一覧")
    minutes_text: Optional[str] = Field(None, description="議事録本文")


class BoardMeetingUpdate(BaseModel):
    """取締役会 更新"""
    meeting_date: Optional[date_type] = Field(None, description="開催日")
    title: Optional[str] = Field(None, min_length=1, description="タイトル")
    materials: Optional[List[BoardMaterial]] = Field(None, description="資料一覧")
    topics: Optional[List[BoardTopic]] = Field(None, description="決議・報告トピック一覧")
    minutes_text: Optional[str] = Field(None, description="議事録本文")


# =============================================================================
# 取締役会 詳細スキーマ
# =============================================================================

class BoardMeeting(BaseModel):
    """取締役会 詳細"""
    id: str = Field(..., description="取締役会ID")
    meeting_date: date_type = Field(..., description="開催日")
    title: str = Field(..., description="タイトル")
    materials: List[BoardMaterial] = Field(default_factory=list, description="資料一覧")
    topics: List[BoardTopic] = Field(default_factory=list, description="決議・報告トピック一覧")
    minutes_text: Optional[str] = Field(None, description="議事録本文")
    created_by: Optional[str] = Field(None, description="作成者ID")
    created_at: datetime = Field(..., description="作成日時")
    updated_at: datetime = Field(..., description="更新日時")

    class Config:
        from_attributes = True


# =============================================================================
# 一覧スキーマ
# =============================================================================

class BoardMeetingListItem(BaseModel):
    """取締役会 一覧アイテム（議事録本文は含めない）"""
    id: str = Field(..., description="取締役会ID")
    meeting_date: date_type = Field(..., description="開催日")
    title: str = Field(..., description="タイトル")
    topics: List[BoardTopic] = Field(default_factory=list, description="決議・報告トピック一覧")

    class Config:
        from_attributes = True


class BoardMeetingListResponse(BaseModel):
    """取締役会 一覧レスポンス"""
    meetings: List[BoardMeetingListItem] = Field(default_factory=list, description="取締役会一覧")
    total: int = Field(default=0, description="総件数")

    class Config:
        from_attributes = True
