"""
餃子ニューススキーマ

餃子ニュース・業界情報機能のPydanticスキーマを定義する。
"""
from typing import List, Optional

from pydantic import BaseModel, Field


class NewsItem(BaseModel):
    """ニュース記事1件"""
    title: str = Field(..., description="記事見出し")
    link: str = Field(..., description="記事URL")
    source: str = Field(..., description="掲載媒体名")
    published_at: Optional[str] = Field(None, description="公開日時（ISO 8601文字列）")
    category: Optional[str] = Field(None, description="カテゴリ（任意）")

    class Config:
        from_attributes = True


class NewsResponse(BaseModel):
    """餃子ニュースレスポンス"""
    items: List[NewsItem] = Field(default_factory=list, description="ニュース記事一覧")

    class Config:
        from_attributes = True
