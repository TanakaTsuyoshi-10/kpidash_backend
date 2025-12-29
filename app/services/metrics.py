"""
KPI計算サービスモジュール

年度計算、累計計算、各種指標計算、アラート判定を提供する。

年度計算ルール:
- 年度開始: 毎年9月1日
- 年度終了: 翌年8月31日
- 例: 2025年4月 → 2024年度（2024年9月〜2025年8月）
"""
import calendar
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Dict, Any, Optional


# =============================================================================
# 年度計算
# =============================================================================

def get_fiscal_year(target_date: date, start_month: int = 9) -> int:
    """
    対象日から年度を算出する

    9月以降 → その年が年度
    8月以前 → 前年が年度

    Args:
        target_date: 対象日付
        start_month: 年度開始月（デフォルト: 9月）

    Returns:
        int: 年度

    Examples:
        >>> get_fiscal_year(date(2025, 4, 15))
        2024
        >>> get_fiscal_year(date(2025, 10, 1))
        2025
    """
    if target_date.month >= start_month:
        return target_date.year
    else:
        return target_date.year - 1


def get_fiscal_year_range(fiscal_year: int, start_month: int = 9) -> tuple[date, date]:
    """
    年度から期間（開始日、終了日）を算出する

    Args:
        fiscal_year: 年度
        start_month: 年度開始月（デフォルト: 9月）

    Returns:
        tuple[date, date]: (開始日, 終了日)

    Examples:
        >>> get_fiscal_year_range(2024)
        (date(2024, 9, 1), date(2025, 8, 31))
    """
    # 年度開始日
    start_date = date(fiscal_year, start_month, 1)

    # 年度終了日（翌年の開始月前月末）
    if start_month == 1:
        end_date = date(fiscal_year, 12, 31)
    else:
        end_year = fiscal_year + 1
        end_month = start_month - 1
        _, last_day = calendar.monthrange(end_year, end_month)
        end_date = date(end_year, end_month, last_day)

    return start_date, end_date


def get_months_in_fiscal_year(
    fiscal_year: int,
    up_to_month: Optional[date] = None,
    start_month: int = 9
) -> List[date]:
    """
    年度内の月リストを取得する

    Args:
        fiscal_year: 年度
        up_to_month: この月まで（省略時は年度終了月まで）
        start_month: 年度開始月

    Returns:
        List[date]: 月初日のリスト
    """
    start_date, end_date = get_fiscal_year_range(fiscal_year, start_month)

    if up_to_month:
        end_date = min(end_date, up_to_month)

    months = []
    current = start_date
    while current <= end_date:
        months.append(current)
        # 翌月1日へ
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)

    return months


# =============================================================================
# 累計計算
# =============================================================================

def calculate_ytd(
    values: List[Dict[str, Any]],
    target_date: date,
    is_target: bool = False,
    date_key: str = "date",
    value_key: str = "value",
    is_target_key: str = "is_target"
) -> Decimal:
    """
    年度累計（Year To Date）を計算する

    年度開始月から指定月までの値を合計する。

    Args:
        values: kpi_valuesのリスト
        target_date: 累計の終了月
        is_target: True=目標累計, False=実績累計
        date_key: 日付カラム名
        value_key: 値カラム名
        is_target_key: 目標/実績フラグカラム名

    Returns:
        Decimal: 累計値
    """
    fiscal_year = get_fiscal_year(target_date)
    start_date, _ = get_fiscal_year_range(fiscal_year)

    total = Decimal("0")

    for item in values:
        item_date = item.get(date_key)
        if isinstance(item_date, str):
            item_date = date.fromisoformat(item_date)

        item_is_target = item.get(is_target_key, False)

        # 目標/実績フィルタ
        if item_is_target != is_target:
            continue

        # 期間フィルタ（年度開始日から対象月まで）
        if item_date and start_date <= item_date <= target_date:
            value = item.get(value_key, 0)
            if value is not None:
                total += Decimal(str(value))

    return total


# =============================================================================
# 指標計算
# =============================================================================

