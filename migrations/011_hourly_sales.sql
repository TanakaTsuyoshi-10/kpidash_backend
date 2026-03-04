-- ============================================================================
-- 011: 時間帯別売上テーブル（hourly_sales）
-- レシートジャーナルCSVから取り込んだ日付×時間帯×店舗×商品の売上データ
-- ============================================================================

-- テーブル作成
CREATE TABLE IF NOT EXISTS hourly_sales (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    date DATE NOT NULL,
    hour SMALLINT NOT NULL CHECK (hour >= 0 AND hour <= 23),
    segment_id UUID NOT NULL REFERENCES segments(id) ON DELETE CASCADE,
    product_name VARCHAR(100) NOT NULL,
    product_group VARCHAR(50) NOT NULL,
    sales DECIMAL(12, 2) NOT NULL DEFAULT 0,
    quantity INTEGER NOT NULL DEFAULT 0,
    receipt_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(date, hour, segment_id, product_name)
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_hourly_sales_date_segment
    ON hourly_sales(date, segment_id);

CREATE INDEX IF NOT EXISTS idx_hourly_sales_date
    ON hourly_sales(date);

CREATE INDEX IF NOT EXISTS idx_hourly_sales_date_hour_segment
    ON hourly_sales(date, hour, segment_id);

CREATE INDEX IF NOT EXISTS idx_hourly_sales_segment_date
    ON hourly_sales(segment_id, date);

-- updated_at自動更新トリガー
CREATE OR REPLACE FUNCTION update_hourly_sales_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_hourly_sales_updated_at ON hourly_sales;
CREATE TRIGGER trigger_hourly_sales_updated_at
    BEFORE UPDATE ON hourly_sales
    FOR EACH ROW
    EXECUTE FUNCTION update_hourly_sales_updated_at();

-- RLS（Row Level Security）
ALTER TABLE hourly_sales ENABLE ROW LEVEL SECURITY;

-- authenticated ユーザーはSELECTのみ
CREATE POLICY "hourly_sales_select_authenticated"
    ON hourly_sales FOR SELECT
    TO authenticated
    USING (true);

-- service_role は全操作可能
CREATE POLICY "hourly_sales_all_service_role"
    ON hourly_sales FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);
