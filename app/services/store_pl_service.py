"""
店舗別収支インポートサービス

店舗別収支データのExcel/CSVからのパースとDBへの保存を行う。

機能:
- Excel/CSVファイルのパース
- 店舗コードとsegment_idの紐付け
- store_plテーブルへのUpsert
- store_pl_sga_detailsテーブルへの保存
"""
import io
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from supabase import Client

from app.services.file_reader import (
    detect_file_type,
    detect_encoding,
    read_excel_file,
    read_csv_file,
)
from app.services.cache_service import cache


# =============================================================================
# カラムマッピング
# =============================================================================

# 日本語カラム名 → 内部カラム名のマッピング
COLUMN_MAPPING = {
    # 店舗識別
    "店舗コード": "store_code",
    "店舗CD": "store_code",
    "店舗番号": "store_code",
    "店舗名": "store_name",
    "店舗名称": "store_name",

    # 期間
    "期間": "period",
    "年月": "period",
    "対象月": "period",

    # 収支項目
    "売上高": "sales",
    "売上": "sales",
    "売上原価": "cost_of_sales",
    "原価": "cost_of_sales",
    "売上総利益": "gross_profit",
    "粗利": "gross_profit",
    "粗利益": "gross_profit",
    "販管費": "sga_total",
    "販管費合計": "sga_total",
    "販売管理費": "sga_total",
    "営業利益": "operating_profit",

    # 販管費明細
    "人件費": "sga_personnel_cost",
    "地代家賃": "sga_land_rent",
    "賃借料": "sga_lease_cost",
    "水道光熱費": "sga_utilities",

    # データ区分
    "データ区分": "data_type",
    "区分": "data_type",
}


# =============================================================================
# パース関数
# =============================================================================

def parse_store_pl_file(
    file_content: bytes,
    filename: str = "",
) -> Dict[str, Any]:
    """
    店舗別収支ファイルをパースする

    Args:
        file_content: ファイル内容（バイト列）
        filename: ファイル名

    Returns:
        Dict[str, Any]: パース結果
            - success: bool
            - period: str (YYYY-MM-01形式)
            - is_target: bool
            - data: List[Dict]
            - errors: List[Dict]
            - warnings: List[str]
    """
    result = {
        "success": False,
        "period": None,
        "is_target": False,
        "data": [],
        "errors": [],
        "warnings": [],
    }

    try:
        # ファイル形式を判定
        file_type = detect_file_type(filename)

        # データフレームとして読み込み
        if file_type in ("xlsx", "xls"):
            df, warnings = read_excel_file(file_content, file_type, header=0)
            result["warnings"].extend(warnings)
        elif file_type == "csv":
            df, warnings = read_csv_file(file_content, header=0)
            result["warnings"].extend(warnings)
        else:
            # バイナリ判定で再試行
            if file_content[:4] == b'PK\x03\x04':
                df, warnings = read_excel_file(file_content, "xlsx", header=0)
                result["warnings"].extend(warnings)
            elif file_content[:4] == b'\xd0\xcf\x11\xe0':
                df, warnings = read_excel_file(file_content, "xls", header=0)
                result["warnings"].extend(warnings)
            else:
                result["errors"].append({
                    "row": None,
                    "column": None,
                    "message": f"サポートされていないファイル形式です: {filename}",
                    "value": None,
                })
                return result

        # カラム名を正規化
        df = _normalize_columns(df)

        # 必須カラムの確認
        required_columns = ["store_code", "sales"]
        missing = [col for col in required_columns if col not in df.columns]
        if missing:
            result["errors"].append({
                "row": None,
                "column": None,
                "message": f"必須カラムがありません: {', '.join(missing)}",
                "value": None,
            })
            return result

        # 期間を特定
        period = _extract_period(df)
        if period:
            result["period"] = period.isoformat()
        else:
            result["warnings"].append("期間情報が見つかりません。各行の期間カラムから取得します。")

        # データ区分を特定
        if "data_type" in df.columns:
            first_type = df["data_type"].dropna().iloc[0] if len(df["data_type"].dropna()) > 0 else None
            if first_type and str(first_type).strip() in ["予算", "目標", "計画"]:
                result["is_target"] = True

        # 各行をパース
        for idx, row in df.iterrows():
            row_num = idx + 2  # ヘッダー行を考慮

            try:
                parsed_row = _parse_row(row, row_num, result)
                if parsed_row:
                    # 期間が行ごとにある場合はそれを使用
                    if not result["period"] and parsed_row.get("period"):
                        result["period"] = parsed_row["period"]
                    result["data"].append(parsed_row)
            except Exception as e:
                result["errors"].append({
                    "row": row_num,
                    "column": None,
                    "message": f"行のパースに失敗: {str(e)}",
                    "value": None,
                })

        if not result["data"]:
            result["errors"].append({
                "row": None,
                "column": None,
                "message": "有効なデータがありません",
                "value": None,
            })
            return result

        result["success"] = len(result["errors"]) == 0

    except Exception as e:
        result["errors"].append({
            "row": None,
            "column": None,
            "message": f"ファイルの解析に失敗しました: {str(e)}",
            "value": None,
        })

    return result


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """カラム名を正規化する"""
    new_columns = {}
    for col in df.columns:
        col_str = str(col).strip()
        if col_str in COLUMN_MAPPING:
            new_columns[col] = COLUMN_MAPPING[col_str]
        else:
            new_columns[col] = col_str.lower().replace(" ", "_")
    return df.rename(columns=new_columns)


