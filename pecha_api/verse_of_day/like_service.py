from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session
from starlette import status

from pecha_api.db.database import SessionLocal
from pecha_api.plans.response_message import NOT_FOUND
from pecha_api.verse_of_day.like_models import VerseOfDayLike
from pecha_api.verse_of_day.like_repository import (
    count_verse_likes,
    create_like,
    delete_like,
    like_exists,
)
from pecha_api.verse_of_day.like_response_models import (
    LikeVerseOfDayResponse,
    VerseOfDayLikesResponse,
)
from pecha_api.verse_of_day.verse_of_day_repository import get_verse_of_day_by_id


def _isoformat(value: Any) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _require_verse(db: Session, verse_id: UUID) -> None:
    verse = get_verse_of_day_by_id(db=db, verse_id=verse_id)
    if not verse:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=NOT_FOUND,
        )


def like_verse_of_day_service(verse_id: UUID, user_id: UUID) -> LikeVerseOfDayResponse:
    with SessionLocal() as db:
        _require_verse(db, verse_id)

        like = VerseOfDayLike(verse_id=verse_id, user_id=user_id)
        created_like, is_new = create_like(db=db, like=like)
        like_count = count_verse_likes(db=db, verse_id=verse_id)

        return LikeVerseOfDayResponse(
            verse_id=verse_id,
            user_id=user_id,
            liked=True,
            like_count=like_count,
            created_at=_isoformat(created_like.created_at),
            is_new=is_new,
        )


def unlike_verse_of_day_service(verse_id: UUID, user_id: UUID) -> None:
    with SessionLocal() as db:
        _require_verse(db, verse_id)
        delete_like(db=db, verse_id=verse_id, user_id=user_id)


def get_verse_likes_service(
    verse_id: UUID,
    user_id: Optional[UUID] = None,
) -> VerseOfDayLikesResponse:
    with SessionLocal() as db:
        _require_verse(db, verse_id)
        like_count = count_verse_likes(db=db, verse_id=verse_id)
        liked_by_me = (
            like_exists(db=db, verse_id=verse_id, user_id=user_id)
            if user_id
            else False
        )
        return VerseOfDayLikesResponse(
            verse_id=verse_id,
            like_count=like_count,
            liked_by_me=liked_by_me,
        )
