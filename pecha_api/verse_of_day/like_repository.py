"""Async repository for verse-of-day likes.

All database I/O runs in a worker thread via ``run_in_threadpool``; see
``like_repository_sync`` for synchronous SQLAlchemy implementations.
"""
from typing import List, Tuple
from uuid import UUID

from starlette.concurrency import run_in_threadpool

from pecha_api.verse_of_day.like_models import VerseOfDayLike
from pecha_api.verse_of_day import like_repository_sync as sync


async def create_like(verse_id: UUID, user_id: UUID) -> Tuple[VerseOfDayLike, bool]:
    return await run_in_threadpool(sync.create_like_in_session, verse_id, user_id)


async def delete_like(verse_id: UUID, user_id: UUID) -> bool:
    return await run_in_threadpool(sync.delete_like_in_session, verse_id, user_id)


async def count_verse_likes(verse_id: UUID) -> int:
    return await run_in_threadpool(sync.count_verse_likes_in_session, verse_id)


async def like_exists(verse_id: UUID, user_id: UUID) -> bool:
    return await run_in_threadpool(sync.like_exists_in_session, verse_id, user_id)


async def get_verse_likers(
    verse_id: UUID, skip: int, limit: int
) -> Tuple[List[VerseOfDayLike], int]:
    return await run_in_threadpool(
        sync.get_verse_likers_in_session, verse_id, skip, limit
    )
