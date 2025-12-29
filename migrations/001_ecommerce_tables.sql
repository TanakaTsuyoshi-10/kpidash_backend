-- =============================================================================
-- 通販分析テーブル作成マイグレーション
-- =============================================================================

-- チャネル別実績テーブル
CREATE TABLE IF NOT EXISTS ecommerce_channel_sales (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    month DATE NOT NULL,                    -- 対象月（YYYY-MM-01形式）
    channel VARCHAR(50) NOT NULL,           -- チャネル: 'EC', '電話', 'FAX', '店舗受付'
    sales DECIMAL(15, 2),                   -- 売上高
    buyers INTEGER,                         -- 購入者数
    -- unit_price は sales / buyers で計算
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(month, channel)
);

-- 商品別実績テーブル
CREATE TABLE IF NOT EXISTS ecommerce_product_sales (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    month DATE NOT NULL,
    product_name VARCHAR(255) NOT NULL,     -- 商品名
    product_category VARCHAR(100),          -- 商品カテゴリ（任意）
    sales DECIMAL(15, 2),                   -- 売上高
    quantity INTEGER,                       -- 販売数量（任意）
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(month, product_name)
);

-- 顧客別実績テーブル
CREATE TABLE IF NOT EXISTS ecommerce_customer_stats (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    month DATE NOT NULL,
    new_customers INTEGER,                  -- 新規顧客数
    repeat_customers INTEGER,               -- リピーター数
    total_customers INTEGER,                -- 合計（計算値でも可）
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(month)
);

-- HPアクセス数テーブル
CREATE TABLE IF NOT EXISTS ecommerce_website_stats (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    month DATE NOT NULL,
    page_views INTEGER,                     -- ページビュー数
    unique_visitors INTEGER,                -- ユニークビジター数
    sessions INTEGER,                       -- セッション数
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(month)
);

-- =============================================================================
-- インデックス作成
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_ecommerce_channel_sales_month
    ON ecommerce_channel_sales(month);
CREATE INDEX IF NOT EXISTS idx_ecommerce_channel_sales_channel
    ON ecommerce_channel_sales(channel);

CREATE INDEX IF NOT EXISTS idx_ecommerce_product_sales_month
    ON ecommerce_product_sales(month);
CREATE INDEX IF NOT EXISTS idx_ecommerce_product_sales_product_name
    ON ecommerce_product_sales(product_name);

CREATE INDEX IF NOT EXISTS idx_ecommerce_customer_stats_month
    ON ecommerce_customer_stats(month);

CREATE INDEX IF NOT EXISTS idx_ecommerce_website_stats_month
    ON ecommerce_website_stats(month);

-- =============================================================================
-- RLS（Row Level Security）設定
-- =============================================================================

-- RLSを有効化
ALTER TABLE ecommerce_channel_sales ENABLE ROW LEVEL SECURITY;
ALTER TABLE ecommerce_product_sales ENABLE ROW LEVEL SECURITY;
ALTER TABLE ecommerce_customer_stats ENABLE ROW LEVEL SECURITY;
ALTER TABLE ecommerce_website_stats ENABLE ROW LEVEL SECURITY;

-- 認証済みユーザーに全権限を付与
CREATE POLICY "Allow authenticated users full access to ecommerce_channel_sales"
    ON ecommerce_channel_sales
    FOR ALL
    TO authenticated
    USING (true)
    WITH CHECK (true);

CREATE POLICY "Allow authenticated users full access to ecommerce_product_sales"
    ON ecommerce_product_sales
    FOR ALL
    TO authenticated
    USING (true)
    WITH CHECK (true);

CREATE POLICY "Allow authenticated users full access to ecommerce_customer_stats"
    ON ecommerce_customer_stats
    FOR ALL
    TO authenticated
    USING (true)
    WITH CHECK (true);

CREATE POLICY "Allow authenticated users full access to ecommerce_website_stats"
    ON ecommerce_website_stats
    FOR ALL
    TO authenticated
    USING (true)
    WITH CHECK (true);

-- service_role用ポリシー
CREATE POLICY "Allow service role full access to ecommerce_channel_sales"
    ON ecommerce_channel_sales
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

CREATE POLICY "Allow service role full access to ecommerce_product_sales"
    ON ecommerce_product_sales
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

CREATE POLICY "Allow service role full access to ecommerce_customer_stats"
    ON ecommerce_customer_stats
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

CREATE POLICY "Allow service role full access to ecommerce_website_stats"
    ON ecommerce_website_stats
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- =============================================================================
-- 更新日時自動更新トリガー
-- =============================================================================

-- 更新日時自動更新関数（既存の場合はスキップ）
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- トリガー作成
DROP TRIGGER IF EXISTS update_ecommerce_channel_sales_updated_at ON ecommerce_channel_sales;
CREATE TRIGGER update_ecommerce_channel_sales_updated_at
    BEFORE UPDATE ON ecommerce_channel_sales
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_ecommerce_product_sales_updated_at ON ecommerce_product_sales;
CREATE TRIGGER update_ecommerce_product_sales_updated_at
    BEFORE UPDATE ON ecommerce_product_sales
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_ecommerce_customer_stats_updated_at ON ecommerce_customer_stats;
CREATE TRIGGER update_ecommerce_customer_stats_updated_at
    BEFORE UPDATE ON ecommerce_customer_stats
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_ecommerce_website_stats_updated_at ON ecommerce_website_stats;
CREATE TRIGGER update_ecommerce_website_stats_updated_at
    BEFORE UPDATE ON ecommerce_website_stats
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
