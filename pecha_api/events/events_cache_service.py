"""Cached reads for the public event endpoints.

Events get `CACHE_SOCIAL_TIMEOUT`, not the hours that plans and series get.
Their content is author-published, but the response also carries live state -
`is_joined`, `my_participation_type`, participant counts - which moves while
people are in the room, and it moves through several write paths, not just
the CMS. A short timeout means the worst staleness anyone sees is measured in
seconds, and it still absorbs nearly all the load: a list read a thousand
times a minute is served from one query either way.

Keys carry the caller's identity because `is_joined` differs per person.
Joining therefore evicts only the joiner's entries - see
`invalidate_user_event_caches` - so a room filling up does not repeatedly
throw away the cache everyone else is reading. Participant counts catch up
when the timeout expires.
"""

from functools import partial
from typing import List, Optional
from uuid import UUID
from datetime import datetime

from pydantic import BaseModel

from pecha_api import config
from pecha_api.cache.cache_enums import CacheType
from pecha_api.cache.cache_identity import cache_identity_from_token
from pecha_api.cache.cached_response import cached_response, invalidate_user_namespaces
from pecha_api.events.event_filters import EventContentFilter
from pecha_api.events.event_response_models import EventDTO, EventsResponse
from pecha_api.events.event_service import (
    get_event_by_id_service,
    get_events_service,
    get_featured_events_service,
)
from pecha_api.events.event_service import get_day_bounds_in_timezone

EVENT_CACHE_TYPES = (
    CacheType.EVENT_LIST,
    CacheType.EVENT_DETAIL,
    CacheType.EVENT_FEATURED,
)


class _FeaturedEvents(BaseModel):
    """The featured endpoint returns a bare list; the cache stores models, so
    it travels wrapped and is unwrapped on the way out."""

    events: List[EventDTO]


def _timeout() -> int:
    return config.get_int("CACHE_SOCIAL_TIMEOUT")


def _filter_parts(content_filter: Optional[EventContentFilter]) -> list:
    """Every filter field, flattened into the key.

    Spelled out rather than taking the object's repr: a new field on
    EventContentFilter must be added here too, and a list that has to be
    edited is easier to notice than a repr that silently keeps working while
    ignoring the new filter.
    """
    if content_filter is None:
        return [None] * 7
    return [
        content_filter.group_id,
        content_filter.plan_id,
        content_filter.accumulator_id,
        content_filter.mantra_id,
        content_filter.timer_id,
        content_filter.group_recitation_collection_id,
        content_filter.event_format,
    ]


async def get_events_service_cached(
    content_filter: Optional[EventContentFilter] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    language: Optional[str] = None,
    restrict_group_ids: Optional[List[UUID]] = None,
    fallback: bool = False,
    should_include_unfollowed: bool = False,
    should_include_past: bool = False,
    skip: int = 0,
    limit: int = 20,
    token: Optional[str] = None,
) -> EventsResponse:
    parts = _filter_parts(content_filter) + [
        from_date,
        to_date,
        language,
        tuple(sorted(str(g) for g in restrict_group_ids)) if restrict_group_ids else None,
        fallback,
        should_include_unfollowed,
        should_include_past,
        skip,
        limit,
    ]
    return await cached_response(
        cache_type=CacheType.EVENT_LIST,
        parts=parts,
        model=EventsResponse,
        loader=partial(
            get_events_service,
            content_filter=content_filter,
            from_date=from_date,
            to_date=to_date,
            language=language,
            restrict_group_ids=restrict_group_ids,
            fallback=fallback,
            should_include_unfollowed=should_include_unfollowed,
            should_include_past=should_include_past,
            skip=skip,
            limit=limit,
            token=token,
        ),
        timeout=_timeout(),
        user_identity=await cache_identity_from_token(token),
    )


async def get_event_by_id_service_cached(
    event_id: UUID,
    language: Optional[str] = None,
    token: Optional[str] = None,
) -> EventDTO:
    return await cached_response(
        cache_type=CacheType.EVENT_DETAIL,
        parts=[event_id, language],
        model=EventDTO,
        loader=partial(
            get_event_by_id_service,
            event_id=event_id,
            language=language,
            token=token,
        ),
        timeout=_timeout(),
        user_identity=await cache_identity_from_token(token),
    )


async def get_featured_events_service_cached(
    language: Optional[str] = None,
    limit: int = 10,
    token: Optional[str] = None,
) -> List[EventDTO]:
    def _load() -> _FeaturedEvents:
        return _FeaturedEvents(
            events=get_featured_events_service(language=language, limit=limit, token=token)
        )

    wrapped = await cached_response(
        cache_type=CacheType.EVENT_FEATURED,
        parts=[language, limit],
        model=_FeaturedEvents,
        loader=_load,
        timeout=_timeout(),
        user_identity=await cache_identity_from_token(token),
    )
    return wrapped.events


async def invalidate_user_event_caches(token: Optional[str]) -> int:
    """Clear the caller's event entries after they join, leave or switch."""
    return await invalidate_user_namespaces(
        EVENT_CACHE_TYPES, await cache_identity_from_token(token)
    )


async def get_events_today_service_cached(
    timezone: Optional[str] = None,
    group_id: Optional[UUID] = None,
    language: Optional[str] = None,
    should_include_unfollowed: bool = False,
    skip: int = 0,
    limit: int = 20,
    token: Optional[str] = None,
) -> EventsResponse:
    """Today's events, through the same cache as the general listing.

    The underlying service is a thin wrapper that resolves "today" in the
    caller's timezone and then runs the ordinary query, so this resolves the
    bounds and reuses the cached list. Those bounds are part of the key, which
    is what makes entries roll over by themselves at midnight in each
    timezone rather than serving yesterday.
    """
    from_date, to_date = get_day_bounds_in_timezone(timezone)
    return await get_events_service_cached(
        content_filter=EventContentFilter(group_id=group_id),
        from_date=from_date,
        to_date=to_date,
        language=language,
        fallback=True,
        should_include_unfollowed=should_include_unfollowed,
        skip=skip,
        limit=limit,
        token=token,
    )
