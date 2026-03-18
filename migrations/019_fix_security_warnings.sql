-- =============================================================================
-- セキュリティ修正マイグレーション
--
-- 対処するSupabase Linter警告:
-- 1. function_search_path_mutable: 6関数にSET search_path = ''を追加
-- 2. rls_policy_always_true: データテーブルの書込みをadmin/editorに限定
--
-- 注: auth_leaked_password_protectionはSupabase Dashboardで有効化が必要
--     Authentication > Attack Protection > Enable Leaked Password Protection
-- =============================================================================


-- =============================================================================
-- 1. 関数のsearch_path修正
-- =============================================================================

-- 1-1. update_updated_at_column
CREATE OR REPLACE FUNCTION public.update_updated_at_column()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $function$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$function$;

-- 1-2. set_complaint_completed_at
CREATE OR REPLACE FUNCTION public.set_complaint_completed_at()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $function$
BEGIN
    IF NEW.status = 'completed' AND OLD.status != 'completed' THEN
        NEW.completed_at = NOW();
    END IF;
    IF NEW.status = 'in_progress' AND OLD.status = 'completed' THEN
        NEW.completed_at = NULL;
    END IF;
    RETURN NEW;
END;
$function$;

-- 1-3. update_hourly_sales_updated_at
CREATE OR REPLACE FUNCTION public.update_hourly_sales_updated_at()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $function$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$function$;

-- 1-4. update_furusato_nozei_stats_updated_at
CREATE OR REPLACE FUNCTION public.update_furusato_nozei_stats_updated_at()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $function$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$function$;

-- 1-5. handle_new_user (SECURITY DEFINERを維持 — auth triggerに必要)
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $function$
BEGIN
    INSERT INTO public.user_profiles (id, email, display_name, role)
    VALUES (
        NEW.id,
        NEW.email,
        COALESCE(NEW.raw_user_meta_data->>'display_name', split_part(NEW.email, '@', 1)),
        COALESCE(NEW.raw_user_meta_data->>'role', 'user')
    )
    ON CONFLICT (id) DO UPDATE SET
        email = EXCLUDED.email,
        updated_at = NOW();
    RETURN NEW;
END;
$function$;

-- 1-6. update_product_sales_updated_at
CREATE OR REPLACE FUNCTION public.update_product_sales_updated_at()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $function$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$function$;


-- =============================================================================
-- 2. RLSポリシー修正 — データテーブルの書込みをadmin/editorに限定
--    (バックエンドはservice_roleでRLSバイパスするため影響なし)
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 2-1. complaints: DELETE のみ admin に限定、INSERT/UPDATEはユーザー確認付き
-- -----------------------------------------------------------------------------
DROP POLICY IF EXISTS "Allow authenticated users to delete complaints" ON public.complaints;
CREATE POLICY "Allow admin to delete complaints" ON public.complaints
    FOR DELETE TO authenticated
    USING (
        EXISTS (
            SELECT 1 FROM public.user_profiles
            WHERE id = auth.uid() AND role IN ('admin', 'super_admin')
        )
    );

DROP POLICY IF EXISTS "Allow authenticated users to insert complaints" ON public.complaints;
CREATE POLICY "Allow authenticated users to insert complaints" ON public.complaints
    FOR INSERT TO authenticated
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM public.user_profiles
            WHERE id = auth.uid() AND role IN ('admin', 'super_admin', 'editor', 'user')
        )
    );

DROP POLICY IF EXISTS "Allow authenticated users to update complaints" ON public.complaints;
CREATE POLICY "Allow authenticated users to update complaints" ON public.complaints
    FOR UPDATE TO authenticated
    USING (
        EXISTS (
            SELECT 1 FROM public.user_profiles
            WHERE id = auth.uid() AND role IN ('admin', 'super_admin', 'editor', 'user')
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM public.user_profiles
            WHERE id = auth.uid() AND role IN ('admin', 'super_admin', 'editor', 'user')
        )
    );

-- -----------------------------------------------------------------------------
-- 2-2. ecommerce_customer_detail_stats: 書込みをadmin/editorに限定
-- -----------------------------------------------------------------------------
DROP POLICY IF EXISTS "ecommerce_customer_detail_stats_insert_policy" ON public.ecommerce_customer_detail_stats;
CREATE POLICY "ecommerce_customer_detail_stats_insert_policy" ON public.ecommerce_customer_detail_stats
    FOR INSERT TO authenticated
    WITH CHECK (
        EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role IN ('admin', 'super_admin', 'editor'))
    );

DROP POLICY IF EXISTS "ecommerce_customer_detail_stats_update_policy" ON public.ecommerce_customer_detail_stats;
CREATE POLICY "ecommerce_customer_detail_stats_update_policy" ON public.ecommerce_customer_detail_stats
    FOR UPDATE TO authenticated
    USING (EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role IN ('admin', 'super_admin', 'editor')))
    WITH CHECK (EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role IN ('admin', 'super_admin', 'editor')));

DROP POLICY IF EXISTS "ecommerce_customer_detail_stats_delete_policy" ON public.ecommerce_customer_detail_stats;
CREATE POLICY "ecommerce_customer_detail_stats_delete_policy" ON public.ecommerce_customer_detail_stats
    FOR DELETE TO authenticated
    USING (EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role IN ('admin', 'super_admin')));

