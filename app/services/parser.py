"""
CSV解析サービスモジュール

CSVファイルの読み込みと解析を行うサービスを提供する。
店舗別CSV、商品別CSVの2種類をサポート。

機能:
- エンコーディング自動判定（UTF-8, Shift-JIS, CP932対応）
- 期間行のパース
- 店舗別/商品別CSVのパース
- バリデーションとエラーレポート生成
"""
import re
from datetime import date
from io import BytesIO, StringIO
from typing import Dict, Any, List, Optional, Tuple

import chardet
import pandas as pd


# =============================================================================
# エンコーディング検出
# =============================================================================

def detect_encoding(file_content: bytes) -> str:
    """
    ファイルのエンコーディングを検出する

    chardetを使用してバイト列からエンコーディングを推定する。
    日本語CSVによく使われるエンコーディングを優先的に判定。

    Args:
        file_content: ファイルの内容（バイト列）

    Returns:
        str: 検出されたエンコーディング名
    """
    # chardetで検出
    result = chardet.detect(file_content)
    detected = result.get("encoding", "utf-8")
    confidence = result.get("confidence", 0)

    # 日本語エンコーディングの正規化
    if detected:
        detected_lower = detected.lower()
        # Shift-JIS系の統一
        if detected_lower in ("shift_jis", "shift-jis", "sjis", "s-jis"):
            return "cp932"
        # ISO-2022-JP
        if detected_lower == "iso-2022-jp":
            return "iso-2022-jp"
        # EUC-JP
        if detected_lower in ("euc-jp", "eucjp"):
            return "euc-jp"

    # 信頼度が低い場合はUTF-8を試す
    if confidence < 0.7:
        try:
            file_content.decode("utf-8")
            return "utf-8"
        except UnicodeDecodeError:
            pass

        # CP932（Windows日本語）を試す
        try:
            file_content.decode("cp932")
            return "cp932"
        except UnicodeDecodeError:
            pass

    return detected if detected else "utf-8"


# =============================================================================
# 期間パース
# =============================================================================

def parse_period(period_str: str) -> Optional[date]:
    """
    期間文字列から対象月の開始日を抽出する

    "2025年4月1日～2025年4月30日" 形式の文字列から
    開始日（2025-04-01）を抽出する。

    Args:
        period_str: 期間文字列（例: "期間,2025年4月1日～2025年4月30日"）

    Returns:
        Optional[date]: 対象月の開始日、パース失敗時はNone
    """
    # 期間文字列から日付部分を抽出
    # パターン: YYYY年M月D日
    pattern = r"(\d{4})年(\d{1,2})月(\d{1,2})日"
    matches = re.findall(pattern, period_str)

    if not matches:
        return None

    # 最初の日付（開始日）を使用
    year, month, day = matches[0]
    try:
        return date(int(year), int(month), 1)  # 月初日に正規化
    except ValueError:
        return None


# =============================================================================
# 店舗別CSVパース
# =============================================================================

