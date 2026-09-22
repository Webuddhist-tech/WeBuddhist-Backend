"""Persistence for group post and comment moderation reports."""
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from pecha_api.group_posts.models import GroupPost
from pecha_api.group_posts.report_models import GroupPostReport


def get_report_by_target_and_reporter(
    db: Session,
    reporter_id: UUID,
    post_id: UUID,
    comment_id: Optional[UUID] = None,
) -> Optional[GroupPostReport]:
    """The reporter's existing report against this exact target, if any.

    Checked before insert so a repeat report answers 409 rather than surfacing
    as a constraint violation.
    """
    query = db.query(GroupPostReport).filter(
        GroupPostReport.reporter_id == reporter_id,
        GroupPostReport.post_id == post_id,
    )
    if comment_id is None:
        query = query.filter(GroupPostReport.comment_id.is_(None))
    else:
        query = query.filter(GroupPostReport.comment_id == comment_id)
    return query.first()


def create_report(db: Session, report: GroupPostReport) -> GroupPostReport:
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


def _display_options():
    """Everything the queue DTO reads, so a page costs a fixed number of
    queries rather than one per report."""
    return (
        selectinload(GroupPostReport.reporter),
        selectinload(GroupPostReport.reported_user),
        selectinload(GroupPostReport.post),
        selectinload(GroupPostReport.comment),
    )


def list_group_post_reports(
    db: Session,
    group_id: UUID,
    skip: int = 0,
    limit: int = 20,
    target_type: Optional[str] = None,
    reason: Optional[str] = None,
    resolved: Optional[bool] = None,
) -> Tuple[List[GroupPostReport], int]:
    """A group's post and comment reports, newest first.

    Scoped by joining through the post, which carries the group - a comment
    report stores its post for exactly this reason.
    """
    query = db.query(GroupPostReport).join(
        GroupPost, GroupPostReport.post_id == GroupPost.id
    ).filter(GroupPost.group_id == group_id)

    if target_type:
        query = query.filter(GroupPostReport.target_type == target_type)
    if reason:
        query = query.filter(GroupPostReport.reason == reason)
    if resolved is True:
        query = query.filter(GroupPostReport.resolved_at.isnot(None))
    elif resolved is False:
        query = query.filter(GroupPostReport.resolved_at.is_(None))

    total = query.with_entities(func.count(GroupPostReport.id)).scalar() or 0
    reports = (
        query.options(*_display_options())
        .order_by(GroupPostReport.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return reports, total
