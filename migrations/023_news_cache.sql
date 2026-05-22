-- =============================================================================
-- 023_news_cache.sql
-- 餃子ニュースの永続キャッシュ
--
-- 目的:
--   Google News RSS から取得したニュースを Supabase に保存し、Cloud Run の
--   インスタンス再生成・デプロイ・スケールをまたいで保持する。
--   従来はインメモリキャッシュのみで、インスタンスごとに揮発していたため
--   「ニュースが表示されたりされなかったりする」現象が発生していた。
--   永続化することで、一度取得できれば以降は安定して表示でき、ライブ取得に
--   失敗しても直近の保存内容を返せる（空になりにくい）。
--
-- アクセス:
--   バックエンドはサービスロールキーで読み書きする（RLS をバイパス）。
--   フロントエンドはこのテーブルに直接アクセスしない。
-- =============================================================================

create table if not exists public.news_cache (
    cache_key   text primary key,
    payload     jsonb not null default '[]'::jsonb,
    fetched_at  timestamptz not null default now()
);

comment on table public.news_cache is '外部ニュース（餃子ニュース等）の永続キャッシュ';
comment on column public.news_cache.cache_key is 'キャッシュキー（例: gyoza）';
comment on column public.news_cache.payload is '記事リスト（JSON配列）';
comment on column public.news_cache.fetched_at is 'RSSから取得した日時（鮮度判定に使用）';

-- RLS を有効化。バックエンドはサービスロールキーでアクセスするため
-- ポリシー無しでも読み書き可能。匿名・認証ユーザーからの直接アクセスは拒否する。
alter table public.news_cache enable row level security;
