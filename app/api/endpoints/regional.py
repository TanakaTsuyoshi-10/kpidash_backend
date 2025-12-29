"""
地区別分析APIエンドポイントモジュール

地区別売上集計・目標管理APIを提供する。
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from supabase import Client

from app.api.deps import get_current_user, get_supabase_admin
from app.schemas.kpi import User
from app.schemas.regional import (
    Region,
    RegionListResponse,
    StoreRegionMappingListResponse,
    UpdateStoreRegionRequest,
    BulkUpdateStoreRegionRequest,
    RegionalSummaryResponse,
    RegionalTargetListResponse,
)
from app.services.regional_service import (
    get_regions,
    get_store_region_mappings,
    update_store_region_mapping,
    bulk_update_store_region_mappings,
    initialize_store_region_mappings,
    get_regional_summary,
    get_regional_targets,
)


router = APIRouter(prefix="/regional", tags=["regional"])


# =============================================================================
# 地区マスタエンドポイント
# =============================================================================

@router.get(
    "/regions",
    response_model=RegionListResponse,
    summary="地区一覧取得",
    description="地区マスタの一覧を取得する。",
)
async def list_regions(
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
) -> RegionListResponse:
    """
    地区一覧を取得

    Returns:
        RegionListResponse: 地区一覧
    """
    try:
        regions = await get_regions(supabase)
        return RegionListResponse(
            regions=[Region(**r) for r in regions]
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"地区一覧の取得に失敗しました: {str(e)}"
        )


# =============================================================================
# 店舗-地区マッピングエンドポイント
# =============================================================================

@router.get(
    "/store-mappings",
    response_model=StoreRegionMappingListResponse,
    summary="店舗-地区マッピング一覧取得",
    description="店舗と地区のマッピング一覧を取得する。",
)
async def list_store_region_mappings(
    department_slug: str = Query("store", description="部門スラッグ"),
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
) -> StoreRegionMappingListResponse:
    """
    店舗-地区マッピング一覧を取得

    Args:
        department_slug: 部門スラッグ

    Returns:
        StoreRegionMappingListResponse: マッピング一覧
    """
    # 部門IDを取得
    dept_response = supabase.table("departments").select(
        "id"
    ).eq("slug", department_slug).execute()

    if not dept_response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"部門が見つかりません: {department_slug}"
        )

    department_id = dept_response.data[0]["id"]

    try:
        mappings = await get_store_region_mappings(supabase, department_id)
        return StoreRegionMappingListResponse(mappings=mappings)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"マッピング一覧の取得に失敗しました: {str(e)}"
        )


@router.post(
    "/store-mappings",
    summary="店舗-地区マッピング更新",
    description="店舗と地区のマッピングを更新する。",
)
async def update_store_mapping(
    request: UpdateStoreRegionRequest,
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
):
    """
    店舗-地区マッピングを更新

    Args:
        request: 更新リクエスト

    Returns:
        更新結果
    """
    try:
        result = await update_store_region_mapping(
            supabase,
            request.segment_id,
            request.region_id
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"マッピングの更新に失敗しました: {str(e)}"
        )


@router.post(
    "/store-mappings/bulk",
    summary="店舗-地区マッピング一括更新",
    description="店舗と地区のマッピングを一括更新する。",
)
async def bulk_update_store_mappings(
    request: BulkUpdateStoreRegionRequest,
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
):
    """
    店舗-地区マッピングを一括更新

    Args:
        request: 一括更新リクエスト

    Returns:
        更新結果
    """
    try:
        mappings = [
            {"segment_id": m.segment_id, "region_id": m.region_id}
            for m in request.mappings
        ]
        result = await bulk_update_store_region_mappings(supabase, mappings)
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"マッピングの一括更新に失敗しました: {str(e)}"
        )


@router.post(
    "/store-mappings/initialize",
    summary="店舗-地区マッピング初期化",
    description="デフォルトの店舗-地区マッピングを初期化する。",
)
async def initialize_store_mappings(
    department_slug: str = Query("store", description="部門スラッグ"),
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
):
    """
    デフォルトの店舗-地区マッピングを初期化

    Args:
        department_slug: 部門スラッグ

    Returns:
        初期化結果
    """
    # 部門IDを取得
    dept_response = supabase.table("departments").select(
        "id"
    ).eq("slug", department_slug).execute()

    if not dept_response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"部門が見つかりません: {department_slug}"
        )

    department_id = dept_response.data[0]["id"]

    try:
        result = await initialize_store_region_mappings(supabase, department_id)
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"マッピングの初期化に失敗しました: {str(e)}"
        )


# =============================================================================
# 地区別集計エンドポイント
# =============================================================================

@router.get(
    "/summary",
    response_model=RegionalSummaryResponse,
    summary="地区別集計取得",
    description="""
    地区別の売上集計を取得する。

    ## 返却データ
    - 地区別の売上高・客数・客単価
    - 前年比較
    - 目標との差異
    - 地区内店舗別データ

    ## パラメータ
    - month: 対象月（YYYY-MM-DD形式）
    - period_type: 期間タイプ（monthly: 単月, cumulative: 累計）
    """,
)
async def regional_summary(
    month: date = Query(..., description="対象月（YYYY-MM-DD形式）"),
    department_slug: str = Query("store", description="部門スラッグ"),
    period_type: str = Query("monthly", description="期間タイプ（monthly/cumulative）"),
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
) -> RegionalSummaryResponse:
    """
    地区別集計を取得

    Args:
        month: 対象月
        department_slug: 部門スラッグ
        period_type: 期間タイプ

    Returns:
        RegionalSummaryResponse: 地区別集計データ
    """
    if period_type not in ["monthly", "cumulative"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="period_typeは'monthly'または'cumulative'を指定してください"
        )

    # 部門IDを取得
    dept_response = supabase.table("departments").select(
        "id"
    ).eq("slug", department_slug).execute()

    if not dept_response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"部門が見つかりません: {department_slug}"
        )

    department_id = dept_response.data[0]["id"]

    try:
        result = await get_regional_summary(
            supabase,
            department_id,
            month,
            period_type
        )
        return RegionalSummaryResponse(**result)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"地区別集計の取得に失敗しました: {str(e)}"
        )


# =============================================================================
# 地区別目標エンドポイント
# =============================================================================

@router.get(
    "/targets",
    response_model=RegionalTargetListResponse,
    summary="地区別目標取得",
    description="地区別の目標値を取得する。",
)
async def list_regional_targets(
    month: date = Query(..., description="対象月（YYYY-MM-DD形式）"),
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
) -> RegionalTargetListResponse:
    """
    地区別目標を取得

    Args:
        month: 対象月

    Returns:
        RegionalTargetListResponse: 目標一覧
    """
    try:
        targets = await get_regional_targets(supabase, month)
        return RegionalTargetListResponse(
            month=month.isoformat(),
            targets=targets
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"地区別目標の取得に失敗しました: {str(e)}"
        )


# 注意: 地区別目標は店舗目標から自動集計されるため、
# POST /targets および POST /targets/bulk エンドポイントは廃止されました。
# 目標設定は「目標設定」ページ (/targets) から店舗別に行ってください。
