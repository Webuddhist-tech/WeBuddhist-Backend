from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pecha_api.notification.notification_preference_enums import (
    NotificationChannel,
    NotificationScope,
    NotificationType,
)
from pecha_api.notification.notification_preference_repository import (
    scoped_preference_filter,
)
from pecha_api.users.users_models import Users

from .event_participant_model import GroupEventParticipant


def is_user_joined_event(db: Session, event_id: UUID, user_id: UUID) -> bool:
    row = db.execute(
        select(GroupEventParticipant.id).where(
            GroupEventParticipant.event_id == event_id,
            GroupEventParticipant.user_id == user_id,
        )
    ).first()
    return row is not None


def get_joined_event_ids_by_user(
    db: Session,
    user_id: UUID,
    event_ids: Optional[List[UUID]] = None,
) -> List[UUID]:
    if event_ids is not None and not event_ids:
        return []
    query = db.query(GroupEventParticipant.event_id).filter(
        GroupEventParticipant.user_id == user_id,
    )
    if event_ids is not None:
        query = query.filter(GroupEventParticipant.event_id.in_(event_ids))
    return [row.event_id for row in query.all()]


def get_participation_types_by_user(
    db: Session,
    user_id: UUID,
    event_ids: Optional[List[UUID]] = None,
) -> Dict[UUID, str]:
    """Map of event_id -> participation type for this user.

    Events the user joined without picking a type are left out, so a missing
    key means "joined but undecided" or "not joined" - callers pair this with
    the joined-ids lookup when they need to tell those apart."""
    if event_ids is not None and not event_ids:
        return {}
    query = db.query(
        GroupEventParticipant.event_id,
        GroupEventParticipant.participation_type,
    ).filter(
        GroupEventParticipant.user_id == user_id,
        GroupEventParticipant.participation_type.isnot(None),
    )
    if event_ids is not None:
        query = query.filter(GroupEventParticipant.event_id.in_(event_ids))
    return {row.event_id: row.participation_type for row in query.all()}


def get_user_participation_type(
    db: Session, event_id: UUID, user_id: UUID
) -> Optional[str]:
    row = db.execute(
        select(GroupEventParticipant.participation_type).where(
            GroupEventParticipant.event_id == event_id,
            GroupEventParticipant.user_id == user_id,
        )
    ).first()
    return row[0] if row is not None else None


def upsert_event_participant(
    db: Session,
    event_id: UUID,
    user_id: UUID,
    participation_type: Optional[str] = None,
) -> None:
    """Join an event. Idempotent: joining again is a no-op.

    Re-joining with a `participation_type` updates the existing row, so the
    join endpoint doubles as a way to switch sides. Re-joining without one
    leaves whatever the user already chose alone."""
    existing = (
        db.query(GroupEventParticipant)
        .filter(
            GroupEventParticipant.event_id == event_id,
            GroupEventParticipant.user_id == user_id,
        )
        .first()
    )
    if existing is not None:
        if participation_type is not None and existing.participation_type != participation_type:
            existing.participation_type = participation_type
            existing.updated_at = datetime.now(timezone.utc)
            db.commit()
        return
    try:
        db.add(
            GroupEventParticipant(
                event_id=event_id,
                user_id=user_id,
                participation_type=participation_type,
                created_at=datetime.now(timezone.utc),
            )
        )
        db.commit()
    except IntegrityError:
        # Concurrent join won the race; the unique constraint already
        # guarantees a single row, so treat this as already joined.
        db.rollback()


def remove_event_participant(db: Session, event_id: UUID, user_id: UUID) -> bool:
    """Leave an event. Returns True when a row was actually removed."""
    participant = (
        db.query(GroupEventParticipant)
        .filter(
            GroupEventParticipant.event_id == event_id,
            GroupEventParticipant.user_id == user_id,
        )
        .first()
    )
    if participant is None:
        return False
    db.delete(participant)
    db.commit()
    return True


def get_event_participants_paginated(
    db: Session,
    event_id: UUID,
    skip: int = 0,
    limit: int = 20,
    notification_type: Optional[NotificationType] = None,
    channel: NotificationChannel = NotificationChannel.PUSH,
) -> Tuple[List[Tuple[Users, datetime, Optional[str]]], int]:
    """Participants of one event, paginated.

    With `notification_type` set, drops participants who have turned that
    notification off or snoozed it - the reminder path passes it, the
    participant list screen does not. Resolution is most-specific-wins: a
    mute on this one event beats the global setting, so someone can silence a
    talkative event without silencing every event they attend. The filter
    sits ahead of OFFSET/LIMIT and inside the count so `total` describes the
    same set the page is drawn from; the worker pages off that total.
    """
    query = (
        db.query(
            Users,
            GroupEventParticipant.created_at,
            GroupEventParticipant.participation_type,
        )
        .join(GroupEventParticipant, GroupEventParticipant.user_id == Users.id)
        .filter(GroupEventParticipant.event_id == event_id)
    )
    if notification_type is not None:
        join_targets, preference_conditions = scoped_preference_filter(
            Users.id,
            notification_type=notification_type,
            channel=channel,
            scope_type=NotificationScope.EVENT,
            scope_id=event_id,
        )
        for alias, onclause in join_targets:
            query = query.outerjoin(alias, onclause)
        query = query.filter(*preference_conditions)
    total = query.count()
    rows = (
        query.order_by(GroupEventParticipant.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return [
        (user, created_at, participation_type)
        for user, created_at, participation_type in rows
    ], total


def get_event_participant_count(db: Session, event_id: UUID) -> int:
    return (
        db.query(func.count(GroupEventParticipant.id))
        .filter(GroupEventParticipant.event_id == event_id)
        .scalar()
        or 0
    )


def get_event_participant_counts(
    db: Session,
    event_ids: List[UUID],
) -> Dict[UUID, int]:
    if not event_ids:
        return {}
    rows = (
        db.query(
            GroupEventParticipant.event_id,
            func.count(GroupEventParticipant.id).label("participant_count"),
        )
        .filter(GroupEventParticipant.event_id.in_(event_ids))
        .group_by(GroupEventParticipant.event_id)
        .all()
    )
    return {row.event_id: int(row.participant_count) for row in rows}
