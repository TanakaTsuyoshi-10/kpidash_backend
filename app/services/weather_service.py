"""
天気データサービス

Open-Meteo API から天気データを取得し、DBにキャッシュする。
地区ごとの緯度経度に基づいて天気を取得。
"""
import logging
from datetime import date, timedelta
from typing import Dict, List, Optional, Any

import httpx
from supabase import Client

from app.services.daily_sales_service import _fetch_all

logger = logging.getLogger(__name__)

# =============================================================================
# 定数
# =============================================================================

# 地区名 → (緯度, 経度)
REGION_COORDINATES: Dict[str, tuple] = {
    "都城地区": (31.72, 131.07),
    "宮崎地区": (31.91, 131.42),
    "鹿児島地区": (31.60, 130.56),
    "福岡地区": (33.59, 130.40),
    "熊本地区": (32.80, 130.71),
    "その他": (31.72, 131.07),  # 本社=都城
}

DEFAULT_REGION = "都城地区"

# WMO Weather Interpretation Codes → 日本語ラベル
WMO_LABELS: Dict[int, str] = {
    0: "快晴",
    1: "晴れ",
    2: "一部曇り",
    3: "曇り",
    45: "霧",
    48: "着氷性の霧",
    51: "弱い霧雨",
    53: "霧雨",
    55: "強い霧雨",
    56: "弱い着氷性霧雨",
    57: "強い着氷性霧雨",
    61: "弱い雨",
    63: "雨",
    65: "強い雨",
    66: "弱い着氷性の雨",
    67: "強い着氷性の雨",
    71: "弱い雪",
    73: "雪",
    75: "強い雪",
    77: "霧雪",
    80: "弱いにわか雨",
    81: "にわか雨",
    82: "強いにわか雨",
    85: "弱いにわか雪",
    86: "強いにわか雪",
    95: "雷雨",
    96: "雹を伴う雷雨",
    99: "強い雹を伴う雷雨",
}

API_TIMEOUT = 10.0  # seconds


# =============================================================================
# 公開関数
# =============================================================================

def get_weather_label(code: int) -> str:
    """WMOコード → 日本語ラベル変換"""
    return WMO_LABELS.get(code, f"不明({code})")


async def resolve_region_name(supabase: Client, segment_id: Optional[str]) -> str:
    """segment_idからregion名を解決する

    Args:
        supabase: Supabaseクライアント
        segment_id: セグメントID（Noneの場合はデフォルト地区）

    Returns:
        地区名（例: "宮崎地区"）
    """
    if not segment_id:
        return DEFAULT_REGION

    try:
        result = (
            supabase.table("store_region_mapping")
            .select("region_id, regions(name)")
            .eq("segment_id", segment_id)
            .limit(1)
            .execute()
        )
        if result.data and len(result.data) > 0:
            region_data = result.data[0].get("regions")
            if region_data and isinstance(region_data, dict):
                return region_data.get("name", DEFAULT_REGION)
            elif region_data and isinstance(region_data, list) and len(region_data) > 0:
                return region_data[0].get("name", DEFAULT_REGION)
    except Exception as e:
        logger.warning(f"Failed to resolve region for segment {segment_id}: {e}")

    return DEFAULT_REGION


async def get_weather_for_dates(
    supabase: Client,
    region_name: str,
    dates: List[str],
) -> Dict[str, Optional[Dict[str, Any]]]:
    """指定日付リストの天気データを取得する

    Args:
        supabase: Supabaseクライアント
        region_name: 地区名
        dates: 日付リスト (YYYY-MM-DD)

    Returns:
        {date_str: {weather_code, weather_label, temp_max, temp_min} | None}
    """
    if not dates:
        return {}

    coords = REGION_COORDINATES.get(region_name, REGION_COORDINATES[DEFAULT_REGION])
    lat, lon = coords

    # region_id を取得
    region_id = await _get_region_id(supabase, region_name)
    if not region_id:
        return {d: None for d in dates}

    # DBキャッシュ照会
    cached = await _fetch_cached_weather(supabase, region_id, dates)

    # 未取得日を特定
    missing_dates = [d for d in dates if d not in cached]

    if missing_dates:
        # Open-Meteo API から取得
        fetched = await _fetch_from_api(lat, lon, missing_dates)

        # DBに保存
        if fetched:
            await _upsert_weather(supabase, region_id, fetched)
            cached.update(fetched)

    # WeatherInfo形式に変換
    result: Dict[str, Optional[Dict[str, Any]]] = {}
    for d in dates:
        raw = cached.get(d)
        if raw:
            result[d] = {
                "weather_code": raw["weather_code"],
                "weather_label": get_weather_label(raw["weather_code"]),
                "temp_max": raw.get("temperature_max"),
                "temp_min": raw.get("temperature_min"),
            }
        else:
            result[d] = None

    return result


