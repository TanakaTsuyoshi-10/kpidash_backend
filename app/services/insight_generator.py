"""
ルールベース洞察生成サービス

ハイライト（毎日変わる3〜4件のテキスト洞察）と
インサイト（好調/注意/要対応の分類付きリスト）を生成する。
"""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Any

from supabase import Client

from app.schemas.insights import (
    HighlightItem,
    HighlightResponse,
    InsightItem,
    InsightsResponse,
    DataFreshnessResponse,
)
from app.services.cache_service import cached


# =============================================================================
# ハイライト生成
# =============================================================================

@cached(prefix="highlights", ttl=300)
async def generate_highlights(supabase: Client) -> HighlightResponse:
    """今日のハイライトを生成する（TTL 300秒）"""
    today = date.today()
    yesterday = today - timedelta(days=1)
    items: List[HighlightItem] = []

    # H1: 昨日の全店売上
    h1 = await _highlight_yesterday_sales(supabase, yesterday)
    if h1:
        items.append(h1)

    # H2: 今月トップ店舗
    h2 = await _highlight_top_store(supabase, today)
    if h2:
        items.append(h2)

    # H3: EC注目チャネル
    h3 = await _highlight_ec_channel(supabase, today)
    if h3:
        items.append(h3)

    # H4: 連続前年割れ警告
    h4 = await _highlight_consecutive_decline(supabase, yesterday)
    if h4:
        items.append(h4)

    # H5: 客数×客単価分解
    h5 = await _highlight_customer_decomposition(supabase, today)
    if h5:
        items.append(h5)

    # H8: 売上目標ペース
    h8 = await _highlight_goal_pace(supabase, today)
    if h8:
        items.append(h8)

    # 最大4件に絞る
    items = items[:4]

    # データ鮮度ラベル
    freshness_label = await _get_store_freshness_label(supabase)

    return HighlightResponse(
        date=today.isoformat(),
        items=items,
        data_freshness=freshness_label,
    )


async def _highlight_yesterday_sales(
    supabase: Client, yesterday: date
) -> Optional[HighlightItem]:
    """H1: 昨日の全店売上"""
    try:
        # 昨日の全店舗売上を合算
        response = supabase.table("hourly_sales").select(
            "total_sales"
        ).eq("date", yesterday.isoformat()).execute()

        if not response.data:
            return None

        total = sum(
            Decimal(str(r["total_sales"]))
            for r in response.data
            if r.get("total_sales") is not None
        )

        if total == 0:
            return None

        # 前年同曜日
        prev_year_date = _previous_year_same_weekday(yesterday)
        prev_response = supabase.table("hourly_sales").select(
            "total_sales"
        ).eq("date", prev_year_date.isoformat()).execute()

        prev_total = Decimal("0")
        if prev_response.data:
            prev_total = sum(
                Decimal(str(r["total_sales"]))
                for r in prev_response.data
                if r.get("total_sales") is not None
            )

        # テキスト生成
        total_man = (total / 10000).quantize(Decimal("1"), rounding=ROUND_HALF_UP)

        if prev_total and prev_total > 0:
            yoy = ((total - prev_total) / prev_total * 100).quantize(
                Decimal("0.1"), rounding=ROUND_HALF_UP
            )
            sign = "+" if yoy > 0 else ""
            text = f"昨日の全店売上は{total_man}万円（前年同曜日比{sign}{yoy}%）"
            severity = "good" if yoy > 0 else "warning" if yoy > -5 else "critical"
        else:
            text = f"昨日の全店売上は{total_man}万円"
            severity = "info"

        return HighlightItem(
            icon="TrendingUp",
            text=text,
            severity=severity,
            link="/products",
        )
    except Exception:
        return None


