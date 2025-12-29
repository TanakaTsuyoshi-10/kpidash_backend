"""
KPIエンドポイントモジュール

KPIデータの取得・計算を行うエンドポイントを提供する。
部門別サマリー、店舗別詳細、グラフデータ、ランキング、アラートを取得可能。
"""
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, HTTPException, status
from supabase import Client

from app.api.deps import get_current_user, get_supabase_admin
from app.schemas.kpi import (
    User,
    DepartmentResponse,
    SegmentResponse,
    KPIDefinitionResponse,
    KPIValueResponse,
    DepartmentSummary,
    SegmentDetail,
    ChartData,
    RankingItem,
    AlertItem,
    ProductMatrixResponse,
    ProductTrendResponse,
    TargetValueCreate,
    TargetValueUpdate,
    TargetValueBulkCreate,
    TargetValueResponse,
    TargetValueBulkResponse,
    TargetMatrixResponse,
    StoreDetailResponse,
)
from app.services.kpi_service import (
    get_department_summary,
    get_segment_detail,
    get_comparison_data,
    get_ranking,
    get_alerts,
    get_product_matrix,
    get_product_trend,
    get_store_detail,
)
from app.services.target_service import (
    create_target_value,
    update_target_value,
    delete_target_value,
    bulk_upsert_targets,
    get_target_values,
    get_target_matrix,
)

# ルーター作成
router = APIRouter(tags=["KPI"])


# =============================================================================
# 部門関連エンドポイント
# =============================================================================

@router.get(
    "/departments",
    response_model=List[DepartmentResponse],
    summary="部門一覧取得",
    description="すべての部門を取得する。",
)
async def get_departments(
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
) -> List[DepartmentResponse]:
    """
    部門一覧を取得する

    Returns:
        List[DepartmentResponse]: 部門一覧
    """
    response = supabase.table("departments").select("id, name, slug").execute()
    return [
        DepartmentResponse(id=d["id"], name=d["name"], slug=d["slug"])
        for d in response.data
    ]


# =============================================================================
# 店舗・拠点関連エンドポイント
# =============================================================================

@router.get(
    "/segments",
    response_model=List[SegmentResponse],
    summary="店舗・拠点一覧取得",
    description="指定した部門の店舗・拠点一覧を取得する。",
)
async def get_segments(
    department_slug: Optional[str] = Query(None, description="部門スラッグ（store, online等）"),
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
) -> List[SegmentResponse]:
    """
    店舗・拠点一覧を取得する

    Args:
        department_slug: 部門スラッグ（オプション）

    Returns:
        List[SegmentResponse]: 店舗・拠点一覧
    """
    query = supabase.table("segments").select("id, code, name, department_id")

    if department_slug:
        # 部門IDを取得
        dept_response = supabase.table("departments").select("id").eq(
            "slug", department_slug
        ).single().execute()
        if not dept_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"部門が見つかりません: {department_slug}"
            )
        query = query.eq("department_id", dept_response.data["id"])

    response = query.execute()
    return [
        SegmentResponse(
            id=s["id"],
            department_id=s["department_id"],
            code=s["code"],
            name=s["name"]
        )
        for s in response.data
    ]


# =============================================================================
# KPI定義関連エンドポイント
# =============================================================================

@router.get(
    "/definitions",
    response_model=List[KPIDefinitionResponse],
    summary="KPI定義一覧取得",
    description="指定した部門のKPI定義一覧を取得する。",
)
async def get_kpi_definitions(
    department_slug: Optional[str] = Query(None, description="部門スラッグ"),
    category: Optional[str] = Query(None, description="カテゴリ（全体, 商品グループ, 分析）"),
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
) -> List[KPIDefinitionResponse]:
    """
    KPI定義一覧を取得する

    Args:
        department_slug: 部門スラッグ（オプション）
        category: カテゴリ（オプション）

    Returns:
        List[KPIDefinitionResponse]: KPI定義一覧
    """
    query = supabase.table("kpi_definitions").select(
        "id, department_id, category, name, unit, is_calculated, formula, display_order, is_visible"
    ).eq("is_visible", True)

    if department_slug:
        dept_response = supabase.table("departments").select("id").eq(
            "slug", department_slug
        ).single().execute()
        if dept_response.data:
            query = query.eq("department_id", dept_response.data["id"])

    if category:
        query = query.eq("category", category)

    response = query.order("display_order").execute()
    return [
        KPIDefinitionResponse(
            id=k["id"],
            department_id=k["department_id"],
            category=k["category"],
            name=k["name"],
            unit=k["unit"],
            is_calculated=k["is_calculated"],
            formula=k.get("formula"),
            display_order=k["display_order"],
            is_visible=k["is_visible"]
        )
        for k in response.data
    ]