async def get_weather_for_month(
    supabase: Client,
    region_name: str,
    year: int,
    month: int,
) -> Dict[str, Optional[Dict[str, Any]]]:
    """月の全日付分の天気データを取得する"""
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)

    dates = []
    d = start
    while d <= end:
        dates.append(d.isoformat())
        d += timedelta(days=1)

    return await get_weather_for_dates(supabase, region_name, dates)


# =============================================================================
# 内部関数
# =============================================================================

async def _get_region_id(supabase: Client, region_name: str) -> Optional[str]:
    """地区名からregion_idを取得"""
    try:
        result = (
            supabase.table("regions")
            .select("id")
            .eq("name", region_name)
            .limit(1)
            .execute()
        )
        if result.data and len(result.data) > 0:
            return result.data[0]["id"]
    except Exception as e:
        logger.warning(f"Failed to get region_id for {region_name}: {e}")
    return None


async def _fetch_cached_weather(
    supabase: Client,
    region_id: str,
    dates: List[str],
) -> Dict[str, Dict[str, Any]]:
    """DBからキャッシュ済み天気データを取得"""
    try:
        rows = _fetch_all(
            supabase.table("weather_data")
            .select("date, weather_code, temperature_max, temperature_min, source")
            .eq("region_id", region_id)
            .in_("date", dates)
        )

        today = date.today().isoformat()
        result = {}
        for row in rows:
            d = row["date"]
            # forecast データは当日以降のみ有効（過去日は archive で上書き可能にする）
            if row.get("source") == "forecast" and d < today:
                continue
            result[d] = {
                "weather_code": row["weather_code"],
                "temperature_max": float(row["temperature_max"]) if row["temperature_max"] is not None else None,
                "temperature_min": float(row["temperature_min"]) if row["temperature_min"] is not None else None,
                "source": row.get("source", "archive"),
            }
        return result
    except Exception as e:
        logger.warning(f"Failed to fetch cached weather: {e}")
        return {}


async def _fetch_from_api(
    lat: float,
    lon: float,
    dates: List[str],
) -> Dict[str, Dict[str, Any]]:
    """Open-Meteo APIから天気データを取得"""
    if not dates:
        return {}

    today = date.today()
    result: Dict[str, Dict[str, Any]] = {}

    # 過去日と未来日を分ける
    past_dates = [d for d in dates if date.fromisoformat(d) < today]
    future_dates = [d for d in dates if date.fromisoformat(d) >= today]

    # 過去日: archive API
    if past_dates:
        past_data = await _call_open_meteo(
            "https://archive-api.open-meteo.com/v1/archive",
            lat, lon, past_dates, "archive"
        )
        result.update(past_data)

    # 当日〜未来: forecast API
    if future_dates:
        future_data = await _call_open_meteo(
            "https://api.open-meteo.com/v1/forecast",
            lat, lon, future_dates, "forecast"
        )
        result.update(future_data)

    return result


async def _call_open_meteo(
    base_url: str,
    lat: float,
    lon: float,
    dates: List[str],
    source: str,
) -> Dict[str, Dict[str, Any]]:
    """Open-Meteo APIを呼び出す"""
    if not dates:
        return {}

    sorted_dates = sorted(dates)
    start_date = sorted_dates[0]
    end_date = sorted_dates[-1]
    date_set = set(dates)

    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date,
        "end_date": end_date,
        "daily": "weather_code,temperature_2m_max,temperature_2m_min",
        "timezone": "Asia/Tokyo",
    }

    try:
        async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
            response = await client.get(base_url, params=params)
            response.raise_for_status()
            data = response.json()

        daily = data.get("daily", {})
        time_list = daily.get("time", [])
        codes = daily.get("weather_code", [])
        temp_max_list = daily.get("temperature_2m_max", [])
        temp_min_list = daily.get("temperature_2m_min", [])

        result = {}
        for i, d in enumerate(time_list):
            if d in date_set:
                result[d] = {
                    "weather_code": codes[i] if i < len(codes) else 0,
                    "temperature_max": temp_max_list[i] if i < len(temp_max_list) else None,
                    "temperature_min": temp_min_list[i] if i < len(temp_min_list) else None,
                    "source": source,
                }

        return result

    except (httpx.HTTPError, httpx.TimeoutException, Exception) as e:
        logger.warning(f"Open-Meteo API error ({base_url}): {e}")
        return {}


async def _upsert_weather(
    supabase: Client,
    region_id: str,
    weather_data: Dict[str, Dict[str, Any]],
) -> None:
    """天気データをDBにupsert"""
    try:
        rows = []
        for date_str, data in weather_data.items():
            rows.append({
                "date": date_str,
                "region_id": region_id,
                "weather_code": data["weather_code"],
                "temperature_max": data.get("temperature_max"),
                "temperature_min": data.get("temperature_min"),
                "source": data.get("source", "archive"),
            })

        if rows:
            supabase.table("weather_data").upsert(
                rows,
                on_conflict="date,region_id",
            ).execute()

    except Exception as e:
        logger.warning(f"Failed to upsert weather data: {e}")
