"""Counts made at an event in person, by people not using the app.

They are kept as the in-person account's rows (IN_PERSON_USER_ID) in the
group accumulation the event is linked to, one row per day in the event's
timezone, so they add to the group's total like anyone else's count. Group
managers list, record, correct and remove them in the Studio."""

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional, Tuple
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy.orm import Session
from starlette import status

from pecha_api import config
from pecha_api.db.database import SessionLocal
from pecha_api.group_accumulator.group_accumulator_repository import (
    get_group_accumulator_by_id,
    get_group_accumulator_total_count,
)
from pecha_api.group_accumulator.group_accumulator_service import _resolve_title
from pecha_api.plans.authors.plan_authors_service import safe_get_image_url, validate_cms_author_details

from .event_repository import get_event_by_id
from .event_service import _require_can_edit_event
from .in_person_count_repository import (
    add_in_person_count,
    delete_in_person_count,
    find_in_person_count_in_range,
    get_in_person_count,
    list_in_person_counts,
    save_in_person_count,
    user_exists,
)
from .in_person_count_response_models import (
    CreateInPersonCountRequest,
    InPersonCountDTO,
    InPersonCountsResponse,
    UpdateInPersonCountRequest,
)

EVENT_HAS_NO_GROUP_ACCUMULATOR = "EVENT_HAS_NO_GROUP_ACCUMULATOR"
IN_PERSON_COUNT_EXISTS = "IN_PERSON_COUNT_EXISTS"
IN_PERSON_USER_NOT_FOUND = "IN_PERSON_USER_NOT_FOUND"


def in_person_user_id() -> UUID:
    return UUID(config.get("IN_PERSON_USER_ID"))


def _zone(tz_name: Optional[str]) -> Tuple[ZoneInfo, str]:
    """The event's timezone, else UTC."""
    if tz_name and tz_name.strip():
        try:
            return ZoneInfo(tz_name.strip()), tz_name.strip()
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return ZoneInfo("UTC"), "UTC"


def _day_window(day: date, zone: ZoneInfo) -> Tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=zone)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _stamp(day: date, zone: ZoneInfo) -> datetime:
    """Midday of `day` in the event's timezone: the same calendar day for
    anyone within twelve hours of it, which is what "today" totals use."""
    return datetime.combine(day, time(12), tzinfo=zone).astimezone(timezone.utc)


def _to_dto(row, zone: ZoneInfo) -> InPersonCountDTO:
    return InPersonCountDTO(
        id=row.id,
        day=row.created_at.astimezone(zone).date(),
        count=row.count,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _load_event(db: Session, token: str, event_id: UUID):
    author = validate_cms_author_details(token=token)
    event = get_event_by_id(db=db, event_id=event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    _require_can_edit_event(db, event.group_id, author)
    return event


def _require_group_accumulator(event) -> UUID:
    if event.group_accumulator_id is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=EVENT_HAS_NO_GROUP_ACCUMULATOR)
    return event.group_accumulator_id


def _require_free_day(db: Session, group_accumulator_id: UUID, day: date, zone: ZoneInfo, exclude_id=None) -> None:
    start_utc, end_utc = _day_window(day, zone)
    clash = find_in_person_count_in_range(
        db,
        group_accumulator_id=group_accumulator_id,
        user_id=in_person_user_id(),
        start_utc=start_utc,
        end_utc=end_utc,
        exclude_id=exclude_id,
    )
    if clash is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=IN_PERSON_COUNT_EXISTS)


def _load_row(db: Session, event, history_id: UUID):
    row = get_in_person_count(
        db,
        history_id=history_id,
        group_accumulator_id=_require_group_accumulator(event),
        user_id=in_person_user_id(),
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="In-person count not found")
    return row


def list_in_person_counts_service(token: str, event_id: UUID, skip: int, limit: int) -> InPersonCountsResponse:
    with SessionLocal() as db:
        event = _load_event(db, token, event_id)
        zone, tz_name = _zone(event.timezone)
        rows, total, total_count = [], 0, 0
        linked = {}
        if event.group_accumulator_id is not None:
            rows, total, total_count = list_in_person_counts(
                db,
                group_accumulator_id=event.group_accumulator_id,
                user_id=in_person_user_id(),
                skip=skip,
                limit=limit,
            )
            group_accumulator = get_group_accumulator_by_id(db, event.group_accumulator_id)
            if group_accumulator is not None:
                linked = {
                    "group_accumulator_title": _resolve_title(group_accumulator, None),
                    "group_accumulator_total_count": get_group_accumulator_total_count(
                        db, event.group_accumulator_id
                    ),
                    "group_accumulator_target_count": group_accumulator.target_count,
                    "group_accumulator_image": safe_get_image_url(
                        group_accumulator.image_key,
                        resource_id=group_accumulator.id,
                        resource_type="group_accumulator",
                    ),
                }
        return InPersonCountsResponse(
            items=[_to_dto(row, zone) for row in rows],
            total=total,
            skip=skip,
            limit=limit,
            total_count=total_count,
            group_accumulator_id=event.group_accumulator_id,
            timezone=tz_name,
            **linked,
        )


def create_in_person_count_service(
    token: str, event_id: UUID, request: CreateInPersonCountRequest
) -> InPersonCountDTO:
    with SessionLocal() as db:
        event = _load_event(db, token, event_id)
        group_accumulator_id = _require_group_accumulator(event)
        if not user_exists(db, in_person_user_id()):
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=IN_PERSON_USER_NOT_FOUND)
        zone, _ = _zone(event.timezone)
        _require_free_day(db, group_accumulator_id, request.day, zone)
        row = add_in_person_count(
            db,
            group_accumulator_id=group_accumulator_id,
            user_id=in_person_user_id(),
            count=request.count,
            created_at=_stamp(request.day, zone),
        )
        return _to_dto(row, zone)


def update_in_person_count_service(
    token: str, event_id: UUID, history_id: UUID, request: UpdateInPersonCountRequest
) -> InPersonCountDTO:
    with SessionLocal() as db:
        event = _load_event(db, token, event_id)
        row = _load_row(db, event, history_id)
        zone, _ = _zone(event.timezone)
        if request.day is not None and request.day != row.created_at.astimezone(zone).date():
            _require_free_day(db, row.group_accumulator_id, request.day, zone, exclude_id=row.id)
            row.created_at = _stamp(request.day, zone)
        row.count = request.count
        return _to_dto(save_in_person_count(db, row), zone)


def delete_in_person_count_service(token: str, event_id: UUID, history_id: UUID) -> None:
    with SessionLocal() as db:
        event = _load_event(db, token, event_id)
        delete_in_person_count(db, _load_row(db, event, history_id))
