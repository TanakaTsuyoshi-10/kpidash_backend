"""
レシートジャーナルCSV解析サービス

POSレシートジャーナルCSVを解析し、店舗×時間帯×商品の販売データを抽出する。

CSVフォーマット:
- エンコーディング: Shift-JIS (cp932)
- 1行目: 期間情報 (例: "販売日：2026年3月1日(日) ～ 2026年3月3日(火)")
- 2行目: "全店舗" 等のメタ行
- 3行目: ヘッダー（販売日時,レシート番号,レジ担当者,決済種別,掛売先,JANコード,商品名,販売単価,税区分,数量,小計,...）
- 4行目以降: データ行（引用符付きフィールドあり）
"""
import csv
import io
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Dict, Any, List, Optional, Tuple

import chardet


# =============================================================================
# エンコーディング検出
# =============================================================================

def detect_encoding(file_content: bytes) -> str:
    """chardetでエンコーディングを検出し、cp932系はcp932に統一する"""
    result = chardet.detect(file_content)
    encoding = (result.get("encoding") or "cp932").lower()
    if encoding in ("shift_jis", "shift-jis", "sjis", "windows-31j"):
        return "cp932"
    return encoding


# =============================================================================
# 商品グループマッピング
# =============================================================================

# 商品名パターン → 商品グループ（順序が重要：先にマッチしたものが優先）
PRODUCT_GROUP_RULES: List[Tuple[str, str]] = [
    # 宅配しょうが（宅配+しょうがの両方を含む → 宅配優先）
    (r"宅配.*生姜|宅配.*しょうが", "宅配"),
    # しょうが入ぎょうざ（ぎょうざより先に判定）
    (r"生姜入|しょうが入|ショウガ入", "しょうが入ぎょうざ"),
    # 宅配系
    (r"宅配", "宅配"),
    # ぎょうざ本体（全角・半角数字対応）
    (r"ぎょうざ[０-９\d]+個|餃子[０-９\d]+個|ギョーザ[０-９\d]+個", "ぎょうざ"),
    # 付属品（たれ・スープ・調味料類）
    (r"丸岡のたれ", "付属品"),
    (r"水スープ|水ｽｰﾌﾟ", "付属品"),
    (r"柚子胡椒たれ|ゆずこしょう", "付属品"),
    (r"ラーユ|ラー油|らーゆ", "付属品"),
    (r"日向夏たれ|日向夏", "付属品"),
    (r"味噌たれ", "付属品"),
    (r"鍋の素|鍋すうぷ|鍋スープ|中華風餃子鍋", "付属品"),
    (r"たれ|タレ|スープ", "付属品"),
    # 箱・保冷箱・トレー
    (r"保冷箱", "箱/保冷箱"),
    (r"\d+個用箱|個用箱", "箱/保冷箱"),
    (r"トレー", "箱/保冷箱"),
    # その他（袋、保冷剤、配送料）
    (r"袋", "その他"),
    (r"保冷剤", "その他"),
    (r"配送料|送料|運賃", "その他"),
    # 地域名+数字パターン = 配送料（例: 中部北陸1352, 九州中国1148）
    (r"^(中部|九州|四国|北海道|沖縄|南北|信越|東海|関東|関西|東北|北陸)", "その他"),
]

# コンパイル済みパターン
_COMPILED_RULES = [(re.compile(pattern), group) for pattern, group in PRODUCT_GROUP_RULES]


def get_product_group(product_name: str) -> str:
    """商品名から商品グループを判定する"""
    for pattern, group in _COMPILED_RULES:
        if pattern.search(product_name):
            return group
    return "その他"


# =============================================================================
# 期間パース
# =============================================================================

