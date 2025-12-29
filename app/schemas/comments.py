"""
月次コメントスキーマモジュール

月次コメントのリクエスト/レスポンススキーマを定義する。
"""
from datetime import datetime
from typing import Optional

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


class MonthlyComment(BaseModel):
    """月次コメント"""
    id: Optional[str] = Field(None, description="コメントID")
    category: str = Field(..., description="カテゴリ")
    period: str = Field(..., description="対象月")
    comment: str = Field(..., description="コメント内容")
    created_by: Optional[str] = Field(None, description="作成者ユーザーID")
    created_by_email: Optional[str] = Field(None, description="作成者メールアドレス")
    is_owner: bool = Field(False, description="現在のユーザーが作成者かどうか")
    created_at: Optional[datetime] = Field(None, description="作成日時")
    updated_at: Optional[datetime] = Field(None, description="更新日時")


class MonthlyCommentResponse(BaseModel):
    """コメント取得レスポンス"""
    comment: Optional[MonthlyComment] = Field(None, description="コメント（存在しない場合はnull）")
