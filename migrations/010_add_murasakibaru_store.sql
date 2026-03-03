-- =============================================================================
-- 紫原店（店舗コード29）の追加マイグレーション
-- =============================================================================

-- 1. segmentsテーブルに紫原店を追加
-- department_idは「store」部門のIDを動的に取得
INSERT INTO segments (code, name, department_id)
SELECT '29', '紫原店', d.id
FROM departments d
WHERE d.slug = 'store'
ON CONFLICT DO NOTHING;

-- 2. store_region_mappingに鹿児島地区としてマッピング
INSERT INTO store_region_mapping (segment_id, region_id)
SELECT s.id, r.id
FROM segments s
JOIN departments d ON s.department_id = d.id
JOIN regions r ON r.name = '鹿児島地区'
WHERE s.code = '29' AND d.slug = 'store'
ON CONFLICT (segment_id) DO NOTHING;
