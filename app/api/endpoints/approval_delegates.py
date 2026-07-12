"""
代理承認設定APIエンドポイント

不在期間中の代理承認者を事前設定する。
全ユーザーが自分の分を管理でき、admin は全員分を管理できる。
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from supabase import Client

from app.api.deps import (
    get_current_user,
    get_supabase_admin,
    get_user_app_role,
)
from app.schemas.approval import ApprovalDelegate, ApprovalDelegateCreate
from app.services import approval_service

router = APIRouter()


@router.get("/", response_model=List[ApprovalDelegate], summary="代理設定一覧")
async def list_delegates(
    all_users: bool = Query(False, description="全ユーザー分を取得（admin のみ）"),
    current_user=Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
):
    is_admin = get_user_app_role(current_user.user_id) == "admin"
    if all_users and is_admin:
        return await approval_service.list_delegates(supabase, None)
    return await approval_service.list_delegates(supabase, current_user.user_id)


@router.post(
    "/",
    response_model=ApprovalDelegate,
    status_code=status.HTTP_201_CREATED,
    summary="代理設定追加",
)
async def create_delegate(
    data: ApprovalDelegateCreate,
    current_user=Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
):
    is_admin = get_user_app_role(current_user.user_id) == "admin"
    # 他ユーザー分の設定は admin のみ
    if data.user_id and data.user_id != current_user.user_id and not is_admin:
        raise HTTPException(
            status_code=403, detail="他のユーザーの代理設定は管理者のみ行えます"
        )
    result = await approval_service.create_delegate(supabase, data, current_user.user_id)
    if not result:
        raise HTTPException(status_code=500, detail="代理設定の作成に失敗しました")
    return result


@router.delete(
    "/{delegate_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="代理設定削除",
)
async def delete_delegate(
    delegate_id: str,
    current_user=Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
):
    is_admin = get_user_app_role(current_user.user_id) == "admin"
    ok = await approval_service.delete_delegate(
        supabase, delegate_id, current_user.user_id, is_admin
    )
    if not ok:
        raise HTTPException(
            status_code=404,
            detail="代理設定が見つからないか、削除権限がありません",
        )
