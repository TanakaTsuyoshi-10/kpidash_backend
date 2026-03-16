-- =============================================
-- 016: 通販分析アップグレード
-- - ecommerce_product_sales に channel カラム追加
-- - ecommerce_customer_detail_stats テーブル新規作成
-- =============================================

-- A. ecommerce_product_sales に channel カラム追加
ALTER TABLE ecommerce_product_sales ADD COLUMN IF NOT EXISTS channel VARCHAR(20);

-- 既存のユニーク制約を削除して新しい制約を追加
-- （既存データは channel = NULL で全チャネル合算として扱う）
ALTER TABLE ecommerce_product_sales
    DROP CONSTRAINT IF EXISTS ecommerce_product_sales_month_product_name_key;

ALTER TABLE ecommerce_product_sales
    ADD CONSTRAINT ecommerce_product_sales_month_product_name_channel_key
    UNIQUE (month, product_name, channel);

-- channel カラムにインデックス追加
CREATE INDEX IF NOT EXISTS idx_ecommerce_product_sales_channel
    ON ecommerce_product_sales (channel);

-- B. 顧客別詳細テーブル新規作成
CREATE TABLE IF NOT EXISTS ecommerce_customer_detail_stats (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    month DATE NOT NULL,
    customer_type VARCHAR(20) NOT NULL,  -- 'new' or 'repeat'
    sales DECIMAL(12, 2),
    quantity INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(month, customer_type)
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_ecommerce_customer_detail_month
    ON ecommerce_customer_detail_stats (month);

CREATE INDEX IF NOT EXISTS idx_ecommerce_customer_detail_type
    ON ecommerce_customer_detail_stats (customer_type);

-- RLS有効化
ALTER TABLE ecommerce_customer_detail_stats ENABLE ROW LEVEL SECURITY;

-- RLSポリシー
CREATE POLICY "ecommerce_customer_detail_stats_select_policy"
    ON ecommerce_customer_detail_stats FOR SELECT
    TO authenticated
    USING (true);

CREATE POLICY "ecommerce_customer_detail_stats_insert_policy"
    ON ecommerce_customer_detail_stats FOR INSERT
    TO authenticated
    WITH CHECK (true);

CREATE POLICY "ecommerce_customer_detail_stats_update_policy"
    ON ecommerce_customer_detail_stats FOR UPDATE
    TO authenticated
    USING (true);

CREATE POLICY "ecommerce_customer_detail_stats_delete_policy"
    ON ecommerce_customer_detail_stats FOR DELETE
    TO authenticated
    USING (true);

-- service_role用ポリシー
CREATE POLICY "ecommerce_customer_detail_stats_service_all"
    ON ecommerce_customer_detail_stats FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- updated_at 自動更新トリガー
CREATE TRIGGER update_ecommerce_customer_detail_stats_updated_at
    BEFORE UPDATE ON ecommerce_customer_detail_stats
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
