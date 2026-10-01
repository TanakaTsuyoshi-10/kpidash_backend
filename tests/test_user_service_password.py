"""パスワード再設定（管理者用）のユニットテスト"""
import asyncio
import re

from app.services.user_service import reset_user_password, _TEMP_PASSWORD_ALPHABET
from tests.test_target_service import FakeWritableSupabase


class _FakeAuthAdmin:
    def __init__(self, fail=False):
        self.calls = []
        self._fail = fail

    def update_user_by_id(self, uid, attrs):
        if self._fail:
            raise RuntimeError("auth api down")
        self.calls.append((uid, attrs))

        class _Res:
            user = object()
        return _Res()


class _FakeAuth:
    def __init__(self, fail=False):
        self.admin = _FakeAuthAdmin(fail)


def _fake(profile_rows, fail=False):
    fake = FakeWritableSupabase({"user_profiles": profile_rows})
    fake.auth = _FakeAuth(fail)
    return fake


class TestResetUserPassword:
    def test_success_generates_safe_temp_password(self):
        fake = _fake([{"id": "u1", "email": "x@gyo-za.co.jp"}])
        result = asyncio.run(reset_user_password(fake, "u1", "admin-1"))
        assert result.success is True
        assert result.email == "x@gyo-za.co.jp"
        # 形式: Gyoza- + 8文字（紛らわしい文字 0/O/1/l/I を含まない）
        assert re.fullmatch(r"Gyoza-[a-zA-Z2-9]{8}", result.temp_password)
        assert all(c in _TEMP_PASSWORD_ALPHABET for c in result.temp_password[6:])
        # Auth API に同じパスワードが渡っている
        uid, attrs = fake.auth.admin.calls[0]
        assert uid == "u1"
        assert attrs == {"password": result.temp_password}

    def test_user_not_found(self):
        fake = _fake([])
        result = asyncio.run(reset_user_password(fake, "missing", "admin-1"))
        assert result.success is False
        assert result.temp_password is None

    def test_auth_api_failure_returns_error(self):
        fake = _fake([{"id": "u1", "email": "x@gyo-za.co.jp"}], fail=True)
        result = asyncio.run(reset_user_password(fake, "u1", "admin-1"))
        assert result.success is False
        assert result.temp_password is None
