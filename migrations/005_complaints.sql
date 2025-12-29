-- =============================================================================
-- クレーム管理テーブル作成マイグレーション
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
-- 1. クレームテーブル
-- =============================================================================

CREATE TABLE IF NOT EXISTS complaints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- 基本情報
    incident_date DATE NOT NULL,                    -- 発生日
    registered_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(), -- 登録日時

    -- 発生部署
    department_type VARCHAR(20) NOT NULL,           -- 発生部署種類: 'store', 'ecommerce', 'headquarters'
    segment_id UUID,                                -- 店舗ID（店舗の場合のみ）

    -- 顧客情報
    customer_type VARCHAR(20) NOT NULL,             -- 顧客種類: 'new', 'repeat', 'unknown'
    customer_name VARCHAR(100),                     -- 顧客名
    contact_info VARCHAR(200),                      -- 連絡先

    -- クレーム情報
    complaint_type VARCHAR(50) NOT NULL,            -- クレーム種類: 'customer_service', 'facility', 'operation', 'product', 'other'
    complaint_content TEXT NOT NULL,                -- クレーム内容

    -- 対応情報
    responder_name VARCHAR(100),                    -- 対応者名
    status VARCHAR(20) NOT NULL DEFAULT 'in_progress', -- 対応状況: 'in_progress', 'completed'
    response_summary TEXT,                          -- 対応の概要
    resolution_cost DECIMAL(12, 2) DEFAULT 0,       -- 対応に要した金額

    -- 完了情報
    completed_at TIMESTAMP WITH TIME ZONE,          -- 完了日時

    -- メタデータ
    created_by UUID,                                -- 作成者
    created_by_email VARCHAR(255),                  -- 作成者メールアドレス
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- segmentsテーブルが存在する場合のみ外部キー制約を追加
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'segments') THEN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.table_constraints
            WHERE constraint_name = 'complaints_segment_id_fkey'
            AND table_name = 'complaints'
        ) THEN
            ALTER TABLE complaints
            ADD CONSTRAINT complaints_segment_id_fkey
            FOREIGN KEY (segment_id) REFERENCES segments(id) ON DELETE SET NULL;
        END IF;
    END IF;
END $$;

-- インデックス
CREATE INDEX IF NOT EXISTS idx_complaints_incident_date ON complaints(incident_date);
CREATE INDEX IF NOT EXISTS idx_complaints_department_type ON complaints(department_type);
CREATE INDEX IF NOT EXISTS idx_complaints_segment_id ON complaints(segment_id);
CREATE INDEX IF NOT EXISTS idx_complaints_complaint_type ON complaints(complaint_type);
CREATE INDEX IF NOT EXISTS idx_complaints_status ON complaints(status);
CREATE INDEX IF NOT EXISTS idx_complaints_created_at ON complaints(created_at);

-- 月別集計用（incident_dateインデックスで代用可能なため、専用インデックスは不要）

-- =============================================================================
-- 2. クレーム種類マスタテーブル（参照用）
-- =============================================================================

