"""CMS admin services for chat moderation reports."""
from typing import Optional

from pecha_api.chat.enums import ChatMessageReportReason, ChatMessageReportSource
from pecha_api.chat.models import ChatMessageReport
from pecha_api.chat.repository import list_reports
from pecha_api.chat.response_models import (
    AdminChatMessageReportDTO,
    AdminChatMessageReportsResponse,
    AdminChatReportUserDTO,
)
from pecha_api.chat.service import _message_type_value, room_kind
from pecha_api.db.database import SessionLocal
from pecha_api.plans.authors.plan_authors_service import validate_and_extract_author_details
from pecha_api.plans.shared.permissions import require_super_admin_or_reviewer
from pecha_api.users.users_models import Users


def _build_user_dto(user: Optional[Users]) -> Optional[AdminChatReportUserDTO]:
    if user is None:
        return None
    return AdminChatReportUserDTO(
        user_id=user.id,
        email=user.email,
        firstname=user.firstname,
        lastname=user.lastname,
    )


def _build_report_dto(report: ChatMessageReport) -> AdminChatMessageReportDTO:
    message = report.message
    # Older manual reports predate the reported_user_id/room_id columns, so
    # fall back to the reported message's own sender and room.
    reported_user = report.reported_user or (message.sender if message else None)
    message_text = report.message_text or (message.body if message else None)
    room = report.room or (message.room if message else None)
    return AdminChatMessageReportDTO(
        id=report.id,
        source=report.source,
        reason=report.reason,
        description=report.description,
        message_id=report.message_id,
        message_text=message_text,
        room_id=room.id if room else report.room_id,
        room_name=room.name if room else None,
        room_kind=room_kind(room) if room else None,
        message_type=_message_type_value(message) if message else None,
        reporter=_build_user_dto(report.reporter),
        reported_user=_build_user_dto(reported_user),
        created_at=report.created_at.isoformat() if report.created_at else "",
        resolved_at=report.resolved_at.isoformat() if report.resolved_at else None,
    )


def list_chat_message_reports_service(
    token: str,
    skip: int = 0,
    limit: int = 20,
    source: Optional[ChatMessageReportSource] = None,
    reason: Optional[ChatMessageReportReason] = None,
    resolved: Optional[bool] = None,
) -> AdminChatMessageReportsResponse:
    author = validate_and_extract_author_details(token=token)
    require_super_admin_or_reviewer(author)
    with SessionLocal() as db:
        rows, total = list_reports(
            db=db,
            skip=skip,
            limit=limit,
            source=source.value if source else None,
            reason=reason.value if reason else None,
            resolved=resolved,
        )
        reports = [_build_report_dto(report) for report in rows]
    return AdminChatMessageReportsResponse(
        reports=reports, skip=skip, limit=limit, total=total
    )
