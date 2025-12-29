"""
利用者管理サービス

利用者管理のビジネスロジックを提供する。
Supabase Authとの連携を含む。
"""
from typing import Optional, List
from supabase import Client

from app.schemas.user import (
    UserProfileCreate,
    UserProfileUpdate,
    UserProfileResponse,
    UserListResponse,
    UserRoleInfo,
    UserRoleListResponse,
    UserOperationResult,
    CurrentUserResponse,
)


# =============================================================================
# 権限チェック
# =============================================================================

async def is_admin(supabase: Client, user_id: str) -> bool:
    """
    ユーザーが管理者かどうかを確認する

    Args:
        supabase: Supabaseクライアント
        user_id: ユーザーID

    Returns:
        bool: 管理者の場合True
    """
    try:
        response = supabase.table("user_profiles").select("role").eq(
            "id", user_id
        ).execute()

        if response.data and len(response.data) > 0:
            return response.data[0].get("role") == "admin"
        return False
    except Exception:
        return False


# =============================================================================
# 現在のユーザー情報取得
# =============================================================================

async def get_current_user_profile(
    supabase: Client,
    user_id: str,
) -> Optional[CurrentUserResponse]:
    """
    現在のユーザープロファイルを取得する

    Args:
        supabase: Supabaseクライアント
        user_id: ユーザーID

    Returns:
        CurrentUserResponse: ユーザー情報
    """
    try:
        response = supabase.table("user_profiles").select(
            "id, email, display_name, role"
        ).eq("id", user_id).execute()

        if response.data and len(response.data) > 0:
            user = response.data[0]
            return CurrentUserResponse(
                id=user["id"],
                email=user["email"],
                display_name=user.get("display_name"),
                role=user["role"],
                is_admin=user["role"] == "admin",
            )
        return None
    except Exception:
        return None


# =============================================================================
# ユーザー一覧取得
# =============================================================================

async def get_user_list(supabase: Client) -> UserListResponse:
    """
    ユーザー一覧を取得する（管理者用）

    Args:
        supabase: Supabaseクライアント

    Returns:
        UserListResponse: ユーザー一覧
    """
    try:
        # user_profilesと権限名を結合して取得
        response = supabase.table("user_profiles").select(
            "id, email, display_name, role, is_active, created_at, updated_at"
        ).order("created_at", desc=True).execute()

        # 権限名を取得
        roles_response = supabase.table("user_roles").select("code, name").execute()
        role_map = {r["code"]: r["name"] for r in roles_response.data} if roles_response.data else {}

        users = []
        for user in response.data or []:
            users.append(UserProfileResponse(
                id=user["id"],
                email=user["email"],
                display_name=user.get("display_name"),
                role=user["role"],
                role_name=role_map.get(user["role"], user["role"]),
                is_active=user.get("is_active", True),
                created_at=user.get("created_at"),
                updated_at=user.get("updated_at"),
                last_sign_in_at=None,  # auth.usersからは取得しない（RLS制限）
            ))

        return UserListResponse(users=users, total=len(users))
    except Exception as e:
        raise Exception(f"ユーザー一覧の取得に失敗しました: {str(e)}")


# =============================================================================
# ユーザー詳細取得
# =============================================================================

async def get_user_profile(
    supabase: Client,
    user_id: str,
) -> Optional[UserProfileResponse]:
    """
    ユーザープロファイルを取得する

    Args:
        supabase: Supabaseクライアント
        user_id: ユーザーID

    Returns:
        UserProfileResponse: ユーザープロファイル
    """
    try:
        response = supabase.table("user_profiles").select(
            "id, email, display_name, role, is_active, created_at, updated_at"
        ).eq("id", user_id).execute()

        if not response.data:
            return None

        user = response.data[0]

        # 権限名を取得
        role_response = supabase.table("user_roles").select("name").eq(
            "code", user["role"]
        ).execute()
        role_name = role_response.data[0]["name"] if role_response.data else user["role"]

        return UserProfileResponse(
            id=user["id"],
            email=user["email"],
            display_name=user.get("display_name"),
            role=user["role"],
            role_name=role_name,
            is_active=user.get("is_active", True),
            created_at=user.get("created_at"),
            updated_at=user.get("updated_at"),
            last_sign_in_at=None,
        )
    except Exception as e:
        raise Exception(f"ユーザー情報の取得に失敗しました: {str(e)}")


# =============================================================================
# ユーザー新規登録
# =============================================================================