def _extract_period(df: pd.DataFrame) -> Optional[date]:
    """データフレームから期間を抽出する"""
    # periodカラムがあればそこから取得
    if "period" in df.columns:
        for val in df["period"].dropna():
            period = _parse_period_value(val)
            if period:
                return period

    return None


def _parse_period_value(value: Any) -> Optional[date]:
    """期間値をパースする"""
    if value is None:
        return None

    if isinstance(value, date):
        return date(value.year, value.month, 1)

    if isinstance(value, pd.Timestamp):
        return date(value.year, value.month, 1)

    if isinstance(value, str):
        value = value.strip()

        # "2025年11月" 形式
        match = re.match(r"(\d{4})年(\d{1,2})月?", value)
        if match:
            return date(int(match.group(1)), int(match.group(2)), 1)

        # "2025/11" または "2025-11" 形式
        match = re.match(r"(\d{4})[/-](\d{1,2})", value)
        if match:
            return date(int(match.group(1)), int(match.group(2)), 1)

        # "2025/11/01" または "2025-11-01" 形式
        match = re.match(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", value)
        if match:
            return date(int(match.group(1)), int(match.group(2)), 1)

    return None


def _parse_row(
    row: pd.Series,
    row_num: int,
    result: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """1行をパースする"""
    # 店舗コードを取得
    store_code = row.get("store_code")
    if pd.isna(store_code) or str(store_code).strip() == "":
        return None

    store_code = str(store_code).strip()

    # 店舗名を取得
    store_name = row.get("store_name", "")
    if pd.notna(store_name):
        store_name = str(store_name).strip()
    else:
        store_name = ""

    # 数値項目をパース
    sales = _parse_decimal(row.get("sales"), row_num, "売上高", result)
    cost_of_sales = _parse_decimal(row.get("cost_of_sales"), row_num, "売上原価", result)
    gross_profit = _parse_decimal(row.get("gross_profit"), row_num, "売上総利益", result)
    sga_total = _parse_decimal(row.get("sga_total"), row_num, "販管費", result)
    operating_profit = _parse_decimal(row.get("operating_profit"), row_num, "営業利益", result)

    # 売上総利益が未設定の場合は計算
    if gross_profit is None and sales is not None and cost_of_sales is not None:
        gross_profit = sales - cost_of_sales

    # 営業利益が未設定の場合は計算
    if operating_profit is None and gross_profit is not None and sga_total is not None:
        operating_profit = gross_profit - sga_total

    # 販管費明細
    sga_personnel_cost = _parse_decimal(row.get("sga_personnel_cost"), row_num, "人件費", result)
    sga_land_rent = _parse_decimal(row.get("sga_land_rent"), row_num, "地代家賃", result)
    sga_lease_cost = _parse_decimal(row.get("sga_lease_cost"), row_num, "賃借料", result)
    sga_utilities = _parse_decimal(row.get("sga_utilities"), row_num, "水道光熱費", result)

    # 期間
    period = None
    if "period" in row.index and pd.notna(row.get("period")):
        period = _parse_period_value(row.get("period"))

    return {
        "store_code": store_code,
        "store_name": store_name,
        "period": period.isoformat() if period else None,
        "sales": float(sales) if sales is not None else 0,
        "cost_of_sales": float(cost_of_sales) if cost_of_sales is not None else 0,
        "gross_profit": float(gross_profit) if gross_profit is not None else 0,
        "sga_total": float(sga_total) if sga_total is not None else 0,
        "operating_profit": float(operating_profit) if operating_profit is not None else 0,
        "sga_personnel_cost": float(sga_personnel_cost) if sga_personnel_cost is not None else None,
        "sga_land_rent": float(sga_land_rent) if sga_land_rent is not None else None,
        "sga_lease_cost": float(sga_lease_cost) if sga_lease_cost is not None else None,
        "sga_utilities": float(sga_utilities) if sga_utilities is not None else None,
    }


def _parse_decimal(
    value: Any,
    row_num: int,
    column_name: str,
    result: Dict[str, Any]
) -> Optional[Decimal]:
    """数値をパースする"""
    if value is None or pd.isna(value):
        return None

    try:
        if isinstance(value, (int, float)):
            return Decimal(str(value))

        # 文字列の場合
        value_str = str(value).strip()
        # カンマ、円記号を除去
        value_str = value_str.replace(",", "").replace("円", "").replace("¥", "")

        if value_str == "" or value_str.lower() == "nan":
            return None

        return Decimal(value_str)

    except (InvalidOperation, ValueError):
        result["warnings"].append(f"{row_num}行目: {column_name}の値が不正です: {value}")
        return None


# =============================================================================
# インポート関数
# =============================================================================

async def import_store_pl_data(
    supabase: Client,
    parsed_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    店舗別収支データをDBにインポートする

    Args:
        supabase: Supabaseクライアント
        parsed_data: parse_store_pl_file()の戻り値

    Returns:
        Dict[str, Any]: インポート結果
    """
    result = {
        "success": False,
        "imported_count": 0,
        "updated_count": 0,
        "inserted_count": 0,
        "errors": [],
        "warnings": [],
    }

    period_str = parsed_data.get("period")
    is_target = parsed_data.get("is_target", False)
    data = parsed_data.get("data", [])

    if not period_str:
        result["errors"].append({
            "row": None,
            "column": None,
            "message": "期間が指定されていません",
            "value": None,
        })
        return result

    if not data:
        result["errors"].append({
            "row": None,
            "column": None,
            "message": "インポートするデータがありません",
            "value": None,
        })
        return result

    try:
        # 店舗コードからsegment_idへのマッピングを取得
        segment_map = await _get_segment_map(supabase)

        # 各行を処理
        for item in data:
            store_code = item.get("store_code")
            if not store_code:
                continue

            segment_id = segment_map.get(store_code)
            if not segment_id:
                result["warnings"].append(f"店舗コード '{store_code}' はマスタに存在しません")
                continue

            # 行の期間があればそれを使用、なければ全体の期間を使用
            row_period = item.get("period") or period_str

            try:
                # 既存データを検索
                existing = supabase.table("store_pl").select("id").eq(
                    "segment_id", segment_id
                ).eq("period", row_period).eq("is_target", is_target).execute()

                # レコードデータを構築
                record = {
                    "segment_id": segment_id,
                    "period": row_period,
                    "is_target": is_target,
                    "sales": item.get("sales", 0),
                    "cost_of_sales": item.get("cost_of_sales", 0),
                    "gross_profit": item.get("gross_profit", 0),
                    "sga_total": item.get("sga_total", 0),
                    "operating_profit": item.get("operating_profit", 0),
                }

                if existing.data:
                    # 更新
                    store_pl_id = existing.data[0]["id"]
                    supabase.table("store_pl").update(record).eq("id", store_pl_id).execute()
                    result["updated_count"] += 1

                    # 販管費明細を更新
                    await _upsert_sga_details(supabase, store_pl_id, item)
                else:
                    # 挿入
                    insert_response = supabase.table("store_pl").insert(record).execute()
                    if insert_response.data:
                        store_pl_id = insert_response.data[0]["id"]
                        result["inserted_count"] += 1

                        # 販管費明細を挿入
                        await _upsert_sga_details(supabase, store_pl_id, item)

                result["imported_count"] += 1

            except Exception as e:
                result["errors"].append({
                    "row": None,
                    "column": None,
                    "message": f"店舗 '{store_code}' のインポートに失敗: {str(e)}",
                    "value": None,
                })

        # 成功時にキャッシュクリア
        if result["imported_count"] > 0:
            cache.clear_prefix("store_pl")
            cache.clear_prefix("financial")
            result["success"] = True

    except Exception as e:
        result["errors"].append({
            "row": None,
            "column": None,
            "message": f"インポート処理エラー: {str(e)}",
            "value": None,
        })

    return result


async def _get_segment_map(supabase: Client) -> Dict[str, str]:
    """店舗コードからsegment_idへのマッピングを取得する"""
    response = supabase.table("segments").select("id, code").execute()

    segment_map = {}
    if response.data:
        for seg in response.data:
            code = seg.get("code")
            if code:
                segment_map[str(code)] = seg["id"]

    return segment_map


async def _upsert_sga_details(
    supabase: Client,
    store_pl_id: str,
    item: Dict[str, Any]
) -> None:
    """販管費明細を挿入/更新する"""
    # 明細項目があるかチェック
    has_details = any([
        item.get("sga_personnel_cost"),
        item.get("sga_land_rent"),
        item.get("sga_lease_cost"),
        item.get("sga_utilities"),
    ])

    if not has_details:
        return

    # 既存の明細を検索
    existing = supabase.table("store_pl_sga_details").select("id").eq(
        "store_pl_id", store_pl_id
    ).execute()

    detail_record = {
        "store_pl_id": store_pl_id,
        "personnel_cost": item.get("sga_personnel_cost") or 0,
        "land_rent": item.get("sga_land_rent") or 0,
        "lease_cost": item.get("sga_lease_cost") or 0,
        "utilities": item.get("sga_utilities") or 0,
    }

    if existing.data:
        # 更新
        supabase.table("store_pl_sga_details").update(detail_record).eq(
            "id", existing.data[0]["id"]
        ).execute()
    else:
        # 挿入
        supabase.table("store_pl_sga_details").insert(detail_record).execute()
