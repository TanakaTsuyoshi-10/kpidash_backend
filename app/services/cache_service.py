"""
シンプルなインメモリキャッシュサービス
TTL（Time To Live）付きでデータをキャッシュ
"""
import time
import asyncio
from typing import Any, Optional, Dict, Callable
from functools import wraps
import hashlib
import inspect


class CacheService:
    """
    インメモリキャッシュ
    本番環境で大規模になる場合はRedisに移行を推奨
    """

    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}
        # デフォルトTTL（秒）
        self.default_ttl = 300  # 5分

    def _generate_key(self, prefix: str, *args, **kwargs) -> str:
        """キャッシュキーを生成"""
        # Supabaseクライアントなどのオブジェクトは除外
        filtered_args = tuple(
            arg for arg in args
            if not hasattr(arg, 'table')  # Supabase Client除外
            and not callable(arg)
        )
        filtered_kwargs = {
            k: v for k, v in kwargs.items()
            if not hasattr(v, 'table') and not callable(v)
        }
        key_data = f"{prefix}:{filtered_args}:{sorted(filtered_kwargs.items())}"
        return hashlib.md5(key_data.encode()).hexdigest()

    def get(self, key: str) -> Optional[Any]:
        """キャッシュからデータを取得"""
        if key not in self._cache:
            return None

        entry = self._cache[key]

        # TTLチェック
        if time.time() > entry['expires_at']:
            del self._cache[key]
            return None

        return entry['value']

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """キャッシュにデータを保存"""
        ttl = ttl or self.default_ttl
        self._cache[key] = {
            'value': value,
            'expires_at': time.time() + ttl,
            'created_at': time.time()
        }

    def delete(self, key: str) -> None:
        """キャッシュからデータを削除"""
        if key in self._cache:
            del self._cache[key]

    def clear_prefix(self, prefix: str) -> int:
        """指定プレフィックスのキャッシュを全削除"""
        keys_to_delete = [k for k in self._cache.keys() if k.startswith(prefix)]
        for key in keys_to_delete:
            del self._cache[key]
        return len(keys_to_delete)

    def clear_all(self) -> None:
        """全キャッシュをクリア"""
        self._cache.clear()

    def cleanup_expired(self) -> int:
        """期限切れキャッシュを削除"""
        current_time = time.time()
        expired_keys = [
            k for k, v in self._cache.items()
            if current_time > v['expires_at']
        ]
        for key in expired_keys:
            del self._cache[key]
        return len(expired_keys)

    def stats(self) -> Dict[str, Any]:
        """キャッシュ統計情報"""
        return {
            'total_entries': len(self._cache),
            'memory_keys': list(self._cache.keys())[:10]  # 最初の10件のみ
        }


# シングルトンインスタンス
cache = CacheService()


def cached(prefix: str, ttl: int = 300):
    """
    キャッシュデコレータ（同期・非同期両対応）

    使用例:
    @cached(prefix="dashboard", ttl=300)
    async def get_dashboard_data(supabase, period_type, year, month):
        ...
    """
    def decorator(func: Callable):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            # キャッシュキー生成
            key = cache._generate_key(prefix, *args, **kwargs)

            # キャッシュチェック
            cached_value = cache.get(key)
            if cached_value is not None:
                return cached_value

            # 関数実行
            result = await func(*args, **kwargs)

            # キャッシュ保存
            cache.set(key, result, ttl)

            return result

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            # キャッシュキー生成
            key = cache._generate_key(prefix, *args, **kwargs)

            # キャッシュチェック
            cached_value = cache.get(key)
            if cached_value is not None:
                return cached_value

            # 関数実行
            result = func(*args, **kwargs)

            # キャッシュ保存
            cache.set(key, result, ttl)

            return result

        # 非同期関数かどうかで適切なラッパーを返す
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def invalidate_cache(prefix: str):
    """
    キャッシュ無効化デコレータ
    データ更新時にキャッシュをクリア

    使用例:
    @invalidate_cache(prefix="dashboard")
    async def update_financial_data(...):
        ...
    """
    def decorator(func: Callable):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            result = await func(*args, **kwargs)
            cache.clear_prefix(prefix)
            return result

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            result = func(*args, **kwargs)
            cache.clear_prefix(prefix)
            return result

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator
