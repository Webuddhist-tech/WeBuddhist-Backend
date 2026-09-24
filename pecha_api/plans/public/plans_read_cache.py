"""Cached reads for the public plan, tag and preset endpoints.

Separate from `plans_cache_service` on purpose: that module is imported by
`plan_service`, and this one imports `plan_service`, so merging them would
make a cycle.

Everything here is author-published content with no per-user component, so
these entries are shared by every reader - one database round trip serves the
whole room for a timeout. `CACHE_CONTENT_TIMEOUT` is a backstop; the CMS write
paths invalidate the namespaces they affect.

Timezone is part of the key wherever the endpoint takes it: restricted plans
are hidden for Chinese timezones, and a key that ignored it would hand a
hidden plan to the person it is hidden from.
"""

from functools import partial
from typing import Optional
from uuid import UUID
from datetime import date as DateType
from datetime import datetime, timezone

from pecha_api import config
from pecha_api.cache.cache_enums import CacheType
from pecha_api.cache.cached_response import cached_response, invalidate_namespaces
from pecha_api.plans.public.plan_response_models import (
    DailyPlanResponse,
    PlanDaysResponse,
    PublicPlanDTO,
    PublicPlansResponse,
    TagsResponse,
)
from pecha_api.plans.public.plan_service import (
    get_plan_daily_content,
    get_plan_days,
    get_public_tag_detail,
    get_public_tags,
    get_published_plan,
    get_published_plans,
    get_tags,
)
from pecha_api.plans.tags.tag_response_models import (
    PublicTagDetailDTO,
    PublicTagsListResponse,
)

# Namespaces a plan write can make stale. Series is in the list because a
# plan carries its series' schedule: publishing a plan moves the series' start
# and end dates and its day count.
PLAN_CACHE_TYPES = (
    CacheType.PLAN_LIST,
    CacheType.PLAN_DETAIL,
    CacheType.PLAN_DAYS_LIST,
    CacheType.PLAN_DAILY,
    CacheType.SERIES_LIST,
    CacheType.SERIES_FEATURED,
    CacheType.SERIES_DETAIL,
)

TAG_CACHE_TYPES = (CacheType.PLAN_TAGS, CacheType.PLAN_TAG_DETAIL)


def _timeout() -> int:
    return config.get_int("CACHE_CONTENT_TIMEOUT")


def _utc_today() -> DateType:
    """The same clock `get_plan_daily_content` reads when it defaults a date."""
    return datetime.now(timezone.utc).date()


async def get_published_plans_cached(
    tag: Optional[str] = None,
    group_id: Optional[UUID] = None,
    search: Optional[str] = None,
    language: str = "en",
    sort_by: str = "title",
    sort_order: str = "asc",
    skip: int = 0,
    limit: int = 20,
    timezone_name: Optional[str] = None,
) -> PublicPlansResponse:
    return await cached_response(
        cache_type=CacheType.PLAN_LIST,
        parts=[tag, group_id, search, language, sort_by, sort_order, skip, limit, timezone_name],
        model=PublicPlansResponse,
        loader=partial(
            get_published_plans,
            tag=tag,
            group_id=group_id,
            search=search,
            language=language,
            sort_by=sort_by,
            sort_order=sort_order,
            skip=skip,
            limit=limit,
            timezone_name=timezone_name,
        ),
        timeout=_timeout(),
    )


async def get_published_plan_cached(
    plan_id: UUID,
    timezone_name: Optional[str] = None,
) -> PublicPlanDTO:
    return await cached_response(
        cache_type=CacheType.PLAN_DETAIL,
        parts=[plan_id, timezone_name],
        model=PublicPlanDTO,
        loader=partial(get_published_plan, plan_id=plan_id, timezone_name=timezone_name),
        timeout=_timeout(),
    )


async def get_plan_days_cached(plan_id: UUID) -> PlanDaysResponse:
    """The day list only. Enrolment is a write and stays out of the cache -
    the caller still runs it on every request."""
    return await cached_response(
        cache_type=CacheType.PLAN_DAYS_LIST,
        parts=[plan_id],
        model=PlanDaysResponse,
        loader=partial(get_plan_days, plan_id=plan_id),
        timeout=_timeout(),
    )


async def get_plan_daily_content_cached(
    plan_id: UUID,
    requested_date: Optional[DateType] = None,
    language: Optional[str] = None,
) -> DailyPlanResponse:
    return await cached_response(
        cache_type=CacheType.PLAN_DAILY,
        # `requested_date` is the caller's, which is often None; the service
        # then resolves "today" itself. Keying on the None would pin an entry
        # built at 23:59 to a day that has ended, and it would go on serving
        # yesterday's reading - and yesterday's prev/next links - until its
        # timeout. Keying on today's UTC date as well, which is the clock the
        # service reads, rolls the key over at midnight on its own.
        parts=[plan_id, requested_date, _utc_today(), language],
        model=DailyPlanResponse,
        loader=partial(
            get_plan_daily_content,
            plan_id=plan_id,
            requested_date=requested_date,
            language=language,
        ),
        timeout=_timeout(),
    )


async def get_tags_cached(language: str = "en") -> TagsResponse:
    return await cached_response(
        cache_type=CacheType.PLAN_TAGS,
        parts=["plan_tags", language],
        model=TagsResponse,
        loader=partial(get_tags, language=language),
        timeout=_timeout(),
    )


async def get_public_tags_cached(
    featured: Optional[bool] = None,
    search: Optional[str] = None,
    language: str = "EN",
    skip: int = 0,
    limit: int = 20,
) -> PublicTagsListResponse:
    return await cached_response(
        cache_type=CacheType.PLAN_TAGS,
        parts=["public_tags", featured, search, language, skip, limit],
        model=PublicTagsListResponse,
        loader=partial(
            get_public_tags,
            featured=featured,
            search=search,
            language=language,
            skip=skip,
            limit=limit,
        ),
        timeout=_timeout(),
    )


async def get_public_tag_detail_cached(
    tag_id: UUID,
    language: str = "EN",
) -> PublicTagDetailDTO:
    return await cached_response(
        cache_type=CacheType.PLAN_TAG_DETAIL,
        parts=[tag_id, language],
        model=PublicTagDetailDTO,
        loader=partial(get_public_tag_detail, tag_id=tag_id, language=language),
        timeout=_timeout(),
    )


async def invalidate_plan_caches() -> int:
    """Drop cached plan and series responses after a plan write.

    Blunt by design: a plan write moves counts, ordering and its series'
    schedule, so it can change a page the plan does not itself appear on.
    Plan writes are CMS-rate, so a full rebuild costs a handful of requests.
    """
    return await invalidate_namespaces(PLAN_CACHE_TYPES)


async def invalidate_tag_caches() -> int:
    return await invalidate_namespaces(TAG_CACHE_TYPES)