async def _highlight_top_store(
    supabase: Client, today: date
) -> Optional[HighlightItem]:
    """H2: 今月トップ店舗"""
    try:
        month_start = date(today.year, today.month, 1)

        # 今月の日次売上を店舗別に集計
        response = supabase.table("hourly_sales").select(
            "segment_id, total_sales"
        ).gte("date", month_start.isoformat()).lte(
            "date", today.isoformat()
        ).execute()

        if not response.data:
            return None

        # 店舗別集計
        store_totals: Dict[str, Decimal] = {}
        for r in response.data:
            sid = r.get("segment_id")
            sales = r.get("total_sales")
            if sid and sales is not None:
                store_totals[sid] = store_totals.get(sid, Decimal("0")) + Decimal(str(sales))

        if not store_totals:
            return None

        # トップ店舗
        top_sid = max(store_totals, key=store_totals.get)  # type: ignore
        top_sales = store_totals[top_sid]

        # 店舗名を取得
        seg_response = supabase.table("segments").select("name").eq(
            "id", top_sid
        ).execute()
        store_name = seg_response.data[0]["name"] if seg_response.data else "不明"

        # 前年同月
        prev_month_start = date(today.year - 1, today.month, 1)
        prev_response = supabase.table("hourly_sales").select(
            "total_sales"
        ).eq("segment_id", top_sid).gte(
            "date", prev_month_start.isoformat()
        ).lte(
            "date", date(today.year - 1, today.month, today.day).isoformat()
        ).execute()

        prev_total = Decimal("0")
        if prev_response.data:
            prev_total = sum(
                Decimal(str(r["total_sales"]))
                for r in prev_response.data
                if r.get("total_sales") is not None
            )

        if prev_total and prev_total > 0:
            yoy = ((top_sales - prev_total) / prev_total * 100).quantize(
                Decimal("0.1"), rounding=ROUND_HALF_UP
            )
            sign = "+" if yoy > 0 else ""
            text = f"{store_name}が今月トップ。前年比{sign}{yoy}%"
            severity = "good" if yoy > 0 else "info"
        else:
            top_man = (top_sales / 10000).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            text = f"{store_name}が今月トップ（{top_man}万円）"
            severity = "info"

        return HighlightItem(
            icon="Trophy",
            text=text,
            severity=severity,
            link="/products",
        )
    except Exception:
        return None


async def _highlight_ec_channel(
    supabase: Client, today: date
) -> Optional[HighlightItem]:
    """H3: EC注目チャネル（前年比が最も高いチャネル）"""
    try:
        # 最新の通販データ月を取得
        month_start = date(today.year, today.month, 1)
        response = supabase.table("ecommerce_channel_sales").select(
            "channel, sales"
        ).eq("month", month_start.isoformat()).execute()

        if not response.data:
            # 前月を試す
            if today.month == 1:
                month_start = date(today.year - 1, 12, 1)
            else:
                month_start = date(today.year, today.month - 1, 1)
            response = supabase.table("ecommerce_channel_sales").select(
                "channel, sales"
            ).eq("month", month_start.isoformat()).execute()

        if not response.data:
            return None

        # 前年同月
        prev_month = date(month_start.year - 1, month_start.month, 1)
        prev_response = supabase.table("ecommerce_channel_sales").select(
            "channel, sales"
        ).eq("month", prev_month.isoformat()).execute()

        prev_by_ch: Dict[str, Decimal] = {}
        if prev_response.data:
            for r in prev_response.data:
                ch = r.get("channel")
                s = r.get("sales")
                if ch and s is not None:
                    prev_by_ch[ch] = Decimal(str(s))

        # 最も前年比が高いチャネルを見つける
        best_ch = None
        best_yoy = Decimal("-999")

        for r in response.data:
            ch = r.get("channel")
            s = r.get("sales")
            if ch and s is not None and ch in prev_by_ch and prev_by_ch[ch] > 0:
                current = Decimal(str(s))
                prev = prev_by_ch[ch]
                yoy = ((current - prev) / prev * 100).quantize(
                    Decimal("0.1"), rounding=ROUND_HALF_UP
                )
                if yoy > best_yoy:
                    best_yoy = yoy
                    best_ch = ch

        if best_ch is None or best_yoy <= 0:
            return None

        text = f"{best_ch}が前年比+{best_yoy}%と好調"
        return HighlightItem(
            icon="ShoppingCart",
            text=text,
            severity="good",
            link="/ecommerce",
        )
    except Exception:
        return None


