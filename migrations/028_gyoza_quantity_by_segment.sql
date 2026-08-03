-- =============================================================================
-- 028_gyoza_quantity_by_segment.sql
-- daily_gyoza_quantity ビューに segment_id を追加
-- =============================================================================
-- 目的:
--   店舗詳細ページの曜日別分析（平日/土日祝）で店舗単体のバット数を
--   計算できるようにする。列構成が変わるため DROP して作り直す。
--   既存の全店集計はアプリ側で全店舗の segment_id を渡して合算する。
-- =============================================================================

DROP VIEW IF EXISTS daily_gyoza_quantity;

CREATE VIEW daily_gyoza_quantity AS
SELECT
    date,
    segment_id,
    product_name,
    product_group,
    SUM(quantity) AS quantity
FROM hourly_sales
WHERE product_group IN ('ぎょうざ', 'しょうが入ぎょうざ')
GROUP BY date, segment_id, product_name, product_group;
