"""
日次販売分析クエリサービス

hourly_salesテーブルから3つのビュー用データを取得する。
manufacturing_service.pyパターンに従い、@cachedデコレータでキャッシュ。
"""
from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, Any, List, Optional

from supabase import Client

from app.services.cache_service import cached
# 日次分析の前年比較は「前年の同一曜日」で統一する（祝日カテゴリ判定は不要）。


# =============================================================================
# ヘルパー関数
# =============================================================================

def _fetch_all(query_builder, order_by: str = "id") -> list:
    """Supabaseの1000行制限を回避して全行を取得する

    ORDER BYを指定しないとPostgreSQLがリクエストごとに異なる順序で返すため、
    ページネーション時に行の重複・欠落が発生する。デフォルトでは id でソート
    するが、id を持たないビュー（daily_sales_by_segment 等）を扱う場合は
    order_by 引数で別の列を指定する。
    """
    all_data = []
    offset = 0
    batch = 1000
    while True:
        result = query_builder.order(order_by).range(offset, offset + batch - 1).execute()
        all_data.extend(result.data)
        if len(result.data) < batch:
            break
        offset += batch
    return all_data

def _get_month_range(month_str: str):
    """月文字列(YYYY-MM-01)から月の開始日・終了日を返す"""
    parts = month_str.split("-")
    year, month = int(parts[0]), int(parts[1])
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    return start, end


def _previous_year_same_weekday(d: date) -> date:
    """前年同曜日を返す（前年の同日付に最も近い同じ曜日の日）

    例: 2026/3/10(火) → 2025/3/11(火)  (3/10は月曜なので+1日)
    """
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


def _previous_year_matching_date(d: date) -> Optional[date]:
    """前年の比較対象日（＝前年の同一曜日）を返す。

    比較ロジックは「前年の同じ曜日」で統一する。今年度の日付の曜日と
    同じ曜日を、前年の同日付に最も近い日から選ぶ（`_previous_year_same_weekday`）。
    その結果、比較対象が前月・翌月にまたがることは許容する。

    旧ロジック（祝日/日/土/金/平日(月-木) の5カテゴリでマッチし、
    金土日祝を必ず同カテゴリ同士で比較する方式）は廃止した。
    例:
      - 水曜 → 前年の（同カテゴリの月-木ではなく）前年の水曜と比較。
      - 祝日 → 前年の祝日ではなく、同じ曜日と比較。
    同一曜日は必ず存在するため None にはならない（前年データが無い場合は
    呼び出し側で YoY=None として扱われる）。
    """
    return _previous_year_same_weekday(d)


async def _get_segments(supabase: Client, department_slug: str = "store"):
    """セグメント一覧を取得"""
    dept_response = supabase.table("departments").select("id").eq(
        "slug", department_slug
    ).single().execute()
    department_id = dept_response.data["id"]

    segments_response = supabase.table("segments").select(
        "id, code, name"
    ).eq("department_id", department_id).order("code").execute()

    return segments_response.data


# =============================================================================
# API 1: 日別×店舗サマリー
# =============================================================================

