import logging
from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException
from starlette import status
from starlette.concurrency import run_in_threadpool

from pecha_api.config import get
from pecha_api.db.database import SessionLocal
from pecha_api.plans.response_message import NOT_FOUND
from pecha_api.uploads.S3_utils import generate_presigned_access_url
from pecha_api.users.users_models import Users
from pecha_api.verse_of_day.like_repository import (
    count_verse_likes,
    create_like,
    delete_like,
    get_verse_likers,
    like_exists,
)
from pecha_api.verse_of_day.like_response_models import (
    LikeVerseOfDayResponse,
    VerseOfDayLikerDTO,
    VerseOfDayLikersResponse,
    VerseOfDayLikesResponse,
)
from pecha_api.verse_of_day.verse_of_day_repository import get_verse_of_day_by_id

logger = logging.getLogger(__name__)


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


def _liker_first_name(user: Optional[Users]) -> str:
    if not user:
        return "Unknown"
    return (user.firstname or "").strip() or "User"


def _liker_avatar_url(user: Optional[Users]) -> Optional[str]:
    if not user or not user.avatar_url:
        return None
    try:
        return generate_presigned_access_url(
            bucket_name=get("AWS_BUCKET_NAME"),
            s3_key=user.avatar_url,
        )
    except Exception:
        logger.exception("Failed to generate verse liker avatar URL")
        return None


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


async def list_verse_likers_service(
    verse_id: UUID,
    skip: int = 0,
    limit: int = 20,
) -> VerseOfDayLikersResponse:
    await _require_verse(verse_id)
    likes, total = await get_verse_likers(verse_id=verse_id, skip=skip, limit=limit)
    return VerseOfDayLikersResponse(
        likes=[
            VerseOfDayLikerDTO(
                user_id=like.user_id,
                first_name=_liker_first_name(like.user),
                last_name=like.user.lastname if like.user else None,
                avatar_url=_liker_avatar_url(like.user),
                created_at=_isoformat(like.created_at),
            )
            for like in likes
        ],
        skip=skip,
        limit=limit,
        total=total,
    )


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
