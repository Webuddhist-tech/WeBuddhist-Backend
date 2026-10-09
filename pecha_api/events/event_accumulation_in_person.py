"""Resolve which junction row manual in-person counts apply to."""

from typing import Optional, Tuple
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session
from starlette import status

from .event_enums import EventAccumulationCountMode
from .event_model import Event
from .group_event_accumulation_repository import list_accumulations_for_event

EVENT_ACCUMULATION_ID_REQUIRED = "EVENT_ACCUMULATION_ID_REQUIRED"
NO_MANUAL_EVENT_ACCUMULATION = "NO_MANUAL_EVENT_ACCUMULATION"
INVALID_EVENT_ACCUMULATION = "INVALID_EVENT_ACCUMULATION"
EVENT_HAS_NO_GROUP_ACCUMULATOR = "EVENT_HAS_NO_GROUP_ACCUMULATOR"


def resolve_manual_in_person_target(
    db: Session,
    event: Event,
    event_accumulation_id: Optional[UUID],
) -> Tuple[Optional[UUID], UUID]:
    """Return (junction link id if any, group_accumulator_id) for in-person counts."""
    links = list_accumulations_for_event(db, event.id)
    manual_links = [
        link
        for link in links
        if link.count_mode == EventAccumulationCountMode.MANUAL_IN_PERSON.value
    ]

    if event_accumulation_id is not None:
        link = next((row for row in links if row.id == event_accumulation_id), None)
        if link is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=INVALID_EVENT_ACCUMULATION,
            )
        if link.count_mode != EventAccumulationCountMode.MANUAL_IN_PERSON.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=NO_MANUAL_EVENT_ACCUMULATION,
            )
        return link.id, link.group_accumulator_id

    if len(manual_links) == 1:
        link = manual_links[0]
        return link.id, link.group_accumulator_id

    if len(manual_links) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=EVENT_ACCUMULATION_ID_REQUIRED,
        )

    if not links and event.group_accumulator_id is not None:
        return None, event.group_accumulator_id

    if links and not manual_links:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=NO_MANUAL_EVENT_ACCUMULATION,
        )

    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=EVENT_HAS_NO_GROUP_ACCUMULATOR,
    )
