import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pecha_api.cache.cache_enums import CacheType
from pecha_api.events.events_cache_service import (
    invalidate_event_detail_cache_for_event,
    invalidate_event_detail_caches,
    schedule_invalidate_event_detail_caches,
)


@pytest.mark.asyncio
async def test_invalidate_event_detail_caches_delegates_to_namespace():
    with patch(
        "pecha_api.events.events_cache_service.invalidate_namespace",
        new_callable=AsyncMock,
        return_value=1,
    ) as mock_invalidate:
        deleted = await invalidate_event_detail_caches()

    assert deleted == 1
    mock_invalidate.assert_awaited_once_with(CacheType.EVENT_DETAIL)


@pytest.mark.asyncio
async def test_invalidate_event_detail_cache_for_event_scoped_delete():
    event_id = uuid.uuid4()

    with patch(
        "pecha_api.events.events_cache_service.cache_type_enabled",
        return_value=True,
    ), patch(
        "pecha_api.events.events_cache_service.mark_namespace_superseded",
    ) as mock_supersede, patch(
        "pecha_api.events.events_cache_service.delete_by_pattern",
        new_callable=AsyncMock,
        return_value=2,
    ) as mock_delete, patch(
        "pecha_api.events.events_cache_service.resource_scan_pattern",
        return_value="pecha:event_detail:r:abc:*",
    ) as mock_pattern, patch(
        "pecha_api.events.events_cache_service.logger"
    ) as mock_logger:
        deleted = await invalidate_event_detail_cache_for_event(event_id)

    assert deleted == 2
    mock_supersede.assert_called_once_with(CacheType.EVENT_DETAIL)
    mock_pattern.assert_called_once_with(CacheType.EVENT_DETAIL, event_id)
    mock_delete.assert_awaited_once_with("pecha:event_detail:r:abc:*")
    mock_logger.info.assert_called_once()


@pytest.mark.asyncio
async def test_invalidate_event_detail_cache_for_event_queues_when_cache_disabled():
    event_id = uuid.uuid4()

    with patch(
        "pecha_api.events.events_cache_service.cache_type_enabled",
        return_value=False,
    ), patch(
        "pecha_api.events.events_cache_service.mark_namespace_superseded",
    ) as mock_supersede, patch(
        "pecha_api.events.events_cache_service.queue_namespace_invalidation",
    ) as mock_queue, patch(
        "pecha_api.events.events_cache_service.delete_by_pattern",
        new_callable=AsyncMock,
    ) as mock_delete:
        deleted = await invalidate_event_detail_cache_for_event(event_id)

    assert deleted == 0
    mock_supersede.assert_called_once_with(CacheType.EVENT_DETAIL)
    mock_queue.assert_called_once_with(CacheType.EVENT_DETAIL)
    mock_delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalidate_event_detail_cache_for_event_handles_redis_error():
    event_id = uuid.uuid4()

    with patch(
        "pecha_api.events.events_cache_service.cache_type_enabled",
        return_value=True,
    ), patch(
        "pecha_api.events.events_cache_service.mark_namespace_superseded",
    ), patch(
        "pecha_api.events.events_cache_service.delete_by_pattern",
        new_callable=AsyncMock,
        side_effect=RuntimeError("redis down"),
    ), patch(
        "pecha_api.events.events_cache_service.queue_namespace_invalidation",
    ) as mock_queue, patch(
        "pecha_api.events.events_cache_service.note_cache_failure",
    ) as mock_note:
        deleted = await invalidate_event_detail_cache_for_event(event_id)

    assert deleted == 0
    mock_queue.assert_called_once_with(CacheType.EVENT_DETAIL)
    mock_note.assert_called_once()


@pytest.mark.asyncio
async def test_schedule_invalidate_event_detail_caches_runs_in_background():
    event_id = uuid.uuid4()

    with patch(
        "pecha_api.events.events_cache_service.invalidate_event_detail_cache_for_event",
        new_callable=AsyncMock,
    ) as mock_invalidate:
        schedule_invalidate_event_detail_caches(event_id)
        await asyncio.sleep(0)

    mock_invalidate.assert_awaited_once_with(event_id)


def test_schedule_invalidate_event_detail_caches_uses_app_loop_from_sync_thread():
    event_id = uuid.uuid4()
    app_loop = MagicMock()
    app_loop.is_running.return_value = True

    with patch(
        "pecha_api.events.events_cache_service.asyncio.get_running_loop",
        side_effect=RuntimeError,
    ), patch(
        "pecha_api.events.events_cache_service._app_event_loop",
        app_loop,
    ), patch(
        "pecha_api.events.events_cache_service.asyncio.run_coroutine_threadsafe",
    ) as mock_threadsafe:
        schedule_invalidate_event_detail_caches(event_id)

    mock_threadsafe.assert_called_once()
    assert mock_threadsafe.call_args.args[1] is app_loop
