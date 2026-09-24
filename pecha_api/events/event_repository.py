from datetime import datetime, timezone
from typing import Callable, List, Tuple, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.engine import Row
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Query, Session, selectinload
from starlette import status

from .event_model import Event
from .event_metadata_model import EventMetadata
from .event_link_model import EventLink
from .event_enums import EventLinkType
from .event_filters import EventContentFilter
from ..accumulator.accumulator_models import Accumulator
from ..mantra.mantra_model import Mantra
from ..plans.plans_models import Plan
from ..plans.plans_enums import PlanStatus
from ..plans.series.series_model import Series
from ..timers.timer_model import Timer
from ..group_recitation_collection.models import GroupRecitationCollection


def _persist_metadata_entries(db: Session, event_id: UUID, metadata_entries: List) -> None:
    for entry in metadata_entries:
        db.add(
            EventMetadata(
                event_id=event_id,
                name=entry.name,
                description=entry.description,
                language=entry.language,
            )
        )


def _persist_link_entries(db: Session, event_id: UUID, link_entries: List) -> None:
    for entry in link_entries:
        db.add(
            EventLink(
                event_id=event_id,
                type=entry.type.value,
                url=entry.url,
                label=entry.label,
                language=entry.language,
                display_order=entry.display_order,
            )
        )


def _persist_youtube_entries(db: Session, event_id: UUID, youtube_entries: List) -> None:
    for entry in youtube_entries:
        db.add(
            EventLink(
                event_id=event_id,
                type=EventLinkType.YOUTUBE.value,
                url=entry.url,
                label=entry.label,
                language=entry.language,
                display_order=entry.display_order,
            )
        )


def save_event(
    db: Session,
    event: Event,
    metadata_entries: List,
    link_entries: Optional[List] = None,
    youtube_entries: Optional[List] = None,
    after_flush: Optional[Callable[[Event], None]] = None,
) -> Event:
    """after_flush runs once event.id is populated and the row is visible
    in-transaction (e.g. for a dependent row's FK), but before the commit
    below - so anything it writes on the same session is persisted or rolled
    back atomically with the event instead of surviving a later failure."""
    try:
        db.add(event)
        db.flush()
        if after_flush is not None:
            after_flush(event)
        _persist_metadata_entries(db, event.id, metadata_entries)
        _persist_link_entries(db, event.id, link_entries or [])
        _persist_youtube_entries(db, event.id, youtube_entries or [])
        db.commit()
        db.refresh(event)
        return get_event_by_id(db, event.id)
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "BAD_REQUEST", "message": str(e.orig)},
        )


def _linked_resource_options() -> tuple:
    """Built lazily (not at import time) so mapper configuration only runs
    once every model across the app has been imported and registered."""
    return (
        selectinload(Event.plan),
        selectinload(Event.accumulator).selectinload(Accumulator.metadata_entries),
        selectinload(Event.accumulator).selectinload(Accumulator.mala),
        selectinload(Event.mantra).selectinload(Mantra.metadata_entries),
        selectinload(Event.mantra).selectinload(Mantra.mala),
        selectinload(Event.timer),
        selectinload(Event.group_recitation_collection),
    )


def get_event_by_id(db: Session, event_id: UUID) -> Optional[Event]:
    return (
        db.query(Event)
        .options(
            selectinload(Event.metadata_entries),
            selectinload(Event.links),
            selectinload(Event.location),
            *_linked_resource_options(),
        )
        .filter(Event.id == event_id)
        .first()
    )


def update_event(
    db: Session,
    event: Event,
    metadata_entries: Optional[List] = None,
    link_entries: Optional[List] = None,
    youtube_entries: Optional[List] = None,
) -> Event:
    try:
        if metadata_entries is not None:
            db.query(EventMetadata).filter(EventMetadata.event_id == event.id).delete()
            _persist_metadata_entries(db, event.id, metadata_entries)
        if link_entries is not None:
            db.query(EventLink).filter(
                EventLink.event_id == event.id,
                EventLink.type != EventLinkType.YOUTUBE.value,
            ).delete()
            _persist_link_entries(db, event.id, link_entries)
        if youtube_entries is not None:
            db.query(EventLink).filter(
                EventLink.event_id == event.id,
                EventLink.type == EventLinkType.YOUTUBE.value,
            ).delete()
            _persist_youtube_entries(db, event.id, youtube_entries)
        db.commit()
        db.refresh(event)
        return get_event_by_id(db, event.id)
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "BAD_REQUEST", "message": str(e.orig)},
        )


def delete_event(db: Session, event: Event) -> None:
    try:
        db.delete(event)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "BAD_REQUEST", "message": str(e)},
        )


def mark_event_notification_dispatched(
    db: Session,
    event_id: UUID,
    sqs_message_id: str,
) -> Optional[Event]:
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        return None
    event.notification_sqs_message_id = sqs_message_id
    event.notification_dispatched_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(event)
    return event


