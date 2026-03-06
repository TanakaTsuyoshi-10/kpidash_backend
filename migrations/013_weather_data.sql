-- ============================================================================
-- 013: 天気データキャッシュテーブル（weather_data）
-- Open-Meteo APIから取得した天気データをキャッシュ保存
-- 地区ごとに日別の天気コード・最高/最低気温を保持
-- ============================================================================

CREATE TABLE IF NOT EXISTS weather_data (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    date DATE NOT NULL,
    region_id UUID NOT NULL REFERENCES regions(id) ON DELETE CASCADE,
    weather_code SMALLINT NOT NULL,        -- WMO天気コード
    temperature_max DECIMAL(4, 1),         -- 最高気温
    temperature_min DECIMAL(4, 1),         -- 最低気温
    source VARCHAR(20) NOT NULL DEFAULT 'archive', -- 'archive' or 'forecast'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(date, region_id)
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_weather_data_date_region
    ON weather_data(date, region_id);

CREATE INDEX IF NOT EXISTS idx_weather_data_date
    ON weather_data(date);

-- updated_at自動更新トリガー
DROP TRIGGER IF EXISTS trigger_weather_data_updated_at ON weather_data;
CREATE TRIGGER trigger_weather_data_updated_at
    BEFORE UPDATE ON weather_data
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- RLS
ALTER TABLE weather_data ENABLE ROW LEVEL SECURITY;

CREATE POLICY "weather_data_select_authenticated"
    ON weather_data FOR SELECT
    TO authenticated
    USING (true);

CREATE POLICY "weather_data_all_service_role"
    ON weather_data FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);