def parse_store_csv(file_content: bytes) -> Dict[str, Any]:
    """
    店舗別CSVをパースする（POS出力形式対応）

    POSシステムからのCSV形式:
    - 1行目: 期間情報（"期間：2025年11月01日00時00分～2025年11月30日23時59分"）
    - 2行目: メタ情報（"全店舗  並び順=店舗番号順"）※スキップ
    - 3行目: ヘッダー（店舗CD,店舗名称,今年度(小計),今年度(客数),...）
    - 4行目以降: データ

    Args:
        file_content: CSVファイルの内容（バイト列）

    Returns:
        Dict[str, Any]: パース結果
            - success: bool - 成功かどうか
            - period: date - 対象期間
            - data: List[Dict] - パースされたデータ
            - errors: List[str] - エラーメッセージ
            - warnings: List[str] - 警告メッセージ
    """
    result = {
        "success": False,
        "period": None,
        "data": [],
        "errors": [],
        "warnings": [],
    }

    # エンコーディング検出
    encoding = detect_encoding(file_content)

    try:
        # バイト列を文字列にデコード
        content = file_content.decode(encoding)
        lines = content.strip().split("\n")

        if len(lines) < 4:
            result["errors"].append("CSVファイルの行数が不足しています（最低4行必要）")
            return result

        # 1行目: 期間情報
        period_line = lines[0]
        period = parse_period(period_line)
        if not period:
            result["errors"].append(
                f"期間情報のパースに失敗しました: {period_line[:50]}..."
            )
            return result
        result["period"] = period

        # 2行目: メタ情報（スキップ）
        # 3行目以降をDataFrameとして読み込み（3行目がヘッダー）
        csv_content = "\n".join(lines[2:])
        df = pd.read_csv(StringIO(csv_content), dtype=str)

        # 必須カラムの確認
        required_columns = ["店舗CD", "店舗名称"]
        # 売上カラム（複数パターン対応 - POS形式含む）
        sales_columns = [
            "今年度(小計)",      # POS形式
            "今年度(税込小計)",
            "今年度（税込小計）",
            "今年度（小計）",
            "税込小計",
            "小計",
        ]
        # 客数カラム（複数パターン対応）
        customer_columns = [
            "今年度(客数)",
            "今年度（客数）",
            "客数",
        ]

        missing = []
        for col in required_columns:
            if col not in df.columns:
                missing.append(col)

        # 売上カラムの特定
        sales_col = None
        for col in sales_columns:
            if col in df.columns:
                sales_col = col
                break
        if not sales_col:
            missing.append("今年度(小計)")

        # 客数カラムの特定
        customer_col = None
        for col in customer_columns:
            if col in df.columns:
                customer_col = col
                break
        if not customer_col:
            missing.append("今年度(客数)")

        if missing:
            result["errors"].append(f"必須カラムがありません: {', '.join(missing)}")
            return result

        # データ行のパース
        for idx, row in df.iterrows():
            row_num = idx + 4  # 期間行 + メタ行 + ヘッダー行 + 0始まりインデックス

            try:
                store_code = str(row["店舗CD"]).strip()
                store_name = str(row["店舗名称"]).strip()

                # 空行スキップ
                if not store_code or store_code.lower() == "nan":
                    continue

                # 売上のパース（カンマ除去、数値変換）
                sales_str = str(row[sales_col]).replace(",", "").strip()
                try:
                    sales = int(float(sales_str)) if sales_str and sales_str.lower() != "nan" else 0
                except ValueError:
                    result["errors"].append(
                        f"{row_num}行目: 売上が数値ではありません: {sales_str}"
                    )
                    continue

                # 客数のパース
                customers_str = str(row[customer_col]).replace(",", "").strip()
                try:
                    customers = int(float(customers_str)) if customers_str and customers_str.lower() != "nan" else 0
                except ValueError:
                    result["errors"].append(
                        f"{row_num}行目: 客数が数値ではありません: {customers_str}"
                    )
                    continue

                # バリデーション
                if sales < 0:
                    result["warnings"].append(
                        f"{row_num}行目: 売上がマイナスです: {sales}"
                    )
                if customers < 0:
                    result["warnings"].append(
                        f"{row_num}行目: 客数がマイナスです: {customers}"
                    )

                result["data"].append({
                    "store_code": store_code,
                    "store_name": store_name,
                    "sales": sales,
                    "customers": customers,
                })

            except Exception as e:
                result["errors"].append(f"{row_num}行目: パースエラー: {str(e)}")

        if not result["data"]:
            result["errors"].append("有効なデータ行がありません")
            return result

        result["success"] = len(result["errors"]) == 0

    except UnicodeDecodeError as e:
        result["errors"].append(f"ファイルのエンコーディングエラー: {str(e)}")
    except Exception as e:
        result["errors"].append(f"CSVパースエラー: {str(e)}")

    return result


# =============================================================================
# 商品別CSVパース（POS形式対応）
# =============================================================================

