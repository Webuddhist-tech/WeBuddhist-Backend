from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from starlette import status
from typing import List, Optional, Tuple
from uuid import UUID

from pecha_api.plans.auth.plan_auth_models import ResponseError
from pecha_api.plans.response_message import BAD_REQUEST, NOT_FOUND
from pecha_api.bookmarks.bookmark_models import Bookmark
from pecha_api.bookmarks.bookmark_enums import BookmarkType, BookmarkFilterType


def save_bookmark(db: Session, bookmark: Bookmark) -> None:
    try:
        db.add(bookmark)
        db.commit()
        db.refresh(bookmark)
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ResponseError(
                error="CONFLICT",
                message="Bookmark already exists for this item"
            ).model_dump()
        )


def get_bookmarks_by_user_id(
    db: Session,
    user_id: UUID,
    type: Optional[BookmarkFilterType] = None,
    skip: int = 0,
    limit: int = 20,
) -> Tuple[List[Bookmark], int]:
    query = db.query(Bookmark).filter(Bookmark.user_id == user_id)
    if type is not None:
        if type == BookmarkFilterType.TEXT:
            query = query.filter(
                Bookmark.type.in_([BookmarkType.TEXT, BookmarkType.VERSE])
            )
        elif type == BookmarkFilterType.ACCUMULATOR:
            # Group accumulations list alongside personal ones; the bookmark's
            # own `type` tells them apart.
            query = query.filter(
                Bookmark.type.in_(
                    [BookmarkType.ACCUMULATOR, BookmarkType.GROUP_ACCUMULATOR]
                )
            )
        else:
            query = query.filter(Bookmark.type == BookmarkType[type.name])
    total = query.count()
    bookmarks = (
        query.order_by(Bookmark.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return bookmarks, total


def get_bookmark_by_user_and_source(
    db: Session,
    user_id: UUID,
    source_id: str,
    type: Optional[BookmarkType] = None,
) -> Optional[Bookmark]:
    query = db.query(Bookmark).filter(
        Bookmark.user_id == user_id,
        Bookmark.source_id == source_id,
    )
    if type is not None:
        query = query.filter(Bookmark.type == type)
    return query.first()


def delete_bookmark(db: Session, user_id: UUID, bookmark_id: UUID) -> None:
    try:
        bookmark = db.query(Bookmark).filter(
            Bookmark.id == bookmark_id,
            Bookmark.user_id == user_id
        ).first()
        
        if not bookmark:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ResponseError(
                    error=NOT_FOUND,
                    message=f"Bookmark with ID {bookmark_id} not found for this user"
                ).model_dump()
            )
        
        db.delete(bookmark)
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ResponseError(
                error=BAD_REQUEST,
                message=f"Database integrity error: {str(e.orig)}"
            ).model_dump()
        )
