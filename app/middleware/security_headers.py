"""
セキュリティヘッダーミドルウェア
"""
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.security_config import security_config


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """セキュリティヘッダーを全レスポンスに追加"""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # セキュリティヘッダーを追加
        for header_name, header_value in security_config.SECURITY_HEADERS.items():
            response.headers[header_name] = header_value

        return response