@cached(prefix="daily_sales", ttl=300)
async def get_daily_sales_summary(
    supabase: Client,
    month: str,
    department_slug: str = "store",
) -> Dict[str, Any]:
    """
    日別×店舗サマリーデータを取得する

    Args:
        supabase: Supabaseクライアント
        month: 対象年月 (YYYY-MM-01)
        department_slug: 部門スラッグ

    Returns:
        DailySalesSummaryResponse相当のdict
    """
    start, end = _get_month_range(month)
    # 前年比較は同一曜日マッチ（前年同日付から±3日以内に必ず同曜日が存在）。
    # 月初・月末の同曜日が前月/翌月にまたがるケースをカバーするため余裕を持って
    # ±7日 取得する。
    prev_start = _previous_year_same_weekday(start) - timedelta(days=7)
    prev_end = _previous_year_same_weekday(end) + timedelta(days=7)

    # セグメント取得
    segments = await _get_segments(supabase, department_slug)
    segment_ids = [s["id"] for s in segments]

    if not segment_ids:
        return {
            "period": month,
            "dates": [],
            "stores": [],
            "data": [],
            "totals": [],
        }

    # 当月売上データ取得（日次集計ビューを使用 → 行数 ~13,000 → ~540 に削減）
    current_sales = _fetch_all(
        supabase.table("daily_sales_by_segment").select(
            "date, segment_id, sales"
        ).gte("date", start.isoformat()).lte(
            "date", end.isoformat()
        ).in_("segment_id", segment_ids),
        order_by="date",
    )

    # 当月客数データ取得（hourly_customers の日次集計ビュー）
    current_customers = _fetch_all(
        supabase.table("daily_customers_by_segment").select(
            "date, segment_id, customer_count"
        ).gte("date", start.isoformat()).lte(
            "date", end.isoformat()
        ).in_("segment_id", segment_ids),
        order_by="date",
    )

    # 前年同月売上データ取得
    prev_sales = _fetch_all(
        supabase.table("daily_sales_by_segment").select(
            "date, segment_id, sales"
        ).gte("date", prev_start.isoformat()).lte(
            "date", prev_end.isoformat()
        ).in_("segment_id", segment_ids),
        order_by="date",
    )

    # 前年同月客数データ取得
    prev_customers = _fetch_all(
        supabase.table("daily_customers_by_segment").select(
            "date, segment_id, customer_count"
        ).gte("date", prev_start.isoformat()).lte(
            "date", prev_end.isoformat()
        ).in_("segment_id", segment_ids),
        order_by="date",
    )

    # 当月: (date, segment_id) でグループ集計
    current_agg: Dict[tuple, Dict[str, Any]] = defaultdict(
        lambda: {"sales": 0.0, "customers": 0}
    )
    for row in current_sales:
        key = (row["date"], row["segment_id"])
        current_agg[key]["sales"] += float(row["sales"])
    for row in current_customers:
        key = (row["date"], row["segment_id"])
        current_agg[key]["customers"] += int(row["customer_count"])

    # 前年: (date, segment_id) でグループ集計
    prev_agg: Dict[tuple, Dict[str, Any]] = defaultdict(
        lambda: {"sales": 0.0, "customers": 0}
    )
    for row in prev_sales:
        key = (row["date"], row["segment_id"])
        prev_agg[key]["sales"] += float(row["sales"])
    for row in prev_customers:
        key = (row["date"], row["segment_id"])
        prev_agg[key]["customers"] += int(row["customer_count"])

    # 日付リスト生成
    dates = []
    d = start
    while d <= end:
        dates.append(d.isoformat())
        d += timedelta(days=1)

    # 店舗情報
    stores = [
        {"segment_id": s["id"], "segment_code": s["code"], "segment_name": s["name"]}
        for s in segments
    ]

    # データ作成
    data = []
    # 月計用
    monthly_totals: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "sales": 0.0, "customers": 0,
            "sales_py": 0.0, "customers_py": 0,
        }
    )

    for dt_str in dates:
        for seg in segments:
            seg_id = seg["id"]
            key = (dt_str, seg_id)
            cur = current_agg.get(key, {"sales": 0.0, "customers": 0})

            # 前年同曜日
            try:
                cur_date = date.fromisoformat(dt_str)
                # 祝日・週末・金曜カテゴリを考慮した前年同カテゴリ最近日でマッチ。
                # 同カテゴリが ±7 日に見つからない場合は prev_date=None となり、
                # 「比較対象なし」として扱う（誤ったカテゴリ間比較を避ける）。
                prev_date = _previous_year_matching_date(cur_date)
                prev_key = (prev_date.isoformat(), seg_id) if prev_date else None
            except ValueError:
                prev_key = None

            prev = prev_agg.get(prev_key, {"sales": 0.0, "customers": 0}) if prev_key else {"sales": 0.0, "customers": 0}

            sales = cur["sales"]
            customers = cur["customers"]
            unit_price = round(sales / customers, 0) if customers > 0 else 0

            sales_py = prev["sales"]
            customers_py = prev["customers"]

            yoy_sales = round((sales / sales_py - 1) * 100, 1) if sales_py > 0 else None
            yoy_customers = round((customers / customers_py - 1) * 100, 1) if customers_py > 0 else None

            entry = {
                "date": dt_str,
                "comparison_date": prev_date.isoformat() if prev_key else None,
                "segment_id": seg_id,
                "sales": sales,
                "customers": customers,
                "unit_price": unit_price,
                "sales_previous_year": sales_py if sales_py > 0 else None,
                "customers_previous_year": customers_py if customers_py > 0 else None,
                "yoy_sales_rate": yoy_sales,
                "yoy_customers_rate": yoy_customers,
            }

            # 売上か客数があるデータのみ追加
            if sales > 0 or customers > 0 or sales_py > 0:
                data.append(entry)

            # 月計に加算
            monthly_totals[seg_id]["sales"] += sales
            monthly_totals[seg_id]["customers"] += customers
            monthly_totals[seg_id]["sales_py"] += sales_py
            monthly_totals[seg_id]["customers_py"] += customers_py

    # 月計行
    totals = []
    for seg in segments:
        seg_id = seg["id"]
        mt = monthly_totals[seg_id]
        sales = mt["sales"]
        customers = mt["customers"]
        unit_price = round(sales / customers, 0) if customers > 0 else 0
        sales_py = mt["sales_py"]
        customers_py = mt["customers_py"]

        yoy_sales = round((sales / sales_py - 1) * 100, 1) if sales_py > 0 else None
        yoy_customers = round((customers / customers_py - 1) * 100, 1) if customers_py > 0 else None

        totals.append({
            "date": "total",
            "segment_id": seg_id,
            "sales": sales,
            "customers": customers,
            "unit_price": unit_price,
            "sales_previous_year": sales_py if sales_py > 0 else None,
            "customers_previous_year": customers_py if customers_py > 0 else None,
            "yoy_sales_rate": yoy_sales,
            "yoy_customers_rate": yoy_customers,
        })

    return {
        "period": month,
        "dates": dates,
        "stores": stores,
        "data": data,
        "totals": totals,
    }


