"""
監査ログサービス
誰がいつ何をしたかを記録
"""
import logging
from datetime import datetime
from typing import Optional, Dict, Any

from fastapi import Request

from app.core.security_config import security_config

# 監査ログ用のロガー設定
audit_logger = logging.getLogger("audit")
audit_logger.setLevel(logging.INFO)

# ログフォーマット
formatter = logging.Formatter(
    '%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# コンソールハンドラ（Cloud Runではこれがログに出力される）
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
audit_logger.addHandler(console_handler)


class AuditLogService:
    """監査ログを記録するサービス"""

    @staticmethod
    def log_action(
        action: str,
        user_id: Optional[str] = None,
        user_email: Optional[str] = None,
        resource: Optional[str] = None,
        resource_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        request: Optional[Request] = None,
        success: bool = True
    ):
        """
        アクションを監査ログに記録

        Args:
            action: 実行されたアクション（LOGIN, LOGOUT, VIEW, CREATE, UPDATE, DELETE, UPLOAD等）
            user_id: ユーザーID
            user_email: ユーザーメールアドレス
            resource: 操作対象リソース（dashboard, financial_data, manufacturing_data等）
            resource_id: リソースID
            details: 追加の詳細情報
            request: FastAPIリクエストオブジェクト
            success: 成功したかどうか
        """
        if not security_config.ENABLE_AUDIT_LOG:
            return

        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "action": action,
            "success": success,
            "user_id": user_id,
            "user_email": user_email,
            "resource": resource,
            "resource_id": resource_id,
        }

        # リクエスト情報を追加
        if request:
            log_entry["ip"] = AuditLogService._get_client_ip(request)
            log_entry["method"] = request.method
            log_entry["path"] = str(request.url.path)
            log_entry["user_agent"] = request.headers.get("User-Agent", "unknown")[:100]

        # 詳細情報を追加
        if details:
            log_entry["details"] = details

        # ログ出力
        status_str = "SUCCESS" if success else "FAILED"
        audit_logger.info(
            f"{status_str} | {action} | user:{user_email or user_id or 'anonymous'} | "
            f"resource:{resource or 'N/A'} | id:{resource_id or 'N/A'} | "
            f"ip:{log_entry.get('ip', 'unknown')}"
        )

    @staticmethod
    def _get_client_ip(request: Request) -> str:
        """クライアントIPを取得"""
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    # 便利メソッド
    @staticmethod
    def log_login(user_id: str, user_email: str, request: Request, success: bool = True):
        AuditLogService.log_action(
            action="LOGIN",
            user_id=user_id,
            user_email=user_email,
            request=request,
            success=success
        )

    @staticmethod
    def log_logout(user_id: str, user_email: str, request: Request):
        AuditLogService.log_action(
            action="LOGOUT",
            user_id=user_id,
            user_email=user_email,
            request=request
        )

    @staticmethod
    def log_data_access(
        user_id: str,
        user_email: str,
        resource: str,
        request: Request,
        details: Optional[Dict] = None
    ):
        AuditLogService.log_action(
            action="VIEW",
            user_id=user_id,
            user_email=user_email,
            resource=resource,
            request=request,
            details=details
        )

    @staticmethod
    def log_data_upload(
        user_id: str,
        user_email: str,
        resource: str,
        request: Request,
        details: Optional[Dict] = None,
        success: bool = True
    ):
        AuditLogService.log_action(
            action="UPLOAD",
            user_id=user_id,
            user_email=user_email,
            resource=resource,
            request=request,
            details=details,
            success=success
        )


# シングルトンインスタンス
audit_log = AuditLogService()
