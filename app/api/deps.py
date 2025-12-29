"""
依存注入モジュール

FastAPIの依存注入機能を使用して、認証・DB接続などの共通処理を提供する。
各エンドポイントで Depends() を使用してこれらの依存を注入できる。
"""
from typing import Generator, Optional

from fastapi import Depends, HTTPException, Header, status
from supabase import create_client, Client

from app.core.config import settings
from app.core.security import (
    extract_token_from_header,
    verify_token,
    TokenValidationError,
)
from app.schemas.kpi import User


def get_supabase_client() -> Client:
    """
    Supabaseクライアントを取得する（匿名キー使用）

    匿名キー（SUPABASE_ANON_KEY）を使用したクライアントを返す。
    RLS（Row Level Security）が適用される。

    Returns:
        Client: Supabaseクライアントインスタンス
    """
    return create_client(
        settings.SUPABASE_URL,
        settings.SUPABASE_ANON_KEY
    )


def get_supabase_admin() -> Client:
    """
    Supabase管理者クライアントを取得する（サービスロールキー使用）

    サービスロールキー（SUPABASE_SERVICE_ROLE_KEY）を使用したクライアントを返す。
    RLSをバイパスするため、管理者操作やバッチ処理に使用する。

    ⚠️ 注意: このクライアントはRLSをバイパスするため、
    適切な権限チェックを行った上で使用すること。

    Returns:
        Client: Supabase管理者クライアントインスタンス
    """
    return create_client(
        settings.SUPABASE_URL,
        settings.SUPABASE_SERVICE_ROLE_KEY
    )


async def get_current_user(
    authorization: Optional[str] = Header(None, description="Bearer token")
) -> User:
    """
    現在のログインユーザーを取得する

    AuthorizationヘッダーからJWTトークンを抽出し、検証して
    ユーザー情報を返す。認証必須のエンドポイントで使用する。

    Args:
        authorization: Authorizationヘッダーの値（"Bearer <token>"形式）

    Returns:
        User: 認証されたユーザー情報

    Raises:
        HTTPException(401): トークンが無効または期限切れの場合
    """
    try:
        # Authorizationヘッダーからトークンを抽出
        token = extract_token_from_header(authorization)

        # トークンを検証してユーザー情報を取得
        user_info = verify_token(token)

        # Userスキーマに変換して返す
        return User(**user_info)

    except TokenValidationError as e:
        # トークン検証エラーをHTTPExceptionに変換
        raise HTTPException(
            status_code=e.status_code,
            detail=e.message,
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user_optional(
    authorization: Optional[str] = Header(None, description="Bearer token")
) -> Optional[User]:
    """
    現在のログインユーザーを取得する（オプション）

    トークンがない場合はNoneを返す。
    トークンがあるが無効な場合はエラーを発生させる。

    認証がオプションのエンドポイントで使用する。

    Args:
        authorization: Authorizationヘッダーの値

    Returns:
        Optional[User]: 認証されたユーザー情報、またはNone
    """
    if not authorization:
        return None

    return await get_current_user(authorization)


async def verify_department_access(
    current_user: User = Depends(get_current_user),
    department_id: Optional[str] = None
) -> User:
    """
    部門アクセス権限を検証する

    ユーザーが指定された部門にアクセス可能かどうかを確認する。
    department_idが指定されていない場合、またはユーザーが
    全部門アクセス権を持っている場合は許可される。

    Args:
        current_user: 認証されたユーザー
        department_id: アクセス対象の部門ID

    Returns:
        User: 認証されたユーザー情報

    Raises:
        HTTPException(403): アクセス権限がない場合
    """
    # department_idが指定されていない場合は許可
    if not department_id:
        return current_user

    # ユーザーに部門IDが設定されていない場合は全部門アクセス可能
    # （管理者ユーザーの場合など）
    if not current_user.department_id:
        return current_user

    # ユーザーの部門と要求された部門が一致するか確認
    if current_user.department_id != department_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="この部門のデータにアクセスする権限がありません。"
        )

    return current_user


def get_db_client_for_user(
    current_user: User = Depends(get_current_user),
) -> Client:
    """
    ユーザー用のDBクライアントを取得する

    認証されたユーザーの権限に応じたDBクライアントを返す。
    通常ユーザーは匿名キーを使用し、RLSが適用される。

    Args:
        current_user: 認証されたユーザー

    Returns:
        Client: Supabaseクライアント
    """
    # 通常のユーザーは匿名キーでアクセス（RLS適用）
    return get_supabase_client()