async def _highlight_consecutive_decline(
    supabase: Client, yesterday: date
) -> Optional[HighlightItem]:
    """H4: 連続前年割れ警告（5日以上連続前年割れの店舗）"""
    try:
        # 過去10日分のデータを取得
        start = yesterday - timedelta(days=9)

        response = supabase.table("hourly_sales").select(
            "date, segment_id, total_sales"
        ).gte("date", start.isoformat()).lte(
            "date", yesterday.isoformat()
        ).execute()

        if not response.data:
            return None

        # 日別・店舗別に集計
        daily_store: Dict[str, Dict[str, Decimal]] = {}
        for r in response.data:
            d = r.get("date")
            sid = r.get("segment_id")
            sales = r.get("total_sales")
            if d and sid and sales is not None:
                if d not in daily_store:
                    daily_store[d] = {}
                daily_store[d][sid] = daily_store[d].get(sid, Decimal("0")) + Decimal(str(sales))

        # 前年同曜日のデータを取得
        prev_start = _previous_year_same_weekday(start)
        prev_end = _previous_year_same_weekday(yesterday)
        prev_response = supabase.table("hourly_sales").select(
            "date, segment_id, total_sales"
        ).gte("date", prev_start.isoformat()).lte(
            "date", prev_end.isoformat()
        ).execute()

        prev_daily_store: Dict[str, Dict[str, Decimal]] = {}
        if prev_response.data:
            for r in prev_response.data:
                d = r.get("date")
                sid = r.get("segment_id")
                sales = r.get("total_sales")
                if d and sid and sales is not None:
                    if d not in prev_daily_store:
                        prev_daily_store[d] = {}
                    prev_daily_store[d][sid] = prev_daily_store[d].get(sid, Decimal("0")) + Decimal(str(sales))

        # 全店舗IDを収集
        all_sids = set()
        for stores in daily_store.values():
            all_sids.update(stores.keys())

        # 各店舗の連続前年割れ日数を計算（直近から遡る）
        worst_sid = None
        worst_streak = 0

        sorted_dates = sorted(daily_store.keys(), reverse=True)

        for sid in all_sids:
            streak = 0
            for d in sorted_dates:
                current = daily_store.get(d, {}).get(sid)
                prev_d = _previous_year_same_weekday(date.fromisoformat(d)).isoformat()
                prev = prev_daily_store.get(prev_d, {}).get(sid)

                if current is not None and prev is not None and prev > 0 and current < prev:
                    streak += 1
                else:
                    break

            if streak >= 5 and streak > worst_streak:
                worst_streak = streak
                worst_sid = sid

        if worst_sid is None:
            return None

        # 店舗名を取得
        seg_response = supabase.table("segments").select("name").eq(
            "id", worst_sid
        ).execute()
        store_name = seg_response.data[0]["name"] if seg_response.data else "不明"

        text = f"{store_name}は{worst_streak}日連続前年割れ"
        return HighlightItem(
            icon="AlertTriangle",
            text=text,
            severity="critical",
            link="/products",
        )
    except Exception:
        return None


