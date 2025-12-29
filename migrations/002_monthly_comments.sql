-- =============================================================================
-- 月次コメントテーブル作成マイグレーション
-- =============================================================================

-- 月次コメントテーブル
CREATE TABLE IF NOT EXISTS monthly_comments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category VARCHAR(50) NOT NULL,  -- 'store', 'ecommerce', 'finance', 'manufacturing'
    period DATE NOT NULL,           -- 月初日 'YYYY-MM-01'
    comment TEXT NOT NULL,
    created_by UUID REFERENCES auth.users(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(category, period)
);

-- =============================================================================
-- インデックス作成
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_monthly_comments_category
    ON monthly_comments(category);
CREATE INDEX IF NOT EXISTS idx_monthly_comments_period
    ON monthly_comments(period);
CREATE INDEX IF NOT EXISTS idx_monthly_comments_category_period
    ON monthly_comments(category, period);

-- =============================================================================
-- RLS（Row Level Security）設定
-- =============================================================================

-- RLSを有効化
ALTER TABLE monthly_comments ENABLE ROW LEVEL SECURITY;

-- 認証済みユーザーはすべてのコメントを閲覧可能
CREATE POLICY "Users can view all comments" ON monthly_comments
    FOR SELECT
    TO authenticated
    USING (true);

-- 認証済みユーザーはコメントを作成可能
CREATE POLICY "Authenticated users can insert comments" ON monthly_comments
    FOR INSERT
    TO authenticated
    WITH CHECK (auth.uid() IS NOT NULL);

-- 認証済みユーザーはコメントを更新可能
CREATE POLICY "Authenticated users can update comments" ON monthly_comments
    FOR UPDATE
    TO authenticated
    USING (auth.uid() IS NOT NULL);

-- 認証済みユーザーはコメントを削除可能
CREATE POLICY "Authenticated users can delete comments" ON monthly_comments
    FOR DELETE
    TO authenticated
    USING (auth.uid() IS NOT NULL);

-- service_role用ポリシー
CREATE POLICY "Allow service role full access to monthly_comments"
    ON monthly_comments
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- =============================================================================
-- 更新日時自動更新トリガー
-- =============================================================================

DROP TRIGGER IF EXISTS update_monthly_comments_updated_at ON monthly_comments;
CREATE TRIGGER update_monthly_comments_updated_at
    BEFORE UPDATE ON monthly_comments
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
