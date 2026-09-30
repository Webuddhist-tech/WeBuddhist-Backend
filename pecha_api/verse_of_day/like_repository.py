from typing import Optional, Tuple
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pecha_api.verse_of_day.like_models import VerseOfDayLike


def create_like(db: Session, like: VerseOfDayLike) -> Tuple[VerseOfDayLike, bool]:
    try:
        db.add(like)
        db.commit()
        db.refresh(like)
        return like, True
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(VerseOfDayLike)
            .filter(
                VerseOfDayLike.verse_id == like.verse_id,
                VerseOfDayLike.user_id == like.user_id,
            )
            .first()
        )
        return existing, False


def delete_like(db: Session, verse_id: UUID, user_id: UUID) -> bool:
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


def count_verse_likes(db: Session, verse_id: UUID) -> int:
    return db.query(VerseOfDayLike).filter(VerseOfDayLike.verse_id == verse_id).count()
