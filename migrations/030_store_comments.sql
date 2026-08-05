-- =============================================================================
-- 030_store_comments.sql
-- 店舗詳細ページのコメント機能: monthly_comments に店舗スコープを追加
-- =============================================================================
-- 目的:
--   店舗詳細ページ（/products/[segmentId]）で店舗×月単位のコメントを
--   記入できるようにする。既存の部門レベル月次コメント（segment_id IS NULL）
--   とは分離され、既存機能への影響はない（GET は segment_id 未指定時に
--   IS NULL でフィルタする）。編集履歴・全員編集可は既存の仕組みを共有。
-- =============================================================================

ALTER TABLE monthly_comments
ADD COLUMN IF NOT EXISTS segment_id uuid REFERENCES segments(id);

CREATE INDEX IF NOT EXISTS idx_monthly_comments_cat_period_segment
ON monthly_comments (category, period, segment_id);
