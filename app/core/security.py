"""
セキュリティモジュール

Supabase AuthのJWTトークン検証機能を提供する。
JWT_SECRETを使ったローカル検証を優先し、失敗時はリモート検証にフォールバック。
"""
import logging
from typing import Optional, Dict, Any

from jose import jwt, JWTError
from supabase import create_client

from app.core.config import settings

logger = logging.getLogger(__name__)


class TokenValidationError(Exception):
    """
    トークン検証エラー

    JWTトークンの検証に失敗した場合に発生する例外。
    """

    def __init__(self, message: str, status_code: int = 401):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


def _decode_token_local(token: str) -> Dict[str, Any]:
    """JWTトークンをローカルで検証する（高速、<1ms）"""
    payload = jwt.decode(
        token,
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGORITHM],
        audience="authenticated",
    )
    return {
        "sub": payload.get("sub"),
        "email": payload.get("email"),
        "app_metadata": payload.get("app_metadata", {}),
        "user_metadata": payload.get("user_metadata", {}),
        "role": payload.get("role", "authenticated"),
    }


def _decode_token_remote(token: str) -> Dict[str, Any]:
    """Supabase Auth APIでトークンを検証する（フォールバック用）"""
    supabase = create_client(
        settings.SUPABASE_URL,
        settings.SUPABASE_ANON_KEY
    )
    user_response = supabase.auth.get_user(token)
    if not user_response or not user_response.user:
        raise TokenValidationError("無効なアクセストークンです", status_code=401)
    user = user_response.user
    return {
        "sub": user.id,
        "email": user.email,
        "app_metadata": user.app_metadata or {},
        "user_metadata": user.user_metadata or {},
        "role": user.role or "authenticated",
    }


def decode_token(token: str) -> Dict[str, Any]:
    """
    JWTトークンを検証する

    ローカルJWT検証を優先し、失敗時はSupabase Auth APIにフォールバック。
    JWT_SECRETが正しく設定されていればローカル検証のみで完結する。

    Args:
        token: Authorizationヘッダーから取得したJWTトークン

    Returns:
        Dict[str, Any]: トークンのペイロード（ユーザー情報を含む）

    Raises:
        TokenValidationError: トークンが無効、期限切れ、または検証失敗時
    """
    # ローカルJWT検証を試行
    try:
        return _decode_token_local(token)
    except (JWTError, Exception) as local_err:
        logger.warning("ローカルJWT検証失敗（リモートにフォールバック）: %s", local_err)

    # フォールバック: Supabase Auth APIで検証
    try:
        return _decode_token_remote(token)
    except TokenValidationError:
        raise
    except Exception as e:
        raise TokenValidationError(
            f"無効なアクセストークンです: {str(e)}",
            status_code=401
        )


def extract_user_info(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    トークンペイロードからユーザー情報を抽出する

    Supabase Authが発行するJWTのペイロード構造:
    {
        "sub": "uuid",              # ユーザーID
        "email": "user@example.com",
        "app_metadata": {
            "department_id": "uuid" # 部門ID（管理者が設定）
        },
        "user_metadata": {},
        "role": "authenticated",
        "aud": "authenticated",
        "iat": 1234567890,
        "exp": 1234567890
    }

    Args:
        payload: デコード済みのJWTペイロード

    Returns:
        Dict[str, Any]: 整形されたユーザー情報
            - user_id: ユーザーUUID
            - email: メールアドレス
            - department_id: 所属部門ID（存在する場合）
            - role: Supabaseロール
    """
    # app_metadataから部門IDを取得（設定されていない場合はNone）
    app_metadata = payload.get("app_metadata", {})
    department_id = app_metadata.get("department_id")

    # user_metadataからその他の情報を取得
    user_metadata = payload.get("user_metadata", {})

    return {
        "user_id": payload.get("sub"),
        "email": payload.get("email"),
        "department_id": department_id,
        "role": payload.get("role", "authenticated"),
        "user_metadata": user_metadata,
    }


def verify_token(token: str) -> Dict[str, Any]:
    """
    トークンを検証してユーザー情報を返す

    decode_tokenとextract_user_infoを組み合わせた便利関数。
    トークンの検証からユーザー情報の抽出まで一括で行う。

    Args:
        token: JWTトークン

    Returns:
        Dict[str, Any]: ユーザー情報

    Raises:
        TokenValidationError: トークン検証失敗時
    """
    payload = decode_token(token)
    return extract_user_info(payload)


def extract_token_from_header(authorization: Optional[str]) -> str:
    """
    Authorizationヘッダーからトークンを抽出する

    "Bearer <token>" 形式のヘッダー値からトークン部分を抽出する。

    Args:
        authorization: Authorizationヘッダーの値

    Returns:
        str: 抽出されたトークン

    Raises:
        TokenValidationError: ヘッダーが不正な形式の場合
    """
    if not authorization:
        raise TokenValidationError(
            "認証が必要です。Authorizationヘッダーにトークンを設定してください。",
            status_code=401
        )

    # "Bearer "プレフィックスを確認
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise TokenValidationError(
            "Authorizationヘッダーの形式が不正です。'Bearer <token>'の形式で指定してください。",
            status_code=401
        )

    return parts[1]
