from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pecha_api.cache import cache_repository


@pytest.fixture(autouse=True)
def _closed_breaker():
    cache_repository.reset_circuit()
    yield
    cache_repository.reset_circuit()


@pytest.mark.asyncio
async def test_a_failure_opens_the_breaker_and_later_calls_skip_redis():
    """A Redis that is down must cost one timeout, not one per request."""
    client = MagicMock()
    client.get = AsyncMock(side_effect=ConnectionError("down"))
    with patch.object(cache_repository, "get_client", return_value=client), \
         patch("pecha_api.cache.cache_repository.config.get_float", return_value=10.0), \
         patch("pecha_api.cache.cache_repository.config.get", return_value="pecha:"):
        assert await cache_repository.get_cache_data("k") is None
        assert client.get.await_count == 1
        assert not cache_repository.cache_is_available()

        for _ in range(5):
            assert await cache_repository.get_cache_data("k") is None
        # Still one: the breaker answered the rest.
        assert client.get.await_count == 1


@pytest.mark.asyncio
async def test_writes_are_skipped_while_the_breaker_is_open():
    client = MagicMock()
    client.setex = AsyncMock(side_effect=ConnectionError("down"))
    with patch.object(cache_repository, "get_client", return_value=client), \
         patch("pecha_api.cache.cache_repository.config.get_float", return_value=10.0), \
         patch("pecha_api.cache.cache_repository.config.get", return_value="pecha:"):
        assert await cache_repository.set_cache("k", "v", 60) is False
        assert await cache_repository.set_cache("k", "v", 60) is False
    assert client.setex.await_count == 1


@pytest.mark.asyncio
async def test_resetting_closes_the_breaker():
    cache_repository.note_cache_failure()
    assert not cache_repository.cache_is_available()
    cache_repository.reset_circuit()
    assert cache_repository.cache_is_available()