CREATE TABLE IF NOT EXISTS complaint_types (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code VARCHAR(50) NOT NULL UNIQUE,               -- コード: 'customer_service', 'facility', etc.
    name VARCHAR(100) NOT NULL,                     -- 表示名
    display_order INTEGER DEFAULT 0,                -- 表示順
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 初期データ投入
INSERT INTO complaint_types (code, name, display_order) VALUES
    ('customer_service', '接客関連', 1),
    ('facility', '店舗設備関連', 2),
    ('operation', '操作方法関連', 3),
    ('product', '味・商品関連', 4),
    ('other', 'その他', 99)
ON CONFLICT (code) DO NOTHING;

-- =============================================================================
-- 3. 発生部署種類マスタテーブル（参照用）
-- =============================================================================

CREATE TABLE IF NOT EXISTS department_types (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code VARCHAR(20) NOT NULL UNIQUE,               -- コード: 'store', 'ecommerce', 'headquarters'
    name VARCHAR(50) NOT NULL,                      -- 表示名
    display_order INTEGER DEFAULT 0,                -- 表示順
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 初期データ投入
INSERT INTO department_types (code, name, display_order) VALUES
    ('store', '店舗', 1),
    ('ecommerce', '通販', 2),
    ('headquarters', '本社', 3)
ON CONFLICT (code) DO NOTHING;

-- =============================================================================
-- 4. 顧客種類マスタテーブル（参照用）
-- =============================================================================

CREATE TABLE IF NOT EXISTS customer_types (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code VARCHAR(20) NOT NULL UNIQUE,               -- コード: 'new', 'repeat', 'unknown'
    name VARCHAR(50) NOT NULL,                      -- 表示名
    display_order INTEGER DEFAULT 0,                -- 表示順
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 初期データ投入
INSERT INTO customer_types (code, name, display_order) VALUES
    ('new', '新規顧客', 1),
    ('repeat', 'リピーター', 2),
    ('unknown', '不明', 3)
ON CONFLICT (code) DO NOTHING;

-- =============================================================================
-- 5. 月別クレーム集計ビュー
-- =============================================================================

CREATE OR REPLACE VIEW view_complaints_monthly_summary AS
SELECT
    DATE_TRUNC('month', incident_date)::DATE as month,
    COUNT(*) as total_count,
    COUNT(*) FILTER (WHERE status = 'completed') as completed_count,
    COUNT(*) FILTER (WHERE status = 'in_progress') as in_progress_count,
    COUNT(*) FILTER (WHERE department_type = 'store') as store_count,
    COUNT(*) FILTER (WHERE department_type = 'ecommerce') as ecommerce_count,
    COUNT(*) FILTER (WHERE department_type = 'headquarters') as headquarters_count,
    COUNT(*) FILTER (WHERE complaint_type = 'customer_service') as customer_service_count,
    COUNT(*) FILTER (WHERE complaint_type = 'facility') as facility_count,
    COUNT(*) FILTER (WHERE complaint_type = 'operation') as operation_count,
    COUNT(*) FILTER (WHERE complaint_type = 'product') as product_count,
    COUNT(*) FILTER (WHERE complaint_type = 'other') as other_count,
    COALESCE(SUM(resolution_cost), 0) as total_resolution_cost
FROM complaints
GROUP BY DATE_TRUNC('month', incident_date);

-- =============================================================================
-- 6. RLS（Row Level Security）設定
-- =============================================================================

ALTER TABLE complaints ENABLE ROW LEVEL SECURITY;
ALTER TABLE complaint_types ENABLE ROW LEVEL SECURITY;
ALTER TABLE department_types ENABLE ROW LEVEL SECURITY;
ALTER TABLE customer_types ENABLE ROW LEVEL SECURITY;

-- 既存ポリシーを削除してから作成
DROP POLICY IF EXISTS "Allow authenticated users to view complaints" ON complaints;
DROP POLICY IF EXISTS "Allow authenticated users to insert complaints" ON complaints;
DROP POLICY IF EXISTS "Allow authenticated users to update complaints" ON complaints;
DROP POLICY IF EXISTS "Allow authenticated users to delete complaints" ON complaints;
DROP POLICY IF EXISTS "Allow service role full access to complaints" ON complaints;

DROP POLICY IF EXISTS "Allow authenticated users to view complaint_types" ON complaint_types;
DROP POLICY IF EXISTS "Allow service role full access to complaint_types" ON complaint_types;

DROP POLICY IF EXISTS "Allow authenticated users to view department_types" ON department_types;
DROP POLICY IF EXISTS "Allow service role full access to department_types" ON department_types;

DROP POLICY IF EXISTS "Allow authenticated users to view customer_types" ON customer_types;
DROP POLICY IF EXISTS "Allow service role full access to customer_types" ON customer_types;

-- 認証済みユーザー用ポリシー
CREATE POLICY "Allow authenticated users to view complaints"
    ON complaints FOR SELECT TO authenticated USING (true);

CREATE POLICY "Allow authenticated users to insert complaints"
    ON complaints FOR INSERT TO authenticated WITH CHECK (true);

CREATE POLICY "Allow authenticated users to update complaints"
    ON complaints FOR UPDATE TO authenticated USING (true) WITH CHECK (true);

CREATE POLICY "Allow authenticated users to delete complaints"
    ON complaints FOR DELETE TO authenticated USING (true);

CREATE POLICY "Allow authenticated users to view complaint_types"
    ON complaint_types FOR SELECT TO authenticated USING (true);

CREATE POLICY "Allow authenticated users to view department_types"
    ON department_types FOR SELECT TO authenticated USING (true);

CREATE POLICY "Allow authenticated users to view customer_types"
    ON customer_types FOR SELECT TO authenticated USING (true);

-- service_role用フルアクセスポリシー
CREATE POLICY "Allow service role full access to complaints"
    ON complaints FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "Allow service role full access to complaint_types"
    ON complaint_types FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "Allow service role full access to department_types"
    ON department_types FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "Allow service role full access to customer_types"
    ON customer_types FOR ALL TO service_role USING (true) WITH CHECK (true);

-- =============================================================================
-- 7. 更新日時自動更新トリガー
-- =============================================================================

DROP TRIGGER IF EXISTS update_complaints_updated_at ON complaints;
CREATE TRIGGER update_complaints_updated_at
    BEFORE UPDATE ON complaints
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- =============================================================================
-- 8. 完了日時自動設定トリガー
-- =============================================================================

CREATE OR REPLACE FUNCTION set_complaint_completed_at()
RETURNS TRIGGER AS $$
BEGIN
    -- 対応済みに変更された場合、完了日時を設定
    IF NEW.status = 'completed' AND OLD.status != 'completed' THEN
        NEW.completed_at = NOW();
    END IF;
    -- 対応中に戻された場合、完了日時をクリア
    IF NEW.status = 'in_progress' AND OLD.status = 'completed' THEN
        NEW.completed_at = NULL;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS set_complaint_completed_at_trigger ON complaints;
CREATE TRIGGER set_complaint_completed_at_trigger
    BEFORE UPDATE ON complaints
    FOR EACH ROW
    EXECUTE FUNCTION set_complaint_completed_at();