async def _highlight_customer_decomposition(
    supabase: Client, today: date
) -> Optional[HighlightItem]:
    """H5: 客数×客単価分解"""
    try:
        # 店舗部門のIDを取得
        dept_response = supabase.table("departments").select("id").eq(
            "slug", "store"
        ).execute()
        if not dept_response.data:
            return None
        department_id = dept_response.data[0]["id"]

        # KPI定義から客数・売上高を取得
        kpi_response = supabase.table("kpi_definitions").select(
            "id, name"
        ).eq("department_id", department_id).in_(
            "name", ["客数", "売上高"]
        ).execute()
        if not kpi_response.data:
            return None

        kpi_ids = {row["name"]: row["id"] for row in kpi_response.data}

        # セグメントIDを取得
        segment_response = supabase.table("segments").select("id").eq(
            "department_id", department_id
        ).execute()
        if not segment_response.data:
            return None
        segment_ids = [s["id"] for s in segment_response.data]

        # 今月の期間
        month_start = date(today.year, today.month, 1)
        month_end = date(today.year, today.month + 1, 1) - timedelta(days=1) if today.month < 12 else date(today.year, 12, 31)

        # 今月のKPI値を取得
        values_response = supabase.table("kpi_values").select(
            "kpi_id, value"
        ).in_("segment_id", segment_ids).gte(
            "date", month_start.isoformat()
        ).lte(
            "date", month_end.isoformat()
        ).eq("is_target", False).execute()

        if not values_response.data:
            return None

        customer_kpi_id = kpi_ids.get("客数")
        sales_kpi_id = kpi_ids.get("売上高")

        curr_customers = Decimal("0")
        curr_sales = Decimal("0")
        for r in values_response.data:
            if r.get("value") is not None:
                if r["kpi_id"] == customer_kpi_id:
                    curr_customers += Decimal(str(r["value"]))
                elif r["kpi_id"] == sales_kpi_id:
                    curr_sales += Decimal(str(r["value"]))

        # 前年同月
        prev_month_start = date(today.year - 1, today.month, 1)
        prev_month_end = date(today.year - 1, today.month + 1, 1) - timedelta(days=1) if today.month < 12 else date(today.year - 1, 12, 31)

        prev_response = supabase.table("kpi_values").select(
            "kpi_id, value"
        ).in_("segment_id", segment_ids).gte(
            "date", prev_month_start.isoformat()
        ).lte(
            "date", prev_month_end.isoformat()
        ).eq("is_target", False).execute()

        prev_customers = Decimal("0")
        prev_sales = Decimal("0")
        if prev_response.data:
            for r in prev_response.data:
                if r.get("value") is not None:
                    if r["kpi_id"] == customer_kpi_id:
                        prev_customers += Decimal(str(r["value"]))
                    elif r["kpi_id"] == sales_kpi_id:
                        prev_sales += Decimal(str(r["value"]))

        if prev_customers == 0 or curr_customers == 0:
            return None

        # 客単価を算出
        curr_unit = curr_sales / curr_customers if curr_customers > 0 else Decimal("0")
        prev_unit = prev_sales / prev_customers if prev_customers > 0 else Decimal("0")

        # 前年比
        cust_yoy = ((curr_customers - prev_customers) / prev_customers * 100).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        )
        unit_yoy = ((curr_unit - prev_unit) / prev_unit * 100).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        ) if prev_unit > 0 else Decimal("0")

        # テンプレート選択
        cust_sign = "+" if cust_yoy > 0 else ""
        unit_sign = "+" if unit_yoy > 0 else ""

        if cust_yoy < 0 and unit_yoy > 0:
            text = f"客数減({cust_sign}{cust_yoy}%)を客単価上昇({unit_sign}{unit_yoy}%)でカバー"
            severity = "info"
        elif cust_yoy > 0 and unit_yoy > 0:
            text = f"客数({cust_sign}{cust_yoy}%)・客単価({unit_sign}{unit_yoy}%)ともに好調"
            severity = "good"
        elif cust_yoy < 0 and unit_yoy < 0:
            text = f"客数({cust_sign}{cust_yoy}%)・客単価({unit_sign}{unit_yoy}%)ともに低下"
            severity = "critical"
        else:
            text = f"客数{cust_sign}{cust_yoy}%、客単価{unit_sign}{unit_yoy}%"
            severity = "info"

        return HighlightItem(
            icon="Users",
            text=text,
            severity=severity,
            link="/products",
        )
    except Exception:
        return None


