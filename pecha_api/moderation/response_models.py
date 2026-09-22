from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel

from pecha_api.moderation.enums import GroupReportKind


class GroupReportUserDTO(BaseModel):
    id: UUID
    username: Optional[str] = None
    firstname: Optional[str] = None
    lastname: Optional[str] = None


class GroupReportDTO(BaseModel):
    """One report in a group's queue, from either source.

    The id-bearing fields are sparse by design: a CHAT_MESSAGE report fills
    message_id/room_id, a POST or COMMENT report fills post_id/comment_id.
    `kind` says which to read. `content_text` always carries the reported text,
    including where the content itself has since been deleted.
    """

    id: UUID
    kind: GroupReportKind
    reason: str
    description: Optional[str] = None
    # MANUAL or AUTOMATIC; post and comment reports are always MANUAL today.
    source: str
    content_text: Optional[str] = None
    post_id: Optional[UUID] = None
    comment_id: Optional[UUID] = None
    message_id: Optional[UUID] = None
    room_id: Optional[UUID] = None
    room_name: Optional[str] = None
    # None for AUTOMATIC chat reports, which no member filed.
    reporter: Optional[GroupReportUserDTO] = None
    reported_user: Optional[GroupReportUserDTO] = None
    created_at: str
    resolved_at: Optional[str] = None


class GroupReportsResponse(BaseModel):
    reports: List[GroupReportDTO]
    skip: int
    limit: int
    total: int
