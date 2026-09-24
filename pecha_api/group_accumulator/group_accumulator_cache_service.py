"""Cached reads for group accumulators.

Totals move every time somebody submits a count, so these take
`CACHE_SOCIAL_TIMEOUT`: at a group practice the number on screen is a few
seconds behind rather than a few hours. Submitting evicts the submitter's own
entries, so the person who just added their count sees it immediately, while
everyone else's view catches up on the timeout instead of every submission
sweeping the cache the whole group is reading.
"""

from functools import partial
from typing import Optional
from uuid import UUID

from pecha_api import config
from pecha_api.cache.cache_enums import CacheType
from pecha_api.cache.cache_identity import cache_identity_from_token
from pecha_api.cache.cached_response import cached_response
from pecha_api.group_accumulator.group_accumulator_response_models import (
    GroupAccumulatorDetailDTO,
    GroupAccumulatorsResponse,
)
from pecha_api.group_accumulator.group_accumulator_service import (
    get_group_accumulator_service,
    get_group_accumulators_service,
)

GROUP_ACCUMULATOR_CACHE_TYPES = (
    CacheType.GROUP_ACCUMULATOR_LIST,
    CacheType.GROUP_ACCUMULATOR_DETAIL,
)


def _timeout() -> int:
    return config.get_int("CACHE_SOCIAL_TIMEOUT")


async def get_group_accumulators_service_cached(
    group_id: UUID,
    skip: int = 0,
    limit: int = 20,
    token: Optional[str] = None,
    timezone_name: Optional[str] = None,
    language: Optional[str] = None,
) -> GroupAccumulatorsResponse:
    return await cached_response(
        cache_type=CacheType.GROUP_ACCUMULATOR_LIST,
        # Timezone is in the key because "today's total" is a different number
        # either side of midnight somewhere.
        parts=[group_id, skip, limit, timezone_name, language],
        model=GroupAccumulatorsResponse,
        loader=partial(
            get_group_accumulators_service,
            group_id=group_id,
            skip=skip,
            limit=limit,
            token=token,
            timezone_name=timezone_name,
            language=language,
        ),
        timeout=_timeout(),
        user_identity=cache_identity_from_token(token),
    )


async def get_group_accumulator_service_cached(
    group_accumulator_id: UUID,
    timezone_name: Optional[str] = None,
    token: Optional[str] = None,
    language: Optional[str] = None,
) -> GroupAccumulatorDetailDTO:
    return await cached_response(
        cache_type=CacheType.GROUP_ACCUMULATOR_DETAIL,
        parts=[group_accumulator_id, timezone_name, language],
        model=GroupAccumulatorDetailDTO,
        loader=partial(
            get_group_accumulator_service,
            group_accumulator_id=group_accumulator_id,
            timezone_name=timezone_name,
            token=token,
            language=language,
        ),
        timeout=_timeout(),
        user_identity=cache_identity_from_token(token),
    )
