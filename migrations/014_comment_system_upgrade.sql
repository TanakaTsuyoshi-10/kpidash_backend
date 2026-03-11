-- =============================================================================
-- コメントシステムアップグレード マイグレーション
-- 複数コメント対応・編集履歴・全ユーザー編集可能
-- =============================================================================

-- UNIQUE制約を削除（1カテゴリ×1月に複数コメントを許可）
ALTER TABLE monthly_comments DROP CONSTRAINT IF EXISTS monthly_comments_category_period_key;

-- created_by_email カラム追加（既存コードが参照しているが未定義）
ALTER TABLE monthly_comments ADD COLUMN IF NOT EXISTS created_by_email TEXT;

-- 編集者追跡カラム追加
ALTER TABLE monthly_comments ADD COLUMN IF NOT EXISTS updated_by UUID REFERENCES auth.users(id);
ALTER TABLE monthly_comments ADD COLUMN IF NOT EXISTS updated_by_email TEXT;

-- =============================================================================
-- 編集履歴テーブル新規作成
-- =============================================================================

CREATE TABLE IF NOT EXISTS comment_edit_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    comment_id UUID NOT NULL REFERENCES monthly_comments(id) ON DELETE CASCADE,
    previous_comment TEXT NOT NULL,
    edited_by UUID REFERENCES auth.users(id),
    edited_by_email TEXT,
    edited_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_comment_edit_history_comment_id
    ON comment_edit_history(comment_id);

-- =============================================================================
-- RLS設定（編集履歴テーブル）
-- =============================================================================

ALTER TABLE comment_edit_history ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view comment history"
    ON comment_edit_history
    FOR SELECT
    TO authenticated
    USING (true);

CREATE POLICY "Service role full access to comment_edit_history"
    ON comment_edit_history
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);
