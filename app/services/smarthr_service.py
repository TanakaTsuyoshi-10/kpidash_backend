"""
SmartHR連携サービス

SmartHR API（https://<subdomain>.smarthr.jp/api/v1）から
crews（従業員）・departments（部署）・payrolls（給与）・payslips（給与明細）を
取得し、部署別×月次の人件費・時間外労働に集計する。

認証情報（SMARTHR_SUBDOMAIN / SMARTHR_ACCESS_TOKEN）が未設定の場合、または
取得・集計に失敗した場合はサンプルデータ（design-demo の数値に準拠）を返す。

SmartHR API の構造:
- /departments: 部署（階層構造。full_name 例「販売部門/福岡エリア/春日店」）
- /crews: 従業員（department に所属部署の full_name 文字列を持つ）
- /payrolls: 給与の実行バッチ（payment_type=salary/bonus, status=fixed/wip）
- /payrolls/{id}/payslips: 給与明細（crew_id・allowances[支給]・deductions[控除]・attendances[勤怠]）
"""
import logging
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings
from app.services.cache_service import cached

logger = logging.getLogger(__name__)

# =============================================================================
# 定数
# =============================================================================

# 集計対象の部署バケット（ダッシュボードの表示名）
DEPARTMENTS: List[str] = ["店舗部門", "通販部門", "製造部門", "本社"]

# 人件費推移の対象月数（直近）
_TREND_MONTH_COUNT = 6

# 対象とする給与バッチの最大件数（直近14ヶ月分。当月＋前年同月＋推移をカバー）
_MAX_PAYROLLS = 14

# SmartHR API のタイムアウト（秒）
_API_TIMEOUT = 20.0

# 給与明細の支給項目のうち、人件費（総支給額）の集計から除外する項目。
# 「銀行振込」「現金支給額」は差引支給額の振込先内訳であり、加算すると二重計上になる。
_PAYOUT_EXCLUDE_KEYWORDS = ("銀行振込",)
_PAYOUT_EXCLUDE_NAMES = {"現金支給額"}

# 人件費推移のサンプル値（部署 → 月次の百万円）
_SAMPLE_TREND: Dict[str, List[float]] = {
    "店舗部門": [8.3, 8.4, 8.5, 8.6, 8.7, 8.9],
    "通販部門": [3.0, 3.1, 3.2, 3.2, 3.3, 3.4],
    "製造部門": [5.4, 5.5, 5.5, 5.6, 5.6, 5.7],
    "本社": [2.8, 2.8, 2.9, 2.9, 2.9, 2.9],
}
_SAMPLE_TREND_MONTHS: List[str] = ["11月", "12月", "1月", "2月", "3月", "4月"]

# 人件費のサンプル値（部署 → (当月, 前年同月)、百万円）
_SAMPLE_LABOR_COST: Dict[str, tuple] = {
    "店舗部門": (8.9, 8.2),
    "通販部門": (3.4, 3.1),
    "製造部門": (5.7, 5.5),
    "本社": (2.9, 2.8),
}

# 時間外労働のサンプル値（部署 → (当月, 前年同月)、時間/月）
_SAMPLE_OVERTIME: Dict[str, tuple] = {
    "店舗部門": (16.2, 18.5),
    "通販部門": (14.5, 12.0),
    "製造部門": (20.1, 22.3),
    "本社": (10.2, 9.5),
}


# =============================================================================
# ヘルパー
# =============================================================================

def _calc_yoy_rate(current: float, previous_year: float) -> float:
    """前年比（%）を計算する。前年が0の場合は0.0を返す。"""
    if previous_year == 0:
        return 0.0
    return round((current - previous_year) / previous_year * 100, 1)


def _bucket_for_department(full_name: str) -> Optional[str]:
    """
    SmartHRの部署 full_name をダッシュボードの4部門バケットに振り分ける。

    SmartHRの最上位部署は「販売部門」「製造部」「事務」。
    - 販売部門/... → 店舗部門
    - 製造部/...   → 製造部門
    - 事務/通販事業部 → 通販部門
    - 事務（その他、総務部など） → 本社
    """
    if not full_name:
        return None
    top = full_name.split("/")[0].strip()
    if top == "販売部門":
        return "店舗部門"
    if top == "製造部":
        return "製造部門"
    if top == "事務":
        return "通販部門" if "通販事業部" in full_name else "本社"
    return None


def _build_sample_summary() -> Dict[str, Any]:
    """design-demo の数値に準拠したサンプルサマリーを生成する。"""
    labor_costs = [
        {
            "department": dept,
            "current": current,
            "previous_year": previous,
            "yoy_rate": _calc_yoy_rate(current, previous),
        }
        for dept, (current, previous) in _SAMPLE_LABOR_COST.items()
    ]
    overtime = [
        {
            "department": dept,
            "current": current,
            "previous_year": previous,
            "yoy_rate": _calc_yoy_rate(current, previous),
        }
        for dept, (current, previous) in _SAMPLE_OVERTIME.items()
    ]
    labor_cost_trend = [
        {
            "month": month,
            "values": {dept: _SAMPLE_TREND[dept][idx] for dept in DEPARTMENTS},
        }
        for idx, month in enumerate(_SAMPLE_TREND_MONTHS)
    ]
    return {
        "labor_costs": labor_costs,
        "overtime": overtime,
        "labor_cost_trend": labor_cost_trend,
        "is_sample": True,
    }


