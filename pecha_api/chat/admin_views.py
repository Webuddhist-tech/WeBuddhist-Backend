from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from starlette import status

from pecha_api.chat.admin_service import list_chat_message_reports_service
from pecha_api.chat.enums import ChatMessageReportReason, ChatMessageReportSource
from pecha_api.chat.response_models import AdminChatMessageReportsResponse
from pecha_api.plans.auth.cms_auth_deps import get_cms_author_token

cms_chat_reports_router = APIRouter(
    prefix="/cms/admin/chat-reports",
    tags=["CMS Admin Chat Reports"],
)


@cms_chat_reports_router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=AdminChatMessageReportsResponse,
)
def get_cms_chat_message_reports(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    source: Annotated[Optional[ChatMessageReportSource], Query()] = None,
    reason: Annotated[Optional[ChatMessageReportReason], Query()] = None,
    resolved: Annotated[Optional[bool], Query()] = None,
    group_id: Annotated[Optional[UUID], Query()] = None,
    token: Annotated[str, Depends(get_cms_author_token)] = "",
):
    """List chat moderation reports, newest first. Super admin / reviewer only.
    Covers both user-submitted (MANUAL) and system-generated (AUTOMATIC)
    reports; filter by source, reason, resolved state, or group.

    This queue stays chat-only. A group's own owners and admins read their
    chat and post reports together at GET /groups/{group_id}/reports."""
    return list_chat_message_reports_service(
        token=token,
        skip=skip,
        limit=limit,
        source=source,
        reason=reason,
        resolved=resolved,
        group_id=group_id,
    )
