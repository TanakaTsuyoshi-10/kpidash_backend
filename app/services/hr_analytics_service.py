"""
人事分析サービス（SmartHR連携）

SmartHR の従業員情報（crews）・給与明細（payslips）から、
店舗別の人員構成・在籍人数の推移・入退社・組織の健全性・
店舗別の人件費×売上を集計する。

個人を特定できる情報（氏名・個別給与など）は返さず、集計値のみを扱う。
SmartHR 連携が無効・取得失敗の場合は is_sample=True の空データを返す。
"""
import logging
from collections import Counter
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

import httpx
from supabase import Client

from app.core.config import settings
from app.services.cache_service import cached
from app.services.smarthr_service import _api_base_url, _fetch_all_pages, _payslip_gross, _payslip_overtime

logger = logging.getLogger(__name__)

_API_TIMEOUT = 30.0

# 雇用形態グループ（ダッシュボード表示用の4分類）
GROUP_FULLTIME = "正社員"
GROUP_CONTRACT = "契約社員"
GROUP_PARTTIME = "パート・アルバイト"
GROUP_UNSET = "未設定"
EMPLOYMENT_GROUPS = [GROUP_FULLTIME, GROUP_CONTRACT, GROUP_PARTTIME, GROUP_UNSET]

# 部門バケット（人数推移・組織指標用）
DEPT_STORE = "店舗部門"
DEPT_MFG = "製造部門"
DEPT_EC = "通販部門"
DEPT_HQ = "本社"
DEPT_UNSET = "部署未設定"
DEPARTMENT_BUCKETS = [DEPT_STORE, DEPT_MFG, DEPT_EC, DEPT_HQ, DEPT_UNSET]


# =============================================================================
# 分類ヘルパー
# =============================================================================

def _employment_group(crew: Dict[str, Any]) -> str:
    """雇用形態を4分類に束ねる。

    - 正社員: 正社員・役員
    - 契約社員: 契約社員・派遣社員・業務委託
    - パート・アルバイト: アルバイト・パート、パート（曜日限定）、契約パート、
      月15日出勤、週2日出勤、年末期間限定、その他
    - 未設定: 雇用形態が未登録
    """
    et = crew.get("employment_type")
    name = (et.get("name") if isinstance(et, dict) else et) or ""
    if not name:
        return GROUP_UNSET
    if name in ("正社員", "役員"):
        return GROUP_FULLTIME
    if name in ("契約社員", "派遣社員", "業務委託"):
        return GROUP_CONTRACT
    return GROUP_PARTTIME


def _crew_department_full_name(crew: Dict[str, Any]) -> str:
    dep = crew.get("department")
    if isinstance(dep, str) and dep:
        return dep
    for cd in crew.get("departments") or []:
        if isinstance(cd, dict) and cd.get("full_name"):
            return cd["full_name"]
    return ""


def _department_bucket(full_name: str) -> str:
    """部署 full_name を部門バケットへ振り分ける（smarthr_service と同じ規則）。"""
    if not full_name:
        return DEPT_UNSET
    top = full_name.split("/")[0].strip()
    if top == "販売部門":
        return DEPT_STORE
    if top == "製造部":
        return DEPT_MFG
    if top == "事務":
        return DEPT_EC if "通販事業部" in full_name else DEPT_HQ
    return DEPT_UNSET


def _store_name(full_name: str) -> Optional[str]:
    """「販売部門/エリア/店舗」の店舗名を返す（店舗未配属は None）。"""
    if not full_name:
        return None
    parts = [p.strip() for p in full_name.split("/")]
    if parts[0] != "販売部門":
        return None
    if len(parts) >= 3 and parts[2]:
        return parts[2]
    return None


