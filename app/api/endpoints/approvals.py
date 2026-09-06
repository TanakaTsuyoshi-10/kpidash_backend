"""
承認ワークフローAPIエンドポイント

申請の起票・一覧・詳細・承認・却下・差戻・差替・取下げ・添付アップロード。
閲覧/起票は user_page_permissions の "approvals" キーで制御（管理者・役員は常に許可）。
承認アクションの可否は「自分が現在の承認担当か」で service 層が判定する。
"""
from uuid import UUID

import os

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile, status
from supabase import Client

from app.api.deps import (
    get_supabase_admin,
    get_user_app_role,
    require_admin_or_executive,
    require_page_permission,
)
from app.schemas.approval import (
    ApprovalActionRequest,
    ApprovalTransferRequest,
    ApprovalDashboardResponse,
    PurgeAttachmentsResult,
    ApprovalReassignRequest,
    ApprovalRequestCreate,
    ApprovalRequestDetail,
    ApprovalRequestListResponse,
    ApprovalRequestSubmit,
    AttachmentUploadResponse,
    PendingCountResponse,
)
from app.services import approval_service

router = APIRouter()

require_approvals = require_page_permission("approvals")


async def get_current_user_or_maintenance_key(
    x_maintenance_key: str | None = Header(None),
    authorization: str | None = Header(None, description="Bearer token"),
):
    """管理者ユーザー、または MAINTENANCE_KEY ヘッダで認証する

    Cloud Scheduler 等の定期実行から呼べるように、環境変数 MAINTENANCE_KEY と
    一致する X-Maintenance-Key ヘッダを持つリクエストも許可する。
    """
    key = os.environ.get("MAINTENANCE_KEY")
    if key and x_maintenance_key == key:
        return None  # メンテナンスキーで許可

    from app.api.deps import get_current_user as _get_current_user

    user = await _get_current_user(authorization)
    if get_user_app_role(user.user_id) != "admin":
        raise HTTPException(status_code=403, detail="管理者権限が必要です")
    return user

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024  # 10MB


# =============================================================================
# 一覧・バッジ
# =============================================================================

@router.get(
    "/",
    response_model=ApprovalRequestListResponse,
    summary="承認申請一覧",
)
async def list_requests(
    tab: str = Query("mine", pattern="^(todo|mine|all)$"),
    current_user=Depends(require_approvals),
    supabase: Client = Depends(get_supabase_admin),
):
    role = get_user_app_role(current_user.user_id)
    return await approval_service.list_requests(
        supabase,
        user_id=current_user.user_id,
        tab=tab,
        is_admin_or_executive=role in ("admin", "executive"),
    )


@router.get(
    "/pending-count",
    response_model=PendingCountResponse,
    summary="自分にアクションが回ってきている件数（バッジ用）",
)
async def pending_count(
    current_user=Depends(require_approvals),
    supabase: Client = Depends(get_supabase_admin),
):
    count = await approval_service.count_pending_for_user(supabase, current_user.user_id)
    return PendingCountResponse(count=count)


@router.get(
    "/assignable-users",
    summary="承認者候補一覧（承認者指定UIに使う軽量ユーザー一覧）",
)
async def assignable_users(
    current_user=Depends(require_approvals),
    supabase: Client = Depends(get_supabase_admin),
):
    return await approval_service.list_assignable_users(supabase)


@router.get(
    "/viewer-candidates",
    summary="閲覧者候補一覧（承認権限不要・有効ユーザー全員）",
)
async def viewer_candidates(
    current_user=Depends(require_approvals),
    supabase: Client = Depends(get_supabase_admin),
):
    return await approval_service.list_viewer_candidates(supabase)


@router.get(
    "/dashboard",
    response_model=ApprovalDashboardResponse,
    summary="承認ワークフローダッシュボード（部署別×フェーズ別の件数と案件一覧）",
)
async def approval_dashboard(
    current_user=Depends(require_approvals),
    supabase: Client = Depends(get_supabase_admin),
):
    return await approval_service.get_dashboard(supabase, current_user.user_id)


@router.post(
    "/maintenance/purge-attachments",
    response_model=PurgeAttachmentsResult,
    summary="保存期間を過ぎた添付画像を削除する（管理者またはメンテナンスキー）",
)
async def purge_attachments(
    dry_run: bool = Query(False, description="true の場合は削除せず対象件数のみ返す"),
    retention_days: int | None = Query(None, ge=7, description="保存日数（省略時は環境変数 ATTACHMENT_RETENTION_DAYS、既定90日）"),
    x_maintenance_key: str | None = Header(None),
    current_user=Depends(get_current_user_or_maintenance_key),
    supabase: Client = Depends(get_supabase_admin),
):
    days = retention_days or int(os.environ.get("ATTACHMENT_RETENTION_DAYS", "90"))
    return await approval_service.purge_old_attachments(supabase, days, dry_run)


# =============================================================================
# 閲覧者の確認（押印）・削除
# =============================================================================

