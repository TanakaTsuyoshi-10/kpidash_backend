-- ============================================================================
-- 025_extend_page_permissions_check.sql
-- user_page_permissions.page_key の CHECK 制約を最新のページキー一覧で更新
-- ============================================================================
-- 背景:
--   初期マイグレーションでの CHECK 制約は dashboard / finance / ecommerce /
--   manufacturing / complaints / products / upload / targets の 8 キーのみ
--   だった。その後 board（取締役会）/ labor（経営指標）/ slack（Slack投稿）
--   を PageKey enum に追加したが DB 側の制約は更新していなかった。
--   そのため一般利用者に board/labor/slack の閲覧権限を付与しようとすると
--   "user_page_permissions_page_key_check" 違反でエラーになっていた。
--
-- 修正:
--   既存の制約を DROP し、全 11 キーを許可するように張り直す。
-- ============================================================================

ALTER TABLE public.user_page_permissions
  DROP CONSTRAINT IF EXISTS user_page_permissions_page_key_check;

ALTER TABLE public.user_page_permissions
  ADD CONSTRAINT user_page_permissions_page_key_check
  CHECK (page_key IN (
    'dashboard',
    'finance',
    'ecommerce',
    'manufacturing',
    'complaints',
    'products',
    'upload',
    'targets',
    'board',
    'labor',
    'slack'
  ));
