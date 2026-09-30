from typing import Tuple
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

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


def _create_like_in_session(verse_id: UUID, user_id: UUID) -> Tuple[VerseOfDayLike, bool]:
    with SessionLocal() as db:
        like = VerseOfDayLike(verse_id=verse_id, user_id=user_id)
        return _create_like(db=db, like=like)


def _delete_like_in_session(verse_id: UUID, user_id: UUID) -> bool:
    with SessionLocal() as db:
        return _delete_like(db=db, verse_id=verse_id, user_id=user_id)


def _count_verse_likes_in_session(verse_id: UUID) -> int:
    with SessionLocal() as db:
        return _count_verse_likes(db=db, verse_id=verse_id)


def _like_exists_in_session(verse_id: UUID, user_id: UUID) -> bool:
    with SessionLocal() as db:
        return _like_exists(db=db, verse_id=verse_id, user_id=user_id)


async def create_like(verse_id: UUID, user_id: UUID) -> Tuple[VerseOfDayLike, bool]:
    return await run_in_threadpool(_create_like_in_session, verse_id, user_id)


async def delete_like(verse_id: UUID, user_id: UUID) -> bool:
    return await run_in_threadpool(_delete_like_in_session, verse_id, user_id)


async def count_verse_likes(verse_id: UUID) -> int:
    return await run_in_threadpool(_count_verse_likes_in_session, verse_id)


async def like_exists(verse_id: UUID, user_id: UUID) -> bool:
    return await run_in_threadpool(_like_exists_in_session, verse_id, user_id)
