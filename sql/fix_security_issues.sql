-- =============================================================================
-- Supabaseセキュリティ問題の修正SQL
-- 実行前にバックアップを取ることを推奨
-- =============================================================================

-- =============================================================================
-- 1. view_user_list の修正（auth.users露出問題 + SECURITY DEFINER）
-- =============================================================================
-- auth.usersへの参照は維持するが、anonからのアクセスを拒否

DROP VIEW IF EXISTS public.view_user_list;

CREATE VIEW public.view_user_list
WITH (security_invoker = true) AS
SELECT
    up.id,
    up.email,
    up.display_name,
    up.role,
    ur.name AS role_name,
    up.is_active,
    up.created_at,
    up.updated_at,
    au.last_sign_in_at,
    au.created_at AS auth_created_at
FROM user_profiles up
JOIN user_roles ur ON up.role::text = ur.code::text
LEFT JOIN auth.users au ON up.id = au.id
ORDER BY up.created_at DESC;

-- anonからのアクセスを完全に拒否
REVOKE ALL ON public.view_user_list FROM anon;
REVOKE ALL ON public.view_user_list FROM public;
GRANT SELECT ON public.view_user_list TO authenticated;

COMMENT ON VIEW public.view_user_list IS 'ユーザー一覧ビュー（認証済みユーザーのみアクセス可能）';


-- =============================================================================
-- 2. view_manufacturing_monthly の修正（SECURITY DEFINER）
-- =============================================================================

DROP VIEW IF EXISTS public.view_manufacturing_monthly;

CREATE VIEW public.view_manufacturing_monthly
WITH (security_invoker = true) AS
SELECT
    date_trunc('month'::text, date::timestamp with time zone)::date AS month,
    sum(production_batts) AS total_batts,
    sum(production_pieces) AS total_pieces,
    sum(workers_count) AS total_workers,
    CASE
        WHEN sum(workers_count) > 0 THEN round(sum(production_batts)::numeric / sum(workers_count)::numeric, 2)
        ELSE 0::numeric
    END AS avg_production_per_worker,
    sum(paid_leave_hours) AS total_paid_leave_hours,
    count(DISTINCT date) AS working_days
FROM manufacturing_data
GROUP BY (date_trunc('month'::text, date::timestamp with time zone));

GRANT SELECT ON public.view_manufacturing_monthly TO authenticated;


-- =============================================================================
-- 3. view_complaints_monthly_summary の修正（SECURITY DEFINER）
-- =============================================================================

DROP VIEW IF EXISTS public.view_complaints_monthly_summary;

CREATE VIEW public.view_complaints_monthly_summary
WITH (security_invoker = true) AS
SELECT
    date_trunc('month'::text, incident_date::timestamp with time zone)::date AS month,
    count(*) AS total_count,
    count(*) FILTER (WHERE status::text = 'completed'::text) AS completed_count,
    count(*) FILTER (WHERE status::text = 'in_progress'::text) AS in_progress_count,
    count(*) FILTER (WHERE department_type::text = 'store'::text) AS store_count,
    count(*) FILTER (WHERE department_type::text = 'ecommerce'::text) AS ecommerce_count,
    count(*) FILTER (WHERE department_type::text = 'headquarters'::text) AS headquarters_count,
    count(*) FILTER (WHERE complaint_type::text = 'customer_service'::text) AS customer_service_count,
    count(*) FILTER (WHERE complaint_type::text = 'facility'::text) AS facility_count,
    count(*) FILTER (WHERE complaint_type::text = 'operation'::text) AS operation_count,
    count(*) FILTER (WHERE complaint_type::text = 'product'::text) AS product_count,
    count(*) FILTER (WHERE complaint_type::text = 'other'::text) AS other_count,
    COALESCE(sum(resolution_cost), 0::numeric) AS total_resolution_cost
FROM complaints
GROUP BY (date_trunc('month'::text, incident_date::timestamp with time zone));

GRANT SELECT ON public.view_complaints_monthly_summary TO authenticated;


-- =============================================================================
-- 4. view_store_pl_with_details の修正（SECURITY DEFINER）
-- =============================================================================

DROP VIEW IF EXISTS public.view_store_pl_with_details;

CREATE VIEW public.view_store_pl_with_details
WITH (security_invoker = true) AS
SELECT
    sp.id,
    sp.segment_id,
    s.code AS store_code,
    s.name AS store_name,
    sp.period,
    sp.sales,
    sp.cost_of_sales,
    sp.gross_profit,
    sp.sga_total,
    sp.operating_profit,
    sp.is_target,
    COALESCE(sd.personnel_cost, 0::numeric) AS sga_personnel_cost,
    COALESCE(sd.land_rent, 0::numeric) AS sga_land_rent,
    COALESCE(sd.lease_cost, 0::numeric) AS sga_lease_cost,
    COALESCE(sd.utilities, 0::numeric) AS sga_utilities,
    sp.sga_total - COALESCE(sd.personnel_cost, 0::numeric) - COALESCE(sd.land_rent, 0::numeric) - COALESCE(sd.lease_cost, 0::numeric) - COALESCE(sd.utilities, 0::numeric) AS sga_others,
    sp.created_at,
    sp.updated_at
