from typing import Dict, List, Optional, Sequence

from fastapi import HTTPException
from sqlalchemy.orm import Session
from starlette import status

from pecha_api.db.database import SessionLocal
from pecha_api.chat.enums import ChatMessageType

from .prayer_intention_model import PrayerIntention
from .prayer_intention_repository import (
    get_prayer_intention_by_slug,
    get_prayer_intentions_by_slugs,
    list_prayer_intentions,
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


def prayer_intention_to_dto(row: PrayerIntention) -> PrayerIntentionDTO:
    return PrayerIntentionDTO(
        slug=row.slug,
        label=row.label,
        color=row.color,
        description=row.description,
        display_order=row.display_order,
    )


def get_all_prayer_intentions_service() -> PrayerIntentionsResponse:
    with SessionLocal() as db:
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
    rows = get_prayer_intentions_by_slugs(db=db, slugs=present)
    return {slug: prayer_intention_to_dto(rows[slug]) for slug in present if slug in rows}


def validate_message_intention_and_body(
    db: Session,
    message_type: str,
    body: str,
    intention: Optional[str],
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
    if get_prayer_intention_by_slug(db=db, slug=normalized_intention) is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=INVALID_PRAYER_INTENTION,
        )
    return normalized_intention