# =============================================================================
# KPIサマリー・詳細エンドポイント
# =============================================================================

@router.get(
    "/summary",
    response_model=DepartmentSummary,
    summary="部門別KPIサマリー取得",
    description="""
    部門全体のKPIサマリーを取得する。

    - 単月実績・目標
    - 年度累計実績・目標
    - 達成率・前年比
    - アラートレベル
    """,
)
async def get_summary(
    department_slug: str = Query(..., description="部門スラッグ: finance, store, online, factory"),
    month: Optional[date] = Query(None, description="対象月（YYYY-MM-DD形式、省略時は当月）"),
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
) -> DepartmentSummary:
    """
    部門別KPIサマリーを取得する

    Args:
        department_slug: 部門スラッグ
        month: 対象月（省略時は当月）

    Returns:
        DepartmentSummary: 部門KPIサマリー
    """
    # 部門IDを取得
    dept_response = supabase.table("departments").select("id").eq(
        "slug", department_slug
    ).single().execute()

    if not dept_response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"部門が見つかりません: {department_slug}"
        )

    department_id = dept_response.data["id"]
    target_month = month if month else date.today()

    result = await get_department_summary(supabase, department_id, target_month)
    return DepartmentSummary(**result)


@router.get(
    "/segment/{segment_id}",
    response_model=SegmentDetail,
    summary="店舗別詳細KPI取得",
    description="""
    店舗・拠点別の詳細KPIを取得する。

    - 各KPI指標の実績・目標・達成率
    - 計算指標（客単価、1人あたり個数）
    """,
)
async def get_segment(
    segment_id: str,
    month: Optional[date] = Query(None, description="対象月（省略時は当月）"),
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
) -> SegmentDetail:
    """
    店舗・拠点別の詳細KPIを取得する

    Args:
        segment_id: セグメント（店舗）ID
        month: 対象月（省略時は当月）

    Returns:
        SegmentDetail: 店舗詳細KPI
    """
    # セグメントの存在確認
    seg_response = supabase.table("segments").select("id").eq(
        "id", segment_id
    ).execute()

    if not seg_response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"店舗が見つかりません: {segment_id}"
        )

    target_month = month if month else date.today()

    result = await get_segment_detail(supabase, segment_id, target_month)
    return SegmentDetail(**result)


# =============================================================================
# グラフ・比較データエンドポイント
# =============================================================================

@router.get(
    "/chart",
    response_model=ChartData,
    summary="グラフ用時系列データ取得",
    description="""
    グラフ表示用の時系列データを取得する（会計年度ベース：9月〜翌8月）。

    - 会計年度の12ヶ月分の実績・目標・前年データ
    - 月の順序は9月→10月→...→7月→8月
    """,
)
async def get_chart_data(
    department_slug: str = Query(..., description="部門スラッグ"),
    kpi_name: str = Query("売上高", description="KPI名"),
    fiscal_year: Optional[int] = Query(None, description="会計年度（省略時は現在の会計年度）"),
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
) -> ChartData:
    """
    グラフ表示用の時系列データを取得する

    Args:
        department_slug: 部門スラッグ
        kpi_name: KPI名
        fiscal_year: 会計年度（2024年度 = 2024年9月〜2025年8月）

    Returns:
        ChartData: グラフ用データ
    """
    # 部門IDを取得
    dept_response = supabase.table("departments").select("id").eq(
        "slug", department_slug
    ).single().execute()

    if not dept_response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"部門が見つかりません: {department_slug}"
        )

    department_id = dept_response.data["id"]

    result = await get_comparison_data(
        supabase, department_id, kpi_name, fiscal_year
    )
    return ChartData(**result)


# =============================================================================
# ランキングエンドポイント
# =============================================================================

@router.get(
    "/ranking",
    response_model=List[RankingItem],
    summary="店舗ランキング取得",
    description="店舗ランキングを取得する。",
)
async def get_segment_ranking(
    department_slug: str = Query(..., description="部門スラッグ"),
    kpi_name: str = Query("売上高", description="KPI名"),
    month: Optional[date] = Query(None, description="対象月（省略時は当月）"),
    limit: int = Query(10, ge=1, le=50, description="上位件数"),
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
) -> List[RankingItem]:
    """
    店舗ランキングを取得する

    Args:
        department_slug: 部門スラッグ
        kpi_name: KPI名
        month: 対象月
        limit: 上位件数

    Returns:
        List[RankingItem]: ランキングデータ
    """
    # 部門IDを取得
    dept_response = supabase.table("departments").select("id").eq(
        "slug", department_slug
    ).single().execute()

    if not dept_response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"部門が見つかりません: {department_slug}"
        )

    department_id = dept_response.data["id"]
    target_month = month if month else date.today()

    result = await get_ranking(supabase, department_id, target_month, kpi_name, limit)
    return [RankingItem(**item) for item in result]