# =============================================================================
# API 2: 時間帯別ヒートマップ
# =============================================================================

@cached(prefix="daily_sales", ttl=300)
async def get_hourly_sales(
    supabase: Client,
    target_date: str,
    department_slug: str = "store",
) -> Dict[str, Any]:
    """
    指定日の時間帯別×店舗データを取得する

    Args:
        supabase: Supabaseクライアント
        target_date: 対象日 (YYYY-MM-DD)
        department_slug: 部門スラッグ

    Returns:
        HourlySalesResponse相当のdict
    """
    segments = await _get_segments(supabase, department_slug)
    segment_ids = [s["id"] for s in segments]

    if not segment_ids:
        return {
            "date": target_date,
            "hours": [],
            "stores": [],
            "data": [],
            "row_totals": [],
            "col_totals": [],
        }

    # 売上データ取得（1000行制限回避）
    hourly_sales_data = _fetch_all(
        supabase.table("hourly_sales").select(
            "hour, segment_id, sales"
        ).eq("date", target_date).in_("segment_id", segment_ids)
    )

    # 客数データ取得（hourly_customers: ユニーク客数）
    hourly_cust_data = _fetch_all(
        supabase.table("hourly_customers").select(
            "hour, segment_id, customer_count"
        ).eq("date", target_date).in_("segment_id", segment_ids)
    )

    # (hour, segment_id) で集計
    agg: Dict[tuple, Dict[str, Any]] = defaultdict(
        lambda: {"sales": 0.0, "customers": 0}
    )
    hours_set = set()

    for row in hourly_sales_data:
        key = (row["hour"], row["segment_id"])
        agg[key]["sales"] += float(row["sales"])
        hours_set.add(row["hour"])

    for row in hourly_cust_data:
        key = (row["hour"], row["segment_id"])
        agg[key]["customers"] += int(row["customer_count"])
        hours_set.add(row["hour"])

    # 営業時間帯（9〜19時をデフォルト、データがあればそちらを使う）
    if hours_set:
        min_hour = min(hours_set)
        max_hour = max(hours_set)
        hours = list(range(min_hour, max_hour + 1))
    else:
        hours = list(range(9, 20))

    stores = [
        {"segment_id": s["id"], "segment_code": s["code"], "segment_name": s["name"]}
        for s in segments
    ]

    # データ
    data = []
    for hour in hours:
        for seg in segments:
            key = (hour, seg["id"])
            val = agg.get(key, {"sales": 0.0, "customers": 0})
            data.append({
                "hour": hour,
                "segment_id": seg["id"],
                "sales": val["sales"],
                "customers": val["customers"],
            })

    # 行計（店舗別合計）
    row_totals = []
    for seg in segments:
        total_sales = sum(
            agg.get((h, seg["id"]), {"sales": 0.0})["sales"] for h in hours
        )
        total_customers = sum(
            agg.get((h, seg["id"]), {"customers": 0})["customers"] for h in hours
        )
        row_totals.append({
            "segment_id": seg["id"],
            "sales": total_sales,
            "customers": total_customers,
        })

    # 列計（時間帯別合計）
    col_totals = []
    for hour in hours:
        total_sales = sum(
            agg.get((hour, seg["id"]), {"sales": 0.0})["sales"] for seg in segments
        )
        total_customers = sum(
            agg.get((hour, seg["id"]), {"customers": 0})["customers"] for seg in segments
        )
        col_totals.append({
            "hour": hour,
            "sales": total_sales,
            "customers": total_customers,
        })

    return {
        "date": target_date,
        "hours": hours,
        "stores": stores,
        "data": data,
        "row_totals": row_totals,
        "col_totals": col_totals,
    }


