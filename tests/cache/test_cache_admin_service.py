from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from pecha_api.cache.cache_admin_service import flush_response_cache


def _client_with_keys(keys):
    """A Redis double whose scan_iter yields `keys` for the matched pattern."""
    client = MagicMock()
    seen = {}

    async def scan_iter(match=None, count=None):
        seen["match"] = match
        for key in keys:
            yield key

    client.scan_iter = scan_iter
    client.unlink = AsyncMock(side_effect=lambda *k: len(k))
    client.delete = AsyncMock(side_effect=lambda *k: len(k))
    return client, seen


@pytest.mark.asyncio
async def test_flush_deletes_every_prefixed_key():
    client, seen = _client_with_keys(["pecha:aaa", "pecha:bbb", "pecha:ccc"])
    with patch("pecha_api.cache.cache_admin_service.get_client", return_value=client), patch(
        "pecha_api.cache.cache_admin_service.config.get", return_value="pecha:"
    ):
        assert await flush_response_cache() == 3
    assert seen["match"] == "pecha:*"


@pytest.mark.asyncio
async def test_flush_scopes_the_pattern_to_the_cache_prefix():
    """Realtime keys share the Redis instance and must survive a flush."""
    client, seen = _client_with_keys([])
    with patch("pecha_api.cache.cache_admin_service.get_client", return_value=client), patch(
        "pecha_api.cache.cache_admin_service.config.get", return_value="pecha:"
    ):
        await flush_response_cache()
    assert seen["match"] == "pecha:*"
    assert not seen["match"].startswith("*")


@pytest.mark.asyncio
async def test_flush_refuses_when_prefix_is_empty():
    """An empty prefix makes the pattern `*`, which would take chat and
    recitation state with it."""
    client, _ = _client_with_keys(["recitation:event:1:state"])
    with patch("pecha_api.cache.cache_admin_service.get_client", return_value=client), patch(
        "pecha_api.cache.cache_admin_service.config.get", return_value="   "
    ):
        with pytest.raises(HTTPException) as exc:
            await flush_response_cache()
    assert exc.value.status_code == 500
    client.unlink.assert_not_called()
    client.delete.assert_not_called()


@pytest.mark.asyncio
async def test_flush_falls_back_to_delete_when_unlink_missing():
    client, _ = _client_with_keys(["pecha:aaa"])
    client.unlink = AsyncMock(side_effect=Exception("unknown command"))
    with patch("pecha_api.cache.cache_admin_service.get_client", return_value=client), patch(
        "pecha_api.cache.cache_admin_service.config.get", return_value="pecha:"
    ):
        assert await flush_response_cache() == 1
    client.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_flush_reports_503_when_redis_is_unreachable():
    client = MagicMock()

    async def scan_iter(match=None, count=None):
        raise ConnectionError("redis down")
        yield  # pragma: no cover - generator marker

    client.scan_iter = scan_iter
    with patch("pecha_api.cache.cache_admin_service.get_client", return_value=client), patch(
        "pecha_api.cache.cache_admin_service.config.get", return_value="pecha:"
    ):
        with pytest.raises(HTTPException) as exc:
            await flush_response_cache()
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_namespace_flush_scopes_the_pattern_to_that_namespace():
    from pecha_api.cache.cache_enums import CacheType

    client, seen = _client_with_keys([])
    with patch("pecha_api.cache.cache_admin_service.get_client", return_value=client), patch(
        "pecha_api.cache.cache_admin_service.config.get", return_value="pecha:"
    ):
        await flush_response_cache(cache_type=CacheType.SERIES_LIST)
    assert seen["match"] == "pecha:series_list:*"
