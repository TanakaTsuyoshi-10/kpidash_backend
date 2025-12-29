"""
クレーム管理サービスモジュール

クレームの登録・取得・更新・削除機能を提供する。
"""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, List, Dict, Any
import math

from supabase import Client

from app.schemas.complaint import (
    ComplaintCreate,
    ComplaintUpdate,
    Complaint,
    ComplaintListItem,
    ComplaintListResponse,
    ComplaintMonthlySummary,
    ComplaintDashboardSummary,
    ComplaintTypeMaster,
    DepartmentTypeMaster,
    CustomerTypeMaster,
    ComplaintMasterDataResponse,
)


# =============================================================================
# 名前変換マップ
# =============================================================================

DEPARTMENT_TYPE_NAMES = {
    "store": "店舗",
    "ecommerce": "通販",
    "headquarters": "本社",
}

CUSTOMER_TYPE_NAMES = {
    "new": "新規顧客",
    "repeat": "リピーター",
    "unknown": "不明",
}

COMPLAINT_TYPE_NAMES = {
    "customer_service": "接客関連",
    "facility": "店舗設備関連",
    "operation": "操作方法関連",
    "product": "味・商品関連",
    "other": "その他",
}

STATUS_NAMES = {
    "in_progress": "対応中",
    "completed": "対応済",
}


# =============================================================================
# ヘルパー関数
# =============================================================================

def _to_decimal(value: Any) -> Decimal:
    """値をDecimalに変換する"""
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (ValueError, TypeError):
        return Decimal("0")


def _calculate_yoy_rate(
    current: int,
    previous: int,
) -> Optional[Decimal]:
    """前年比（変化率）を計算する"""
    if previous == 0:
        return None
    result = ((Decimal(str(current)) - Decimal(str(previous))) / Decimal(str(previous))) * 100
    return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# =============================================================================
# マスタデータ取得
# =============================================================================

async def get_master_data(supabase: Client) -> ComplaintMasterDataResponse:
    """
    クレーム関連マスタデータを取得する

    Args:
        supabase: Supabaseクライアント

    Returns:
        ComplaintMasterDataResponse
    """
    try:
        # クレーム種類
        ct_response = supabase.table("complaint_types").select("*").order("display_order").execute()
        complaint_types = [
            ComplaintTypeMaster(code=r["code"], name=r["name"], display_order=r.get("display_order", 0))
            for r in (ct_response.data or [])
        ]

        # 発生部署種類
        dt_response = supabase.table("department_types").select("*").order("display_order").execute()
        department_types = [
            DepartmentTypeMaster(code=r["code"], name=r["name"], display_order=r.get("display_order", 0))
            for r in (dt_response.data or [])
        ]

        # 顧客種類
        cust_response = supabase.table("customer_types").select("*").order("display_order").execute()
        customer_types = [
            CustomerTypeMaster(code=r["code"], name=r["name"], display_order=r.get("display_order", 0))
            for r in (cust_response.data or [])
        ]

        return ComplaintMasterDataResponse(
            complaint_types=complaint_types,
            department_types=department_types,
            customer_types=customer_types,
        )

    except Exception as e:
        raise Exception(f"マスタデータの取得に失敗しました: {str(e)}")


# =============================================================================
# クレーム登録
# =============================================================================

async def create_complaint(
    supabase: Client,
    data: ComplaintCreate,
    user_id: str,
    user_email: str,
) -> Complaint:
    """
    クレームを新規登録する

    Args:
        supabase: Supabaseクライアント
        data: 登録データ
        user_id: 作成者ID
        user_email: 作成者メールアドレス

    Returns:
        Complaint
    """
    try:
        record = {
            "incident_date": data.incident_date.isoformat(),
            "department_type": data.department_type.value,
            "segment_id": data.segment_id if data.department_type.value == "store" else None,
            "customer_type": data.customer_type.value,
            "customer_name": data.customer_name,
            "contact_info": data.contact_info,
            "complaint_type": data.complaint_type.value,
            "complaint_content": data.complaint_content,
            "responder_name": data.responder_name,
            "status": data.status.value,
            "response_summary": data.response_summary,
            "resolution_cost": float(data.resolution_cost),
            "created_by": user_id,
            "created_by_email": user_email,
        }

        response = supabase.table("complaints").insert(record).execute()

        if not response.data:
            raise Exception("クレームの登録に失敗しました")

        return await get_complaint_by_id(supabase, response.data[0]["id"])

    except Exception as e:
        raise Exception(f"クレームの登録に失敗しました: {str(e)}")


# =============================================================================
# クレーム取得
# =============================================================================

