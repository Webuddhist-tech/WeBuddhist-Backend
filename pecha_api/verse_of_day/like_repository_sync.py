"""Synchronous SQLAlchemy helpers for verse-of-day likes.

Invoked only from worker threads via ``run_in_threadpool`` in ``like_repository``.
"""
from typing import List, Tuple
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from pecha_api.db.database import SessionLocal
from pecha_api.verse_of_day.like_models import VerseOfDayLike


def _create_like(db: Session, like: VerseOfDayLike) -> Tuple[VerseOfDayLike, bool]:
    try:
        db.add(like)
        db.commit()
        db.refresh(like)
        return like, True
    except IntegrityError as exc:
        db.rollback()
        existing = (
            db.query(VerseOfDayLike)
            .filter(
                VerseOfDayLike.verse_id == like.verse_id,
                VerseOfDayLike.user_id == like.user_id,
            )
            .first()
        )
        if existing is None:
            raise exc
        return existing, False


def _delete_like(db: Session, verse_id: UUID, user_id: UUID) -> bool:
    deleted_count = (
        db.query(VerseOfDayLike)
        .filter(
            VerseOfDayLike.verse_id == verse_id,
            VerseOfDayLike.user_id == user_id,
        )
        .delete()
    )
    db.commit()
    return deleted_count > 0


def _count_verse_likes(db: Session, verse_id: UUID) -> int:
    return db.query(VerseOfDayLike).filter(VerseOfDayLike.verse_id == verse_id).count()


def _get_verse_likers(
    db: Session,
    verse_id: UUID,
    skip: int,
    limit: int,
) -> Tuple[List[VerseOfDayLike], int]:
    query = (
        db.query(VerseOfDayLike)
        .filter(VerseOfDayLike.verse_id == verse_id)
        .order_by(VerseOfDayLike.created_at.desc(), VerseOfDayLike.id.desc())
    )
    total = query.count()
    likes = (
        query.options(selectinload(VerseOfDayLike.user))
        .offset(skip)
        .limit(limit)
        .all()
    )
    return likes, total


def _like_exists(db: Session, verse_id: UUID, user_id: UUID) -> bool:
    return (
        db.query(VerseOfDayLike)
        .filter(
            VerseOfDayLike.verse_id == verse_id,
            VerseOfDayLike.user_id == user_id,
        )
        .count()
        > 0
    )


def create_like_in_session(verse_id: UUID, user_id: UUID) -> Tuple[VerseOfDayLike, bool]:
    with SessionLocal() as db:
        like = VerseOfDayLike(verse_id=verse_id, user_id=user_id)
        return _create_like(db=db, like=like)


def delete_like_in_session(verse_id: UUID, user_id: UUID) -> bool:
    with SessionLocal() as db:
        return _delete_like(db=db, verse_id=verse_id, user_id=user_id)


def count_verse_likes_in_session(verse_id: UUID) -> int:
    with SessionLocal() as db:
        return _count_verse_likes(db=db, verse_id=verse_id)


def like_exists_in_session(verse_id: UUID, user_id: UUID) -> bool:
    with SessionLocal() as db:
        return _like_exists(db=db, verse_id=verse_id, user_id=user_id)


def get_verse_likers_in_session(
    verse_id: UUID, skip: int, limit: int
) -> Tuple[List[VerseOfDayLike], int]:
    with SessionLocal() as db:
        return _get_verse_likers(db=db, verse_id=verse_id, skip=skip, limit=limit)
