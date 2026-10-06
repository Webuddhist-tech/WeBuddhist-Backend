"""Async repository for verse-of-day comments.

All database I/O runs in a worker thread via ``run_in_threadpool``; see
``comment_repository_sync`` for synchronous SQLAlchemy implementations.
"""
from typing import List, Optional, Tuple
from uuid import UUID

from starlette.concurrency import run_in_threadpool

from pecha_api.verse_of_day.comment_models import VerseOfDayComment
from pecha_api.verse_of_day import comment_repository_sync as sync


async def get_verse_comments(
    verse_id: UUID,
    skip: int = 0,
    limit: int = 20,
) -> Tuple[List[VerseOfDayComment], int]:
    return await run_in_threadpool(
        sync.get_verse_comments_in_session,
        verse_id,
        skip,
        limit,
    )


async def create_comment(
    verse_id: UUID,
    user_id: UUID,
    text: str,
    parent_comment_id: Optional[UUID] = None,
) -> VerseOfDayComment:
    return await run_in_threadpool(
        sync.create_comment_in_session,
        verse_id,
        user_id,
        text,
        parent_comment_id,
    )


async def get_comment_by_id_for_verse(
    comment_id: UUID,
    verse_id: UUID,
) -> Optional[VerseOfDayComment]:
    return await run_in_threadpool(
        sync.get_comment_by_id_for_verse_in_session,
        comment_id,
        verse_id,
    )


async def get_comment_by_id(comment_id: UUID) -> Optional[VerseOfDayComment]:
    return await run_in_threadpool(sync.get_comment_by_id_in_session, comment_id)


async def delete_comment(comment_id: UUID) -> None:
    await run_in_threadpool(sync.delete_comment_in_session, comment_id)