# =============================================================================
# API 3: 日次推移グラフ
# =============================================================================

@cached(prefix="daily_sales", ttl=300)
async def get_daily_trend(
    supabase: Client,
    month: str,
    segment_id: Optional[str] = None,
    department_slug: str = "store",
) -> Dict[str, Any]:
    """
    日次推移データ（当年+前年同月）を取得する

    Args:
        supabase: Supabaseクライアント
        month: 対象年月 (YYYY-MM-01)
        segment_id: セグメントID（省略時は全店舗合計）
        department_slug: 部門スラッグ

    Returns:
        DailyTrendResponse相当のdict
    """
    start, end = _get_month_range(month)
    # 前年比較は同一曜日マッチ（前年同日付から±3日以内に必ず同曜日が存在）。
    # 月初・月末の同曜日が前月/翌月にまたがるケースをカバーするため余裕を持って
    # ±7日 取得する。
    prev_start = _previous_year_same_weekday(start) - timedelta(days=7)
    prev_end = _previous_year_same_weekday(end) + timedelta(days=7)

    # セグメント名を取得
    segment_name = None
    if segment_id:
        seg_response = supabase.table("segments").select(
            "name"
        ).eq("id", segment_id).single().execute()
        segment_name = seg_response.data["name"]

    # 当月売上データ（日次集計ビュー）
    sales_query = supabase.table("daily_sales_by_segment").select(
        "date, sales"
    ).gte("date", start.isoformat()).lte("date", end.isoformat())

    # 当月客数データ（日次集計ビュー）
    cust_query = supabase.table("daily_customers_by_segment").select(
        "date, customer_count"
    ).gte("date", start.isoformat()).lte("date", end.isoformat())

    if segment_id:
        sales_query = sales_query.eq("segment_id", segment_id)
        cust_query = cust_query.eq("segment_id", segment_id)
    else:
        segments = await _get_segments(supabase, department_slug)
        segment_ids = [s["id"] for s in segments]
        if segment_ids:
            sales_query = sales_query.in_("segment_id", segment_ids)
            cust_query = cust_query.in_("segment_id", segment_ids)

    current_sales_data = _fetch_all(sales_query, order_by="date")
    current_cust_data = _fetch_all(cust_query, order_by="date")

    # 前年同月売上データ（日次集計ビュー）
    prev_sales_query = supabase.table("daily_sales_by_segment").select(
        "date, sales"
    ).gte("date", prev_start.isoformat()).lte("date", prev_end.isoformat())

    # 前年同月客数データ（日次集計ビュー）
    prev_cust_query = supabase.table("daily_customers_by_segment").select(
        "date, customer_count"
    ).gte("date", prev_start.isoformat()).lte("date", prev_end.isoformat())

    if segment_id:
        prev_sales_query = prev_sales_query.eq("segment_id", segment_id)
        prev_cust_query = prev_cust_query.eq("segment_id", segment_id)
    else:
        if segment_ids:
            prev_sales_query = prev_sales_query.in_("segment_id", segment_ids)
            prev_cust_query = prev_cust_query.in_("segment_id", segment_ids)

    prev_sales_data = _fetch_all(prev_sales_query, order_by="date")
    prev_cust_data = _fetch_all(prev_cust_query, order_by="date")

    # 日別に集計
    current_daily: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"sales": 0.0, "customers": 0}
    )
    for row in current_sales_data:
        current_daily[row["date"]]["sales"] += float(row["sales"])
    for row in current_cust_data:
        current_daily[row["date"]]["customers"] += int(row["customer_count"])

    prev_daily: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"sales": 0.0, "customers": 0}
    )
    for row in prev_sales_data:
        prev_daily[row["date"]]["sales"] += float(row["sales"])
    for row in prev_cust_data:
        prev_daily[row["date"]]["customers"] += int(row["customer_count"])

    # 日次データ作成
    # - previous_year は「当年の各日に対する前年同曜日マッチ日」で1日1点に整列する。
    #   （±7日の取得パディングをそのまま出力すると、当月日数を超える系列になり
    #   グラフが45日分描画されるバグになるため、出力は当月の日数に必ず揃える）
    # - current_year は当日までで打ち切る（進行中の月で未来日が0円で描画され、
    #   月末にグラフが0に落ちたように見えるのを防ぐ）
    today = date.today()
    current_year = []
    previous_year = []
    d = start
    while d <= end:
        dt_str = d.isoformat()
        if d <= today:
            val = current_daily.get(dt_str, {"sales": 0.0, "customers": 0})
            current_year.append({
                "date": dt_str,
                "sales": val["sales"],
                "customers": val["customers"],
            })

        prev_d = _previous_year_matching_date(d)
        prev_str = prev_d.isoformat() if prev_d else None
        pval = prev_daily.get(prev_str, {"sales": 0.0, "customers": 0}) if prev_str else {"sales": 0.0, "customers": 0}
        previous_year.append({
            "date": prev_str or dt_str,
            "sales": pval["sales"],
            "customers": pval["customers"],
        })
        d += timedelta(days=1)

    # 末尾の未取込日（売上・客数とも0）は落とす。レシートジャーナルの取込が
    # 当日に追いついていない期間が0円で描画され、線が0に急落して見えるため。
    # 月中の休業日などの0は残す（末尾連続分のみトリム）。
    while current_year and current_year[-1]["sales"] == 0 and current_year[-1]["customers"] == 0:
        current_year.pop()

    return {
        "period": month,
        "segment_id": segment_id,
        "segment_name": segment_name,
        "current_year": current_year,
        "previous_year": previous_year,
    }


