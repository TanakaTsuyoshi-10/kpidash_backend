"""
申請種別マスタ・Slack投稿先バインディング管理APIエンドポイント

種別の閲覧は approvals 権限があれば可（起票フォームで必要）。
作成・更新・削除、Slack投稿先の管理は admin のみ。
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from supabase import Client
from typing import List, Optional

from app.api.deps import (
    get_supabase_admin,
    get_user_app_role,
    require_page_permission,
    get_current_user,
)
from app.schemas.approval import (
    RequestType,
    RequestTypeCreate,
    RequestTypeUpdate,
    SlackChannelBinding,
    SlackChannelBindingCreate,
)
from app.services import approval_service

router = APIRouter()

require_approvals = require_page_permission("approvals")


async def require_admin(current_user=Depends(get_current_user)):
    """admin ロールのみ許可"""
    if get_user_app_role(current_user.user_id) != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="この操作には管理者権限が必要です",
        )
    return current_user


# =============================================================================
# 申請種別マスタ
# =============================================================================

@router.get("/", response_model=List[RequestType], summary="申請種別一覧")
async def list_types(
    include_inactive: bool = Query(False),
    current_user=Depends(require_approvals),
    supabase: Client = Depends(get_supabase_admin),
):
    return await approval_service.list_request_types(supabase, include_inactive)


@router.post(
    "/",
    response_model=RequestType,
    status_code=status.HTTP_201_CREATED,
    summary="申請種別作成（管理者のみ）",
)
async def create_type(
    data: RequestTypeCreate,
    current_user=Depends(require_admin),
    supabase: Client = Depends(get_supabase_admin),
):
    result = await approval_service.create_request_type(supabase, data)
    if not result:
        raise HTTPException(status_code=500, detail="申請種別の作成に失敗しました")
    return result


@router.put("/{code}", response_model=RequestType, summary="申請種別更新（管理者のみ）")
async def update_type(
    code: str,
    data: RequestTypeUpdate,
    current_user=Depends(require_admin),
    supabase: Client = Depends(get_supabase_admin),
):
    result = await approval_service.update_request_type(supabase, code, data)
    if not result:
        raise HTTPException(status_code=404, detail="申請種別が見つかりません")
    return result


# =============================================================================
# Slack 投稿先バインディング
# =============================================================================

@router.get(
    "/channel-bindings",
    response_model=List[SlackChannelBinding],
    summary="Slack投稿先一覧",
)
async def list_bindings(
    request_type: Optional[str] = Query(None),
    current_user=Depends(require_approvals),
    supabase: Client = Depends(get_supabase_admin),
):
    return await approval_service.list_channel_bindings(supabase, request_type)


@router.post(
    "/channel-bindings",
    response_model=SlackChannelBinding,
    status_code=status.HTTP_201_CREATED,
    summary="Slack投稿先追加（管理者のみ）",
)
async def create_binding(
    data: SlackChannelBindingCreate,
    current_user=Depends(require_admin),
    supabase: Client = Depends(get_supabase_admin),
):
    result = await approval_service.create_channel_binding(supabase, data)
    if not result:
        raise HTTPException(status_code=500, detail="Slack投稿先の登録に失敗しました")
    return result


@router.delete(
    "/channel-bindings/{binding_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Slack投稿先削除（管理者のみ）",
)
async def delete_binding(
    binding_id: str,
    current_user=Depends(require_admin),
    supabase: Client = Depends(get_supabase_admin),
):
    ok = await approval_service.delete_channel_binding(supabase, binding_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Slack投稿先が見つかりません")
