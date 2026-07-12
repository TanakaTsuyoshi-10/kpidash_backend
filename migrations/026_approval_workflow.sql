-- =============================================================================
-- 026_approval_workflow.sql
-- 承認ワークフロー機能（Phase 1: LINE / Instagram 投稿承認）
-- =============================================================================
-- 設計方針:
--   - 申請種別（request_types）を追加すれば経費・稟議などにも展開できる汎用構造
--   - 承認ステップは jsonb ではなくリレーショナルテーブル（approval_steps）。
--     差替・差戻など UPDATE 粒度が細かく、監査ログの FK に安定した PK が必要なため
--   - RLS は既存流儀（authenticated: SELECT / service_role: FOR ALL）。
--     書き込みはすべてバックエンドの service_role 経由で、権限は FastAPI 側で検査
-- =============================================================================

-- =============================================================================
-- 0. 前提関数の作成（存在しない場合のみ）
-- =============================================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- 1. 申請種別マスタ
-- =============================================================================

CREATE TABLE IF NOT EXISTS request_types (
    code TEXT PRIMARY KEY,                          -- 'line_post', 'instagram_post', 将来 'expense', 'ringi'
    label TEXT NOT NULL,                            -- 表示名（例: LINE公式アカウント投稿）
    description TEXT,                               -- 起票画面に出す説明
    default_approver_ids UUID[] NOT NULL DEFAULT '{}',  -- 既定の承認者候補（申請時に上書き可）
    default_approval_mode TEXT NOT NULL DEFAULT 'sequential'
        CHECK (default_approval_mode IN ('sequential', 'parallel_and', 'parallel_or')),
    content_schema JSONB NOT NULL DEFAULT '{}'::jsonb,  -- 将来の動的フォーム定義用（Phase1 は未使用）
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    display_order INT NOT NULL DEFAULT 100,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- =============================================================================
-- 2. 申請本体
-- =============================================================================

CREATE TABLE IF NOT EXISTS approval_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    request_type TEXT NOT NULL REFERENCES request_types(code),
    title TEXT NOT NULL,

    -- draft: 下書き / pending: 承認待ち / approved: 全承認完了（Slack投稿前）
    -- rejected: 却下 / cancelled: 取下げ / published: Slack投稿済み / publish_failed: 投稿失敗
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'pending', 'approved', 'rejected',
                          'cancelled', 'published', 'publish_failed')),

    approval_mode TEXT NOT NULL DEFAULT 'sequential'
        CHECK (approval_mode IN ('sequential', 'parallel_and', 'parallel_or')),

    -- 申請コンテンツ（種別ごとに構造が異なるため jsonb）
    -- line_post/instagram_post: { caption_html, caption_plain, attachments: [{path, url, filename}], schedule_note }
    content JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- その他メタ（slack_channel_id: 投稿先チャンネル、stalled: 停滞フラグ 等）
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,

    requester_id UUID NOT NULL,                     -- auth.users.id
    requester_email TEXT NOT NULL DEFAULT '',       -- 通知用に非正規化

    current_step_no INT NOT NULL DEFAULT 1,         -- sequential 用カーソル

    submitted_at TIMESTAMP WITH TIME ZONE,
    approved_at TIMESTAMP WITH TIME ZONE,
    rejected_at TIMESTAMP WITH TIME ZONE,
    published_at TIMESTAMP WITH TIME ZONE,
    soft_deleted_at TIMESTAMP WITH TIME ZONE,       -- 監査のため物理削除しない

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_approval_requests_status_requester
    ON approval_requests(status, requester_id);
CREATE INDEX IF NOT EXISTS idx_approval_requests_type_status
    ON approval_requests(request_type, status);
CREATE INDEX IF NOT EXISTS idx_approval_requests_created_at
    ON approval_requests(created_at DESC);

-- =============================================================================
-- 3. 承認ステップ（1段 = 1レコード）
-- =============================================================================

CREATE TABLE IF NOT EXISTS approval_steps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id UUID NOT NULL REFERENCES approval_requests(id) ON DELETE CASCADE,

    step_no INT NOT NULL,                           -- sequential: 1..N / parallel_*: 全員 1

    assignee_id UUID NOT NULL,                      -- 現在の承認者（差替時はここを更新）
    original_assignee_id UUID NOT NULL,             -- 申請時の当初承認者（差替追跡用）
    assignee_email TEXT NOT NULL DEFAULT '',        -- 通知用に非正規化

    -- pending: 承認待ち / approved: 承認 / rejected: 却下
    -- skipped: parallel_or で他者承認により不要化 / delegated: 代理に委譲済み（旧行の目印）
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected', 'skipped', 'delegated')),

    acted_at TIMESTAMP WITH TIME ZONE,
    comment TEXT,
    notified_at TIMESTAMP WITH TIME ZONE,           -- メール送信の冪等化・督促判定用

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    UNIQUE (request_id, step_no, assignee_id)
);