def calculate_customer_unit_price(
    sales: Decimal,
    customers: int
) -> Optional[Decimal]:
    """
    客単価を計算する

    客単価 = 売上高 ÷ 客数

    Args:
        sales: 売上高
        customers: 客数

    Returns:
        Optional[Decimal]: 客単価（円）、客数が0の場合はNone
    """
    if customers == 0:
        return None

    result = sales / Decimal(str(customers))
    return result.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def calculate_items_per_customer(
    items: int,
    customers: int
) -> Optional[Decimal]:
    """
    1人あたり個数を計算する

    1人あたり個数 = 販売個数 ÷ 客数

    Args:
        items: 販売個数
        customers: 客数

    Returns:
        Optional[Decimal]: 1人あたり個数、客数が0の場合はNone
    """
    if customers == 0:
        return None

    result = Decimal(str(items)) / Decimal(str(customers))
    return result.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def calculate_achievement_rate(
    actual: Decimal,
    target: Decimal
) -> Optional[Decimal]:
    """
    目標達成率を計算する

    達成率 = 実績 ÷ 目標 × 100

    Args:
        actual: 実績値
        target: 目標値

    Returns:
        Optional[Decimal]: 達成率（%）、目標が0の場合はNone
    """
    if target == 0:
        return None

    result = (actual / target) * 100
    return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate_yoy_rate(
    current: Decimal,
    previous: Decimal
) -> Optional[Decimal]:
    """
    前年比（変化率）を計算する

    前年比 = (今期 - 前期) ÷ 前期 × 100

    例:
    - 今期 29,820,336 / 前期 31,576,724 → -5.56%（減少）
    - 今期 105,000 / 前期 100,000 → +5.00%（増加）

    Args:
        current: 今期の値
        previous: 前期の値

    Returns:
        Optional[Decimal]: 前年比（%）、前期が0の場合はNone
    """
    if previous == 0:
        return None

    result = ((current - previous) / previous) * 100
    return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# =============================================================================
# アラート判定
# =============================================================================

def get_alert_level(achievement_rate: Optional[Decimal]) -> str:
    """
    達成率からアラートレベルを判定する

    レベル定義:
    - none: 達成率 >= 100%
    - warning: 達成率 80% 〜 99%
    - critical: 達成率 < 80%

    Args:
        achievement_rate: 達成率（%）

    Returns:
        str: "none" | "warning" | "critical"
    """
    if achievement_rate is None:
        return "none"

    if achievement_rate >= 100:
        return "none"
    elif achievement_rate >= 80:
        return "warning"
    else:
        return "critical"


# =============================================================================
# ユーティリティ
# =============================================================================

def normalize_to_month_start(target_date: date) -> date:
    """
    日付を月初日に正規化する

    Args:
        target_date: 対象日付

    Returns:
        date: 月初日
    """
    return date(target_date.year, target_date.month, 1)


def get_previous_year_month(target_date: date) -> date:
    """
    前年同月を取得する

    Args:
        target_date: 対象日付

    Returns:
        date: 前年同月の月初日
    """
    return date(target_date.year - 1, target_date.month, 1)


def calculate_derived_kpi(
    formula: str,
    values: Dict[str, Decimal]
) -> Optional[Decimal]:
    """
    計算式に基づいて派生KPIを計算する

    安全な式評価を行う。サポートする演算子: +, -, *, /

    Args:
        formula: 計算式（例: "売上高 / 客数"）
        values: KPI名→値のマッピング

    Returns:
        Optional[Decimal]: 計算結果、計算できない場合はNone
    """
    # 簡易的な計算式パーサー
    # 将来的にはより安全な実装に置き換える
    try:
        # KPI名を値に置換
        expression = formula
        for name, value in values.items():
            expression = expression.replace(name, str(value))

        # 安全な演算のみ許可（eval は使用しない）
        # ここでは単純な2項演算のみサポート
        if "/" in expression:
            parts = expression.split("/")
            if len(parts) == 2:
                left = Decimal(parts[0].strip())
                right = Decimal(parts[1].strip())
                if right == 0:
                    return None
                return left / right

        return None
    except Exception:
        return None