def parse_period_line(line: str) -> Optional[Tuple[date, date]]:
    """
    1行目の期間行をパースする

    例: "販売日：2026年3月1日(日) ～ 2026年3月3日(火)"
    例: "販売日：2026年03月01日(日) ～ 2026年03月03日(火)"
    """
    date_pattern = r"(\d{4})年(\d{1,2})月(\d{1,2})日"
    matches = re.findall(date_pattern, line)

    if len(matches) >= 2:
        try:
            start_date = date(int(matches[0][0]), int(matches[0][1]), int(matches[0][2]))
            end_date = date(int(matches[1][0]), int(matches[1][1]), int(matches[1][2]))
            return (start_date, end_date)
        except ValueError:
            pass

    if len(matches) == 1:
        try:
            d = date(int(matches[0][0]), int(matches[0][1]), int(matches[0][2]))
            return (d, d)
        except ValueError:
            pass

    return None


# =============================================================================
# 店舗コード抽出
# =============================================================================

def extract_store_code(receipt_no: str) -> Optional[str]:
    """
    レシート番号から店舗コードを抽出する

    例: "No.25-251-260301090520" → "25"
    例: "No.3-31-260301092930" → "3"
    """
    match = re.match(r"No\.(\d+)-", receipt_no)
    if match:
        return match.group(1)
    return None


# =============================================================================
# 販売日時パース
# =============================================================================

def parse_sale_datetime(dt_str: str) -> Optional[Tuple[date, int]]:
    """
    販売日時文字列をパースする（引用符を除去してからパース）

    例: '"2026年03月01日(日) 09:05"' → (date(2026,3,1), 9)
    例: "2026年3月1日(日) 9:05" → (date(2026,3,1), 9)
    """
    # 前後の引用符・空白を除去
    cleaned = dt_str.strip().strip('"').strip("'").strip()

    # re.search を使って文字列中のどこかにパターンがあれば取得
    match = re.search(
        r"(\d{4})年(\d{1,2})月(\d{1,2})日\([^)]*\)\s*(\d{1,2}):(\d{2})",
        cleaned
    )
    if match:
        try:
            y = int(match.group(1))
            m = int(match.group(2))
            d = int(match.group(3))
            h = int(match.group(4))
            return (date(y, m, d), h)
        except ValueError:
            pass
    return None


# =============================================================================
# 数値パース
# =============================================================================

def parse_number(value: str) -> Decimal:
    """
    数値文字列をパースする（カンマ区切り、マイナス対応）

    例: "930.0000" → 930
    例: "1,200" → 1200
    例: "-500" → -500
    """
    if not value or not value.strip():
        return Decimal(0)

    cleaned = value.strip().strip('"')
    cleaned = cleaned.replace("¥", "").replace("￥", "")
    cleaned = cleaned.replace(",", "")
    cleaned = cleaned.replace(" ", "").replace("　", "")

    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return Decimal(0)


# =============================================================================
# CSV行パース（引用符付きフィールド対応）
# =============================================================================

def parse_csv_line(line: str) -> List[str]:
    """
    CSV行を正しくパースする（引用符内のカンマを考慮）

    Python csv モジュールを使用して、"1,070" のようなフィールドを正しく処理する。
    """
    reader = csv.reader(io.StringIO(line))
    for row in reader:
        return row
    return []


# =============================================================================
# メインパース関数
# =============================================================================

