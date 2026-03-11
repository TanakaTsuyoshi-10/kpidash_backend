"""
月次コメントスキーマモジュール

月次コメントのリクエスト/レスポンススキーマを定義する。
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class SaveCommentRequest(BaseModel):
    """コメント保存リクエスト"""
    category: str = Field(
        ...,
        description="カテゴリ: store, ecommerce, finance, manufacturing"
    )
    period: str = Field(
        ...,
        description="対象月（YYYY-MM-01形式）"
    )
    comment: str = Field(
        ...,
        description="コメント内容"
    )


class UpdateCommentRequest(BaseModel):
    """コメント更新リクエスト"""
    comment: str = Field(
        ...,
        description="コメント内容"
    )


class MonthlyComment(BaseModel):
    """月次コメント"""
    id: Optional[str] = Field(None, description="コメントID")
    category: str = Field(..., description="カテゴリ")
    period: str = Field(..., description="対象月")
    comment: str = Field(..., description="コメント内容")
    created_by: Optional[str] = Field(None, description="作成者ユーザーID")
    created_by_email: Optional[str] = Field(None, description="作成者メールアドレス")
    updated_by: Optional[str] = Field(None, description="最終編集者ユーザーID")
    updated_by_email: Optional[str] = Field(None, description="最終編集者メールアドレス")
    created_at: Optional[datetime] = Field(None, description="作成日時")
    updated_at: Optional[datetime] = Field(None, description="更新日時")


class MonthlyCommentsResponse(BaseModel):
    """複数コメント取得レスポンス"""
    comments: List[MonthlyComment] = Field(default_factory=list, description="コメントリスト")


class CommentEditHistoryEntry(BaseModel):
    """編集履歴エントリ"""
    id: str
    previous_comment: str
    edited_by: Optional[str] = None
    edited_by_email: Optional[str] = None
    edited_at: Optional[datetime] = None


class CommentEditHistoryResponse(BaseModel):
    """編集履歴レスポンス"""
    history: List[CommentEditHistoryEntry] = Field(default_factory=list, description="編集履歴リスト")
