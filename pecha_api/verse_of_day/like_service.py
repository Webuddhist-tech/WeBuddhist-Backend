from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException
from starlette import status
from starlette.concurrency import run_in_threadpool

from pecha_api.db.database import SessionLocal
from pecha_api.plans.response_message import NOT_FOUND
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


async def _require_verse(verse_id: UUID) -> None:
    def _check() -> None:
        with SessionLocal() as db:
            verse = get_verse_of_day_by_id(db=db, verse_id=verse_id)
            if not verse:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=NOT_FOUND,
                )

    await run_in_threadpool(_check)


async def like_verse_of_day_service(
    verse_id: UUID,
    user_id: UUID,
) -> LikeVerseOfDayResponse:
    await _require_verse(verse_id)

    created_like, is_new = await create_like(verse_id=verse_id, user_id=user_id)
    like_count = await count_verse_likes(verse_id=verse_id)

    return LikeVerseOfDayResponse(
        verse_id=verse_id,
        user_id=user_id,
        liked=True,
        like_count=like_count,
        created_at=_isoformat(created_like.created_at),
        is_new=is_new,
    )


async def unlike_verse_of_day_service(verse_id: UUID, user_id: UUID) -> None:
    await _require_verse(verse_id)
    await delete_like(verse_id=verse_id, user_id=user_id)


async def get_verse_likes_service(
    verse_id: UUID,
    user_id: Optional[UUID] = None,
) -> VerseOfDayLikesResponse:
    await _require_verse(verse_id)
    like_count = await count_verse_likes(verse_id=verse_id)
    liked_by_me = (
        await like_exists(verse_id=verse_id, user_id=user_id)
        if user_id
        else False
    )
    return VerseOfDayLikesResponse(
        verse_id=verse_id,
        like_count=like_count,
        liked_by_me=liked_by_me,
    )
