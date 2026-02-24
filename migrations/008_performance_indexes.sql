-- パフォーマンス改善用複合インデックス
-- 常に組み合わせてフィルタされるカラムに対して複合インデックスを追加

-- store_pl: segment_id + period + is_target は常に組み合わせて使用
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_store_pl_segment_period_target
    ON store_pl(segment_id, period, is_target);

-- financial_data: month + is_target は常に組み合わせて使用
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_financial_data_month_target
    ON financial_data(month, is_target);

-- ecommerce_channel_sales: month + is_target は常に組み合わせて使用
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ecommerce_channel_month_target
    ON ecommerce_channel_sales(month, is_target);

-- financial_cost_details: period + is_target は常に組み合わせて使用
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_financial_cost_period_target
    ON financial_cost_details(period, is_target);

-- financial_sga_details: period + is_target は常に組み合わせて使用
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_financial_sga_period_target
    ON financial_sga_details(period, is_target);
