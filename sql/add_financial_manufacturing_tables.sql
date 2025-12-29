-- ==========================================
-- 財務・製造データテーブル追加
-- KPI管理システム ダッシュボード再構築用
-- ==========================================

-- ==========================================
-- 財務データテーブル
-- ==========================================

CREATE TABLE IF NOT EXISTS financial_data (
    id BIGSERIAL PRIMARY KEY,
    fiscal_year INTEGER NOT NULL,
    month DATE NOT NULL,

    -- 売上高
    sales_total NUMERIC,
    sales_store NUMERIC,
    sales_online NUMERIC,

    -- 原価・利益
    cost_of_sales NUMERIC,
    gross_profit NUMERIC,
    gross_profit_rate NUMERIC,

    -- 販管費
    sg_and_a_total NUMERIC,
    labor_cost NUMERIC,
    labor_cost_rate NUMERIC,
    other_expenses NUMERIC,

    -- 営業利益
    operating_profit NUMERIC,
    operating_profit_rate NUMERIC,

    -- キャッシュフロー
    cf_operating NUMERIC,
    cf_investing NUMERIC,
    cf_financing NUMERIC,
    cf_free NUMERIC,

    -- 目標値
    target_sales_total NUMERIC,
    target_gross_profit NUMERIC,
    target_operating_profit NUMERIC,

    -- メタデータ
    is_target BOOLEAN DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    UNIQUE(month, is_target)
);

CREATE INDEX IF NOT EXISTS idx_financial_data_month ON financial_data(month);
CREATE INDEX IF NOT EXISTS idx_financial_data_fiscal_year ON financial_data(fiscal_year);

-- ==========================================
-- 製造データテーブル
-- ==========================================

CREATE TABLE IF NOT EXISTS manufacturing_data (
    id BIGSERIAL PRIMARY KEY,
    date DATE NOT NULL,

    -- 製造実績
    production_batts INTEGER,
    production_pieces INTEGER,

    -- 人員
    workers_count INTEGER,
    production_per_worker NUMERIC,

    -- 有給休暇
    paid_leave_hours NUMERIC,

    -- メタデータ
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    UNIQUE(date)
);

CREATE INDEX IF NOT EXISTS idx_manufacturing_data_date ON manufacturing_data(date);

-- 月次集計用ビュー
CREATE OR REPLACE VIEW view_manufacturing_monthly AS
SELECT
    DATE_TRUNC('month', date)::DATE as month,
    SUM(production_batts) as total_batts,
    SUM(production_pieces) as total_pieces,
    SUM(workers_count) as total_workers,
    CASE
        WHEN SUM(workers_count) > 0
        THEN ROUND(SUM(production_batts)::NUMERIC / SUM(workers_count), 2)
        ELSE 0
    END as avg_production_per_worker,
    SUM(paid_leave_hours) as total_paid_leave_hours,
    COUNT(DISTINCT date) as working_days
FROM manufacturing_data
GROUP BY DATE_TRUNC('month', date);

-- ==========================================
-- RLS設定
-- ==========================================

ALTER TABLE financial_data ENABLE ROW LEVEL SECURITY;
ALTER TABLE manufacturing_data ENABLE ROW LEVEL SECURITY;

-- 既存ポリシーを削除（エラー回避）
DROP POLICY IF EXISTS "Allow authenticated read financial_data" ON financial_data;
DROP POLICY IF EXISTS "Allow authenticated read manufacturing_data" ON manufacturing_data;
DROP POLICY IF EXISTS "Allow service_role write financial_data" ON financial_data;
DROP POLICY IF EXISTS "Allow service_role write manufacturing_data" ON manufacturing_data;

-- 読み取りポリシー
CREATE POLICY "Allow authenticated read financial_data" ON financial_data
    FOR SELECT TO authenticated USING (true);

CREATE POLICY "Allow authenticated read manufacturing_data" ON manufacturing_data
    FOR SELECT TO authenticated USING (true);

-- 書き込みポリシー（service_role用）
CREATE POLICY "Allow service_role write financial_data" ON financial_data
    FOR ALL USING (true);

CREATE POLICY "Allow service_role write manufacturing_data" ON manufacturing_data
    FOR ALL USING (true);

-- ==========================================
-- 更新トリガー
-- ==========================================

-- updated_at 自動更新トリガー関数（既に存在する場合はスキップ）
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- financial_data用トリガー
DROP TRIGGER IF EXISTS update_financial_data_updated_at ON financial_data;
CREATE TRIGGER update_financial_data_updated_at
    BEFORE UPDATE ON financial_data
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- manufacturing_data用トリガー
DROP TRIGGER IF EXISTS update_manufacturing_data_updated_at ON manufacturing_data;
CREATE TRIGGER update_manufacturing_data_updated_at
    BEFORE UPDATE ON manufacturing_data
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