def list_undispatched_event_notifications(
    db: Session,
    *,
    older_than: datetime,
    limit: int,
) -> List[Event]:
    return (
        db.query(Event)
        .filter(
            Event.notification_sqs_message_id.is_(None),
            Event.created_at <= older_than,
            # Never re-enqueue for an event whose organizer has since
            # switched notifications off.
            Event.notifications_enabled.is_(True),
        )
        .order_by(Event.created_at.asc())
        .limit(limit)
        .all()
    )


def _apply_event_filters(
    query: Query,
    content_filter: Optional[EventContentFilter] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    restrict_group_ids: Optional[List[UUID]] = None,
    not_ended_before: Optional[datetime] = None,
    exclude_plan_or_series_linked: bool = False,
) -> Query:
    content_filter = content_filter or EventContentFilter()
    if restrict_group_ids is not None:
        query = query.filter(Event.group_id.in_(restrict_group_ids))
    if content_filter.group_id:
        query = query.filter(Event.group_id == content_filter.group_id)
    if content_filter.plan_id:
        query = query.filter(Event.plan_id == content_filter.plan_id)
    if exclude_plan_or_series_linked:
        query = query.filter(Event.plan_id.is_(None), Event.series_id.is_(None))
    if content_filter.accumulator_id:
        query = query.filter(Event.accumulator_id == content_filter.accumulator_id)
    if content_filter.mantra_id:
        query = query.filter(Event.mantra_id == content_filter.mantra_id)
    if content_filter.timer_id:
        query = query.filter(Event.timer_id == content_filter.timer_id)
    if content_filter.group_recitation_collection_id:
        query = query.filter(
            Event.group_recitation_collection_id
            == content_filter.group_recitation_collection_id
        )
    if content_filter.event_format:
        query = query.filter(
            Event.event_format.in_({content_filter.event_format, "hybrid"})
        )
    if from_date is not None:
        query = query.filter(Event.end_date >= from_date)
    if not_ended_before is not None:
        query = query.filter(Event.end_date >= not_ended_before)
    if to_date is not None:
        query = query.filter(Event.start_date <= to_date)
    return query


def _plan_series_published_or_standalone():
    return or_(
        Plan.series_id.is_(None),
        exists(
            select(1).where(
                and_(
                    Series.id == Plan.series_id,
                    Series.status == PlanStatus.PUBLISHED,
                )
            )
        ),
    )


def _publishable_linked_content_filter():
    """SQL equivalent of event_has_publishable_linked_content for feed totals."""
    published_plan = and_(
        Plan.status == PlanStatus.PUBLISHED,
        Plan.deleted_at.is_(None),
        _plan_series_published_or_standalone(),
    )
    published_series = and_(
        Series.status == PlanStatus.PUBLISHED,
        Series.deleted_at.is_(None),
    )
    return or_(
        and_(Event.plan_id.is_(None), Event.series_id.is_(None)),
        and_(
            Event.plan_id.isnot(None),
            exists(select(1).where(Plan.id == Event.plan_id, published_plan)),
        ),
        and_(
            Event.plan_id.is_(None),
            Event.series_id.isnot(None),
            exists(select(1).where(Series.id == Event.series_id, published_series)),
        ),
    )


def count_publishable_one_shot_feed_events(
    db: Session,
    restrict_group_ids: List[UUID],
) -> int:
    """Count in-scope one-shot events whose linked plan/series is publishable."""
    if not restrict_group_ids:
        return 0
    total = (
        _apply_event_filters(
            db.query(func.count(Event.id)).filter(Event.is_recurring == False),
            restrict_group_ids=restrict_group_ids,
        )
        .filter(_publishable_linked_content_filter())
        .scalar()
    )
    return int(total or 0)


def get_events(
    db: Session,
    content_filter: Optional[EventContentFilter] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    restrict_group_ids: Optional[List[UUID]] = None,
    not_ended_before: Optional[datetime] = None,
    skip: int = 0,
    limit: Optional[int] = 20,
    should_sort_newest_first: bool = False,
    exclude_plan_or_series_linked: bool = False,
) -> Tuple[List[Event], int]:
    if restrict_group_ids is not None and not restrict_group_ids:
        return [], 0

    count_query = _apply_event_filters(
        db.query(func.count(Event.id)).filter(Event.is_recurring == False),
        content_filter=content_filter,
        from_date=from_date,
        to_date=to_date,
        restrict_group_ids=restrict_group_ids,
        not_ended_before=not_ended_before,
        exclude_plan_or_series_linked=exclude_plan_or_series_linked,
    )
    total = count_query.scalar()

    events_query = _apply_event_filters(
        db.query(Event).options(
            selectinload(Event.metadata_entries),
            selectinload(Event.links),
            selectinload(Event.location),
            *_linked_resource_options(),
        ).filter(Event.is_recurring == False),
        content_filter=content_filter,
        from_date=from_date,
        to_date=to_date,
        restrict_group_ids=restrict_group_ids,
        not_ended_before=not_ended_before,
        exclude_plan_or_series_linked=exclude_plan_or_series_linked,
    )
    order_by = (
        (Event.created_at.desc(), Event.id.desc())
        if should_sort_newest_first
        else (Event.start_date.asc(),)
    )
    events_query = events_query.order_by(*order_by).offset(skip)
    if limit is not None:
        events_query = events_query.limit(limit)
    events = events_query.all()
    return events, total