# =============================================================================
# アラートエンドポイント
# =============================================================================

@router.get(
    "/alerts",
    response_model=List[AlertItem],
    summary="未達アラート一覧取得",
    description="""
    未達アラート一覧を取得する。

    - critical, warning レベルの項目を抽出
    - 部門指定なしの場合は全部門
    """,
)
async def get_alert_list(
    department_slug: Optional[str] = Query(None, description="部門スラッグ（省略時は全部門）"),
    month: Optional[date] = Query(None, description="対象月（省略時は当月）"),
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
) -> List[AlertItem]:
    """
    未達アラート一覧を取得する

    Args:
        department_slug: 部門スラッグ（省略時は全部門）
        month: 対象月

    Returns:
        List[AlertItem]: アラート一覧
    """
    department_id = None
    if department_slug:
        dept_response = supabase.table("departments").select("id").eq(
            "slug", department_slug
        ).single().execute()
        if dept_response.data:
            department_id = dept_response.data["id"]

    target_month = month if month else date.today()

    result = await get_alerts(supabase, department_id, target_month)
    return [AlertItem(**item) for item in result]


# =============================================================================
# 店舗詳細エンドポイント
# =============================================================================

@router.get(
    "/store/{segment_id}/detail",
    response_model=StoreDetailResponse,
    summary="店舗詳細取得",
    description="""
    店舗の詳細データを取得する。

    - 店舗全体のサマリー（売上・客数・客単価）
    - 商品グループ別の売上データ
    - 前年同月比較
    """,
)
async def get_store_detail_data(
    segment_id: str,
    month: date = Query(..., description="対象月（YYYY-MM-DD形式）"),
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
) -> StoreDetailResponse:
    """
    店舗の詳細データを取得する

    Args:
        segment_id: 店舗ID
        month: 対象月

    Returns:
        StoreDetailResponse: 店舗詳細データ
    """
    result = await get_store_detail(supabase, segment_id, month)

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"店舗が見つかりません: {segment_id}"
        )

    return StoreDetailResponse(**result)


# =============================================================================
# 商品マトリックスエンドポイント（一括取得）
# =============================================================================

@router.get(
    "/product-matrix",
    response_model=ProductMatrixResponse,
    summary="商品マトリックス一括取得",
    description="""
    店舗×商品グループのマトリックスデータを一括取得する。

    - 1回のAPIコールで全店舗のデータを取得
    - 各商品グループの当月実績・前年同月・前年比を含む
    - フロントエンドでのN+1問題を解消
    - 累計モード（cumulative）では9月〜対象月の累計と前々年比も含む

    ## パラメータ
    - period_type: 期間タイプ（monthly: 単月, cumulative: 9月〜対象月の累計）

    ## レスポンス構造
    - product_groups: 商品グループ名のリスト
    - stores: 店舗別の商品グループ別売上データ
    - totals: 商品グループ別の全店舗合計
    """,
)
async def get_product_matrix_data(
    department_slug: str = Query(..., description="部門スラッグ: store, online等"),
    month: Optional[date] = Query(None, description="対象月（YYYY-MM-DD形式、省略時は当月）"),
    period_type: str = Query("monthly", description="期間タイプ（monthly/cumulative）"),
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
) -> ProductMatrixResponse:
    """
    商品マトリックスデータを一括取得する

    Args:
        department_slug: 部門スラッグ
        month: 対象月（省略時は当月）
        period_type: 期間タイプ（monthly: 単月, cumulative: 累計）

    Returns:
        ProductMatrixResponse: 商品マトリックスデータ
    """
    # period_typeのバリデーション
    if period_type not in ["monthly", "cumulative"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="period_typeは'monthly'または'cumulative'を指定してください"
        )

    # 部門IDを取得
    dept_response = supabase.table("departments").select("id").eq(
        "slug", department_slug
    ).single().execute()

    if not dept_response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"部門が見つかりません: {department_slug}"
        )

    department_id = dept_response.data["id"]
    target_month = month if month else date.today()

    result = await get_product_matrix(supabase, department_id, target_month, period_type)
    return ProductMatrixResponse(**result)


# =============================================================================
# 商品別月次推移エンドポイント（グラフ用）
# =============================================================================

