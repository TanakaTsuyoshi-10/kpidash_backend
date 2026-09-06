-- =============================================================================
-- 033_approval_transfer_duplicate.sql
-- 承認ワークフロー: 起票担当者の変更・稟議の複製に伴う監査アクション追加
-- =============================================================================

ALTER TABLE approval_actions DROP CONSTRAINT IF EXISTS approval_actions_action_check;
ALTER TABLE approval_actions ADD CONSTRAINT approval_actions_action_check
    CHECK (action = ANY (ARRAY[
        'submit', 'resubmit', 'approve', 'reject',
        'return_to_requester', 'return_to_step', 'reassign',
        'add_approver', 'remove_approver', 'delegate_auto',
        'cancel', 'publish_success', 'publish_failed', 'notify_failed',
        'viewer_ack', 'delete', 'attachments_purged',
        'transfer_requester', 'duplicate'
    ]::text[]));