# =============================================================================
# SmartHR API 呼び出し
# =============================================================================

def _api_base_url() -> str:
    """SmartHR API のベースURLを返す。"""
    return f"https://{settings.SMARTHR_SUBDOMAIN}.smarthr.jp/api/v1"


async def _fetch_all_pages(
    client: httpx.AsyncClient, endpoint: str, params: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """
    SmartHR API のページネーション（page / per_page）を辿り全件取得する。
    """
    results: List[Dict[str, Any]] = []
    page = 1
    per_page = 100

    while True:
        query: Dict[str, Any] = {"page": page, "per_page": per_page}
        if params:
            query.update(params)

        response = await client.get(endpoint, params=query)
        response.raise_for_status()
        batch = response.json()

        if not isinstance(batch, list) or not batch:
            break

        results.extend(batch)

        total_pages = response.headers.get("Total-Pages") or response.headers.get(
            "total-pages"
        )
        if total_pages is not None:
            try:
                if page >= int(total_pages):
                    break
            except (TypeError, ValueError):
                pass
        if len(batch) < per_page:
            break

        page += 1
        if page > 100:  # 過剰なリクエストを防ぐ安全弁
            break

    return results


def _payslip_gross(slip: Dict[str, Any]) -> float:
    """給与明細1件の総支給額（人件費）を算出する（支給項目の合計−振込内訳）。"""
    gross = 0.0
    for item in slip.get("allowances") or []:
        name = item.get("name") or ""
        if name in _PAYOUT_EXCLUDE_NAMES:
            continue
        if any(kw in name for kw in _PAYOUT_EXCLUDE_KEYWORDS):
            continue
        try:
            gross += float(item.get("amount") or 0)
        except (TypeError, ValueError):
            continue
    return gross


def _payslip_overtime(slip: Dict[str, Any]) -> float:
    """給与明細1件の時間外労働時間を算出する（勤怠の残業・休出時間の合計）。"""
    overtime = 0.0
    for item in slip.get("attendances") or []:
        name = item.get("name") or ""
        if "残業" in name or name == "休出時間":
            try:
                overtime += float(item.get("amount") or 0)
            except (TypeError, ValueError):
                continue
    return overtime


async def _fetch_smarthr_summary(target_month: Optional[str] = None) -> Dict[str, Any]:
    """
    SmartHR API から実データを取得し、部署別×月次に集計する。

    crews で従業員→部門バケットを引き、payrolls（給与・確定分）の payslips を
    部署別×月次に集計して人件費（総支給額）と時間外労働時間を求める。

    Returns:
        LaborSummaryResponse 相当の dict（is_sample=False）
    """
    headers = {
        "Authorization": f"Bearer {settings.SMARTHR_ACCESS_TOKEN}",
        "Accept": "application/json",
    }

    async with httpx.AsyncClient(
        base_url=_api_base_url(), headers=headers, timeout=_API_TIMEOUT
    ) as client:
        crews = await _fetch_all_pages(client, "/crews")
        payrolls = await _fetch_all_pages(client, "/payrolls")

        # 従業員ID → 部門バケット
        bucket_by_crew: Dict[str, str] = {}
        for crew in crews:
            crew_id = crew.get("id")
            if not crew_id:
                continue
            full_name = ""
            dep = crew.get("department")
            if isinstance(dep, str):
                full_name = dep
            if not full_name:
                for cd in crew.get("departments") or []:
                    if isinstance(cd, dict) and cd.get("full_name"):
                        full_name = cd["full_name"]
                        break
            bucket = _bucket_for_department(full_name)
            if bucket:
                bucket_by_crew[str(crew_id)] = bucket

        # 給与（payment_type=salary・status=fixed）のみを対象に、
        # 給与計算期間でdedup（同一期間は published_at が新しいものを採用）し直近分を選択
        by_period: Dict[str, Dict[str, Any]] = {}
        for p in payrolls:
            if p.get("payment_type") != "salary" or p.get("status") != "fixed":
                continue
            key = p.get("period_end_at") or p.get("paid_at")
            if not key:
                continue
            prev = by_period.get(key)
            if prev is None or (p.get("published_at") or "") > (
                prev.get("published_at") or ""
            ):
                by_period[key] = p
        selected = sorted(
            by_period.values(),
            key=lambda p: p.get("paid_at") or "",
            reverse=True,
        )[:_MAX_PAYROLLS]

        # 部署別×月次の集計バケット（月キー = 支給日 paid_at の YYYY-MM）
        cost: Dict[str, Dict[str, float]] = {d: {} for d in DEPARTMENTS}
        ot_sum: Dict[str, Dict[str, float]] = {d: {} for d in DEPARTMENTS}
        ot_cnt: Dict[str, Dict[str, int]] = {d: {} for d in DEPARTMENTS}

        for payroll in selected:
            month_key = str(payroll.get("paid_at") or "")[:7]
            if not month_key:
                continue
            payslips = await _fetch_all_pages(
                client, f"/payrolls/{payroll['id']}/payslips"
            )
            for slip in payslips:
                bucket = bucket_by_crew.get(str(slip.get("crew_id") or ""))
                if not bucket:
                    continue
                cost[bucket][month_key] = (
                    cost[bucket].get(month_key, 0.0) + _payslip_gross(slip)
                )
                ot_sum[bucket][month_key] = (
                    ot_sum[bucket].get(month_key, 0.0) + _payslip_overtime(slip)
                )
                ot_cnt[bucket][month_key] = ot_cnt[bucket].get(month_key, 0) + 1

    # 集計結果が空ならフォールバック
    if not any(cost[d] for d in DEPARTMENTS):
        raise ValueError("SmartHR から有効な給与明細データを取得できませんでした")

    # 月キー（YYYY-MM）を新しい順にソート
    all_months = sorted(
        {m for d in DEPARTMENTS for m in cost[d].keys()}, reverse=True
    )
    # 対象月: target_month 指定があり該当データがあればそれを優先、なければ最新月
    current_key = ""
    if target_month:
        tm = str(target_month)[:7]
        if tm in all_months:
            current_key = tm
    if not current_key:
        current_key = all_months[0] if all_months else ""
    previous_key = ""
    if current_key:
        year, _, month = current_key.partition("-")
        try:
            previous_key = f"{int(year) - 1}-{month}"
        except ValueError:
            previous_key = ""

    def _to_million(value: float) -> float:
        return round(value / 1_000_000, 1)

    labor_costs: List[Dict[str, Any]] = []
    overtime: List[Dict[str, Any]] = []

    for dept in DEPARTMENTS:
        cur_cost = _to_million(cost[dept].get(current_key, 0.0))
        prev_cost = _to_million(cost[dept].get(previous_key, 0.0))
        labor_costs.append(
            {
                "department": dept,
                "current": cur_cost,
                "previous_year": prev_cost,
                "yoy_rate": _calc_yoy_rate(cur_cost, prev_cost),
            }
        )

        cur_cnt = ot_cnt[dept].get(current_key, 0) or 1
        prev_cnt = ot_cnt[dept].get(previous_key, 0) or 1
        cur_ot = round(ot_sum[dept].get(current_key, 0.0) / cur_cnt, 1)
        prev_ot = round(ot_sum[dept].get(previous_key, 0.0) / prev_cnt, 1)
        overtime.append(
            {
                "department": dept,
                "current": cur_ot,
                "previous_year": prev_ot,
                "yoy_rate": _calc_yoy_rate(cur_ot, prev_ot),
            }
        )

    # 月次推移（対象月までの直近6ヶ月、古い順）
    trend_keys = sorted(m for m in all_months if m <= current_key)[
        -_TREND_MONTH_COUNT:
    ]
    labor_cost_trend: List[Dict[str, Any]] = []
    for key in trend_keys:
        _, _, month = key.partition("-")
        try:
            label = f"{int(month)}月"
        except ValueError:
            label = key
        labor_cost_trend.append(
            {
                "month": label,
                "values": {
                    dept: _to_million(cost[dept].get(key, 0.0))
                    for dept in DEPARTMENTS
                },
            }
        )

    return {
        "labor_costs": labor_costs,
        "overtime": overtime,
        "labor_cost_trend": labor_cost_trend,
        "is_sample": False,
    }


# =============================================================================
# 公開関数
# =============================================================================

@cached(prefix="hr", ttl=3600)
async def get_labor_summary(target_month: Optional[str] = None) -> Dict[str, Any]:
    """
    部署別 人件費・時間外サマリーを取得する。

    Args:
        target_month: 対象月（"YYYY-MM" 形式。未指定なら最新月）

    SmartHR連携が無効（認証情報未設定）の場合、または取得・集計に失敗した
    場合はサンプルデータ（is_sample=True）を返す。
    """
    if not settings.smarthr_enabled:
        logger.info("SmartHR連携が無効のためサンプルデータを返します")
        return _build_sample_summary()

    try:
        return await _fetch_smarthr_summary(target_month)
    except Exception as exc:  # noqa: BLE001 - 失敗時は必ずサンプルへフォールバック
        logger.warning(
            "SmartHR API からのデータ取得に失敗したためサンプルにフォールバックします: %s",
            exc,
        )
        return _build_sample_summary()