@router.get(
    "/product-trend",
    response_model=ProductTrendResponse,
    summary="商品別月次推移取得",
    description="""
    商品グループ別の月次推移データを取得する（グラフ用、会計年度ベース：9月〜翌8月）。

    - 指定した商品グループの月次推移データを取得
    - 全店舗合計と店舗別データの両方を含む
    - 前年同月データと前年比も含む
    - 月の順序は9月→10月→...→7月→8月

    ## グラフ表示用途
    - 折れ線グラフ: 月次推移（実績 vs 前年）
    - 棒グラフ: 店舗別比較
    - 積み上げグラフ: 店舗構成比
    """,
)
async def get_product_trend_data(
    department_slug: str = Query(..., description="部門スラッグ: store, online等"),
    product_group: str = Query(..., description="商品グループ名: ぎょうざ, しょうが入ぎょうざ等"),
    fiscal_year: Optional[int] = Query(None, description="会計年度（省略時は現在の会計年度）"),
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
) -> ProductTrendResponse:
    """
    商品グループ別の月次推移データを取得する

    Args:
        department_slug: 部門スラッグ
        product_group: 商品グループ名
        fiscal_year: 会計年度（2024年度 = 2024年9月〜2025年8月）

    Returns:
        ProductTrendResponse: 月次推移データ
    """
    # 部門IDを取得
    dept_response = supabase.table("departments").select("id").eq(
        "slug", department_slug
    ).single().execute()

    if not dept_response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"部門が見つかりません: {department_slug}"
        )

    department_id = dept_response.data["id"]

    result = await get_product_trend(supabase, department_id, product_group, fiscal_year)
    return ProductTrendResponse(**result)


# =============================================================================
# KPI値関連エンドポイント（既存）
# =============================================================================

@router.get(
    "/values",
    response_model=List[KPIValueResponse],
    summary="KPI値取得",
    description="""
    指定した条件でKPI値を取得する。

    目標値・実績値、月次・累計の切り替えが可能。
    """,
)
async def get_kpi_values(
    segment_id: Optional[str] = Query(None, description="店舗・拠点ID"),
    kpi_id: Optional[str] = Query(None, description="KPI定義ID"),
    start_date: Optional[date] = Query(None, description="開始日（YYYY-MM-DD）"),
    end_date: Optional[date] = Query(None, description="終了日（YYYY-MM-DD）"),
    is_target: Optional[bool] = Query(None, description="目標値(true)か実績値(false)か"),
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
) -> List[KPIValueResponse]:
    """
    KPI値を取得する

    Args:
        segment_id: 店舗・拠点ID（オプション）
        kpi_id: KPI定義ID（オプション）
        start_date: 開始日（オプション）
        end_date: 終了日（オプション）
        is_target: 目標値/実績値フィルタ（オプション）

    Returns:
        List[KPIValueResponse]: KPI値一覧
    """
    query = supabase.table("kpi_values").select(
        "id, segment_id, kpi_id, date, value, is_target"
    )

    if segment_id:
        query = query.eq("segment_id", segment_id)
    if kpi_id:
        query = query.eq("kpi_id", kpi_id)
    if start_date:
        query = query.gte("date", start_date.isoformat())
    if end_date:
        query = query.lte("date", end_date.isoformat())
    if is_target is not None:
        query = query.eq("is_target", is_target)

    response = query.order("date", desc=True).execute()

    return [
        KPIValueResponse(
            id=v["id"],
            segment_id=v["segment_id"],
            kpi_id=v["kpi_id"],
            date=v["date"],
            value=float(v["value"]),
            is_target=v["is_target"]
        )
        for v in response.data
    ]


# =============================================================================
# 目標値管理エンドポイント
# =============================================================================