-- -----------------------------------------------------------------------------
-- 2-3. ecommerce_monthly_summary: 書込みをadmin/editorに限定
-- -----------------------------------------------------------------------------
DROP POLICY IF EXISTS "Allow authenticated users full access to ecommerce_monthly_summ" ON public.ecommerce_monthly_summary;
CREATE POLICY "ecommerce_monthly_summary_select_policy" ON public.ecommerce_monthly_summary
    FOR SELECT TO authenticated USING (true);
CREATE POLICY "ecommerce_monthly_summary_modify_policy" ON public.ecommerce_monthly_summary
    FOR ALL TO authenticated
    USING (EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role IN ('admin', 'super_admin', 'editor')))
    WITH CHECK (EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role IN ('admin', 'super_admin', 'editor')));

-- -----------------------------------------------------------------------------
-- 2-4. financial_cost_details: 書込みをadmin/editorに限定
-- -----------------------------------------------------------------------------
DROP POLICY IF EXISTS "Allow authenticated users to insert financial_cost_details" ON public.financial_cost_details;
CREATE POLICY "Allow admin to insert financial_cost_details" ON public.financial_cost_details
    FOR INSERT TO authenticated
    WITH CHECK (EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role IN ('admin', 'super_admin', 'editor')));

DROP POLICY IF EXISTS "Allow authenticated users to update financial_cost_details" ON public.financial_cost_details;
CREATE POLICY "Allow admin to update financial_cost_details" ON public.financial_cost_details
    FOR UPDATE TO authenticated
    USING (EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role IN ('admin', 'super_admin', 'editor')))
    WITH CHECK (EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role IN ('admin', 'super_admin', 'editor')));

-- -----------------------------------------------------------------------------
-- 2-5. financial_sga_details: 書込みをadmin/editorに限定
-- -----------------------------------------------------------------------------
DROP POLICY IF EXISTS "Allow authenticated users to insert financial_sga_details" ON public.financial_sga_details;
CREATE POLICY "Allow admin to insert financial_sga_details" ON public.financial_sga_details
    FOR INSERT TO authenticated
    WITH CHECK (EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role IN ('admin', 'super_admin', 'editor')));

DROP POLICY IF EXISTS "Allow authenticated users to update financial_sga_details" ON public.financial_sga_details;
CREATE POLICY "Allow admin to update financial_sga_details" ON public.financial_sga_details
    FOR UPDATE TO authenticated
    USING (EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role IN ('admin', 'super_admin', 'editor')))
    WITH CHECK (EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role IN ('admin', 'super_admin', 'editor')));

-- -----------------------------------------------------------------------------
-- 2-6. furusato_nozei_stats: 書込みをadmin/editorに限定
-- -----------------------------------------------------------------------------
DROP POLICY IF EXISTS "furusato_nozei_stats_insert" ON public.furusato_nozei_stats;
CREATE POLICY "furusato_nozei_stats_insert" ON public.furusato_nozei_stats
    FOR INSERT TO authenticated
    WITH CHECK (EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role IN ('admin', 'super_admin', 'editor')));

DROP POLICY IF EXISTS "furusato_nozei_stats_update" ON public.furusato_nozei_stats;
CREATE POLICY "furusato_nozei_stats_update" ON public.furusato_nozei_stats
    FOR UPDATE TO authenticated
    USING (EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role IN ('admin', 'super_admin', 'editor')))
    WITH CHECK (EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role IN ('admin', 'super_admin', 'editor')));

-- -----------------------------------------------------------------------------
-- 2-7. product_sales: 書込みをadmin/editorに限定
-- -----------------------------------------------------------------------------
DROP POLICY IF EXISTS "Allow authenticated insert access" ON public.product_sales;
CREATE POLICY "Allow admin insert access" ON public.product_sales
    FOR INSERT TO authenticated
    WITH CHECK (EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role IN ('admin', 'super_admin', 'editor')));

DROP POLICY IF EXISTS "Allow authenticated update access" ON public.product_sales;
CREATE POLICY "Allow admin update access" ON public.product_sales
    FOR UPDATE TO authenticated
    USING (EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role IN ('admin', 'super_admin', 'editor')))
    WITH CHECK (EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role IN ('admin', 'super_admin', 'editor')));

-- -----------------------------------------------------------------------------
-- 2-8. regional_targets: 書込みをadmin/editorに限定
-- -----------------------------------------------------------------------------
DROP POLICY IF EXISTS "Allow authenticated users full access to regional_targets" ON public.regional_targets;
CREATE POLICY "regional_targets_select_policy" ON public.regional_targets
    FOR SELECT TO authenticated USING (true);
CREATE POLICY "regional_targets_modify_policy" ON public.regional_targets
    FOR ALL TO authenticated
    USING (EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role IN ('admin', 'super_admin', 'editor')))
    WITH CHECK (EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role IN ('admin', 'super_admin', 'editor')));

-- -----------------------------------------------------------------------------
-- 2-9. target_setting_history: 書込みをadmin/editorに限定
-- -----------------------------------------------------------------------------
DROP POLICY IF EXISTS "Allow authenticated users to insert target_setting_history" ON public.target_setting_history;
CREATE POLICY "Allow admin to insert target_setting_history" ON public.target_setting_history
    FOR INSERT TO authenticated
    WITH CHECK (EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role IN ('admin', 'super_admin', 'editor')));
