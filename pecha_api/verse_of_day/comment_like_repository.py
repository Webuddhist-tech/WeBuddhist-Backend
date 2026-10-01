"""Async repository for verse-of-day comment likes."""
from typing import Dict, List, Optional, Set, Tuple
from uuid import UUID

from starlette.concurrency import run_in_threadpool

from pecha_api.verse_of_day.comment_like_models import VerseOfDayCommentLike
from pecha_api.verse_of_day import comment_like_repository_sync as sync


async def create_like(comment_id: UUID, user_id: UUID) -> Tuple[VerseOfDayCommentLike, bool]:
    return await run_in_threadpool(sync.create_like_in_session, comment_id, user_id)


async def delete_like(comment_id: UUID, user_id: UUID) -> bool:
    return await run_in_threadpool(sync.delete_like_in_session, comment_id, user_id)


async def count_comment_likes(comment_id: UUID) -> int:
    return await run_in_threadpool(sync.count_comment_likes_in_session, comment_id)


async def get_comment_likers(
    comment_id: UUID, skip: int, limit: int
) -> Tuple[List[VerseOfDayCommentLike], int]:
    return await run_in_threadpool(
        sync.get_comment_likers_in_session, comment_id, skip, limit
    )


async def batch_comment_like_state(
    comment_ids: List[UUID], user_id: Optional[UUID]
) -> Tuple[Dict[UUID, int], Set[UUID]]:
    return await run_in_threadpool(
        sync.batch_comment_like_state_in_session, comment_ids, user_id
    )
