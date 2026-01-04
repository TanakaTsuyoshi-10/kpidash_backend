"""
管理者用エンドポイント
キャッシュ管理などのシステム管理機能を提供
"""
from fastapi import APIRouter, Depends
from app.services.cache_service import cache
from app.api.deps import get_current_user
from app.schemas.kpi import User

router = APIRouter(tags=["管理"])


@router.get("/cache/stats")
async def get_cache_stats(
    current_user: User = Depends(get_current_user)
):
    """
    キャッシュ統計情報を取得

    Returns:
        キャッシュの統計情報（エントリ数、キー一覧など）
    """
    return cache.stats()


@router.post("/cache/clear")
async def clear_cache(
    prefix: str = None,
    current_user: User = Depends(get_current_user)
):
    """
    キャッシュをクリア

    Args:
        prefix: クリアするキャッシュのプレフィックス（省略時は全クリア）

    Returns:
        クリア結果
    """
    if prefix:
        count = cache.clear_prefix(prefix)
        return {"message": f"プレフィックス '{prefix}' のキャッシュを {count} 件クリアしました"}
    else:
        cache.clear_all()
        return {"message": "全キャッシュをクリアしました"}


@router.post("/cache/cleanup")
async def cleanup_cache(
    current_user: User = Depends(get_current_user)
):
    """
    期限切れキャッシュを削除

    Returns:
        削除結果
    """
    count = cache.cleanup_expired()
    return {"message": f"期限切れキャッシュを {count} 件削除しました"}