def parse_receipt_journal(file_content: bytes, filename: str = "") -> Dict[str, Any]:
    """
    レシートジャーナルCSVをパースする

    Args:
        file_content: ファイルの内容（バイト列）
        filename: ファイル名（ログ用）

    Returns:
        Dict[str, Any]:
            - success: bool - パース成功/失敗
            - start_date: Optional[date] - 期間開始日
            - end_date: Optional[date] - 期間終了日
            - transactions: List[Dict] - トランザクションデータ
            - errors: List[str] - エラーメッセージ
            - warnings: List[str] - 警告メッセージ
    """
    result: Dict[str, Any] = {
        "success": False,
        "start_date": None,
        "end_date": None,
        "transactions": [],
        "errors": [],
        "warnings": [],
    }

    if not file_content:
        result["errors"].append("ファイルが空です")
        return result

    # エンコーディング検出
    encoding = detect_encoding(file_content)

    try:
        text = file_content.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        try:
            text = file_content.decode("cp932")
        except UnicodeDecodeError:
            result["errors"].append("ファイルのエンコーディングを判定できません")
            return result

    lines = text.splitlines()
    if not lines:
        result["errors"].append("ファイルにデータがありません")
        return result

    # 1行目: 期間情報
    period = parse_period_line(lines[0])
    if period:
        result["start_date"] = period[0]
        result["end_date"] = period[1]

    # ヘッダー行を探す
    header_idx = None
    header_cols = []
    for i, line in enumerate(lines):
        if "販売日時" in line and "レシート" in line:
            header_cols = parse_csv_line(line)
            header_cols = [col.strip() for col in header_cols]
            header_idx = i
            break

    if header_idx is None:
        result["errors"].append("ヘッダー行が見つかりません（「販売日時」「レシート」を含む行が必要です）")
        return result

    # カラムインデックスを特定
    col_map: Dict[str, int] = {}
    target_cols = {
        "販売日時": ["販売日時", "日時", "取引日時"],
        "レシート番号": ["レシート番号", "レシートNo", "レシートＮｏ", "伝票番号"],
        "商品名": ["商品名", "品名", "商品"],
        "数量": ["数量", "個数"],
        "小計": ["小計", "金額", "売上"],
    }

    for key, candidates in target_cols.items():
        for j, col_name in enumerate(header_cols):
            for candidate in candidates:
                if candidate in col_name:
                    col_map[key] = j
                    break
            if key in col_map:
                break

    required = ["販売日時", "レシート番号", "商品名", "小計"]
    missing = [k for k in required if k not in col_map]
    if missing:
        result["errors"].append(f"必須カラムが見つかりません: {', '.join(missing)}")
        return result

    # データ行をパース（csv.readerで引用符付きフィールドを正しく処理）
    transactions = []
    skip_count = 0

    for i in range(header_idx + 1, len(lines)):
        line = lines[i].strip()
        if not line:
            continue

        cols = parse_csv_line(line)
        if not cols:
            continue

        # 販売日時
        dt_idx = col_map["販売日時"]
        if dt_idx >= len(cols):
            continue
        dt_parsed = parse_sale_datetime(cols[dt_idx])
        if not dt_parsed:
            # 集計行やメタ行をスキップ
            skip_count += 1
            continue

        sale_date, sale_hour = dt_parsed

        # レシート番号
        receipt_idx = col_map["レシート番号"]
        receipt_no = cols[receipt_idx].strip() if receipt_idx < len(cols) else ""

        # 店舗コード抽出
        store_code = extract_store_code(receipt_no)
        if not store_code:
            continue

        # 商品名
        product_idx = col_map["商品名"]
        product_name = cols[product_idx].strip() if product_idx < len(cols) else ""
        if not product_name:
            continue

        # 商品グループ
        product_group = get_product_group(product_name)

        # 数量
        quantity = 1
        if "数量" in col_map:
            qty_idx = col_map["数量"]
            if qty_idx < len(cols):
                qty_val = parse_number(cols[qty_idx])
                quantity = int(qty_val) if qty_val else 1

        # 小計
        subtotal_idx = col_map["小計"]
        subtotal = parse_number(cols[subtotal_idx]) if subtotal_idx < len(cols) else Decimal(0)

        transactions.append({
            "date": sale_date,
            "hour": sale_hour,
            "store_code": store_code,
            "receipt_no": receipt_no,
            "product_name": product_name,
            "product_group": product_group,
            "quantity": quantity,
            "sales": float(subtotal),
        })

    if not transactions:
        result["errors"].append("有効なトランザクションデータが見つかりません")
        return result

    result["success"] = True
    result["transactions"] = transactions

    # 期間情報がない場合、データから推定
    if not result["start_date"] and transactions:
        dates = [t["date"] for t in transactions]
        result["start_date"] = min(dates)
        result["end_date"] = max(dates)

    return result
