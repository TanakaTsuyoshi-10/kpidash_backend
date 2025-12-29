"""
月次コメントAPIエンドポイントモジュール

月次コメントの取得・保存・削除APIを提供する。
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from supabase import Client

from app.api.deps import get_current_user, get_supabase_admin
from app.schemas.kpi import User
from app.schemas.comments import (
    SaveCommentRequest,
    MonthlyComment,
    MonthlyCommentResponse,
)


router = APIRouter(tags=["comments"])

# 有効なカテゴリ
VALID_CATEGORIES = ["store", "ecommerce", "finance", "manufacturing", "regional"]


# =============================================================================
# コメント取得エンドポイント
# =============================================================================

@router.get(
    "/comments/{category}",
    response_model=MonthlyCommentResponse,
    summary="月次コメント取得",
    description="""
    指定カテゴリ・月のコメントを取得する。

    ## カテゴリ
    - store: 店舗部門
    - ecommerce: 通販部門
    - finance: 財務
    - manufacturing: 製造

    ## パラメータ
    - category: カテゴリ（パスパラメータ）
    - period: 対象月（YYYY-MM-01形式、クエリパラメータ）

    ## レスポンス
    - is_owner: 現在のユーザーがコメント作成者かどうか
    - created_by_email: 作成者のメールアドレス
    """,
)
async def get_monthly_comment(
    category: str,
    period: str = Query(..., description="対象月（YYYY-MM-01形式）"),
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
) -> MonthlyCommentResponse:
    """
    指定カテゴリ・月のコメントを取得

    Args:
        category: カテゴリ
        period: 対象月（YYYY-MM-01形式）

    Returns:
        MonthlyCommentResponse: コメント（存在しない場合はnull）
    """
    if category not in VALID_CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不正なカテゴリ: {category}。有効な値: {', '.join(VALID_CATEGORIES)}"
        )

    try:
        response = supabase.table("monthly_comments").select(
            "id, category, period, comment, created_by, created_by_email, created_at, updated_at"
        ).eq("category", category).eq("period", period).execute()

        if response.data and len(response.data) > 0:
            row = response.data[0]
            created_by = row.get("created_by")
            is_owner = created_by == current_user.user_id if created_by else False

            return MonthlyCommentResponse(
                comment=MonthlyComment(
                    id=row["id"],
                    category=row["category"],
                    period=row["period"],
                    comment=row["comment"],
                    created_by=created_by,
                    created_by_email=row.get("created_by_email"),
                    is_owner=is_owner,
                    created_at=row.get("created_at"),
                    updated_at=row.get("updated_at"),
                )
            )
        else:
            return MonthlyCommentResponse(comment=None)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"コメントの取得に失敗しました: {str(e)}"
        )


# =============================================================================
# コメント保存エンドポイント
# =============================================================================

@router.post(
    "/comments",
    response_model=MonthlyComment,
    summary="月次コメント保存",
    description="""
    コメントを保存する。

    - 新規作成: 誰でも作成可能
    - 更新: 作成者本人のみ更新可能

    ## リクエストボディ
    - category: カテゴリ（store, ecommerce, finance, manufacturing）
    - period: 対象月（YYYY-MM-01形式）
    - comment: コメント内容
    """,
)
async def save_monthly_comment(
    data: SaveCommentRequest,
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
) -> MonthlyComment:
    """
    コメントを保存

    Args:
        data: 保存データ

    Returns:
        MonthlyComment: 保存されたコメント
    """
    if data.category not in VALID_CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不正なカテゴリ: {data.category}。有効な値: {', '.join(VALID_CATEGORIES)}"
        )

    try:
        # 既存コメントの確認
        existing = supabase.table("monthly_comments").select(
            "id, created_by"
        ).eq("category", data.category).eq("period", data.period).execute()

        if existing.data and len(existing.data) > 0:
            # 既存コメントがある場合、作成者のみ更新可能
            existing_comment = existing.data[0]
            if existing_comment.get("created_by") != current_user.user_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="このコメントを編集する権限がありません。作成者のみ編集できます。"
                )

            # 更新処理
            update_data = {
                "comment": data.comment,
            }
            response = supabase.table("monthly_comments").update(
                update_data
            ).eq("id", existing_comment["id"]).execute()
        else:
            # 新規作成
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
                is_owner=True,  # 保存後は必ず自分のコメント
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
# コメント削除エンドポイント
# =============================================================================

@router.delete(
    "/comments/{category}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="月次コメント削除",
    description="""
    指定カテゴリ・月のコメントを削除する。
    作成者本人のみ削除可能。

    ## パラメータ
    - category: カテゴリ（パスパラメータ）
    - period: 対象月（YYYY-MM-01形式、クエリパラメータ）
    """,
)
async def delete_monthly_comment(
    category: str,
    period: str = Query(..., description="対象月（YYYY-MM-01形式）"),
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
) -> Response:
    """
    指定カテゴリ・月のコメントを削除

    Args:
        category: カテゴリ
        period: 対象月（YYYY-MM-01形式）

    Returns:
        204 No Content
    """
    if category not in VALID_CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不正なカテゴリ: {category}。有効な値: {', '.join(VALID_CATEGORIES)}"
        )

    try:
        # 既存コメントの確認
        existing = supabase.table("monthly_comments").select(
            "id, created_by"
        ).eq("category", category).eq("period", period).execute()

        if not existing.data or len(existing.data) == 0:
            # コメントが存在しない場合は204を返す（冪等性）
            return Response(status_code=status.HTTP_204_NO_CONTENT)

        existing_comment = existing.data[0]
        if existing_comment.get("created_by") != current_user.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="このコメントを削除する権限がありません。作成者のみ削除できます。"
            )

        supabase.table("monthly_comments").delete().eq(
            "id", existing_comment["id"]
        ).execute()

        return Response(status_code=status.HTTP_204_NO_CONTENT)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"コメントの削除に失敗しました: {str(e)}"
        )
