"""
承認ワークフローサービス

申請の下書き作成・申請・承認・却下・差戻・差替・取下げと、
承認完了時の Slack 投稿、申請時のメール通知を担う。

状態遷移:
    draft → pending → approved → published / publish_failed
                   → rejected（却下）
    draft/pending → cancelled（取下げ）
    pending → draft（差戻し = return_to_requester）

承認モード:
    sequential   : step_no 順に1人ずつ。全員承認で完了
    parallel_and : 全員同時に回覧。全員承認で完了
    parallel_or  : 全員同時に回覧。誰か1人の承認で完了（残りは skipped）
"""
import logging
import uuid as uuid_module
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from supabase import Client

from app.schemas.approval import (
    ApprovalAction,
    ApprovalDelegate,
    ApprovalDelegateCreate,
    ApprovalRequestCreate,
    ApprovalRequestDetail,
    ApprovalRequestListResponse,
    ApprovalRequestSubmit,
    ApprovalRequestSummary,
    ApprovalStep,
    ApproverInput,
    RequestType,
    RequestTypeCreate,
    RequestTypeUpdate,
    SlackChannelBinding,
    SlackChannelBindingCreate,
)
from app.services import email_service, slack_post_service

logger = logging.getLogger(__name__)

ATTACHMENTS_BUCKET = "approvals-attachments"