def parse_product_csv(file_content: bytes) -> Dict[str, Any]:
    """
    商品別CSVをパースする（POS出力形式対応）

    POSシステムからのCSV形式:
    - 1行目: 期間情報（"期間：2025年11月01日00時00分～2025年11月30日23時59分"）
    - 2行目: メタ情報（"本社  並び順=商品番号順"）※スキップ
    - 3行目: ヘッダー（店舗CD,店舗名,商品CD,商品名,商品大分類CD,商品大分類名,...）
    - 4行目以降: データ（店舗別×商品別）

    Args:
        file_content: CSVファイルの内容（バイト列）

    Returns:
        Dict[str, Any]: パース結果
            - success: bool - 成功かどうか
            - period: date - 対象期間
            - data: List[Dict] - パースされたデータ（店舗別×商品別）
            - errors: List[str] - エラーメッセージ
            - warnings: List[str] - 警告メッセージ
    """
    result = {
        "success": False,
        "period": None,
        "data": [],
        "errors": [],
        "warnings": [],
    }

    # エンコーディング検出
    encoding = detect_encoding(file_content)

    try:
        # バイト列を文字列にデコード
        content = file_content.decode(encoding)
        lines = content.strip().split("\n")

        if len(lines) < 4:
            result["errors"].append("CSVファイルの行数が不足しています（最低4行必要）")
            return result

        # 1行目: 期間情報
        period_line = lines[0]
        period = parse_period(period_line)
        if not period:
            result["errors"].append(
                f"期間情報のパースに失敗しました: {period_line[:50]}..."
            )
            return result
        result["period"] = period

        # 2行目: メタ情報（スキップ）
        # 3行目以降をDataFrameとして読み込み（3行目がヘッダー）
        csv_content = "\n".join(lines[2:])
        df = pd.read_csv(StringIO(csv_content), dtype=str)

        # 必須カラムの確認（POS形式に対応）
        required_mapping = {
            "店舗CD": ["店舗CD", "店舗コード"],
            "店舗名": ["店舗名", "店舗名称"],
            "商品CD": ["商品CD", "商品コード"],
            "商品名": ["商品名", "商品名称"],
            "大分類名": ["商品大分類名", "大分類名", "大分類"],
            "件数": ["件数", "数量", "販売数量"],
            "税込小計": ["税込小計", "税込売上", "売上"],
        }

        # オプションカラム（あれば取得）
        optional_mapping = {
            "大分類CD": ["商品大分類CD", "大分類CD", "大分類コード"],
            "中分類CD": ["商品中分類CD", "中分類CD", "中分類コード"],
            "中分類名": ["商品中分類名", "中分類名", "中分類"],
            "税抜小計": ["税抜小計", "税抜売上"],
            "消費税": ["消費税", "消費税額"],
        }

        column_map = {}
        missing = []

        for key, candidates in required_mapping.items():
            found = False
            for col in candidates:
                if col in df.columns:
                    column_map[key] = col
                    found = True
                    break
            if not found:
                missing.append(key)

        if missing:
            result["errors"].append(f"必須カラムがありません: {', '.join(missing)}")
            return result

        # オプションカラムの検出
        optional_map = {}
        for key, candidates in optional_mapping.items():
            for col in candidates:
                if col in df.columns:
                    optional_map[key] = col
                    break

        # データ行のパース
        for idx, row in df.iterrows():
            row_num = idx + 4  # 期間行 + メタ行 + ヘッダー行 + 0始まりインデックス

            try:
                store_code = str(row[column_map["店舗CD"]]).strip()
                store_name = str(row[column_map["店舗名"]]).strip()
                product_code = str(row[column_map["商品CD"]]).strip()
                product_name = str(row[column_map["商品名"]]).strip()
                category = str(row[column_map["大分類名"]]).strip()

                # 空行スキップ
                if not product_name or product_name.lower() == "nan":
                    continue

                # 件数のパース
                quantity_str = str(row[column_map["件数"]]).replace(",", "").strip()
                try:
                    quantity = int(float(quantity_str)) if quantity_str and quantity_str.lower() != "nan" else 0
                except ValueError:
                    result["errors"].append(
                        f"{row_num}行目: 件数が数値ではありません: {quantity_str}"
                    )
                    continue

                # 売上のパース
                sales_str = str(row[column_map["税込小計"]]).replace(",", "").strip()
                try:
                    sales = int(float(sales_str)) if sales_str and sales_str.lower() != "nan" else 0
                except ValueError:
                    result["errors"].append(
                        f"{row_num}行目: 税込小計が数値ではありません: {sales_str}"
                    )
                    continue

                # オプション項目のパース
                category_code = None
                if "大分類CD" in optional_map:
                    val = str(row[optional_map["大分類CD"]]).strip()
                    category_code = val if val.lower() != "nan" else None

                subcategory_code = None
                if "中分類CD" in optional_map:
                    val = str(row[optional_map["中分類CD"]]).strip()
                    subcategory_code = val if val.lower() != "nan" else None

                subcategory_name = None
                if "中分類名" in optional_map:
                    val = str(row[optional_map["中分類名"]]).strip()
                    subcategory_name = val if val.lower() != "nan" else None

                sales_without_tax = None
                if "税抜小計" in optional_map:
                    val_str = str(row[optional_map["税抜小計"]]).replace(",", "").strip()
                    try:
                        sales_without_tax = int(float(val_str)) if val_str and val_str.lower() != "nan" else None
                    except ValueError:
                        pass

                tax_amount = None
                if "消費税" in optional_map:
                    val_str = str(row[optional_map["消費税"]]).replace(",", "").strip()
                    try:
                        tax_amount = int(float(val_str)) if val_str and val_str.lower() != "nan" else None
                    except ValueError:
                        pass

                # バリデーション
                if quantity < 0:
                    result["warnings"].append(
                        f"{row_num}行目: 件数がマイナスです: {quantity}"
                    )
                if sales < 0:
                    result["warnings"].append(
                        f"{row_num}行目: 売上がマイナスです: {sales}"
                    )

                result["data"].append({
                    "store_code": store_code,
                    "store_name": store_name,
                    "product_code": product_code,
                    "product_name": product_name,
                    "category": category,
                    "category_code": category_code,
                    "subcategory_code": subcategory_code,
                    "subcategory_name": subcategory_name,
                    "quantity": quantity,
                    "sales": sales,
                    "sales_without_tax": sales_without_tax,
                    "tax_amount": tax_amount,
                })

            except Exception as e:
                result["errors"].append(f"{row_num}行目: パースエラー: {str(e)}")

        if not result["data"]:
            result["errors"].append("有効なデータ行がありません")
            return result

        result["success"] = len(result["errors"]) == 0

    except UnicodeDecodeError as e:
        result["errors"].append(f"ファイルのエンコーディングエラー: {str(e)}")
    except Exception as e:
        result["errors"].append(f"CSVパースエラー: {str(e)}")

    return result