CREATE INDEX IF NOT EXISTS idx_approval_steps_assignee_status
    ON approval_steps(assignee_id, status);
CREATE INDEX IF NOT EXISTS idx_approval_steps_request_step
    ON approval_steps(request_id, step_no);

-- =============================================================================
-- 4. 監査証跡
-- =============================================================================

CREATE TABLE IF NOT EXISTS approval_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id UUID NOT NULL REFERENCES approval_requests(id) ON DELETE CASCADE,
    step_id UUID REFERENCES approval_steps(id) ON DELETE SET NULL,  -- ルート変更等は step なし

    actor_id UUID NOT NULL,                         -- 実施者（代理承認時は代理人）
    actor_email TEXT NOT NULL DEFAULT '',
    on_behalf_of_id UUID,                           -- 誰の代理か（代理承認時のみ）

    action TEXT NOT NULL
        CHECK (action IN ('submit', 'resubmit', 'approve', 'reject',
                          'return_to_requester', 'return_to_step',
                          'reassign', 'add_approver', 'remove_approver',
                          'delegate_auto', 'cancel',
                          'publish_success', 'publish_failed', 'notify_failed')),

    before_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    after_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    comment TEXT,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_approval_actions_request_created
    ON approval_actions(request_id, created_at);

-- =============================================================================
-- 5. 代理承認設定（不在期間の事前設定）
-- =============================================================================

CREATE TABLE IF NOT EXISTS approval_delegates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,                          -- 委任元（不在になる本人）
    delegate_id UUID NOT NULL,                      -- 委任先
    starts_at TIMESTAMP WITH TIME ZONE NOT NULL,
    ends_at TIMESTAMP WITH TIME ZONE NOT NULL,
    note TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    CHECK (starts_at < ends_at),
    CHECK (user_id <> delegate_id)
);

-- 同一ユーザーの有効期間が重複しないよう運用（厳密な排他制約は Phase2 で検討）
CREATE INDEX IF NOT EXISTS idx_approval_delegates_user_period
    ON approval_delegates(user_id, starts_at, ends_at);

-- =============================================================================
-- 6. Slack 投稿先バインディング（申請種別 × チャンネル 1..N）
-- =============================================================================

CREATE TABLE IF NOT EXISTS slack_channel_bindings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_type TEXT NOT NULL REFERENCES request_types(code) ON DELETE CASCADE,
    label TEXT NOT NULL,                            -- UI 表示名（例: 「フード用」「コーポレート用」）
    channel_id TEXT NOT NULL,                       -- Slack チャンネルID（C0XXXXXX）
    channel_name TEXT NOT NULL DEFAULT '',          -- 表示用チャンネル名（#xxx）
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    UNIQUE (request_type, channel_id)
);

CREATE INDEX IF NOT EXISTS idx_slack_channel_bindings_type
    ON slack_channel_bindings(request_type);

-- =============================================================================
-- 7. RLS 設定（既存流儀: authenticated SELECT / service_role FOR ALL）
-- =============================================================================

ALTER TABLE request_types ENABLE ROW LEVEL SECURITY;
ALTER TABLE approval_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE approval_steps ENABLE ROW LEVEL SECURITY;
ALTER TABLE approval_actions ENABLE ROW LEVEL SECURITY;
ALTER TABLE approval_delegates ENABLE ROW LEVEL SECURITY;
ALTER TABLE slack_channel_bindings ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Allow authenticated users to view request_types" ON request_types;
CREATE POLICY "Allow authenticated users to view request_types"
    ON request_types FOR SELECT TO authenticated USING (true);
DROP POLICY IF EXISTS "Allow service role full access to request_types" ON request_types;
CREATE POLICY "Allow service role full access to request_types"
    ON request_types FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Allow authenticated users to view approval_requests" ON approval_requests;
CREATE POLICY "Allow authenticated users to view approval_requests"
    ON approval_requests FOR SELECT TO authenticated USING (true);
