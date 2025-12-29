"""
認証エンドポイントモジュール

ユーザー認証に関連するエンドポイントを提供する。
Supabase Authと連携してJWTトークンベースの認証を行う。
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from supabase import Client

from app.api.deps import get_current_user, get_supabase_admin
from app.schemas.kpi import User, UserResponse

# ルーター作成
# prefix="/auth" は main.py で設定される
router = APIRouter(tags=["認証"])


@router.get(
    "/me",
    response_model=UserResponse,
    summary="現在のユーザー情報を取得",
    description="""
    JWTトークンから現在ログインしているユーザーの情報を取得する。

    このエンドポイントは認証必須。
    Authorizationヘッダーに有効なBearerトークンを設定する必要がある。
    """,
    responses={
        200: {
            "description": "ユーザー情報の取得成功",
            "content": {
                "application/json": {
                    "example": {
                        "user_id": "12345678-1234-1234-1234-123456789abc",
                        "email": "user@example.com",
                        "department_id": "87654321-4321-4321-4321-cba987654321",
                        "department_name": "店舗部門"
                    }
                }
            }
        },
        401: {
            "description": "認証エラー（トークンなし、無効、期限切れ）",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "認証が必要です。Authorizationヘッダーにトークンを設定してください。"
                    }
                }
            }
        }
    }
)
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
) -> UserResponse:
    """
    現在のログインユーザー情報を取得する

    JWTトークンを検証し、ユーザーの基本情報と所属部門を返す。
    部門IDが設定されている場合は、departmentsテーブルから部門名を取得する。

    Args:
        current_user: JWT検証により取得された現在のユーザー
        supabase: Supabase管理者クライアント（部門名取得用）

    Returns:
        UserResponse: ユーザー情報（部門名を含む）
    """
    department_name: Optional[str] = None

    # 部門IDが設定されている場合、部門名を取得
    if current_user.department_id:
        try:
            result = supabase.table("departments").select("name").eq(
                "id", current_user.department_id
            ).single().execute()

            if result.data:
                department_name = result.data.get("name")

        except Exception:
            # 部門情報の取得に失敗しても、ユーザー情報は返す
            # エラーログは本番環境で適切に記録すべき
            pass

    return UserResponse(
        user_id=current_user.user_id,
        email=current_user.email,
        department_id=current_user.department_id,
        department_name=department_name,
    )


@router.get(
    "/verify",
    summary="トークン検証",
    description="""
    JWTトークンが有効かどうかを検証する。

    フロントエンドでトークンの有効性を確認する際に使用する。
    """,
    responses={
        200: {
            "description": "トークンは有効",
            "content": {
                "application/json": {
                    "example": {
                        "valid": True,
                        "user_id": "12345678-1234-1234-1234-123456789abc"
                    }
                }
            }
        },
        401: {
            "description": "トークンは無効",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "無効なアクセストークンです"
                    }
                }
            }
        }
    }
)
async def verify_token(
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    トークンの有効性を検証する

    Args:
        current_user: JWT検証により取得された現在のユーザー

    Returns:
        dict: 検証結果とユーザーID
    """
    return {
        "valid": True,
        "user_id": current_user.user_id
    }
