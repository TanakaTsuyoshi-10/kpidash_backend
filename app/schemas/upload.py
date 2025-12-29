"""
アップロード用スキーマモジュール

CSVアップロード機能で使用するリクエスト/レスポンスのデータモデルを定義する。
"""
from datetime import date as DateType
from typing import List, Optional, Any

from pydantic import BaseModel, Field


# =============================================================================
# バリデーションエラー関連スキーマ
# =============================================================================

class ValidationError(BaseModel):
    """
    バリデーションエラースキーマ

    CSV行ごとのバリデーションエラー詳細を表す。
    """
    row: int = Field(..., description="エラーが発生した行番号（1始まり）")
    column: str = Field(..., description="エラーが発生したカラム名")
    message: str = Field(..., description="エラーメッセージ")
    value: Optional[str] = Field(None, description="エラーの原因となった値")


# =============================================================================
# パース結果スキーマ
# =============================================================================

class ParseResult(BaseModel):
    """
    CSV解析結果スキーマ

    CSVファイルの解析結果を表す。
    """
    success: bool = Field(..., description="解析成功かどうか")
    period: Optional[DateType] = Field(None, description="対象期間（月初日）")
    row_count: int = Field(default=0, description="データ行数")
    errors: List[ValidationError] = Field(default_factory=list, description="バリデーションエラーのリスト")


# =============================================================================
# 店舗別CSVパース結果
# =============================================================================

class StoreKPIRow(BaseModel):
    """
    店舗別KPIデータ行スキーマ

    パースされた店舗別CSVの1行分のデータを表す。
    """
    store_code: str = Field(..., description="店舗コード")
    store_name: str = Field(..., description="店舗名称")
    sales: int = Field(..., description="今年度売上（税込小計）")
    customers: int = Field(..., description="今年度客数")


class StoreKPIParseResult(BaseModel):
    """
    店舗別CSV解析結果スキーマ
    """
    success: bool = Field(..., description="解析成功かどうか")
    period: Optional[DateType] = Field(None, description="対象期間（月初日）")
    data: List[StoreKPIRow] = Field(default_factory=list, description="パースされたデータ")
    errors: List[str] = Field(default_factory=list, description="エラーメッセージのリスト")
    warnings: List[str] = Field(default_factory=list, description="警告メッセージのリスト")


# =============================================================================
# 商品別CSVパース結果
# =============================================================================

class ProductKPIRow(BaseModel):
    """
    商品別KPIデータ行スキーマ

    パースされた商品別CSVの1行分のデータを表す。
    """
    product_name: str = Field(..., description="商品名")
    category: str = Field(..., description="大分類名")
    quantity: int = Field(..., description="件数（販売数量）")
    sales: int = Field(..., description="税込小計")


class ProductKPIParseResult(BaseModel):
    """
    商品別CSV解析結果スキーマ
    """
    success: bool = Field(..., description="解析成功かどうか")
    period: Optional[DateType] = Field(None, description="対象期間（月初日）")
    data: List[ProductKPIRow] = Field(default_factory=list, description="パースされたデータ")
    errors: List[str] = Field(default_factory=list, description="エラーメッセージのリスト")
    warnings: List[str] = Field(default_factory=list, description="警告メッセージのリスト")


# =============================================================================
# アップロード結果スキーマ
# =============================================================================

class UploadResult(BaseModel):
    """
    アップロード結果ベーススキーマ

    CSVアップロード処理の結果を表す基本スキーマ。
    """
    success: bool = Field(..., description="処理成功かどうか")
    period: Optional[DateType] = Field(None, description="対象期間（月初日）")
    imported_count: int = Field(default=0, description="インポートされたレコード数")
    errors: List[str] = Field(default_factory=list, description="エラーメッセージのリスト")
    warnings: List[str] = Field(default_factory=list, description="警告メッセージのリスト")


class StoreKPIUploadResult(UploadResult):
    """
    店舗別KPIアップロード結果スキーマ

    店舗別CSVアップロード処理の結果を表す。
    """
    pass


class StoreProcessed(BaseModel):
    """処理された店舗情報"""
    store_code: str = Field(..., description="店舗コード")
    store_name: str = Field(..., description="店舗名")


class ProductKPIUploadResult(UploadResult):
    """
    商品別KPIアップロード結果スキーマ

    商品別CSVアップロード処理の結果を表す。
    """
    new_products: List[str] = Field(
        default_factory=list,
        description="新規登録された商品名のリスト"
    )
    unmapped_products: List[str] = Field(
        default_factory=list,
        description="KPIグループ未設定の商品名のリスト"
    )
    stores_processed: List[StoreProcessed] = Field(
        default_factory=list,
        description="処理された店舗のリスト"
    )


# =============================================================================
# インポート結果スキーマ
# =============================================================================

class ImportResult(BaseModel):
    """
    インポート結果スキーマ

    DBへのインポート処理結果を表す。
    """
    imported: int = Field(default=0, description="インポートされたレコード数")
    updated: int = Field(default=0, description="更新されたレコード数")
    errors: List[str] = Field(default_factory=list, description="エラーメッセージのリスト")
    warnings: List[str] = Field(default_factory=list, description="警告メッセージのリスト")


class ProductImportResult(ImportResult):
    """
    商品別インポート結果スキーマ
    """
    new_products: List[str] = Field(
        default_factory=list,
        description="新規登録された商品名のリスト"
    )
    unmapped: List[str] = Field(
        default_factory=list,
        description="マッピングされなかった商品名のリスト"
    )


# =============================================================================
# エラーレスポンススキーマ
# =============================================================================

class UploadErrorDetail(BaseModel):
    """
    アップロードエラー詳細スキーマ

    バリデーションエラー時の詳細レスポンス。
    """
    success: bool = Field(default=False, description="常にFalse")
    message: str = Field(..., description="エラーメッセージ")
    errors: List[ValidationError] = Field(
        default_factory=list,
        description="行ごとのバリデーションエラー"
    )


# =============================================================================
# KPIグループ集計結果
# =============================================================================

class KPIGroupAggregate(BaseModel):
    """
    KPIグループ別集計結果スキーマ

    商品をKPIグループ別に集計した結果を表す。
    """
    kpi_name: str = Field(..., description="KPIグループ名")
    kpi_id: Optional[str] = Field(None, description="KPI定義ID")
    total_quantity: int = Field(default=0, description="合計数量")
    total_sales: int = Field(default=0, description="合計売上")
    products: List[str] = Field(default_factory=list, description="含まれる商品名のリスト")
