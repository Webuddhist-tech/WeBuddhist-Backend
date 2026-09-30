import logging
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from starlette import status

from pecha_api.config import get
from pecha_api.db.database import SessionLocal
from pecha_api.plans.response_message import NOT_FOUND
from pecha_api.uploads.S3_utils import generate_presigned_access_url
from pecha_api.users.users_models import Users
from pecha_api.verse_of_day.comment_models import VerseOfDayComment
from pecha_api.verse_of_day.comment_repository import (
    create_comment,
    get_verse_comments,
)
from pecha_api.verse_of_day.comment_response_models import (
    VerseOfDayCommentDTO,
    VerseOfDayCommentUserDTO,
    VerseOfDayCommentsResponse,
)
from pecha_api.verse_of_day.verse_of_day_repository import get_verse_of_day_by_id

logger = logging.getLogger(__name__)


def _isoformat(value) -> Optional[str]:
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
        return VerseOfDayCommentUserDTO(
            first_name="Unknown",
            email="unknown@example.com",
        )
    return VerseOfDayCommentUserDTO(
        first_name=user.firstname,
        last_name=user.lastname,
        email=user.email,
        avatar_url=_generate_avatar_url(user.avatar_url),
    )


def build_comment_dto(comment: VerseOfDayComment) -> VerseOfDayCommentDTO:
    return VerseOfDayCommentDTO(
        id=comment.id,
        verse_id=comment.verse_id,
        user=_build_comment_user(comment.user),
        text=comment.text,
        created_at=_isoformat(comment.created_at),
        updated_at=_isoformat(comment.updated_at),
    )


def _require_verse(db, verse_id: UUID) -> None:
    verse = get_verse_of_day_by_id(db=db, verse_id=verse_id)
    if not verse:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=NOT_FOUND,
        )


def list_verse_comments_service(
    verse_id: UUID,
    skip: int = 0,
    limit: int = 20,
) -> VerseOfDayCommentsResponse:
    with SessionLocal() as db:
        _require_verse(db, verse_id)
        comments, total = get_verse_comments(
            db=db,
            verse_id=verse_id,
            skip=skip,
            limit=limit,
        )
        return VerseOfDayCommentsResponse(
            comments=[build_comment_dto(comment) for comment in comments],
            skip=skip,
            limit=limit,
            total=total,
        )


def create_verse_comment_service(
    verse_id: UUID,
    user_id: UUID,
    text: str,
) -> VerseOfDayCommentDTO:
    with SessionLocal() as db:
        _require_verse(db, verse_id)
        comment = VerseOfDayComment(
            verse_id=verse_id,
            user_id=user_id,
            text=text,
        )
        created = create_comment(db=db, comment=comment)
        return build_comment_dto(created)
