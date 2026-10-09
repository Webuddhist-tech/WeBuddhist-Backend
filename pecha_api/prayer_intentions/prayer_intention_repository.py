from typing import Dict, List, Optional, Sequence, Set
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette import status

from .event_prayer_intention_model import EventPrayerIntention
from .prayer_intention_model import PrayerIntention


def list_prayer_intentions(db: Session) -> List[PrayerIntention]:
    return (
        db.query(PrayerIntention)
        .order_by(PrayerIntention.display_order.asc(), PrayerIntention.slug.asc())
        .all()
    )


def get_prayer_intention_by_slug(db: Session, slug: str) -> Optional[PrayerIntention]:
    return db.query(PrayerIntention).filter(PrayerIntention.slug == slug).first()


def get_prayer_intention_by_id(
    db: Session, intention_id: UUID
) -> Optional[PrayerIntention]:
    return db.query(PrayerIntention).filter(PrayerIntention.id == intention_id).first()


def get_prayer_intentions_by_slugs(
    db: Session, slugs: Sequence[str]
) -> Dict[str, PrayerIntention]:
    if not slugs:
        return {}
    unique = list(dict.fromkeys(slugs))
    rows = db.query(PrayerIntention).filter(PrayerIntention.slug.in_(unique)).all()
    return {row.slug: row for row in rows}


def get_prayer_intentions_by_ids(
    db: Session, intention_ids: Sequence[UUID]
) -> Dict[UUID, PrayerIntention]:
    if not intention_ids:
        return {}
    unique = list(dict.fromkeys(intention_ids))
    rows = db.query(PrayerIntention).filter(PrayerIntention.id.in_(unique)).all()
    return {row.id: row for row in rows}


def create_prayer_intention(
    db: Session,
    *,
    slug: str,
    label: str,
    color: str,
    description: str,
    display_order: int,
) -> PrayerIntention:
    existing = get_prayer_intention_by_slug(db=db, slug=slug)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Prayer intention with slug '{slug}' already exists",
        )
    row = PrayerIntention(
        slug=slug,
        label=label,
        color=color,
        description=description,
        display_order=display_order,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Prayer intention with slug '{slug}' already exists",
        ) from exc
    db.refresh(row)
    return row


def update_prayer_intention(
    db: Session,
    intention: PrayerIntention,
    *,
    label: str,
    color: str,
    description: str,
    display_order: int,
) -> PrayerIntention:
    intention.label = label
    intention.color = color
    intention.description = description
    intention.display_order = display_order
    db.commit()
    db.refresh(intention)
    return intention


def count_event_prayer_intention_links(db: Session, event_id: UUID) -> int:
    return (
        db.query(func.count())
        .select_from(EventPrayerIntention)
        .filter(EventPrayerIntention.event_id == event_id)
        .scalar()
        or 0
    )


def count_intention_event_links(db: Session, intention_id: UUID) -> int:
    return (
        db.query(func.count())
        .select_from(EventPrayerIntention)
        .filter(EventPrayerIntention.intention_id == intention_id)
        .scalar()
        or 0
    )


def list_prayer_intentions_for_event(db: Session, event_id: UUID) -> List[PrayerIntention]:
    return (
        db.query(PrayerIntention)
        .join(
            EventPrayerIntention,
            EventPrayerIntention.intention_id == PrayerIntention.id,
        )
        .filter(EventPrayerIntention.event_id == event_id)
        .order_by(PrayerIntention.display_order.asc(), PrayerIntention.slug.asc())
        .all()
    )


def list_prayer_intentions_grouped_by_event_id(
    db: Session, event_ids: Sequence[UUID]
) -> Dict[UUID, List[PrayerIntention]]:
    unique_ids = list(dict.fromkeys(event_ids))
    if not unique_ids:
        return {}
    rows = (
        db.query(EventPrayerIntention.event_id, PrayerIntention)
        .join(
            PrayerIntention,
            EventPrayerIntention.intention_id == PrayerIntention.id,
        )
        .filter(EventPrayerIntention.event_id.in_(unique_ids))
        .order_by(
            EventPrayerIntention.event_id.asc(),
            PrayerIntention.display_order.asc(),
            PrayerIntention.slug.asc(),
        )
        .all()
    )
    grouped: Dict[UUID, List[PrayerIntention]] = {event_id: [] for event_id in unique_ids}
    for event_id, intention in rows:
        grouped[event_id].append(intention)
    return grouped


def replace_event_prayer_intentions(
    db: Session, event_id: UUID, intention_ids: Sequence[UUID]
) -> None:
    unique_ids = list(dict.fromkeys(intention_ids))
    if unique_ids:
        found = get_prayer_intentions_by_ids(db=db, intention_ids=unique_ids)
        missing = [str(i) for i in unique_ids if i not in found]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown prayer intention id(s): {', '.join(missing)}",
            )

    db.query(EventPrayerIntention).filter(
        EventPrayerIntention.event_id == event_id
    ).delete()
    for intention_id in unique_ids:
        db.add(
            EventPrayerIntention(event_id=event_id, intention_id=intention_id)
        )
    db.flush()


def get_event_allowed_slugs(db: Session, event_id: UUID) -> Optional[Set[str]]:
    if count_event_prayer_intention_links(db=db, event_id=event_id) == 0:
        return None
    rows = list_prayer_intentions_for_event(db=db, event_id=event_id)
    return {row.slug for row in rows}
