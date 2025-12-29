-- =============================================================================
-- 目標設定機能拡張マイグレーション
--
-- 対象:
-- 1. 通販部門: チャネル別売上目標、顧客統計目標
-- 2. 財務部門: 既存テーブルにis_targetがあるため、INSERT/UPDATE用のポリシー追加のみ
-- 3. 店舗部門: kpi_valuesで既にis_target対応済み
-- =============================================================================

-- =============================================================================
-- 1. 通販チャネル別売上テーブルにis_target追加
-- =============================================================================

-- is_targetカラムを追加（存在しない場合のみ）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'ecommerce_channel_sales' AND column_name = 'is_target'
    ) THEN
        ALTER TABLE ecommerce_channel_sales ADD COLUMN is_target BOOLEAN DEFAULT false;
    END IF;
END $$;

-- ユニーク制約を更新（month, channel, is_target）
-- まず既存の制約を削除
ALTER TABLE ecommerce_channel_sales DROP CONSTRAINT IF EXISTS ecommerce_channel_sales_month_channel_key;

-- 新しいユニーク制約を追加
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'ecommerce_channel_sales_month_channel_is_target_key'
        AND table_name = 'ecommerce_channel_sales'
    ) THEN
        ALTER TABLE ecommerce_channel_sales
        ADD CONSTRAINT ecommerce_channel_sales_month_channel_is_target_key
        UNIQUE (month, channel, is_target);
    END IF;
END $$;

-- インデックス追加
CREATE INDEX IF NOT EXISTS idx_ecommerce_channel_sales_is_target
    ON ecommerce_channel_sales(is_target);

-- =============================================================================
-- 2. 通販顧客統計テーブルにis_target追加
-- =============================================================================

-- is_targetカラムを追加（存在しない場合のみ）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'ecommerce_customer_stats' AND column_name = 'is_target'
    ) THEN
        ALTER TABLE ecommerce_customer_stats ADD COLUMN is_target BOOLEAN DEFAULT false;
    END IF;
END $$;

-- ユニーク制約を更新（month, is_target）
ALTER TABLE ecommerce_customer_stats DROP CONSTRAINT IF EXISTS ecommerce_customer_stats_month_key;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'ecommerce_customer_stats_month_is_target_key'
        AND table_name = 'ecommerce_customer_stats'
    ) THEN
        ALTER TABLE ecommerce_customer_stats
        ADD CONSTRAINT ecommerce_customer_stats_month_is_target_key
        UNIQUE (month, is_target);
    END IF;
END $$;

-- インデックス追加
CREATE INDEX IF NOT EXISTS idx_ecommerce_customer_stats_is_target
    ON ecommerce_customer_stats(is_target);

-- =============================================================================
-- 3. 財務系テーブルに認証ユーザーの書き込みポリシー追加
-- =============================================================================

-- financial_cost_details
DROP POLICY IF EXISTS "Allow authenticated users to insert financial_cost_details" ON financial_cost_details;
CREATE POLICY "Allow authenticated users to insert financial_cost_details"
    ON financial_cost_details FOR INSERT TO authenticated WITH CHECK (true);

DROP POLICY IF EXISTS "Allow authenticated users to update financial_cost_details" ON financial_cost_details;
CREATE POLICY "Allow authenticated users to update financial_cost_details"
    ON financial_cost_details FOR UPDATE TO authenticated USING (true) WITH CHECK (true);

-- financial_sga_details
DROP POLICY IF EXISTS "Allow authenticated users to insert financial_sga_details" ON financial_sga_details;
CREATE POLICY "Allow authenticated users to insert financial_sga_details"
    ON financial_sga_details FOR INSERT TO authenticated WITH CHECK (true);

DROP POLICY IF EXISTS "Allow authenticated users to update financial_sga_details" ON financial_sga_details;
CREATE POLICY "Allow authenticated users to update financial_sga_details"
    ON financial_sga_details FOR UPDATE TO authenticated USING (true) WITH CHECK (true);

-- =============================================================================
-- 4. 通販売上サマリーテーブル（月別合計）
-- =============================================================================

CREATE TABLE IF NOT EXISTS ecommerce_monthly_summary (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    month DATE NOT NULL,                            -- 対象月（YYYY-MM-01形式）

    -- 売上サマリー
    total_sales DECIMAL(15, 2) DEFAULT 0,           -- 売上合計
    total_buyers INTEGER DEFAULT 0,                 -- 購入者数合計

    is_target BOOLEAN DEFAULT false,                -- 目標/実績フラグ
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    UNIQUE(month, is_target)
);

CREATE INDEX IF NOT EXISTS idx_ecommerce_monthly_summary_month
    ON ecommerce_monthly_summary(month);

-- RLS設定
ALTER TABLE ecommerce_monthly_summary ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Allow authenticated users full access to ecommerce_monthly_summary" ON ecommerce_monthly_summary;
CREATE POLICY "Allow authenticated users full access to ecommerce_monthly_summary"
    ON ecommerce_monthly_summary
    FOR ALL
    TO authenticated
    USING (true)
    WITH CHECK (true);

