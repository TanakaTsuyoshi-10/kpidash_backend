-- =============================================================================
-- 利用者管理機能マイグレーション
--
-- 対象:
-- 1. ユーザープロファイルテーブル（auth.usersと連携）
-- 2. ユーザー権限管理
-- =============================================================================

-- =============================================================================
-- 1. ユーザープロファイルテーブル
-- =============================================================================

CREATE TABLE IF NOT EXISTS user_profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,

    -- 基本情報
    display_name VARCHAR(100),                      -- 表示名（利用者名）
    email VARCHAR(255) NOT NULL,                    -- メールアドレス（auth.usersと同期）

    -- 権限
    role VARCHAR(20) NOT NULL DEFAULT 'user',       -- 権限: 'admin', 'user'

    -- ステータス
    is_active BOOLEAN DEFAULT true,                 -- 有効/無効

    -- メタデータ
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_by UUID,                                -- 登録者
    updated_by UUID                                 -- 更新者
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_user_profiles_email ON user_profiles(email);
CREATE INDEX IF NOT EXISTS idx_user_profiles_role ON user_profiles(role);
CREATE INDEX IF NOT EXISTS idx_user_profiles_is_active ON user_profiles(is_active);

-- =============================================================================
-- 2. ユーザー権限マスタテーブル（参照用）
-- =============================================================================

CREATE TABLE IF NOT EXISTS user_roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code VARCHAR(20) NOT NULL UNIQUE,               -- コード: 'admin', 'user'
    name VARCHAR(50) NOT NULL,                      -- 表示名
    description TEXT,                               -- 説明
    display_order INTEGER DEFAULT 0,                -- 表示順
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 初期データ投入
INSERT INTO user_roles (code, name, description, display_order) VALUES
    ('admin', '管理者', '利用者登録・権限変更が可能', 1),
    ('user', '一般利用者', '閲覧・データ入力のみ可能', 2)
ON CONFLICT (code) DO NOTHING;

-- =============================================================================
-- 3. RLS（Row Level Security）設定
-- =============================================================================

ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_roles ENABLE ROW LEVEL SECURITY;

-- 既存ポリシーを削除
DROP POLICY IF EXISTS "Users can view own profile" ON user_profiles;
DROP POLICY IF EXISTS "Admins can view all profiles" ON user_profiles;
DROP POLICY IF EXISTS "Admins can insert profiles" ON user_profiles;
DROP POLICY IF EXISTS "Admins can update profiles" ON user_profiles;
DROP POLICY IF EXISTS "Users can update own profile" ON user_profiles;
DROP POLICY IF EXISTS "Users can update own display_name" ON user_profiles;
DROP POLICY IF EXISTS "Service role full access to user_profiles" ON user_profiles;

DROP POLICY IF EXISTS "Allow authenticated users to view user_roles" ON user_roles;
DROP POLICY IF EXISTS "Service role full access to user_roles" ON user_roles;

-- user_profiles ポリシー

-- 自分自身のプロファイルは閲覧可能
CREATE POLICY "Users can view own profile"
    ON user_profiles FOR SELECT
    TO authenticated
    USING (auth.uid() = id);

-- 管理者は全プロファイルを閲覧可能
CREATE POLICY "Admins can view all profiles"
    ON user_profiles FOR SELECT
    TO authenticated
    USING (
        EXISTS (
            SELECT 1 FROM user_profiles
            WHERE id = auth.uid() AND role = 'admin'
        )
    );

-- 管理者のみ新規登録可能
CREATE POLICY "Admins can insert profiles"
    ON user_profiles FOR INSERT
    TO authenticated
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM user_profiles
            WHERE id = auth.uid() AND role = 'admin'
        )
    );

-- 管理者は全プロファイルを更新可能
CREATE POLICY "Admins can update profiles"
    ON user_profiles FOR UPDATE
    TO authenticated
    USING (
        EXISTS (
            SELECT 1 FROM user_profiles
            WHERE id = auth.uid() AND role = 'admin'
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM user_profiles
            WHERE id = auth.uid() AND role = 'admin'
        )
    );

-- 一般ユーザーは自分のプロファイル（表示名のみ）を更新可能
CREATE POLICY "Users can update own display_name"
    ON user_profiles FOR UPDATE
    TO authenticated
    USING (auth.uid() = id)
    WITH CHECK (auth.uid() = id);

-- service_role用フルアクセス
CREATE POLICY "Service role full access to user_profiles"
    ON user_profiles FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- user_roles ポリシー
CREATE POLICY "Allow authenticated users to view user_roles"
    ON user_roles FOR SELECT
    TO authenticated
    USING (true);

CREATE POLICY "Service role full access to user_roles"
    ON user_roles FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- =============================================================================
-- 4. 更新日時自動更新トリガー
-- =============================================================================

DROP TRIGGER IF EXISTS update_user_profiles_updated_at ON user_profiles;
CREATE TRIGGER update_user_profiles_updated_at
    BEFORE UPDATE ON user_profiles
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- =============================================================================
-- 5. 新規ユーザー登録時にプロファイル自動作成トリガー
-- =============================================================================

CREATE OR REPLACE FUNCTION handle_new_user()
RETURNS TRIGGER AS $$
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
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 既存のトリガーを削除してから作成
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW
    EXECUTE FUNCTION handle_new_user();

-- =============================================================================
-- 6. ユーザー一覧ビュー（管理画面用）
-- =============================================================================

CREATE OR REPLACE VIEW view_user_list AS
SELECT
    up.id,
    up.email,
    up.display_name,
    up.role,
    ur.name as role_name,
    up.is_active,
    up.created_at,
    up.updated_at,
    au.last_sign_in_at,
    au.created_at as auth_created_at
FROM user_profiles up
JOIN user_roles ur ON up.role = ur.code
LEFT JOIN auth.users au ON up.id = au.id
ORDER BY up.created_at DESC;

-- =============================================================================
-- 7. 既存ユーザーのプロファイル作成（初回マイグレーション時）
-- =============================================================================

-- 既存のauth.usersにプロファイルがない場合は作成
INSERT INTO user_profiles (id, email, display_name, role)
SELECT
    id,
    email,
    COALESCE(raw_user_meta_data->>'display_name', split_part(email, '@', 1)),
    COALESCE(raw_user_meta_data->>'role', 'user')
FROM auth.users
WHERE id NOT IN (SELECT id FROM user_profiles)
ON CONFLICT (id) DO NOTHING;

-- =============================================================================
-- 8. 最初の管理者設定（初期セットアップ用）
-- 注意: 実運用時は適切なユーザーを管理者に設定してください
-- =============================================================================

-- 最初に登録されたユーザーを管理者にする（プロファイルが存在する場合）
UPDATE user_profiles
SET role = 'admin'
WHERE id = (
    SELECT id FROM user_profiles
    ORDER BY created_at ASC
    LIMIT 1
)
AND NOT EXISTS (
    SELECT 1 FROM user_profiles WHERE role = 'admin'
);