def _parse_date(value: Any) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _month_end(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


def _is_employed_at(crew: Dict[str, Any], as_of: date) -> bool:
    """as_of 時点で在籍していたか（入社日・退職日から判定）。

    入社日未登録（役員など3名）は、在籍扱いの開始を不明として
    「退職日がない限り在籍」とみなす。
    """
    entered = _parse_date(crew.get("entered_at"))
    resigned = _parse_date(crew.get("resigned_at"))
    if entered and entered > as_of:
        return False
    if resigned and resigned <= as_of:
        return False
    return True


def _age_at(birth: date, as_of: date) -> int:
    return as_of.year - birth.year - (
        (as_of.month, as_of.day) < (birth.month, birth.day)
    )


# =============================================================================
# SmartHR データ取得（キャッシュ付き）
# =============================================================================

@cached(prefix="hr", ttl=1800)
async def _get_crews() -> List[Dict[str, Any]]:
    """従業員一覧を取得する（30分キャッシュ）。"""
    headers = {
        "Authorization": f"Bearer {settings.SMARTHR_ACCESS_TOKEN}",
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(
        base_url=_api_base_url(), headers=headers, timeout=_API_TIMEOUT
    ) as client:
        return await _fetch_all_pages(client, "/crews")


@cached(prefix="hr", ttl=1800)
async def _get_departments() -> List[Dict[str, Any]]:
    """部署一覧を取得する（30分キャッシュ）。エリア判定に使用。"""
    headers = {
        "Authorization": f"Bearer {settings.SMARTHR_ACCESS_TOKEN}",
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(
        base_url=_api_base_url(), headers=headers, timeout=_API_TIMEOUT
    ) as client:
        return await _fetch_all_pages(client, "/departments")


async def _area_by_segment(segment_names: List[str]) -> Dict[str, str]:
    """ダッシュボード店舗名 → エリア名（SmartHRの「販売部門/エリア/店舗」階層から）。"""
    try:
        departments = await _get_departments()
    except Exception as exc:  # noqa: BLE001
        logger.warning("SmartHR departments 取得に失敗: %s", exc)
        return {}
    out: Dict[str, str] = {}
    for d in departments:
        full = d.get("full_name") or ""
        parts = [x.strip() for x in full.split("/")]
        if len(parts) >= 3 and parts[0] == "販売部門" and parts[1] and parts[2]:
            seg = _match_segment(parts[2], segment_names) if segment_names else None
            out[seg or parts[2]] = parts[1]
    return out


def _sort_rows_by_area(
    rows: List[Dict[str, Any]], name_key: str, name_order: List[str]
) -> None:
    """行をエリアごとにまとめて並べ替える（エリア順・エリア内は店舗コード順）。"""
    idx = {n: i for i, n in enumerate(name_order)}
    area_first: Dict[str, int] = {}
    for r in rows:
        a = r.get("area") or "エリア未設定"
        i = idx.get(r[name_key], 9999)
        area_first[a] = min(area_first.get(a, 9999), i)
    rows.sort(
        key=lambda r: (
            area_first.get(r.get("area") or "エリア未設定", 9999),
            idx.get(r[name_key], 9999),
        )
    )


def _empty(is_sample: bool = True) -> Dict[str, Any]:
    return {"is_sample": is_sample}


# =============================================================================
# 1) 店舗別・部門別 所属人数（現在）
# =============================================================================

def _breakdown_row(name: str, crews: List[Dict[str, Any]]) -> Dict[str, Any]:
    counts = Counter(_employment_group(c) for c in crews)
    return {
        "name": name,
        "total": len(crews),
        "fulltime": counts.get(GROUP_FULLTIME, 0),
        "contract": counts.get(GROUP_CONTRACT, 0),
        "parttime": counts.get(GROUP_PARTTIME, 0),
        "unset": counts.get(GROUP_UNSET, 0),
    }


async def get_headcount_summary(supabase: Optional[Client] = None) -> Dict[str, Any]:
    """現在の在籍者を店舗別・部門別に雇用形態内訳つきで集計する。

    店舗はダッシュボードの全店舗（本社除く）を所属0名でも表示し、
    SmartHRの店舗名はダッシュボードの店舗名に名寄せする。
    """
    if not settings.smarthr_enabled:
        return {**_empty(), "stores": [], "others": [], "company": None, "as_of": None}
    try:
        crews = [c for c in await _get_crews() if c.get("emp_status") == "employed"]
    except Exception as exc:  # noqa: BLE001
        logger.warning("SmartHR crews 取得に失敗: %s", exc)
        return {**_empty(), "stores": [], "others": [], "company": None, "as_of": None}

    segment_names = _store_segment_names(supabase) if supabase else []

    by_store: Dict[str, List[Dict[str, Any]]] = {}
    others: Dict[str, List[Dict[str, Any]]] = {}
    for c in crews:
        full = _crew_department_full_name(c)
        store = _store_name(full)
        if store:
            by_store.setdefault(store, []).append(c)
            continue
        # 店舗以外は実際の部署名で認識する:
        # - 製造部はまとめて「製造部門」
        # - 事務配下は2階層目の部署名そのまま（通販事業部・総務部・庶務課など）
        # - 店舗部門でエリア止まり → 店舗部門（店舗未配属）
        top = full.split("/")[0].strip() if full else ""
        if not full:
            name = DEPT_UNSET
        elif top == "製造部":
            name = DEPT_MFG
        elif top == "事務":
            parts = [x.strip() for x in full.split("/")]
            name = parts[1] if len(parts) >= 2 and parts[1] else "事務（部署未設定）"
        elif top == "販売部門":
            name = "店舗部門（店舗未配属）"
        else:
            name = top
        others.setdefault(name, []).append(c)

    if segment_names:
        # SmartHR店舗名 → ダッシュボード店舗名に名寄せし、全店舗分の行を作る
        merged: Dict[str, List[Dict[str, Any]]] = {n: [] for n in segment_names}
        unmatched: Dict[str, List[Dict[str, Any]]] = {}
        for sm_name, members in by_store.items():
            seg = _match_segment(sm_name, segment_names)
            if seg:
                merged[seg].extend(members)
            else:
                unmatched[sm_name] = members
        stores = [_breakdown_row(name, merged[name]) for name in segment_names]
        stores += [
            _breakdown_row(name, members) for name, members in unmatched.items()
        ]
        area_map = await _area_by_segment(segment_names)
        for r in stores:
            r["area"] = area_map.get(r["name"])
        _sort_rows_by_area(stores, "name", segment_names)
    else:
        stores = [
            _breakdown_row(name, members)
            for name, members in sorted(
                by_store.items(), key=lambda kv: -len(kv[1])
            )
        ]
    # 製造部門 → 事務系部署（人数順）→ 店舗未配属 → 部署未設定 の順
    tail = ["店舗部門（店舗未配属）", DEPT_UNSET]
    middle = sorted(
        (n for n in others.keys() if n != DEPT_MFG and n not in tail),
        key=lambda n: -len(others[n]),
    )
    other_rows = [
        _breakdown_row(name, others[name])
        for name in [DEPT_MFG, *middle, *tail]
        if name in others
    ]

    return {
        "as_of": date.today().isoformat(),
        "stores": stores,
        "others": other_rows,
        "company": _breakdown_row("全社", crews),
        "is_sample": False,
    }


# =============================================================================
# 2) 在籍人数の推移（月次）
# =============================================================================

async def get_headcount_trend(months: int = 36) -> Dict[str, Any]:
    """月末時点の在籍人数を、雇用形態グループ別・部門別に遡って集計する。"""
    if not settings.smarthr_enabled:
        return {**_empty(), "months": [], "by_group": {}, "by_department": {}}
    try:
        crews = await _get_crews()
    except Exception as exc:  # noqa: BLE001
        logger.warning("SmartHR crews 取得に失敗: %s", exc)
        return {**_empty(), "months": [], "by_group": {}, "by_department": {}}

    today = date.today()
    month_keys: List[Tuple[int, int]] = []
    y, m = today.year, today.month
    for _ in range(months):
        month_keys.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    month_keys.reverse()

    labels = [f"{y}-{m:02d}" for y, m in month_keys]
    by_group: Dict[str, List[int]] = {g: [] for g in EMPLOYMENT_GROUPS}
    by_department: Dict[str, List[int]] = {d: [] for d in DEPARTMENT_BUCKETS}

    # 事前計算（毎月のループで再計算しない）
    enriched = [
        (
            c,
            _employment_group(c),
            _department_bucket(_crew_department_full_name(c)),
        )
        for c in crews
    ]

    for y, m in month_keys:
        eom = _month_end(y, m)
        g_counts: Counter = Counter()
        d_counts: Counter = Counter()
        for c, group, dept in enriched:
            if _is_employed_at(c, eom):
                g_counts[group] += 1
                d_counts[dept] += 1
        for g in EMPLOYMENT_GROUPS:
            by_group[g].append(g_counts.get(g, 0))
        for d in DEPARTMENT_BUCKETS:
            by_department[d].append(d_counts.get(d, 0))

    return {
        "months": labels,
        "by_group": by_group,
        "by_department": by_department,
        "is_sample": False,
    }


# =============================================================================
# 3) 入退社サマリー
# =============================================================================

async def get_turnover_summary(months: int = 12) -> Dict[str, Any]:
    """直近N ヶ月の入社・退職の動きと離職率・退職理由を集計する。"""
    if not settings.smarthr_enabled:
        return {
            **_empty(), "monthly": [], "hires_total": 0, "leavers_total": 0,
            "turnover_rate": None, "avg_headcount": None, "reasons": [],
        }
    try:
        crews = await _get_crews()
    except Exception as exc:  # noqa: BLE001
        logger.warning("SmartHR crews 取得に失敗: %s", exc)
        return {
            **_empty(), "monthly": [], "hires_total": 0, "leavers_total": 0,
            "turnover_rate": None, "avg_headcount": None, "reasons": [],
        }

    today = date.today()
    month_keys: List[Tuple[int, int]] = []
    y, m = today.year, today.month
    for _ in range(months):
        month_keys.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    month_keys.reverse()

    monthly = []
    headcounts = []
    window_start = date(month_keys[0][0], month_keys[0][1], 1)
    for y, m in month_keys:
        key = f"{y}-{m:02d}"
        hires = sum(
            1 for c in crews
            if (d := _parse_date(c.get("entered_at"))) and d.strftime("%Y-%m") == key
        )
        leavers = sum(
            1 for c in crews
            if (d := _parse_date(c.get("resigned_at"))) and d.strftime("%Y-%m") == key
        )
        monthly.append({"month": key, "hires": hires, "leavers": leavers})
        headcounts.append(
            sum(1 for c in crews if _is_employed_at(c, _month_end(y, m)))
        )

    leavers_total = sum(p["leavers"] for p in monthly)
    hires_total = sum(p["hires"] for p in monthly)
    avg_headcount = round(sum(headcounts) / len(headcounts), 1) if headcounts else None
    turnover_rate = (
        round(leavers_total / avg_headcount * 100, 1)
        if avg_headcount else None
    )

    # 退職理由（期間内に退職した人の理由の分布。理由未登録は「未登録」）
    reasons: Counter = Counter()
    for c in crews:
        resigned = _parse_date(c.get("resigned_at"))
        if resigned and resigned >= window_start:
            reason = (c.get("resigned_reason") or "").strip() or "未登録"
            reasons[reason] += 1

    return {
        "monthly": monthly,
        "hires_total": hires_total,
        "leavers_total": leavers_total,
        "avg_headcount": avg_headcount,
        "turnover_rate": turnover_rate,
        "reasons": [
            {"reason": r, "count": n}
            for r, n in reasons.most_common(8)
        ],
        "is_sample": False,
    }


# =============================================================================
# 4) 組織の健全性（平均年齢・勤続年数・年齢構成）
# =============================================================================

_AGE_BUCKETS = [(0, 19, "〜19歳"), (20, 29, "20代"), (30, 39, "30代"),
                (40, 49, "40代"), (50, 59, "50代"), (60, 69, "60代"),
                (70, 200, "70歳〜")]


async def get_org_health() -> Dict[str, Any]:
    """在籍者の平均年齢・平均勤続年数・年齢構成を全社／部門別に集計する。"""
    if not settings.smarthr_enabled:
        return {
            **_empty(), "avg_age": None, "avg_tenure_years": None,
            "age_distribution": [], "by_department": [],
        }
    try:
        crews = [c for c in await _get_crews() if c.get("emp_status") == "employed"]
    except Exception as exc:  # noqa: BLE001
        logger.warning("SmartHR crews 取得に失敗: %s", exc)
        return {
            **_empty(), "avg_age": None, "avg_tenure_years": None,
            "age_distribution": [], "by_department": [],
        }

    today = date.today()

    def _stats(members: List[Dict[str, Any]]) -> Tuple[Optional[float], Optional[float]]:
        ages = [
            _age_at(b, today) for c in members
            if (b := _parse_date(c.get("birth_at")))
        ]
        tenures = [
            (today - e).days / 365.25 for c in members
            if (e := _parse_date(c.get("entered_at")))
        ]
        avg_age = round(sum(ages) / len(ages), 1) if ages else None
        avg_tenure = round(sum(tenures) / len(tenures), 1) if tenures else None
        return avg_age, avg_tenure

    avg_age, avg_tenure = _stats(crews)

    dist: Counter = Counter()
    for c in crews:
        b = _parse_date(c.get("birth_at"))
        if not b:
            continue
        age = _age_at(b, today)
        for lo, hi, label in _AGE_BUCKETS:
            if lo <= age <= hi:
                dist[label] += 1
                break
    age_distribution = [
        {"label": label, "count": dist.get(label, 0)}
        for _, _, label in _AGE_BUCKETS
        if dist.get(label, 0) > 0 or label in ("20代", "30代", "40代", "50代", "60代")
    ]

    by_department = []
    for bucket in DEPARTMENT_BUCKETS:
        members = [
            c for c in crews
            if _department_bucket(_crew_department_full_name(c)) == bucket
        ]
        if not members:
            continue
        d_age, d_tenure = _stats(members)
        by_department.append({
            "department": bucket,
            "headcount": len(members),
            "avg_age": d_age,
            "avg_tenure_years": d_tenure,
        })

    return {
        "avg_age": avg_age,
        "avg_tenure_years": avg_tenure,
        "age_distribution": age_distribution,
        "by_department": by_department,
        "is_sample": False,
    }


# =============================================================================
# 5) 店舗別 人件費 × 売上
# =============================================================================

# 店舗別人件費×売上に通販事業部を1行として併載するためのキー
EC_LABOR_KEY = "通販事業部"


def _store_segment_names(supabase: Client) -> List[str]:
    """ダッシュボードの店舗一覧（本社除く・コード順）を返す。失敗時は空。"""
    try:
        dept = supabase.table("departments").select("id").eq("slug", "store").execute()
        if not dept.data:
            return []
        segs = (
            supabase.table("segments")
            .select("code, name")
            .eq("department_id", dept.data[0]["id"])
            .execute()
        ).data or []
        segs = [s for s in segs if s.get("name") != "本社"]
        try:
            segs.sort(key=lambda x: int(x["code"]))
        except (TypeError, ValueError):
            segs.sort(key=lambda x: str(x["code"]))
        return [s["name"] for s in segs]
    except Exception as exc:  # noqa: BLE001
        logger.warning("店舗セグメント取得に失敗: %s", exc)
        return []


def _match_segment(store: str, segment_names: List[str]) -> Optional[str]:
    """SmartHRの店舗名をダッシュボードの店舗（segment）名に対応づける。

    完全一致 → 片方がもう片方の末尾に一致（例: SmartHR「有田店」⇔「福岡有田店」）
    """
    if store in segment_names:
        return store
    for seg in segment_names:
        if seg.endswith(store) or store.endswith(seg):
            return seg
    return None


async def get_store_labor(supabase: Client, month: str) -> Dict[str, Any]:
    """店舗別の人件費・残業を売上と結合する。

    - 人件費・残業: 支給月（paid_at）が対象月の給与明細を店舗別に集計
    - 売上: kpi_values（実績）の店舗別売上高
    - 人件費率 = 人件費 ÷ 売上、1人あたり売上 = 売上 ÷ 月末在籍数
    """
    month_key = str(month)[:7]
    try:
        y, m = int(month_key[:4]), int(month_key[5:7])
    except ValueError:
        raise ValueError("month は YYYY-MM または YYYY-MM-DD 形式で指定してください")
    prev_key = f"{y - 1}-{m:02d}"
    month_iso = f"{month_key}-01"

    if not settings.smarthr_enabled:
        return {**_empty(), "month": month_key, "rows": [], "total": None,
                "unmatched_stores": []}

    headers = {
        "Authorization": f"Bearer {settings.SMARTHR_ACCESS_TOKEN}",
        "Accept": "application/json",
    }
    try:
        crews = await _get_crews()
        async with httpx.AsyncClient(
            base_url=_api_base_url(), headers=headers, timeout=_API_TIMEOUT
        ) as client:
            payrolls = await _fetch_all_pages(client, "/payrolls")

            # 対象月・前年同月の給与バッチ（salary・fixed、同一期間は新しい公開分）
            by_period: Dict[str, Dict[str, Any]] = {}
            for p in payrolls:
                if p.get("payment_type") != "salary" or p.get("status") != "fixed":
                    continue
                paid_month = str(p.get("paid_at") or "")[:7]
                if paid_month not in (month_key, prev_key):
                    continue
                key = p.get("period_end_at") or p.get("paid_at")
                prev = by_period.get(key)
                if prev is None or (p.get("published_at") or "") > (
                    prev.get("published_at") or ""
                ):
                    by_period[key] = p

            # 従業員 → 集計キー（店舗名 or 通販事業部。その他は None=対象外）
            def _labor_key(full: str) -> Optional[str]:
                store = _store_name(full)
                if store:
                    return store
                if full and "通販事業部" in full:
                    return EC_LABOR_KEY
                return None

            store_by_crew: Dict[str, Optional[str]] = {
                str(c.get("id")): _labor_key(_crew_department_full_name(c))
                for c in crews
            }

            cost: Dict[str, Dict[str, float]] = {}
            ot: Dict[str, Dict[str, float]] = {}
            slips_cnt: Dict[str, Dict[str, int]] = {}
            for payroll in by_period.values():
                pm = str(payroll.get("paid_at") or "")[:7]
                payslips = await _fetch_all_pages(
                    client, f"/payrolls/{payroll['id']}/payslips"
                )
                for slip in payslips:
                    store = store_by_crew.get(str(slip.get("crew_id") or ""))
                    if not store:
                        continue  # 店舗・通販事業部以外（製造・総務等）は対象外
                    cost.setdefault(store, {})
                    ot.setdefault(store, {})
                    slips_cnt.setdefault(store, {})
                    cost[store][pm] = cost[store].get(pm, 0.0) + _payslip_gross(slip)
                    ot[store][pm] = ot[store].get(pm, 0.0) + _payslip_overtime(slip)
                    slips_cnt[store][pm] = slips_cnt[store].get(pm, 0) + 1
    except Exception as exc:  # noqa: BLE001
        logger.warning("SmartHR 店舗別人件費の取得に失敗: %s", exc)
        return {**_empty(), "month": month_key, "rows": [], "total": None,
                "unmatched_stores": []}

    # 店舗別売上（実績）
    sales_by_segment: Dict[str, float] = {}
    segment_names: List[str] = []
    ordered_store_names: List[str] = []
    try:
        dept = supabase.table("departments").select("id").eq("slug", "store").execute()
        if dept.data:
            segs = (
                supabase.table("segments")
                .select("id, code, name")
                .eq("department_id", dept.data[0]["id"])
                .execute()
            ).data or []
            segment_names = [s["name"] for s in segs]
            store_segs = [s for s in segs if s.get("name") != "本社"]
            try:
                store_segs.sort(key=lambda x: int(x["code"]))
            except (TypeError, ValueError):
                store_segs.sort(key=lambda x: str(x["code"]))
            ordered_store_names = [s["name"] for s in store_segs]
            kpi = (
                supabase.table("kpi_definitions")
                .select("id")
                .eq("department_id", dept.data[0]["id"])
                .eq("name", "売上高")
                .limit(1)
                .execute()
            ).data
            if kpi and segs:
                values = (
                    supabase.table("kpi_values")
                    .select("segment_id, value")
                    .eq("kpi_id", kpi[0]["id"])
                    .eq("date", month_iso)
                    .eq("is_target", False)
                    .in_("segment_id", [s["id"] for s in segs])
                    .execute()
                ).data or []
                name_by_id = {s["id"]: s["name"] for s in segs}
                for v in values:
                    name = name_by_id.get(v["segment_id"])
                    if name:
                        sales_by_segment[name] = float(v["value"] or 0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("店舗別売上の取得に失敗: %s", exc)

    # 通販売上（実績・チャネル合計）
    ec_sales: Optional[float] = None
    try:
        ec_rows = (
            supabase.table("ecommerce_channel_sales")
            .select("sales")
            .eq("month", month_iso)
            .eq("is_target", False)
            .execute()
        ).data or []
        if ec_rows:
            ec_sales = sum(float(r.get("sales") or 0) for r in ec_rows)
    except Exception as exc:  # noqa: BLE001
        logger.warning("通販売上の取得に失敗: %s", exc)

    # 月末在籍数（店舗・通販事業部別）
    eom = _month_end(y, m)
    headcount_by_store: Counter = Counter()
    for c in crews:
        full = _crew_department_full_name(c)
        key = _store_name(full) or (EC_LABOR_KEY if full and "通販事業部" in full else None)
        if key and _is_employed_at(c, eom):
            headcount_by_store[key] += 1

    def _yoy(cur: float, prev: float) -> Optional[float]:
        if not prev:
            return None
        return round((cur - prev) / prev * 100, 1)

    def _make_row(
        display: str,
        data_keys: List[str],
        sales: Optional[float],
    ) -> Dict[str, Any]:
        c_cur = round(sum(cost.get(k, {}).get(month_key, 0.0) for k in data_keys))
        c_prev = round(sum(cost.get(k, {}).get(prev_key, 0.0) for k in data_keys))
        headcount = sum(headcount_by_store.get(k, 0) for k in data_keys)
        cnt = sum(slips_cnt.get(k, {}).get(month_key, 0) for k in data_keys)
        ot_total = sum(ot.get(k, {}).get(month_key, 0.0) for k in data_keys)
        return {
            "store": display,
            "headcount": headcount,
            "labor_cost": c_cur,
            "labor_cost_prev_year": c_prev,
            "labor_cost_yoy": _yoy(c_cur, c_prev),
            "sales": round(sales) if sales is not None else None,
            "labor_cost_ratio": (
                round(c_cur / sales * 100, 1) if sales else None
            ),
            "sales_per_head": (
                round(sales / headcount) if sales and headcount else None
            ),
            "overtime_per_head": (
                round(ot_total / cnt, 1) if cnt else None
            ),
        }

    smarthr_keys = sorted(
        (cost.keys() | set(headcount_by_store.keys())) - {EC_LABOR_KEY}
    )
    rows = []
    unmatched = []
    if ordered_store_names:
        # ダッシュボードの全店舗を表示（SmartHRにデータがない店舗も0で出す）
        keys_by_segment: Dict[str, List[str]] = {n: [] for n in ordered_store_names}
        for k in smarthr_keys:
            seg = _match_segment(k, ordered_store_names)
            if seg:
                keys_by_segment[seg].append(k)
            else:
                unmatched.append(k)
        for seg_name in ordered_store_names:
            rows.append(
                _make_row(seg_name, keys_by_segment[seg_name], sales_by_segment.get(seg_name))
            )
        for k in unmatched:
            rows.append(_make_row(k, [k], None))
        # エリアごとにまとめて表示（エリア内は店舗コード順）
        area_map = await _area_by_segment(ordered_store_names)
        for r in rows:
            r["area"] = area_map.get(r["store"])
        _sort_rows_by_area(rows, "store", ordered_store_names)
    else:
        for k in smarthr_keys:
            seg_name = _match_segment(k, segment_names)
            if seg_name is None and segment_names:
                unmatched.append(k)
            rows.append(
                _make_row(seg_name or k, [k], sales_by_segment.get(seg_name) if seg_name else None)
            )
        rows.sort(key=lambda r: -(r["sales"] or -1))

    # 通販事業部の行（人件費=通販事業部所属の給与、売上=通販チャネル合計）
    if (
        EC_LABOR_KEY in cost
        or headcount_by_store.get(EC_LABOR_KEY)
        or ec_sales is not None
    ):
        rows.append(_make_row(EC_LABOR_KEY, [EC_LABOR_KEY], ec_sales))

    total_cost = sum(r["labor_cost"] for r in rows)
    total_prev = sum(r["labor_cost_prev_year"] for r in rows)
    total_sales = sum(r["sales"] for r in rows if r["sales"] is not None)
    total_head = sum(r["headcount"] for r in rows)
    total = {
        "store": "合計",
        "headcount": total_head,
        "labor_cost": total_cost,
        "labor_cost_prev_year": total_prev,
        "labor_cost_yoy": _yoy(total_cost, total_prev),
        "sales": total_sales or None,
        "labor_cost_ratio": (
            round(total_cost / total_sales * 100, 1) if total_sales else None
        ),
        "sales_per_head": (
            round(total_sales / total_head) if total_sales and total_head else None
        ),
        "overtime_per_head": None,
    }

    return {
        "month": month_key,
        "rows": rows,
        "total": total,
        "unmatched_stores": unmatched,
        "is_sample": False,
    }
