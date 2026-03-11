-- =============================================================================
-- クレーム管理システム改修マイグレーション
--
-- 変更点:
-- 1. クレーム種類を5種類→11種類に更新
-- 2. complaints テーブルに store_name, slip_number, handling_notes カラム追加
-- 3. 月別集計ビューを新種類に対応して再作成
-- =============================================================================

-- =============================================================================
-- 1. complaint_types マスタ更新（旧データ削除→新データ投入）
-- =============================================================================

DELETE FROM complaint_types;

INSERT INTO complaint_types (code, name, display_order) VALUES
    ('store_service', '店舗接客', 1),
    ('packing_error', '梱包ミス', 2),
    ('price_discrepancy', '金額相違', 3),
    ('phone_support', '電話対応', 4),
    ('date_error', '日時違い', 5),
    ('address_error', '住所違い', 6),
    ('quantity_error', '注文数違い', 7),
    ('delay', '遅延', 8),
    ('contamination', '異物混入', 9),
    ('taste', '味のクレーム', 10),
    ('other', 'その他', 99)
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    display_order = EXCLUDED.display_order;

-- =============================================================================
-- 2. complaints テーブルにカラム追加
-- =============================================================================

-- 店舗名（店舗の場合、任意）
ALTER TABLE complaints ADD COLUMN IF NOT EXISTS store_name VARCHAR(100);

-- 伝票番号（通販の場合、任意）
ALTER TABLE complaints ADD COLUMN IF NOT EXISTS slip_number VARCHAR(100);

-- 対応中メモ（対応中の状況記録）
ALTER TABLE complaints ADD COLUMN IF NOT EXISTS handling_notes TEXT;

-- =============================================================================
-- 3. 月別集計ビュー更新（新クレーム種類対応）
-- =============================================================================

DROP VIEW IF EXISTS view_complaints_monthly_summary;
CREATE VIEW view_complaints_monthly_summary AS
SELECT
    DATE_TRUNC('month', incident_date)::DATE as month,
    COUNT(*) as total_count,
    COUNT(*) FILTER (WHERE status = 'completed') as completed_count,
    COUNT(*) FILTER (WHERE status = 'in_progress') as in_progress_count,
    -- 部署別
    COUNT(*) FILTER (WHERE department_type = 'store') as store_count,
    COUNT(*) FILTER (WHERE department_type = 'ecommerce') as ecommerce_count,
    COUNT(*) FILTER (WHERE department_type = 'headquarters') as headquarters_count,
    -- 種類別（新11種類）
    COUNT(*) FILTER (WHERE complaint_type = 'store_service') as store_service_count,
    COUNT(*) FILTER (WHERE complaint_type = 'packing_error') as packing_error_count,
    COUNT(*) FILTER (WHERE complaint_type = 'price_discrepancy') as price_discrepancy_count,
    COUNT(*) FILTER (WHERE complaint_type = 'phone_support') as phone_support_count,
    COUNT(*) FILTER (WHERE complaint_type = 'date_error') as date_error_count,
    COUNT(*) FILTER (WHERE complaint_type = 'address_error') as address_error_count,
    COUNT(*) FILTER (WHERE complaint_type = 'quantity_error') as quantity_error_count,
    COUNT(*) FILTER (WHERE complaint_type = 'delay') as delay_count,
    COUNT(*) FILTER (WHERE complaint_type = 'contamination') as contamination_count,
    COUNT(*) FILTER (WHERE complaint_type = 'taste') as taste_count,
    COUNT(*) FILTER (WHERE complaint_type = 'other') as other_count,
    -- コスト
    COALESCE(SUM(resolution_cost), 0) as total_resolution_cost
FROM complaints
GROUP BY DATE_TRUNC('month', incident_date);
