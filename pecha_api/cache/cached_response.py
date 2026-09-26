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
# Bumped when a namespace is invalidated, before the sweep. A reader that
# loaded before the bump must not store afterwards: the sweep has already
# deleted the old entry, and writing it back would outlive every pending
# invalidation. Per-process, like the debt above.
_namespace_epochs: Dict[CacheType, int] = {}
# User-scoped deletions that could not run (breaker open, or Redis error).
# Keyed by (namespace, identity); "" is the anonymous segment. Drained before
# the next read of that user's entry, which is skipped until the deletion lands.
_pending_user_invalidations: Dict[Tuple[CacheType, str], int] = {}


def _user_debt_key(
    cache_type: CacheType, user_identity: Optional[str]
) -> Tuple[CacheType, str]:
    return cache_type, user_identity if user_identity is not None else ""


def _note_namespace_changed(cache_type: CacheType) -> None:
    _namespace_epochs[cache_type] = _namespace_epochs.get(cache_type, 0) + 1


def _namespace_epoch(cache_type: CacheType) -> int:
    return _namespace_epochs.get(cache_type, 0)


def _mark_user_pending(cache_type: CacheType, user_identity: Optional[str]) -> None:
    _pending_user_invalidations[_user_debt_key(cache_type, user_identity)] = next(
        _invalidation_marks
    )


def _mark_pending(cache_type: CacheType) -> None:
    """Record that this namespace is owed an eviction, under a fresh mark."""
    _pending_invalidations[cache_type] = next(_invalidation_marks)


def _settle_pending(cache_type: CacheType, mark: Optional[int]) -> None:
    """Clear the debt, unless it was re-marked while the sweep was running."""
    if _pending_invalidations.get(cache_type) != mark:
        return
    _pending_invalidations.pop(cache_type, None)


async def _drain_pending_invalidations() -> None:
    """Retry invalidations that could not be carried out earlier.

    A namespace that is currently switched off is left owed. Its debt is not
    urgent - nothing reads it while it is off - and sweeping it here would
    charge its SCAN to a read of some unrelated namespace, which is the exact
    cost switching it off was meant to avoid. It is paid on the first read
    after it is switched back on, before anything is read back.
    """
    if not _pending_invalidations or not cache_is_available():
        return
    for cache_type in list(_pending_invalidations):
        if not cache_type_enabled(cache_type):
            continue
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


async def _drain_pending_user_invalidations() -> None:
    """Retry user-scoped deletions that were skipped or failed earlier."""
    if not _pending_user_invalidations or not cache_is_available():
        return
    for key in list(_pending_user_invalidations):
        cache_type, identity = key
        if not cache_type_enabled(cache_type):
            continue
        mark = _pending_user_invalidations.get(key)
        try:
            await delete_by_pattern(user_scan_pattern(cache_type, identity or None))
        except Exception as cache_error:
            logger.error(
                "Retry of user invalidation for %s failed: %s",
                cache_type.value,
                cache_error,
            )
            return
        if _pending_user_invalidations.get(key) != mark:
            continue
        _pending_user_invalidations.pop(key, None)
        logger.info("Retried user invalidation for %s", cache_type.value)


def _read_is_blocked(cache_type: CacheType, user_identity: Optional[str]) -> bool:
    if cache_type in _pending_invalidations:
        return True
    return _user_debt_key(cache_type, user_identity) in _pending_user_invalidations


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
    await _drain_pending_user_invalidations()
    # A namespace or user we still owe an eviction for is not safe to read:
    # the entry sitting there may be the one a write already replaced.
    # The epoch is taken after the drains and before the load, so a sweep
    # that lands while we are loading makes the store below a no-op.
    epoch = _namespace_epoch(cache_type)
    cached = None if _read_is_blocked(cache_type, user_identity) else await get_cache_data(
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

    if (
        response is not None
        and _namespace_epoch(cache_type) == epoch
        and not _read_is_blocked(cache_type, user_identity)
    ):
        await set_cache(
            hash_key=hash_key,
            value=response.model_dump(mode="json"),
            cache_time_out=timeout,
        )
    return response


async def _invalidate_namespace(cache_type: CacheType) -> Tuple[int, bool]:
    """Sweep one namespace. Returns the number removed and whether it worked."""
    # Before the first await, so a load already in flight sees the bump and
    # refuses to write its (now superseded) value back after this sweep.
    _note_namespace_changed(cache_type)
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
                _note_namespace_changed(queued)
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
    if not cache_enabled():
        return 0
    total = 0
    for cache_type in cache_types:
        if not cache_type_enabled(cache_type):
            continue
        # The breaker exists so reads do not each pay a timeout. Skipping the
        # deletion without a debt would leave the old progress in place until
        # the entry expired, which is the failure the deletion was meant to
        # prevent. Record it and retry on the next read.
        if not cache_is_available():
            _mark_user_pending(cache_type, user_identity)
            logger.error(
                "Cache unreachable; queued %s invalidation for one user",
                cache_type.value,
            )
            continue
        key = _user_debt_key(cache_type, user_identity)
        mark = _pending_user_invalidations.get(key)
        try:
            total += await delete_by_pattern(user_scan_pattern(cache_type, user_identity))
        except Exception as cache_error:
            _mark_user_pending(cache_type, user_identity)
            logger.error(
                "Could not invalidate %s for one user (queued for retry): %s",
                cache_type.value,
                cache_error,
            )
            continue
        if _pending_user_invalidations.get(key) == mark:
            _pending_user_invalidations.pop(key, None)
    return total
