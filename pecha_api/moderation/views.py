from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from starlette import status

from pecha_api.moderation.enums import GroupReportKind
from pecha_api.moderation.response_models import GroupReportsResponse
from pecha_api.moderation.service import list_group_reports_service
from pecha_api.plans.auth.cms_auth_deps import get_cms_author_token

group_reports_router = APIRouter(
    prefix="/groups/{group_id}/reports",
    tags=["Group Moderation Reports"],
)


@group_reports_router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=GroupReportsResponse,
)
def get_group_reports(
    group_id: UUID,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    kind: Annotated[Optional[GroupReportKind], Query()] = None,
    reason: Annotated[Optional[str], Query()] = None,
    resolved: Annotated[Optional[bool], Query()] = None,
    token: Annotated[str, Depends(get_cms_author_token)] = "",
):
    """A group's moderation queue, newest first: chat message reports and post
    and comment reports together. Group owner/admin, or platform staff.

    Filter with `kind` (CHAT_MESSAGE, POST, COMMENT) to see one sort, and with
    `reason` or `resolved` as on the platform-wide CMS queue."""
    return list_group_reports_service(
        token=token,
        group_id=group_id,
        skip=skip,
        limit=limit,
        kind=kind,
        reason=reason,
        resolved=resolved,
    )
