"""
承認ワークフローのユニットテスト

- 同時承認グループ（同一 step_no の複数承認者）の進行制御
- step_no の連番正規化
- 閲覧者の閲覧・確認（押印）が承認完了後のみ可能になるゲート
"""
import asyncio
from datetime import date

from app.services.approval_service import (
    _actionable_steps,
    _replace_steps,
    acknowledge_request,
    VIEWER_VISIBLE_STATUSES,
)
from app.schemas.approval import ApproverInput
from tests.test_target_service import FakeWritableSupabase


# =============================================================================
# 同時承認グループの進行制御
# =============================================================================

class TestActionableStepsGrouped:
    STEPS = [
        {"id": "s1", "step_no": 1, "status": "approved"},
        {"id": "s2", "step_no": 2, "status": "pending"},
        {"id": "s3", "step_no": 2, "status": "pending"},
        {"id": "s4", "step_no": 3, "status": "pending"},
    ]

    def test_sequential_returns_all_members_of_current_step(self):
        """順次モードで現在ステップの同時承認メンバー全員がアクション可能"""
        actionable = _actionable_steps(self.STEPS, "sequential", 2)
        assert {s["id"] for s in actionable} == {"s2", "s3"}

    def test_sequential_excludes_future_steps(self):
        """後続ステップ（最終決裁者など）はまだアクション不可"""
        actionable = _actionable_steps(self.STEPS, "sequential", 2)
        assert all(s["step_no"] == 2 for s in actionable)

    def test_group_partially_approved_still_current(self):
        """グループ内の1人が承認しても、残りが承認するまで現ステップに留まる
        （approve_step の next_step_no = min(残pendingのstep_no) 相当の検証）"""
        steps = [
            {"id": "s1", "step_no": 1, "status": "approved"},
            {"id": "s2", "step_no": 2, "status": "approved"},
            {"id": "s3", "step_no": 2, "status": "pending"},
            {"id": "s4", "step_no": 3, "status": "pending"},
        ]
        remaining = [s for s in steps if s["status"] == "pending"]
        next_step_no = min(s["step_no"] for s in remaining)
        assert next_step_no == 2  # まだステップ2（同時承認の残り待ち）
        assert {s["id"] for s in _actionable_steps(steps, "sequential", next_step_no)} == {"s3"}

    def test_group_fully_approved_advances_to_final(self):
        """同時承認グループ全員の承認で最終決裁者ステップへ進む"""
        steps = [
            {"id": "s1", "step_no": 1, "status": "approved"},
            {"id": "s2", "step_no": 2, "status": "approved"},
            {"id": "s3", "step_no": 2, "status": "approved"},
            {"id": "s4", "step_no": 3, "status": "pending"},
        ]
        remaining = [s for s in steps if s["status"] == "pending"]
        next_step_no = min(s["step_no"] for s in remaining)
        assert next_step_no == 3
        assert {s["id"] for s in _actionable_steps(steps, "sequential", next_step_no)} == {"s4"}


class TestReplaceStepsNormalization:
    def test_step_no_normalized_and_groups_preserved(self):
        """飛び番の step_no は連番に正規化され、同一グループは維持される"""
        fake = FakeWritableSupabase()
        approvers = [
            ApproverInput(step_no=2, assignee_id="a"),
            ApproverInput(step_no=5, assignee_id="b"),
            ApproverInput(step_no=5, assignee_id="c"),
            ApproverInput(step_no=9, assignee_id="d"),
        ]
        asyncio.run(_replace_steps(fake, "req-1", approvers))
        inserted = next(w[2] for w in fake.writes if w[0] == "insert" and w[1] == "approval_steps")
        by_assignee = {r["assignee_id"]: r["step_no"] for r in inserted}
        assert by_assignee == {"a": 1, "b": 2, "c": 2, "d": 3}


# =============================================================================
# 閲覧者の確認（押印）は承認完了後のみ
# =============================================================================

def _ack(status: str) -> bool:
    fake = FakeWritableSupabase({
        "approval_requests": [{"status": status}],
        "approval_viewers": [{"id": "v1", "acknowledged_at": None}],
    })
    return asyncio.run(acknowledge_request(fake, "req-1", "user-1", "u@example.com"))


class TestAcknowledgeGating:
    def test_pending_request_cannot_ack(self):
        """承認中はまだ確認（押印）できない"""
        assert _ack("pending") is False

    def test_draft_request_cannot_ack(self):
        assert _ack("draft") is False

    def test_approved_request_can_ack(self):
        for status in VIEWER_VISIBLE_STATUSES:
            assert _ack(status) is True, status
