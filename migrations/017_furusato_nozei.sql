-- =============================================
-- 017: ふるさと納税管理テーブル
-- - furusato_nozei_stats テーブル新規作成
-- - RLSポリシー設定
-- - updated_at トリガー
-- =============================================

-- A. ふるさと納税統計テーブル
CREATE TABLE IF NOT EXISTS furusato_nozei_stats (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    month DATE NOT NULL UNIQUE,
    -- 販売実績
    inventory INTEGER,              -- 在庫数
    orders INTEGER,                 -- 単月注文数
    sales DECIMAL(12, 2),           -- 単月売上高
    unit_price DECIMAL(10, 2),      -- 単価
    orders_kyushu INTEGER,          -- エリア: 九州
    orders_chugoku_shikoku INTEGER, -- エリア: 中国・四国
    orders_kansai INTEGER,          -- エリア: 関西
    orders_kanto INTEGER,           -- エリア: 関東
    orders_other INTEGER,           -- エリア: その他
    -- リピート情報
    new_customers INTEGER,          -- 当月新規注文者数
    ec_site_buyers INTEGER,         -- ECサイトでの購入経験者
    repeat_buyers INTEGER,          -- ふるさと納税複数回購入経験者
    repeat_single_month INTEGER,    -- 単月で複数回注文
    repeat_multi_month INTEGER,     -- 複数月で注文経験有
    -- 返品・苦情
    reshipping_count INTEGER,       -- 再送数
    complaint_count INTEGER,        -- 苦情数
    -- 口コミ
    positive_reviews INTEGER,       -- ポジティブ情報
    negative_reviews INTEGER,       -- ネガティブ情報
    -- コメント
    comment_sales TEXT,
    comment_repeat TEXT,
    comment_complaint TEXT,
    comment_review TEXT,
    -- タイムスタンプ
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_furusato_nozei_stats_month
    ON furusato_nozei_stats (month);

-- B. RLSポリシー
ALTER TABLE furusato_nozei_stats ENABLE ROW LEVEL SECURITY;

CREATE POLICY "furusato_nozei_stats_select"
    ON furusato_nozei_stats FOR SELECT
    TO authenticated
    USING (true);

CREATE POLICY "furusato_nozei_stats_insert"
    ON furusato_nozei_stats FOR INSERT
    TO authenticated
    WITH CHECK (true);

CREATE POLICY "furusato_nozei_stats_update"
    ON furusato_nozei_stats FOR UPDATE
    TO authenticated
    USING (true)
    WITH CHECK (true);

-- C. updated_at トリガー
CREATE OR REPLACE FUNCTION update_furusato_nozei_stats_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_furusato_nozei_stats_updated_at
    BEFORE UPDATE ON furusato_nozei_stats
    FOR EACH ROW
    EXECUTE FUNCTION update_furusato_nozei_stats_updated_at();