async def _highlight_goal_pace(
    supabase: Client, today: date
) -> Optional[HighlightItem]:
    """H8: 売上目標ペース"""
    try:
        month_start = date(today.year, today.month, 1)
        if today.month == 12:
            month_end = date(today.year + 1, 1, 1) - timedelta(days=1)
        else:
            month_end = date(today.year, today.month + 1, 1) - timedelta(days=1)

        total_days = (month_end - month_start).days + 1
        elapsed_days = (today - month_start).days + 1
        remaining_days = total_days - elapsed_days

        # 今月の累計売上（hourly_sales）
        response = supabase.table("hourly_sales").select(
            "total_sales"
        ).gte("date", month_start.isoformat()).lte(
            "date", today.isoformat()
        ).execute()

        if not response.data:
            return None

        actual = sum(
            Decimal(str(r["total_sales"]))
            for r in response.data
            if r.get("total_sales") is not None
        )

        # 月間目標（financial_data の is_target=True から店舗売上目標を取得）
        target_response = supabase.table("financial_data").select(
            "sales_store"
        ).eq("month", month_start.isoformat()).eq("is_target", True).execute()

        if not target_response.data or not target_response.data[0].get("sales_store"):
            return None

        target = Decimal(str(target_response.data[0]["sales_store"]))
        if target <= 0:
            return None

        rate = (actual / target * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        progress_rate = Decimal(str(elapsed_days / total_days * 100)).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        )

        if rate < progress_rate:
            gap = target - actual
            gap_man = (gap / 10000).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            text = f"目標達成率{rate}%（残り{remaining_days}日で{gap_man}万円が必要）"
            severity = "warning"
        else:
            text = f"目標達成率{rate}%（進捗率{progress_rate}%を上回るペース）"
            severity = "good"

        return HighlightItem(
            icon="Target",
            text=text,
            severity=severity,
            link="/targets",
        )
    except Exception:
        return None


async def _get_store_freshness_label(supabase: Client) -> str:
    """店舗データの鮮度ラベルを生成"""
    try:
        response = supabase.table("hourly_sales").select(
            "date"
        ).order("date", desc=True).limit(1).execute()

        if response.data:
            latest = date.fromisoformat(response.data[0]["date"])
            today = date.today()
            diff = (today - latest).days

            if diff == 0:
                return "今日"
            elif diff == 1:
                return "昨日"
            else:
                return f"{diff}日前"
        return "データなし"
    except Exception:
        return "不明"


# =============================================================================
# インサイト生成
# =============================================================================

@cached(prefix="insights", ttl=120)
async def generate_insights(supabase: Client) -> InsightsResponse:
    """注目ポイントを生成する（TTL 120秒）"""
    today = date.today()
    period = today.strftime("%Y-%m")
    items: List[InsightItem] = []

    # I1/I2: 店舗別YoY
    store_insights = await _insight_store_yoy(supabase, today)
    items.extend(store_insights)

    # I3/I4: ECチャネル
    ec_insights = await _insight_ec_channels(supabase, today)
    items.extend(ec_insights)

    # I5/I6: クレーム
    complaint_insights = await _insight_complaints(supabase, today)
    items.extend(complaint_insights)

    # I7: 営業利益悪化
    profit_insight = await _insight_operating_profit(supabase, today)
    if profit_insight:
        items.append(profit_insight)

    # 重要度でソート: critical > warning > good
    severity_order = {"critical": 0, "warning": 1, "good": 2}
    items.sort(key=lambda x: severity_order.get(x.severity, 3))

    return InsightsResponse(
        period=period,
        items=items,
    )


async def _insight_store_yoy(
    supabase: Client, today: date
) -> List[InsightItem]:
    """I1/I2: 店舗別前年比"""
    items = []
    try:
        month_start = date(today.year, today.month, 1)

        response = supabase.table("hourly_sales").select(
            "segment_id, total_sales"
        ).gte("date", month_start.isoformat()).lte(
            "date", today.isoformat()
        ).execute()

        if not response.data:
            return items

        # 店舗別集計
        store_totals: Dict[str, Decimal] = {}
        for r in response.data:
            sid = r.get("segment_id")
            sales = r.get("total_sales")
            if sid and sales is not None:
                store_totals[sid] = store_totals.get(sid, Decimal("0")) + Decimal(str(sales))

        # 前年同月
        prev_month_start = date(today.year - 1, today.month, 1)
        prev_response = supabase.table("hourly_sales").select(
            "segment_id, total_sales"
        ).gte("date", prev_month_start.isoformat()).lte(
            "date", date(today.year - 1, today.month, min(today.day, 28)).isoformat()
        ).execute()

        prev_totals: Dict[str, Decimal] = {}
        if prev_response.data:
            for r in prev_response.data:
                sid = r.get("segment_id")
                sales = r.get("total_sales")
                if sid and sales is not None:
                    prev_totals[sid] = prev_totals.get(sid, Decimal("0")) + Decimal(str(sales))

        # 店舗名を一括取得
        all_sids = list(store_totals.keys())
        if not all_sids:
            return items

        seg_response = supabase.table("segments").select("id, name").in_(
            "id", all_sids
        ).execute()
        name_map = {s["id"]: s["name"] for s in (seg_response.data or [])}

        # YoYを計算して分類
        for sid, current in store_totals.items():
            prev = prev_totals.get(sid)
            if prev and prev > 0:
                yoy = ((current - prev) / prev * 100).quantize(
                    Decimal("0.1"), rounding=ROUND_HALF_UP
                )
                name = name_map.get(sid, "不明")

                if yoy > 15:
                    items.append(InsightItem(
                        category="good",
                        severity="good",
                        text=f"{name}が前年比+{yoy}%と好調",
                        link="/products",
                    ))
                elif yoy < -10:
                    items.append(InsightItem(
                        category="warning",
                        severity="warning" if yoy > -20 else "critical",
                        text=f"{name}が前年比{yoy}%で要注意",
                        link="/products",
                    ))
    except Exception:
        pass

    return items


