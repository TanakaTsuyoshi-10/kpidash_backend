-- =============================================================================
-- 財務詳細・店舗別収支テーブル作成マイグレーション
-- =============================================================================

-- =============================================================================
-- 1. 売上原価明細テーブル
-- =============================================================================

CREATE TABLE IF NOT EXISTS financial_cost_details (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    period DATE NOT NULL,                           -- 対象月（YYYY-MM-01形式）

    -- 売上原価の内訳
    purchases DECIMAL(15, 2) DEFAULT 0,             -- 仕入高
    raw_material_purchases DECIMAL(15, 2) DEFAULT 0, -- 原材料仕入高
    labor_cost DECIMAL(15, 2) DEFAULT 0,            -- 労務費
    consumables DECIMAL(15, 2) DEFAULT 0,           -- 消耗品費
    rent DECIMAL(15, 2) DEFAULT 0,                  -- 賃借料
    repairs DECIMAL(15, 2) DEFAULT 0,               -- 修繕費
    utilities DECIMAL(15, 2) DEFAULT 0,             -- 水道光熱費
    -- その他は売上原価合計との差額として計算（保存しない）

    is_target BOOLEAN DEFAULT false,                -- 目標/実績フラグ
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    UNIQUE(period, is_target)
);

CREATE INDEX IF NOT EXISTS idx_financial_cost_details_period
    ON financial_cost_details(period);

-- =============================================================================
-- 2. 販管費明細テーブル
-- =============================================================================

CREATE TABLE IF NOT EXISTS financial_sga_details (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    period DATE NOT NULL,                           -- 対象月（YYYY-MM-01形式）

    -- 販管費の内訳
    executive_compensation DECIMAL(15, 2) DEFAULT 0, -- 役員報酬
    personnel_cost DECIMAL(15, 2) DEFAULT 0,        -- 人件費（販管費）
    delivery_cost DECIMAL(15, 2) DEFAULT 0,         -- 配送費
    packaging_cost DECIMAL(15, 2) DEFAULT 0,        -- 包装費
    payment_fees DECIMAL(15, 2) DEFAULT 0,          -- 支払手数料
    freight_cost DECIMAL(15, 2) DEFAULT 0,          -- 荷造運賃費
    sales_commission DECIMAL(15, 2) DEFAULT 0,      -- 販売手数料
    advertising_cost DECIMAL(15, 2) DEFAULT 0,      -- 広告宣伝費
    -- その他は販管費合計との差額として計算（保存しない）

    is_target BOOLEAN DEFAULT false,                -- 目標/実績フラグ
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    UNIQUE(period, is_target)
);

CREATE INDEX IF NOT EXISTS idx_financial_sga_details_period
    ON financial_sga_details(period);

-- =============================================================================
-- 3. 店舗別収支テーブル
-- =============================================================================

CREATE TABLE IF NOT EXISTS store_pl (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    segment_id UUID NOT NULL REFERENCES segments(id) ON DELETE CASCADE,
    period DATE NOT NULL,                           -- 対象月（YYYY-MM-01形式）

    -- 収支項目
    sales DECIMAL(15, 2) DEFAULT 0,                 -- 売上高
    cost_of_sales DECIMAL(15, 2) DEFAULT 0,         -- 売上原価
    gross_profit DECIMAL(15, 2) DEFAULT 0,          -- 売上総利益（計算値も可）
    sga_total DECIMAL(15, 2) DEFAULT 0,             -- 販管費合計
    operating_profit DECIMAL(15, 2) DEFAULT 0,      -- 営業利益（計算値も可）

    is_target BOOLEAN DEFAULT false,                -- 目標/実績フラグ
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    UNIQUE(segment_id, period, is_target)
);

CREATE INDEX IF NOT EXISTS idx_store_pl_segment_id ON store_pl(segment_id);
CREATE INDEX IF NOT EXISTS idx_store_pl_period ON store_pl(period);

-- =============================================================================
-- 4. 店舗別販管費明細テーブル
-- =============================================================================

