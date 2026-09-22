"""Filing moderation reports against a group's posts and comments.

Mirrors the chat message report rules: the reporter must be able to see the
content, cannot report their own, and gets one report per target.
"""
import logging
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette import status

from pecha_api.db.database import SessionLocal
from pecha_api.group_posts.comment_repository import get_comment_by_id_only
from pecha_api.group_posts.enums import (
    GroupPostReportReason,
    GroupPostReportTargetType,
)
from pecha_api.group_posts.report_models import GroupPostReport
from pecha_api.group_posts.report_repository import (
    create_report,
    get_report_by_target_and_reporter,
)
from pecha_api.group_posts.repository import get_post_by_id_only
from pecha_api.group_posts.service_utils import validate_group_content_access
from pecha_api.plans.response_message import NOT_FOUND
from pecha_api.users.users_repository import get_user_by_email_or_none

logger = logging.getLogger(__name__)

CANNOT_REPORT_OWN_CONTENT = "You cannot report your own content"
ALREADY_REPORTED = "You have already reported this"


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)


def _already_reported() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT, detail=ALREADY_REPORTED
    )


def _get_visible_post(db: Session, post_id: UUID, user_id: UUID):
    post = get_post_by_id_only(db=db, post_id=post_id, status=None)
    if not post:
        raise _not_found()
    # Same gate the post itself is read through, so a report cannot be used to
    # probe for content in a private group the reporter has not joined.
    validate_group_content_access(db=db, group_id=post.group_id, user_id=user_id)
    return post


def _file(
    db: Session,
    *,
    post_id: UUID,
    comment_id: Optional[UUID],
    target_type: GroupPostReportTargetType,
    reporter_id: UUID,
    reported_user_id: Optional[UUID],
    content_text: Optional[str],
    reason: GroupPostReportReason,
    description: Optional[str],
) -> None:
    if reported_user_id is not None and reported_user_id == reporter_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=CANNOT_REPORT_OWN_CONTENT,
        )

    existing = get_report_by_target_and_reporter(
        db=db, reporter_id=reporter_id, post_id=post_id, comment_id=comment_id
    )
    if existing:
        raise _already_reported()

    try:
        create_report(
            db=db,
            report=GroupPostReport(
                post_id=post_id,
                comment_id=comment_id,
                reporter_id=reporter_id,
                reported_user_id=reported_user_id,
                target_type=target_type.value,
                content_text=content_text,
                reason=reason.value,
                description=description,
            ),
        )
    except IntegrityError:
        # A concurrent duplicate won the race past the lookup; the partial
        # unique index already guarantees the one open report we wanted.
        db.rollback()
        raise _already_reported()

    logger.info(
        "Filed %s report against post %s comment %s",
        target_type.value,
        post_id,
        comment_id,
    )


def report_post_service(
    post_id: UUID,
    user_id: UUID,
    reason: GroupPostReportReason,
    description: Optional[str] = None,
) -> None:
    with SessionLocal() as db:
        post = _get_visible_post(db=db, post_id=post_id, user_id=user_id)
        # A post records its author as an email (created_by), not a user id,
        # so the reported user is resolved here - both to name them in the
        # queue and to enforce the self-report rule.
        author = get_user_by_email_or_none(db=db, email=post.created_by)
        _file(
            db,
            post_id=post.id,
            comment_id=None,
            target_type=GroupPostReportTargetType.POST,
            reporter_id=user_id,
            reported_user_id=author.id if author else None,
            content_text=post.caption,
            reason=reason,
            description=description,
        )


def report_comment_service(
    comment_id: UUID,
    user_id: UUID,
    reason: GroupPostReportReason,
    description: Optional[str] = None,
) -> None:
    with SessionLocal() as db:
        comment = get_comment_by_id_only(db=db, comment_id=comment_id)
        if not comment:
            raise _not_found()
        post = _get_visible_post(db=db, post_id=comment.post_id, user_id=user_id)
        _file(
            db,
            post_id=post.id,
            comment_id=comment.id,
            target_type=GroupPostReportTargetType.COMMENT,
            reporter_id=user_id,
            reported_user_id=comment.user_id,
            content_text=comment.text,
            reason=reason,
            description=description,
        )