async def _insight_ec_channels(
    supabase: Client, today: date
) -> List[InsightItem]:
    """I3/I4: ECチャネル"""
    items = []
    try:
        month_start = date(today.year, today.month, 1)

        response = supabase.table("ecommerce_channel_sales").select(
            "channel, sales, sales_target"
        ).eq("month", month_start.isoformat()).execute()

        if not response.data:
            # 前月を試す
            if today.month == 1:
                month_start = date(today.year - 1, 12, 1)
            else:
                month_start = date(today.year, today.month - 1, 1)
            response = supabase.table("ecommerce_channel_sales").select(
                "channel, sales, sales_target"
            ).eq("month", month_start.isoformat()).execute()

        if not response.data:
            return items

        # 前年同月
        prev_month = date(month_start.year - 1, month_start.month, 1)
        prev_response = supabase.table("ecommerce_channel_sales").select(
            "channel, sales"
        ).eq("month", prev_month.isoformat()).execute()

        prev_by_ch: Dict[str, Decimal] = {}
        if prev_response.data:
            for r in prev_response.data:
                ch = r.get("channel")
                s = r.get("sales")
                if ch and s is not None:
                    prev_by_ch[ch] = Decimal(str(s))

        for r in response.data:
            ch = r.get("channel")
            s = r.get("sales")
            target = r.get("sales_target")

            if not ch:
                continue

            # I3: 急成長チャネル
            if ch in prev_by_ch and prev_by_ch[ch] > 0 and s is not None:
                current = Decimal(str(s))
                prev = prev_by_ch[ch]
                yoy = ((current - prev) / prev * 100).quantize(
                    Decimal("0.1"), rounding=ROUND_HALF_UP
                )
                if yoy > 30:
                    items.append(InsightItem(
                        category="good",
                        severity="good",
                        text=f"{ch}が前年比+{yoy}%と急成長",
                        link="/ecommerce",
                    ))

            # I4: 達成率低迷
            if s is not None and target is not None and target > 0:
                rate = (Decimal(str(s)) / Decimal(str(target)) * 100).quantize(
                    Decimal("0.1"), rounding=ROUND_HALF_UP
                )
                if rate < 80:
                    items.append(InsightItem(
                        category="warning",
                        severity="critical",
                        text=f"{ch}の達成率が{rate}%",
                        link="/ecommerce",
                    ))
    except Exception:
        pass

    return items