# =============================================================================
# ヘルパー
# =============================================================================

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_profiles(supabase: Client, user_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """user_profiles をまとめて引く（id -> {email, display_name}）"""
    ids = [uid for uid in set(user_ids) if uid]
    if not ids:
        return {}
    try:
        res = (
            supabase.table("user_profiles")
            .select("id, email, display_name")
            .in_("id", ids)
            .execute()
        )
        return {str(r["id"]): r for r in (res.data or [])}
    except Exception as exc:
        logger.warning("user_profiles 取得失敗: %s", exc)
        return {}


def _display_name(profile: Optional[Dict[str, Any]]) -> str:
    if not profile:
        return "不明なユーザー"
    return profile.get("display_name") or (profile.get("email") or "").split("@")[0] or "不明なユーザー"


def _record_action(
    supabase: Client,
    request_id: str,
    actor_id: str,
    actor_email: str,
    action: str,
    step_id: Optional[str] = None,
    on_behalf_of_id: Optional[str] = None,
    before_state: Optional[Dict[str, Any]] = None,
    after_state: Optional[Dict[str, Any]] = None,
    comment: Optional[str] = None,
) -> None:
    """監査証跡を記録する（失敗しても本処理は止めない）"""
    try:
        supabase.table("approval_actions").insert({
            "request_id": request_id,
            "step_id": step_id,
            "actor_id": actor_id,
            "actor_email": actor_email,
            "on_behalf_of_id": on_behalf_of_id,
            "action": action,
            "before_state": before_state or {},
            "after_state": after_state or {},
            "comment": comment,
        }).execute()
    except Exception as exc:
        logger.error("監査証跡の記録に失敗: request=%s action=%s error=%s", request_id, action, exc)


def _resolve_delegate(supabase: Client, assignee_id: str) -> Optional[Dict[str, Any]]:
    """有効な代理設定があれば返す（不在期間中の自動ルーティング用）"""
    try:
        now = _now_iso()
        res = (
            supabase.table("approval_delegates")
            .select("*")
            .eq("user_id", assignee_id)
            .lte("starts_at", now)
            .gte("ends_at", now)
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None
    except Exception as exc:
        logger.warning("代理設定の解決に失敗: %s", exc)
        return None


def _row_to_step(row: Dict[str, Any], profiles: Dict[str, Dict[str, Any]]) -> ApprovalStep:
    return ApprovalStep(
        id=str(row["id"]),
        request_id=str(row["request_id"]),
        step_no=row["step_no"],
        assignee_id=str(row["assignee_id"]),
        original_assignee_id=str(row["original_assignee_id"]),
        assignee_email=row.get("assignee_email") or "",
        assignee_name=_display_name(profiles.get(str(row["assignee_id"]))),
        status=row["status"],
        acted_at=row.get("acted_at"),
        comment=row.get("comment"),
        notified_at=row.get("notified_at"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_summary(
    row: Dict[str, Any],
    type_labels: Dict[str, str],
    profiles: Dict[str, Dict[str, Any]],
    my_pending_request_ids: Optional[set] = None,
) -> ApprovalRequestSummary:
    return ApprovalRequestSummary(
        id=str(row["id"]),
        request_type=row["request_type"],
        request_type_label=type_labels.get(row["request_type"], row["request_type"]),
        title=row["title"],
        status=row["status"],
        approval_mode=row["approval_mode"],
        requester_id=str(row["requester_id"]),
        requester_email=row.get("requester_email") or "",
        requester_name=_display_name(profiles.get(str(row["requester_id"]))),
        current_step_no=row.get("current_step_no") or 1,
        my_step_pending=(
            str(row["id"]) in my_pending_request_ids
            if my_pending_request_ids is not None else False
        ),
        stalled=bool((row.get("metadata") or {}).get("stalled")),
        submitted_at=row.get("submitted_at"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _actionable_steps(steps: List[Dict[str, Any]], mode: str, current_step_no: int) -> List[Dict[str, Any]]:
    """今アクション可能な（承認待ちが回ってきている）step 行を返す"""
    pending = [s for s in steps if s["status"] == "pending"]
    if mode == "sequential":
        return [s for s in pending if s["step_no"] == current_step_no]
    return pending  # parallel_and / parallel_or は全 pending が対象


# =============================================================================
# 承認者候補（軽量ユーザー一覧）
# =============================================================================

async def list_assignable_users(supabase: Client) -> List[Dict[str, str]]:
    """承認者として指定可能なユーザーの軽量一覧（有効ユーザーのみ）"""
    try:
        res = (
            supabase.table("user_profiles")
            .select("id, email, display_name, is_active")
            .eq("is_active", True)
            .order("display_name")
            .execute()
        )
        return [
            {
                "id": str(r["id"]),
                "email": r.get("email") or "",
                "display_name": _display_name(r),
            }
            for r in (res.data or [])
        ]
    except Exception as exc:
        logger.warning("承認者候補の取得に失敗: %s", exc)
        return []


# =============================================================================
# 申請種別マスタ
# =============================================================================

async def list_request_types(supabase: Client, include_inactive: bool = False) -> List[RequestType]:
    query = supabase.table("request_types").select("*").order("display_order")
    if not include_inactive:
        query = query.eq("is_active", True)
    res = query.execute()
    return [RequestType(**{**r, "default_approver_ids": [str(x) for x in (r.get("default_approver_ids") or [])]}) for r in (res.data or [])]


async def create_request_type(supabase: Client, data: RequestTypeCreate) -> Optional[RequestType]:
    record = data.model_dump()
    res = supabase.table("request_types").insert(record).execute()
    if not res.data:
        return None
    row = res.data[0]
    return RequestType(**{**row, "default_approver_ids": [str(x) for x in (row.get("default_approver_ids") or [])]})


async def update_request_type(supabase: Client, code: str, data: RequestTypeUpdate) -> Optional[RequestType]:
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if not updates:
        res = supabase.table("request_types").select("*").eq("code", code).execute()
    else:
        res = supabase.table("request_types").update(updates).eq("code", code).execute()
    if not res.data:
        return None
    row = res.data[0]
    return RequestType(**{**row, "default_approver_ids": [str(x) for x in (row.get("default_approver_ids") or [])]})


# =============================================================================
# Slack チャンネルバインディング
# =============================================================================

async def list_channel_bindings(supabase: Client, request_type: Optional[str] = None) -> List[SlackChannelBinding]:
    query = supabase.table("slack_channel_bindings").select("*").order("created_at")
    if request_type:
        query = query.eq("request_type", request_type)
    res = query.execute()
    return [SlackChannelBinding(**{**r, "id": str(r["id"])}) for r in (res.data or [])]


async def create_channel_binding(supabase: Client, data: SlackChannelBindingCreate) -> Optional[SlackChannelBinding]:
    # Bot 参加チェック（未参加でも登録は許可し、警告ログを残す）
    is_member, channel_name = await slack_post_service.check_bot_in_channel(data.channel_id)
    record = data.model_dump()
    if channel_name and not record.get("channel_name"):
        record["channel_name"] = channel_name
    res = supabase.table("slack_channel_bindings").insert(record).execute()
    if not res.data:
        return None
    binding = SlackChannelBinding(**{**res.data[0], "id": str(res.data[0]["id"])})
    if not is_member:
        logger.warning("Bot が未参加のチャンネルが登録されました: %s", data.channel_id)
    return binding


async def delete_channel_binding(supabase: Client, binding_id: str) -> bool:
    res = supabase.table("slack_channel_bindings").delete().eq("id", binding_id).execute()
    return bool(res.data)


# =============================================================================
# 申請 CRUD
# =============================================================================

async def create_draft(
    supabase: Client,
    data: ApprovalRequestCreate,
    user_id: str,
    user_email: str,
) -> Optional[ApprovalRequestDetail]:
    """下書きを作成する"""
    record = {
        "request_type": data.request_type,
        "title": data.title or "(無題)",
        "status": "draft",
        "approval_mode": data.approval_mode or "sequential",
        "content": data.content,
        "metadata": data.metadata,
        "requester_id": user_id,
        "requester_email": user_email,
    }
    res = supabase.table("approval_requests").insert(record).execute()
    if not res.data:
        return None
    request_id = str(res.data[0]["id"])

    # 下書き段階でも承認者指定があれば steps を作っておく
    if data.approvers:
        await _replace_steps(supabase, request_id, data.approvers)

    return await get_request(supabase, request_id, user_id)


async def update_draft(
    supabase: Client,
    request_id: str,
    data: ApprovalRequestCreate,
    user_id: str,
) -> Optional[ApprovalRequestDetail]:
    """下書きを更新する（起票者本人のみ・draft のみ）"""
    res = supabase.table("approval_requests").select("*").eq("id", request_id).execute()
    if not res.data:
        return None
    row = res.data[0]
    if str(row["requester_id"]) != user_id or row["status"] != "draft":
        return None

    supabase.table("approval_requests").update({
        "title": data.title or "(無題)",
        "content": data.content,
        "metadata": data.metadata,
        "approval_mode": data.approval_mode or row["approval_mode"],
    }).eq("id", request_id).execute()

    if data.approvers is not None:
        await _replace_steps(supabase, request_id, data.approvers)

    return await get_request(supabase, request_id, user_id)


async def _replace_steps(supabase: Client, request_id: str, approvers: List[ApproverInput]) -> None:
    """steps を作り直す（draft 段階のみ呼ぶこと）"""
    supabase.table("approval_steps").delete().eq("request_id", request_id).execute()
    if not approvers:
        return
    profiles = _get_profiles(supabase, [a.assignee_id for a in approvers])
    rows = []
    for a in approvers:
        profile = profiles.get(a.assignee_id, {})
        rows.append({
            "request_id": request_id,
            "step_no": a.step_no,
            "assignee_id": a.assignee_id,
            "original_assignee_id": a.assignee_id,
            "assignee_email": profile.get("email") or "",
        })
    supabase.table("approval_steps").insert(rows).execute()


async def list_requests(
    supabase: Client,
    user_id: str,
    tab: str = "mine",
    is_admin_or_executive: bool = False,
    limit: int = 50,
) -> ApprovalRequestListResponse:
    """
    一覧取得。
    tab:
        todo : 自分にアクションが回ってきている申請
        mine : 自分が起票した申請
        all  : 全件（admin/executive のみ）
    """
    # 自分が pending assignee の request_id 集合
    my_steps_res = (
        supabase.table("approval_steps")
        .select("request_id, step_no, status")
        .eq("assignee_id", user_id)
        .eq("status", "pending")
        .execute()
    )
    my_pending_ids = {str(s["request_id"]) for s in (my_steps_res.data or [])}

    if tab == "todo":
        if not my_pending_ids:
            return ApprovalRequestListResponse(requests=[], total=0)
        query = (
            supabase.table("approval_requests")
            .select("*")
            .in_("id", list(my_pending_ids))
            .eq("status", "pending")
            .is_("soft_deleted_at", "null")
        )
    elif tab == "all":
        if not is_admin_or_executive:
            return ApprovalRequestListResponse(requests=[], total=0)
        query = (
            supabase.table("approval_requests")
            .select("*")
            .is_("soft_deleted_at", "null")
        )
    else:  # mine
        query = (
            supabase.table("approval_requests")
            .select("*")
            .eq("requester_id", user_id)
            .is_("soft_deleted_at", "null")
        )

    res = query.order("created_at", desc=True).limit(limit).execute()
    rows = res.data or []

    # sequential の場合、自分の step 番号が current でないものは todo から除く
    if tab == "todo" and rows:
        step_rows = (
            supabase.table("approval_steps")
            .select("request_id, step_no")
            .eq("assignee_id", user_id)
            .eq("status", "pending")
            .execute()
        ).data or []
        my_step_no = {str(s["request_id"]): s["step_no"] for s in step_rows}
        rows = [
            r for r in rows
            if r["approval_mode"] != "sequential"
            or my_step_no.get(str(r["id"])) == (r.get("current_step_no") or 1)
        ]

    types = await list_request_types(supabase, include_inactive=True)
    type_labels = {t.code: t.label for t in types}
    profiles = _get_profiles(supabase, [str(r["requester_id"]) for r in rows])

    summaries = [_row_to_summary(r, type_labels, profiles, my_pending_ids) for r in rows]
    return ApprovalRequestListResponse(requests=summaries, total=len(summaries))


async def count_pending_for_user(supabase: Client, user_id: str) -> int:
    """自分にアクションが回ってきている件数（サイドバーバッジ用）"""
    result = await list_requests(supabase, user_id, tab="todo")
    return result.total


async def get_request(
    supabase: Client,
    request_id: str,
    user_id: str,
) -> Optional[ApprovalRequestDetail]:
    """詳細取得（ステップ・監査履歴込み）"""
    res = supabase.table("approval_requests").select("*").eq("id", request_id).execute()
    if not res.data:
        return None
    row = res.data[0]

    steps_res = (
        supabase.table("approval_steps")
        .select("*")
        .eq("request_id", request_id)
        .order("step_no")
        .order("created_at")
        .execute()
    )
    step_rows = steps_res.data or []

    actions_res = (
        supabase.table("approval_actions")
        .select("*")
        .eq("request_id", request_id)
        .order("created_at")
        .execute()
    )
    action_rows = actions_res.data or []

    all_user_ids = (
        [str(row["requester_id"])]
        + [str(s["assignee_id"]) for s in step_rows]
        + [str(a["actor_id"]) for a in action_rows]
    )
    profiles = _get_profiles(supabase, all_user_ids)

    types = await list_request_types(supabase, include_inactive=True)
    type_labels = {t.code: t.label for t in types}

    actionable = _actionable_steps(step_rows, row["approval_mode"], row.get("current_step_no") or 1)
    can_act = row["status"] == "pending" and any(
        str(s["assignee_id"]) == user_id for s in actionable
    )
    can_edit = str(row["requester_id"]) == user_id and row["status"] == "draft"

    summary = _row_to_summary(row, type_labels, profiles)
    return ApprovalRequestDetail(
        **summary.model_dump(),
        content=row.get("content") or {},
        metadata=row.get("metadata") or {},
        approved_at=row.get("approved_at"),
        rejected_at=row.get("rejected_at"),
        published_at=row.get("published_at"),
        steps=[_row_to_step(s, profiles) for s in step_rows],
        actions=[
            ApprovalAction(
                **{
                    **a,
                    "id": str(a["id"]),
                    "request_id": str(a["request_id"]),
                    "step_id": str(a["step_id"]) if a.get("step_id") else None,
                    "actor_id": str(a["actor_id"]),
                    "on_behalf_of_id": str(a["on_behalf_of_id"]) if a.get("on_behalf_of_id") else None,
                    "actor_name": _display_name(profiles.get(str(a["actor_id"]))),
                }
            )
            for a in action_rows
        ],
        can_act=can_act,
        can_edit=can_edit,
    )


# =============================================================================
# 申請（submit）
# =============================================================================

async def submit_request(
    supabase: Client,
    request_id: str,
    data: ApprovalRequestSubmit,
    user_id: str,
    user_email: str,
) -> Optional[ApprovalRequestDetail]:
    """下書きを申請する（差戻し後の再申請も同じ）"""
    res = supabase.table("approval_requests").select("*").eq("id", request_id).execute()
    if not res.data:
        return None
    row = res.data[0]
    if str(row["requester_id"]) != user_id or row["status"] not in ("draft",):
        return None

    is_resubmit = bool(row.get("submitted_at"))

    # 内容を確定
    supabase.table("approval_requests").update({
        "title": data.title,
        "content": data.content,
        "metadata": data.metadata,
        "approval_mode": data.approval_mode,
        "status": "pending",
        "current_step_no": 1,
        "submitted_at": _now_iso(),
        "rejected_at": None,
    }).eq("id", request_id).execute()

    # ステップを作り直し（再申請時も全リセット）
    await _replace_steps(supabase, request_id, data.approvers)

    # 代理設定の自動ルーティング
    await _apply_auto_delegation(supabase, request_id, data.title, user_email)

    _record_action(
        supabase, request_id, user_id, user_email,
        "resubmit" if is_resubmit else "submit",
        after_state={
            "approval_mode": data.approval_mode,
            "approvers": [a.model_dump() for a in data.approvers],
        },
    )

    # 最初にアクションすべき承認者へメール通知
    await _notify_current_approvers(supabase, request_id)

    return await get_request(supabase, request_id, user_id)


async def _apply_auto_delegation(
    supabase: Client, request_id: str, title: str, requester_email: str
) -> None:
    """pending step の assignee に有効な代理設定があれば自動で差し替える"""
    steps_res = (
        supabase.table("approval_steps")
        .select("*")
        .eq("request_id", request_id)
        .eq("status", "pending")
        .execute()
    )
    for step in steps_res.data or []:
        delegate_row = _resolve_delegate(supabase, str(step["assignee_id"]))
        if not delegate_row:
            continue
        delegate_id = str(delegate_row["delegate_id"])
        profiles = _get_profiles(supabase, [str(step["assignee_id"]), delegate_id])
        original_name = _display_name(profiles.get(str(step["assignee_id"])))
        delegate_name = _display_name(profiles.get(delegate_id))
        delegate_email = (profiles.get(delegate_id) or {}).get("email") or ""

        supabase.table("approval_steps").update({
            "assignee_id": delegate_id,
            "assignee_email": delegate_email,
        }).eq("id", step["id"]).execute()

        _record_action(
            supabase, request_id, delegate_id, delegate_email, "delegate_auto",
            step_id=str(step["id"]),
            on_behalf_of_id=str(step["assignee_id"]),
            before_state={"assignee_id": str(step["assignee_id"])},
            after_state={"assignee_id": delegate_id, "delegate_row_id": str(delegate_row["id"])},
        )

        emails = [e for e in [
            (profiles.get(str(step["assignee_id"])) or {}).get("email"),
            delegate_email,
        ] if e]
        if emails:
            await email_service.send_delegation_email(
                emails, original_name, delegate_name, title, request_id
            )


async def _notify_current_approvers(supabase: Client, request_id: str) -> None:
    """今アクションすべき承認者にメールを送り notified_at を更新する"""
    res = supabase.table("approval_requests").select("*").eq("id", request_id).execute()
    if not res.data:
        return
    row = res.data[0]
    if row["status"] != "pending":
        return

    steps_res = (
        supabase.table("approval_steps")
        .select("*")
        .eq("request_id", request_id)
        .execute()
    )
    actionable = _actionable_steps(
        steps_res.data or [], row["approval_mode"], row.get("current_step_no") or 1
    )

    types = await list_request_types(supabase, include_inactive=True)
    type_label = next((t.label for t in types if t.code == row["request_type"]), row["request_type"])

    profiles = _get_profiles(supabase, [str(row["requester_id"])])
    requester_name = _display_name(profiles.get(str(row["requester_id"])))

    content = row.get("content") or {}
    preview = (content.get("caption_plain") or "")[:200]

    for step in actionable:
        email = step.get("assignee_email")
        if not email:
            continue
        ok = await email_service.send_approval_request_email(
            email, requester_name, type_label, row["title"], preview, request_id
        )
        if ok:
            supabase.table("approval_steps").update(
                {"notified_at": _now_iso()}
            ).eq("id", step["id"]).execute()
        else:
            _record_action(
                supabase, request_id, str(row["requester_id"]), row.get("requester_email") or "",
                "notify_failed", step_id=str(step["id"]),
                after_state={"email": email},
            )


# =============================================================================
# 承認・却下・差戻・取下げ
# =============================================================================

async def approve_step(
    supabase: Client,
    request_id: str,
    step_id: str,
    user_id: str,
    user_email: str,
    comment: Optional[str] = None,
) -> Optional[ApprovalRequestDetail]:
    """1ステップを承認する。全ステップ完了なら Slack 投稿まで行う"""
    res = supabase.table("approval_requests").select("*").eq("id", request_id).execute()
    if not res.data or res.data[0]["status"] != "pending":
        return None
    row = res.data[0]

    steps_res = supabase.table("approval_steps").select("*").eq("request_id", request_id).execute()
    step_rows = steps_res.data or []
    actionable = _actionable_steps(step_rows, row["approval_mode"], row.get("current_step_no") or 1)

    target = next(
        (s for s in actionable if str(s["id"]) == step_id and str(s["assignee_id"]) == user_id),
        None,
    )
    if not target:
        return None  # 権限なし or 順番が来ていない

    supabase.table("approval_steps").update({
        "status": "approved",
        "acted_at": _now_iso(),
        "comment": comment,
    }).eq("id", step_id).execute()

    on_behalf = (
        str(target["original_assignee_id"])
        if str(target["original_assignee_id"]) != user_id else None
    )
    _record_action(
        supabase, request_id, user_id, user_email, "approve",
        step_id=step_id, on_behalf_of_id=on_behalf,
        before_state={"status": "pending"},
        after_state={"status": "approved"},
        comment=comment,
    )

    # 完了判定
    mode = row["approval_mode"]
    remaining = [
        s for s in step_rows
        if str(s["id"]) != step_id and s["status"] == "pending"
    ]

    if mode == "parallel_or":
        # 1人承認で完了。残りを skipped に
        for s in remaining:
            supabase.table("approval_steps").update({"status": "skipped"}).eq("id", s["id"]).execute()
        await _finalize_approval(supabase, request_id)
    elif not remaining:
        # sequential / parallel_and で全員承認済み
        await _finalize_approval(supabase, request_id)
    elif mode == "sequential":
        # 次の step へ進めて通知
        next_step_no = min(s["step_no"] for s in remaining)
        supabase.table("approval_requests").update(
            {"current_step_no": next_step_no}
        ).eq("id", request_id).execute()
        await _notify_current_approvers(supabase, request_id)

    return await get_request(supabase, request_id, user_id)


async def _finalize_approval(supabase: Client, request_id: str) -> None:
    """全承認完了 → approved に遷移し Slack 投稿を試みる"""
    supabase.table("approval_requests").update({
        "status": "approved",
        "approved_at": _now_iso(),
    }).eq("id", request_id).execute()

    await publish_to_slack(supabase, request_id)


async def publish_to_slack(supabase: Client, request_id: str) -> bool:
    """承認済み申請を Slack に投稿する（手動再試行からも呼ばれる）"""
    res = supabase.table("approval_requests").select("*").eq("id", request_id).execute()
    if not res.data:
        return False
    row = res.data[0]
    if row["status"] not in ("approved", "publish_failed"):
        return False

    content = row.get("content") or {}
    metadata = row.get("metadata") or {}
    channel_id = metadata.get("slack_channel_id") or ""

    # チャンネル未指定なら種別のデフォルトを引く
    if not channel_id:
        bindings = await list_channel_bindings(supabase, row["request_type"])
        default = next((b for b in bindings if b.is_default), bindings[0] if bindings else None)
        if default:
            channel_id = default.channel_id

    if not channel_id:
        logger.warning("Slack 投稿先チャンネルが未設定: request=%s", request_id)
        supabase.table("approval_requests").update({"status": "publish_failed"}).eq("id", request_id).execute()
        _record_action(
            supabase, request_id, str(row["requester_id"]), row.get("requester_email") or "",
            "publish_failed", after_state={"error": "channel_not_configured"},
        )
        return False

    # 添付画像を Storage からダウンロード
    # attachments はアップロード履歴（追加専用）のため、エディタで削除された
    # 画像が残っている場合がある。本文HTMLに実在する画像だけを投稿対象にする。
    caption_html = content.get("caption_html") or ""
    image_bytes_list = []
    for att in content.get("attachments") or []:
        path = att.get("path")
        url = att.get("url") or ""
        if not path:
            continue
        if url and url not in caption_html:
            logger.info("本文から削除済みの添付をスキップ: %s", path)
            continue
        try:
            data = supabase.storage.from_(ATTACHMENTS_BUCKET).download(path)
            image_bytes_list.append((data, att.get("filename") or path.split("/")[-1]))
        except Exception as exc:
            logger.warning("添付ダウンロード失敗: %s (%s)", path, exc)

    types = await list_request_types(supabase, include_inactive=True)
    type_label = next((t.label for t in types if t.code == row["request_type"]), row["request_type"])
    profiles = _get_profiles(supabase, [str(row["requester_id"])])
    requester_name = _display_name(profiles.get(str(row["requester_id"])))

    result = await slack_post_service.post_approved_content(
        channel_id=channel_id,
        title=row["title"],
        caption_html=content.get("caption_html") or "",
        requester_name=requester_name,
        type_label=type_label,
        image_bytes_list=image_bytes_list,
    )

    if result["ok"]:
        supabase.table("approval_requests").update({
            "status": "published",
            "published_at": _now_iso(),
        }).eq("id", request_id).execute()
        _record_action(
            supabase, request_id, str(row["requester_id"]), row.get("requester_email") or "",
            "publish_success",
            after_state={"channel_id": channel_id, "ts": result.get("ts")},
        )
        return True

    supabase.table("approval_requests").update({"status": "publish_failed"}).eq("id", request_id).execute()
    _record_action(
        supabase, request_id, str(row["requester_id"]), row.get("requester_email") or "",
        "publish_failed",
        after_state={"channel_id": channel_id, "error": result.get("error")},
    )
    return False


async def reject_step(
    supabase: Client,
    request_id: str,
    step_id: str,
    user_id: str,
    user_email: str,
    comment: Optional[str] = None,
) -> Optional[ApprovalRequestDetail]:
    """却下する（申請全体が rejected になる）"""
    res = supabase.table("approval_requests").select("*").eq("id", request_id).execute()
    if not res.data or res.data[0]["status"] != "pending":
        return None
    row = res.data[0]

    steps_res = supabase.table("approval_steps").select("*").eq("request_id", request_id).execute()
    actionable = _actionable_steps(
        steps_res.data or [], row["approval_mode"], row.get("current_step_no") or 1
    )
    target = next(
        (s for s in actionable if str(s["id"]) == step_id and str(s["assignee_id"]) == user_id),
        None,
    )
    if not target:
        return None

    supabase.table("approval_steps").update({
        "status": "rejected",
        "acted_at": _now_iso(),
        "comment": comment,
    }).eq("id", step_id).execute()

    supabase.table("approval_requests").update({
        "status": "rejected",
        "rejected_at": _now_iso(),
    }).eq("id", request_id).execute()

    on_behalf = (
        str(target["original_assignee_id"])
        if str(target["original_assignee_id"]) != user_id else None
    )
    _record_action(
        supabase, request_id, user_id, user_email, "reject",
        step_id=step_id, on_behalf_of_id=on_behalf,
        before_state={"status": "pending"},
        after_state={"status": "rejected"},
        comment=comment,
    )
    return await get_request(supabase, request_id, user_id)


async def return_to_requester(
    supabase: Client,
    request_id: str,
    step_id: str,
    user_id: str,
    user_email: str,
    comment: Optional[str] = None,
) -> Optional[ApprovalRequestDetail]:
    """起票者へ差し戻す（draft に戻り再編集→再申請できる）"""
    res = supabase.table("approval_requests").select("*").eq("id", request_id).execute()
    if not res.data or res.data[0]["status"] != "pending":
        return None
    row = res.data[0]

    steps_res = supabase.table("approval_steps").select("*").eq("request_id", request_id).execute()
    actionable = _actionable_steps(
        steps_res.data or [], row["approval_mode"], row.get("current_step_no") or 1
    )
    target = next(
        (s for s in actionable if str(s["id"]) == step_id and str(s["assignee_id"]) == user_id),
        None,
    )
    if not target:
        return None

    supabase.table("approval_requests").update({
        "status": "draft",
        "current_step_no": 1,
    }).eq("id", request_id).execute()

    _record_action(
        supabase, request_id, user_id, user_email, "return_to_requester",
        step_id=step_id, comment=comment,
        before_state={"status": "pending"},
        after_state={"status": "draft"},
    )
    return await get_request(supabase, request_id, user_id)


async def cancel_request(
    supabase: Client,
    request_id: str,
    user_id: str,
    user_email: str,
) -> Optional[ApprovalRequestDetail]:
    """起票者による取下げ（draft / pending のみ）"""
    res = supabase.table("approval_requests").select("*").eq("id", request_id).execute()
    if not res.data:
        return None
    row = res.data[0]
    if str(row["requester_id"]) != user_id or row["status"] not in ("draft", "pending"):
        return None

    supabase.table("approval_requests").update({"status": "cancelled"}).eq("id", request_id).execute()
    _record_action(
        supabase, request_id, user_id, user_email, "cancel",
        before_state={"status": row["status"]},
        after_state={"status": "cancelled"},
    )
    return await get_request(supabase, request_id, user_id)


async def reassign_step(
    supabase: Client,
    request_id: str,
    step_id: str,
    new_assignee_id: str,
    actor_id: str,
    actor_email: str,
    comment: Optional[str] = None,
) -> Optional[ApprovalRequestDetail]:
    """承認者を差し替える（admin/executive のみ — 権限チェックは endpoint 側）"""
    step_res = supabase.table("approval_steps").select("*").eq("id", step_id).execute()
    if not step_res.data:
        return None
    step = step_res.data[0]
    if str(step["request_id"]) != request_id or step["status"] != "pending":
        return None

    profiles = _get_profiles(supabase, [new_assignee_id])
    new_email = (profiles.get(new_assignee_id) or {}).get("email") or ""

    supabase.table("approval_steps").update({
        "assignee_id": new_assignee_id,
        "assignee_email": new_email,
        "notified_at": None,  # 新担当に改めて通知するためリセット
    }).eq("id", step_id).execute()

    _record_action(
        supabase, request_id, actor_id, actor_email, "reassign",
        step_id=step_id, comment=comment,
        before_state={"assignee_id": str(step["assignee_id"])},
        after_state={"assignee_id": new_assignee_id},
    )

    await _notify_current_approvers(supabase, request_id)
    return await get_request(supabase, request_id, actor_id)


# =============================================================================
# 代理承認設定
# =============================================================================

async def list_delegates(
    supabase: Client, user_id: Optional[str] = None
) -> List[ApprovalDelegate]:
    query = supabase.table("approval_delegates").select("*").order("starts_at", desc=True)
    if user_id:
        query = query.eq("user_id", user_id)
    res = query.execute()
    rows = res.data or []
    profiles = _get_profiles(
        supabase,
        [str(r["user_id"]) for r in rows] + [str(r["delegate_id"]) for r in rows],
    )
    return [
        ApprovalDelegate(
            id=str(r["id"]),
            user_id=str(r["user_id"]),
            user_email=(profiles.get(str(r["user_id"])) or {}).get("email"),
            user_name=_display_name(profiles.get(str(r["user_id"]))),
            delegate_id=str(r["delegate_id"]),
            delegate_email=(profiles.get(str(r["delegate_id"])) or {}).get("email"),
            delegate_name=_display_name(profiles.get(str(r["delegate_id"]))),
            starts_at=r["starts_at"],
            ends_at=r["ends_at"],
            note=r.get("note"),
            created_at=r["created_at"],
        )
        for r in rows
    ]


async def create_delegate(
    supabase: Client, data: ApprovalDelegateCreate, requester_user_id: str
) -> Optional[ApprovalDelegate]:
    record = {
        "user_id": data.user_id or requester_user_id,
        "delegate_id": data.delegate_id,
        "starts_at": data.starts_at.isoformat(),
        "ends_at": data.ends_at.isoformat(),
        "note": data.note,
    }
    res = supabase.table("approval_delegates").insert(record).execute()
    if not res.data:
        return None
    delegates = await list_delegates(supabase, record["user_id"])
    created_id = str(res.data[0]["id"])
    return next((d for d in delegates if d.id == created_id), None)


async def delete_delegate(supabase: Client, delegate_id: str, user_id: str, is_admin: bool) -> bool:
    res = supabase.table("approval_delegates").select("*").eq("id", delegate_id).execute()
    if not res.data:
        return False
    if not is_admin and str(res.data[0]["user_id"]) != user_id:
        return False
    supabase.table("approval_delegates").delete().eq("id", delegate_id).execute()
    return True


# =============================================================================
# 添付アップロード
# =============================================================================

async def upload_attachment(
    supabase: Client,
    file_bytes: bytes,
    filename: str,
    content_type: str,
) -> Optional[Dict[str, str]]:
    """添付画像を Storage にアップロードし、公開URLを返す"""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "png"
    if ext not in ("png", "jpg", "jpeg", "gif", "webp"):
        return None
    path = f"uploads/{uuid_module.uuid4()}.{ext}"
    try:
        supabase.storage.from_(ATTACHMENTS_BUCKET).upload(
            path, file_bytes, {"content-type": content_type or "image/png"}
        )
        url = supabase.storage.from_(ATTACHMENTS_BUCKET).get_public_url(path)
        # get_public_url が末尾に ? を付けるバージョンがあるため整形
        url = url.rstrip("?")
        return {"path": path, "url": url, "filename": filename}
    except Exception as exc:
        logger.error("添付アップロード失敗: %s", exc)
        return None
