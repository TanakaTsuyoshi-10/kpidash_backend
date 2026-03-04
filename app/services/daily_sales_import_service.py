"""
日次販売データインポートサービス

レシートジャーナルのパース結果をhourly_salesテーブルに集計・保存する。
import_service.pyと同じパターンで、segments取得→Dict集計→バッチupsert。
"""
from collections import defaultdict
from typing import Dict, Any, List, Set, Tuple

from supabase import Client

from app.services.cache_service import cache


async def get_segments_by_store_code(
    supabase: Client,
    department_slug: str = "store"
) -> Dict[str, Dict[str, Any]]:
    """
    店舗部門のセグメント一覧を取得し、store_code → segment 辞書を返す
    """
    # 部門IDを取得
    dept_response = supabase.table("departments").select("id").eq(
        "slug", department_slug
    ).single().execute()
    department_id = dept_response.data["id"]

    # セグメント一覧取得
    segments_response = supabase.table("segments").select(
        "id, code, name"
    ).eq("department_id", department_id).execute()

    return {str(seg["code"]): seg for seg in segments_response.data}


async def import_receipt_journal(
    supabase: Client,
    parsed_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    レシートジャーナルのパース結果をhourly_salesにインポートする

    Args:
        supabase: Supabase管理者クライアント
        parsed_data: parse_receipt_journal()の戻り値

    Returns:
        Dict[str, Any]:
            - success: bool
            - imported: int - インポートレコード数
            - errors: List[str]
            - warnings: List[str]
            - stores_processed: List[str] - 処理した店舗名
    """
    result: Dict[str, Any] = {
        "success": False,
        "imported": 0,
        "errors": [],
        "warnings": [],
        "stores_processed": [],
    }

    transactions = parsed_data.get("transactions", [])
    if not transactions:
        result["errors"].append("インポートするデータがありません")
        return result

    # 店舗マスタ取得
    try:
        segments = await get_segments_by_store_code(supabase)
    except Exception as e:
        result["errors"].append(f"店舗マスタの取得に失敗しました: {str(e)}")
        return result

    # (date, hour, segment_id, product_name) でDict集計
    # キー: (date, hour, segment_id, product_name)
    # 値: {sales, quantity, receipt_numbers}
    AggKey = Tuple[str, int, str, str]
    aggregated: Dict[AggKey, Dict[str, Any]] = defaultdict(
        lambda: {"sales": 0.0, "quantity": 0, "receipt_numbers": set(), "product_group": ""}
    )

    processed_stores: Set[str] = set()
    skipped_stores: Set[str] = set()

    for txn in transactions:
        store_code = txn["store_code"]
        segment = segments.get(store_code)

        if not segment:
            skipped_stores.add(store_code)
            continue

        segment_id = segment["id"]
        segment_name = segment["name"]
        processed_stores.add(segment_name)

        key: AggKey = (
            txn["date"].isoformat(),
            txn["hour"],
            segment_id,
            txn["product_name"],
        )

        agg = aggregated[key]
        agg["sales"] += txn["sales"]
        agg["quantity"] += txn["quantity"]
        agg["receipt_numbers"].add(txn["receipt_no"])
        agg["product_group"] = txn["product_group"]

    if skipped_stores:
        for sc in sorted(skipped_stores):
            result["warnings"].append(f"店舗CD {sc} はマスタに存在しません")

    if not aggregated:
        result["errors"].append("有効なデータがありません（全店舗がマスタ未登録）")
        return result

    # upsertレコード作成
    records = []
    for (dt, hour, seg_id, product_name), agg in aggregated.items():
        records.append({
            "date": dt,
            "hour": hour,
            "segment_id": seg_id,
            "product_name": product_name,
            "product_group": agg["product_group"],
            "sales": round(agg["sales"], 2),
            "quantity": agg["quantity"],
            "receipt_count": len(agg["receipt_numbers"]),
        })

    # バッチupsert（500件ずつ）
    try:
        batch_size = 500
        for i in range(0, len(records), batch_size):
            batch = records[i:i + batch_size]
            supabase.table("hourly_sales").upsert(
                batch,
                on_conflict="date,hour,segment_id,product_name"
            ).execute()

        result["success"] = True
        result["imported"] = len(records)
        result["stores_processed"] = sorted(processed_stores)

        # キャッシュクリア
        cache.clear_prefix("daily_sales")

    except Exception as e:
        result["errors"].append(f"データの保存に失敗しました: {str(e)}")

    return result
