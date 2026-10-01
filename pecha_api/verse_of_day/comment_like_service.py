from uuid import UUID

from fastapi import HTTPException
from starlette import status
from starlette.concurrency import run_in_threadpool

from pecha_api.plans.response_message import NOT_FOUND
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
from pecha_api.verse_of_day.comment_repository_sync import get_comment_by_id_in_session
from pecha_api.verse_of_day.like_service import (
    _isoformat,
    _liker_avatar_url,
    _liker_first_name,
    _require_verse,
)


async def _get_comment_verse_id(comment_id: UUID) -> UUID:
    def _load() -> UUID:
        comment = get_comment_by_id_in_session(comment_id=comment_id)
        if not comment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=NOT_FOUND,
            )
        return comment.verse_id

    return await run_in_threadpool(_load)


async def like_verse_comment_service(
    comment_id: UUID,
    user_id: UUID,
) -> LikeVerseOfDayCommentResponse:
    verse_id = await _get_comment_verse_id(comment_id)
    await _require_verse(verse_id)

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
    verse_id = await _get_comment_verse_id(comment_id)
    await _require_verse(verse_id)
    await delete_like(comment_id=comment_id, user_id=user_id)


async def list_verse_comment_likers_service(
    comment_id: UUID,
    skip: int = 0,
    limit: int = 20,
) -> VerseOfDayCommentLikersResponse:
    verse_id = await _get_comment_verse_id(comment_id)
    await _require_verse(verse_id)

    likes, total = await get_comment_likers(
        comment_id=comment_id, skip=skip, limit=limit
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
