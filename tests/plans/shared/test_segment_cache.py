import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from pecha_api.cache.cache_enums import CacheType
from pecha_api.plans.shared import segment_cache
from pecha_api.plans.shared.segment_cache import cached_segment_value

CONTENT = CacheType.OPENPECHA_SEGMENT_CONTENT


@pytest.fixture(autouse=True)
def clean_in_flight():
    segment_cache._in_flight.clear()
    yield
    segment_cache._in_flight.clear()


def _fetcher(value="upstream", calls=None):
    async def fetch():
        if calls is not None:
            calls.append(value)
        return value

    return fetch


@pytest.mark.asyncio
async def test_a_hit_returns_the_cached_body_without_fetching():
    calls = []
    with patch.object(segment_cache, "get_cache_data", new_callable=AsyncMock,
                      return_value={"value": "cached"}), \
         patch.object(segment_cache, "set_cache", new_callable=AsyncMock) as mock_set:
        result = await cached_segment_value(
            cache_type=CONTENT, segment_id="seg-1", fetch=_fetcher(calls=calls)
        )

    assert result == "cached"
    assert calls == []
    mock_set.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_miss_fetches_once_and_stores_the_result():
    calls = []
    with patch.object(segment_cache, "get_cache_data", new_callable=AsyncMock,
                      return_value=None), \
         patch.object(segment_cache, "set_cache", new_callable=AsyncMock) as mock_set:
        result = await cached_segment_value(
            cache_type=CONTENT, segment_id="seg-1", fetch=_fetcher(calls=calls)
        )

    assert result == "upstream"
    assert calls == ["upstream"]
    assert mock_set.await_args.kwargs["value"] == {"value": "upstream"}


@pytest.mark.asyncio
async def test_concurrent_misses_for_one_segment_share_a_single_fetch():
    """The burst this cache exists for: many readers opening the same cold day."""
    calls = []
    release = asyncio.Event()

    async def slow_fetch():
        calls.append("seg-1")
        await release.wait()
        return "upstream"

    with patch.object(segment_cache, "get_cache_data", new_callable=AsyncMock,
                      return_value=None), \
         patch.object(segment_cache, "set_cache", new_callable=AsyncMock):
        waiters = [
            asyncio.create_task(
                cached_segment_value(
                    cache_type=CONTENT, segment_id="seg-1", fetch=slow_fetch
                )
            )
            for _ in range(5)
        ]
        await asyncio.sleep(0)
        release.set()
        results = await asyncio.gather(*waiters)

    assert results == ["upstream"] * 5
    assert calls == ["seg-1"]


@pytest.mark.asyncio
async def test_different_segments_do_not_share_a_fetch():
    calls = []

    async def fetch_for(segment_id):
        calls.append(segment_id)
        return f"body-{segment_id}"

    with patch.object(segment_cache, "get_cache_data", new_callable=AsyncMock,
                      return_value=None), \
         patch.object(segment_cache, "set_cache", new_callable=AsyncMock):
        results = await asyncio.gather(
            *[
                cached_segment_value(
                    cache_type=CONTENT,
                    segment_id=segment_id,
                    fetch=lambda sid=segment_id: fetch_for(sid),
                )
                for segment_id in ("a", "b")
            ]
        )

    assert results == ["body-a", "body-b"]
    assert sorted(calls) == ["a", "b"]


@pytest.mark.asyncio
async def test_a_failed_fetch_is_not_cached_and_reaches_the_caller():
    async def failing_fetch():
        raise RuntimeError("openpecha is down")

    with patch.object(segment_cache, "get_cache_data", new_callable=AsyncMock,
                      return_value=None), \
         patch.object(segment_cache, "set_cache", new_callable=AsyncMock) as mock_set:
        with pytest.raises(RuntimeError):
            await cached_segment_value(
                cache_type=CONTENT, segment_id="seg-1", fetch=failing_fetch
            )

    mock_set.assert_not_awaited()
    assert segment_cache._in_flight == {}


@pytest.mark.asyncio
async def test_a_segment_with_no_content_is_cached_as_an_answer():
    """None is what upstream said, not a miss - re-asking every time is waste."""
    with patch.object(segment_cache, "get_cache_data", new_callable=AsyncMock,
                      return_value={"value": None}), \
         patch.object(segment_cache, "set_cache", new_callable=AsyncMock):
        calls = []
        result = await cached_segment_value(
            cache_type=CONTENT, segment_id="seg-1", fetch=_fetcher(calls=calls)
        )

    assert result is None
    assert calls == []


@pytest.mark.asyncio
async def test_a_switched_off_namespace_goes_straight_to_the_fetch():
    calls = []
    with patch.object(segment_cache, "cache_type_enabled", return_value=False), \
         patch.object(segment_cache, "get_cache_data", new_callable=AsyncMock) as mock_get, \
         patch.object(segment_cache, "set_cache", new_callable=AsyncMock) as mock_set:
        result = await cached_segment_value(
            cache_type=CONTENT, segment_id="seg-1", fetch=_fetcher(calls=calls)
        )

    assert result == "upstream"
    assert calls == ["upstream"]
    mock_get.assert_not_awaited()
    mock_set.assert_not_awaited()


@pytest.mark.asyncio
async def test_content_and_reference_are_separate_entries_for_one_segment():
    keys = []

    async def record(hash_key):
        keys.append(hash_key)
        return None

    with patch.object(segment_cache, "get_cache_data", side_effect=record), \
         patch.object(segment_cache, "set_cache", new_callable=AsyncMock):
        await cached_segment_value(
            cache_type=CONTENT, segment_id="seg-1", fetch=_fetcher()
        )
        await cached_segment_value(
            cache_type=CacheType.OPENPECHA_SEGMENT_REFERENCE,
            segment_id="seg-1",
            fetch=_fetcher(),
        )

    assert len(keys) == 2
    assert keys[0] != keys[1]


def test_a_second_loop_does_not_join_the_first_loops_fetch():
    """This module is imported once per process, but the process runs more than
    one loop - several services call asyncio.run() from worker threads. A task
    belongs to the loop that created it, so a second loop that picked up the
    first loop's entry would raise on await instead of saving a round trip."""
    stranded = []

    async def _leave_one_in_flight():
        # A task that never settles, so its entry stays in the map for the
        # second loop to trip over.
        async def _never():
            await asyncio.Event().wait()

        task = asyncio.create_task(_never())
        stranded.append(task)
        key = (id(asyncio.get_running_loop()), CONTENT, "seg-shared")
        segment_cache._in_flight[key] = task

    async def _fetch_on_a_fresh_loop():
        with patch.object(segment_cache, "get_cache_data", new_callable=AsyncMock,
                          return_value=None), \
             patch.object(segment_cache, "set_cache", new_callable=AsyncMock):
            return await cached_segment_value(
                cache_type=CONTENT, segment_id="seg-shared", fetch=_fetcher()
            )

    first = asyncio.new_event_loop()
    try:
        first.run_until_complete(_leave_one_in_flight())
        assert len(segment_cache._in_flight) == 1

        # A different loop entirely: it must run its own fetch, not await the
        # task parked above.
        result = asyncio.run(_fetch_on_a_fresh_loop())
        assert result == "upstream"
    finally:
        for task in stranded:
            task.cancel()
        first.close()
