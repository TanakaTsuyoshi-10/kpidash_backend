"""
商品関連APIエンドポイントモジュール

店舗別売上集計などの商品関連APIを提供する。
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from supabase import Client

from app.api.deps import get_current_user, get_supabase_admin
from app.schemas.kpi import (
    User,
    StoreSummaryResponse,
    AvailableMonthsResponse,
    StoreTrendAllResponse,
    StoreTrendSingleResponse,
)
from app.services.kpi_service import (
    get_store_summary,
    get_available_months,
    get_store_trend_all,
    get_store_trend_single,
)
from app.services.metrics import get_fiscal_year

router = APIRouter(prefix="/products", tags=["products"])


@router.get("/store-summary", response_model=StoreSummaryResponse)
async def store_summary(
    month: date = Query(..., description="対象月（YYYY-MM-DD形式）"),
    department_slug: str = Query("store", description="部門スラッグ"),
    period_type: str = Query("monthly", description="期間タイプ（monthly/cumulative）"),
    supabase: Client = Depends(get_supabase_admin),
    current_user: User = Depends(get_current_user),
) -> StoreSummaryResponse:
    """
    店舗別売上集計を取得

    全店舗の売上高・客数・客単価と前年比を一覧表示する。
    単月モードと累計モードに対応。

    Parameters:
    - month: 対象月（YYYY-MM-DD形式、月初日を指定）
    - department_slug: 部門スラッグ（デフォルト: "store"）
    - period_type: 期間タイプ（monthly: 単月, cumulative: 9月〜対象月の累計）

    Returns:
    - period: 対象期間
    - department_slug: 部門スラッグ
    - period_type: 期間タイプ
    - fiscal_year: 会計年度（累計時のみ）
    - stores: 店舗別データリスト
    - totals: 合計データ
    """
    # period_typeのバリデーション
    if period_type not in ["monthly", "cumulative"]:
        raise HTTPException(
            status_code=400,
            detail="period_typeは'monthly'または'cumulative'を指定してください"
        )

    # 部門IDを取得
    dept_response = supabase.table("departments").select(
        "id"
    ).eq("slug", department_slug).execute()

    if not dept_response.data:
        raise HTTPException(
            status_code=404,
            detail=f"部門が見つかりません: {department_slug}"
        )

    department_id = dept_response.data[0]["id"]

    try:
        result = await get_store_summary(
            supabase=supabase,
            department_id=department_id,
            target_month=month,
            period_type=period_type
        )
        return StoreSummaryResponse(**result)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"店舗別売上集計の取得に失敗しました: {str(e)}"
        )


@router.get("/available-months", response_model=AvailableMonthsResponse)
async def available_months(
    department_slug: str = Query("store", description="部門スラッグ"),
    supabase: Client = Depends(get_supabase_admin),
    current_user: User = Depends(get_current_user),
) -> AvailableMonthsResponse:
    """
    利用可能な月一覧を取得

    データベースに格納されている全ての月を降順で返す。
    月セレクターで選択可能な月の一覧を提供する。

    Parameters:
    - department_slug: 部門スラッグ（デフォルト: "store"）

    Returns:
    - months: 利用可能な月のリスト（YYYY-MM-DD形式、降順）
    """
    # 部門IDを取得
    dept_response = supabase.table("departments").select(
        "id"
    ).eq("slug", department_slug).execute()

    department_id = None
    if dept_response.data:
        department_id = dept_response.data[0]["id"]

    try:
        months = await get_available_months(
            supabase=supabase,
            department_id=department_id
        )
        return AvailableMonthsResponse(months=months)

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"利用可能な月一覧の取得に失敗しました: {str(e)}"
        )


@router.get("/store-trend-all", response_model=StoreTrendAllResponse)
async def store_trend_all(
    department_slug: str = Query("store", description="部門スラッグ"),
    fiscal_year: Optional[int] = Query(None, description="会計年度（9月起点）"),
    supabase: Client = Depends(get_supabase_admin),
    current_user: User = Depends(get_current_user),
) -> StoreTrendAllResponse:
    """
    全店舗の月別売上推移を取得

    全店舗の会計年度（9月〜翌8月）の売上推移を返す。

    Parameters:
    - department_slug: 部門スラッグ（デフォルト: "store"）
    - fiscal_year: 会計年度（デフォルト: 現在の会計年度）

    Returns:
    - fiscal_year: 会計年度
    - months: 月ラベル（YYYY-MM形式）
    - stores: 店舗別データリスト
    """
    # 部門IDを取得
    dept_response = supabase.table("departments").select(
        "id"
    ).eq("slug", department_slug).execute()

    if not dept_response.data:
        raise HTTPException(
            status_code=404,
            detail=f"部門が見つかりません: {department_slug}"
        )

    department_id = dept_response.data[0]["id"]

    # 会計年度が指定されていない場合は現在の会計年度を使用
    if fiscal_year is None:
        fiscal_year = get_fiscal_year(date.today())

    try:
        result = await get_store_trend_all(
            supabase=supabase,
            department_id=department_id,
            fiscal_year=fiscal_year
        )
        return StoreTrendAllResponse(**result)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"全店舗推移の取得に失敗しました: {str(e)}"
        )


@router.get("/store-trend/{segment_id}", response_model=StoreTrendSingleResponse)
async def store_trend_single(
    segment_id: str,
    department_slug: str = Query("store", description="部門スラッグ"),
    fiscal_year: Optional[int] = Query(None, description="会計年度（9月起点）"),
    supabase: Client = Depends(get_supabase_admin),
    current_user: User = Depends(get_current_user),
) -> StoreTrendSingleResponse:
    """
    単一店舗の月別売上推移を取得（前年・前々年比較付き）

    指定した店舗の会計年度（9月〜翌8月）の売上推移と
    前年・前々年の比較データを返す。

    Parameters:
    - segment_id: 店舗ID
    - department_slug: 部門スラッグ（デフォルト: "store"）
    - fiscal_year: 会計年度（デフォルト: 現在の会計年度）

    Returns:
    - segment_id: 店舗ID
    - segment_name: 店舗名
    - fiscal_year: 会計年度
    - months: 月ラベル（YYYY-MM形式）
    - actual: 当年売上
    - previous_year: 前年売上
    - two_years_ago: 前々年売上
    - summary: サマリー（合計・前年比）
    """
    # 会計年度が指定されていない場合は現在の会計年度を使用
    if fiscal_year is None:
        fiscal_year = get_fiscal_year(date.today())

    try:
        result = await get_store_trend_single(
            supabase=supabase,
            segment_id=segment_id,
            fiscal_year=fiscal_year
        )
        return StoreTrendSingleResponse(**result)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"店舗推移の取得に失敗しました: {str(e)}"
        )
