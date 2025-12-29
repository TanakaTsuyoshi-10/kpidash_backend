"""
期間計算ユーティリティ

ダッシュボードの期間計算（月次・四半期・年度）を行うユーティリティ関数を提供する。

年度計算ルール:
- 年度開始: 毎年9月1日
- 年度終了: 翌年8月31日
- 四半期: Q1(9-11月), Q2(12-2月), Q3(3-5月), Q4(6-8月)
"""
import calendar
from datetime import date
from typing import Tuple


# 年度開始月
FISCAL_YEAR_START_MONTH = 9


def get_fiscal_year(target_date: date) -> int:
    """
    日付から年度を計算する（9月始まり）

    9月以降: その年が年度
    8月以前: 前年が年度

    Args:
        target_date: 対象日付

    Returns:
        int: 年度

    Examples:
        >>> get_fiscal_year(date(2025, 11, 15))
        2025
        >>> get_fiscal_year(date(2025, 4, 15))
        2024
    """
    if target_date.month >= FISCAL_YEAR_START_MONTH:
        return target_date.year
    else:
        return target_date.year - 1


def get_quarter(month: int) -> int:
    """
    月から四半期を計算する（9月始まり）

    Q1: 9-11月
    Q2: 12-2月
    Q3: 3-5月
    Q4: 6-8月

    Args:
        month: 月（1-12）

    Returns:
        int: 四半期（1-4）

    Examples:
        >>> get_quarter(9)
        1
        >>> get_quarter(12)
        2
        >>> get_quarter(3)
        3
        >>> get_quarter(6)
        4
    """
    # 月を年度内の順序に変換（9月=1, 10月=2, ..., 8月=12）
    fiscal_month = (month - FISCAL_YEAR_START_MONTH) % 12 + 1
    return (fiscal_month - 1) // 3 + 1


def get_quarter_months(quarter: int) -> Tuple[int, int, int]:
    """
    四半期から月を取得する

    Args:
        quarter: 四半期（1-4）

    Returns:
        Tuple[int, int, int]: 四半期に含まれる月（開始月, 中間月, 終了月）

    Examples:
        >>> get_quarter_months(1)
        (9, 10, 11)
        >>> get_quarter_months(2)
        (12, 1, 2)
    """
    quarter_to_months = {
        1: (9, 10, 11),
        2: (12, 1, 2),
        3: (3, 4, 5),
        4: (6, 7, 8),
    }
    return quarter_to_months.get(quarter, (9, 10, 11))


def get_period_range(
    period_type: str,
    year: int,
    month: int = 1,
    quarter: int = 1
) -> Tuple[date, date, str]:
    """
    期間タイプから開始日・終了日・表示文字列を返す

    Args:
        period_type: 期間タイプ（monthly/quarterly/yearly）
        year: 年度
        month: 月（monthlyの場合に使用）
        quarter: 四半期（quarterlyの場合に使用）

    Returns:
        Tuple[date, date, str]: (開始日, 終了日, 期間ラベル)

    Examples:
        >>> get_period_range("monthly", 2025, month=11)
        (date(2025, 11, 1), date(2025, 11, 30), "2025年11月")

        >>> get_period_range("quarterly", 2025, quarter=1)
        (date(2025, 9, 1), date(2025, 11, 30), "2025年度Q1")

        >>> get_period_range("yearly", 2025)
        (date(2025, 9, 1), date(2026, 8, 31), "2025年度")
    """
    if period_type == "monthly":
        return _get_monthly_range(year, month)
    elif period_type == "quarterly":
        return _get_quarterly_range(year, quarter)
    elif period_type == "yearly":
        return _get_yearly_range(year)
    else:
        # デフォルトは月次
        return _get_monthly_range(year, month)


def _get_monthly_range(year: int, month: int) -> Tuple[date, date, str]:
    """月次の期間を取得する"""
    start_date = date(year, month, 1)
    _, last_day = calendar.monthrange(year, month)
    end_date = date(year, month, last_day)
    label = f"{year}年{month}月"
    return start_date, end_date, label


def _get_quarterly_range(fiscal_year: int, quarter: int) -> Tuple[date, date, str]:
    """四半期の期間を取得する"""
    months = get_quarter_months(quarter)
    start_month, _, end_month = months

    # 開始日の年を計算
    if quarter == 1:
        # Q1: 9-11月 → fiscal_year年
        start_year = fiscal_year
        end_year = fiscal_year
    elif quarter == 2:
        # Q2: 12-2月 → 12月はfiscal_year年、1-2月はfiscal_year+1年
        start_year = fiscal_year
        end_year = fiscal_year + 1
    else:
        # Q3, Q4: 翌年
        start_year = fiscal_year + 1
        end_year = fiscal_year + 1

    start_date = date(start_year, start_month, 1)
    _, last_day = calendar.monthrange(end_year, end_month)
    end_date = date(end_year, end_month, last_day)
    label = f"{fiscal_year}年度Q{quarter}"

    return start_date, end_date, label


def _get_yearly_range(fiscal_year: int) -> Tuple[date, date, str]:
    """年度の期間を取得する"""
    start_date = date(fiscal_year, FISCAL_YEAR_START_MONTH, 1)
    end_year = fiscal_year + 1
    end_month = FISCAL_YEAR_START_MONTH - 1  # 8月
    _, last_day = calendar.monthrange(end_year, end_month)
    end_date = date(end_year, end_month, last_day)
    label = f"{fiscal_year}年度"
    return start_date, end_date, label


def get_previous_year_range(
    start_date: date,
    end_date: date
) -> Tuple[date, date]:
    """
    前年同期間を計算する

    Args:
        start_date: 期間開始日
        end_date: 期間終了日

    Returns:
        Tuple[date, date]: (前年開始日, 前年終了日)

    Examples:
        >>> get_previous_year_range(date(2025, 11, 1), date(2025, 11, 30))
        (date(2024, 11, 1), date(2024, 11, 30))
    """
    prev_start = date(start_date.year - 1, start_date.month, start_date.day)

    # 終了日は月末の可能性があるため、適切に処理
    try:
        prev_end = date(end_date.year - 1, end_date.month, end_date.day)
    except ValueError:
        # うるう年の2月29日など、存在しない日付の場合は月末を使用
        _, last_day = calendar.monthrange(end_date.year - 1, end_date.month)
        prev_end = date(end_date.year - 1, end_date.month, last_day)

    return prev_start, prev_end


def get_two_years_ago_range(
    start_date: date,
    end_date: date
) -> Tuple[date, date]:
    """
    前々年同期間を計算する

    Args:
        start_date: 期間開始日
        end_date: 期間終了日

    Returns:
        Tuple[date, date]: (前々年開始日, 前々年終了日)
    """
    prev2_start = date(start_date.year - 2, start_date.month, start_date.day)

    try:
        prev2_end = date(end_date.year - 2, end_date.month, end_date.day)
    except ValueError:
        _, last_day = calendar.monthrange(end_date.year - 2, end_date.month)
        prev2_end = date(end_date.year - 2, end_date.month, last_day)

    return prev2_start, prev2_end


def get_current_period_defaults() -> Tuple[int, int, int]:
    """
    現在の日付から、デフォルトの年度・月・四半期を取得する

    Returns:
        Tuple[int, int, int]: (年度, 月, 四半期)
    """
    today = date.today()
    fiscal_year = get_fiscal_year(today)
    current_month = today.month
    current_quarter = get_quarter(current_month)

    return fiscal_year, current_month, current_quarter
