-- kpi_valuesテーブルへの複合インデックス追加
-- 店舗実績クエリがsegment_id IN, kpi_id IN, date =, is_target = falseで検索する際の高速化
-- 特に累計モードでの効果が大きい（-200〜500ms）

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_kpi_values_segment_kpi_date_target
    ON kpi_values(segment_id, kpi_id, date, is_target);
