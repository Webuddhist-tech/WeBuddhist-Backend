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
from typing import Callable, Optional, Sequence, Set, Type, TypeVar

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

# Namespaces whose invalidation could not be carried out, usually because
# Redis was unreachable at the moment of the write. They are retried on the
# next cache operation, and until one succeeds those namespaces are not served
# from cache at all: an entry a write has already superseded must not come
# back when the cache does. Without this a CMS edit made during a Redis blip
# would go on showing the old content for the whole 3.5h timeout.
#
# This is per-process. Another instance that never attempted the write knows
# nothing about the debt and can still serve its own stale entry until the
# timeout - the durable version of this needs a queue, which is more machinery
# than the failure deserves.
_pending_invalidations: Set[CacheType] = set()


async def _drain_pending_invalidations() -> None:
    """Retry invalidations that could not be carried out earlier."""
    if not _pending_invalidations or not cache_is_available():
        return
    for cache_type in list(_pending_invalidations):
        try:
            deleted = await delete_by_pattern(namespace_scan_pattern(cache_type))
        except Exception as cache_error:
            logger.error("Retry of invalidation for %s failed: %s", cache_type.value, cache_error)
            return
        _pending_invalidations.discard(cache_type)
        logger.info(
            "Retried invalidation for %s: %d entries removed", cache_type.value, deleted
        )


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

    await _drain_pending_invalidations()
    # A namespace we still owe an eviction for is not safe to read: the entry
    # sitting there may be the one a write already replaced.
    cached = None if cache_type in _pending_invalidations else await get_cache_data(
        hash_key=hash_key
    )
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
    # Attempted even when the breaker is open. The breaker exists to stop
    # reads paying a timeout each; an invalidation that is skipped is not
    # deferred, it is lost, and these namespaces hold content for hours.
    try:
        deleted = await delete_by_pattern(namespace_scan_pattern(cache_type))
    except Exception as cache_error:
        _pending_invalidations.add(cache_type)
        logger.error(
            "Could not invalidate cache namespace %s (queued for retry): %s",
            cache_type.value,
            cache_error,
        )
        return 0
    _pending_invalidations.discard(cache_type)
    logger.info("Invalidated %d cache entries in %s", deleted, cache_type.value)
    return deleted


async def invalidate_namespaces(cache_types: Sequence[CacheType]) -> int:
    """Invalidate several namespaces, stopping at the first sign Redis is gone.

    A plan write touches eight namespaces. Attempting all eight against an
    unreachable Redis would cost the author eight connect timeouts on one
    save, so the first failure is taken as the answer for the rest: they are
    queued rather than retried here, which costs nothing now and loses
    nothing, since the queue is drained on the next cache operation.
    """
    total = 0
    remaining = list(cache_types)
    while remaining:
        cache_type = remaining.pop(0)
        total += await invalidate_namespace(cache_type)
        if cache_type in _pending_invalidations:
            _pending_invalidations.update(remaining)
            logger.error(
                "Cache unreachable; queued %d further namespaces for retry", len(remaining)
            )
            break
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
