"""
FastAPIアプリケーション エントリーポイント

KPI管理システムのバックエンドAPIを提供する。
Supabase認証と連携し、部門別のKPIデータ管理機能を提供する。
"""
import os
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware

from app.core.config import settings
from app.core.security_config import security_config
from app.middleware.rate_limiter import RateLimitMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.api.endpoints import auth, upload, kpi, products, ecommerce, comments, regional, templates, dashboard, manufacturing, finance, complaints, targets, users, admin, daily_sales, order_forecast, furusato
from app.schemas.kpi import HealthResponse, APIInfo


# =============================================================================
# FastAPIアプリケーション初期化
# =============================================================================

app = FastAPI(
    title=settings.API_TITLE,
    version=settings.API_VERSION,
    description=settings.API_DESCRIPTION,
    docs_url="/docs",      # Swagger UI
    redoc_url="/redoc",    # ReDoc
    openapi_url="/openapi.json",
)


# =============================================================================
# CORSミドルウェア設定
# =============================================================================

app.add_middleware(
    CORSMiddleware,
    # 許可するオリジン（フロントエンドのURL）
    allow_origins=settings.allowed_origins_list,
    # 認証情報（Cookie, Authorizationヘッダー）の送信を許可
    allow_credentials=True,
    # 許可するHTTPメソッド（必要なメソッドのみに制限）
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    # 許可するリクエストヘッダー（必要なヘッダーのみに制限）
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
    # レスポンスで公開するヘッダー
    expose_headers=["X-Request-ID"],
    # プリフライトリクエストのキャッシュ時間（秒）
    max_age=600,
)


# =============================================================================
# セキュリティミドルウェア設定
# =============================================================================

# セキュリティヘッダー（全リクエストに適用）
app.add_middleware(SecurityHeadersMiddleware)

# Gzip圧縮（1KB以上のレスポンスを圧縮）
app.add_middleware(GZipMiddleware, minimum_size=1000)

# レート制限（本番環境のみ）
if os.getenv("APP_ENV") == "production":
    app.add_middleware(RateLimitMiddleware)


# =============================================================================
# ルーター登録
# =============================================================================

# 認証関連エンドポイント
app.include_router(auth.router, prefix="/auth")

# CSVアップロード関連エンドポイント
app.include_router(upload.router, prefix="/upload")

# KPIデータ取得エンドポイント
app.include_router(kpi.router, prefix="/kpi")

# 商品関連エンドポイント
app.include_router(products.router)

# 通販分析エンドポイント
app.include_router(ecommerce.router)

# コメントエンドポイント
app.include_router(comments.router)

# 地区別分析エンドポイント
app.include_router(regional.router)

# テンプレートダウンロードエンドポイント
app.include_router(templates.router, prefix="/api/v1")

# ダッシュボードエンドポイント
app.include_router(dashboard.router)

# 製造分析エンドポイント
app.include_router(manufacturing.router, prefix="/api/v1")

# 財務分析エンドポイント
app.include_router(finance.router, prefix="/api/v1")

# クレーム管理エンドポイント
app.include_router(complaints.router, prefix="/api/v1/complaints", tags=["クレーム管理"])

# 目標設定エンドポイント
app.include_router(targets.router, prefix="/api/v1/targets", tags=["目標設定"])

# 利用者管理エンドポイント
app.include_router(users.router, prefix="/api/v1/users", tags=["利用者管理"])

# 管理者用エンドポイント（キャッシュ管理など）
app.include_router(admin.router, prefix="/api/v1/admin")

# 日次販売分析エンドポイント
app.include_router(daily_sales.router, prefix="/daily-sales", tags=["日次販売分析"])

# 予想注文（発注バット数予測）エンドポイント
app.include_router(order_forecast.router, prefix="/order-forecast", tags=["予想注文"])

# ふるさと納税分析エンドポイント
app.include_router(furusato.router)


# =============================================================================
# ルートエンドポイント
# =============================================================================

@app.get(
    "/",
    response_model=APIInfo,
    summary="API情報",
    description="APIの基本情報を返す。",
    tags=["システム"],
)
async def root() -> APIInfo:
    """
    APIのルートエンドポイント

    APIの基本情報（タイトル、バージョン、説明）を返す。
    ヘルスチェックやAPI確認に使用できる。

    Returns:
        APIInfo: API情報
    """
    return APIInfo(
        title=settings.API_TITLE,
        version=settings.API_VERSION,
        description=settings.API_DESCRIPTION,
        docs_url="/docs",
    )


@app.get(
    "/health",
    response_model=HealthResponse,
    summary="ヘルスチェック",
    description="""
    アプリケーションの稼働状態を確認する。

    このエンドポイントは認証不要。
    Cloud Runのヘルスチェックやモニタリングに使用する。
    """,
    tags=["システム"],
)
async def health_check() -> HealthResponse:
    """
    ヘルスチェックエンドポイント

    アプリケーションの稼働状態と基本情報を返す。
    認証不要で、ロードバランサーやモニタリングツールから
    アプリケーションの状態を確認するために使用する。

    Returns:
        HealthResponse: ヘルスチェック結果
    """
    return HealthResponse(
        status="healthy",
        environment=settings.APP_ENV,
        version=settings.API_VERSION,
        timestamp=datetime.now(),
    )


# =============================================================================
# イベントハンドラ
# =============================================================================

@app.on_event("startup")
async def startup_event():
    """
    アプリケーション起動時の処理

    - 設定の読み込み確認
    - DB接続の初期化（必要に応じて）
    """
    print(f"🚀 {settings.API_TITLE} v{settings.API_VERSION} が起動しました")
    print(f"   環境: {settings.APP_ENV}")
    print(f"   デバッグ: {settings.DEBUG}")
    print(f"   許可オリジン: {settings.allowed_origins_list}")
    print(f"   セキュリティヘッダー: 有効")
    print(f"   レート制限: {'有効' if os.getenv('APP_ENV') == 'production' else '無効（開発環境）'}")
    print(f"   監査ログ: {'有効' if security_config.ENABLE_AUDIT_LOG else '無効'}")
    print(f"   Gzip圧縮: 有効（1KB以上）")
    print(f"   キャッシュ: 有効（インメモリ、TTL: 5分）")


@app.on_event("shutdown")
async def shutdown_event():
    """
    アプリケーション終了時の処理

    - リソースのクリーンアップ
    - DB接続のクローズ（必要に応じて）
    """
    print(f"👋 {settings.API_TITLE} を終了します")


# =============================================================================
# 開発用: uvicornで直接実行する場合
# =============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
    )
