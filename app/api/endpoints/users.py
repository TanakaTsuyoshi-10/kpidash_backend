"""
利用者管理APIエンドポイント

利用者管理のAPIエンドポイントを定義する。
"""
from fastapi import APIRouter, Depends, HTTPException
from supabase import Client

from app.api.deps import get_current_user, get_supabase_client, get_supabase_admin
from app.schemas.user import (
    OrgDepartment,
    OrgDepartmentCreate,
    OrgDepartmentListResponse,
    OrgDepartmentUpdate,
    UserProfileCreate,
    UserProfileUpdate,
    UserProfileResponse,
    UserListResponse,
    UserRoleListResponse,
    UserOperationResult,
    CurrentUserResponse,
    UserPagePermissionsUpdate,
    UserPagePermissionsResponse,
)
from app.services import user_service

router = APIRouter()


# =============================================================================
# 管理者権限チェック依存関数
# =============================================================================

async def require_admin(
    current_user = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
) -> dict:
    """管理者権限を要求する依存関数"""
    user_id = current_user.user_id
    if not user_id:
        raise HTTPException(status_code=401, detail="認証が必要です")

    is_admin = await user_service.is_admin(supabase, user_id)
    if not is_admin:
        raise HTTPException(status_code=403, detail="管理者権限が必要です")

    return current_user


# =============================================================================
# 現在のユーザー情報
# =============================================================================

@router.get(
    "/me",
    response_model=CurrentUserResponse,
    summary="現在のユーザー情報取得",
    description="ログイン中のユーザー情報を取得する。",
)
async def get_current_user_info(
    current_user = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
):
    """現在のユーザー情報を取得する。"""
    user_id = current_user.user_id
    if not user_id:
        raise HTTPException(status_code=401, detail="認証が必要です")

    profile = await user_service.get_current_user_profile(supabase, user_id)
    if not profile:
        # プロファイルがない場合は基本情報を返す
        return CurrentUserResponse(
            id=user_id,
            email=current_user.email or "",
            display_name=None,
            role="user",
            is_admin=False,
        )

    return profile


@router.patch(
    "/me",
    response_model=UserOperationResult,
    summary="自分のプロファイル更新",
    description="自分の表示名を更新する。",
)
async def update_my_profile(
    display_name: str,
    current_user = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
):
    """自分のプロファイルを更新する。"""
    user_id = current_user.user_id
    if not user_id:
        raise HTTPException(status_code=401, detail="認証が必要です")

    return await user_service.update_own_profile(supabase, user_id, display_name)


# =============================================================================
# ユーザー一覧（管理者用）
# =============================================================================

@router.get(
    "",
    response_model=UserListResponse,
    summary="ユーザー一覧取得",
    description="登録されている全ユーザーの一覧を取得する。管理者権限が必要。",
)
async def get_users(
    current_user = Depends(require_admin),
    supabase: Client = Depends(get_supabase_admin),
):
    """ユーザー一覧を取得する（管理者用）。"""
    try:
        return await user_service.get_user_list(supabase)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# 部署マスタ（承認ワークフローの閲覧スコープ用）
# =============================================================================

@router.get(
    "/org-departments",
    response_model=OrgDepartmentListResponse,
    summary="部署一覧取得",
    description="部署マスタの一覧を取得する。承認者選択・利用者管理で使用。",
)
async def list_org_departments(
    include_inactive: bool = False,
    current_user = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
):
    """部署一覧を取得する（認証ユーザー）。"""
    try:
        return await user_service.list_org_departments(supabase, include_inactive)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/org-departments",
    response_model=OrgDepartment,
    summary="部署作成",
    description="部署を新規作成する。管理者権限が必要。",
)
async def create_org_department(
    data: OrgDepartmentCreate,
    current_user = Depends(require_admin),
    supabase: Client = Depends(get_supabase_admin),
):
    """部署を作成する（管理者用）。"""
    try:
        result = await user_service.create_org_department(
            supabase, data.name, data.display_order
        )
        if not result:
            raise HTTPException(status_code=500, detail="部署の作成に失敗しました")
        return result
    except HTTPException:
        raise
    except Exception as e:
        msg = str(e)
        if "duplicate" in msg.lower() or "unique" in msg.lower():
            raise HTTPException(status_code=400, detail="同名の部署が既に存在します")
        raise HTTPException(status_code=500, detail=msg)


@router.put(
    "/org-departments/{department_id}",
    response_model=OrgDepartment,
    summary="部署更新",
    description="部署名・表示順・有効フラグを更新する。管理者権限が必要。",
)
async def update_org_department(
    department_id: str,
    data: OrgDepartmentUpdate,
    current_user = Depends(require_admin),
    supabase: Client = Depends(get_supabase_admin),
):
    """部署を更新する（管理者用）。"""
    try:
        result = await user_service.update_org_department(
            supabase, department_id,
            name=data.name,
            display_order=data.display_order,
            is_active=data.is_active,
        )
        if not result:
            raise HTTPException(status_code=404, detail="部署が見つかりません")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# ページ権限取得・更新（管理者用）
