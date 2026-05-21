"""
取締役会資料・議事録サービスモジュール

取締役会の登録・取得・更新・削除機能を提供する。
"""
from typing import Optional, List, Dict, Any

from supabase import Client

from app.schemas.board import (
    BoardMaterial,
    BoardTopic,
    BoardMeetingCreate,
    BoardMeetingUpdate,
    BoardMeeting,
    BoardMeetingListItem,
    BoardMeetingListResponse,
)


# =============================================================================
# ヘルパー関数
# =============================================================================

def _parse_materials(value: Any) -> List[BoardMaterial]:
    """JSONB配列をBoardMaterialのリストに変換する"""
    if not value:
        return []
    result: List[BoardMaterial] = []
    for item in value:
        if isinstance(item, dict):
            result.append(BoardMaterial(
                label=item.get("label", ""),
                url=item.get("url", ""),
            ))
    return result


def _parse_topics(value: Any) -> List[BoardTopic]:
    """JSONB配列をBoardTopicのリストに変換する"""
    if not value:
        return []
    result: List[BoardTopic] = []
    for item in value:
        if isinstance(item, dict):
            result.append(BoardTopic(
                category=item.get("category", ""),
                title=item.get("title", ""),
            ))
    return result


def _row_to_meeting(row: Dict[str, Any]) -> BoardMeeting:
    """DBレコードをBoardMeetingに変換する"""
    return BoardMeeting(
        id=str(row["id"]),
        meeting_date=row["meeting_date"],
        title=row["title"],
        materials=_parse_materials(row.get("materials")),
        topics=_parse_topics(row.get("topics")),
        minutes_text=row.get("minutes_text"),
        created_by=str(row["created_by"]) if row.get("created_by") else None,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# =============================================================================
# 取締役会一覧取得
# =============================================================================

async def list_meetings(supabase: Client) -> BoardMeetingListResponse:
    """
    取締役会一覧を取得する

    Args:
        supabase: Supabase管理者クライアント

    Returns:
        BoardMeetingListResponse
    """
    try:
        response = (
            supabase.table("board_meetings")
            .select("id, meeting_date, title, topics", count="exact")
            .order("meeting_date", desc=True)
            .order("created_at", desc=True)
            .execute()
        )

        meetings = [
            BoardMeetingListItem(
                id=str(row["id"]),
                meeting_date=row["meeting_date"],
                title=row["title"],
                topics=_parse_topics(row.get("topics")),
            )
            for row in (response.data or [])
        ]

        return BoardMeetingListResponse(
            meetings=meetings,
            total=response.count or len(meetings),
        )

    except Exception as e:
        raise Exception(f"取締役会一覧の取得に失敗しました: {str(e)}")


# =============================================================================
# 取締役会詳細取得
# =============================================================================

async def get_meeting(supabase: Client, meeting_id: str) -> Optional[BoardMeeting]:
    """
    IDで取締役会を取得する

    Args:
        supabase: Supabase管理者クライアント
        meeting_id: 取締役会ID

    Returns:
        BoardMeeting or None
    """
    try:
        response = (
            supabase.table("board_meetings")
            .select("*")
            .eq("id", meeting_id)
            .execute()
        )

        if not response.data:
            return None

        return _row_to_meeting(response.data[0])

    except Exception as e:
        raise Exception(f"取締役会の取得に失敗しました: {str(e)}")


# =============================================================================
# 取締役会登録
# =============================================================================

async def create_meeting(
    supabase: Client,
    data: BoardMeetingCreate,
    user_id: Optional[str] = None,
) -> BoardMeeting:
    """
    取締役会を新規登録する

    Args:
        supabase: Supabase管理者クライアント
        data: 登録データ
        user_id: 作成者ID

    Returns:
        BoardMeeting
    """
    try:
        record = {
            "meeting_date": data.meeting_date.isoformat(),
            "title": data.title,
            "materials": [m.model_dump() for m in data.materials],
            "topics": [t.model_dump() for t in data.topics],
            "minutes_text": data.minutes_text,
            "created_by": user_id,
        }

        response = supabase.table("board_meetings").insert(record).execute()

        if not response.data:
            raise Exception("取締役会の登録に失敗しました")

        return _row_to_meeting(response.data[0])

    except Exception as e:
        raise Exception(f"取締役会の登録に失敗しました: {str(e)}")


# =============================================================================
# 取締役会更新
# =============================================================================

async def update_meeting(
    supabase: Client,
    meeting_id: str,
    data: BoardMeetingUpdate,
) -> Optional[BoardMeeting]:
    """
    取締役会を更新する

    Args:
        supabase: Supabase管理者クライアント
        meeting_id: 取締役会ID
        data: 更新データ

    Returns:
        BoardMeeting or None
    """
    try:
        update_data: Dict[str, Any] = {}
        if data.meeting_date is not None:
            update_data["meeting_date"] = data.meeting_date.isoformat()
        if data.title is not None:
            update_data["title"] = data.title
        if data.materials is not None:
            update_data["materials"] = [m.model_dump() for m in data.materials]
        if data.topics is not None:
            update_data["topics"] = [t.model_dump() for t in data.topics]
        if data.minutes_text is not None:
            update_data["minutes_text"] = data.minutes_text

        if not update_data:
            return await get_meeting(supabase, meeting_id)

        response = (
            supabase.table("board_meetings")
            .update(update_data)
            .eq("id", meeting_id)
            .execute()
        )

        if not response.data:
            return None

        return _row_to_meeting(response.data[0])

    except Exception as e:
        raise Exception(f"取締役会の更新に失敗しました: {str(e)}")


# =============================================================================
# 取締役会削除
# =============================================================================

async def delete_meeting(supabase: Client, meeting_id: str) -> bool:
    """
    取締役会を削除する

    Args:
        supabase: Supabase管理者クライアント
        meeting_id: 取締役会ID

    Returns:
        bool: 削除成功
    """
    try:
        supabase.table("board_meetings").delete().eq("id", meeting_id).execute()
        return True
    except Exception as e:
        raise Exception(f"取締役会の削除に失敗しました: {str(e)}")
