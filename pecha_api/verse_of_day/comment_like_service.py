import logging
from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException
from starlette import status

from pecha_api.config import get
from pecha_api.plans.response_message import NOT_FOUND
from pecha_api.uploads.S3_utils import generate_presigned_access_url
from pecha_api.users.users_models import Users
from pecha_api.verse_of_day.comment_like_repository import (
    count_comment_likes,
    create_like,
    delete_like,
    get_comment_likers,
)
from pecha_api.verse_of_day.comment_like_response_models import (
    LikeVerseOfDayCommentResponse,
    VerseOfDayCommentLikerDTO,
    VerseOfDayCommentLikersResponse,
)
from pecha_api.verse_of_day.comment_repository import get_comment_by_id
from pecha_api.verse_of_day.comment_service import _require_verse

logger = logging.getLogger(__name__)


def _isoformat(value: Any) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


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
        logger.exception("Failed to generate comment liker avatar URL")
        return None


async def _require_comment(comment_id: UUID):
    comment = await get_comment_by_id(comment_id=comment_id)
    if not comment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=NOT_FOUND,
        )
    await _require_verse(comment.verse_id)
    return comment


async def like_verse_comment_service(
    comment_id: UUID,
    user_id: UUID,
) -> LikeVerseOfDayCommentResponse:
    await _require_comment(comment_id)
    created_like, is_new = await create_like(comment_id=comment_id, user_id=user_id)
    like_count = await count_comment_likes(comment_id=comment_id)
    return LikeVerseOfDayCommentResponse(
        comment_id=comment_id,
        user_id=user_id,
        liked=True,
        like_count=like_count,
        created_at=_isoformat(created_like.created_at),
        is_new=is_new,
    )


async def unlike_verse_comment_service(comment_id: UUID, user_id: UUID) -> None:
    await _require_comment(comment_id)
    await delete_like(comment_id=comment_id, user_id=user_id)


async def list_verse_comment_likers_service(
    comment_id: UUID,
    skip: int = 0,
    limit: int = 20,
) -> VerseOfDayCommentLikersResponse:
    await _require_comment(comment_id)
    likes, total = await get_comment_likers(
        comment_id=comment_id,
        skip=skip,
        limit=limit,
    )
    return VerseOfDayCommentLikersResponse(
        likes=[
            VerseOfDayCommentLikerDTO(
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
