"""Shared cache for openpecha segment lookups.

A segment body is upstream content: the same text for every reader, changed
only by an edit in openpecha. Resolving one costs an HTTP round trip, and a
plan day resolves one per segment across all of its subtasks - so without a
cache here, every reader of every day re-fetches the same segments, and all of
it queues through the single openpecha concurrency gate in `external_clients`.
That gate is narrow on purpose, which makes repeated work expensive in latency
rather than just in bandwidth.

Two things keep that traffic down:

* Entries are keyed by segment id alone. Nothing per-user goes in the key,
  because nothing about a segment body is per-user - one reader's fetch serves
  everyone else's, across every endpoint that resolves segments.
* Concurrent misses for the same id share a single fetch. A cold day opened by
  several readers at once would otherwise issue the same request once per
  reader, and a cold day is exactly when the gate is most contended.

Failures are not cached: `fetch` raising propagates to the caller and nothing
is stored, so an upstream blip is retried by the next reader rather than being
held for the whole timeout. A fetch that succeeds and legitimately has no
content is a real answer and is cached as one.
"""

import asyncio
import logging
from typing import Awaitable, Callable, Dict, Optional, Tuple

from pecha_api import config
from pecha_api.cache.cache_enums import CacheType
from pecha_api.cache.cache_keys import build_cache_key
from pecha_api.cache.cache_repository import (
    cache_type_enabled,
    get_cache_data,
    set_cache,
)

logger = logging.getLogger(__name__)

FetchSegment = Callable[[], Awaitable[Optional[str]]]

# Fetches currently in flight, keyed by the loop that owns the task as well as
# by namespace and segment id. Each entry is removed by the task that owns it
# once it settles, so nothing accumulates.
#
# The loop is part of the key because this module is imported once per process
# but the process runs more than one loop: several services call asyncio.run()
# from worker threads. A task belongs to the loop that created it, and awaiting
# it from another raises rather than joining the fetch - so without the loop in
# the key, one loop's in-flight entry would break the second loop's lookup
# instead of saving it a round trip.
_FlightKey = Tuple[int, CacheType, str]
_in_flight: Dict[_FlightKey, "asyncio.Task[Optional[str]]"] = {}


def _timeout() -> int:
    return config.get_int("CACHE_SEGMENT_TIMEOUT")


def _hash_key(cache_type: CacheType, segment_id: str) -> str:
    return build_cache_key(cache_type=cache_type, parts=[segment_id])


async def cached_segment_value(
    cache_type: CacheType,
    segment_id: str,
    fetch: FetchSegment,
) -> Optional[str]:
    """Return the cached value for `segment_id`, resolving it on a miss.

    `fetch` runs at most once per id across concurrent callers, and anything it
    raises reaches every one of them untouched - the caller decides what a
    failed segment means, as it did before this cache existed.
    """
    if not cache_type_enabled(cache_type):
        return await fetch()

    hash_key = _hash_key(cache_type, segment_id)
    cached = await get_cache_data(hash_key=hash_key)
    # Stored wrapped, so that a segment whose real value is null round-trips as
    # itself rather than as a miss that re-fetches it every time.
    if isinstance(cached, dict) and "value" in cached:
        return cached["value"]

    return await _fetch_once(cache_type, segment_id, hash_key, fetch)


async def _fetch_once(
    cache_type: CacheType,
    segment_id: str,
    hash_key: str,
    fetch: FetchSegment,
) -> Optional[str]:
    """Run `fetch` for this id, or join the run already under way on this loop."""
    flight_key = (id(asyncio.get_running_loop()), cache_type, segment_id)
    task = _in_flight.get(flight_key)
    if task is None:
        task = asyncio.create_task(_fetch_and_store(hash_key, fetch))
        _in_flight[flight_key] = task
        task.add_done_callback(lambda settled: _release(flight_key, settled))

    # Shielded: this fetch belongs to everyone waiting on it, so one caller
    # giving up - a disconnect, a timeout further up - must not cancel it out
    # from under the others.
    return await asyncio.shield(task)


def _release(
    flight_key: _FlightKey, task: "asyncio.Task[Optional[str]]"
) -> None:
    _in_flight.pop(flight_key, None)
    # Retrieving the exception marks it seen. Without this, a fetch whose
    # waiters all went away before it settled is reported by the event loop as
    # an exception that was never retrieved, which is noise: the waiters
    # leaving is the reason nobody read it.
    if not task.cancelled():
        task.exception()


async def _fetch_and_store(hash_key: str, fetch: FetchSegment) -> Optional[str]:
    value = await fetch()
    await set_cache(
        hash_key=hash_key, value={"value": value}, cache_time_out=_timeout()
    )
    return value
