"""Cached reads for the public series endpoints.

Series are author-published: nothing but a CMS write changes them, and every
one of those writes invalidates these namespaces (see
`invalidate_series_caches`), so the timeout is a backstop rather than the
thing keeping the response correct.

The response does vary per user - `partner` carries the caller's enrolment -
so these keys carry a verified user identity. Everything else that changes the
response is in the key too: filters, pagination, language and timezone.
Timezone matters more than it looks: restricted series are hidden for Chinese
timezones, so leaving it out would serve a hidden series to someone it is
meant to be hidden from.
"""

from functools import partial
from typing import Optional
from uuid import UUID

from pecha_api import config
from pecha_api.cache.cache_enums import CacheType
from pecha_api.cache.cache_identity import cache_identity_from_token
from pecha_api.cache.cached_response import cached_response, invalidate_namespaces
from pecha_api.plans.series.series_response_models import SeriesDTO, SeriesListResponse
from pecha_api.plans.series.series_service import (
    get_filtered_series,
    get_random_featured_series,
    get_series_detail,
)

# Every namespace a series write can make stale.
SERIES_CACHE_TYPES = (
    CacheType.SERIES_LIST,
    CacheType.SERIES_FEATURED,
    CacheType.SERIES_DETAIL,
)


def _timeout() -> int:
    return config.get_int("CACHE_CONTENT_TIMEOUT")


async def get_filtered_series_cached(
    search: Optional[str],
    skip: int,
    limit: int,
    language: Optional[str] = None,
    group_id: Optional[UUID] = None,
    token: Optional[str] = None,
    timezone_name: Optional[str] = None,
) -> SeriesListResponse:
    return await cached_response(
        cache_type=CacheType.SERIES_LIST,
        parts=[search, skip, limit, language, group_id, timezone_name],
        model=SeriesListResponse,
        loader=partial(
            get_filtered_series,
            search=search,
            skip=skip,
            limit=limit,
            language=language,
            group_id=group_id,
            token=token,
            timezone_name=timezone_name,
        ),
        timeout=_timeout(),
        user_identity=cache_identity_from_token(token),
    )


async def get_random_featured_series_cached(
    language: Optional[str] = None,
    limit: int = 10,
    token: Optional[str] = None,
) -> SeriesListResponse:
    """Note: the underlying query picks at random, so caching freezes the
    selection for one timeout rather than reshuffling per request."""
    return await cached_response(
        cache_type=CacheType.SERIES_FEATURED,
        parts=[language, limit],
        model=SeriesListResponse,
        loader=partial(
            get_random_featured_series,
            language=language,
            limit=limit,
            token=token,
        ),
        timeout=_timeout(),
        user_identity=cache_identity_from_token(token),
    )


async def get_series_detail_cached(
    series_id: UUID,
    language: Optional[str] = None,
    token: Optional[str] = None,
    timezone_name: Optional[str] = None,
) -> SeriesDTO:
    return await cached_response(
        cache_type=CacheType.SERIES_DETAIL,
        parts=[series_id, language, timezone_name],
        model=SeriesDTO,
        loader=partial(
            get_series_detail,
            series_id=series_id,
            language=language,
            token=token,
            timezone_name=timezone_name,
        ),
        timeout=_timeout(),
        user_identity=cache_identity_from_token(token),
    )


async def invalidate_series_caches() -> int:
    """Drop every cached series response.

    Deliberately blunt: a series write can change a list page it does not
    appear on (ordering, counts, a group's summary), so evicting the whole
    namespace is the only version that is actually correct. Series writes are
    rare - a handful a day from the CMS - so the cost of rebuilding is paid by
    a few requests, once.
    """
    return await invalidate_namespaces(SERIES_CACHE_TYPES)