DROP POLICY IF EXISTS "Allow service role full access to approval_requests" ON approval_requests;
CREATE POLICY "Allow service role full access to approval_requests"
    ON approval_requests FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Allow authenticated users to view approval_steps" ON approval_steps;
CREATE POLICY "Allow authenticated users to view approval_steps"
    ON approval_steps FOR SELECT TO authenticated USING (true);
DROP POLICY IF EXISTS "Allow service role full access to approval_steps" ON approval_steps;
CREATE POLICY "Allow service role full access to approval_steps"
    ON approval_steps FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Allow authenticated users to view approval_actions" ON approval_actions;
CREATE POLICY "Allow authenticated users to view approval_actions"
    ON approval_actions FOR SELECT TO authenticated USING (true);
DROP POLICY IF EXISTS "Allow service role full access to approval_actions" ON approval_actions;
CREATE POLICY "Allow service role full access to approval_actions"
    ON approval_actions FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Allow authenticated users to view approval_delegates" ON approval_delegates;
CREATE POLICY "Allow authenticated users to view approval_delegates"
    ON approval_delegates FOR SELECT TO authenticated USING (true);
DROP POLICY IF EXISTS "Allow service role full access to approval_delegates" ON approval_delegates;
CREATE POLICY "Allow service role full access to approval_delegates"
    ON approval_delegates FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Allow authenticated users to view slack_channel_bindings" ON slack_channel_bindings;
CREATE POLICY "Allow authenticated users to view slack_channel_bindings"
    ON slack_channel_bindings FOR SELECT TO authenticated USING (true);
DROP POLICY IF EXISTS "Allow service role full access to slack_channel_bindings" ON slack_channel_bindings;
CREATE POLICY "Allow service role full access to slack_channel_bindings"
    ON slack_channel_bindings FOR ALL TO service_role USING (true) WITH CHECK (true);

-- =============================================================================
-- 8. 更新日時自動更新トリガー
-- =============================================================================

DROP TRIGGER IF EXISTS update_request_types_updated_at ON request_types;
CREATE TRIGGER update_request_types_updated_at
    BEFORE UPDATE ON request_types
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_approval_requests_updated_at ON approval_requests;
CREATE TRIGGER update_approval_requests_updated_at
    BEFORE UPDATE ON approval_requests
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_approval_steps_updated_at ON approval_steps;
CREATE TRIGGER update_approval_steps_updated_at
    BEFORE UPDATE ON approval_steps
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_approval_delegates_updated_at ON approval_delegates;
CREATE TRIGGER update_approval_delegates_updated_at
    BEFORE UPDATE ON approval_delegates
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_slack_channel_bindings_updated_at ON slack_channel_bindings;
CREATE TRIGGER update_slack_channel_bindings_updated_at
    BEFORE UPDATE ON slack_channel_bindings
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- =============================================================================
-- 9. user_page_permissions の CHECK 制約に 'approvals' を追加
-- =============================================================================

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
    'slack',
    'approvals'
  ));

-- =============================================================================
-- 10. Storage バケット（承認申請の添付画像）
-- =============================================================================

INSERT INTO storage.buckets (id, name, public)
VALUES ('approvals-attachments', 'approvals-attachments', true)
ON CONFLICT (id) DO NOTHING;

-- 認証済みユーザーは参照可、書き込みは service_role（バックエンド）経由のみ
DROP POLICY IF EXISTS "Allow authenticated read approvals-attachments" ON storage.objects;
CREATE POLICY "Allow authenticated read approvals-attachments"
    ON storage.objects FOR SELECT TO authenticated
    USING (bucket_id = 'approvals-attachments');

DROP POLICY IF EXISTS "Allow service role manage approvals-attachments" ON storage.objects;
CREATE POLICY "Allow service role manage approvals-attachments"
    ON storage.objects FOR ALL TO service_role
    USING (bucket_id = 'approvals-attachments')
    WITH CHECK (bucket_id = 'approvals-attachments');

-- =============================================================================
-- 11. 初期データ（Phase 1 の申請種別）
-- =============================================================================

INSERT INTO request_types (code, label, description, default_approval_mode, display_order)
VALUES
    ('line_post', 'LINE公式アカウント投稿',
     'LINE公式アカウントで配信する投稿コンテンツ（キャプション＋画像）の承認申請', 'sequential', 10),
    ('instagram_post', 'Instagram投稿',
     'Instagramで配信する投稿コンテンツ（キャプション＋画像）の承認申請', 'sequential', 20)
ON CONFLICT (code) DO NOTHING;
