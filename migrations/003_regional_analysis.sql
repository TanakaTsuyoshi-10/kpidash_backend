-- =============================================================================
-- 地区別分析テーブル作成マイグレーション
-- =============================================================================

-- 地区マスタテーブル
CREATE TABLE IF NOT EXISTS regions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(50) NOT NULL UNIQUE,      -- 地区名: '都城地区', '宮崎地区' など
    display_order INTEGER DEFAULT 0,        -- 表示順
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 店舗-地区マッピングテーブル
CREATE TABLE IF NOT EXISTS store_region_mapping (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    segment_id UUID NOT NULL REFERENCES segments(id) ON DELETE CASCADE,
    region_id UUID NOT NULL REFERENCES regions(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(segment_id)  -- 1店舗は1地区にのみ所属
);

-- 地区別目標テーブル
CREATE TABLE IF NOT EXISTS regional_targets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    region_id UUID NOT NULL REFERENCES regions(id) ON DELETE CASCADE,
    month DATE NOT NULL,                    -- 対象月（YYYY-MM-01形式）
    target_sales DECIMAL(15, 2),            -- 目標売上高
    target_customers INTEGER,               -- 目標客数
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(region_id, month)
);

-- =============================================================================
-- インデックス作成
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_store_region_mapping_segment_id
    ON store_region_mapping(segment_id);
CREATE INDEX IF NOT EXISTS idx_store_region_mapping_region_id
    ON store_region_mapping(region_id);
CREATE INDEX IF NOT EXISTS idx_regional_targets_region_id
    ON regional_targets(region_id);
CREATE INDEX IF NOT EXISTS idx_regional_targets_month
    ON regional_targets(month);

-- =============================================================================
-- RLS（Row Level Security）設定
-- =============================================================================

ALTER TABLE regions ENABLE ROW LEVEL SECURITY;
ALTER TABLE store_region_mapping ENABLE ROW LEVEL SECURITY;
ALTER TABLE regional_targets ENABLE ROW LEVEL SECURITY;

-- 認証済みユーザーポリシー
CREATE POLICY "Allow authenticated users to view regions" ON regions
    FOR SELECT TO authenticated USING (true);

CREATE POLICY "Allow authenticated users to view store_region_mapping" ON store_region_mapping
    FOR SELECT TO authenticated USING (true);

CREATE POLICY "Allow authenticated users full access to regional_targets" ON regional_targets
    FOR ALL TO authenticated USING (true) WITH CHECK (true);

-- service_role用ポリシー
CREATE POLICY "Allow service role full access to regions" ON regions
    FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "Allow service role full access to store_region_mapping" ON store_region_mapping
    FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "Allow service role full access to regional_targets" ON regional_targets
    FOR ALL TO service_role USING (true) WITH CHECK (true);

-- =============================================================================
-- 初期データ投入：地区マスタ
-- =============================================================================

INSERT INTO regions (name, display_order) VALUES
    ('都城地区', 1),
    ('宮崎地区', 2),
    ('鹿児島地区', 3),
    ('福岡地区', 4),
    ('熊本地区', 5),
    ('その他', 99)
ON CONFLICT (name) DO NOTHING;

-- =============================================================================
-- 更新日時自動更新トリガー
-- =============================================================================

DROP TRIGGER IF EXISTS update_regions_updated_at ON regions;
CREATE TRIGGER update_regions_updated_at
    BEFORE UPDATE ON regions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_regional_targets_updated_at ON regional_targets;
CREATE TRIGGER update_regional_targets_updated_at
    BEFORE UPDATE ON regional_targets
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
