"""
目標設定サービスのユニットテスト

2026-09 の店舗目標保存後に GET が 500 になった実バグ
（kpi_values.id が int なのにスキーマが str で検証失敗）の回帰テストと、
前年欠損・前年0・部分入力のパターンを検証する。

実行: ./venv/bin/pytest tests/test_target_service.py -v
（pytest は requirements-dev.txt でインストール）
"""
import asyncio
from datetime import date
from decimal import Decimal

from app.services.target_service import (
    _calculate_yoy_rate,
    _calculate_sales_ratio,
    _to_decimal,
    get_target_matrix,
    get_ecommerce_targets,
    get_financial_targets,
)
from app.schemas.target import (
    StoreTargetMatrix,
    EcommerceTargetResponse,
    FinancialTargetResponse,
)


# =============================================================================
# 比率計算ヘルパー: 前年欠損・前年0・None はエラーにせず None を返す
# =============================================================================

class TestCalculateYoyRate:
    def test_normal(self):
        assert _calculate_yoy_rate(Decimal("110"), Decimal("100")) == Decimal("10.00")

    def test_previous_none(self):
        """前年実績なし（紫原店パターン）→ None"""
        assert _calculate_yoy_rate(Decimal("100"), None) is None

    def test_previous_zero(self):
        """前年実績が 0（本社パターン）→ ZeroDivisionError にせず None"""
        assert _calculate_yoy_rate(Decimal("100"), Decimal("0")) is None

    def test_current_none(self):
        """目標未入力（客数空欄パターン）→ None"""
        assert _calculate_yoy_rate(None, Decimal("100")) is None


class TestCalculateSalesRatio:
    def test_normal(self):
        assert _calculate_sales_ratio(Decimal("30"), Decimal("100")) == Decimal("30.00")

    def test_sales_none(self):
        assert _calculate_sales_ratio(Decimal("30"), None) is None

    def test_sales_zero(self):
        assert _calculate_sales_ratio(Decimal("30"), Decimal("0")) is None

    def test_value_none(self):
        assert _calculate_sales_ratio(None, Decimal("100")) is None


class TestToDecimal:
    def test_none(self):
        assert _to_decimal(None) is None

    def test_int_float_str(self):
        assert _to_decimal(100) == Decimal("100")
        assert _to_decimal(1.5) == Decimal("1.5")
        assert _to_decimal("2.5") == Decimal("2.5")


# =============================================================================
# 疑似 Supabase クライアント
# =============================================================================

class _FakeQuery:
    """table().select().eq()... .execute() のチェーンを再現する"""

    def __init__(self, rows):
        self._rows = rows

    def __getattr__(self, name):
        # eq / in_ / order / limit などは全て自身を返す（データはテーブル単位で固定）
        def _chain(*args, **kwargs):
            return self
        return _chain

    def execute(self):
        class _Res:
            def __init__(self, data):
                self.data = data
        return _Res(self._rows)


class FakeSupabase:
    """テーブル名 → 応答行リスト。呼び出し順にテーブル別の応答を返す。

    同じテーブルが複数回参照される場合（今月目標→前年実績）は、
    リストのリストを渡すと呼び出しごとに順番に消費する。
    """

    def __init__(self, tables):
        self._tables = dict(tables)
        self._call_counts = {}

    def table(self, name):
        rows = self._tables.get(name, [])
        if rows and isinstance(rows[0], list):
            idx = self._call_counts.get(name, 0)
            self._call_counts[name] = idx + 1
            rows = rows[idx] if idx < len(rows) else []
        return _FakeQuery(rows)


# =============================================================================
# 店舗目標マトリックス（Bug 1 回帰テスト）
# =============================================================================

SEG_HONSHA = "seg-honsha"
SEG_KANOYA = "seg-kanoya"
SEG_MURASAKIBARU = "seg-murasakibaru"
KPI_SALES = "kpi-sales"
KPI_CUSTOMERS = "kpi-customers"


def _store_fake_supabase():
    return FakeSupabase({
        "segments": [
            {"id": SEG_HONSHA, "code": "1", "name": "本社"},
            {"id": SEG_KANOYA, "code": "5", "name": "鹿屋店"},
            {"id": SEG_MURASAKIBARU, "code": "29", "name": "紫原店"},
        ],
        "kpi_definitions": [
            {"id": KPI_SALES, "name": "売上高", "unit": "円", "category": "全体"},
            {"id": KPI_CUSTOMERS, "name": "客数", "unit": "人", "category": "全体"},
        ],
        "kpi_values": [
            # 1回目の呼び出し: 今月の目標（売上のみ保存・客数は未保存＝部分入力）
            [
                # target_id は kpi_values.id で int（←これを str スキーマで受けて 500 になった）
                {"id": 10041, "segment_id": SEG_KANOYA, "kpi_id": KPI_SALES, "value": 5741065},
                {"id": 10042, "segment_id": SEG_HONSHA, "kpi_id": KPI_SALES, "value": 100000},
            ],
            # 2回目の呼び出し: 前年実績（本社=0、紫原店=行なし）
            [
                {"segment_id": SEG_HONSHA, "kpi_id": KPI_SALES, "value": 0},
                {"segment_id": SEG_KANOYA, "kpi_id": KPI_SALES, "value": 5000000},
                {"segment_id": SEG_KANOYA, "kpi_id": KPI_CUSTOMERS, "value": 12000},
            ],
        ],
    })


