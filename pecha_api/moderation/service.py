"""A group's combined moderation queue.

Chat message reports and post/comment reports live in separate tables, so the
two are queried independently and merged here. `kind` narrows to one of them,
which skips the other query entirely.
"""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session
from starlette import status

from pecha_api.chat.models import ChatMessageReport
from pecha_api.chat.repository import list_reports as list_chat_reports
from pecha_api.db.database import SessionLocal
from pecha_api.group_posts.report_models import GroupPostReport
from pecha_api.group_posts.report_repository import list_group_post_reports
from pecha_api.moderation.enums import GroupReportKind
from pecha_api.moderation.response_models import (
    GroupReportDTO,
    GroupReportsResponse,
    GroupReportUserDTO,
)
from pecha_api.plans.authors.plan_authors_model import Author
from pecha_api.plans.authors.plan_authors_service import validate_and_extract_author_details
from pecha_api.plans.groups.groups_enums import AuthorGroupMemberRole
from pecha_api.plans.shared.permissions import (
    is_reviewer,
    is_super_admin,
    require_group_member,
)
from pecha_api.users.users_models import Users

# Moderating a group is an owner/admin job - an AUTHOR can post but does not
# review reports, and a VIEWER certainly does not.
_MODERATOR_ROLES = {AuthorGroupMemberRole.OWNER, AuthorGroupMemberRole.ADMIN}


def _require_group_moderator(db: Session, group_id: UUID, author: Author) -> None:
    if is_super_admin(author) or is_reviewer(author):
        return
    require_group_member(
        db=db, group_id=group_id, author=author, allowed_roles=_MODERATOR_ROLES
    )


def _user_dto(user: Optional[Users]) -> Optional[GroupReportUserDTO]:
    if user is None:
        return None
    return GroupReportUserDTO(
        id=user.id,
        username=user.username,
        firstname=user.firstname,
        lastname=user.lastname,
    )


def _isoformat(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _chat_dto(report: ChatMessageReport) -> GroupReportDTO:
    message = report.message
    room = report.room or (message.room if message else None)
    return GroupReportDTO(
        id=report.id,
        kind=GroupReportKind.CHAT_MESSAGE,
        reason=report.reason,
        description=report.description,
        source=report.source,
        content_text=report.message_text or (message.body if message else None),
        message_id=report.message_id,
        room_id=room.id if room else report.room_id,
        room_name=room.name if room else None,
        reporter=_user_dto(report.reporter),
        reported_user=_user_dto(
            report.reported_user or (message.sender if message else None)
        ),
        created_at=_isoformat(report.created_at) or "",
        resolved_at=_isoformat(report.resolved_at),
    )


def _post_dto(report: GroupPostReport) -> GroupReportDTO:
    return GroupReportDTO(
        id=report.id,
        kind=GroupReportKind(report.target_type),
        reason=report.reason,
        description=report.description,
        source="MANUAL",
        content_text=report.content_text,
        post_id=report.post_id,
        comment_id=report.comment_id,
        reporter=_user_dto(report.reporter),
        reported_user=_user_dto(report.reported_user),
        created_at=_isoformat(report.created_at) or "",
        resolved_at=_isoformat(report.resolved_at),
    )


def list_group_reports_service(
    token: str,
    group_id: UUID,
    skip: int = 0,
    limit: int = 20,
    kind: Optional[GroupReportKind] = None,
    reason: Optional[str] = None,
    resolved: Optional[bool] = None,
) -> GroupReportsResponse:
    author = validate_and_extract_author_details(token=token)

    wants_chat = kind is None or kind == GroupReportKind.CHAT_MESSAGE
    wants_posts = kind is None or kind in (
        GroupReportKind.POST,
        GroupReportKind.COMMENT,
    )

    with SessionLocal() as db:
        _require_group_moderator(db=db, group_id=group_id, author=author)

        dtos: List[GroupReportDTO] = []
        total = 0

        # Each side is read from the start up to skip+limit, because a row
        # from either table can land anywhere in the merged order. Fine for a
        # per-group queue; it would need a UNION view to page deeply.
        window = skip + limit

        if wants_chat:
            chat_rows, chat_total = list_chat_reports(
                db=db,
                group_id=group_id,
                skip=0,
                limit=window,
                reason=reason,
                resolved=resolved,
            )
            dtos.extend(_chat_dto(row) for row in chat_rows)
            total += chat_total

        if wants_posts:
            post_rows, post_total = list_group_post_reports(
                db=db,
                group_id=group_id,
                skip=0,
                limit=window,
                target_type=kind.value if kind in (
                    GroupReportKind.POST,
                    GroupReportKind.COMMENT,
                ) else None,
                reason=reason,
                resolved=resolved,
            )
            dtos.extend(_post_dto(row) for row in post_rows)
            total += post_total

    dtos.sort(key=lambda report: report.created_at, reverse=True)
    return GroupReportsResponse(
        reports=dtos[skip : skip + limit],
        skip=skip,
        limit=limit,
        total=total,
    )
