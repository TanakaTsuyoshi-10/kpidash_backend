-- ページ閲覧権限テーブル
-- ユーザーごとに閲覧可能なページを管理する

CREATE TABLE user_page_permissions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
  page_key VARCHAR(50) NOT NULL CHECK (page_key IN (
    'dashboard', 'finance', 'ecommerce', 'manufacturing', 'products', 'upload', 'targets'
  )),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (user_id, page_key)
);

ALTER TABLE user_page_permissions ENABLE ROW LEVEL SECURITY;

-- ユーザーは自分の権限を読み取り可能
CREATE POLICY "users_read_own_permissions" ON user_page_permissions
  FOR SELECT USING (auth.uid() = user_id);

-- 管理者は全権限を管理可能
CREATE POLICY "admins_manage_permissions" ON user_page_permissions
  FOR ALL USING (
    EXISTS (SELECT 1 FROM user_profiles WHERE id = auth.uid() AND role = 'admin')
  );

-- service_role: RLSバイパス（バックエンド用）
CREATE POLICY "service_role_all" ON user_page_permissions
  FOR ALL TO service_role USING (true) WITH CHECK (true);
