"""日本の祝日判定ユーティリティ。

祝日法に基づいて日本の祝日を算出する。npmパッケージや外部APIに依存しない。
対応範囲は 1980〜2099 年。

`frontend/src/lib/japanese-holidays.ts` と同等のロジックを Python で実装し、
フロント・バックで同じ判定結果になることを保証する。
"""
from datetime import date, timedelta
from functools import lru_cache
from typing import Dict, Optional


# =============================================================================
# ヘルパー
# =============================================================================


def _nth_monday(year: int, month: int, n: int) -> int:
    """指定年月の第 n 月曜日の「日」を返す。"""
    first_weekday = date(year, month, 1).weekday()  # 月=0 ... 日=6
    # 月の最初の月曜日（first_weekday=0 のとき 1日）
    first_monday = 1 + ((7 - first_weekday) % 7)
    return first_monday + (n - 1) * 7


def _vernal_equinox_day(year: int) -> int:
    """春分の日（1980〜2099 年）。"""
    if year <= 1979 or year >= 2100:
        return 21
    return int(20.8431 + 0.242194 * (year - 1980) - (year - 1980) // 4)


def _autumnal_equinox_day(year: int) -> int:
    """秋分の日（1980〜2099 年）。"""
    if year <= 1979 or year >= 2100:
        return 23
    return int(23.2488 + 0.242194 * (year - 1980) - (year - 1980) // 4)


# =============================================================================
# 年別 祝日マップ
# =============================================================================


@lru_cache(maxsize=128)
def _holidays_for_year(year: int) -> Dict[date, str]:
    """指定年の祝日（date → 祝日名）を構築する。"""
    h: Dict[date, str] = {}

    # --- 固定祝日 ---
    h[date(year, 1, 1)] = "元日"
    h[date(year, 2, 11)] = "建国記念の日"
    h[date(year, 2, 23)] = "天皇誕生日"
    h[date(year, 4, 29)] = "昭和の日"
    h[date(year, 5, 3)] = "憲法記念日"
    h[date(year, 5, 4)] = "みどりの日"
    h[date(year, 5, 5)] = "こどもの日"
    h[date(year, 8, 11)] = "山の日"
    h[date(year, 11, 3)] = "文化の日"
    h[date(year, 11, 23)] = "勤労感謝の日"

    # --- ハッピーマンデー ---
    h[date(year, 1, _nth_monday(year, 1, 2))] = "成人の日"
    h[date(year, 7, _nth_monday(year, 7, 3))] = "海の日"
    h[date(year, 9, _nth_monday(year, 9, 3))] = "敬老の日"
    h[date(year, 10, _nth_monday(year, 10, 2))] = "スポーツの日"

    # --- 春分・秋分 ---
    h[date(year, 3, _vernal_equinox_day(year))] = "春分の日"
    h[date(year, 9, _autumnal_equinox_day(year))] = "秋分の日"

    # --- 振替休日 ---
    # 祝日が日曜の場合、翌日以降の最初の非祝日を振替休日にする
    for d in list(h.keys()):
        if d.weekday() == 6:  # 日曜
            sub = d + timedelta(days=1)
            while sub in h:
                sub += timedelta(days=1)
            h[sub] = "振替休日"

    # --- 国民の休日 ---
    # 2つの祝日に挟まれた平日（日曜以外）は国民の休日
    sorted_dates = sorted(h.keys())
    for i in range(len(sorted_dates) - 1):
        d1, d2 = sorted_dates[i], sorted_dates[i + 1]
        if (d2 - d1).days == 2:
            between = d1 + timedelta(days=1)
            if between not in h and between.weekday() != 6:
                h[between] = "国民の休日"

    return h


# =============================================================================
# 公開関数
# =============================================================================


def get_japanese_holiday(d: date) -> Optional[str]:
    """指定日が日本の祝日なら祝日名を返す。祝日でなければ None。"""
    return _holidays_for_year(d.year).get(d)


def is_japanese_holiday(d: date) -> bool:
    """指定日が日本の祝日かどうかを返す。"""
    return get_japanese_holiday(d) is not None