# =============================================================================

@router.get(
    "/{user_id}/permissions",
    response_model=UserPagePermissionsResponse,
    summary="ユーザーページ権限取得",
    description="指定したユーザーのページ閲覧権限を取得する。管理者権限が必要。",
)
async def get_user_permissions(
    user_id: str,
    current_user = Depends(require_admin),
    supabase: Client = Depends(get_supabase_admin),
):
    """ユーザーのページ権限を取得する（管理者用）。"""
    try:
        allowed_pages = await user_service.get_user_page_permissions(supabase, user_id)
        return UserPagePermissionsResponse(user_id=user_id, allowed_pages=allowed_pages)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put(
    "/{user_id}/permissions",
    response_model=UserOperationResult,
    summary="ユーザーページ権限更新",
    description="指定したユーザーのページ閲覧権限を更新する。管理者権限が必要。",
)
async def update_user_permissions(
    user_id: str,
    data: UserPagePermissionsUpdate,
    current_user = Depends(require_admin),
    supabase: Client = Depends(get_supabase_admin),
):
    """ユーザーのページ権限を更新する（管理者用）。"""
    admin_user_id = current_user.user_id
    page_keys = [k.value for k in data.page_keys]

    result = await user_service.update_user_page_permissions(
        supabase, user_id, page_keys, admin_user_id
    )

    if not result.success:
        raise HTTPException(status_code=400, detail=result.message)

    return result


# =============================================================================
# ユーザー詳細取得（管理者用）
# =============================================================================

@router.get(
    "/{user_id}",
    response_model=UserProfileResponse,
    summary="ユーザー詳細取得",
    description="指定したユーザーの詳細情報を取得する。管理者権限が必要。",
)
async def get_user(
    user_id: str,
    current_user = Depends(require_admin),
    supabase: Client = Depends(get_supabase_admin),
):
    """ユーザー詳細を取得する（管理者用）。"""
    try:
        profile = await user_service.get_user_profile(supabase, user_id)
        if not profile:
            raise HTTPException(status_code=404, detail="ユーザーが見つかりません")
        return profile
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# ユーザー新規登録（管理者用）
# =============================================================================

@router.post(
    "",
    response_model=UserOperationResult,
    summary="ユーザー新規登録",
    description="新しいユーザーを登録する。管理者権限が必要。",
)
async def create_user(
    data: UserProfileCreate,
    current_user = Depends(require_admin),
    supabase: Client = Depends(get_supabase_admin),
):
    """ユーザーを新規登録する（管理者用）。"""
    admin_user_id = current_user.user_id

    result = await user_service.create_user(supabase, data, admin_user_id)

    if not result.success:
        raise HTTPException(status_code=400, detail=result.message)

    return result


# =============================================================================
# ユーザー情報更新（管理者用）
# =============================================================================

@router.patch(
    "/{user_id}",
    response_model=UserOperationResult,
    summary="ユーザー情報更新",
    description="ユーザー情報を更新する。管理者権限が必要。",
)
async def update_user(
    user_id: str,
    data: UserProfileUpdate,
    current_user = Depends(require_admin),
    supabase: Client = Depends(get_supabase_admin),
):
    """ユーザー情報を更新する（管理者用）。"""
    admin_user_id = current_user.user_id

    result = await user_service.update_user(supabase, user_id, data, admin_user_id)

    if not result.success:
        raise HTTPException(status_code=400, detail=result.message)

    return result


# =============================================================================
# ユーザー無効化（管理者用）
# =============================================================================

@router.delete(
    "/{user_id}",
    response_model=UserOperationResult,
    summary="ユーザー無効化",
    description="ユーザーを無効化する。管理者権限が必要。",
)
async def deactivate_user(
    user_id: str,
    current_user = Depends(require_admin),
    supabase: Client = Depends(get_supabase_admin),
):
    """ユーザーを無効化する（管理者用）。"""
    admin_user_id = current_user.user_id

    result = await user_service.deactivate_user(supabase, user_id, admin_user_id)

    if not result.success:
        raise HTTPException(status_code=400, detail=result.message)

    return result


# =============================================================================
# 権限一覧取得
# =============================================================================

@router.get(
    "/roles/list",
    response_model=UserRoleListResponse,
    summary="権限一覧取得",
    description="利用可能な権限の一覧を取得する。",
)
async def get_roles(
    current_user = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
):
    """権限一覧を取得する。"""
    try:
        return await user_service.get_roles(supabase)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