class TestGetTargetMatrix:
    def test_partial_save_with_int_ids_passes_schema(self):
        """売上のみ保存・前年0・前年欠損の混在でも取得成功し、
        int の target_id がスキーマ検証を通る（Bug 1 回帰）"""
        result = asyncio.run(
            get_target_matrix(_store_fake_supabase(), "dept-store", date(2026, 9, 1))
        )
        # response_model と同じ検証（ここで例外が出れば本番は 500）
        matrix = StoreTargetMatrix(**result)

        assert len(matrix.rows) == 3
        rows = {r.segment_name: r for r in matrix.rows}

        # 鹿屋店: 売上目標あり（int の target_id）、客数は未保存 → None
        kanoya = rows["鹿屋店"].values
        assert kanoya[KPI_SALES].target_id == 10041
        assert kanoya[KPI_SALES].value == Decimal("5741065")
        assert kanoya[KPI_CUSTOMERS].value is None
        assert kanoya[KPI_CUSTOMERS].target_id is None

        # 本社: 前年実績 0 でもエラーにならない
        honsha = rows["本社"].values
        assert honsha[KPI_SALES].last_year_actual == Decimal("0")

        # 紫原店: 前年実績なし → None（KeyError にならない）
        murasakibaru = rows["紫原店"].values
        assert murasakibaru[KPI_SALES].last_year_actual is None
        assert murasakibaru[KPI_SALES].value is None


# =============================================================================
# 通販目標（部分入力: 売上のみ・購入者数/顧客統計は空欄）
# =============================================================================

class TestGetEcommerceTargets:
    def test_channel_sales_only_without_customers(self):
        fake = FakeSupabase({
            "ecommerce_channel_sales": [
                # 今月目標: EC の売上のみ（buyers 空欄）
                [{"channel": "EC", "sales": 52000000, "buyers": None, "month": "2026-09-01"}],
                # 前年実績: EC あり（buyers あり）、電話は前年 0
                [
                    {"channel": "EC", "sales": 52202614, "buyers": 8000, "month": "2025-09-01"},
                    {"channel": "電話", "sales": 0, "buyers": 0, "month": "2025-09-01"},
                ],
            ],
            # 顧客統計は目標・前年とも未登録
            "ecommerce_customer_stats": [],
        })
        result = asyncio.run(get_ecommerce_targets(fake, date(2026, 9, 1)))
        assert isinstance(result, EcommerceTargetResponse)

        ec = next(c for c in result.channel_targets if c.channel == "EC")
        assert ec.target_sales == Decimal("52000000")
        assert ec.target_buyers is None
        assert ec.yoy_buyers_rate is None  # buyers 未入力 → None（エラーにしない）
        assert ec.yoy_sales_rate is not None

        # 前年 0 の電話チャネル: 前年比 None
        tel = next(c for c in result.channel_targets if c.channel == "電話")
        assert tel.yoy_sales_rate is None

        # 顧客統計未登録 → customer_target 自体が None
        assert result.customer_target is None


# =============================================================================
# 財務目標（前年欠損・前年0・部分入力）
# =============================================================================

class TestGetFinancialTargets:
    def test_partial_summary_with_zero_and_missing_prior(self):
        fake = FakeSupabase({
            "financial_data": [
                # 今月目標: 売上高のみ入力（他は空欄）
                [{"sales_total": 100000000, "sales_store": None, "sales_online": None,
                  "cost_of_sales": None, "gross_profit": None,
                  "sg_and_a_total": None, "operating_profit": None}],
                # 前年実績: 売上 0（0除算パターン）
                [{"sales_total": 0, "sales_store": 0, "sales_online": 0,
                  "cost_of_sales": 0, "gross_profit": 0,
                  "sg_and_a_total": 0, "operating_profit": 0}],
            ],
            # 原価・販管費明細は目標・前年とも未登録（欠損パターン）
            "financial_cost_details": [],
            "financial_sga_details": [],
        })
        result = asyncio.run(get_financial_targets(fake, date(2026, 9, 1)))
        assert isinstance(result, FinancialTargetResponse)

        summary = {i.field_name: i for i in result.summary_items}
        # 前年 0 → 前年比 None（ZeroDivisionError にしない）
        assert summary["sales_total"].yoy_rate is None
        assert summary["sales_total"].target_value == Decimal("100000000")
        # 未入力項目は None のまま
        assert summary["operating_profit"].target_value is None

        # 明細が未登録でも全項目 None で返る（KeyError にしない）
        assert all(i.target_value is None and i.last_year_actual is None
                   for i in result.cost_items)
        assert all(i.target_value is None and i.last_year_actual is None
                   for i in result.sga_items)
