-- =============================================================================
-- 取締役会資料・議事録テーブル作成マイグレーション
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
-- 1. 取締役会テーブル
-- =============================================================================

CREATE TABLE IF NOT EXISTS board_meetings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- 基本情報
    meeting_date DATE NOT NULL,                     -- 開催日
    title TEXT NOT NULL,                            -- タイトル（例: 第12回 取締役会）

    -- 資料（[{label, url}] 形式のJSONB配列）
    materials JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- 決議・報告トピック（[{category, title}] 形式のJSONB配列）
    -- category は '決議' または '報告'
    topics JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- 議事録本文
    minutes_text TEXT,

    -- メタデータ
    created_by UUID,                                -- 作成者
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_board_meetings_meeting_date ON board_meetings(meeting_date);
CREATE INDEX IF NOT EXISTS idx_board_meetings_created_at ON board_meetings(created_at);

-- =============================================================================
-- 2. RLS（Row Level Security）設定
-- =============================================================================

ALTER TABLE board_meetings ENABLE ROW LEVEL SECURITY;

-- 既存ポリシーを削除してから作成
DROP POLICY IF EXISTS "Allow authenticated users to view board_meetings" ON board_meetings;
DROP POLICY IF EXISTS "Allow service role full access to board_meetings" ON board_meetings;

-- 認証済みユーザー用ポリシー（参照のみ）
CREATE POLICY "Allow authenticated users to view board_meetings"
    ON board_meetings FOR SELECT TO authenticated USING (true);

-- service_role用フルアクセスポリシー
CREATE POLICY "Allow service role full access to board_meetings"
    ON board_meetings FOR ALL TO service_role USING (true) WITH CHECK (true);

-- =============================================================================
-- 3. 更新日時自動更新トリガー
-- =============================================================================

DROP TRIGGER IF EXISTS update_board_meetings_updated_at ON board_meetings;
CREATE TRIGGER update_board_meetings_updated_at
    BEFORE UPDATE ON board_meetings
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