@router.post(
    "/{request_id}/acknowledge",
    summary="閲覧者の確認（押印）を記録する",
)
async def acknowledge_request(
    request_id: UUID,
    current_user=Depends(require_approvals),
    supabase: Client = Depends(get_supabase_admin),
):
    ok = await approval_service.acknowledge_request(
        supabase, str(request_id), current_user.user_id, current_user.email or ""
    )
    if not ok:
        raise HTTPException(status_code=403, detail="この案件の閲覧者に指定されていません")
    result = await approval_service.get_request(supabase, str(request_id), current_user.user_id)
    return result


@router.delete(
    "/{request_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="案件を削除する（起票者本人、または上席=admin/executive）",
)
async def delete_request(
    request_id: UUID,
    current_user=Depends(require_approvals),
    supabase: Client = Depends(get_supabase_admin),
):
    role = get_user_app_role(current_user.user_id)
    err = await approval_service.delete_request(
        supabase, str(request_id), current_user.user_id, current_user.email or "", role
    )
    if err:
        raise HTTPException(status_code=403, detail=err)


@router.post(
    "/{request_id}/transfer",
    response_model=ApprovalRequestDetail,
    summary="起票担当者を変更する（下書きの引き継ぎ）",
)
async def transfer_request(
    request_id: UUID,
    data: ApprovalTransferRequest,
    current_user=Depends(require_approvals),
    supabase: Client = Depends(get_supabase_admin),
):
    role = get_user_app_role(current_user.user_id)
    err = await approval_service.transfer_requester(
        supabase, str(request_id), data.new_requester_id,
        current_user.user_id, current_user.email or "", role,
    )
    if err:
        raise HTTPException(status_code=403, detail=err)
    result = await approval_service.get_request(supabase, str(request_id), current_user.user_id)
    if not result:
        raise HTTPException(status_code=404, detail="案件が見つかりません")
    return result


@router.post(
    "/{request_id}/duplicate",
    response_model=ApprovalRequestDetail,
    status_code=status.HTTP_201_CREATED,
    summary="稟議を複製して自分の下書きを作成する",
)
async def duplicate_request(
    request_id: UUID,
    current_user=Depends(require_approvals),
    supabase: Client = Depends(get_supabase_admin),
):
    result = await approval_service.duplicate_request(
        supabase, str(request_id), current_user.user_id, current_user.email or ""
    )
    if not result:
        raise HTTPException(status_code=404, detail="案件が見つからないか、複製権限がありません")
    return result


# =============================================================================
# 起票（下書き）
# =============================================================================

@router.post(
    "/",
    response_model=ApprovalRequestDetail,
    status_code=status.HTTP_201_CREATED,
    summary="下書き作成",
)
async def create_draft(
    data: ApprovalRequestCreate,
    current_user=Depends(require_approvals),
    supabase: Client = Depends(get_supabase_admin),
):
    result = await approval_service.create_draft(
        supabase, data, current_user.user_id, current_user.email or ""
    )
    if not result:
        raise HTTPException(status_code=500, detail="下書きの作成に失敗しました")
    return result


@router.put(
    "/{request_id}",
    response_model=ApprovalRequestDetail,
    summary="下書き更新",
)
async def update_draft(
    request_id: UUID,
    data: ApprovalRequestCreate,
    current_user=Depends(require_approvals),
    supabase: Client = Depends(get_supabase_admin),
):
    result = await approval_service.update_draft(
        supabase, str(request_id), data, current_user.user_id
    )
    if not result:
        raise HTTPException(
            status_code=404,
            detail="下書きが見つからないか、編集権限がありません（申請済みの場合は編集できません）",
        )
    return result


# =============================================================================
# 詳細
# =============================================================================

@router.get(
    "/{request_id}",
    response_model=ApprovalRequestDetail,
    summary="申請詳細",
)
async def get_request(
    request_id: UUID,
    current_user=Depends(require_approvals),
    supabase: Client = Depends(get_supabase_admin),
):
    result = await approval_service.get_request(supabase, str(request_id), current_user.user_id)
    if not result:
        raise HTTPException(status_code=404, detail="申請が見つかりません")

    # 閲覧権限: 申請者本人・承認ライン・admin/executive
    role = get_user_app_role(current_user.user_id)
    is_privileged = role in ("admin", "executive")
    in_route = any(
        s.assignee_id == current_user.user_id or s.original_assignee_id == current_user.user_id
        for s in result.steps
    )
    if not (is_privileged or result.requester_id == current_user.user_id or in_route):
        raise HTTPException(status_code=403, detail="この申請を閲覧する権限がありません")

    # 監査履歴は権限のある人のみ（それ以外は空にして返す）
    if not (is_privileged or result.requester_id == current_user.user_id or in_route):
        result.actions = []
    return result


# =============================================================================
# 申請・承認アクション
# =============================================================================

