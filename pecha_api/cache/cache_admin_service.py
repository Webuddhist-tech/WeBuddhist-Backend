"""Flushing the response cache by hand.

Keys are namespaced (`pecha:series_list:<hash>`, see cache_keys.py), so a
flush can be scoped three ways: one key whose hash you have, one namespace, or
everything under the cache prefix.

It deliberately does not use FLUSHDB. The same Redis holds the live recitation
position snapshots, chat presence and the per-event throttle counters, none of
which are cache - wiping them mid-puja would drop every phone in the room back
to no position. Only keys under CACHE_PREFIX are touched.
"""

import logging
from typing import Optional

from fastapi import HTTPException
from starlette import status

from pecha_api import config
from pecha_api.cache.cache_enums import CacheType
from pecha_api.cache.cache_repository import get_client, note_cache_failure

logger = logging.getLogger(__name__)

# Keys per SCAN round trip, and per delete. Large enough to finish quickly on a
# real keyspace, small enough that neither command blocks Redis for long.
SCAN_BATCH_SIZE = 500


async def _delete_batch(client, keys: list) -> int:
    if not keys:
        return 0
    try:
        # UNLINK reclaims memory on a background thread; DELETE blocks Redis
        # while it frees. Older servers may not have it.
        return int(await client.unlink(*keys))
    except Exception:
        return int(await client.delete(*keys))


async def delete_by_pattern(pattern: str) -> int:
    """Delete every key matching `pattern`. Returns the count.

    SCAN, never KEYS: KEYS walks the whole keyspace in one blocking pass, and
    this runs while people are using the app - on every write that invalidates
    a namespace, not just on an admin flush.
    """
    client = get_client()
    deleted = 0
    batch: list = []

    try:
        async for key in client.scan_iter(match=pattern, count=SCAN_BATCH_SIZE):
            batch.append(key)
            if len(batch) >= SCAN_BATCH_SIZE:
                deleted += await _delete_batch(client, batch)
                batch = []
        deleted += await _delete_batch(client, batch)
    except Exception as cache_error:
        # Invalidation runs on write paths; a Redis problem must not fail the
        # write that triggered it. Admin flushes turn this into a 503 instead,
        # via flush_response_cache below.
        # Tell the breaker, so the next few requests skip the cache instead of
        # each paying the same timeout to rediscover that Redis is down.
        note_cache_failure()
        logger.error("Cache delete failed for %r: %s", pattern, cache_error, exc_info=True)
        raise

    return deleted


def _require_prefix() -> str:
    prefix = config.get("CACHE_PREFIX")
    if not prefix or not prefix.strip():
        # Without a prefix the pattern would be `*`, which would take the
        # realtime keys with it. Refuse rather than guess.
        logger.error("Refusing to flush cache: CACHE_PREFIX is empty")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="CACHE_PREFIX is not configured; refusing to flush the cache",
        )
    return prefix


async def flush_response_cache(cache_type: Optional[CacheType] = None) -> int:
    """Delete cached responses - one namespace, or all of them."""
    prefix = _require_prefix()
    pattern = f"{prefix}{cache_type.value}:*" if cache_type else f"{prefix}*"

    try:
        deleted = await delete_by_pattern(pattern)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not reach the cache to flush it",
        )

    logger.warning("Response cache flushed: %d keys removed under %r", deleted, pattern)
    return deleted


async def flush_cache_key(hash_key: str) -> bool:
    """Delete one cached entry by its hash key, for a targeted eviction."""
    from pecha_api.cache.cache_repository import delete_cache

    return await delete_cache(hash_key=hash_key)
