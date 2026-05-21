"""
EC Web分析（GA4連携）サービス

GoogleアナリティクスGA4 Data API（google-analytics-data）でEC主要数値を取得する。
settings.ga4_enabled が False の場合、または取得に失敗した場合はサンプルデータを返す。
"""
import json
import os
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.services.cache_service import cached


# =============================================================================
# サンプルデータ
# =============================================================================

def _sample_summary() -> Dict[str, Any]:
    """design-demo の数値に合わせたサンプルデータを返す。"""
    yesterday = date.today() - timedelta(days=1)
    channels = [
        {"channel": "オーガニック検索", "share": 46.0},
        {"channel": "直接", "share": 22.0},
        {"channel": "SNS", "share": 18.0},
        {"channel": "参照", "share": 9.0},
        {"channel": "メール", "share": 5.0},
    ]
    regions = [
        {"region": "福岡県", "sessions": 980},
        {"region": "東京都", "sessions": 520},
        {"region": "大阪府", "sessions": 410},
        {"region": "熊本県", "sessions": 380},
        {"region": "神奈川県", "sessions": 290},
    ]
    sessions = {"value": 2840.0, "vs_prev_month": 8.2, "vs_prev_year": 14.1}
    bounce_rate = {"value": 38.2, "vs_prev_month": -1.3, "vs_prev_year": -2.1}

    return {
        "sessions": sessions,
        "bounce_rate": bounce_rate,
        "channels": channels,
        "regions": regions,
        "comment": _build_comment(sessions, bounce_rate, channels),
        "is_sample": True,
        "date_label": f"{yesterday.month}月{yesterday.day}日（前日）",
    }


# =============================================================================
# 簡易コメント生成（ルールベース）
# =============================================================================

def _build_comment(
    sessions: Dict[str, float],
    bounce_rate: Dict[str, float],
    channels: List[Dict[str, Any]],
    top_region: Optional[str] = None,
) -> str:
    """前年比の符号・流入経路の最大・離脱率の改善有無から簡易コメントを生成する。"""
    parts: List[str] = []

    # 流入数の前年比
    yoy = sessions.get("vs_prev_year", 0.0)
    if yoy > 5:
        parts.append(f"前日の流入数は前年同月比 +{yoy:.1f}% と好調。")
    elif yoy < -5:
        parts.append(f"前日の流入数は前年同月比 {yoy:.1f}% と減少傾向。")
    else:
        sign = "+" if yoy >= 0 else ""
        parts.append(f"前日の流入数は前年同月比 {sign}{yoy:.1f}% と横ばいです。")

    # 流入経路の最大
    if channels:
        top_channel = max(channels, key=lambda c: c.get("share", 0.0))
        share = top_channel.get("share", 0.0)
        name = top_channel.get("channel", "")
        if share >= 45:
            parts.append(f"{name}が流入の約半数を占めています。")
        else:
            parts.append(f"{name}が流入経路の最多（{share:.0f}%）です。")

    # 離脱率の改善有無（負の値 = 改善）
    bounce_yoy = bounce_rate.get("vs_prev_year", 0.0)
    if bounce_yoy < 0:
        parts.append("離脱率も前年から改善傾向です。")
    elif bounce_yoy > 0:
        parts.append("離脱率は前年より上昇しており注意が必要です。")

    # 最多流入地区
    if top_region:
        parts.append(f"{top_region}からのアクセスが最多です。")

    return "".join(parts)


# =============================================================================
# GA4 Data API 連携
# =============================================================================

def _build_ga4_client() -> Any:
    """GA4_CREDENTIALS_JSON（JSON文字列 or ファイルパス）からBetaAnalyticsDataClientを構築する。"""
    # 遅延import: 未インストール環境でも他機能が壊れないようにする
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.oauth2 import service_account

    raw = settings.GA4_CREDENTIALS_JSON.strip()

    if raw.startswith("{"):
        # JSON文字列として解釈
        info = json.loads(raw)
        credentials = service_account.Credentials.from_service_account_info(info)
    elif os.path.isfile(raw):
        # ファイルパスとして解釈
        credentials = service_account.Credentials.from_service_account_file(raw)
    else:
        raise ValueError("GA4_CREDENTIALS_JSON is not valid JSON or file path")

    return BetaAnalyticsDataClient(credentials=credentials)


def _date_label(d: date) -> str:
    """対象日ラベルを生成する。"""
    return f"{d.month}月{d.day}日（前日）"


def _comparison(current: float, prev_month: float, prev_year: float, is_rate: bool) -> Dict[str, float]:
    """指標の比較値を計算する。

    is_rate が True の場合（離脱率）はポイント差、それ以外は変化率（%）を返す。
    """
    if is_rate:
        return {
            "value": round(current, 1),
            "vs_prev_month": round(current - prev_month, 1),
            "vs_prev_year": round(current - prev_year, 1),
        }

    def _pct(base: float) -> float:
        if base <= 0:
            return 0.0
        return round((current - base) / base * 100, 1)

    return {
        "value": round(current, 1),
        "vs_prev_month": _pct(prev_month),
        "vs_prev_year": _pct(prev_year),
    }


