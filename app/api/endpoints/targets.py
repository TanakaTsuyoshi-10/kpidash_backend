"""
目標設定APIエンドポイント

部門別目標設定のAPIエンドポイントを定義する。
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from supabase import Client

from app.api.deps import get_current_user, get_supabase_admin
from app.schemas.target import (
    StoreTargetMatrix,
    StoreTargetBulkInput,
    FinancialTargetResponse,
    FinancialTargetInput,
    EcommerceTargetResponse,
    EcommerceTargetInput,
    TargetOverview,
    TargetSettingResult,
)
from app.services import target_service

router = APIRouter()


# =============================================================================
# 目標概要
# =============================================================================

@router.get(
    "/overview",
    response_model=TargetOverview,
    summary="目標設定概要取得",
    description="部門別の目標設定状況概要を取得する。",
)
async def get_target_overview(
    month: date = Query(..., description="対象月（YYYY-MM-01形式）"),
    current_user = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
):
    """目標設定概要を取得する。"""
    try:
        return await target_service.get_target_overview(supabase, month)
    except Exception as e:
        import traceback
        print(f"ERROR in get_target_overview: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# 店舗部門 目標設定
# =============================================================================

@router.get(
    "/store",
    response_model=StoreTargetMatrix,
    summary="店舗目標マトリックス取得",
    description="店舗×KPIの目標マトリックスを取得する。前年実績も含む。",
)
async def get_store_targets(
    month: date = Query(..., description="対象月（YYYY-MM-01形式）"),
    current_user = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
):
    """店舗目標マトリックスを取得する。"""
    try:
        # 店舗部門IDを取得
        dept_response = supabase.table("departments").select("id").eq("slug", "store").execute()
        if not dept_response.data:
            raise HTTPException(status_code=404, detail="店舗部門が見つかりません")

        department_id = dept_response.data[0]["id"]
        return await target_service.get_target_matrix(supabase, department_id, month)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/store",
    response_model=TargetSettingResult,
    summary="店舗目標一括保存",
    description="店舗別KPI目標を一括保存する。",
)
async def save_store_targets(
    data: StoreTargetBulkInput,
    current_user = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
):
    """店舗目標を一括保存する。"""
    try:
        targets = [
            {
                "segment_id": t.segment_id,
                "kpi_id": t.kpi_id,
                "month": data.month,
                "value": float(t.value),
            }
            for t in data.targets
        ]
        return await target_service.bulk_upsert_targets(supabase, targets)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# 財務部門 目標設定
# =============================================================================

@router.get(
    "/financial",
    response_model=FinancialTargetResponse,
    summary="財務目標取得",
    description="財務目標（サマリー、売上原価明細、販管費明細）を取得する。前年実績・前年比も含む。",
)
async def get_financial_targets(
    month: date = Query(..., description="対象月（YYYY-MM-01形式）"),
    current_user = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
):
    """財務目標を取得する。"""
    try:
        return await target_service.get_financial_targets(supabase, month)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/financial",
    response_model=TargetSettingResult,
    summary="財務目標保存",
    description="財務目標を保存する。",
)
async def save_financial_targets(
    data: FinancialTargetInput,
    current_user = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
):
    """財務目標を保存する。"""
    try:
        user_id = current_user.user_id
        user_email = current_user.email
        return await target_service.save_financial_targets(
            supabase, data, user_id, user_email
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# 通販部門 目標設定
# =============================================================================

@router.get(
    "/ecommerce",
    response_model=EcommerceTargetResponse,
    summary="通販目標取得",
    description="通販目標（チャネル別売上、顧客統計）を取得する。前年実績・前年比も含む。",
)
async def get_ecommerce_targets(
    month: date = Query(..., description="対象月（YYYY-MM-01形式）"),
    current_user = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
):
    """通販目標を取得する。"""
    try:
        return await target_service.get_ecommerce_targets(supabase, month)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/ecommerce",
    response_model=TargetSettingResult,
    summary="通販目標保存",
    description="通販目標を保存する。",
)
async def save_ecommerce_targets(
    data: EcommerceTargetInput,
    current_user = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
):
    """通販目標を保存する。"""
    try:
        user_id = current_user.user_id
        user_email = current_user.email
        return await target_service.save_ecommerce_targets(
            supabase, data, user_id, user_email
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
