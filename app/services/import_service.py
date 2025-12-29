"""
データインポートサービスモジュール

パースしたCSVデータをDBに保存するサービスを提供する。
商品マッピングの自動登録、Upsert処理をサポート。

機能:
- 店舗別KPIデータのインポート
- 商品別KPIデータのインポート（グループ別集計含む）
- 商品マッピングの自動登録
- kpi_valuesへのUpsert
"""
from datetime import date
from decimal import Decimal
from typing import Dict, Any, List, Optional, Tuple
from uuid import UUID

from supabase import Client


# =============================================================================
# カテゴリマッピング定義
# =============================================================================

# 大分類名 → KPIグループ名の対応
CATEGORY_MAPPING = {
    # ぎょうざ系（店頭・宅配）
    "ぎょうざ": "ぎょうざ",
    "生ぎょうざ": "ぎょうざ",
    "餃子": "ぎょうざ",
    "宅配ぎょうざ": "ぎょうざ",
    # しょうが入り系
    "しょうが入": "しょうが入ぎょうざ",
    "しょうが入ぎょうざ": "しょうが入ぎょうざ",
    "しょうが入り": "しょうが入ぎょうざ",
    "生姜入": "しょうが入ぎょうざ",
    "生姜ぎょうざ": "しょうが入ぎょうざ",
    # 付属品系（たれ・スープ）
    "たれ": "付属品",
    "たれ・スープ": "付属品",
    "スープ": "付属品",
    "タレ": "付属品",
    "調味料": "付属品",
    "宅配たれ・スープ": "付属品",
    # 梱包・送料系 → 経費として別KPIグループにするか、その他
    "梱包料": "その他",
    "宅配梱包料": "その他",
    "送料": "その他",
    "袋": "その他",
    # 食品系（冷凍食品など）
    "食品": "その他",
    "冷凍食品": "その他",
    # その他
    "その他": "その他",
    "未分類": "その他",
}


# =============================================================================
# 店舗KPIインポート
# =============================================================================

async def import_store_kpi(
    supabase: Client,
    parsed_data: Dict[str, Any],
    department_id: str
) -> Dict[str, Any]:
    """
    店舗別KPIデータをDBにインポートする

    パースされた店舗別CSVデータをkpi_valuesテーブルに保存する。
    各店舗の売上高と客数を登録する。

    Args:
        supabase: Supabaseクライアント
        parsed_data: parse_store_csv()の戻り値
        department_id: 部門ID

    Returns:
        Dict[str, Any]: インポート結果
            - imported: int - インポートされたレコード数
            - errors: List[str] - エラーメッセージ
            - warnings: List[str] - 警告メッセージ
    """
    result = {
        "imported": 0,
        "updated": 0,
        "errors": [],
        "warnings": [],
    }

    period = parsed_data.get("period")
    data = parsed_data.get("data", [])

    if not period or not data:
        result["errors"].append("有効なデータがありません")
        return result

    # 店舗マスタを取得（店舗コード → セグメントID のマッピング作成）
    try:
        segments_response = supabase.table("segments").select(
            "id, code, name"
        ).eq("department_id", department_id).execute()
        segments = {str(seg["code"]): seg for seg in segments_response.data}
    except Exception as e:
        result["errors"].append(f"店舗マスタの取得に失敗しました: {str(e)}")
        return result

    # KPI定義を取得（売上高、客数）
    try:
        kpi_response = supabase.table("kpi_definitions").select(
            "id, name"
        ).eq("department_id", department_id).in_(
            "name", ["売上高", "客数"]
        ).execute()
        kpi_map = {kpi["name"]: kpi["id"] for kpi in kpi_response.data}
    except Exception as e:
        result["errors"].append(f"KPI定義の取得に失敗しました: {str(e)}")
        return result

    sales_kpi_id = kpi_map.get("売上高")
    customers_kpi_id = kpi_map.get("客数")

    if not sales_kpi_id or not customers_kpi_id:
        result["errors"].append("売上高または客数のKPI定義が見つかりません")
        return result

    # バルク処理用のレコードを準備
    kpi_records = []
    for item in data:
        store_code = item["store_code"]
        segment = segments.get(store_code)

        if not segment:
            result["warnings"].append(f"店舗CD {store_code} はマスタに存在しません")
            continue

        segment_id = segment["id"]

        # 売上高レコード
        kpi_records.append({
            "segment_id": segment_id,
            "kpi_id": sales_kpi_id,
            "date": period.isoformat(),
            "value": float(item["sales"]),
            "is_target": False,
        })

        # 客数レコード
        kpi_records.append({
            "segment_id": segment_id,
            "kpi_id": customers_kpi_id,
            "date": period.isoformat(),
            "value": float(item["customers"]),
            "is_target": False,
        })

    # バルクUpsert処理
    if kpi_records:
        try:
            # バッチサイズで分割してupsert（Supabaseの制限対応）
            batch_size = 500
            for i in range(0, len(kpi_records), batch_size):
                batch = kpi_records[i:i + batch_size]
                # on_conflict: ユニーク制約に基づいてupsert
                supabase.table("kpi_values").upsert(
                    batch,
                    on_conflict="segment_id,kpi_id,date,is_target"
                ).execute()
            result["imported"] = len(kpi_records)

        except Exception as e:
            result["errors"].append(f"KPIバルクインポートに失敗: {str(e)}")

    return result