def get_one_shot_event_feed_keys(
    db: Session,
    restrict_group_ids: List[UUID],
    limit: int,
    exclude_plan_or_series_linked: bool = False,
) -> Tuple[List[Row], int]:
    """Newest-first (id, created_at) rows for one-shot events, plus publishable total.

    The total excludes one-shots whose linked plan/series is not publishable.
    Only ranking columns are selected (no eager loads) so the feed can rank a
    deep window cheaply and load full events for the page via get_events_by_ids.
    """
    if not restrict_group_ids:
        return [], 0

    total = count_publishable_one_shot_feed_events(
        db,
        restrict_group_ids=restrict_group_ids,
    )

    rows = (
        _apply_event_filters(
            db.query(Event.id, Event.created_at).filter(Event.is_recurring == False),
            restrict_group_ids=restrict_group_ids,
            exclude_plan_or_series_linked=exclude_plan_or_series_linked,
        )
        .order_by(Event.created_at.desc(), Event.id.desc())
        .limit(limit)
        .all()
    )
    return rows, total


def get_events_by_ids(
    db: Session,
    event_ids: List[UUID],
    restrict_group_ids: List[UUID],
    exclude_plan_or_series_linked: bool = False,
) -> List[Event]:
    """Fully load one-shot events by id, re-checking the same scope used to
    rank them so an event that moved out of the viewer's groups (or was
    linked to a plan or series) in between is not returned."""
    if not event_ids or not restrict_group_ids:
        return []
    return (
        _apply_event_filters(
            db.query(Event).options(
                selectinload(Event.metadata_entries),
                selectinload(Event.links),
                selectinload(Event.location),
                *_linked_resource_options(),
            ).filter(Event.is_recurring == False),
            restrict_group_ids=restrict_group_ids,
            exclude_plan_or_series_linked=exclude_plan_or_series_linked,
        )
        .filter(Event.id.in_(event_ids))
        .all()
    )


def get_featured_events(
    db: Session,
    limit: Optional[int] = 10,
    not_ended_before: Optional[datetime] = None,
) -> List[Event]:
    """Get featured one-shot events."""
    query = (
        db.query(Event)
        .options(
            selectinload(Event.metadata_entries),
            selectinload(Event.links),
            selectinload(Event.location),
            *_linked_resource_options(),
        )
        .filter(Event.featured == True)
        .filter(Event.is_recurring == False)
        .order_by(Event.start_date.desc())
    )
    if not_ended_before is not None:
        query = query.filter(Event.end_date >= not_ended_before)
    if limit is not None:
        query = query.limit(limit)
    return query.all()


def get_featured_recurring_events(
    db: Session,
) -> List[Event]:
    """Get featured recurring event templates."""
    return (
        db.query(Event)
        .options(
            selectinload(Event.metadata_entries),
            selectinload(Event.links),
            selectinload(Event.location),
            *_linked_resource_options(),
        )
        .filter(Event.featured == True)
        .filter(Event.is_recurring == True)
        .all()
    )


def list_recurring_events_for_materialization(
    db: Session,
    *,
    after_id: Optional[UUID] = None,
    limit: int = 200,
) -> List[Event]:
    """Recurring templates in id order, for the reminder materializer.

    Deliberately not get_recurring_events: that one eager-loads metadata,
    links, location and every linked resource for rendering, none of which
    the materializer reads, and returns the whole table at once. This walks
    it in keyset pages so a scheduled job can cross a large table without
    holding one enormous result set."""
    query = db.query(Event).filter(Event.is_recurring.is_(True))
    if after_id is not None:
        query = query.filter(Event.id > after_id)
    return query.order_by(Event.id.asc()).limit(limit).all()


def get_recurring_events(
    db: Session,
    content_filter: Optional[EventContentFilter] = None,
    restrict_group_ids: Optional[List[UUID]] = None,
    exclude_plan_or_series_linked: bool = False,
) -> List[Event]:
    """Get all recurring event templates matching the filters."""
    query = db.query(Event).options(
        selectinload(Event.metadata_entries),
        selectinload(Event.links),
        selectinload(Event.location),
        *_linked_resource_options(),
    ).filter(Event.is_recurring == True)

    return _apply_event_filters(
        query,
        content_filter=content_filter,
        restrict_group_ids=restrict_group_ids,
        exclude_plan_or_series_linked=exclude_plan_or_series_linked,
    ).all()
