-- =============================================================================
-- 032_approval_viewers_and_lifecycle.sql
-- 承認ワークフロー: 閲覧者（押印確認）・削除・添付画像の保存期限
-- =============================================================================
-- 1. approval_viewers: 起票時に指定する閲覧者。承認はしないが
--    「確認（押印）」を記録する（acknowledged_at）
-- 2. approval_actions.action に viewer_ack / delete / attachments_purged を追加
-- =============================================================================

CREATE TABLE IF NOT EXISTS approval_viewers (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id uuid NOT NULL REFERENCES approval_requests(id) ON DELETE CASCADE,
    viewer_id uuid NOT NULL,
    viewer_email varchar(255),
    acknowledged_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (request_id, viewer_id)
);

CREATE INDEX IF NOT EXISTS idx_approval_viewers_request ON approval_viewers (request_id);
CREATE INDEX IF NOT EXISTS idx_approval_viewers_viewer ON approval_viewers (viewer_id);

ALTER TABLE approval_viewers ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "approval_viewers_select" ON approval_viewers;
CREATE POLICY "approval_viewers_select" ON approval_viewers
    FOR SELECT TO authenticated USING (true);

DROP POLICY IF EXISTS "approval_viewers_service_all" ON approval_viewers;
CREATE POLICY "approval_viewers_service_all" ON approval_viewers
    FOR ALL TO service_role USING (true) WITH CHECK (true);

-- 監査アクションの種類を追加
ALTER TABLE approval_actions DROP CONSTRAINT IF EXISTS approval_actions_action_check;
ALTER TABLE approval_actions ADD CONSTRAINT approval_actions_action_check
    CHECK (action = ANY (ARRAY[
        'submit', 'resubmit', 'approve', 'reject',
        'return_to_requester', 'return_to_step', 'reassign',
        'add_approver', 'remove_approver', 'delegate_auto',
        'cancel', 'publish_success', 'publish_failed', 'notify_failed',
        'viewer_ack', 'delete', 'attachments_purged'
    ]::text[]));
