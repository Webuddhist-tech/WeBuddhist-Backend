"""Synchronous SQLAlchemy helpers for verse-of-day comment likes."""
from typing import Dict, List, Optional, Set, Tuple
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from pecha_api.db.database import SessionLocal
from pecha_api.verse_of_day.comment_like_models import VerseOfDayCommentLike


def _create_like(db: Session, like: VerseOfDayCommentLike) -> Tuple[VerseOfDayCommentLike, bool]:
    try:
        db.add(like)
        db.commit()
        db.refresh(like)
        return like, True
    except IntegrityError as exc:
        db.rollback()
        existing = (
            db.query(VerseOfDayCommentLike)
            .filter(
                VerseOfDayCommentLike.comment_id == like.comment_id,
                VerseOfDayCommentLike.user_id == like.user_id,
            )
            .first()
        )
        if existing is None:
            raise exc
        return existing, False


def _delete_like(db: Session, comment_id: UUID, user_id: UUID) -> bool:
    deleted_count = (
        db.query(VerseOfDayCommentLike)
        .filter(
            VerseOfDayCommentLike.comment_id == comment_id,
            VerseOfDayCommentLike.user_id == user_id,
        )
        .delete()
    )
    db.commit()
    return deleted_count > 0


def _count_comment_likes(db: Session, comment_id: UUID) -> int:
    return (
        db.query(VerseOfDayCommentLike)
        .filter(VerseOfDayCommentLike.comment_id == comment_id)
        .count()
    )


def _get_comment_likers(
    db: Session,
    comment_id: UUID,
    skip: int,
    limit: int,
) -> Tuple[List[VerseOfDayCommentLike], int]:
    query = (
        db.query(VerseOfDayCommentLike)
        .filter(VerseOfDayCommentLike.comment_id == comment_id)
        .order_by(
            VerseOfDayCommentLike.created_at.desc(),
            VerseOfDayCommentLike.id.desc(),
        )
    )
    total = query.count()
    likes = (
        query.options(selectinload(VerseOfDayCommentLike.user))
        .offset(skip)
        .limit(limit)
        .all()
    )
    return likes, total


def _batch_count_comment_likes(
    db: Session, comment_ids: List[UUID]
) -> Dict[UUID, int]:
    if not comment_ids:
        return {}
    results = (
        db.query(
            VerseOfDayCommentLike.comment_id,
            func.count(VerseOfDayCommentLike.id),
        )
        .filter(VerseOfDayCommentLike.comment_id.in_(comment_ids))
        .group_by(VerseOfDayCommentLike.comment_id)
        .all()
    )
    return {comment_id: count for comment_id, count in results}


def _batch_check_comments_liked_by_user(
    db: Session, comment_ids: List[UUID], user_id: UUID
) -> Set[UUID]:
    if not comment_ids:
        return set()
    results = (
        db.query(VerseOfDayCommentLike.comment_id)
        .filter(
            VerseOfDayCommentLike.comment_id.in_(comment_ids),
            VerseOfDayCommentLike.user_id == user_id,
        )
        .all()
    )
    return {comment_id for (comment_id,) in results}


def create_like_in_session(
    comment_id: UUID, user_id: UUID
) -> Tuple[VerseOfDayCommentLike, bool]:
    with SessionLocal() as db:
        like = VerseOfDayCommentLike(comment_id=comment_id, user_id=user_id)
        return _create_like(db=db, like=like)


def delete_like_in_session(comment_id: UUID, user_id: UUID) -> bool:
    with SessionLocal() as db:
        return _delete_like(db=db, comment_id=comment_id, user_id=user_id)


def count_comment_likes_in_session(comment_id: UUID) -> int:
    with SessionLocal() as db:
        return _count_comment_likes(db=db, comment_id=comment_id)


def get_comment_likers_in_session(
    comment_id: UUID, skip: int, limit: int
) -> Tuple[List[VerseOfDayCommentLike], int]:
    with SessionLocal() as db:
        return _get_comment_likers(db=db, comment_id=comment_id, skip=skip, limit=limit)


def batch_comment_like_state_in_session(
    comment_ids: List[UUID],
    user_id: Optional[UUID],
) -> Tuple[Dict[UUID, int], Set[UUID]]:
    with SessionLocal() as db:
        counts = _batch_count_comment_likes(db=db, comment_ids=comment_ids)
        liked_ids = (
            _batch_check_comments_liked_by_user(
                db=db, comment_ids=comment_ids, user_id=user_id
            )
            if user_id
            else set()
        )
        return counts, liked_ids
