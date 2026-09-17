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
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from supabase import Client

from app.schemas.approval import (
    ApprovalDashboardDeptRow,
    ApprovalDashboardRequestRow,
    ApprovalDashboardResponse,
    ApprovalViewer,
    PurgeAttachmentsResult,
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

# 閲覧者（押印担当）が案件を閲覧・確認できるステータス（承認完了後のみ）
VIEWER_VISIBLE_STATUSES = ("approved", "published", "publish_failed")


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
            .select("id, email, display_name, org_departments(name)")
            .in_("id", ids)
            .execute()
        )
        return {str(r["id"]): r for r in (res.data or [])}
    except Exception as exc:
        logger.warning("user_profiles 取得失敗: %s", exc)
        return {}


def _department_name(profile: Optional[Dict[str, Any]]) -> Optional[str]:
    """プロファイル行から部署名を取り出す（未設定は None）"""
    if not profile:
        return None
    dept = profile.get("org_departments")
    if isinstance(dept, dict):
        return dept.get("name")
    return None


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
        assignee_department=_department_name(profiles.get(str(row["assignee_id"]))),
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

def _build_user_candidates(rows: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """候補ユーザー行を部署ごとにグループ表示しやすい形に整形する

    - display_name: 名前（役職）
    - department: 部署名（未設定は「部署未設定」として末尾）
    - 並び順: 部署の表示順 → 部署名 → 名前
    """
    result = []
    for r in rows:
        dept = r.get("org_departments") or {}
        dept_name = dept.get("name") if isinstance(dept, dict) else None
        dept_order = dept.get("display_order") if isinstance(dept, dict) else None
        position = r.get("position")
        result.append({
            "id": str(r["id"]),
            "email": r.get("email") or "",
            "display_name": _display_name(r) + (f"（{position}）" if position else ""),
            "department": dept_name or "部署未設定",
            "_order": dept_order if dept_order is not None else 99999,
        })
    result.sort(key=lambda x: (x["_order"], x["department"], x["display_name"]))
    for r in result:
        r.pop("_order", None)
    return result


async def list_assignable_users(supabase: Client) -> List[Dict[str, str]]:
    """承認者として指定可能なユーザーの軽量一覧

    承認権限（user_profiles.can_approve）を持つ有効ユーザーのみ返す。
    部署ごとにグループ表示できるよう department を添え、部署順で返す。
    """
    try:
        res = (
            supabase.table("user_profiles")
            .select("id, email, display_name, is_active, position, org_departments(name, display_order)")
            .eq("is_active", True)
            .eq("can_approve", True)
            .order("display_name")
            .execute()
        )
        return _build_user_candidates(res.data or [])
    except Exception as exc:
        logger.warning("承認者候補の取得に失敗: %s", exc)
        return []


async def _get_viewer_context(supabase: Client, user_id: str) -> Dict[str, Any]:
    """稟議の閲覧スコープ判定に使うユーザー属性を取得する

    - role admin/executive または approval_view_all=true → 全社閲覧
    - それ以外 → 自部署（org_department_id）の稟議のみ
    """
    try:
        res = (
            supabase.table("user_profiles")
            .select("role, org_department_id, approval_view_all")
            .eq("id", user_id)
            .execute()
        )
        row = (res.data or [{}])[0]
        role = row.get("role") or "user"
        view_all = role in ("admin", "executive") or bool(row.get("approval_view_all"))
        return {
            "role": role,
            "view_all": view_all,
            "org_department_id": row.get("org_department_id"),
        }
    except Exception as exc:
        logger.warning("閲覧コンテキストの取得に失敗: %s", exc)
        return {"role": "user", "view_all": False, "org_department_id": None}


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
    # 申請者の部署をスタンプ（閲覧スコープ判定に使用）
    requester_ctx = await _get_viewer_context(supabase, user_id)
    record = {
        "request_type": data.request_type,
        "title": data.title or "(無題)",
        "status": "draft",
        "approval_mode": data.approval_mode or "sequential",
        "content": data.content,
        "metadata": data.metadata,
        "requester_id": user_id,
        "requester_email": user_email,
        "org_department_id": requester_ctx["org_department_id"],
    }
    res = supabase.table("approval_requests").insert(record).execute()
    if not res.data:
        return None
    request_id = str(res.data[0]["id"])

    # 下書き段階でも承認者指定があれば steps を作っておく
    if data.approvers:
        await _replace_steps(supabase, request_id, data.approvers)

    # 閲覧者
    if data.viewers:
        await _replace_viewers(supabase, request_id, data.viewers)

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

    if data.viewers is not None:
        await _replace_viewers(supabase, request_id, data.viewers)

    return await get_request(supabase, request_id, user_id)


async def _replace_steps(supabase: Client, request_id: str, approvers: List[ApproverInput]) -> None:
    """steps を作り直す（draft 段階のみ呼ぶこと）"""
    supabase.table("approval_steps").delete().eq("request_id", request_id).execute()
    if not approvers:
        return
    # step_no を 1..k の連番に正規化する。同じ step_no を持つ承認者は
    # 「同時承認グループ」（全員の承認でそのステップ完了）として扱われる。
    distinct_steps = sorted({a.step_no for a in approvers})
    step_map = {no: i + 1 for i, no in enumerate(distinct_steps)}
    profiles = _get_profiles(supabase, [a.assignee_id for a in approvers])
    rows = []
    for a in approvers:
        profile = profiles.get(a.assignee_id, {})
        rows.append({
            "request_id": request_id,
            "step_no": step_map[a.step_no],
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
        all  : 閲覧範囲内の申請
               （admin/executive/全社閲覧権限者 → 全件、
                それ以外 → 自部署の申請＋自分が起票した申請）
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

    # 閲覧者として未確認（未押印）の案件
    my_ack_res = (
        supabase.table("approval_viewers")
        .select("request_id")
        .eq("viewer_id", user_id)
        .is_("acknowledged_at", "null")
        .execute()
    )
    my_unacked_ids = {str(v["request_id"]) for v in (my_ack_res.data or [])}

    if tab == "todo":
        todo_ids = my_pending_ids | my_unacked_ids
        if not todo_ids:
            return ApprovalRequestListResponse(requests=[], total=0)
        query = (
            supabase.table("approval_requests")
            .select("*")
            .in_("id", list(todo_ids))
            .neq("status", "draft")
            .is_("soft_deleted_at", "null")
        )
    elif tab == "all":
        viewer = await _get_viewer_context(supabase, user_id)
        query = (
            supabase.table("approval_requests")
            .select("*")
            .is_("soft_deleted_at", "null")
        )
        if not viewer["view_all"]:
            # 自部署の申請＋自分が起票した申請のみ（部署未設定なら自分の分のみ）
            dept_id = viewer["org_department_id"]
            if dept_id:
                query = query.or_(
                    f"org_department_id.eq.{dept_id},requester_id.eq.{user_id}"
                )
            else:
                query = query.eq("requester_id", user_id)
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
    # （閲覧者として未確認の案件は承認順に関係なく残す）
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
            if (
                str(r["id"]) in my_unacked_ids
                and r["status"] in VIEWER_VISIBLE_STATUSES
            )
            or (
                str(r["id"]) in my_pending_ids
                and r["status"] == "pending"
                and (
                    r["approval_mode"] != "sequential"
                    or my_step_no.get(str(r["id"])) == (r.get("current_step_no") or 1)
                )
            )
        ]

    types = await list_request_types(supabase, include_inactive=True)
    type_labels = {t.code: t.label for t in types}
    profiles = _get_profiles(supabase, [str(r["requester_id"]) for r in rows])

    summaries = [_row_to_summary(r, type_labels, profiles, my_pending_ids) for r in rows]
    return ApprovalRequestListResponse(requests=summaries, total=len(summaries))


async def _replace_viewers(
    supabase: Client,
    request_id: str,
    viewer_ids: List[str],
) -> None:
    """閲覧者を指定リストに揃える（既存の押印済みレコードは保持する）"""
    try:
        existing = (
            supabase.table("approval_viewers")
            .select("id, viewer_id")
            .eq("request_id", request_id)
            .execute()
        ).data or []
        existing_ids = {str(v["viewer_id"]) for v in existing}
        target_ids = {str(v) for v in viewer_ids if v}

        removed = existing_ids - target_ids
        if removed:
            supabase.table("approval_viewers").delete().eq(
                "request_id", request_id
            ).in_("viewer_id", list(removed)).execute()

        added = target_ids - existing_ids
        if added:
            profiles = _get_profiles(supabase, list(added))
            supabase.table("approval_viewers").insert([
                {
                    "request_id": request_id,
                    "viewer_id": vid,
                    "viewer_email": (profiles.get(vid) or {}).get("email"),
                }
                for vid in added
            ]).execute()
    except Exception as exc:
        logger.warning("閲覧者の更新に失敗: %s", exc)


async def acknowledge_request(
    supabase: Client,
    request_id: str,
    user_id: str,
    user_email: str,
) -> bool:
    """閲覧者の確認（押印）を記録する（承認完了後のみ）"""
    req_res = (
        supabase.table("approval_requests")
        .select("status")
        .eq("id", request_id)
        .execute()
    )
    if not req_res.data or req_res.data[0]["status"] not in VIEWER_VISIBLE_STATUSES:
        return False
    res = (
        supabase.table("approval_viewers")
        .select("id, acknowledged_at")
        .eq("request_id", request_id)
        .eq("viewer_id", user_id)
        .execute()
    )
    if not res.data:
        return False
    row = res.data[0]
    if row.get("acknowledged_at"):
        return True  # 既に押印済み
    supabase.table("approval_viewers").update(
        {"acknowledged_at": _now_iso()}
    ).eq("id", row["id"]).execute()
    _record_action(
        supabase, request_id, user_id, user_email, "viewer_ack",
        after_state={"acknowledged": True},
        comment="閲覧者として内容を確認",
    )
    return True


async def delete_request(
    supabase: Client,
    request_id: str,
    user_id: str,
    user_email: str,
    role: str,
) -> Optional[str]:
    """案件を削除（ソフトデリート）する

    - 起票者本人: 自分の案件（承認進行中 pending を除く）を削除可能
    - admin / executive（上席）: 他人の案件も削除可能（pending含む）
    戻り値: None=成功, それ以外はエラーメッセージ
    """
    res = supabase.table("approval_requests").select(
        "id, requester_id, status, title, soft_deleted_at"
    ).eq("id", request_id).execute()
    if not res.data:
        return "案件が見つかりません"
    row = res.data[0]
    if row.get("soft_deleted_at"):
        return None  # 既に削除済み

    is_privileged = role in ("admin", "executive")
    is_requester = str(row["requester_id"]) == user_id
    if not is_privileged:
        if not is_requester:
            return "他のユーザーの案件は削除できません"
        if row["status"] == "pending":
            return "承認進行中の案件は削除できません（先に取下げてください）"

    supabase.table("approval_requests").update(
        {"soft_deleted_at": _now_iso()}
    ).eq("id", request_id).execute()
    _record_action(
        supabase, request_id, user_id, user_email, "delete",
        before_state={"status": row["status"], "title": row.get("title")},
        comment="上席権限による削除" if (is_privileged and not is_requester) else "起票者による削除",
    )
    return None


async def count_pending_for_user(supabase: Client, user_id: str) -> int:
    """自分にアクションが回ってきている件数（サイドバーバッジ用）"""
    result = await list_requests(supabase, user_id, tab="todo")
    return result.total


async def get_request(
    supabase: Client,
    request_id: str,
    user_id: str,
) -> Optional[ApprovalRequestDetail]:
    """詳細取得（ステップ・監査履歴込み）

    閲覧できるのは以下のいずれか:
    - 申請者本人 / 承認ライン上の担当者
    - admin・executive・稟議全社閲覧権限を持つユーザー
    - 申請者と同じ部署のユーザー
    それ以外には None（=404）を返し存在も秘匿する。
    """
    res = supabase.table("approval_requests").select("*").eq("id", request_id).execute()
    if not res.data:
        return None
    row = res.data[0]
    if row.get("soft_deleted_at"):
        return None

    # 閲覧者（押印）一覧
    viewers_res = (
        supabase.table("approval_viewers")
        .select("*")
        .eq("request_id", request_id)
        .order("created_at")
        .execute()
    )
    viewer_rows = viewers_res.data or []
    is_viewer = any(str(v["viewer_id"]) == user_id for v in viewer_rows)
    # 閲覧者としての閲覧は承認完了後のみ（承認中の案件は見せない）
    viewer_can_see = is_viewer and row["status"] in VIEWER_VISIBLE_STATUSES

    # 閲覧権限チェック（閲覧者は承認完了後、部署に関わらず閲覧可）
    if str(row.get("requester_id")) != user_id and not viewer_can_see:
        assignee_res = (
            supabase.table("approval_steps")
            .select("id")
            .eq("request_id", request_id)
            .eq("assignee_id", user_id)
            .limit(1)
            .execute()
        )
        is_assignee = bool(assignee_res.data)
        if not is_assignee:
            viewer = await _get_viewer_context(supabase, user_id)
            same_dept = (
                viewer["org_department_id"] is not None
                and str(row.get("org_department_id") or "") == str(viewer["org_department_id"])
            )
            if not viewer["view_all"] and not same_dept:
                return None

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
        + [str(v["viewer_id"]) for v in viewer_rows]
    )
    profiles = _get_profiles(supabase, all_user_ids)

    types = await list_request_types(supabase, include_inactive=True)
    type_labels = {t.code: t.label for t in types}

    actionable = _actionable_steps(step_rows, row["approval_mode"], row.get("current_step_no") or 1)
    can_act = row["status"] == "pending" and any(
        str(s["assignee_id"]) == user_id for s in actionable
    )
    can_edit = str(row["requester_id"]) == user_id and row["status"] == "draft"

    # 閲覧者の押印可否・削除可否
    my_viewer_row = next((v for v in viewer_rows if str(v["viewer_id"]) == user_id), None)
    can_ack = (
        my_viewer_row is not None
        and not my_viewer_row.get("acknowledged_at")
        and row["status"] in VIEWER_VISIBLE_STATUSES
    )
    viewer_ctx = await _get_viewer_context(supabase, user_id)
    is_privileged = viewer_ctx["role"] in ("admin", "executive")
    can_delete = is_privileged or (
        str(row["requester_id"]) == user_id and row["status"] != "pending"
    )

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
        viewers=[
            ApprovalViewer(
                id=str(v["id"]),
                viewer_id=str(v["viewer_id"]),
                viewer_email=v.get("viewer_email") or "",
                viewer_name=_display_name(profiles.get(str(v["viewer_id"]))),
                acknowledged_at=v.get("acknowledged_at"),
            )
            for v in viewer_rows
        ],
        can_ack=can_ack,
        can_delete=can_delete,
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

    # 内容を確定（部署は申請時点の申請者の所属で最新化する）
    requester_ctx = await _get_viewer_context(supabase, user_id)
    supabase.table("approval_requests").update({
        "title": data.title,
        "content": data.content,
        "metadata": data.metadata,
        "approval_mode": data.approval_mode,
        "status": "pending",
        "current_step_no": 1,
        "org_department_id": requester_ctx["org_department_id"],
        "submitted_at": _now_iso(),
        "rejected_at": None,
    }).eq("id", request_id).execute()

    # ステップを作り直し（再申請時も全リセット）
    await _replace_steps(supabase, request_id, data.approvers)

    # 閲覧者を確定
    await _replace_viewers(supabase, request_id, data.viewers)

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
        # 通知済みならスキップ（同時承認グループの途中承認時の重複送信防止）
        if step.get("notified_at"):
            continue
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


# =============================================================================
# ダッシュボード
# =============================================================================

PHASE_LABELS = {
    "draft": "起票中",
    "pending": "承認待ち",
    "approved": "承認済み",
    "published": "承認済み",
    "rejected": "却下",
    "cancelled": "取下げ",
    "publish_failed": "承認済み",
}


async def list_viewer_candidates(supabase: Client) -> List[Dict[str, str]]:
    """閲覧者として指定可能なユーザー一覧（承認権限は不要・有効ユーザー全員）

    部署ごとにグループ表示できるよう department を添え、部署順で返す。
    """
    try:
        res = (
            supabase.table("user_profiles")
            .select("id, email, display_name, is_active, position, org_departments(name, display_order)")
            .eq("is_active", True)
            .order("display_name")
            .execute()
        )
        return _build_user_candidates(res.data or [])
    except Exception as exc:
        logger.warning("閲覧者候補の取得に失敗: %s", exc)
        return []


async def get_dashboard(
    supabase: Client,
    user_id: str,
    limit: int = 300,
) -> ApprovalDashboardResponse:
    """承認ワークフローのダッシュボード

    - 部署別×フェーズ別の件数
    - 案件一覧（起票者・部署・種別・フェーズ）
    閲覧スコープは一覧と同じ（全社閲覧権限がなければ自部署＋自分の起票分）。
    """
    viewer = await _get_viewer_context(supabase, user_id)
    query = (
        supabase.table("approval_requests")
        .select("*")
        .is_("soft_deleted_at", "null")
    )
    if not viewer["view_all"]:
        dept_id = viewer["org_department_id"]
        if dept_id:
            query = query.or_(
                f"org_department_id.eq.{dept_id},requester_id.eq.{user_id}"
            )
        else:
            query = query.eq("requester_id", user_id)
    rows = (query.order("created_at", desc=True).limit(limit).execute()).data or []

    # 部署名・申請者名・種別ラベルを解決
    dept_res = supabase.table("org_departments").select("id, name").execute()
    dept_names = {str(d["id"]): d["name"] for d in (dept_res.data or [])}
    profiles = _get_profiles(supabase, [str(r["requester_id"]) for r in rows])
    types = await list_request_types(supabase, include_inactive=True)
    type_labels = {t.code: t.label for t in types}

    # 部署別集計
    dept_agg: Dict[str, Dict[str, int]] = {}
    request_rows = []
    for r in rows:
        dept_name = dept_names.get(str(r.get("org_department_id") or ""), "部署未設定")
        agg = dept_agg.setdefault(
            dept_name, {"draft": 0, "pending": 0, "approved": 0, "rejected": 0, "total": 0}
        )
        status = r["status"]
        if status == "draft":
            agg["draft"] += 1
        elif status == "pending":
            agg["pending"] += 1
        elif status in ("approved", "published", "publish_failed"):
            agg["approved"] += 1
        else:
            agg["rejected"] += 1
        agg["total"] += 1

        request_rows.append(ApprovalDashboardRequestRow(
            id=str(r["id"]),
            title=r.get("title") or "(無題)",
            request_type_label=type_labels.get(r["request_type"], r["request_type"]),
            status=status,
            phase=PHASE_LABELS.get(status, status),
            requester_name=_display_name(profiles.get(str(r["requester_id"]))),
            department_name=dept_name,
            submitted_at=r.get("submitted_at"),
            created_at=r.get("created_at"),
        ))

    by_department = [
        ApprovalDashboardDeptRow(department_name=name, **agg)
        for name, agg in sorted(dept_agg.items(), key=lambda x: -x[1]["total"])
    ]

    return ApprovalDashboardResponse(
        by_department=by_department,
        requests=request_rows,
        total=len(request_rows),
    )


# =============================================================================
# 添付画像の保存期限パージ（DB容量対策）
# =============================================================================

PURGED_IMAGE_PLACEHOLDER = (
    '<div style="border:1px dashed #ccc; padding:8px; color:#888; font-size:12px;">'
    '[添付画像は保存期間経過のため削除されました]</div>'
)


async def purge_old_attachments(
    supabase: Client,
    retention_days: int = 90,
    dry_run: bool = False,
) -> PurgeAttachmentsResult:
    """保存期間を過ぎた稟議の添付画像を Storage から削除する

    - 稟議本体（テキスト・承認履歴）は残す
    - 本文中の <img> タグは削除告知プレースホルダに置換する
    - 基準日: submitted_at（未申請の下書きは created_at）
    """
    import re as _re

    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()

    rows = (
        supabase.table("approval_requests")
        .select("id, requester_id, requester_email, content, metadata, submitted_at, created_at")
        .lt("created_at", cutoff)
        .execute()
    ).data or []

    purged_requests = 0
    deleted_files = 0

    for r in rows:
        ref_date = r.get("submitted_at") or r.get("created_at")
        if not ref_date or str(ref_date) >= cutoff:
            continue
        metadata = r.get("metadata") or {}
        if metadata.get("attachments_purged_at"):
            continue
        content = r.get("content") or {}
        attachments = content.get("attachments") or []
        caption_html = content.get("caption_html") or ""
        has_images = bool(attachments) or "<img" in caption_html
        if not has_images:
            continue

        paths = [a["path"] for a in attachments if a.get("path")]
        if dry_run:
            purged_requests += 1
            deleted_files += len(paths)
            continue

        # Storage から削除
        if paths:
            try:
                supabase.storage.from_(ATTACHMENTS_BUCKET).remove(paths)
                deleted_files += len(paths)
            except Exception as exc:
                logger.warning("添付削除失敗 request=%s: %s", r["id"], exc)

        # 本文の画像をプレースホルダに置換し、添付リストを空にする
        new_html = _re.sub(r"<img\b[^>]*>", PURGED_IMAGE_PLACEHOLDER, caption_html)
        new_content = {**content, "caption_html": new_html, "attachments": []}
        new_metadata = {
            **metadata,
            "attachments_purged_at": _now_iso(),
            "purged_file_count": len(paths),
        }
        supabase.table("approval_requests").update({
            "content": new_content,
            "metadata": new_metadata,
        }).eq("id", r["id"]).execute()

        _record_action(
            supabase, str(r["id"]), str(r["requester_id"]),
            r.get("requester_email") or "", "attachments_purged",
            after_state={"purged_file_count": len(paths)},
            comment=f"保存期間（{retention_days}日）経過による添付画像の自動削除",
        )
        purged_requests += 1

    return PurgeAttachmentsResult(
        retention_days=retention_days,
        dry_run=dry_run,
        purged_requests=purged_requests,
        deleted_files=deleted_files,
    )


# =============================================================================
# 起票担当者の変更（編集途中の引き継ぎ）
# =============================================================================

async def transfer_requester(
    supabase: Client,
    request_id: str,
    new_requester_id: str,
    actor_id: str,
    actor_email: str,
    actor_role: str,
) -> Optional[str]:
    """下書き（差戻し済み含む）の起票担当者を変更する

    - 現在の起票者本人、または admin/executive が実行可能
    - draft 状態のみ（承認進行中・完了後の案件は担当変更不可）
    戻り値: None=成功, それ以外はエラーメッセージ
    """
    res = supabase.table("approval_requests").select(
        "id, requester_id, requester_email, status, title, soft_deleted_at"
    ).eq("id", request_id).execute()
    if not res.data:
        return "案件が見つかりません"
    row = res.data[0]
    if row.get("soft_deleted_at"):
        return "削除済みの案件です"
    if row["status"] != "draft":
        return "担当者を変更できるのは下書き（差戻し済み含む）の案件のみです"

    is_privileged = actor_role in ("admin", "executive")
    if str(row["requester_id"]) != actor_id and not is_privileged:
        return "担当者を変更できるのは現在の担当者本人か上席のみです"

    profiles = _get_profiles(supabase, [new_requester_id])
    new_profile = profiles.get(str(new_requester_id))
    if not new_profile:
        return "変更先のユーザーが見つかりません"

    supabase.table("approval_requests").update({
        "requester_id": new_requester_id,
        "requester_email": new_profile.get("email"),
    }).eq("id", request_id).execute()

    _record_action(
        supabase, request_id, actor_id, actor_email, "transfer_requester",
        before_state={"requester_id": str(row["requester_id"]), "requester_email": row.get("requester_email")},
        after_state={"requester_id": str(new_requester_id), "requester_email": new_profile.get("email")},
        comment=f"起票担当者を {_display_name(new_profile)} に変更",
    )
    return None


# =============================================================================
# 稟議の複製
# =============================================================================

async def duplicate_request(
    supabase: Client,
    request_id: str,
    user_id: str,
    user_email: str,
) -> Optional[ApprovalRequestDetail]:
    """既存の稟議（過去の案件・作成途中の下書きいずれも）を複製して
    自分の新しい下書きを作成する

    - 複製できるのはその案件を閲覧できるユーザー
    - 本文・種別・承認ルート・閲覧者・Slack投稿先を引き継ぐ
    - 添付画像は Storage 上でコピーし、元案件の保存期限切れの影響を受けない
    """
    source = await get_request(supabase, request_id, user_id)
    if source is None:
        return None  # 存在しない or 閲覧権限なし

    content = dict(source.content or {})
    metadata = dict(source.metadata or {})

    # 添付画像を複製（元が期限切れで消えても複製側が壊れないように）
    caption_html = content.get("caption_html") or ""
    new_attachments = []
    for att in (content.get("attachments") or []):
        old_path = att.get("path")
        old_url = att.get("url")
        if not old_path:
            continue
        ext = old_path.rsplit(".", 1)[-1] if "." in old_path else "png"
        new_path = f"uploads/{uuid_module.uuid4()}.{ext}"
        try:
            supabase.storage.from_(ATTACHMENTS_BUCKET).copy(old_path, new_path)
            new_url = supabase.storage.from_(ATTACHMENTS_BUCKET).get_public_url(new_path).rstrip("?")
            new_attachments.append({**att, "path": new_path, "url": new_url})
            if old_url:
                caption_html = caption_html.replace(old_url, new_url)
        except Exception as exc:
            logger.warning("複製時の添付コピー失敗 %s: %s", old_path, exc)
            # コピー失敗時は元URLのまま引き継ぐ
            new_attachments.append(att)

    content["caption_html"] = caption_html
    content["attachments"] = new_attachments
    # パージ済みフラグは複製には引き継がない
    metadata.pop("attachments_purged_at", None)
    metadata.pop("purged_file_count", None)

    requester_ctx = await _get_viewer_context(supabase, user_id)
    record = {
        "request_type": source.request_type,
        "title": f"{source.title}（複製）",
        "status": "draft",
        "approval_mode": source.approval_mode,
        "content": content,
        "metadata": metadata,
        "requester_id": user_id,
        "requester_email": user_email,
        "org_department_id": requester_ctx["org_department_id"],
    }
    res = supabase.table("approval_requests").insert(record).execute()
    if not res.data:
        return None
    new_id = str(res.data[0]["id"])

    # 承認ルートを引き継ぐ
    if source.steps:
        approvers = [
            ApproverInput(step_no=st.step_no, assignee_id=st.assignee_id)
            for st in sorted(source.steps, key=lambda x: (x.step_no,))
        ]
        # 同一 step_no × 承認者の重複（差替履歴等）を除去
        seen = set()
        unique_approvers = []
        for a in approvers:
            key = (a.step_no, a.assignee_id)
            if key in seen:
                continue
            seen.add(key)
            unique_approvers.append(a)
        await _replace_steps(supabase, new_id, unique_approvers)

    # 閲覧者を引き継ぐ
    if source.viewers:
        await _replace_viewers(supabase, new_id, [v.viewer_id for v in source.viewers])

    _record_action(
        supabase, new_id, user_id, user_email, "duplicate",
        after_state={"source_request_id": request_id},
        comment=f"「{source.title}」から複製",
    )
    return await get_request(supabase, new_id, user_id)
