"""
月次コメントAPIエンドポイントモジュール

月次コメントの取得・追加・編集・削除・履歴取得APIを提供する。
複数コメント対応・全ユーザー編集可能・編集履歴追跡。
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from supabase import Client

from app.api.deps import get_current_user, get_supabase_admin
from app.schemas.kpi import User
from app.schemas.comments import (
    SaveCommentRequest,
    UpdateCommentRequest,
    MonthlyComment,
    MonthlyCommentsResponse,
    CommentEditHistoryEntry,
    CommentEditHistoryResponse,
)


router = APIRouter(tags=["comments"])

# 有効なカテゴリ
VALID_CATEGORIES = ["store", "ecommerce", "finance", "manufacturing", "regional"]


# =============================================================================
# コメント一覧取得エンドポイント
# =============================================================================

@router.get(
    "/comments/{category}",
    response_model=MonthlyCommentsResponse,
    summary="月次コメント一覧取得",
    description="""
    指定カテゴリ・月のコメント一覧を取得する。

    ## カテゴリ
    - store: 店舗部門
    - ecommerce: 通販部門
    - finance: 財務
    - manufacturing: 製造
    - regional: 地域別

    ## パラメータ
    - category: カテゴリ（パスパラメータ）
    - period: 対象月（YYYY-MM-01形式、クエリパラメータ）

    ## レスポンス
    - comments: コメントリスト（時系列順）
    """,
)
async def get_monthly_comments(
    category: str,
    period: str = Query(..., description="対象月（YYYY-MM-01形式）"),
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
) -> MonthlyCommentsResponse:
    """指定カテゴリ・月のコメント一覧を取得"""
    if category not in VALID_CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不正なカテゴリ: {category}。有効な値: {', '.join(VALID_CATEGORIES)}"
        )

    try:
        response = supabase.table("monthly_comments").select(
            "id, category, period, comment, created_by, created_by_email, "
            "updated_by, updated_by_email, created_at, updated_at"
        ).eq("category", category).eq("period", period).order("created_at").execute()

        comments = []
        for row in (response.data or []):
            comments.append(MonthlyComment(
                id=row["id"],
                category=row["category"],
                period=row["period"],
                comment=row["comment"],
                created_by=row.get("created_by"),
                created_by_email=row.get("created_by_email"),
                updated_by=row.get("updated_by"),
                updated_by_email=row.get("updated_by_email"),
                created_at=row.get("created_at"),
                updated_at=row.get("updated_at"),
            ))

        return MonthlyCommentsResponse(comments=comments)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"コメントの取得に失敗しました: {str(e)}"
        )


# =============================================================================
# コメント追加エンドポイント
# =============================================================================

@router.post(
    "/comments",
    response_model=MonthlyComment,
    summary="月次コメント追加",
    description="""
    新規コメントを追加する。認証済みユーザーなら誰でも追加可能。

    ## リクエストボディ
    - category: カテゴリ（store, ecommerce, finance, manufacturing, regional）
    - period: 対象月（YYYY-MM-01形式）
    - comment: コメント内容
    """,
)
async def add_monthly_comment(
    data: SaveCommentRequest,
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
) -> MonthlyComment:
    """新規コメントを追加"""
    if data.category not in VALID_CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不正なカテゴリ: {data.category}。有効な値: {', '.join(VALID_CATEGORIES)}"
        )

    try:
        insert_data = {
            "category": data.category,
            "period": data.period,
            "comment": data.comment,
            "created_by": current_user.user_id,
            "created_by_email": current_user.email,
        }
        response = supabase.table("monthly_comments").insert(insert_data).execute()

        if response.data and len(response.data) > 0:
            row = response.data[0]
            return MonthlyComment(
                id=row["id"],
                category=row["category"],
                period=row["period"],
                comment=row["comment"],
                created_by=row.get("created_by"),
                created_by_email=row.get("created_by_email"),
                updated_by=row.get("updated_by"),
                updated_by_email=row.get("updated_by_email"),
                created_at=row.get("created_at"),
                updated_at=row.get("updated_at"),
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="コメントの保存に失敗しました"
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"コメントの保存に失敗しました: {str(e)}"
        )


# =============================================================================
# コメント編集エンドポイント
# =============================================================================

@router.put(
    "/comments/{comment_id}",
    response_model=MonthlyComment,
    summary="月次コメント編集",
    description="""
    指定IDのコメントを編集する。認証済みユーザーなら誰でも編集可能。
    編集前のテキストは編集履歴に自動保存される。
    """,
)
async def update_monthly_comment(
    comment_id: str,
    data: UpdateCommentRequest,
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
) -> MonthlyComment:
    """指定IDのコメントを編集（編集履歴を自動保存）"""
    try:
        # 1. 対象コメントの現在テキストを取得
        existing = supabase.table("monthly_comments").select(
            "id, comment"
        ).eq("id", comment_id).execute()

        if not existing.data or len(existing.data) == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="コメントが見つかりません"
            )

        previous_comment = existing.data[0]["comment"]

        # 2. 編集履歴に旧テキストを保存
        supabase.table("comment_edit_history").insert({
            "comment_id": comment_id,
            "previous_comment": previous_comment,
            "edited_by": current_user.user_id,
            "edited_by_email": current_user.email,
        }).execute()

        # 3. コメントを更新
        response = supabase.table("monthly_comments").update({
            "comment": data.comment,
            "updated_by": current_user.user_id,
            "updated_by_email": current_user.email,
        }).eq("id", comment_id).execute()

        if response.data and len(response.data) > 0:
            row = response.data[0]
            return MonthlyComment(
                id=row["id"],
                category=row["category"],
                period=row["period"],
                comment=row["comment"],
                created_by=row.get("created_by"),
                created_by_email=row.get("created_by_email"),
                updated_by=row.get("updated_by"),
                updated_by_email=row.get("updated_by_email"),
                created_at=row.get("created_at"),
                updated_at=row.get("updated_at"),
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="コメントの更新に失敗しました"
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"コメントの更新に失敗しました: {str(e)}"
        )


# =============================================================================
# コメント削除エンドポイント
# =============================================================================

@router.delete(
    "/comments/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="月次コメント削除",
    description="""
    指定IDのコメントを削除する。認証済みユーザーなら誰でも削除可能。
    """,
)
async def delete_monthly_comment(
    comment_id: str,
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
) -> Response:
    """指定IDのコメントを削除"""
    try:
        # コメントの存在確認
        existing = supabase.table("monthly_comments").select(
            "id"
        ).eq("id", comment_id).execute()

        if not existing.data or len(existing.data) == 0:
            return Response(status_code=status.HTTP_204_NO_CONTENT)

        supabase.table("monthly_comments").delete().eq(
            "id", comment_id
        ).execute()

        return Response(status_code=status.HTTP_204_NO_CONTENT)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"コメントの削除に失敗しました: {str(e)}"
        )


# =============================================================================
# 編集履歴取得エンドポイント
# =============================================================================

@router.get(
    "/comments/{comment_id}/history",
    response_model=CommentEditHistoryResponse,
    summary="コメント編集履歴取得",
    description="""
    指定コメントの編集履歴を取得する。新しい順で返す。
    """,
)
async def get_comment_history(
    comment_id: str,
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
) -> CommentEditHistoryResponse:
    """指定コメントの編集履歴を取得"""
    try:
        response = supabase.table("comment_edit_history").select(
            "id, previous_comment, edited_by, edited_by_email, edited_at"
        ).eq("comment_id", comment_id).order("edited_at", desc=True).execute()

        history = []
        for row in (response.data or []):
            history.append(CommentEditHistoryEntry(
                id=row["id"],
                previous_comment=row["previous_comment"],
                edited_by=row.get("edited_by"),
                edited_by_email=row.get("edited_by_email"),
                edited_at=row.get("edited_at"),
            ))

        return CommentEditHistoryResponse(history=history)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"編集履歴の取得に失敗しました: {str(e)}"
        )