@router.post(
    "/targets",
    response_model=TargetValueResponse,
    status_code=status.HTTP_201_CREATED,
    summary="目標値登録",
    description="""
    目標値を登録する。

    - 同一の店舗・KPI・月の組み合わせが存在する場合は更新（Upsert）
    - 存在しない場合は新規作成
    """,
)
async def create_target(
    request: TargetValueCreate,
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
) -> TargetValueResponse:
    """
    目標値を登録する

    Args:
        request: 目標値作成リクエスト

    Returns:
        TargetValueResponse: 登録された目標値
    """
    try:
        result = await create_target_value(
            supabase,
            segment_id=request.segment_id,
            kpi_id=request.kpi_id,
            month=request.month,
            value=request.value
        )
        return TargetValueResponse(
            id=result["id"],
            segment_id=request.segment_id,
            segment_name=None,
            kpi_id=request.kpi_id,
            kpi_name=None,
            month=request.month,
            value=request.value
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.put(
    "/targets/{target_id}",
    response_model=TargetValueResponse,
    summary="目標値更新",
    description="既存の目標値を更新する。",
)
async def update_target(
    target_id: int,
    request: TargetValueUpdate,
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
) -> TargetValueResponse:
    """
    目標値を更新する

    Args:
        target_id: 目標値ID
        request: 更新リクエスト

    Returns:
        TargetValueResponse: 更新された目標値
    """
    try:
        result = await update_target_value(supabase, target_id, request.value)
        return TargetValueResponse(
            id=result["id"],
            segment_id=result["segment_id"],
            segment_name=None,
            kpi_id=result["kpi_id"],
            kpi_name=None,
            month=result["date"],
            value=float(result["value"])
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


@router.delete(
    "/targets/{target_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="目標値削除",
    description="目標値を削除する。",
)
async def delete_target(
    target_id: int,
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
):
    """
    目標値を削除する

    Args:
        target_id: 目標値ID
    """
    success = await delete_target_value(supabase, target_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="目標値が見つかりません"
        )


@router.post(
    "/targets/bulk",
    response_model=TargetValueBulkResponse,
    summary="目標値一括登録",
    description="""
    目標値を一括で登録・更新する。

    - 既存の値は上書き（Upsert）
    - エラーが発生した項目はスキップして処理を継続
    - 処理結果（成功件数、エラー件数）を返す
    """,
)
async def bulk_create_targets(
    request: TargetValueBulkCreate,
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
) -> TargetValueBulkResponse:
    """
    目標値を一括登録する

    Args:
        request: 一括登録リクエスト

    Returns:
        TargetValueBulkResponse: 処理結果
    """
    targets = [
        {
            "segment_id": t.segment_id,
            "kpi_id": t.kpi_id,
            "month": t.month,
            "value": t.value
        }
        for t in request.targets
    ]

    result = await bulk_upsert_targets(supabase, targets)
    return TargetValueBulkResponse(
        success=len(result["errors"]) == 0,
        created_count=result["created_count"],
        updated_count=result["updated_count"],
        errors=result["errors"]
    )


@router.get(
    "/targets",
    response_model=List[TargetValueResponse],
    summary="目標値一覧取得",
    description="""
    目標値一覧を取得する。

    - 部門スラッグと対象月は必須
    - 店舗ID、KPI IDでフィルタ可能
    """,
)
async def list_targets(
    department_slug: str = Query(..., description="部門スラッグ"),
    month: date = Query(..., description="対象月（YYYY-MM-DD形式）"),
    segment_id: Optional[str] = Query(None, description="店舗ID（オプション）"),
    kpi_id: Optional[str] = Query(None, description="KPI ID（オプション）"),
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
) -> List[TargetValueResponse]:
    """
    目標値一覧を取得する

    Args:
        department_slug: 部門スラッグ
        month: 対象月
        segment_id: 店舗ID（オプション）
        kpi_id: KPI ID（オプション）

    Returns:
        List[TargetValueResponse]: 目標値一覧
    """
    # 部門IDを取得
    dept_response = supabase.table("departments").select("id").eq(
        "slug", department_slug
    ).single().execute()

    if not dept_response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"部門が見つかりません: {department_slug}"
        )

    department_id = dept_response.data["id"]

    result = await get_target_values(
        supabase, department_id, month, segment_id, kpi_id
    )
    return [TargetValueResponse(**item) for item in result]


@router.get(
    "/targets/matrix",
    response_model=TargetMatrixResponse,
    summary="目標値マトリックス取得",
    description="""
    店舗×KPIの目標値マトリックスを取得する。

    - 目標値入力画面用
    - 店舗一覧とKPI一覧、および既存の目標値を返す
    - 未設定のセルはnullで返す
    """,
)
async def get_targets_matrix(
    department_slug: str = Query(..., description="部門スラッグ"),
    month: date = Query(..., description="対象月（YYYY-MM-DD形式）"),
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
) -> TargetMatrixResponse:
    """
    目標値マトリックスを取得する

    Args:
        department_slug: 部門スラッグ
        month: 対象月

    Returns:
        TargetMatrixResponse: 目標値マトリックス
    """
    # 部門IDを取得
    dept_response = supabase.table("departments").select("id").eq(
        "slug", department_slug
    ).single().execute()

    if not dept_response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"部門が見つかりません: {department_slug}"
        )

    department_id = dept_response.data["id"]

    result = await get_target_matrix(supabase, department_id, month)
    return TargetMatrixResponse(**result)