async def get_complaint_by_id(supabase: Client, complaint_id: str) -> Optional[Complaint]:
    """
    IDでクレームを取得する

    Args:
        supabase: Supabaseクライアント
        complaint_id: クレームID

    Returns:
        Complaint or None
    """
    try:
        response = supabase.table("complaints").select("*").eq("id", complaint_id).execute()

        if not response.data:
            return None

        row = response.data[0]

        # 店舗名を取得
        segment_name = None
        if row.get("segment_id"):
            seg_response = supabase.table("segments").select("name").eq("id", row["segment_id"]).execute()
            if seg_response.data:
                segment_name = seg_response.data[0]["name"]

        return Complaint(
            id=str(row["id"]),
            incident_date=row["incident_date"],
            registered_at=row["registered_at"],
            department_type=row["department_type"],
            department_type_name=DEPARTMENT_TYPE_NAMES.get(row["department_type"], row["department_type"]),
            segment_id=str(row["segment_id"]) if row.get("segment_id") else None,
            segment_name=segment_name,
            customer_type=row["customer_type"],
            customer_type_name=CUSTOMER_TYPE_NAMES.get(row["customer_type"], row["customer_type"]),
            customer_name=row.get("customer_name"),
            contact_info=row.get("contact_info"),
            complaint_type=row["complaint_type"],
            complaint_type_name=COMPLAINT_TYPE_NAMES.get(row["complaint_type"], row["complaint_type"]),
            complaint_content=row["complaint_content"],
            responder_name=row.get("responder_name"),
            status=row["status"],
            status_name=STATUS_NAMES.get(row["status"], row["status"]),
            response_summary=row.get("response_summary"),
            resolution_cost=_to_decimal(row.get("resolution_cost")),
            completed_at=row.get("completed_at"),
            created_by_email=row.get("created_by_email"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    except Exception as e:
        raise Exception(f"クレームの取得に失敗しました: {str(e)}")


# =============================================================================
# クレーム一覧取得
# =============================================================================

async def get_complaints(
    supabase: Client,
    page: int = 1,
    page_size: int = 20,
    status: Optional[str] = None,
    department_type: Optional[str] = None,
    complaint_type: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    search_query: Optional[str] = None,
) -> ComplaintListResponse:
    """
    クレーム一覧を取得する

    Args:
        supabase: Supabaseクライアント
        page: ページ番号
        page_size: 1ページあたり件数
        status: 対応状況フィルタ
        department_type: 発生部署フィルタ
        complaint_type: クレーム種類フィルタ
        start_date: 期間開始日
        end_date: 期間終了日
        search_query: 検索クエリ

    Returns:
        ComplaintListResponse
    """
    try:
        # ベースクエリ
        query = supabase.table("complaints").select("*", count="exact")

        # フィルタ適用
        if status:
            query = query.eq("status", status)
        if department_type:
            query = query.eq("department_type", department_type)
        if complaint_type:
            query = query.eq("complaint_type", complaint_type)
        if start_date:
            query = query.gte("incident_date", start_date.isoformat())
        if end_date:
            query = query.lte("incident_date", end_date.isoformat())
        if search_query:
            query = query.or_(f"complaint_content.ilike.%{search_query}%,customer_name.ilike.%{search_query}%")

        # ソートとページネーション
        offset = (page - 1) * page_size
        query = query.order("incident_date", desc=True).order("created_at", desc=True)
        query = query.range(offset, offset + page_size - 1)

        response = query.execute()

        total_count = response.count or 0
        total_pages = math.ceil(total_count / page_size) if total_count > 0 else 1

        # 店舗名を一括取得
        segment_ids = [r["segment_id"] for r in (response.data or []) if r.get("segment_id")]
        segment_map = {}
        if segment_ids:
            seg_response = supabase.table("segments").select("id, name").in_("id", segment_ids).execute()
            segment_map = {str(s["id"]): s["name"] for s in (seg_response.data or [])}

        # レスポンス構築
        complaints = []
        for row in (response.data or []):
            segment_name = segment_map.get(str(row.get("segment_id"))) if row.get("segment_id") else None
            content = row["complaint_content"]
            if len(content) > 100:
                content = content[:100] + "..."

            complaints.append(ComplaintListItem(
                id=str(row["id"]),
                incident_date=row["incident_date"],
                department_type=row["department_type"],
                department_type_name=DEPARTMENT_TYPE_NAMES.get(row["department_type"], row["department_type"]),
                segment_name=segment_name,
                customer_type_name=CUSTOMER_TYPE_NAMES.get(row["customer_type"], row["customer_type"]),
                complaint_type=row["complaint_type"],
                complaint_type_name=COMPLAINT_TYPE_NAMES.get(row["complaint_type"], row["complaint_type"]),
                complaint_content=content,
                status=row["status"],
                status_name=STATUS_NAMES.get(row["status"], row["status"]),
                responder_name=row.get("responder_name"),
                resolution_cost=_to_decimal(row.get("resolution_cost")),
                created_at=row["created_at"],
            ))

        return ComplaintListResponse(
            complaints=complaints,
            total_count=total_count,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    except Exception as e:
        raise Exception(f"クレーム一覧の取得に失敗しました: {str(e)}")


# =============================================================================
# クレーム更新
# =============================================================================

async def update_complaint(
    supabase: Client,
    complaint_id: str,
    data: ComplaintUpdate,
) -> Complaint:
    """
    クレームを更新する

    Args:
        supabase: Supabaseクライアント
        complaint_id: クレームID
        data: 更新データ

    Returns:
        Complaint
    """
    try:
        # 更新対象のフィールドのみ抽出
        update_data = {}
        if data.incident_date is not None:
            update_data["incident_date"] = data.incident_date.isoformat()
        if data.department_type is not None:
            update_data["department_type"] = data.department_type.value
        if data.segment_id is not None:
            update_data["segment_id"] = data.segment_id
        if data.customer_type is not None:
            update_data["customer_type"] = data.customer_type.value
        if data.customer_name is not None:
            update_data["customer_name"] = data.customer_name
        if data.contact_info is not None:
            update_data["contact_info"] = data.contact_info
        if data.complaint_type is not None:
            update_data["complaint_type"] = data.complaint_type.value
        if data.complaint_content is not None:
            update_data["complaint_content"] = data.complaint_content
        if data.responder_name is not None:
            update_data["responder_name"] = data.responder_name
        if data.status is not None:
            update_data["status"] = data.status.value
        if data.response_summary is not None:
            update_data["response_summary"] = data.response_summary
        if data.resolution_cost is not None:
            update_data["resolution_cost"] = float(data.resolution_cost)

        if not update_data:
            return await get_complaint_by_id(supabase, complaint_id)

        response = supabase.table("complaints").update(update_data).eq("id", complaint_id).execute()

        if not response.data:
            raise Exception("クレームの更新に失敗しました")

        return await get_complaint_by_id(supabase, complaint_id)

    except Exception as e:
        raise Exception(f"クレームの更新に失敗しました: {str(e)}")


# =============================================================================
# クレーム削除
# =============================================================================

async def delete_complaint(supabase: Client, complaint_id: str) -> bool:
    """
    クレームを削除する

    Args:
        supabase: Supabaseクライアント
        complaint_id: クレームID

    Returns:
        bool: 削除成功
    """
    try:
        response = supabase.table("complaints").delete().eq("id", complaint_id).execute()
        return True
    except Exception as e:
        raise Exception(f"クレームの削除に失敗しました: {str(e)}")


# =============================================================================
# 月別サマリー取得
# =============================================================================

async def get_monthly_summary(
    supabase: Client,
    month: date,
) -> ComplaintMonthlySummary:
    """
    月別クレームサマリーを取得する

    Args:
        supabase: Supabaseクライアント
        month: 対象月

    Returns:
        ComplaintMonthlySummary
    """
    try:
        month_str = month.replace(day=1).isoformat()

        response = supabase.table("view_complaints_monthly_summary").select("*").eq("month", month_str).execute()

        if not response.data:
            return ComplaintMonthlySummary(month=month.replace(day=1))

        row = response.data[0]
        return ComplaintMonthlySummary(
            month=row["month"],
            total_count=row.get("total_count", 0),
            completed_count=row.get("completed_count", 0),
            in_progress_count=row.get("in_progress_count", 0),
            store_count=row.get("store_count", 0),
            ecommerce_count=row.get("ecommerce_count", 0),
            headquarters_count=row.get("headquarters_count", 0),
            customer_service_count=row.get("customer_service_count", 0),
            facility_count=row.get("facility_count", 0),
            operation_count=row.get("operation_count", 0),
            product_count=row.get("product_count", 0),
            other_count=row.get("other_count", 0),
            total_resolution_cost=_to_decimal(row.get("total_resolution_cost")),
        )

    except Exception as e:
        raise Exception(f"月別サマリーの取得に失敗しました: {str(e)}")


# =============================================================================
# ダッシュボード用サマリー取得
# =============================================================================

async def get_dashboard_summary(
    supabase: Client,
    current_month: date,
) -> ComplaintDashboardSummary:
    """
    ダッシュボード用クレームサマリーを取得する

    Args:
        supabase: Supabaseクライアント
        current_month: 対象月

    Returns:
        ComplaintDashboardSummary
    """
    try:
        # 今月の件数
        current_month_start = current_month.replace(day=1)
        current_summary = await get_monthly_summary(supabase, current_month_start)

        # 先月の件数
        if current_month.month == 1:
            prev_month = date(current_month.year - 1, 12, 1)
        else:
            prev_month = date(current_month.year, current_month.month - 1, 1)
        prev_summary = await get_monthly_summary(supabase, prev_month)

        # 前年同月の件数
        prev_year_month = date(current_month.year - 1, current_month.month, 1)
        prev_year_summary = await get_monthly_summary(supabase, prev_year_month)

        # 前年比計算
        yoy_rate = _calculate_yoy_rate(current_summary.total_count, prev_year_summary.total_count)

        # 対応中件数（全期間）
        in_progress_response = supabase.table("complaints").select("id", count="exact").eq("status", "in_progress").execute()
        in_progress_count = in_progress_response.count or 0

        return ComplaintDashboardSummary(
            current_month_count=current_summary.total_count,
            previous_month_count=prev_summary.total_count,
            yoy_rate=yoy_rate,
            in_progress_count=in_progress_count,
        )

    except Exception as e:
        raise Exception(f"ダッシュボードサマリーの取得に失敗しました: {str(e)}")
