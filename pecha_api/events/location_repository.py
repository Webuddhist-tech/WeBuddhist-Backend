from typing import Dict, List, Optional, Tuple
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from starlette import status

from .event_model import Event
from .location_metadata_model import LocationMetadata
from .location_model import Location


def _persist_location_metadata(
    db: Session, location_id: UUID, translations: List
) -> None:
    for entry in translations:
        db.add(
            LocationMetadata(
                location_id=location_id,
                name=entry.name,
                language=entry.language,
            )
        )


def get_locations(
    db: Session,
    group_id: UUID,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
) -> Tuple[List[Location], int]:
    query = (
        db.query(Location)
        .options(selectinload(Location.metadata_entries))
        .filter(Location.group_id == group_id)
    )
    if search and search.strip():
        # Match the canonical name or any translated name. `.any()` is an
        # EXISTS, so several matching translations still count as one row.
        pattern = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Location.name.ilike(pattern),
                Location.metadata_entries.any(LocationMetadata.name.ilike(pattern)),
            )
        )

    total = query.count()
    locations = (
        query.order_by(Location.name.asc()).offset(skip).limit(limit).all()
    )
    return locations, total


def get_location_by_id(
    db: Session, location_id: UUID, group_id: UUID
) -> Optional[Location]:
    return (
        db.query(Location)
        .options(selectinload(Location.metadata_entries))
        .filter(Location.id == location_id, Location.group_id == group_id)
        .first()
    )


def get_location_without_group_filter(
    db: Session, location_id: UUID
) -> Optional[Location]:
    return db.query(Location).filter(Location.id == location_id).first()


def get_event_count(db: Session, location_id: UUID) -> int:
    return (
        db.query(func.count(Event.id))
        .filter(Event.location_id == location_id)
        .scalar()
        or 0
    )


def get_event_counts(db: Session, location_ids: List[UUID]) -> Dict[UUID, int]:
    if not location_ids:
        return {}
    rows = (
        db.query(Event.location_id, func.count(Event.id))
        .filter(Event.location_id.in_(location_ids))
        .group_by(Event.location_id)
        .all()
    )
    return {row[0]: row[1] for row in rows}


def save_location(
    db: Session, location: Location, translations: Optional[List] = None
) -> Location:
    try:
        db.add(location)
        if translations:
            db.flush()
            _persist_location_metadata(db, location.id, translations)
        db.commit()
        db.refresh(location)
        return location
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "BAD_REQUEST", "message": str(e.orig)},
        )


def update_location(
    db: Session, location: Location, translations: Optional[List] = None
) -> Location:
    try:
        # A list replaces the whole set, mirroring how event metadata is
        # updated; None (omitted in the request) leaves the rows untouched.
        if translations is not None:
            db.query(LocationMetadata).filter(
                LocationMetadata.location_id == location.id
            ).delete()
            _persist_location_metadata(db, location.id, translations)
        db.commit()
        db.refresh(location)
        return location
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "BAD_REQUEST", "message": str(e.orig)},
        )


def delete_location(db: Session, location: Location) -> None:
    try:
        db.delete(location)
        db.commit()
    except IntegrityError:
        db.rollback()
        event_count = get_event_count(db=db, location_id=location.id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "LOCATION_IN_USE",
                "message": (
                    f"Location is used by {event_count} event(s) and cannot be deleted"
                ),
                "event_count": event_count,
            },
        )
