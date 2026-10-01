from uuid import UUID

from fastapi import HTTPException
from starlette import status

from pecha_api.db.database import SessionLocal
from pecha_api.plans.authors.plan_authors_service import validate_cms_author_details
from pecha_api.plans.shared.permissions import require_cms_write_access

from .prayer_intention_repository import (
    count_intention_event_links,
    create_prayer_intention,
    get_prayer_intention_by_id,
    list_prayer_intentions,
    update_prayer_intention,
)
from .prayer_intention_response_models import (
    CreatePrayerIntentionRequest,
    PatchPrayerIntentionRequest,
    PrayerIntentionCMSDTO,
    PrayerIntentionsCMSListResponse,
)
from .prayer_intention_service import prayer_intention_to_dto


def _build_cms_dto(row, *, linked_event_count: int) -> PrayerIntentionCMSDTO:
    base = prayer_intention_to_dto(row)
    return PrayerIntentionCMSDTO(
        id=row.id,
        linked_event_count=linked_event_count,
        **base.model_dump(),
    )


def cms_list_prayer_intentions_service(token: str) -> PrayerIntentionsCMSListResponse:
    validate_cms_author_details(token=token)
    with SessionLocal() as db:
        rows = list_prayer_intentions(db)
        intentions = [
            _build_cms_dto(
                row,
                linked_event_count=count_intention_event_links(
                    db=db, intention_id=row.id
                ),
            )
            for row in rows
        ]
        return PrayerIntentionsCMSListResponse(intentions=intentions)


def cms_create_prayer_intention_service(
    token: str, request: CreatePrayerIntentionRequest
) -> PrayerIntentionCMSDTO:
    author = validate_cms_author_details(token=token)
    require_cms_write_access(author)
    with SessionLocal() as db:
        row = create_prayer_intention(
            db=db,
            slug=request.slug,
            label=request.label,
            color=request.color,
            description=request.description,
            display_order=request.display_order,
        )
        return _build_cms_dto(row, linked_event_count=0)


def cms_patch_prayer_intention_service(
    token: str,
    intention_id: UUID,
    request: PatchPrayerIntentionRequest,
) -> PrayerIntentionCMSDTO:
    author = validate_cms_author_details(token=token)
    require_cms_write_access(author)
    with SessionLocal() as db:
        row = get_prayer_intention_by_id(db=db, intention_id=intention_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Prayer intention not found",
            )
        row = update_prayer_intention(
            db=db,
            intention=row,
            label=request.label if request.label is not None else row.label,
            color=request.color if request.color is not None else row.color,
            description=(
                request.description
                if request.description is not None
                else row.description
            ),
            display_order=(
                request.display_order
                if request.display_order is not None
                else row.display_order
            ),
        )
        return _build_cms_dto(
            row,
            linked_event_count=count_intention_event_links(
                db=db, intention_id=row.id
            ),
        )
