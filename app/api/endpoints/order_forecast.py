"""
予想注文（発注バット数予測）エンドポイント

GET /order-forecast - 指定日の予想バット数・前年/前々年カレンダーを返す
GET /order-forecast/daily-products - 日別×商品別パック数
GET /order-forecast/hourly-products - 時間帯別×商品別パック数
"""
from fastapi import APIRouter, Depends, Query
from supabase import Client

from app.api.deps import get_current_user, get_supabase_admin
from app.schemas.kpi import User
from app.schemas.order_forecast import (
    OrderForecastResponse,
    DailyProductBreakdownResponse,
    HourlyProductBreakdownResponse,
)
from app.services.order_forecast_service import (
    get_order_forecast,
    get_daily_product_breakdown,
    get_hourly_product_breakdown,
)


router = APIRouter(tags=["予想注文"])


@router.get(
    "",
    response_model=OrderForecastResponse,
    summary="予想注文データを取得",
    description="""
    指定日の発注バット数予測データを取得する。

    前年・前々年の同曜日実績を参照し、予想バット数を算出する。
    カレンダー形式で前年・前々年の同月実績も返す。
    """,
)
async def order_forecast(
    target_date: str = Query(
        ...,
        description="対象日 (YYYY-MM-DD)",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    ),
    segment_id: str = Query(None, description="セグメントID（省略時は全店舗）"),
    department_slug: str = Query("store", description="部門スラッグ"),
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
):
    return await get_order_forecast(supabase, target_date, segment_id, department_slug)


@router.get(
    "/daily-products",
    response_model=DailyProductBreakdownResponse,
    summary="日別×商品別パック数を取得",
    description="指定年月の日別×商品別パック数を返す。",
)
async def daily_product_breakdown(
    year: int = Query(..., description="対象年"),
    month: int = Query(..., ge=1, le=12, description="対象月"),
    segment_id: str = Query(None, description="セグメントID（省略時は全店舗合算）"),
    department_slug: str = Query("store", description="部門スラッグ"),
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
):
    return await get_daily_product_breakdown(supabase, year, month, segment_id, department_slug)


@router.get(
    "/hourly-products",
    response_model=HourlyProductBreakdownResponse,
    summary="時間帯別×商品別パック数を取得",
    description="指定日の時間帯別×商品別パック数を返す。",
)
async def hourly_product_breakdown(
    target_date: str = Query(
        ...,
        description="対象日 (YYYY-MM-DD)",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    ),
    segment_id: str = Query(None, description="セグメントID（省略時は全店舗合算）"),
    department_slug: str = Query("store", description="部門スラッグ"),
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
):
    return await get_hourly_product_breakdown(supabase, target_date, segment_id, department_slug)
