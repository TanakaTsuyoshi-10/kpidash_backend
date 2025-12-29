"""
クレーム管理APIエンドポイント

クレーム管理機能のAPIエンドポイントを定義する。
"""
from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from supabase import Client

from app.api.deps import get_current_user, get_supabase_client, get_supabase_admin
from app.schemas.complaint import (
    ComplaintCreate,
    ComplaintUpdate,
    Complaint,
    ComplaintListResponse,
    ComplaintMonthlySummary,
    ComplaintDashboardSummary,
    ComplaintMasterDataResponse,
    DepartmentTypeEnum,
    ComplaintTypeEnum,
    ComplaintStatusEnum,
)
from app.services import complaint_service

router = APIRouter()


# =============================================================================
# マスタデータ取得
# =============================================================================

@router.get(
    "/master",
    response_model=ComplaintMasterDataResponse,
    summary="マスタデータ取得",
    description="クレーム種類、発生部署種類、顧客種類のマスタデータを取得する。",
)
async def get_master_data(
    current_user = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
):
    """マスタデータを取得する。"""
    return await complaint_service.get_master_data(supabase)


# =============================================================================
# クレームCRUD操作
# =============================================================================

@router.post(
    "/",
    response_model=Complaint,
    status_code=status.HTTP_201_CREATED,
    summary="クレーム新規登録",
    description="新規クレームを登録する。",
)
async def create_complaint(
    complaint_data: ComplaintCreate,
    current_user = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
):
    """クレームを新規登録する。"""
    user_id = current_user.user_id
    user_email = current_user.email

    result = await complaint_service.create_complaint(
        supabase=supabase,
        data=complaint_data,
        user_id=user_id,
        user_email=user_email,
    )

    if not result:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="クレームの登録に失敗しました",
        )

    return result


@router.get(
    "/",
    response_model=ComplaintListResponse,
    summary="クレーム一覧取得",
    description="クレーム一覧を取得する。フィルタリングとページネーションに対応。",
)
async def get_complaints(
    current_user = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
    page: int = Query(1, ge=1, description="ページ番号"),
    page_size: int = Query(20, ge=1, le=100, description="1ページあたりの件数"),
    start_date: Optional[date] = Query(None, description="発生日（開始）"),
    end_date: Optional[date] = Query(None, description="発生日（終了）"),
    department_type: Optional[DepartmentTypeEnum] = Query(None, description="発生部署種類"),
    segment_id: Optional[str] = Query(None, description="店舗ID"),
    complaint_type: Optional[ComplaintTypeEnum] = Query(None, description="クレーム種類"),
    status_filter: Optional[ComplaintStatusEnum] = Query(None, alias="status", description="対応状況"),
    search: Optional[str] = Query(None, description="検索キーワード（内容、顧客名）"),
):
    """クレーム一覧を取得する。"""
    return await complaint_service.get_complaints(
        supabase=supabase,
        page=page,
        page_size=page_size,
        status=status_filter.value if status_filter else None,
        department_type=department_type.value if department_type else None,
        complaint_type=complaint_type.value if complaint_type else None,
        start_date=start_date,
        end_date=end_date,
        search_query=search,
    )


@router.get(
    "/summary/monthly",
    response_model=ComplaintMonthlySummary,
    summary="月別サマリー取得",
    description="指定月のクレームサマリーを取得する。",
)
async def get_monthly_summary(
    month: date = Query(..., description="対象月（YYYY-MM-01形式）"),
    current_user = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
):
    """月別サマリーを取得する。"""
    return await complaint_service.get_monthly_summary(supabase, month)


@router.get(
    "/summary/dashboard",
    response_model=ComplaintDashboardSummary,
    summary="ダッシュボード用サマリー取得",
    description="ダッシュボード表示用のクレームサマリーを取得する。",
)
async def get_dashboard_summary(
    month: date = Query(..., description="対象月（YYYY-MM-01形式）"),
    current_user = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
):
    """ダッシュボード用サマリーを取得する。"""
    return await complaint_service.get_dashboard_summary(supabase, month)


@router.get(
    "/{complaint_id}",
    response_model=Complaint,
    summary="クレーム詳細取得",
    description="指定されたクレームの詳細を取得する。",
)
async def get_complaint(
    complaint_id: UUID,
    current_user = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
):
    """クレーム詳細を取得する。"""
    result = await complaint_service.get_complaint_by_id(supabase, str(complaint_id))

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="クレームが見つかりません",
        )

    return result


@router.put(
    "/{complaint_id}",
    response_model=Complaint,
    summary="クレーム更新",
    description="指定されたクレームを更新する。",
)
async def update_complaint(
    complaint_id: UUID,
    complaint_data: ComplaintUpdate,
    current_user = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
):
    """クレームを更新する。"""
    result = await complaint_service.update_complaint(
        supabase=supabase,
        complaint_id=str(complaint_id),
        data=complaint_data,
    )

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="クレームが見つかりません",
        )

    return result


@router.delete(
    "/{complaint_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="クレーム削除",
    description="指定されたクレームを削除する。",
)
async def delete_complaint(
    complaint_id: UUID,
    current_user = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
):
    """クレームを削除する。"""
    success = await complaint_service.delete_complaint(supabase, str(complaint_id))

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="クレームが見つかりません",
        )
