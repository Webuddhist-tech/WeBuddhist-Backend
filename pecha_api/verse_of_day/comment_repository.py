from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session, selectinload
from starlette.concurrency import run_in_threadpool

from pecha_api.db.database import SessionLocal
from pecha_api.verse_of_day.comment_models import VerseOfDayComment


def _get_verse_comments(
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


def _create_comment(db: Session, comment: VerseOfDayComment) -> VerseOfDayComment:
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return (
        db.query(VerseOfDayComment)
        .options(selectinload(VerseOfDayComment.user))
        .filter(VerseOfDayComment.id == comment.id)
        .one()
    )


def _get_comment_by_id(db: Session, comment_id: UUID) -> Optional[VerseOfDayComment]:
    return (
        db.query(VerseOfDayComment)
        .filter(VerseOfDayComment.id == comment_id)
        .first()
    )


def _delete_comment(db: Session, comment: VerseOfDayComment) -> None:
    db.delete(comment)
    db.commit()


def _get_verse_comments_in_session(
    verse_id: UUID,
    skip: int,
    limit: int,
) -> Tuple[List[VerseOfDayComment], int]:
    with SessionLocal() as db:
        return _get_verse_comments(db=db, verse_id=verse_id, skip=skip, limit=limit)


def _create_comment_in_session(
    verse_id: UUID,
    user_id: UUID,
    text: str,
) -> VerseOfDayComment:
    with SessionLocal() as db:
        comment = VerseOfDayComment(
            verse_id=verse_id,
            user_id=user_id,
            text=text,
        )
        return _create_comment(db=db, comment=comment)


def _get_comment_by_id_in_session(comment_id: UUID) -> Optional[VerseOfDayComment]:
    with SessionLocal() as db:
        return _get_comment_by_id(db=db, comment_id=comment_id)


def _delete_comment_in_session(comment_id: UUID) -> None:
    with SessionLocal() as db:
        comment = _get_comment_by_id(db=db, comment_id=comment_id)
        if comment is None:
            return
        _delete_comment(db=db, comment=comment)


async def get_verse_comments(
    verse_id: UUID,
    skip: int = 0,
    limit: int = 20,
) -> Tuple[List[VerseOfDayComment], int]:
    return await run_in_threadpool(
        _get_verse_comments_in_session,
        verse_id,
        skip,
        limit,
    )


async def create_comment(
    verse_id: UUID,
    user_id: UUID,
    text: str,
) -> VerseOfDayComment:
    return await run_in_threadpool(
        _create_comment_in_session,
        verse_id,
        user_id,
        text,
    )


async def get_comment_by_id(comment_id: UUID) -> Optional[VerseOfDayComment]:
    return await run_in_threadpool(_get_comment_by_id_in_session, comment_id)


async def delete_comment(comment_id: UUID) -> None:
    await run_in_threadpool(_delete_comment_in_session, comment_id)
