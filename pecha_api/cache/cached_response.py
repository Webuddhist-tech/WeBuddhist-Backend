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
import itertools
import logging
from typing import Callable, Dict, Optional, Sequence, Tuple, Type, TypeVar

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
from pecha_api.cache.cache_repository import (
    cache_enabled,
    cache_is_available,
    cache_type_enabled,
    get_cache_data,
    set_cache,
)

logger = logging.getLogger(__name__)

ModelT = TypeVar("ModelT", bound=BaseModel)

# Namespaces whose invalidation could not be carried out, usually because
# Redis was unreachable at the moment of the write. They are retried on the
# next cache operation, and until one succeeds those namespaces are not served
# from cache at all: an entry a write has already superseded must not come
# back when the cache does. Without this a CMS edit made during a Redis blip
# would go on showing the old content for the whole 3.5h timeout.
#
# Each debt carries a mark. A sweep takes many round trips - SCAN, then
# UNLINK, repeatedly - so another write can fail and re-mark the same
# namespace while one is in flight, and that sweep, which began before the
# second write, proves nothing about what the second write superseded.
# Clearing a debt is therefore conditional on its mark still being the one the
# sweep set out to settle.
#
# This is per-process. Another instance that never attempted the write knows
# nothing about the debt and can still serve its own stale entry until the
# timeout - the durable version of this needs a queue, which is more machinery
# than the failure deserves.
_pending_invalidations: Dict[CacheType, int] = {}
_invalidation_marks = itertools.count()


def _mark_pending(cache_type: CacheType) -> None:
    """Record that this namespace is owed an eviction, under a fresh mark."""
    _pending_invalidations[cache_type] = next(_invalidation_marks)


def _settle_pending(cache_type: CacheType, mark: Optional[int]) -> None:
    """Clear the debt, unless it was re-marked while the sweep was running."""
    if _pending_invalidations.get(cache_type) != mark:
        return
    _pending_invalidations.pop(cache_type, None)


async def _drain_pending_invalidations() -> None:
    """Retry invalidations that could not be carried out earlier."""
    if not _pending_invalidations or not cache_is_available():
        return
    for cache_type in list(_pending_invalidations):
        mark = _pending_invalidations.get(cache_type)
        try:
            deleted = await delete_by_pattern(namespace_scan_pattern(cache_type))
        except Exception as cache_error:
            logger.error("Retry of invalidation for %s failed: %s", cache_type.value, cache_error)
            return
        _settle_pending(cache_type, mark)
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
    # Switched off: no key, no Redis round trip, no pending-invalidation
    # bookkeeping. The endpoint behaves exactly as it did before it was cached.
    if not cache_type_enabled(cache_type):
        if asyncio.iscoroutinefunction(loader):
            return await loader()
        return await run_in_threadpool(loader)

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


async def _invalidate_namespace(cache_type: CacheType) -> Tuple[int, bool]:
    """Sweep one namespace. Returns the number removed and whether it worked."""
    # The mark this sweep settles, read before the first await: anything
    # marked after this point is a debt the sweep cannot have paid.
    if not cache_type_enabled(cache_type):
        # Nothing new is written to this namespace while it is switched off,
        # but whatever was written before the switch is still there, still
        # inside its timeout. Sweeping now would cost a SCAN loop per write
        # against the Redis this switch exists to keep out of the request path,
        # so the debt is recorded instead and drained on the next read that
        # finds the cache available. Until then `_pending_invalidations` makes
        # reads of this namespace skip the cache rather than serve an entry the
        # sweep has not reached.
        #
        # Only for a namespace switched off on its own. With the master switch
        # off there is no cache in the request path at all, and turning the
        # whole thing back on is an operator action that carries its own flush.
        if cache_enabled():
            _mark_pending(cache_type)
        return 0, True

    mark = _pending_invalidations.get(cache_type)
    # Attempted even when the breaker is open. The breaker exists to stop
    # reads paying a timeout each; an invalidation that is skipped is not
    # deferred, it is lost, and these namespaces hold content for hours.
    try:
        deleted = await delete_by_pattern(namespace_scan_pattern(cache_type))
    except Exception as cache_error:
        _mark_pending(cache_type)
        logger.error(
            "Could not invalidate cache namespace %s (queued for retry): %s",
            cache_type.value,
            cache_error,
        )
        return 0, False
    _settle_pending(cache_type, mark)
    logger.info("Invalidated %d cache entries in %s", deleted, cache_type.value)
    return deleted, True


async def invalidate_namespace(cache_type: CacheType) -> int:
    """Drop every cached entry of one type. Returns the number removed.

    Never raises. This runs on write paths - publishing a series, joining an
    event - and a write that succeeded must not be reported as failed because
    the cache could not be reached afterwards. The cost of swallowing it is a
    stale entry until its timeout, which is exactly what the timeout is for.
    """
    deleted, _ = await _invalidate_namespace(cache_type)
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
        # The sweep reports its own outcome rather than it being read back off
        # the pending set, where a concurrent write's failure would look like
        # this one's.
        deleted, succeeded = await _invalidate_namespace(cache_type)
        total += deleted
        if not succeeded:
            for queued in remaining:
                _mark_pending(queued)
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
        if not cache_type_enabled(cache_type):
            continue
        try:
            total += await delete_by_pattern(user_scan_pattern(cache_type, user_identity))
        except Exception as cache_error:
            logger.error(
                "Could not invalidate %s for one user: %s", cache_type.value, cache_error
            )
    return total
