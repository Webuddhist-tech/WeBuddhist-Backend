from datetime import datetime, timezone
from typing import List, Optional, Union
from uuid import UUID

from fastapi import HTTPException
from starlette import status

from pecha_api.db.database import SessionLocal
from pecha_api.plans.authors.plan_authors_service import validate_cms_author_details
from pecha_api.plans.plans_enums import LanguageCode
from pecha_api.plans.shared.permissions import (
    require_can_create_content,
    require_can_read_group_content,
)

from .location_model import Location
from .location_repository import (
    delete_location,
    get_event_count,
    get_event_counts,
    get_location_by_id,
    get_locations,
    save_location,
    update_location,
)
from .location_response_models import (
    CreateLocationRequest,
    LocationDetailDTO,
    LocationMetadataDTO,
    LocationsResponse,
    UpdateLocationRequest,
)


def _language_value(language: Union[LanguageCode, str]) -> str:
    return language.value if hasattr(language, "value") else str(language)


def _translations_to_dtos(location: Location) -> List[LocationMetadataDTO]:
    entries = getattr(location, "metadata_entries", None) or []
    return sorted(
        (
            LocationMetadataDTO(
                id=entry.id,
                name=entry.name,
                language=_language_value(entry.language),
            )
            for entry in entries
        ),
        key=lambda dto: dto.language,
    )


def _location_to_dto(location: Location, event_count: int = 0) -> LocationDetailDTO:
    return LocationDetailDTO(
        id=location.id,
        group_id=location.group_id,
        name=location.name,
        latitude=location.latitude,
        longitude=location.longitude,
        event_count=event_count,
        translations=_translations_to_dtos(location),
    )


def _get_location_or_404(db, location_id: UUID, group_id: UUID) -> Location:
    location = get_location_by_id(db=db, location_id=location_id, group_id=group_id)
    if location is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Location with id '{location_id}' not found",
        )
    return location


def get_locations_service(
    token: str,
    group_id: UUID,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
) -> LocationsResponse:
    current_author = validate_cms_author_details(token=token)
    with SessionLocal() as db:
        require_can_read_group_content(db=db, group_id=group_id, author=current_author)
        locations, total = get_locations(
            db=db, group_id=group_id, search=search, skip=skip, limit=limit
        )
        counts = get_event_counts(
            db=db, location_ids=[location.id for location in locations]
        )
        return LocationsResponse(
            locations=[
                _location_to_dto(location, event_count=counts.get(location.id, 0))
                for location in locations
            ],
            skip=skip,
            limit=limit,
            total=total,
        )


def get_location_by_id_service(
    token: str, group_id: UUID, location_id: UUID
) -> LocationDetailDTO:
    current_author = validate_cms_author_details(token=token)
    with SessionLocal() as db:
        require_can_read_group_content(db=db, group_id=group_id, author=current_author)
        location = _get_location_or_404(db, location_id, group_id)
        event_count = get_event_count(db=db, location_id=location_id)
        return _location_to_dto(location, event_count=event_count)


def create_location_service(
    token: str, group_id: UUID, request: CreateLocationRequest
) -> LocationDetailDTO:
    current_author = validate_cms_author_details(token=token)
    with SessionLocal() as db:
        require_can_create_content(db=db, group_id=group_id, author=current_author)
        now = datetime.now(timezone.utc)
        location = Location(
            group_id=group_id,
            name=request.name,
            latitude=request.latitude,
            longitude=request.longitude,
            created_at=now,
            updated_at=now,
            created_by=current_author.email,
        )
        saved = save_location(
            db=db, location=location, translations=request.translations
        )
        return _location_to_dto(saved)


def update_location_service(
    token: str, group_id: UUID, location_id: UUID, request: UpdateLocationRequest
) -> LocationDetailDTO:
    current_author = validate_cms_author_details(token=token)
    with SessionLocal() as db:
        require_can_create_content(db=db, group_id=group_id, author=current_author)
        location = _get_location_or_404(db, location_id, group_id)

        if request.name is not None:
            location.name = request.name
        if "latitude" in request.model_fields_set:
            location.latitude = request.latitude
            location.longitude = request.longitude

        location.updated_at = datetime.now(timezone.utc)
        saved = update_location(
            db=db, location=location, translations=request.translations
        )
        event_count = get_event_count(db=db, location_id=location_id)
        return _location_to_dto(saved, event_count=event_count)


def delete_location_service(token: str, group_id: UUID, location_id: UUID) -> None:
    current_author = validate_cms_author_details(token=token)
    with SessionLocal() as db:
        require_can_create_content(db=db, group_id=group_id, author=current_author)
        location = _get_location_or_404(db, location_id, group_id)

        event_count = get_event_count(db=db, location_id=location_id)
        if event_count > 0:
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
        delete_location(db=db, location=location)
