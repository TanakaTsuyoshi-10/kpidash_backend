-- kpi_values テーブルに UNIQUE 制約を追加
-- upsert (on_conflict="segment_id,kpi_id,date,is_target") が正しく動作するために必要
--
-- 注意: 重複データが既に存在する場合、先にクリーンアップが必要
-- 以下のクエリで重複を確認:
--   SELECT segment_id, kpi_id, date, is_target, COUNT(*)
--   FROM kpi_values
--   GROUP BY segment_id, kpi_id, date, is_target
--   HAVING COUNT(*) > 1;

-- Step 1: 重複データを削除（最新のレコードを残す）
DELETE FROM kpi_values
WHERE id NOT IN (
    SELECT MAX(id)
    FROM kpi_values
    GROUP BY segment_id, kpi_id, date, is_target
);

-- Step 2: UNIQUE インデックスを作成
CREATE UNIQUE INDEX IF NOT EXISTS idx_kpi_values_unique
    ON kpi_values(segment_id, kpi_id, date, is_target);
