"""
餃子ニュースAPIエンドポイント

餃子ニュース・業界情報のAPIエンドポイントを定義する。
"""
from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.schemas.news import NewsItem, NewsResponse
from app.services import news_service

router = APIRouter()


@router.get(
    "/gyoza",
    response_model=NewsResponse,
    summary="餃子ニュース取得",
    description="Google ニュースから餃子関連の最新ニュースを取得する。",
)
async def get_gyoza_news(
    limit: int = Query(8, ge=1, le=20, description="取得件数"),
    current_user=Depends(get_current_user),
) -> NewsResponse:
    """餃子ニュース一覧を取得する。

    取得失敗時は空の一覧を返す（ダッシュボードを壊さない）。
    """
    items = await news_service.get_gyoza_news(limit=limit)
    return NewsResponse(items=[NewsItem(**item) for item in items])