# =============================================================================
# API 4: 時間帯別ヒートマップ（月間合計）
# =============================================================================

@cached(prefix="daily_sales", ttl=300)
async def get_hourly_sales_month(
    supabase: Client,
    month: str,
    department_slug: str = "store",
) -> Dict[str, Any]:
    """
    指定月の時間帯別×店舗の合計データを取得する（月間合計ヒートマップ用）

    集計ビュー hourly_sales_agg / hourly_customers_agg（(date, segment, hour)
    粒度）を月範囲で取得し、(hour, segment) に集約する。
    レスポンス形式は get_hourly_sales と同じ（date には月初文字列を入れる）。
    """
    start, end = _get_month_range(month)
    segments = await _get_segments(supabase, department_slug)
    segment_ids = [s["id"] for s in segments]

    if not segment_ids:
        return {
            "date": month,
            "hours": [],
            "stores": [],
            "data": [],
            "row_totals": [],
            "col_totals": [],
        }

    hourly_sales_data = _fetch_all(
        supabase.table("hourly_sales_agg").select(
            "hour, segment_id, sales"
        ).gte("date", start.isoformat()).lte("date", end.isoformat())
        .in_("segment_id", segment_ids),
        order_by="date",
    )
    hourly_cust_data = _fetch_all(
        supabase.table("hourly_customers_agg").select(
            "hour, segment_id, customer_count"
        ).gte("date", start.isoformat()).lte("date", end.isoformat())
        .in_("segment_id", segment_ids),
        order_by="date",
    )

    agg: Dict[tuple, Dict[str, Any]] = defaultdict(
        lambda: {"sales": 0.0, "customers": 0}
    )
    hours_set = set()
    for row in hourly_sales_data:
        key = (row["hour"], row["segment_id"])
        agg[key]["sales"] += float(row["sales"])
        hours_set.add(row["hour"])
    for row in hourly_cust_data:
        key = (row["hour"], row["segment_id"])
        agg[key]["customers"] += int(row["customer_count"])
        hours_set.add(row["hour"])

    if hours_set:
        hours = list(range(min(hours_set), max(hours_set) + 1))
    else:
        hours = list(range(9, 20))

    stores = [
        {"segment_id": s["id"], "segment_code": s["code"], "segment_name": s["name"]}
        for s in segments
    ]

    data = []
    for hour in hours:
        for seg in segments:
            val = agg.get((hour, seg["id"]), {"sales": 0.0, "customers": 0})
            data.append({
                "hour": hour,
                "segment_id": seg["id"],
                "sales": val["sales"],
                "customers": val["customers"],
            })

    row_totals = []
    for seg in segments:
        row_totals.append({
            "segment_id": seg["id"],
            "sales": sum(agg.get((h, seg["id"]), {"sales": 0.0})["sales"] for h in hours),
            "customers": sum(agg.get((h, seg["id"]), {"customers": 0})["customers"] for h in hours),
        })

    col_totals = []
    for hour in hours:
        col_totals.append({
            "hour": hour,
            "sales": sum(agg.get((hour, s["id"]), {"sales": 0.0})["sales"] for s in segments),
            "customers": sum(agg.get((hour, s["id"]), {"customers": 0})["customers"] for s in segments),
        })

    return {
        "date": month,
        "hours": hours,
        "stores": stores,
        "data": data,
        "row_totals": row_totals,
        "col_totals": col_totals,
    }