CREATE TABLE IF NOT EXISTS store_pl_sga_details (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    store_pl_id UUID NOT NULL REFERENCES store_pl(id) ON DELETE CASCADE,

    -- 販管費の内訳
    personnel_cost DECIMAL(15, 2) DEFAULT 0,        -- 人件費
    land_rent DECIMAL(15, 2) DEFAULT 0,             -- 地代家賃
    lease_cost DECIMAL(15, 2) DEFAULT 0,            -- 賃借料
    utilities DECIMAL(15, 2) DEFAULT 0,             -- 水道光熱費
    -- その他は販管費合計との差額として計算（保存しない）

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_store_pl_sga_details_store_pl_id
    ON store_pl_sga_details(store_pl_id);

-- =============================================================================
-- RLS（Row Level Security）設定
-- =============================================================================

ALTER TABLE financial_cost_details ENABLE ROW LEVEL SECURITY;
ALTER TABLE financial_sga_details ENABLE ROW LEVEL SECURITY;
ALTER TABLE store_pl ENABLE ROW LEVEL SECURITY;
ALTER TABLE store_pl_sga_details ENABLE ROW LEVEL SECURITY;

-- 認証済みユーザー読み取りポリシー
CREATE POLICY "Allow authenticated users to view financial_cost_details"
    ON financial_cost_details FOR SELECT TO authenticated USING (true);

CREATE POLICY "Allow authenticated users to view financial_sga_details"
    ON financial_sga_details FOR SELECT TO authenticated USING (true);

CREATE POLICY "Allow authenticated users to view store_pl"
    ON store_pl FOR SELECT TO authenticated USING (true);

CREATE POLICY "Allow authenticated users to view store_pl_sga_details"
    ON store_pl_sga_details FOR SELECT TO authenticated USING (true);

-- service_role用フルアクセスポリシー
CREATE POLICY "Allow service role full access to financial_cost_details"
    ON financial_cost_details FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "Allow service role full access to financial_sga_details"
    ON financial_sga_details FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "Allow service role full access to store_pl"
    ON store_pl FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "Allow service role full access to store_pl_sga_details"
    ON store_pl_sga_details FOR ALL TO service_role USING (true) WITH CHECK (true);

-- =============================================================================
-- 更新日時自動更新トリガー
-- =============================================================================

DROP TRIGGER IF EXISTS update_financial_cost_details_updated_at ON financial_cost_details;
CREATE TRIGGER update_financial_cost_details_updated_at
    BEFORE UPDATE ON financial_cost_details
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_financial_sga_details_updated_at ON financial_sga_details;
CREATE TRIGGER update_financial_sga_details_updated_at
    BEFORE UPDATE ON financial_sga_details
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_store_pl_updated_at ON store_pl;
CREATE TRIGGER update_store_pl_updated_at
    BEFORE UPDATE ON store_pl
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_store_pl_sga_details_updated_at ON store_pl_sga_details;
CREATE TRIGGER update_store_pl_sga_details_updated_at
    BEFORE UPDATE ON store_pl_sga_details
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- =============================================================================
-- 店舗別収支ビュー（販管費明細を含む）
-- =============================================================================

CREATE OR REPLACE VIEW view_store_pl_with_details AS
SELECT
    sp.id,
    sp.segment_id,
    s.code as store_code,
    s.name as store_name,
    sp.period,
    sp.sales,
    sp.cost_of_sales,
    sp.gross_profit,
    sp.sga_total,
    sp.operating_profit,
    sp.is_target,
    -- 販管費明細
    COALESCE(sd.personnel_cost, 0) as sga_personnel_cost,
    COALESCE(sd.land_rent, 0) as sga_land_rent,
    COALESCE(sd.lease_cost, 0) as sga_lease_cost,
    COALESCE(sd.utilities, 0) as sga_utilities,
    -- その他（販管費合計 - 明細合計）
    sp.sga_total - COALESCE(sd.personnel_cost, 0)
                 - COALESCE(sd.land_rent, 0)
                 - COALESCE(sd.lease_cost, 0)
                 - COALESCE(sd.utilities, 0) as sga_others,
    sp.created_at,
    sp.updated_at
FROM store_pl sp
JOIN segments s ON sp.segment_id = s.id
LEFT JOIN store_pl_sga_details sd ON sp.id = sd.store_pl_id;
