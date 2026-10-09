from typing import Dict, List, Optional, Sequence
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session
from starlette import status

from pecha_api.db.database import SessionLocal
from pecha_api.chat.enums import ChatMessageType

from .prayer_intention_model import PrayerIntention
from .prayer_intention_repository import (
    get_event_allowed_slugs,
    get_prayer_intention_by_slug,
    get_prayer_intentions_by_slugs,
    list_prayer_intentions,
    list_prayer_intentions_for_event,
)
from .intention_slugs import (
    canonical_prayer_intention_slug,
    catalog_slug_lookup_candidates,
)
from .prayer_intention_response_models import (
    PrayerIntentionDTO,
    PrayerIntentionsResponse,
)

PRAYER_REQUEST_BODY_MAX_LENGTH = 280

PRAYER_INTENTION_REQUIRED = "PRAYER_INTENTION_REQUIRED"
INVALID_PRAYER_INTENTION = "INVALID_PRAYER_INTENTION"
PRAYER_BODY_TOO_LONG = "PRAYER_BODY_TOO_LONG"
INTENTION_NOT_ALLOWED_ON_TEXT = "INTENTION_NOT_ALLOWED_ON_TEXT"
INTENTION_NOT_ALLOWED_FOR_EVENT = "INTENTION_NOT_ALLOWED_FOR_EVENT"


def prayer_intention_to_dto(row: PrayerIntention) -> PrayerIntentionDTO:
    return PrayerIntentionDTO(
        slug=row.slug,
        label=row.label,
        color=row.color,
        description=row.description,
        display_order=row.display_order,
    )


def resolve_prayer_intention_catalog_slug(db: Session, slug: str) -> Optional[str]:
    """Return the catalog slug present in the DB for this intention, if any."""
    canonical = canonical_prayer_intention_slug(slug)
    for candidate in catalog_slug_lookup_candidates(canonical):
        if get_prayer_intention_by_slug(db=db, slug=candidate) is not None:
            return candidate
    return None


def get_all_prayer_intentions_service(
    event_id: Optional[UUID] = None,
) -> PrayerIntentionsResponse:
    with SessionLocal() as db:
        if event_id is not None:
            # Lazy import avoids events package init → event_service → this module.
            from pecha_api.events.event_repository import get_event_by_id

            if get_event_by_id(db=db, event_id=event_id) is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Event with id '{event_id}' not found",
                )
            rows = list_prayer_intentions_for_event(db=db, event_id=event_id)
            if not rows:
                rows = list_prayer_intentions(db)
        else:
            rows = list_prayer_intentions(db)
        return PrayerIntentionsResponse(
            intentions=[prayer_intention_to_dto(row) for row in rows]
        )


def resolve_intention_dtos_for_slugs(
    db: Session, slugs: Sequence[Optional[str]]
) -> Dict[str, PrayerIntentionDTO]:
    present = [slug for slug in slugs if slug]
    if not present:
        return {}
    catalog_slug_by_stored = {
        slug: resolve_prayer_intention_catalog_slug(db=db, slug=slug)
        for slug in present
    }
    unique_catalog_slugs = [
        catalog_slug
        for catalog_slug in dict.fromkeys(catalog_slug_by_stored.values())
        if catalog_slug
    ]
    rows = get_prayer_intentions_by_slugs(db=db, slugs=unique_catalog_slugs)
    return {
        slug: prayer_intention_to_dto(rows[catalog_slug_by_stored[slug]])
        for slug in present
        if catalog_slug_by_stored[slug] in rows
    }


def validate_message_intention_and_body(
    db: Session,
    message_type: str,
    body: str,
    intention: Optional[str],
    event_id: Optional[UUID] = None,
) -> Optional[str]:
    """Return the normalised intention slug to store, or None for TEXT."""
    normalized_intention = (intention or "").strip().lower() or None

    if message_type == ChatMessageType.TEXT.value:
        if normalized_intention is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=INTENTION_NOT_ALLOWED_ON_TEXT,
            )
        if len(body) > 4000:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Message body must not exceed 4000 characters",
            )
        return None

    if message_type != ChatMessageType.PRAYER.value:
        return normalized_intention

    if not normalized_intention:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=PRAYER_INTENTION_REQUIRED,
        )
    if len(body) > PRAYER_REQUEST_BODY_MAX_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=PRAYER_BODY_TOO_LONG,
        )
    catalog_slug = resolve_prayer_intention_catalog_slug(
        db=db, slug=normalized_intention
    )
    if catalog_slug is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=INVALID_PRAYER_INTENTION,
        )
    if event_id is not None:
        allowed_slugs = get_event_allowed_slugs(db=db, event_id=event_id)
        if allowed_slugs is not None and catalog_slug not in allowed_slugs:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=INTENTION_NOT_ALLOWED_FOR_EVENT,
            )
    return catalog_slug