async def _insight_complaints(
    supabase: Client, today: date
) -> List[InsightItem]:
    """I5/I6: クレーム"""
    items = []
    try:
        month_start = date(today.year, today.month, 1)
        if today.month == 1:
            prev_month_start = date(today.year - 1, 12, 1)
        else:
            prev_month_start = date(today.year, today.month - 1, 1)

        # 今月のクレーム数
        current_response = supabase.table("complaints").select(
            "id", count="exact"
        ).gte("occurred_date", month_start.isoformat()).lte(
            "occurred_date", today.isoformat()
        ).execute()
        current_count = current_response.count or 0

        # 前月のクレーム数
        prev_response = supabase.table("complaints").select(
            "id", count="exact"
        ).gte("occurred_date", prev_month_start.isoformat()).lt(
            "occurred_date", month_start.isoformat()
        ).execute()
        prev_count = prev_response.count or 0

        # I5: クレーム急増
        if prev_count > 0:
            diff = current_count - prev_count
            change_rate = diff / prev_count * 100
            if change_rate > 50 and diff > 0:
                items.append(InsightItem(
                    category="warning",
                    severity="critical",
                    text=f"クレームが前月比+{diff}件と急増",
                    link="/manufacturing/complaints",
                ))

        # I6: 未対応クレーム
        in_progress_response = supabase.table("complaints").select(
            "id", count="exact"
        ).eq("status", "in_progress").execute()
        in_progress_count = in_progress_response.count or 0

        if in_progress_count > 5:
            items.append(InsightItem(
                category="warning",
                severity="warning",
                text=f"未対応クレームが{in_progress_count}件",
                link="/manufacturing/complaints",
            ))
    except Exception:
        pass

    return items


async def _insight_operating_profit(
    supabase: Client, today: date
) -> Optional[InsightItem]:
    """I7: 営業利益悪化"""
    try:
        month_start = date(today.year, today.month, 1)
        prev_year_month = date(today.year - 1, today.month, 1)

        # 今月
        response = supabase.table("financial_data").select(
            "operating_profit"
        ).eq("month", month_start.isoformat()).eq("is_target", False).execute()

        if not response.data or response.data[0].get("operating_profit") is None:
            return None

        current = Decimal(str(response.data[0]["operating_profit"]))

        # 前年同月
        prev_response = supabase.table("financial_data").select(
            "operating_profit"
        ).eq("month", prev_year_month.isoformat()).eq("is_target", False).execute()

        if not prev_response.data or prev_response.data[0].get("operating_profit") is None:
            return None

        prev = Decimal(str(prev_response.data[0]["operating_profit"]))
        if prev == 0:
            return None

        yoy = ((current - prev) / abs(prev) * 100).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        )

        if yoy < -20:
            return InsightItem(
                category="critical",
                severity="critical",
                text=f"営業利益が前年比{yoy}%と大幅減",
                link="/finance",
            )
    except Exception:
        pass

    return None


# =============================================================================
# データ鮮度
# =============================================================================

@cached(prefix="data_freshness", ttl=600)
async def get_data_freshness(supabase: Client) -> DataFreshnessResponse:
    """データ鮮度を取得する（TTL 600秒）"""
    financial_latest = None
    store_latest = None
    ecommerce_latest = None

    try:
        # 財務データの最新月
        fin_response = supabase.table("financial_data").select(
            "month"
        ).eq("is_target", False).order("month", desc=True).limit(1).execute()

        if fin_response.data:
            raw = fin_response.data[0]["month"]
            financial_latest = raw[:7] if raw else None
    except Exception:
        pass

    try:
        # 店舗売上データの最新日
        store_response = supabase.table("hourly_sales").select(
            "date"
        ).order("date", desc=True).limit(1).execute()

        if store_response.data:
            store_latest = store_response.data[0]["date"]
    except Exception:
        pass

    try:
        # 通販データの最新月
        ec_response = supabase.table("ecommerce_channel_sales").select(
            "month"
        ).order("month", desc=True).limit(1).execute()

        if ec_response.data:
            raw = ec_response.data[0]["month"]
            ecommerce_latest = raw[:7] if raw else None
    except Exception:
        pass

    return DataFreshnessResponse(
        financial_latest=financial_latest,
        store_latest=store_latest,
        ecommerce_latest=ecommerce_latest,
    )


# =============================================================================
# ユーティリティ
# =============================================================================

def _previous_year_same_weekday(d: date) -> date:
    """前年同曜日を返す"""
    try:
        base = d.replace(year=d.year - 1)
    except ValueError:
        base = d.replace(year=d.year - 1, day=28)

    diff = d.weekday() - base.weekday()
    if diff > 3:
        diff -= 7
    elif diff < -3:
        diff += 7

    return base + timedelta(days=diff)
