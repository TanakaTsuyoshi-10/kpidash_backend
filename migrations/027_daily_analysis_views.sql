-- =============================================================================
-- 027_daily_analysis_views.sql
-- 日次分析の拡張用 集計ビュー
-- =============================================================================
-- 目的:
--   1. hourly_sales_agg / hourly_customers_agg
--      時間帯別ヒートマップの「月間合計」表示用。
--      生の hourly_sales は商品明細を含み月間4万行超になるため、
--      (date, segment_id, hour) 粒度に集約して転送量を1/8程度に抑える。
--   2. daily_gyoza_quantity
--      曜日別分析（平日/土日祝）のバット数計算用。
--      ぎょうざ系商品の日別×商品名の販売個数（全店舗合計）。
--      バット数 = Σ(個数×パック入数) ÷ 60 はアプリ側で計算する
--      （パック入数は商品名から抽出するため SQL では行わない）。
-- =============================================================================

CREATE OR REPLACE VIEW hourly_sales_agg AS
SELECT
    date,
    segment_id,
    hour,
    SUM(sales) AS sales
FROM hourly_sales
GROUP BY date, segment_id, hour;

CREATE OR REPLACE VIEW hourly_customers_agg AS
SELECT
    date,
    segment_id,
    hour,
    SUM(customer_count) AS customer_count
FROM hourly_customers
GROUP BY date, segment_id, hour;

CREATE OR REPLACE VIEW daily_gyoza_quantity AS
SELECT
    date,
    product_name,
    product_group,
    SUM(quantity) AS quantity
FROM hourly_sales
WHERE product_group IN ('ぎょうざ', 'しょうが入ぎょうざ')
GROUP BY date, product_name, product_group;
