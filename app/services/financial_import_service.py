"""
財務・製造データインポートサービスモジュール

パースした財務データ・製造データをDBに保存するサービスを提供する。
Upsert処理（既存データがあれば更新、なければ挿入）をサポート。

機能:
- 財務データのDB保存（import_financial_data）
- 製造データのDB保存（import_manufacturing_data）
- 会計年度の自動計算
"""
from datetime import date
from typing import Any, Dict, List

from supabase import Client


# =============================================================================
# 会計年度計算
# =============================================================================

def calculate_fiscal_year(target_date: date) -> int:
    """
    会計年度を計算する

    9月～翌8月を1会計年度とする。
    - 9月～12月: その年が会計年度
    - 1月～8月: 前年が会計年度

    Args:
        target_date: 対象日付

    Returns:
        会計年度（整数）
    """
    if target_date.month >= 9:
        return target_date.year
    else:
        return target_date.year - 1


# =============================================================================
# 財務データインポート
# =============================================================================

async def import_financial_data(
    supabase: Client,
    parsed_data: Dict[str, Any]
) -> Dict[str, Any]:
    """
    財務データをDBにインポートする

    financial_dataテーブルに対してUpsert処理を行う。
    ユニーク制約: (month, is_target)

    Args:
        supabase: Supabaseクライアント
        parsed_data: parse_financial_excel()の戻り値

    Returns:
        Dict[str, Any]: インポート結果
            - success: bool - 成功かどうか
            - action: str - 実行アクション（inserted/updated）
            - month: str - 対象月
            - is_target: bool - 目標値かどうか
            - errors: List[str] - エラーメッセージ
    """
    result = {
        "success": False,
        "action": None,
        "month": parsed_data.get("month"),
        "is_target": parsed_data.get("is_target", False),
        "errors": [],
    }

    month = parsed_data.get("month")
    is_target = parsed_data.get("is_target", False)
    data = parsed_data.get("data", {})

    if not month:
        result["errors"].append("対象月が指定されていません")
        return result

    if not data:
        result["errors"].append("保存するデータがありません")
        return result

    # 日付をdate型に変換
    try:
        target_date = date.fromisoformat(month)
    except ValueError:
        result["errors"].append(f"対象月の形式が不正です: {month}")
        return result

    # 会計年度を計算
    fiscal_year = calculate_fiscal_year(target_date)

    # 保存用データを構築
    record = {
        "fiscal_year": fiscal_year,
        "month": month,
        "is_target": is_target,
        **data,
    }

    try:
        # 既存データを検索
        existing = supabase.table("financial_data").select("id").eq(
            "month", month
        ).eq("is_target", is_target).execute()

        if existing.data:
            # 更新
            response = supabase.table("financial_data").update(record).eq(
                "id", existing.data[0]["id"]
            ).execute()
            result["action"] = "updated"
        else:
            # 挿入
            response = supabase.table("financial_data").insert(record).execute()
            result["action"] = "inserted"

        if response.data:
            result["success"] = True
        else:
            result["errors"].append("データの保存に失敗しました")

    except Exception as e:
        result["errors"].append(f"DB操作エラー: {str(e)}")

    return result


# =============================================================================
# 製造データインポート
# =============================================================================

async def import_manufacturing_data(
    supabase: Client,
    parsed_data: Dict[str, Any]
) -> Dict[str, Any]:
    """
    製造データをDBにインポートする

    manufacturing_dataテーブルに対して日次データをUpsert処理する。
    ユニーク制約: (date)

    Args:
        supabase: Supabaseクライアント
        parsed_data: parse_manufacturing_excel()の戻り値

    Returns:
        Dict[str, Any]: インポート結果
            - success: bool - 成功かどうか
            - imported_count: int - インポート件数
            - updated_count: int - 更新件数
            - inserted_count: int - 挿入件数
            - errors: List[str] - エラーメッセージ
            - warnings: List[str] - 警告メッセージ
    """
    result = {
        "success": False,
        "imported_count": 0,
        "updated_count": 0,
        "inserted_count": 0,
        "errors": [],
        "warnings": [],
    }

    data = parsed_data.get("data", [])

    if not data:
        result["errors"].append("保存するデータがありません")
        return result

    # 各日次データを処理
    records_to_upsert = []

    for item in data:
        try:
            row_date = item.get("date")
            if not row_date:
                continue

            # 製造量(個)の計算: バット数 × 60
            production_batts = item.get("production_batts")
            production_pieces = item.get("production_pieces")
            if production_batts and not production_pieces:
                production_pieces = production_batts * 60

            # 1人あたり製造量の計算
            workers_count = item.get("workers_count")
            production_per_worker = item.get("production_per_worker")
            if production_batts and workers_count and workers_count > 0 and not production_per_worker:
                production_per_worker = round(production_batts / workers_count, 2)

            record = {
                "date": row_date,
                "production_batts": production_batts,
                "production_pieces": production_pieces,
                "workers_count": workers_count,
                "production_per_worker": production_per_worker,
                "paid_leave_hours": item.get("paid_leave_hours"),
            }
            records_to_upsert.append(record)

        except Exception as e:
            result["errors"].append(f"データ行の処理エラー: {str(e)}")

    if not records_to_upsert:
        result["errors"].append("有効なデータがありません")
        return result

    # バルクUpsert処理
    try:
        # 既存データの日付を取得
        dates = [r["date"] for r in records_to_upsert]
        existing_response = supabase.table("manufacturing_data").select(
            "date"
        ).in_("date", dates).execute()

        existing_dates = {r["date"] for r in existing_response.data} if existing_response.data else set()

        # 挿入と更新の件数を計算
        for record in records_to_upsert:
            if record["date"] in existing_dates:
                result["updated_count"] += 1
            else:
                result["inserted_count"] += 1

        # Upsert実行
        response = supabase.table("manufacturing_data").upsert(
            records_to_upsert,
            on_conflict="date"
        ).execute()

        if response.data:
            result["success"] = True
            result["imported_count"] = len(records_to_upsert)
        else:
            result["errors"].append("データの保存に失敗しました")

    except Exception as e:
        result["errors"].append(f"DB操作エラー: {str(e)}")

    return result