async def create_user(
    supabase: Client,
    data: UserProfileCreate,
    admin_user_id: str,
) -> UserOperationResult:
    """
    新規ユーザーを登録する（管理者用）

    Supabase Authにユーザーを作成し、プロファイルテーブルにも登録する。

    Args:
        supabase: Supabaseクライアント
        data: ユーザー登録データ
        admin_user_id: 操作を行う管理者のID

    Returns:
        UserOperationResult: 操作結果
    """
    try:
        # Supabase Admin APIでユーザーを作成
        # 注意: これにはservice_roleキーが必要
        auth_response = supabase.auth.admin.create_user({
            "email": data.email,
            "password": data.password,
            "email_confirm": True,  # メール確認をスキップ
            "user_metadata": {
                "display_name": data.display_name,
                "role": data.role.value,
            },
        })

        if not auth_response.user:
            return UserOperationResult(
                success=False,
                message="ユーザーの作成に失敗しました",
                user_id=None,
            )

        user_id = auth_response.user.id

        # プロファイルテーブルに登録（トリガーで自動作成されるが、念のため更新）
        supabase.table("user_profiles").upsert({
            "id": user_id,
            "email": data.email,
            "display_name": data.display_name or data.email.split("@")[0],
            "role": data.role.value,
            "is_active": True,
            "created_by": admin_user_id,
            "updated_by": admin_user_id,
        }).execute()

        return UserOperationResult(
            success=True,
            message="ユーザーを登録しました",
            user_id=user_id,
        )

    except Exception as e:
        error_message = str(e)
        if "already registered" in error_message.lower() or "duplicate" in error_message.lower():
            return UserOperationResult(
                success=False,
                message="このメールアドレスは既に登録されています",
                user_id=None,
            )
        return UserOperationResult(
            success=False,
            message=f"ユーザー登録に失敗しました: {error_message}",
            user_id=None,
        )


# =============================================================================
# ユーザー情報更新
# =============================================================================

async def update_user(
    supabase: Client,
    user_id: str,
    data: UserProfileUpdate,
    admin_user_id: str,
) -> UserOperationResult:
    """
    ユーザー情報を更新する（管理者用）

    Args:
        supabase: Supabaseクライアント
        user_id: 更新対象ユーザーID
        data: 更新データ
        admin_user_id: 操作を行う管理者のID

    Returns:
        UserOperationResult: 操作結果
    """
    try:
        # 更新データを構築
        update_data = {"updated_by": admin_user_id}

        if data.display_name is not None:
            update_data["display_name"] = data.display_name

        if data.role is not None:
            update_data["role"] = data.role.value

        if data.is_active is not None:
            update_data["is_active"] = data.is_active

        # プロファイルを更新
        response = supabase.table("user_profiles").update(update_data).eq(
            "id", user_id
        ).execute()

        if not response.data:
            return UserOperationResult(
                success=False,
                message="ユーザーが見つかりません",
                user_id=None,
            )

        return UserOperationResult(
            success=True,
            message="ユーザー情報を更新しました",
            user_id=user_id,
        )

    except Exception as e:
        return UserOperationResult(
            success=False,
            message=f"ユーザー情報の更新に失敗しました: {str(e)}",
            user_id=None,
        )


# =============================================================================
# 自分のプロファイル更新
# =============================================================================

async def update_own_profile(
    supabase: Client,
    user_id: str,
    display_name: str,
) -> UserOperationResult:
    """
    自分の表示名を更新する

    Args:
        supabase: Supabaseクライアント
        user_id: ユーザーID
        display_name: 新しい表示名

    Returns:
        UserOperationResult: 操作結果
    """
    try:
        response = supabase.table("user_profiles").update({
            "display_name": display_name,
        }).eq("id", user_id).execute()

        if not response.data:
            return UserOperationResult(
                success=False,
                message="プロファイルが見つかりません",
                user_id=None,
            )

        return UserOperationResult(
            success=True,
            message="プロファイルを更新しました",
            user_id=user_id,
        )

    except Exception as e:
        return UserOperationResult(
            success=False,
            message=f"プロファイルの更新に失敗しました: {str(e)}",
            user_id=None,
        )


# =============================================================================
# 権限一覧取得
# =============================================================================

async def get_roles(supabase: Client) -> UserRoleListResponse:
    """
    権限一覧を取得する

    Args:
        supabase: Supabaseクライアント

    Returns:
        UserRoleListResponse: 権限一覧
    """
    try:
        response = supabase.table("user_roles").select(
            "code, name, description"
        ).order("display_order").execute()

        roles = [
            UserRoleInfo(
                code=r["code"],
                name=r["name"],
                description=r.get("description"),
            )
            for r in response.data or []
        ]

        return UserRoleListResponse(roles=roles)

    except Exception as e:
        raise Exception(f"権限一覧の取得に失敗しました: {str(e)}")


# =============================================================================
# ユーザー削除（無効化）
# =============================================================================

async def deactivate_user(
    supabase: Client,
    user_id: str,
    admin_user_id: str,
) -> UserOperationResult:
    """
    ユーザーを無効化する（管理者用）

    完全削除ではなく、is_activeをfalseにする。

    Args:
        supabase: Supabaseクライアント
        user_id: 無効化対象ユーザーID
        admin_user_id: 操作を行う管理者のID

    Returns:
        UserOperationResult: 操作結果
    """
    try:
        # 自分自身を無効化しようとした場合はエラー
        if user_id == admin_user_id:
            return UserOperationResult(
                success=False,
                message="自分自身を無効化することはできません",
                user_id=None,
            )

        response = supabase.table("user_profiles").update({
            "is_active": False,
            "updated_by": admin_user_id,
        }).eq("id", user_id).execute()

        if not response.data:
            return UserOperationResult(
                success=False,
                message="ユーザーが見つかりません",
                user_id=None,
            )

        return UserOperationResult(
            success=True,
            message="ユーザーを無効化しました",
            user_id=user_id,
        )

    except Exception as e:
        return UserOperationResult(
            success=False,
            message=f"ユーザーの無効化に失敗しました: {str(e)}",
            user_id=None,
        )