# =============================================================================
# API 5: 曜日別分析（平日 / 土日祝）
# =============================================================================

def _is_weekend_or_holiday(d: date) -> bool:
    """土曜・日曜・祝日なら True"""
    from app.services.japanese_holidays import is_japanese_holiday
    return d.weekday() >= 5 or is_japanese_holiday(d)


async def _collect_daily_metrics(
    supabase: Client,
    start: date,
    end: date,
    segment_ids: List[str],
) -> Dict[str, Dict[str, float]]:
    """期間内の日別 売上・客数・バット数 を全店合計で収集する"""
    from app.services.order_forecast_service import (
        BATS_DIVISOR,
        _extract_pack_size,
    )

    sales_rows = _fetch_all(
        supabase.table("daily_sales_by_segment").select("date, sales")
        .gte("date", start.isoformat()).lte("date", end.isoformat())
        .in_("segment_id", segment_ids),
        order_by="date",
    )
    cust_rows = _fetch_all(
        supabase.table("daily_customers_by_segment").select("date, customer_count")
        .gte("date", start.isoformat()).lte("date", end.isoformat())
        .in_("segment_id", segment_ids),
        order_by="date",
    )
    qty_rows = _fetch_all(
        supabase.table("daily_gyoza_quantity").select("date, product_name, quantity")
        .gte("date", start.isoformat()).lte("date", end.isoformat())
        .in_("segment_id", segment_ids),
        order_by="date",
    )

    daily: Dict[str, Dict[str, float]] = defaultdict(
        lambda: {"sales": 0.0, "customers": 0.0, "bats": 0.0}
    )
    for row in sales_rows:
        daily[row["date"]]["sales"] += float(row["sales"])
    for row in cust_rows:
        daily[row["date"]]["customers"] += float(row["customer_count"])
    for row in qty_rows:
        pack_size = _extract_pack_size(row["product_name"])
        if pack_size == 0:
            continue
        daily[row["date"]]["bats"] += float(row["quantity"]) * pack_size / BATS_DIVISOR

    return daily


