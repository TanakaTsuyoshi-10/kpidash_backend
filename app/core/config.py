"""
環境変数管理モジュール

pydantic-settingsを使用して環境変数を型安全に管理する。
.envファイルからの自動読み込みに対応。
"""
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    アプリケーション設定クラス

    環境変数または.envファイルから設定を読み込む。
    すべての設定値は型アノテーションで型安全に管理される。
    """

    # Supabase設定
    # SupabaseプロジェクトのURL
    SUPABASE_URL: str
    # Supabase匿名キー（フロントエンド用、RLSが適用される）
    SUPABASE_ANON_KEY: str
    # Supabaseサービスロールキー（バックエンド用、RLSをバイパス）
    SUPABASE_SERVICE_ROLE_KEY: str

    # JWT設定
    # Supabaseプロジェクトで使用されるJWTシークレット
    JWT_SECRET: str
    # JWTの署名アルゴリズム（Supabaseのデフォルト）
    JWT_ALGORITHM: str = "HS256"

    # アプリケーション設定
    # 実行環境（development, staging, production）
    APP_ENV: str = "development"
    # デバッグモード（開発時はTrue）
    DEBUG: bool = True
    # 許可するCORSオリジン（カンマ区切り）
    ALLOWED_ORIGINS: str = "http://localhost:3000"

    # APIメタ情報
    # APIタイトル
    API_TITLE: str = "KPI管理システム API"
    # APIバージョン
    API_VERSION: str = "1.0.0"
    # API説明
    API_DESCRIPTION: str = "社内KPI管理システムのバックエンドAPI"

    # 年度設定
    # 年度開始月（9月始まり = 9）
    FISCAL_YEAR_START_MONTH: int = 9

    @property
    def allowed_origins_list(self) -> List[str]:
        """
        許可されたオリジンをリストで取得

        ALLOWED_ORIGINSをカンマで分割してリストに変換する。

        Returns:
            List[str]: 許可されたオリジンのリスト
        """
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",")]

    @property
    def is_development(self) -> bool:
        """
        開発環境かどうかを判定

        Returns:
            bool: 開発環境の場合True
        """
        return self.APP_ENV == "development"

    @property
    def is_production(self) -> bool:
        """
        本番環境かどうかを判定

        Returns:
            bool: 本番環境の場合True
        """
        return self.APP_ENV == "production"

    model_config = SettingsConfigDict(
        # .envファイルから環境変数を読み込む
        env_file=".env",
        # .envファイルのエンコーディング
        env_file_encoding="utf-8",
        # 環境変数名の大文字小文字を区別しない
        case_sensitive=False,
        # 追加のフィールドを無視
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    """
    設定インスタンスを取得（シングルトン）

    lru_cacheを使用して設定の読み込みは一度だけ行う。
    アプリケーション全体で同じ設定インスタンスを共有する。

    Returns:
        Settings: アプリケーション設定
    """
    return Settings()


# グローバル設定インスタンス（簡易アクセス用）
settings = get_settings()
