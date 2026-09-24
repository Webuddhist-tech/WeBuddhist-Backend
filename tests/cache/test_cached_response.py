from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel

from pecha_api.cache.cache_enums import CacheType
from pecha_api.cache.cached_response import (
    cached_response,
    invalidate_namespace,
    invalidate_user_namespaces,
)


class Sample(BaseModel):
    value: str
    count: int = 0


def _loader(value="fresh", calls=None):
    def load():
        if calls is not None:
            calls.append(value)
        return Sample(value=value, count=1)

    return load


@pytest.mark.asyncio
async def test_a_hit_returns_the_cached_value_without_loading():
    calls = []
    with patch("pecha_api.cache.cached_response.get_cache_data", new_callable=AsyncMock,
               return_value={"value": "cached", "count": 7}), \
         patch("pecha_api.cache.cached_response.set_cache", new_callable=AsyncMock) as mock_set:
        result = await cached_response(
            cache_type=CacheType.PLAN_LIST, parts=["a"], model=Sample,
            loader=_loader(calls=calls), timeout=60,
        )
    assert result == Sample(value="cached", count=7)
    assert calls == []
    mock_set.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_miss_loads_and_stores():
    with patch("pecha_api.cache.cached_response.get_cache_data", new_callable=AsyncMock,
               return_value=None), \
         patch("pecha_api.cache.cached_response.set_cache", new_callable=AsyncMock) as mock_set:
        result = await cached_response(
            cache_type=CacheType.PLAN_LIST, parts=["a"], model=Sample,
            loader=_loader("fresh"), timeout=123,
        )
    assert result.value == "fresh"
    assert mock_set.await_args.kwargs["cache_time_out"] == 123
    assert mock_set.await_args.kwargs["value"] == {"value": "fresh", "count": 1}


@pytest.mark.asyncio
async def test_an_entry_from_an_older_dto_shape_is_treated_as_a_miss():
    """A deploy that changes a DTO must not start failing requests over
    yesterday's JSON."""
    with patch("pecha_api.cache.cached_response.get_cache_data", new_callable=AsyncMock,
               return_value={"gone": "field"}), \
         patch("pecha_api.cache.cached_response.set_cache", new_callable=AsyncMock):
        result = await cached_response(
            cache_type=CacheType.PLAN_LIST, parts=["a"], model=Sample,
            loader=_loader("rebuilt"), timeout=60,
        )
    assert result.value == "rebuilt"


@pytest.mark.asyncio
async def test_an_async_loader_is_awaited():
    async def load():
        return Sample(value="async")

    with patch("pecha_api.cache.cached_response.get_cache_data", new_callable=AsyncMock,
               return_value=None), \
         patch("pecha_api.cache.cached_response.set_cache", new_callable=AsyncMock):
        result = await cached_response(
            cache_type=CacheType.PLAN_LIST, parts=["a"], model=Sample,
            loader=load, timeout=60,
        )
    assert result.value == "async"


@pytest.mark.asyncio
async def test_a_loader_error_propagates_and_is_not_cached():
    def boom():
        raise ValueError("database is down")

    with patch("pecha_api.cache.cached_response.get_cache_data", new_callable=AsyncMock,
               return_value=None), \
         patch("pecha_api.cache.cached_response.set_cache", new_callable=AsyncMock) as mock_set:
        with pytest.raises(ValueError):
            await cached_response(
                cache_type=CacheType.PLAN_LIST, parts=["a"], model=Sample,
                loader=boom, timeout=60,
            )
    mock_set.assert_not_awaited()


@pytest.mark.asyncio
async def test_two_users_do_not_read_each_others_entries():
    seen = []

    async def fake_get(hash_key):
        seen.append(hash_key)
        return None

    with patch("pecha_api.cache.cached_response.get_cache_data", side_effect=fake_get), \
         patch("pecha_api.cache.cached_response.set_cache", new_callable=AsyncMock):
        for identity in ("iss|alice", "iss|bob"):
            await cached_response(
                cache_type=CacheType.EVENT_LIST, parts=["en"], model=Sample,
                loader=_loader(), timeout=60, user_identity=identity,
            )
    assert seen[0] != seen[1]


@pytest.mark.asyncio
async def test_invalidating_a_namespace_never_raises():
    """It runs on write paths: a write that succeeded must not be reported as
    failed because Redis was unreachable afterwards."""
    with patch("pecha_api.cache.cached_response.cache_is_available", return_value=True), \
         patch("pecha_api.cache.cached_response.delete_by_pattern", new_callable=AsyncMock,
               side_effect=ConnectionError("redis down")):
        assert await invalidate_namespace(CacheType.PLAN_LIST) == 0


@pytest.mark.asyncio
async def test_user_invalidation_targets_only_that_user():
    with patch("pecha_api.cache.cached_response.cache_is_available", return_value=True), \
         patch("pecha_api.cache.cached_response.delete_by_pattern", new_callable=AsyncMock,
               return_value=3) as mock_delete:
        deleted = await invalidate_user_namespaces([CacheType.EVENT_LIST], "iss|alice")
    assert deleted == 3
    pattern = mock_delete.await_args.args[0]
    assert pattern.endswith(":*")
    assert ":anon:" not in pattern


@pytest.mark.asyncio
async def test_invalidation_is_skipped_while_the_breaker_is_open():
    with patch("pecha_api.cache.cached_response.cache_is_available", return_value=False), \
         patch("pecha_api.cache.cached_response.delete_by_pattern", new_callable=AsyncMock) as mock_delete:
        assert await invalidate_namespace(CacheType.PLAN_LIST) == 0
    mock_delete.assert_not_awaited()