def _summarize_group(
    daily: Dict[str, Dict[str, float]],
    dates: List[date],
) -> Dict[str, Any]:
    """日付グループの平均指標を計算する（データがある日のみ平均対象）"""
    days_with_data = [
        d for d in dates
        if daily.get(d.isoformat(), {}).get("sales", 0.0) > 0
    ]
    n = len(days_with_data)
    if n == 0:
        return {
            "days": 0, "avg_sales": 0.0, "avg_bats": 0.0,
            "avg_customers": 0.0, "avg_price": 0.0,
        }
    total_sales = sum(daily[d.isoformat()]["sales"] for d in days_with_data)
    total_cust = sum(daily[d.isoformat()]["customers"] for d in days_with_data)
    total_bats = sum(daily[d.isoformat()]["bats"] for d in days_with_data)
    return {
        "days": n,
        "avg_sales": round(total_sales / n, 0),
        "avg_bats": round(total_bats / n, 1),
        "avg_customers": round(total_cust / n, 1),
        "avg_price": round(total_sales / total_cust, 0) if total_cust > 0 else 0.0,
    }


def _with_yoy(current: Dict[str, Any], previous: Dict[str, Any]) -> Dict[str, Any]:
    """current に前年値と前年比を付与する"""
    result = dict(current)
    result["prev"] = previous
    yoy = {}
    for key in ("avg_sales", "avg_bats", "avg_customers", "avg_price"):
        prev_val = previous.get(key) or 0
        cur_val = current.get(key) or 0
        yoy[key] = round(cur_val / prev_val * 100, 1) if prev_val else None
    result["yoy"] = yoy
    return result


@cached(prefix="daily_sales", ttl=300)
async def get_weekday_analysis(
    supabase: Client,
    month: str,
    department_slug: str = "store",
    segment_id: Optional[str] = None,
    period_type: str = "monthly",
) -> Dict[str, Any]:
    """
    曜日別分析: 平日 / 土日祝 の平均売上・バット数・来客数・客単価と前年同期比

    - 土日祝 = 土曜・日曜・日本の祝日（振替休日含む）
    - 平均はデータがある日のみを分母にする（休業日・未取込日を除外）
    - 前年は前年同期間のカレンダーで同様に集計して比較する
    - バット数 = ぎょうざ系商品の販売個数×パック入数 ÷ 60
    - segment_id 指定時はその店舗のみ、未指定時は部門の全店舗合計
    - period_type="cumulative" で年度累計（9月〜対象月）の日次平均
    """
    start, end = _get_month_range(month)
    if period_type == "cumulative":
        # 年度開始（9月）〜対象月末の範囲で平均を取る
        fy_start_year = start.year if start.month >= 9 else start.year - 1
        start = date(fy_start_year, 9, 1)
    try:
        prev_start = start.replace(year=start.year - 1)
    except ValueError:
        prev_start = start.replace(year=start.year - 1, day=28)
    try:
        prev_end = end.replace(year=end.year - 1)
    except ValueError:
        prev_end = end.replace(year=end.year - 1, day=28)

    if segment_id:
        segment_ids = [segment_id]
    else:
        segments = await _get_segments(supabase, department_slug)
        segment_ids = [s["id"] for s in segments]
    if not segment_ids:
        empty = {
            "days": 0, "avg_sales": 0.0, "avg_bats": 0.0,
            "avg_customers": 0.0, "avg_price": 0.0,
            "prev": {}, "yoy": {},
        }
        return {"period": month, "weekday": empty, "weekend": empty}

    current_daily = await _collect_daily_metrics(supabase, start, end, segment_ids)
    prev_daily = await _collect_daily_metrics(supabase, prev_start, prev_end, segment_ids)

    # 当月は当日まで（未来日を分母に入れない）
    today = date.today()
    cur_last = min(end, today)

    def split_dates(s: date, e: date):
        weekdays, weekends = [], []
        d = s
        while d <= e:
            (weekends if _is_weekend_or_holiday(d) else weekdays).append(d)
            d += timedelta(days=1)
        return weekdays, weekends

    cur_weekdays, cur_weekends = split_dates(start, cur_last)
    prev_weekdays, prev_weekends = split_dates(prev_start, prev_end)

    weekday_cur = _summarize_group(current_daily, cur_weekdays)
    weekday_prev = _summarize_group(prev_daily, prev_weekdays)
    weekend_cur = _summarize_group(current_daily, cur_weekends)
    weekend_prev = _summarize_group(prev_daily, prev_weekends)

    return {
        "period": month,
        "weekday": _with_yoy(weekday_cur, weekday_prev),
        "weekend": _with_yoy(weekend_cur, weekend_prev),
    }