# =============================================================================
# バリデーション
# =============================================================================

def validate_store_data(
    data: List[Dict[str, Any]],
    existing_segments: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    店舗データのバリデーション

    店舗CDがDBに存在するか検証し、存在する店舗のデータのみを返す。

    Args:
        data: パースされた店舗データのリスト
        existing_segments: DBに存在するセグメント（店舗）のリスト

    Returns:
        Tuple[List[Dict], List[str]]: (有効なデータ, 警告メッセージ)
    """
    # 既存の店舗コードセット
    existing_codes = {str(seg["code"]) for seg in existing_segments}

    valid_data = []
    warnings = []

    # 重複チェック用
    seen_codes = set()

    for item in data:
        store_code = item["store_code"]

        # 重複チェック
        if store_code in seen_codes:
            warnings.append(f"店舗CD {store_code} が重複しています")
            continue
        seen_codes.add(store_code)

        # 存在チェック
        if store_code not in existing_codes:
            warnings.append(f"店舗CD {store_code} はマスタに存在しません")
            continue

        valid_data.append(item)

    return valid_data, warnings


def validate_product_data(data: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    商品データのバリデーション

    必須項目の存在チェックと数値の妥当性チェックを行う。

    Args:
        data: パースされた商品データのリスト

    Returns:
        Tuple[List[Dict], List[str]]: (有効なデータ, 警告メッセージ)
    """
    valid_data = []
    warnings = []

    for item in data:
        # 空の商品名チェック
        if not item.get("product_name"):
            warnings.append("商品名が空のデータがあります")
            continue

        # 空のカテゴリチェック
        if not item.get("category"):
            warnings.append(f"商品「{item['product_name']}」のカテゴリが空です")
            # カテゴリなしでも登録は許可（未分類扱い）
            item["category"] = "未分類"

        valid_data.append(item)

    return valid_data, warnings


# =============================================================================
# ユーティリティ
# =============================================================================

def extract_product_names(df: pd.DataFrame, column_name: str = "商品名") -> List[str]:
    """
    DataFrameから商品名を抽出する

    Args:
        df: 対象のDataFrame
        column_name: 商品名カラム名

    Returns:
        List[str]: 商品名のリスト（重複なし）
    """
    if column_name not in df.columns:
        return []

    names = df[column_name].dropna().unique().tolist()
    return [str(name).strip() for name in names if str(name).strip()]
