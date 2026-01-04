"""
入力バリデーション用ユーティリティ
"""
import re
from typing import Optional

from fastapi import HTTPException, status


class InputValidator:
    """入力値のバリデーション"""

    # 許可される年の範囲
    MIN_YEAR = 2020
    MAX_YEAR = 2100

    # ファイルサイズ制限（10MB）
    MAX_FILE_SIZE = 10 * 1024 * 1024

    # 許可されるファイル拡張子
    ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".csv"}

    @staticmethod
    def validate_year(year: int) -> int:
        """年の妥当性を検証"""
        if not InputValidator.MIN_YEAR <= year <= InputValidator.MAX_YEAR:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"年は{InputValidator.MIN_YEAR}から{InputValidator.MAX_YEAR}の範囲で指定してください"
            )
        return year

    @staticmethod
    def validate_month(month: int) -> int:
        """月の妥当性を検証"""
        if not 1 <= month <= 12:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="月は1から12の範囲で指定してください"
            )
        return month

    @staticmethod
    def validate_quarter(quarter: int) -> int:
        """四半期の妥当性を検証"""
        if not 1 <= quarter <= 4:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="四半期は1から4の範囲で指定してください"
            )
        return quarter

    @staticmethod
    def validate_period_type(period_type: str) -> str:
        """期間タイプの妥当性を検証"""
        allowed = {"monthly", "quarterly", "yearly", "cumulative"}
        if period_type not in allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"期間タイプは {', '.join(allowed)} のいずれかを指定してください"
            )
        return period_type

    @staticmethod
    def validate_file_extension(filename: str) -> str:
        """ファイル拡張子を検証"""
        import os
        ext = os.path.splitext(filename)[1].lower()
        if ext not in InputValidator.ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"許可されているファイル形式は {', '.join(InputValidator.ALLOWED_EXTENSIONS)} です"
            )
        return filename

    @staticmethod
    def validate_file_size(file_size: int) -> int:
        """ファイルサイズを検証"""
        if file_size > InputValidator.MAX_FILE_SIZE:
            max_mb = InputValidator.MAX_FILE_SIZE / (1024 * 1024)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"ファイルサイズは{max_mb}MB以下にしてください"
            )
        return file_size

    @staticmethod
    def sanitize_string(value: str, max_length: int = 255) -> str:
        """文字列をサニタイズ"""
        if not value:
            return value
        # 長さ制限
        value = value[:max_length]
        # 危険な文字を除去
        value = re.sub(r'[<>"\';]', '', value)
        return value.strip()


validator = InputValidator()
