-- =============================================================================
-- Supabaseセキュリティワーニングの修正SQL
-- =============================================================================

-- =============================================================================
-- 1. Function Search Path の修正
-- =============================================================================

-- update_updated_at_column 関数の修正
CREATE OR REPLACE FUNCTION public.update_updated_at_column()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

-- set_complaint_completed_at 関数の修正
CREATE OR REPLACE FUNCTION public.set_complaint_completed_at()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
BEGIN
    IF NEW.status = 'completed' AND OLD.status != 'completed' THEN
        NEW.completed_at = NOW();
    END IF;
    RETURN NEW;
END;
$$;

-- handle_new_user 関数の修正
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    INSERT INTO public.user_profiles (id, email, display_name, role, is_active)
    VALUES (
        NEW.id,
        NEW.email,
        COALESCE(NEW.raw_user_meta_data->>'display_name', split_part(NEW.email, '@', 1)),
        COALESCE(NEW.raw_user_meta_data->>'role', 'viewer'),
        true
    )
    ON CONFLICT (id) DO NOTHING;
    RETURN NEW;
END;
$$;

-- update_product_sales_updated_at 関数の修正
CREATE OR REPLACE FUNCTION public.update_product_sales_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


-- =============================================================================
-- 2. RLSポリシーの強化（役割ベースのアクセス制御）
-- =============================================================================

-- -----------------------------------------------------------------------------
-- complaints テーブル
-- -----------------------------------------------------------------------------
DROP POLICY IF EXISTS "Allow authenticated users to insert complaints" ON public.complaints;
DROP POLICY IF EXISTS "Allow authenticated users to update complaints" ON public.complaints;
DROP POLICY IF EXISTS "Allow authenticated users to delete complaints" ON public.complaints;

-- INSERT: 認証済みユーザー全員が登録可能（これは意図的に緩く）
CREATE POLICY "complaints_insert_policy" ON public.complaints
    FOR INSERT TO authenticated
    WITH CHECK (true);

-- UPDATE: admin/super_admin/editor のみ
CREATE POLICY "complaints_update_policy" ON public.complaints
    FOR UPDATE TO authenticated
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

-- DELETE: admin/super_admin のみ
CREATE POLICY "complaints_delete_policy" ON public.complaints
    FOR DELETE TO authenticated
    USING (
        EXISTS (
            SELECT 1 FROM public.user_profiles
            WHERE id = auth.uid() AND role IN ('admin', 'super_admin')
        )
    );


-- -----------------------------------------------------------------------------
-- ecommerce_monthly_summary テーブル
-- -----------------------------------------------------------------------------
DROP POLICY IF EXISTS "Allow authenticated users full access to ecommerce_monthly_summ" ON public.ecommerce_monthly_summary;

CREATE POLICY "ecommerce_monthly_summary_select_policy" ON public.ecommerce_monthly_summary
    FOR SELECT TO authenticated
    USING (true);

CREATE POLICY "ecommerce_monthly_summary_modify_policy" ON public.ecommerce_monthly_summary
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


-- -----------------------------------------------------------------------------
-- financial_cost_details テーブル
-- -----------------------------------------------------------------------------
DROP POLICY IF EXISTS "Allow authenticated users to insert financial_cost_details" ON public.financial_cost_details;
DROP POLICY IF EXISTS "Allow authenticated users to update financial_cost_details" ON public.financial_cost_details;

CREATE POLICY "financial_cost_details_select_policy" ON public.financial_cost_details
    FOR SELECT TO authenticated
    USING (true);

CREATE POLICY "financial_cost_details_modify_policy" ON public.financial_cost_details
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


-- -----------------------------------------------------------------------------
-- financial_data テーブル
-- -----------------------------------------------------------------------------
DROP POLICY IF EXISTS "Allow service_role write financial_data" ON public.financial_data;

-- SELECTは全認証ユーザー
CREATE POLICY "financial_data_select_policy" ON public.financial_data
    FOR SELECT TO authenticated
    USING (true);

-- 書き込みはadmin/super_admin/editor
CREATE POLICY "financial_data_modify_policy" ON public.financial_data
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


-- -----------------------------------------------------------------------------
-- financial_sga_details テーブル
-- -----------------------------------------------------------------------------
DROP POLICY IF EXISTS "Allow authenticated users to insert financial_sga_details" ON public.financial_sga_details;
DROP POLICY IF EXISTS "Allow authenticated users to update financial_sga_details" ON public.financial_sga_details;

CREATE POLICY "financial_sga_details_select_policy" ON public.financial_sga_details
    FOR SELECT TO authenticated
    USING (true);

CREATE POLICY "financial_sga_details_modify_policy" ON public.financial_sga_details
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


-- -----------------------------------------------------------------------------
-- manufacturing_data テーブル
-- -----------------------------------------------------------------------------
DROP POLICY IF EXISTS "Allow service_role write manufacturing_data" ON public.manufacturing_data;

CREATE POLICY "manufacturing_data_select_policy" ON public.manufacturing_data
    FOR SELECT TO authenticated
    USING (true);

CREATE POLICY "manufacturing_data_modify_policy" ON public.manufacturing_data
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


-- -----------------------------------------------------------------------------
-- product_sales テーブル
-- -----------------------------------------------------------------------------
DROP POLICY IF EXISTS "Allow authenticated insert access" ON public.product_sales;
DROP POLICY IF EXISTS "Allow authenticated update access" ON public.product_sales;

CREATE POLICY "product_sales_select_policy" ON public.product_sales
    FOR SELECT TO authenticated
    USING (true);

CREATE POLICY "product_sales_modify_policy" ON public.product_sales
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


-- -----------------------------------------------------------------------------
-- regional_targets テーブル
-- -----------------------------------------------------------------------------
DROP POLICY IF EXISTS "Allow authenticated users full access to regional_targets" ON public.regional_targets;

CREATE POLICY "regional_targets_select_policy" ON public.regional_targets
    FOR SELECT TO authenticated
    USING (true);

CREATE POLICY "regional_targets_modify_policy" ON public.regional_targets
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


-- -----------------------------------------------------------------------------
-- target_setting_history テーブル
-- -----------------------------------------------------------------------------
DROP POLICY IF EXISTS "Allow authenticated users to insert target_setting_history" ON public.target_setting_history;

CREATE POLICY "target_setting_history_select_policy" ON public.target_setting_history
    FOR SELECT TO authenticated
    USING (true);

CREATE POLICY "target_setting_history_modify_policy" ON public.target_setting_history
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
-- ワーニングが解消されたことを確認してください。
--
-- ※ Leaked Password Protection は管理画面から有効化してください：
--   Authentication > Settings > Password Security > Enable leaked password protection