# =============================================================================
# 財務データ取得
# =============================================================================

async def get_financial_data(
    supabase: Client,
    month: date,
    is_target: bool = False
) -> Dict[str, Any]:
    """
    財務データを取得する

    Args:
        supabase: Supabaseクライアント
        month: 対象月
        is_target: 目標値かどうか

    Returns:
        財務データ
    """
    try:
        response = supabase.table("financial_data").select("*").eq(
            "month", month.isoformat()
        ).eq("is_target", is_target).execute()

        if response.data:
            return response.data[0]
        return None

    except Exception as e:
        raise Exception(f"財務データの取得に失敗しました: {str(e)}")


async def get_financial_data_range(
    supabase: Client,
    start_month: date,
    end_month: date,
    is_target: bool = False
) -> List[Dict[str, Any]]:
    """
    期間指定で財務データを取得する

    Args:
        supabase: Supabaseクライアント
        start_month: 開始月
        end_month: 終了月
        is_target: 目標値かどうか

    Returns:
        財務データリスト
    """
    try:
        response = supabase.table("financial_data").select("*").gte(
            "month", start_month.isoformat()
        ).lte(
            "month", end_month.isoformat()
        ).eq("is_target", is_target).order("month").execute()

        return response.data if response.data else []

    except Exception as e:
        raise Exception(f"財務データの取得に失敗しました: {str(e)}")


# =============================================================================
# 製造データ取得
# =============================================================================

async def get_manufacturing_data(
    supabase: Client,
    target_date: date
) -> Dict[str, Any]:
    """
    製造データを取得する（日次）

    Args:
        supabase: Supabaseクライアント
        target_date: 対象日付

    Returns:
        製造データ
    """
    try:
        response = supabase.table("manufacturing_data").select("*").eq(
            "date", target_date.isoformat()
        ).execute()

        if response.data:
            return response.data[0]
        return None

    except Exception as e:
        raise Exception(f"製造データの取得に失敗しました: {str(e)}")


async def get_manufacturing_data_monthly(
    supabase: Client,
    year: int,
    month: int
) -> List[Dict[str, Any]]:
    """
    製造データを取得する（月次）

    Args:
        supabase: Supabaseクライアント
        year: 年
        month: 月

    Returns:
        製造データリスト
    """
    try:
        # 月の開始日と終了日を計算
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1)
        else:
            end_date = date(year, month + 1, 1)

        response = supabase.table("manufacturing_data").select("*").gte(
            "date", start_date.isoformat()
        ).lt(
            "date", end_date.isoformat()
        ).order("date").execute()

        return response.data if response.data else []

    except Exception as e:
        raise Exception(f"製造データの取得に失敗しました: {str(e)}")


async def get_manufacturing_monthly_summary(
    supabase: Client,
    year: int,
    month: int
) -> Dict[str, Any]:
    """
    製造データの月次サマリーを取得する（ビューから）

    Args:
        supabase: Supabaseクライアント
        year: 年
        month: 月

    Returns:
        月次サマリー
    """
    try:
        # 月初日
        month_date = date(year, month, 1).isoformat()

        response = supabase.table("view_manufacturing_monthly").select("*").eq(
            "month", month_date
        ).execute()

        if response.data:
            return response.data[0]
        return None

    except Exception as e:
        raise Exception(f"製造月次サマリーの取得に失敗しました: {str(e)}")