# =============================================================================
# API 6: 店舗の日別×時間帯 来客ヒートマップ
# =============================================================================

@cached(prefix="daily_sales", ttl=300)
async def get_store_hourly_customers(
    supabase: Client,
    month: str,
    segment_id: str,
    period_type: str = "monthly",
) -> Dict[str, Any]:
    """
    店舗詳細ページ用: 日別×時間帯の来客数マトリクスを取得する

    - 単月: 行=日付（当月1日〜月末。進行中の月は当日まで）
    - 累計: 行=月（年度開始9月〜対象月。月×時間帯で合算）
    - 列=時間帯（期間内にデータがある時間帯の min〜max）
    - row_totals=日計（累計時は月計）、col_totals=時間帯別合計（最終行用）
    """
    start, end = _get_month_range(month)
    is_cumulative = period_type == "cumulative"
    if is_cumulative:
        fy_start_year = start.year if start.month >= 9 else start.year - 1
        start = date(fy_start_year, 9, 1)
    today = date.today()
    last = min(end, today)

    rows = _fetch_all(
        supabase.table("hourly_customers_agg")
        .select("date, hour, customer_count")
        .eq("segment_id", segment_id)
        .gte("date", start.isoformat())
        .lte("date", last.isoformat()),
        order_by="date",
    )

    # (date, hour) -> customers。累計時は日付を月初に丸めて月単位に合算する
    # （ビューは (date, segment, hour) 粒度で一意）
    agg: Dict[tuple, int] = {}
    for row in rows:
        dt = f"{row['date'][:7]}-01" if is_cumulative else row["date"]
        key = (dt, int(row["hour"]))
        agg[key] = agg.get(key, 0) + int(row["customer_count"])

    hour_set = sorted({h for (_, h) in agg})
    hours = list(range(hour_set[0], hour_set[-1] + 1)) if hour_set else []

    dates = []
    d = start
    while d <= last:
        dates.append(d.isoformat())
        if is_cumulative:
            d = date(d.year + 1, 1, 1) if d.month == 12 else date(d.year, d.month + 1, 1)
        else:
            d += timedelta(days=1)

    # 末尾の未取込日（来客0）はトリムする（日次推移と同じ扱い。期間中の休業日は残す）
    dates_with_data = {dt for (dt, _) in agg}
    while dates and dates[-1] not in dates_with_data:
        dates.pop()
    # 累計時はレシートジャーナル取込前の先頭の空月もトリムする
    if is_cumulative:
        while dates and dates[0] not in dates_with_data:
            dates.pop(0)

    data = [
        {"date": dt, "hour": h, "customers": c}
        for (dt, h), c in agg.items()
        if c > 0
    ]

    row_totals = [
        {"date": dt, "customers": sum(agg.get((dt, h), 0) for h in hours)}
        for dt in dates
    ]
    col_totals = [
        {"hour": h, "customers": sum(agg.get((dt, h), 0) for dt in dates)}
        for h in hours
    ]
    total = sum(t["customers"] for t in col_totals)

    return {
        "period": month,
        "segment_id": segment_id,
        "hours": hours,
        "dates": dates,
        "data": data,
        "row_totals": row_totals,
        "col_totals": col_totals,
        "total": total,
    }
