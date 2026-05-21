"""
取締役会資料・議事録APIエンドポイント

取締役会の資料・議事録機能のAPIエンドポイントを定義する。
取締役会資料は機密性が高いため、管理者・役員のみアクセス可能。
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from supabase import Client

from app.api.deps import require_page_permission, get_supabase_admin
from app.schemas.board import (
    BoardMeetingCreate,
    BoardMeetingUpdate,
    BoardMeeting,
    BoardMeetingListResponse,
)
from app.services import board_service

router = APIRouter()

# 取締役会の閲覧権限（権限管理の "board" キーで制御。管理者は常に許可）
require_board = require_page_permission("board")


# =============================================================================
# 取締役会CRUD操作
# =============================================================================

@router.get(
    "/",
    response_model=BoardMeetingListResponse,
    summary="取締役会一覧取得",
    description="取締役会の一覧を取得する（管理者・役員のみ）。",
)
async def list_board_meetings(
    current_user=Depends(require_board),
    supabase: Client = Depends(get_supabase_admin),
):
    """取締役会一覧を取得する。"""
    return await board_service.list_meetings(supabase)


@router.post(
    "/",
    response_model=BoardMeeting,
    status_code=status.HTTP_201_CREATED,
    summary="取締役会新規登録",
    description="新規取締役会を登録する（管理者・役員のみ）。",
)
async def create_board_meeting(
    meeting_data: BoardMeetingCreate,
    current_user=Depends(require_board),
    supabase: Client = Depends(get_supabase_admin),
):
    """取締役会を新規登録する。"""
    result = await board_service.create_meeting(
        supabase=supabase,
        data=meeting_data,
        user_id=current_user.user_id,
    )

    if not result:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="取締役会の登録に失敗しました",
        )

    return result


@router.get(
    "/{meeting_id}",
    response_model=BoardMeeting,
    summary="取締役会詳細取得",
    description="指定された取締役会の詳細を取得する（管理者・役員のみ）。",
)
async def get_board_meeting(
    meeting_id: UUID,
    current_user=Depends(require_board),
    supabase: Client = Depends(get_supabase_admin),
):
    """取締役会詳細を取得する。"""
    result = await board_service.get_meeting(supabase, str(meeting_id))

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="取締役会が見つかりません",
        )

    return result


@router.put(
    "/{meeting_id}",
    response_model=BoardMeeting,
    summary="取締役会更新",
    description="指定された取締役会を更新する（管理者・役員のみ）。",
)
async def update_board_meeting(
    meeting_id: UUID,
    meeting_data: BoardMeetingUpdate,
    current_user=Depends(require_board),
    supabase: Client = Depends(get_supabase_admin),
):
    """取締役会を更新する。"""
    result = await board_service.update_meeting(
        supabase=supabase,
        meeting_id=str(meeting_id),
        data=meeting_data,
    )

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="取締役会が見つかりません",
        )

    return result


@router.delete(
    "/{meeting_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="取締役会削除",
    description="指定された取締役会を削除する（管理者・役員のみ）。",
)
async def delete_board_meeting(
    meeting_id: UUID,
    current_user=Depends(require_board),
    supabase: Client = Depends(get_supabase_admin),
):
    """取締役会を削除する。"""
    success = await board_service.delete_meeting(supabase, str(meeting_id))

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="取締役会が見つかりません",
        )
