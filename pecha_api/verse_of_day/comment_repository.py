from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session, selectinload

from pecha_api.verse_of_day.comment_models import VerseOfDayComment


def get_verse_comments(
    db: Session,
    verse_id: UUID,
    skip: int = 0,
    limit: int = 20,
) -> Tuple[List[VerseOfDayComment], int]:
    query = (
        db.query(VerseOfDayComment)
        .filter(VerseOfDayComment.verse_id == verse_id)
        .order_by(VerseOfDayComment.created_at.desc(), VerseOfDayComment.id.desc())
    )

    total = query.count()
    comments = (
        query.options(selectinload(VerseOfDayComment.user))
        .offset(skip)
        .limit(limit)
        .all()
    )
    return comments, total


def create_comment(db: Session, comment: VerseOfDayComment) -> VerseOfDayComment:
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return (
        db.query(VerseOfDayComment)
        .options(selectinload(VerseOfDayComment.user))
        .filter(VerseOfDayComment.id == comment.id)
        .one()
    )


def get_comment_by_id(db: Session, comment_id: UUID) -> Optional[VerseOfDayComment]:
    return (
        db.query(VerseOfDayComment)
        .filter(VerseOfDayComment.id == comment_id)
        .first()
    )


def delete_comment(db: Session, comment: VerseOfDayComment) -> None:
    db.delete(comment)
    db.commit()