DROP POLICY IF EXISTS "Allow service role full access to ecommerce_monthly_summary" ON ecommerce_monthly_summary;
CREATE POLICY "Allow service role full access to ecommerce_monthly_summary"
    ON ecommerce_monthly_summary
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- 更新日時トリガー
DROP TRIGGER IF EXISTS update_ecommerce_monthly_summary_updated_at ON ecommerce_monthly_summary;
CREATE TRIGGER update_ecommerce_monthly_summary_updated_at
    BEFORE UPDATE ON ecommerce_monthly_summary
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- =============================================================================
-- 5. 目標設定履歴テーブル（監査用）
-- =============================================================================

CREATE TABLE IF NOT EXISTS target_setting_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- 対象情報
    department_type VARCHAR(20) NOT NULL,           -- 'store', 'ecommerce', 'financial'
    target_table VARCHAR(100) NOT NULL,             -- 対象テーブル名
    target_id UUID,                                 -- 対象レコードID
    period DATE NOT NULL,                           -- 対象月

    -- 変更情報
    field_name VARCHAR(100) NOT NULL,               -- 変更フィールド名
    old_value DECIMAL(15, 2),                       -- 変更前の値
    new_value DECIMAL(15, 2),                       -- 変更後の値

    -- メタデータ
    changed_by UUID,                                -- 変更者ID
    changed_by_email VARCHAR(255),                  -- 変更者メールアドレス
    changed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_target_setting_history_department_type
    ON target_setting_history(department_type);
CREATE INDEX IF NOT EXISTS idx_target_setting_history_period
    ON target_setting_history(period);
CREATE INDEX IF NOT EXISTS idx_target_setting_history_changed_at
    ON target_setting_history(changed_at);

-- RLS設定
ALTER TABLE target_setting_history ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Allow authenticated users to view target_setting_history" ON target_setting_history;
CREATE POLICY "Allow authenticated users to view target_setting_history"
    ON target_setting_history FOR SELECT TO authenticated USING (true);

DROP POLICY IF EXISTS "Allow authenticated users to insert target_setting_history" ON target_setting_history;
CREATE POLICY "Allow authenticated users to insert target_setting_history"
    ON target_setting_history FOR INSERT TO authenticated WITH CHECK (true);

DROP POLICY IF EXISTS "Allow service role full access to target_setting_history" ON target_setting_history;
CREATE POLICY "Allow service role full access to target_setting_history"
    ON target_setting_history FOR ALL TO service_role USING (true) WITH CHECK (true);

-- =============================================================================
-- 6. 財務目標サマリービュー（財務分析画面用）
-- =============================================================================

CREATE OR REPLACE VIEW view_financial_targets AS
SELECT
    fd.month as period,
    -- 売上・利益
    fd.sales_total,
    fd.sales_store,
    fd.sales_online,
    fd.cost_of_sales,
    fd.gross_profit,
    fd.gross_profit_rate,
    fd.sg_and_a_total as sga_total,
    fd.operating_profit,
    fd.operating_profit_rate,
    -- 売上原価明細
    fcd.purchases as cost_purchases,
    fcd.raw_material_purchases as cost_raw_materials,
    fcd.labor_cost as cost_labor,
    fcd.consumables as cost_consumables,
    fcd.rent as cost_rent,
    fcd.repairs as cost_repairs,
    fcd.utilities as cost_utilities,
    -- 販管費明細
    fsd.executive_compensation as sga_executive,
    fsd.personnel_cost as sga_personnel,
    fsd.delivery_cost as sga_delivery,
    fsd.packaging_cost as sga_packaging,
    fsd.payment_fees as sga_payment_fees,
    fsd.freight_cost as sga_freight,
    fsd.sales_commission as sga_commission,
    fsd.advertising_cost as sga_advertising
FROM financial_data fd
LEFT JOIN financial_cost_details fcd ON fd.month = fcd.period AND fd.is_target = fcd.is_target
LEFT JOIN financial_sga_details fsd ON fd.month = fsd.period AND fd.is_target = fsd.is_target
WHERE fd.is_target = true;

-- =============================================================================
-- 7. 通販目標サマリービュー（通販分析画面用）
-- =============================================================================

CREATE OR REPLACE VIEW view_ecommerce_targets AS
SELECT
    ems.month as period,
    ems.total_sales,
    ems.total_buyers,
    -- 顧客統計
    ecs.new_customers,
    ecs.repeat_customers,
    ecs.total_customers
FROM ecommerce_monthly_summary ems
LEFT JOIN ecommerce_customer_stats ecs ON ems.month = ecs.month AND ems.is_target = ecs.is_target
WHERE ems.is_target = true;

-- =============================================================================
-- 8. チャネル別目標ビュー
-- =============================================================================

CREATE OR REPLACE VIEW view_ecommerce_channel_targets AS
SELECT
    month as period,
    channel,
    sales as target_sales,
    buyers as target_buyers
FROM ecommerce_channel_sales
WHERE is_target = true;