FROM store_pl sp
JOIN segments s ON sp.segment_id = s.id
LEFT JOIN store_pl_sga_details sd ON sp.id = sd.store_pl_id;

GRANT SELECT ON public.view_store_pl_with_details TO authenticated;


-- =============================================================================
-- 5. view_kpi_cumulative の修正（SECURITY DEFINER）
-- =============================================================================

DROP VIEW IF EXISTS public.view_kpi_cumulative;

CREATE VIEW public.view_kpi_cumulative
WITH (security_invoker = true) AS
WITH base_data AS (
    SELECT
        v.id,
        v.segment_id,
        v.kpi_id,
        v.date,
        v.value,
        v.is_target,
        d.id AS department_id,
        d.name AS department_name,
        s.name AS segment_name,
        k.name AS kpi_name,
        k.category AS kpi_category,
        k.display_order,
        k.is_visible,
        CASE
            WHEN EXTRACT(month FROM v.date) >= 9::numeric THEN EXTRACT(year FROM v.date)
            ELSE EXTRACT(year FROM v.date) - 1::numeric
        END AS fiscal_year
    FROM kpi_values v
    JOIN segments s ON v.segment_id = s.id
    JOIN departments d ON s.department_id = d.id
    JOIN kpi_definitions k ON v.kpi_id = k.id
)
SELECT
    id,
    segment_id,
    kpi_id,
    date,
    value,
    is_target,
    department_id,
    department_name,
    segment_name,
    kpi_name,
    kpi_category,
    display_order,
    is_visible,
    fiscal_year,
    sum(value) OVER (PARTITION BY segment_id, kpi_id, is_target, fiscal_year ORDER BY date) AS cumulative_value
FROM base_data;

GRANT SELECT ON public.view_kpi_cumulative TO authenticated;


-- =============================================================================
-- 6. view_ecommerce_targets の修正（SECURITY DEFINER）
-- =============================================================================

DROP VIEW IF EXISTS public.view_ecommerce_targets;

CREATE VIEW public.view_ecommerce_targets
WITH (security_invoker = true) AS
SELECT
    ems.month AS period,
    ems.total_sales,
    ems.total_buyers,
    ecs.new_customers,
    ecs.repeat_customers,
    ecs.total_customers
FROM ecommerce_monthly_summary ems
LEFT JOIN ecommerce_customer_stats ecs ON ems.month = ecs.month AND ems.is_target = ecs.is_target
WHERE ems.is_target = true;

GRANT SELECT ON public.view_ecommerce_targets TO authenticated;


-- =============================================================================
-- 7. view_ecommerce_channel_targets の修正（SECURITY DEFINER）
-- =============================================================================

DROP VIEW IF EXISTS public.view_ecommerce_channel_targets;

CREATE VIEW public.view_ecommerce_channel_targets
WITH (security_invoker = true) AS
SELECT
    month AS period,
    channel,
    sales AS target_sales,
    buyers AS target_buyers
FROM ecommerce_channel_sales
WHERE is_target = true;

GRANT SELECT ON public.view_ecommerce_channel_targets TO authenticated;


-- =============================================================================
-- 8. view_financial_targets の修正（SECURITY DEFINER）
-- =============================================================================

DROP VIEW IF EXISTS public.view_financial_targets;

CREATE VIEW public.view_financial_targets
WITH (security_invoker = true) AS
SELECT
    fd.month AS period,
    fd.sales_total,
    fd.sales_store,
    fd.sales_online,
    fd.cost_of_sales,
    fd.gross_profit,
    fd.gross_profit_rate,
    fd.sg_and_a_total AS sga_total,
    fd.operating_profit,
    fd.operating_profit_rate,
    fcd.purchases AS cost_purchases,
    fcd.raw_material_purchases AS cost_raw_materials,
    fcd.labor_cost AS cost_labor,
    fcd.consumables AS cost_consumables,
    fcd.rent AS cost_rent,
    fcd.repairs AS cost_repairs,
    fcd.utilities AS cost_utilities,
    fsd.executive_compensation AS sga_executive,
    fsd.personnel_cost AS sga_personnel,
    fsd.delivery_cost AS sga_delivery,
    fsd.packaging_cost AS sga_packaging,
    fsd.payment_fees AS sga_payment_fees,
    fsd.freight_cost AS sga_freight,
    fsd.sales_commission AS sga_commission,
    fsd.advertising_cost AS sga_advertising
FROM financial_data fd
LEFT JOIN financial_cost_details fcd ON fd.month = fcd.period AND fd.is_target = fcd.is_target
LEFT JOIN financial_sga_details fsd ON fd.month = fsd.period AND fd.is_target = fsd.is_target
WHERE fd.is_target = true;

