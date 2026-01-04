"""
データベースクエリ最適化ユーティリティ
"""
from typing import List, Dict, Any, Optional
from datetime import date


def build_date_range_query(
    table: str,
    date_column: str,
    start_date: date,
    end_date: date,
    select_columns: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    日付範囲クエリのパラメータを構築
    """
    return {
        'table': table,
        'date_column': date_column,
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'select_columns': select_columns or ['*']
    }


def paginate_results(
    data: List[Any],
    page: int = 1,
    page_size: int = 50
) -> Dict[str, Any]:
    """
    結果をページネーション
    """
    total = len(data)
    start = (page - 1) * page_size
    end = start + page_size

    return {
        'data': data[start:end],
        'pagination': {
            'page': page,
            'page_size': page_size,
            'total': total,
            'total_pages': (total + page_size - 1) // page_size
        }
    }


def batch_query(
    items: List[Any],
    batch_size: int = 100
) -> List[List[Any]]:
    """
    大量データをバッチに分割

    Args:
        items: 分割するリスト
        batch_size: バッチサイズ

    Returns:
        バッチのリスト
    """
    return [
        items[i:i + batch_size]
        for i in range(0, len(items), batch_size)
    ]


def optimize_select_columns(
    requested_fields: Optional[List[str]] = None,
    available_fields: Optional[List[str]] = None
) -> str:
    """
    必要なカラムのみを選択するためのSELECT句を構築

    Args:
        requested_fields: リクエストされたフィールド
        available_fields: 利用可能なフィールド

    Returns:
        SELECT句の文字列
    """
    if not requested_fields:
        return "*"

    if available_fields:
        # 利用可能なフィールドのみフィルタリング
        valid_fields = [f for f in requested_fields if f in available_fields]
        if valid_fields:
            return ", ".join(valid_fields)

    return ", ".join(requested_fields)
