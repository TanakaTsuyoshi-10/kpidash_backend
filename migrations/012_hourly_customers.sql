-- ============================================================================
-- 012: 時間帯別客数テーブル（hourly_customers）
-- 同一レシート番号=同一客として、(date, hour, segment_id) 単位でユニーク客数を保持
-- hourly_sales の receipt_count は商品ごとのレシート数であり、
-- 商品をまたいで SUM すると重複カウントされるため、客数は別テーブルで管理する
-- ============================================================================

CREATE TABLE IF NOT EXISTS hourly_customers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    date DATE NOT NULL,
    hour SMALLINT NOT NULL CHECK (hour >= 0 AND hour <= 23),
    segment_id UUID NOT NULL REFERENCES segments(id) ON DELETE CASCADE,
    customer_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(date, hour, segment_id)
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_hourly_customers_date_segment
    ON hourly_customers(date, segment_id);

CREATE INDEX IF NOT EXISTS idx_hourly_customers_date
    ON hourly_customers(date);

-- updated_at自動更新トリガー
CREATE OR REPLACE FUNCTION update_hourly_customers_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_hourly_customers_updated_at ON hourly_customers;
CREATE TRIGGER trigger_hourly_customers_updated_at
    BEFORE UPDATE ON hourly_customers
    FOR EACH ROW
    EXECUTE FUNCTION update_hourly_customers_updated_at();

-- RLS
ALTER TABLE hourly_customers ENABLE ROW LEVEL SECURITY;

CREATE POLICY "hourly_customers_select_authenticated"
    ON hourly_customers FOR SELECT
    TO authenticated
    USING (true);

CREATE POLICY "hourly_customers_all_service_role"
    ON hourly_customers FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);
