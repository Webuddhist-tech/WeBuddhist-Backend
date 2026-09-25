"""Cached reads for a user's own plan and series progress.

Every response here belongs to one person, so every key carries their
identity and nobody else's entry is ever a candidate. Progress moves as they
complete subtasks, which is a write on this same router, so the writes evict
that caller's entries and the short timeout covers what the invalidation
cannot see - a day completed through a different route, an author republishing
the day underneath them.

`get_user_plan_day_details` is deliberately absent. It was cached here once,
which did nothing for it: the key carried the reader's identity, so the
expensive part of that response - resolving every segment on the day through
openpecha - was rebuilt once per reader rather than once per day. That work is
cached by segment id in `plans/shared/segment_cache.py` instead, where one
reader's fetch serves all of them, and the endpoint now reads the caller's
progress live.
"""

from functools import partial
from typing import Optional
from uuid import UUID

from pecha_api import config
from pecha_api.cache.cache_enums import CacheType
from pecha_api.cache.cache_identity import cache_identity_from_token
from pecha_api.cache.cached_response import cached_response
from pecha_api.plans.users.plan_users_response_models import (
    UserPlanDayCompletionStatusResponse,
    UserPlanProgressResponse,
    UserPlansResponse,
    UserSeriesDaysCompletedResponse,
    UserSeriesEnrollmentsResponse,
    UserSeriesProgressResponse,
)
from pecha_api.plans.users.plan_users_service import (
    get_user_plan_days_completion_status_service,
    get_user_plan_progress,
    get_user_enrolled_plans,
    get_user_series_days_completed,
    get_user_series_enrollments,
    get_user_series_progress,
)

USER_PLAN_CACHE_TYPES = (CacheType.USER_PLAN_PROGRESS,)


def _timeout() -> int:
    return config.get_int("CACHE_SOCIAL_TIMEOUT")


async def get_user_plans_cached(
    token: str,
    status_filter: Optional[str] = None,
    series_id: Optional[UUID] = None,
    language: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
) -> UserPlansResponse:
    return await cached_response(
        cache_type=CacheType.USER_PLAN_PROGRESS,
        parts=["plans", status_filter, series_id, language, skip, limit],
        model=UserPlansResponse,
        loader=partial(
            get_user_enrolled_plans,
            token=token,
            status_filter=status_filter,
            series_id=series_id,
            language=language,
            skip=skip,
            limit=limit,
        ),
        timeout=_timeout(),
        user_identity=await cache_identity_from_token(token),
    )


async def get_user_plan_progress_cached(token: str, plan_id: UUID) -> UserPlanProgressResponse:
    return await cached_response(
        cache_type=CacheType.USER_PLAN_PROGRESS,
        parts=["plan_progress", plan_id],
        model=UserPlanProgressResponse,
        loader=partial(get_user_plan_progress, token=token, plan_id=plan_id),
        timeout=_timeout(),
        user_identity=await cache_identity_from_token(token),
    )


async def get_user_plan_days_completion_status_cached(
    token: str, plan_id: UUID
) -> UserPlanDayCompletionStatusResponse:
    return await cached_response(
        cache_type=CacheType.USER_PLAN_PROGRESS,
        parts=["completion_status", plan_id],
        model=UserPlanDayCompletionStatusResponse,
        loader=partial(
            get_user_plan_days_completion_status_service, token=token, plan_id=plan_id
        ),
        timeout=_timeout(),
        user_identity=await cache_identity_from_token(token),
    )


async def get_user_series_enrollments_cached(
    token: str,
    status_filter: Optional[str] = None,
    language: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
) -> UserSeriesEnrollmentsResponse:
    return await cached_response(
        cache_type=CacheType.USER_PLAN_PROGRESS,
        parts=["series_enrollments", status_filter, language, skip, limit],
        model=UserSeriesEnrollmentsResponse,
        loader=partial(
            get_user_series_enrollments,
            token=token,
            status_filter=status_filter,
            language=language,
            skip=skip,
            limit=limit,
        ),
        timeout=_timeout(),
        user_identity=await cache_identity_from_token(token),
    )


async def get_user_series_days_completed_cached(
    token: str,
    language: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
) -> UserSeriesDaysCompletedResponse:
    return await cached_response(
        cache_type=CacheType.USER_PLAN_PROGRESS,
        parts=["series_days_completed", language, skip, limit],
        model=UserSeriesDaysCompletedResponse,
        loader=partial(
            get_user_series_days_completed,
            token=token,
            language=language,
            skip=skip,
            limit=limit,
        ),
        timeout=_timeout(),
        user_identity=await cache_identity_from_token(token),
    )


async def get_user_series_progress_cached(
    token: str,
    series_id: UUID,
    language: Optional[str] = None,
) -> UserSeriesProgressResponse:
    return await cached_response(
        cache_type=CacheType.USER_PLAN_PROGRESS,
        parts=["series_progress", series_id, language],
        model=UserSeriesProgressResponse,
        loader=partial(
            get_user_series_progress,
            token=token,
            series_id=series_id,
            language=language,
        ),
        timeout=_timeout(),
        user_identity=await cache_identity_from_token(token),
    )
