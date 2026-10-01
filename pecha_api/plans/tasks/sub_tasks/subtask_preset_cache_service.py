"""Cached reads for subtask presets.

A preset belongs to one subtask and changes only through the CMS, so the key
is just the subtask id and both write paths evict that one entry - no
namespace sweep needed, unlike plans and series where a write moves counts and
ordering on pages the item does not appear on.
"""

from functools import partial
from uuid import UUID

from pecha_api import config
from pecha_api.cache.cache_enums import CacheType
from pecha_api.cache.cache_keys import build_cache_key
from pecha_api.cache.cache_repository import delete_cache
from pecha_api.cache.cached_response import cached_response

from .subtask_preset_response_models import PresetResponse
from .subtask_preset_service import get_preset_service


def _parts(subtask_id: UUID) -> list:
    return [subtask_id]


async def get_preset_service_cached(subtask_id: UUID) -> PresetResponse:
    return await cached_response(
        cache_type=CacheType.SUBTASK_PRESETS,
        parts=_parts(subtask_id),
        model=PresetResponse,
        loader=partial(get_preset_service, subtask_id=subtask_id),
        timeout=config.get_int("CACHE_CONTENT_TIMEOUT"),
    )


async def invalidate_preset_cache(subtask_id: UUID) -> bool:
    return await delete_cache(
        hash_key=build_cache_key(cache_type=CacheType.SUBTASK_PRESETS, parts=_parts(subtask_id))
    )
