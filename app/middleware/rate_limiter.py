"""
レート制限ミドルウェア
IPアドレスベースでリクエスト数を制限
"""
import time
from collections import defaultdict
from typing import Dict

from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.security_config import security_config


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    シンプルなインメモリレート制限
    本番環境ではRedisベースの実装を推奨
    """

    def __init__(self, app):
        super().__init__(app)
        # {ip: [timestamp, ...]}
        self.requests: Dict[str, list] = defaultdict(list)
        self.max_requests = security_config.RATE_LIMIT_REQUESTS
        self.window_seconds = security_config.RATE_LIMIT_WINDOW

    async def dispatch(self, request: Request, call_next):
        # ヘルスチェックはレート制限対象外
        if request.url.path in ["/health", "/", "/docs", "/redoc", "/openapi.json"]:
            return await call_next(request)

        # クライアントIPを取得
        client_ip = self._get_client_ip(request)

        # レート制限チェック
        if not self._is_allowed(client_ip):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="リクエスト数が制限を超えました。しばらく待ってから再試行してください。"
            )

        response = await call_next(request)
        return response

    def _get_client_ip(self, request: Request) -> str:
        """クライアントIPを取得（プロキシ対応）"""
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _is_allowed(self, client_ip: str) -> bool:
        """リクエストが許可されるかチェック"""
        current_time = time.time()
        window_start = current_time - self.window_seconds

        # 古いリクエストを削除
        self.requests[client_ip] = [
            req_time for req_time in self.requests[client_ip]
            if req_time > window_start
        ]

        # 制限チェック
        if len(self.requests[client_ip]) >= self.max_requests:
            return False

        # 新しいリクエストを記録
        self.requests[client_ip].append(current_time)
        return True