GRANT SELECT ON public.view_financial_targets TO authenticated;


-- =============================================================================
-- 9. RLS（Row Level Security）の有効化
-- =============================================================================

-- departments テーブル
ALTER TABLE public.departments ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "departments_select_policy" ON public.departments;
DROP POLICY IF EXISTS "departments_insert_policy" ON public.departments;
DROP POLICY IF EXISTS "departments_update_policy" ON public.departments;
DROP POLICY IF EXISTS "departments_delete_policy" ON public.departments;

CREATE POLICY "departments_select_policy" ON public.departments
    FOR SELECT TO authenticated
    USING (true);

CREATE POLICY "departments_modify_policy" ON public.departments
    FOR ALL TO authenticated
    USING (
        EXISTS (
            SELECT 1 FROM public.user_profiles
            WHERE id = auth.uid() AND role IN ('admin', 'super_admin')
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM public.user_profiles
            WHERE id = auth.uid() AND role IN ('admin', 'super_admin')
        )
    );


-- segments テーブル
ALTER TABLE public.segments ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "segments_select_policy" ON public.segments;
DROP POLICY IF EXISTS "segments_insert_policy" ON public.segments;
DROP POLICY IF EXISTS "segments_update_policy" ON public.segments;
DROP POLICY IF EXISTS "segments_delete_policy" ON public.segments;

CREATE POLICY "segments_select_policy" ON public.segments
    FOR SELECT TO authenticated
    USING (true);

CREATE POLICY "segments_modify_policy" ON public.segments
    FOR ALL TO authenticated
    USING (
        EXISTS (
            SELECT 1 FROM public.user_profiles
            WHERE id = auth.uid() AND role IN ('admin', 'super_admin')
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM public.user_profiles
            WHERE id = auth.uid() AND role IN ('admin', 'super_admin')
        )
    );


-- kpi_definitions テーブル
ALTER TABLE public.kpi_definitions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "kpi_definitions_select_policy" ON public.kpi_definitions;
DROP POLICY IF EXISTS "kpi_definitions_insert_policy" ON public.kpi_definitions;
DROP POLICY IF EXISTS "kpi_definitions_update_policy" ON public.kpi_definitions;
DROP POLICY IF EXISTS "kpi_definitions_delete_policy" ON public.kpi_definitions;

CREATE POLICY "kpi_definitions_select_policy" ON public.kpi_definitions
    FOR SELECT TO authenticated
    USING (true);

CREATE POLICY "kpi_definitions_modify_policy" ON public.kpi_definitions
    FOR ALL TO authenticated
    USING (
        EXISTS (
            SELECT 1 FROM public.user_profiles
            WHERE id = auth.uid() AND role IN ('admin', 'super_admin')
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM public.user_profiles
            WHERE id = auth.uid() AND role IN ('admin', 'super_admin')
        )
    );


-- product_mappings テーブル
ALTER TABLE public.product_mappings ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "product_mappings_select_policy" ON public.product_mappings;
DROP POLICY IF EXISTS "product_mappings_insert_policy" ON public.product_mappings;
DROP POLICY IF EXISTS "product_mappings_update_policy" ON public.product_mappings;
DROP POLICY IF EXISTS "product_mappings_delete_policy" ON public.product_mappings;

CREATE POLICY "product_mappings_select_policy" ON public.product_mappings
    FOR SELECT TO authenticated
    USING (true);

CREATE POLICY "product_mappings_modify_policy" ON public.product_mappings
    FOR ALL TO authenticated
    USING (
        EXISTS (
            SELECT 1 FROM public.user_profiles
            WHERE id = auth.uid() AND role IN ('admin', 'super_admin')
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM public.user_profiles
            WHERE id = auth.uid() AND role IN ('admin', 'super_admin')
        )
    );


-- kpi_values テーブル
ALTER TABLE public.kpi_values ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "kpi_values_select_policy" ON public.kpi_values;
DROP POLICY IF EXISTS "kpi_values_insert_policy" ON public.kpi_values;
DROP POLICY IF EXISTS "kpi_values_update_policy" ON public.kpi_values;
DROP POLICY IF EXISTS "kpi_values_delete_policy" ON public.kpi_values;

CREATE POLICY "kpi_values_select_policy" ON public.kpi_values
    FOR SELECT TO authenticated
    USING (true);

CREATE POLICY "kpi_values_modify_policy" ON public.kpi_values
    FOR ALL TO authenticated
    USING (
        EXISTS (
            SELECT 1 FROM public.user_profiles
            WHERE id = auth.uid() AND role IN ('admin', 'super_admin', 'editor')
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM public.user_profiles
            WHERE id = auth.uid() AND role IN ('admin', 'super_admin', 'editor')
        )
    );


-- =============================================================================
-- 完了
-- =============================================================================
-- 実行後、Supabaseのセキュリティリンターを再実行して
-- エラーが解消されたことを確認してください。