def _run_report(client: Any, property_id: str) -> Dict[str, Any]:
    """GA4 run_report を実行し、EC主要数値を集計して返す。"""
    from google.analytics.data_v1beta.types import (
        DateRange,
        Dimension,
        Metric,
        RunReportRequest,
    )

    today = date.today()
    yesterday = today - timedelta(days=1)

    # 前月同日・前年同日（存在しない日付は月末に丸める）
    def _shift(d: date, years: int = 0, months: int = 0) -> date:
        y = d.year + years
        m = d.month + months
        while m > 12:
            m -= 12
            y += 1
        while m < 1:
            m += 12
            y -= 1
        day = d.day
        while True:
            try:
                return date(y, m, day)
            except ValueError:
                day -= 1

    prev_month_day = _shift(yesterday, months=-1)
    prev_year_day = _shift(yesterday, years=-1)

    property_name = f"properties/{property_id}"

    # --- 指標（sessions / bounceRate）の日別比較 ---
    metric_request = RunReportRequest(
        property=property_name,
        dimensions=[Dimension(name="date")],
        metrics=[Metric(name="sessions"), Metric(name="bounceRate")],
        date_ranges=[
            DateRange(start_date=yesterday.isoformat(), end_date=yesterday.isoformat(), name="current"),
            DateRange(start_date=prev_month_day.isoformat(), end_date=prev_month_day.isoformat(), name="prev_month"),
            DateRange(start_date=prev_year_day.isoformat(), end_date=prev_year_day.isoformat(), name="prev_year"),
        ],
    )
    metric_resp = client.run_report(metric_request)

    sessions_by_range: Dict[str, float] = {}
    bounce_by_range: Dict[str, float] = {}
    for row in metric_resp.rows:
        # date_range はディメンション値の最後に付与される
        range_name = row.dimension_values[-1].value if row.dimension_values else "current"
        sess = float(row.metric_values[0].value or 0)
        bounce = float(row.metric_values[1].value or 0) * 100  # bounceRateは0〜1の比率
        sessions_by_range[range_name] = sessions_by_range.get(range_name, 0.0) + sess
        # 離脱率は平均扱い（1日1行想定のため上書きで十分）
        bounce_by_range[range_name] = bounce

    sessions = _comparison(
        sessions_by_range.get("current", 0.0),
        sessions_by_range.get("prev_month", 0.0),
        sessions_by_range.get("prev_year", 0.0),
        is_rate=False,
    )
    bounce_rate = _comparison(
        bounce_by_range.get("current", 0.0),
        bounce_by_range.get("prev_month", 0.0),
        bounce_by_range.get("prev_year", 0.0),
        is_rate=True,
    )

    # --- 流入経路（sessionDefaultChannelGroup） ---
    channel_request = RunReportRequest(
        property=property_name,
        dimensions=[Dimension(name="sessionDefaultChannelGroup")],
        metrics=[Metric(name="sessions")],
        date_ranges=[DateRange(start_date=yesterday.isoformat(), end_date=yesterday.isoformat())],
    )
    channel_resp = client.run_report(channel_request)
    channel_pairs: List[Tuple[str, float]] = []
    for row in channel_resp.rows:
        name = row.dimension_values[0].value if row.dimension_values else "その他"
        sess = float(row.metric_values[0].value or 0)
        channel_pairs.append((_translate_channel(name), sess))

    total_channel = sum(s for _, s in channel_pairs)
    channels: List[Dict[str, Any]] = []
    if total_channel > 0:
        for name, sess in sorted(channel_pairs, key=lambda x: x[1], reverse=True):
            channels.append({"channel": name, "share": round(sess / total_channel * 100, 1)})

    # --- 地区別流入（region） ---
    region_request = RunReportRequest(
        property=property_name,
        dimensions=[Dimension(name="region")],
        metrics=[Metric(name="sessions")],
        date_ranges=[DateRange(start_date=yesterday.isoformat(), end_date=yesterday.isoformat())],
    )
    region_resp = client.run_report(region_request)
    region_pairs: List[Tuple[str, int]] = []
    for row in region_resp.rows:
        name = row.dimension_values[0].value if row.dimension_values else "不明"
        sess = int(float(row.metric_values[0].value or 0))
        region_pairs.append((name, sess))
    region_pairs.sort(key=lambda x: x[1], reverse=True)
    regions = [{"region": name, "sessions": sess} for name, sess in region_pairs[:5]]

    top_region = regions[0]["region"] if regions else None

    return {
        "sessions": sessions,
        "bounce_rate": bounce_rate,
        "channels": channels,
        "regions": regions,
        "comment": _build_comment(sessions, bounce_rate, channels, top_region),
        "is_sample": False,
        "date_label": _date_label(yesterday),
    }


def _translate_channel(name: str) -> str:
    """GA4のチャネルグループ名を日本語表記に変換する。"""
    mapping = {
        "Organic Search": "オーガニック検索",
        "Direct": "直接",
        "Organic Social": "SNS",
        "Paid Social": "SNS",
        "Social": "SNS",
        "Referral": "参照",
        "Email": "メール",
        "Paid Search": "リスティング広告",
        "Display": "ディスプレイ広告",
        "Affiliates": "アフィリエイト",
        "(Other)": "その他",
        "Unassigned": "その他",
    }
    return mapping.get(name, name)


# =============================================================================
# 公開関数
# =============================================================================

@cached(prefix="ga4", ttl=3600)
async def get_ec_summary() -> Dict[str, Any]:
    """EC Web分析サマリーを取得する（TTL 3600秒）。

    settings.ga4_enabled が False の場合、または取得に失敗した場合はサンプルデータを返す。
    """
    if not settings.ga4_enabled:
        return _sample_summary()

    try:
        client = _build_ga4_client()
        return _run_report(client, settings.GA4_PROPERTY_ID)
    except Exception:
        # 取得失敗時はサンプルデータにフォールバック
        return _sample_summary()
