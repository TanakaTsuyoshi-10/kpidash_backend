-- =============================================================================
-- 031_org_departments_approval_scope.sql
-- 承認ワークフローの部署スコープ閲覧と利用者管理スキーム拡張
-- =============================================================================
-- 目的:
--   1. 組織上の部署マスタ org_departments を新設
--      （KPI分析用の departments テーブルとは別物）
--   2. user_profiles に 部署・役職・承認権限・稟議全社閲覧権限 を追加
--      ※ ページ閲覧権限（user_page_permissions）とは別軸の
--        「稟議の閲覧権限」を導入する
--   3. approval_requests に申請時の部署をスタンプし、
--      閲覧スコープ（自部署のみ / 全社）判定に使う
--   4. 過去に承認者に指定されたユーザーへ承認権限をバックフィル
-- =============================================================================

-- 1. 部署マスタ
CREATE TABLE IF NOT EXISTS org_departments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name varchar(100) NOT NULL UNIQUE,
    display_order int NOT NULL DEFAULT 0,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE org_departments ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "org_departments_select" ON org_departments;
CREATE POLICY "org_departments_select" ON org_departments
    FOR SELECT TO authenticated USING (true);

DROP POLICY IF EXISTS "org_departments_service_all" ON org_departments;
CREATE POLICY "org_departments_service_all" ON org_departments
    FOR ALL TO service_role USING (true) WITH CHECK (true);

-- 2. user_profiles 拡張
ALTER TABLE user_profiles
    ADD COLUMN IF NOT EXISTS org_department_id uuid REFERENCES org_departments(id),
    ADD COLUMN IF NOT EXISTS position varchar(100),
    ADD COLUMN IF NOT EXISTS can_approve boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS approval_view_all boolean NOT NULL DEFAULT false;

-- 3. approval_requests に部署スタンプ
ALTER TABLE approval_requests
    ADD COLUMN IF NOT EXISTS org_department_id uuid REFERENCES org_departments(id);

CREATE INDEX IF NOT EXISTS idx_approval_requests_org_department
ON approval_requests (org_department_id);

-- 4. バックフィル: 過去に承認ステップの担当者になったユーザーは承認権限持ち
UPDATE user_profiles SET can_approve = true
WHERE id IN (SELECT DISTINCT assignee_id FROM approval_steps WHERE assignee_id IS NOT NULL);

-- admin / executive は承認権限を既定で付与
UPDATE user_profiles SET can_approve = true WHERE role IN ('admin', 'executive');
