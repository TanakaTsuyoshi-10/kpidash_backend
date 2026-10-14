"""人事分析サービスの分類・判定ロジックのユニットテスト"""
from datetime import date

from app.services.hr_analytics_service import (
    _employment_group,
    _store_name,
    _department_bucket,
    _match_segment,
    _is_employed_at,
    _age_at,
    GROUP_FULLTIME, GROUP_CONTRACT, GROUP_PARTTIME, GROUP_UNSET,
)


class TestEmploymentGroup:
    def _crew(self, name):
        return {"employment_type": {"name": name} if name is not None else None}

    def test_fulltime(self):
        assert _employment_group(self._crew("正社員")) == GROUP_FULLTIME
        assert _employment_group(self._crew("役員")) == GROUP_FULLTIME

    def test_contract(self):
        assert _employment_group(self._crew("契約社員")) == GROUP_CONTRACT
        assert _employment_group(self._crew("派遣社員")) == GROUP_CONTRACT

    def test_parttime_variants(self):
        for name in ("アルバイト・パート", "パート（水・木・金）", "契約パート",
                     "月15日出勤", "週2日出勤", "年末期間限定", "その他"):
            assert _employment_group(self._crew(name)) == GROUP_PARTTIME, name

    def test_unset(self):
        assert _employment_group(self._crew(None)) == GROUP_UNSET
        assert _employment_group({}) == GROUP_UNSET


class TestStoreAndBucket:
    def test_store_name(self):
        assert _store_name("販売部門/福岡エリア/春日店") == "春日店"
        assert _store_name("販売部門/宮崎エリア") is None  # エリア止まり
        assert _store_name("製造部/梱包課") is None
        assert _store_name("") is None

    def test_department_bucket(self):
        assert _department_bucket("販売部門/熊本エリア/長嶺店") == "店舗部門"
        assert _department_bucket("製造部/ラップ") == "製造部門"
        assert _department_bucket("事務/通販事業部") == "通販部門"
        assert _department_bucket("事務/総務部") == "本社"
        assert _department_bucket("") == "部署未設定"


class TestMatchSegment:
    SEGMENTS = ["福岡有田店", "春日店", "長嶺店"]

    def test_exact(self):
        assert _match_segment("春日店", self.SEGMENTS) == "春日店"

    def test_suffix(self):
        """SmartHR「有田店」⇔ ダッシュボード「福岡有田店」"""
        assert _match_segment("有田店", self.SEGMENTS) == "福岡有田店"

    def test_no_match(self):
        assert _match_segment("存在しない店", self.SEGMENTS) is None


class TestEmployedAt:
    def test_basic(self):
        crew = {"entered_at": "2024-04-01", "resigned_at": "2026-03-31"}
        assert _is_employed_at(crew, date(2024, 3, 31)) is False  # 入社前
        assert _is_employed_at(crew, date(2024, 4, 30)) is True
        assert _is_employed_at(crew, date(2026, 3, 31)) is False  # 退職日以降は不在籍
        assert _is_employed_at(crew, date(2026, 3, 30)) is True

    def test_missing_entered(self):
        """入社日未登録（役員など）は退職していない限り在籍扱い"""
        assert _is_employed_at({"entered_at": None, "resigned_at": None}, date(2020, 1, 31)) is True

    def test_age(self):
        assert _age_at(date(1980, 10, 15), date(2026, 10, 14)) == 45
        assert _age_at(date(1980, 10, 14), date(2026, 10, 14)) == 46
