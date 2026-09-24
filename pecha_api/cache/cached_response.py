"""Get-or-load around the response cache.

Every cached endpoint goes through `cached_response`, so the serialization,
the failure behaviour and the "never cache an empty result by accident" rules
live in one place rather than being re-decided per endpoint.

The cache is always optional: if Redis is slow, down, or holding something
that no longer parses into the current model, the loader runs and the request
is served. A cache miss is a slow request; a cache error must never be a
failed one.
"""

import asyncio
import logging
from typing import Callable, Optional, Sequence, Type, TypeVar

from pydantic import BaseModel, ValidationError
from starlette.concurrency import run_in_threadpool

from pecha_api.cache.cache_admin_service import delete_by_pattern
from pecha_api.cache.cache_enums import CacheType
from pecha_api.cache.cache_keys import (
    KeyPart,
    build_cache_key,
    namespace_scan_pattern,
    user_scan_pattern,
)
from pecha_api.cache.cache_repository import cache_is_available, get_cache_data, set_cache

logger = logging.getLogger(__name__)

ModelT = TypeVar("ModelT", bound=BaseModel)


async def cached_response(
    cache_type: CacheType,
    parts: Sequence[KeyPart],
    model: Type[ModelT],
    loader: Callable[[], ModelT],
    timeout: int,
    user_identity: Optional[str] = None,
) -> ModelT:
    """Return the cached response for these inputs, or build and store it.

    `loader` does the database work and may be sync or async. A sync one runs
    in a worker thread, so a cache miss does not block the event loop; an
    async one is awaited as it already manages that itself.
    """
    hash_key = build_cache_key(
        cache_type=cache_type, parts=parts, user_identity=user_identity
    )

    cached = await get_cache_data(hash_key=hash_key)
    if isinstance(cached, dict):
        try:
            return model(**cached)
        except ValidationError:
            # Stored by an older deploy whose DTO had a different shape. Treat
            # it as a miss and let the fresh value overwrite it, rather than
            # failing a request over a stale cache entry.
            logger.warning(
                "Discarding unparseable cache entry for %s", cache_type.value
            )

    if asyncio.iscoroutinefunction(loader):
        response = await loader()
    else:
        response = await run_in_threadpool(loader)

    if response is not None:
        await set_cache(
            hash_key=hash_key,
            value=response.model_dump(mode="json"),
            cache_time_out=timeout,
        )
    return response


async def invalidate_namespace(cache_type: CacheType) -> int:
    """Drop every cached entry of one type. Returns the number removed.

    Never raises. This runs on write paths - publishing a series, joining an
    event - and a write that succeeded must not be reported as failed because
    the cache could not be reached afterwards. The cost of swallowing it is a
    stale entry until its timeout, which is exactly what the timeout is for.
    """
    if not cache_is_available():
        # The breaker is open, so there is nothing to invalidate that anyone
        # is reading: every request is going to the database anyway.
        return 0
    try:
        deleted = await delete_by_pattern(namespace_scan_pattern(cache_type))
    except Exception as cache_error:
        logger.error(
            "Could not invalidate cache namespace %s: %s",
            cache_type.value,
            cache_error,
        )
        return 0
    logger.info("Invalidated %d cache entries in %s", deleted, cache_type.value)
    return deleted


async def invalidate_namespaces(cache_types: Sequence[CacheType]) -> int:
    total = 0
    for cache_type in cache_types:
        total += await invalidate_namespace(cache_type)
    return total


async def invalidate_user_namespaces(
    cache_types: Sequence[CacheType],
    user_identity: Optional[str],
) -> int:
    """Drop one user's entries in these namespaces, leaving everyone else's.

    For writes whose effect is confined to the person making them. What such a
    write also changes for others - a participant count, a like total - is
    left to the short timeout on these namespaces rather than paid for with a
    full sweep per write, which under a join storm would evict the cache
    faster than it could be filled.
    """
    if not cache_is_available():
        return 0
    total = 0
    for cache_type in cache_types:
        try:
            total += await delete_by_pattern(user_scan_pattern(cache_type, user_identity))
        except Exception as cache_error:
            logger.error(
                "Could not invalidate %s for one user: %s", cache_type.value, cache_error
            )
    return total