# =============================================================================
# 商品KPIインポート
# =============================================================================

async def import_product_kpi(
    supabase: Client,
    parsed_data: Dict[str, Any],
    department_id: str,
    segment_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    商品別KPIデータをDBにインポートする

    パースされた商品別CSVデータを処理し、店舗別×KPIグループ別に集計して
    kpi_valuesテーブルに保存する。

    POSからの店舗別×商品別データを処理する場合:
    - 各行に店舗CD、店舗名が含まれる
    - 店舗ごとにKPIグループ別集計を行う
    - 各店舗のセグメントに対してkpi_valuesを登録

    Args:
        supabase: Supabaseクライアント
        parsed_data: parse_product_csv()の戻り値
        department_id: 部門ID
        segment_id: セグメントID（指定しない場合は店舗別に処理）

    Returns:
        Dict[str, Any]: インポート結果
            - imported: int - インポートされたレコード数
            - new_products: List[str] - 新規登録された商品名
            - unmapped: List[str] - マッピングされなかった商品名
            - errors: List[str] - エラーメッセージ
            - warnings: List[str] - 警告メッセージ
    """
    result = {
        "imported": 0,
        "new_products": [],
        "unmapped": [],
        "errors": [],
        "warnings": [],
        "stores_processed": [],
    }

    period = parsed_data.get("period")
    data = parsed_data.get("data", [])

    if not period or not data:
        result["errors"].append("有効なデータがありません")
        return result

    # 店舗マスタを取得（店舗コード → セグメントID のマッピング）
    try:
        segments_response = supabase.table("segments").select(
            "id, code, name"
        ).eq("department_id", department_id).execute()
        segments = {str(seg["code"]): seg for seg in segments_response.data}
    except Exception as e:
        result["errors"].append(f"店舗マスタの取得に失敗しました: {str(e)}")
        return result

    # 商品マッピングを取得
    try:
        mappings_response = supabase.table("product_mappings").select(
            "id, raw_product_name, kpi_id"
        ).execute()
        existing_mappings = {
            m["raw_product_name"]: m for m in mappings_response.data
        }
    except Exception as e:
        result["errors"].append(f"商品マッピングの取得に失敗: {str(e)}")
        return result

    # KPI定義を取得
    try:
        kpi_response = supabase.table("kpi_definitions").select(
            "id, name, category"
        ).eq("department_id", department_id).execute()
        kpi_by_name = {kpi["name"]: kpi for kpi in kpi_response.data}
    except Exception as e:
        result["errors"].append(f"KPI定義の取得に失敗: {str(e)}")
        return result

    # 店舗別×KPIグループ別に集計
    # 構造: {store_code: {kpi_name: {kpi_id, quantity, sales}}}
    store_aggregated = {}
    processed_products = set()

    for item in data:
        store_code = item.get("store_code", "1")
        product_name = item["product_name"]
        category = item["category"]
        quantity = item["quantity"]
        sales = item["sales"]

        # マッピングを取得または作成
        mapping = existing_mappings.get(product_name)

        if not mapping:
            # 新規商品 - マッピングを作成
            kpi_group = get_kpi_group_from_category(category)
            kpi_id = kpi_by_name.get(kpi_group, {}).get("id")

            try:
                new_mapping = await get_or_create_product_mapping(
                    supabase, product_name, category, kpi_id
                )
                existing_mappings[product_name] = new_mapping
                if product_name not in processed_products:
                    result["new_products"].append(product_name)
                    processed_products.add(product_name)
                mapping = new_mapping
            except Exception as e:
                result["errors"].append(
                    f"商品 {product_name} のマッピング作成に失敗: {str(e)}"
                )
                continue

        # KPIグループに集計（店舗別）
        if mapping.get("kpi_id"):
            kpi_id = mapping["kpi_id"]
            # KPI IDからKPI名を逆引き
            kpi_info = next(
                (k for k in kpi_response.data if k["id"] == kpi_id),
                None
            )
            if kpi_info:
                kpi_name = kpi_info["name"]

                # 店舗別の集計データを初期化
                if store_code not in store_aggregated:
                    store_aggregated[store_code] = {}

                if kpi_name not in store_aggregated[store_code]:
                    store_aggregated[store_code][kpi_name] = {
                        "kpi_id": kpi_id,
                        "quantity": 0,
                        "sales": 0,
                    }
                store_aggregated[store_code][kpi_name]["quantity"] += quantity
                store_aggregated[store_code][kpi_name]["sales"] += sales
        else:
            if product_name not in result["unmapped"]:
                result["unmapped"].append(product_name)

    # 店舗別に集計結果をDBに保存（バルク処理）
    kpi_records = []
    for store_code, kpi_data in store_aggregated.items():
        # 店舗コードからセグメントIDを取得
        segment = segments.get(store_code)

        if not segment:
            result["warnings"].append(f"店舗CD {store_code} はマスタに存在しません")
            continue

        current_segment_id = segment["id"]
        result["stores_processed"].append({
            "store_code": store_code,
            "store_name": segment["name"]
        })

        for kpi_name, agg_data in kpi_data.items():
            kpi_records.append({
                "segment_id": current_segment_id,
                "kpi_id": agg_data["kpi_id"],
                "date": period.isoformat(),
                "value": float(agg_data["sales"]),
                "is_target": False,
            })

    # バルクUpsert処理
    if kpi_records:
        try:
            # バッチサイズで分割してupsert（Supabaseの制限対応）
            batch_size = 500
            for i in range(0, len(kpi_records), batch_size):
                batch = kpi_records[i:i + batch_size]
                # on_conflict: ユニーク制約に基づいてupsert
                supabase.table("kpi_values").upsert(
                    batch,
                    on_conflict="segment_id,kpi_id,date,is_target"
                ).execute()
            result["imported"] = len(kpi_records)

        except Exception as e:
            result["errors"].append(f"KPIバルクインポートに失敗: {str(e)}")

    # 個別商品データをproduct_salesテーブルに保存
    product_sales_result = await import_product_sales(
        supabase, data, period, segments
    )
    result["product_sales_imported"] = product_sales_result.get("imported", 0)
    result["errors"].extend(product_sales_result.get("errors", []))

    return result


# =============================================================================
# 個別商品販売データのインポート
# =============================================================================

async def import_product_sales(
    supabase: Client,
    data: List[Dict[str, Any]],
    period: date,
    segments: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    """
    個別商品販売データをproduct_salesテーブルにインポートする（バルク処理）

    Args:
        supabase: Supabaseクライアント
        data: パースされた商品データ
        period: 対象期間（月初日）
        segments: 店舗マスタ（店舗コード → セグメント情報）

    Returns:
        Dict[str, Any]: インポート結果
    """
    result = {
        "imported": 0,
        "errors": [],
    }

    # 店舗×商品コード別に集計
    # 構造: {(segment_id, product_code): {data}}
    product_aggregated: Dict[tuple, Dict[str, Any]] = {}

    for item in data:
        store_code = item.get("store_code", "")
        segment = segments.get(store_code)

        if not segment:
            continue

        segment_id = segment["id"]
        product_code = item.get("product_code", "")

        if not product_code or product_code.lower() == "nan":
            continue

        key = (segment_id, product_code)

        if key not in product_aggregated:
            product_aggregated[key] = {
                "segment_id": segment_id,
                "sale_date": period.isoformat(),
                "product_code": product_code,
                "product_name": item.get("product_name", ""),
                "product_category_code": item.get("category_code"),
                "product_category_name": item.get("category", ""),
                "product_subcategory_code": item.get("subcategory_code"),
                "product_subcategory_name": item.get("subcategory_name"),
                "quantity": 0,
                "sales_with_tax": 0,
                "sales_without_tax": 0,
                "tax_amount": 0,
            }

        # 集計
        product_aggregated[key]["quantity"] += item.get("quantity", 0)
        product_aggregated[key]["sales_with_tax"] += item.get("sales", 0)
        if item.get("sales_without_tax"):
            product_aggregated[key]["sales_without_tax"] += item["sales_without_tax"]
        if item.get("tax_amount"):
            product_aggregated[key]["tax_amount"] += item["tax_amount"]

    if not product_aggregated:
        return result

    # バルクUpsert処理
    try:
        records = list(product_aggregated.values())

        # バッチサイズで分割してupsert（Supabaseの制限対応）
        batch_size = 500
        for i in range(0, len(records), batch_size):
            batch = records[i:i + batch_size]
            # on_conflict: ユニーク制約に基づいてupsert
            supabase.table("product_sales").upsert(
                batch,
                on_conflict="segment_id,sale_date,product_code"
            ).execute()
        result["imported"] = len(records)

    except Exception as e:
        result["errors"].append(f"バルクインポートに失敗: {str(e)}")

    return result


# =============================================================================
# 商品マッピング
# =============================================================================

def get_kpi_group_from_category(category: str) -> str:
    """
    大分類名からKPIグループ名を取得する

    CATEGORY_MAPPINGを使用して大分類名を正規化されたKPIグループ名に変換する。

    Args:
        category: 大分類名

    Returns:
        str: KPIグループ名（マッピングが見つからない場合は"その他"）
    """
    return CATEGORY_MAPPING.get(category, "その他")


async def get_or_create_product_mapping(
    supabase: Client,
    product_name: str,
    category: str,
    kpi_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    商品マッピングを取得または作成する

    product_mappingsテーブルから商品名で検索し、存在しなければ新規作成する。

    Args:
        supabase: Supabaseクライアント
        product_name: 商品名
        category: 大分類名
        kpi_id: KPI定義ID（マッピング済みの場合）

    Returns:
        Dict[str, Any]: マッピング情報
            - id: UUID
            - raw_product_name: str
            - kpi_id: Optional[UUID]
    """
    # 既存のマッピングを検索
    try:
        response = supabase.table("product_mappings").select(
            "id, raw_product_name, kpi_id"
        ).eq("raw_product_name", product_name).execute()

        if response.data:
            return response.data[0]
    except Exception:
        pass

    # 新規作成
    insert_data = {
        "raw_product_name": product_name,
        "kpi_id": kpi_id,
    }

    response = supabase.table("product_mappings").insert(insert_data).execute()

    if response.data:
        return response.data[0]

    raise Exception(f"商品マッピングの作成に失敗しました: {product_name}")


def aggregate_by_kpi_group(
    data: List[Dict[str, Any]],
    mappings: Dict[str, Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    """
    商品データをKPIグループ別に集計する

    個別商品データをKPIグループ（マッピングされたKPI）ごとに
    数量と売上を合計する。

    Args:
        data: パースされた商品データのリスト
        mappings: 商品名 → マッピング情報の辞書

    Returns:
        Dict[str, Dict]: KPIグループ名 → {kpi_id, total_quantity, total_sales, products}
    """
    result = {}

    for item in data:
        product_name = item["product_name"]
        mapping = mappings.get(product_name, {})
        kpi_id = mapping.get("kpi_id")

        if not kpi_id:
            continue

        if kpi_id not in result:
            result[kpi_id] = {
                "kpi_id": kpi_id,
                "total_quantity": 0,
                "total_sales": 0,
                "products": [],
            }

        result[kpi_id]["total_quantity"] += item["quantity"]
        result[kpi_id]["total_sales"] += item["sales"]
        result[kpi_id]["products"].append(product_name)

    return result


# =============================================================================
# KPI値のUpsert
# =============================================================================

async def upsert_kpi_value(
    supabase: Client,
    segment_id: str,
    kpi_id: str,
    target_date: date,
    value: Decimal,
    is_target: bool = False
) -> bool:
    """
    KPI値をUpsertする

    kpi_valuesテーブルに対してUpsert（存在すれば更新、なければ挿入）を行う。
    ユニーク制約: (segment_id, kpi_id, date, is_target)

    Args:
        supabase: Supabaseクライアント
        segment_id: セグメントID
        kpi_id: KPI定義ID
        target_date: 対象日付（月初日）
        value: 値
        is_target: 目標値(True)か実績値(False)か

    Returns:
        bool: 成功した場合True
    """
    # 既存のレコードを検索
    existing = supabase.table("kpi_values").select("id").eq(
        "segment_id", segment_id
    ).eq("kpi_id", kpi_id).eq(
        "date", target_date.isoformat()
    ).eq("is_target", is_target).execute()

    data = {
        "segment_id": segment_id,
        "kpi_id": kpi_id,
        "date": target_date.isoformat(),
        "value": float(value),
        "is_target": is_target,
    }

    if existing.data:
        # 更新
        response = supabase.table("kpi_values").update(data).eq(
            "id", existing.data[0]["id"]
        ).execute()
    else:
        # 挿入
        response = supabase.table("kpi_values").insert(data).execute()

    return bool(response.data)


# =============================================================================
# ユーティリティ
# =============================================================================

async def get_segments_for_department(
    supabase: Client,
    department_id: str
) -> List[Dict[str, Any]]:
    """
    部門に属するセグメント一覧を取得する

    Args:
        supabase: Supabaseクライアント
        department_id: 部門ID

    Returns:
        List[Dict]: セグメント情報のリスト
    """
    response = supabase.table("segments").select(
        "id, code, name"
    ).eq("department_id", department_id).execute()

    return response.data if response.data else []


async def get_kpi_definitions_for_department(
    supabase: Client,
    department_id: str
) -> List[Dict[str, Any]]:
    """
    部門に属するKPI定義一覧を取得する

    Args:
        supabase: Supabaseクライアント
        department_id: 部門ID

    Returns:
        List[Dict]: KPI定義情報のリスト
    """
    response = supabase.table("kpi_definitions").select(
        "id, name, category, unit"
    ).eq("department_id", department_id).eq("is_visible", True).order(
        "display_order"
    ).execute()

    return response.data if response.data else []
