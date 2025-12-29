"""
財務分析APIエンドポイント

財務サマリー、売上原価・販管費の明細展開、店舗別収支のAPIを提供する。
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from supabase import Client

from app.api.deps import get_current_user, get_supabase_admin
from app.schemas.kpi import User
from app.schemas.financial import (
    FinancialAnalysisResponse,
    StorePL,
    StorePLListResponse,
)
from app.services.financial_service import (
    get_financial_analysis,
    get_store_pl_list,
    get_store_pl_by_segment_id,
)


router = APIRouter(prefix="/finance", tags=["財務分析"])


# =============================================================================
# 財務分析エンドポイント
# =============================================================================

@router.get(
    "/analysis",
    response_model=FinancialAnalysisResponse,
    summary="財務分析データ取得",
    description="""
    財務分析データを取得する。

    ## 機能
    - 財務サマリー（売上高、売上原価、販管費、営業利益など）
    - 売上原価の明細展開（仕入高、原材料仕入高、労務費、消耗品費など）
    - 販管費の明細展開（役員報酬、人件費、配送費、包装費など）
    - 前年データとの比較

    ## パラメータ
    - month: 対象月（YYYY-MM-01形式）
    - period_type: 期間タイプ（monthly: 単月, cumulative: 累計）
    """,
)
async def financial_analysis(
    month: date = Query(..., description="対象月（YYYY-MM-01形式）"),
    period_type: str = Query(
        "monthly",
        description="期間タイプ（monthly/cumulative）",
        regex="^(monthly|cumulative)$"
    ),
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
) -> FinancialAnalysisResponse:
    """
    財務分析データを取得

    Args:
        month: 対象月
        period_type: 期間タイプ

    Returns:
        FinancialAnalysisResponse: 財務分析データ
    """
    try:
        return await get_financial_analysis(
            supabase=supabase,
            period=month,
            period_type=period_type,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"財務分析データの取得に失敗しました: {str(e)}",
        )


# =============================================================================
# 店舗別収支エンドポイント
# =============================================================================

@router.get(
    "/store-pl",
    response_model=StorePLListResponse,
    summary="店舗別収支一覧取得",
    description="""
    店舗別収支の一覧を取得する。

    ## 機能
    - 各店舗の売上高、売上原価、売上総利益、販管費、営業利益
    - 販管費の明細展開（人件費、地代家賃、賃借料、水道光熱費、その他）
    - 前年比較

    ## パラメータ
    - month: 対象月（YYYY-MM-01形式）
    - department_slug: 部門スラッグ（デフォルト: store）
    """,
)
async def store_pl_list(
    month: date = Query(..., description="対象月（YYYY-MM-01形式）"),
    department_slug: str = Query("store", description="部門スラッグ"),
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
) -> StorePLListResponse:
    """
    店舗別収支一覧を取得

    Args:
        month: 対象月
        department_slug: 部門スラッグ

    Returns:
        StorePLListResponse: 店舗別収支一覧
    """
    try:
        return await get_store_pl_list(
            supabase=supabase,
            period=month,
            department_slug=department_slug,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"店舗別収支の取得に失敗しました: {str(e)}",
        )


@router.get(
    "/store-pl/{segment_id}",
    response_model=StorePL,
    summary="店舗収支取得",
    description="""
    特定店舗の収支を取得する。

    店舗分析の詳細ページで使用。

    ## 機能
    - 売上高、売上原価、売上総利益、販管費、営業利益
    - 販管費の明細展開
    - 前年比較
    """,
)
async def store_pl_detail(
    segment_id: str,
    month: date = Query(..., description="対象月（YYYY-MM-01形式）"),
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
) -> StorePL:
    """
    特定店舗の収支を取得

    Args:
        segment_id: 店舗ID
        month: 対象月

    Returns:
        StorePL: 店舗収支
    """
    try:
        result = await get_store_pl_by_segment_id(
            supabase=supabase,
            segment_id=segment_id,
            period=month,
        )
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="店舗が見つかりません",
            )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"店舗収支の取得に失敗しました: {str(e)}",
        )