@router.post(
    "/{request_id}/submit",
    response_model=ApprovalRequestDetail,
    summary="申請（下書きを承認フローに乗せる）",
)
async def submit_request(
    request_id: UUID,
    data: ApprovalRequestSubmit,
    current_user=Depends(require_approvals),
    supabase: Client = Depends(get_supabase_admin),
):
    result = await approval_service.submit_request(
        supabase, str(request_id), data, current_user.user_id, current_user.email or ""
    )
    if not result:
        raise HTTPException(
            status_code=400,
            detail="申請できませんでした（下書き状態でないか、起票者ではありません）",
        )
    return result


@router.post(
    "/{request_id}/steps/{step_id}/approve",
    response_model=ApprovalRequestDetail,
    summary="承認",
)
async def approve(
    request_id: UUID,
    step_id: UUID,
    data: ApprovalActionRequest,
    current_user=Depends(require_approvals),
    supabase: Client = Depends(get_supabase_admin),
):
    result = await approval_service.approve_step(
        supabase, str(request_id), str(step_id),
        current_user.user_id, current_user.email or "", data.comment,
    )
    if not result:
        raise HTTPException(
            status_code=403,
            detail="承認できません（担当ではないか、承認順が回ってきていません）",
        )
    return result


@router.post(
    "/{request_id}/steps/{step_id}/reject",
    response_model=ApprovalRequestDetail,
    summary="却下",
)
async def reject(
    request_id: UUID,
    step_id: UUID,
    data: ApprovalActionRequest,
    current_user=Depends(require_approvals),
    supabase: Client = Depends(get_supabase_admin),
):
    result = await approval_service.reject_step(
        supabase, str(request_id), str(step_id),
        current_user.user_id, current_user.email or "", data.comment,
    )
    if not result:
        raise HTTPException(
            status_code=403,
            detail="却下できません（担当ではないか、承認順が回ってきていません）",
        )
    return result


@router.post(
    "/{request_id}/steps/{step_id}/return",
    response_model=ApprovalRequestDetail,
    summary="起票者へ差戻し",
)
async def return_to_requester(
    request_id: UUID,
    step_id: UUID,
    data: ApprovalActionRequest,
    current_user=Depends(require_approvals),
    supabase: Client = Depends(get_supabase_admin),
):
    result = await approval_service.return_to_requester(
        supabase, str(request_id), str(step_id),
        current_user.user_id, current_user.email or "", data.comment,
    )
    if not result:
        raise HTTPException(
            status_code=403,
            detail="差戻しできません（担当ではないか、承認順が回ってきていません）",
        )
    return result


@router.post(
    "/{request_id}/cancel",
    response_model=ApprovalRequestDetail,
    summary="取下げ（起票者のみ）",
)
async def cancel(
    request_id: UUID,
    current_user=Depends(require_approvals),
    supabase: Client = Depends(get_supabase_admin),
):
    result = await approval_service.cancel_request(
        supabase, str(request_id), current_user.user_id, current_user.email or ""
    )
    if not result:
        raise HTTPException(
            status_code=403,
            detail="取下げできません（起票者ではないか、既に確定済みです）",
        )
    return result


@router.post(
    "/{request_id}/reassign",
    response_model=ApprovalRequestDetail,
    summary="承認者差替（管理者・役員のみ）",
)
async def reassign(
    request_id: UUID,
    data: ApprovalReassignRequest,
    current_user=Depends(require_admin_or_executive),
    supabase: Client = Depends(get_supabase_admin),
):
    result = await approval_service.reassign_step(
        supabase, str(request_id), data.step_id, data.new_assignee_id,
        current_user.user_id, current_user.email or "", data.comment,
    )
    if not result:
        raise HTTPException(
            status_code=400,
            detail="差替できませんでした（対象ステップが見つからないか、承認待ちではありません）",
        )
    return result


@router.post(
    "/{request_id}/republish",
    response_model=ApprovalRequestDetail,
    summary="Slack投稿の再試行（管理者・役員のみ）",
)
async def republish(
    request_id: UUID,
    current_user=Depends(require_admin_or_executive),
    supabase: Client = Depends(get_supabase_admin),
):
    ok = await approval_service.publish_to_slack(supabase, str(request_id))
    if not ok:
        raise HTTPException(status_code=400, detail="Slack投稿に失敗しました")
    result = await approval_service.get_request(supabase, str(request_id), current_user.user_id)
    if not result:
        raise HTTPException(status_code=404, detail="申請が見つかりません")
    return result


# =============================================================================
# 添付アップロード
# =============================================================================

@router.post(
    "/attachments",
    response_model=AttachmentUploadResponse,
    summary="添付画像アップロード",
)
async def upload_attachment(
    file: UploadFile = File(...),
    current_user=Depends(require_approvals),
    supabase: Client = Depends(get_supabase_admin),
):
    data = await file.read()
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(status_code=413, detail="画像サイズは10MB以下にしてください")
    result = await approval_service.upload_attachment(
        supabase, data, file.filename or "image.png", file.content_type or "image/png"
    )
    if not result:
        raise HTTPException(
            status_code=400,
            detail="アップロードに失敗しました（対応形式: png / jpg / jpeg / gif / webp）",
        )
    return AttachmentUploadResponse(**result)
