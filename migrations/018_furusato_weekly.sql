-- =============================================
-- 018: ふるさと納税 週次データカラム追加
-- - weekly_sales, weekly_repeat, weekly_complaint, weekly_review (JSONB)
-- =============================================

ALTER TABLE furusato_nozei_stats
  ADD COLUMN IF NOT EXISTS weekly_sales JSONB,
  ADD COLUMN IF NOT EXISTS weekly_repeat JSONB,
  ADD COLUMN IF NOT EXISTS weekly_complaint JSONB,
  ADD COLUMN IF NOT EXISTS weekly_review JSONB;
