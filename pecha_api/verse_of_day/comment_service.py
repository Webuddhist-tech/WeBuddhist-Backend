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
from pecha_api.verse_of_day.comment_models import VerseOfDayComment
from pecha_api.verse_of_day.comment_like_repository import (
    batch_check_comments_liked_by_user,
    batch_count_comment_likes,
)
from pecha_api.verse_of_day.comment_repository import (
    create_comment,
    delete_comment,
    get_comment_by_id,
    get_comment_by_id_for_verse,
    get_verse_comments,
)
from pecha_api.verse_of_day.comment_response_models import (
    VerseOfDayCommentDTO,
    VerseOfDayCommentUserDTO,
    VerseOfDayCommentsResponse,
)
from pecha_api.verse_of_day.verse_of_day_repository import get_verse_of_day_by_id

logger = logging.getLogger(__name__)


def _isoformat(value: Any) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _generate_avatar_url(avatar_key: Optional[str]) -> Optional[str]:
    if not avatar_key:
        return None
    try:
        return generate_presigned_access_url(
            bucket_name=get("AWS_BUCKET_NAME"),
            s3_key=avatar_key,
        )
    except Exception:
        logger.exception("Failed to generate comment user avatar URL")
        return None


def _build_comment_user(user: Optional[Users]) -> VerseOfDayCommentUserDTO:
    if not user:
        return VerseOfDayCommentUserDTO(first_name="Unknown")
    first_name = (user.firstname or "").strip() or "User"
    return VerseOfDayCommentUserDTO(
        first_name=first_name,
        last_name=user.lastname,
        avatar_url=_generate_avatar_url(user.avatar_url),
    )


def build_comment_dto(
    comment: VerseOfDayComment,
    like_count: int = 0,
    liked_by_me: bool = False,
) -> VerseOfDayCommentDTO:
    return VerseOfDayCommentDTO(
        id=comment.id,
        verse_id=comment.verse_id,
        user_id=comment.user_id,
        parent_comment_id=comment.parent_comment_id,
        user=_build_comment_user(comment.user),
        text=comment.text,
        created_at=_isoformat(comment.created_at),
        updated_at=_isoformat(comment.updated_at),
        like_count=like_count,
        liked_by_me=liked_by_me,
    )


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


async def list_verse_comments_service(
    verse_id: UUID,
    skip: int = 0,
    limit: int = 20,
    user_id: Optional[UUID] = None,
) -> VerseOfDayCommentsResponse:
    await _require_verse(verse_id)
    comments, total = await get_verse_comments(
        verse_id=verse_id,
        skip=skip,
        limit=limit,
    )
    comment_ids = [comment.id for comment in comments]
    like_counts = await batch_count_comment_likes(comment_ids)
    liked_comments = (
        await batch_check_comments_liked_by_user(comment_ids, user_id)
        if user_id
        else set()
    )
    return VerseOfDayCommentsResponse(
        comments=[
            build_comment_dto(
                comment,
                like_count=like_counts.get(comment.id, 0),
                liked_by_me=comment.id in liked_comments,
            )
            for comment in comments
        ],
        skip=skip,
        limit=limit,
        total=total,
    )


async def create_verse_comment_service(
    verse_id: UUID,
    user_id: UUID,
    text: str,
    parent_comment_id: Optional[UUID] = None,
) -> VerseOfDayCommentDTO:
    await _require_verse(verse_id)

    if parent_comment_id is not None:
        parent_comment = await get_comment_by_id_for_verse(
            comment_id=parent_comment_id,
            verse_id=verse_id,
        )
        if not parent_comment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Parent comment not found",
            )

    created = await create_comment(
        verse_id=verse_id,
        user_id=user_id,
        text=text,
        parent_comment_id=parent_comment_id,
    )
    return build_comment_dto(created)


async def delete_verse_comment_service(comment_id: UUID, user_id: UUID) -> None:
    comment = await get_comment_by_id(comment_id=comment_id)
    if not comment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=NOT_FOUND,
        )
    await _require_verse(comment.verse_id)
    if comment.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete your own comments",
        )
    await delete_comment(comment_id=comment_id)
