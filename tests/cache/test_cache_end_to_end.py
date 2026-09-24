"""The read-through cycle against an in-memory Redis double.

The other cache tests patch `get_cache_data`/`set_cache` and so never exercise
the real key strings, the JSON round trip, or whether an invalidation pattern
actually matches the keys the writer produced. This runs the real
cache_repository against a stand-in that behaves like Redis, so a mismatch
between how a key is built and how it is later scanned for shows up here.
"""

import fnmatch
from unittest.mock import patch

import pytest
from pydantic import BaseModel

from pecha_api.cache import cache_repository
from pecha_api.cache.cache_admin_service import delete_by_pattern, flush_response_cache
from pecha_api.cache.cache_enums import CacheType
from pecha_api.cache.cached_response import (
    cached_response,
    invalidate_namespace,
    invalidate_user_namespaces,
)

PREFIX = "pecha:"


class FakeRedis:
    """Enough of redis.asyncio for the cache: setex, get, delete, scan_iter."""

    def __init__(self):
        self.store = {}

    async def setex(self, key, ttl, value):
        self.store[key] = value
        return True

    async def get(self, key):
        return self.store.get(key)

    async def delete(self, *keys):
        removed = 0
        for key in keys:
            removed += 1 if self.store.pop(key, None) is not None else 0
        return removed

    async def unlink(self, *keys):
        return await self.delete(*keys)

    async def exists(self, key):
        return 1 if key in self.store else 0

    async def scan_iter(self, match=None, count=None):
        for key in list(self.store):
            if match is None or fnmatch.fnmatch(key, match):
                yield key


class Payload(BaseModel):
    value: str


@pytest.fixture
def redis():
    fake = FakeRedis()
    cache_repository.reset_circuit()
    with patch.object(cache_repository, "get_client", return_value=fake), \
         patch("pecha_api.cache.cache_admin_service.get_client", return_value=fake), \
         patch("pecha_api.cache.cache_repository.config.get", return_value=PREFIX), \
         patch("pecha_api.cache.cache_keys.config.get", return_value=PREFIX), \
         patch("pecha_api.cache.cache_admin_service.config.get", return_value=PREFIX):
        yield fake
    cache_repository.reset_circuit()


def _loader(calls, value="loaded"):
    def load():
        calls.append(value)
        return Payload(value=value)

    return load


async def _read(cache_type=CacheType.PLAN_LIST, parts=("en",), identity=None, calls=None):
    return await cached_response(
        cache_type=cache_type,
        parts=list(parts),
        model=Payload,
        loader=_loader(calls if calls is not None else []),
        timeout=60,
        user_identity=identity,
    )


@pytest.mark.asyncio
async def test_second_read_is_served_from_the_cache(redis):
    calls = []
    first = await _read(calls=calls)
    second = await _read(calls=calls)
    assert first == second == Payload(value="loaded")
    assert calls == ["loaded"], "the second read should not have hit the loader"
    assert len(redis.store) == 1


@pytest.mark.asyncio
async def test_stored_key_carries_the_prefix_and_namespace(redis):
    await _read()
    key = next(iter(redis.store))
    assert key.startswith(f"{PREFIX}plan_list:")


@pytest.mark.asyncio
async def test_invalidating_the_namespace_forces_a_reload(redis):
    calls = []
    await _read(calls=calls)
    removed = await invalidate_namespace(CacheType.PLAN_LIST)
    assert removed == 1
    assert redis.store == {}
    await _read(calls=calls)
    assert calls == ["loaded", "loaded"]


@pytest.mark.asyncio
async def test_different_parts_are_stored_separately(redis):
    await _read(parts=("en",))
    await _read(parts=("bo",))
    assert len(redis.store) == 2


@pytest.mark.asyncio
async def test_one_users_invalidation_leaves_the_others_alone(redis):
    await _read(cache_type=CacheType.EVENT_LIST, identity="iss|alice")
    await _read(cache_type=CacheType.EVENT_LIST, identity="iss|bob")
    await _read(cache_type=CacheType.EVENT_LIST, identity=None)
    assert len(redis.store) == 3

    removed = await invalidate_user_namespaces([CacheType.EVENT_LIST], "iss|alice")
    assert removed == 1
    assert len(redis.store) == 2, "only alice's entry should be gone"

    # And alice reloads while bob still hits.
    calls = []
    await _read(cache_type=CacheType.EVENT_LIST, identity="iss|alice", calls=calls)
    await _read(cache_type=CacheType.EVENT_LIST, identity="iss|bob", calls=calls)
    assert calls == ["loaded"]


@pytest.mark.asyncio
async def test_flush_clears_the_cache_but_not_the_realtime_keys(redis):
    await _read(cache_type=CacheType.PLAN_LIST)
    await _read(cache_type=CacheType.EVENT_LIST)
    # Live recitation state shares the Redis instance and is not cache.
    redis.store["recitation:event:1:state"] = "live"
    redis.store["chat:room:1:presence"] = "someone"

    removed = await flush_response_cache()

    assert removed == 2
    assert set(redis.store) == {"recitation:event:1:state", "chat:room:1:presence"}


@pytest.mark.asyncio
async def test_namespace_flush_leaves_other_namespaces_intact(redis):
    await _read(cache_type=CacheType.PLAN_LIST)
    await _read(cache_type=CacheType.EVENT_LIST)

    removed = await flush_response_cache(cache_type=CacheType.PLAN_LIST)

    assert removed == 1
    assert all(":event_list:" in key for key in redis.store)


@pytest.mark.asyncio
async def test_a_flushed_entry_is_rebuilt_on_the_next_read(redis):
    """What "flush resets the cache" means in practice."""
    calls = []
    await _read(calls=calls)
    await flush_response_cache()
    assert redis.store == {}
    await _read(calls=calls)
    assert calls == ["loaded", "loaded"]
    assert len(redis.store) == 1


@pytest.mark.asyncio
async def test_delete_by_pattern_batches_without_scanning_everything(redis):
    for index in range(1200):
        redis.store[f"{PREFIX}plan_list:anon:{index}"] = "x"
    redis.store[f"{PREFIX}event_list:anon:keep"] = "x"

    removed = await delete_by_pattern(f"{PREFIX}plan_list:*")

    assert removed == 1200
    assert set(redis.store) == {f"{PREFIX}event_list:anon:keep"}
