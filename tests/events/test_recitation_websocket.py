import json
from unittest.mock import AsyncMock, call, patch
from uuid import uuid4

import pytest

from pecha_api.events.recitation_websocket import (
    MAX_SETS_PER_SECOND,
    POSITION_TTL_SECONDS,
    RATE_WINDOW_SECONDS,
    RecitationBroadcaster,
    _ALLOW_SET_SCRIPT,
    _RATE_KEY_PATTERN,
    get_broadcaster,
    init_broadcaster,
    position_channel,
    position_rate_key,
    position_revision_key,
    position_state_key,
)


def _broadcaster() -> RecitationBroadcaster:
    broadcaster = RecitationBroadcaster("redis://localhost:6379/0")
    broadcaster.redis = AsyncMock()
    _stub_scan_iter(broadcaster.redis, [])
    return broadcaster


def _stub_scan_iter(redis, keys, seen=None):
    """AsyncMock returns a coroutine; scan_iter has to be an async iterator."""

    def scan_iter(**kwargs):
        if seen is not None:
            seen.update(kwargs)

        async def _iter():
            for key in keys:
                yield key

        return _iter()

    redis.scan_iter = scan_iter


class TestRecitationBroadcasterLifecycle:

    @pytest.mark.asyncio
    async def test_initialization(self):
        broadcaster = RecitationBroadcaster("redis://localhost:6379/0")

        assert broadcaster.redis_url == "redis://localhost:6379/0"
        assert broadcaster.redis is None
        assert broadcaster.connections == {}

    @pytest.mark.asyncio
    async def test_connect_and_disconnect(self):
        broadcaster = RecitationBroadcaster("redis://localhost:6379/0")
        mock_redis = AsyncMock()

        async def mock_from_url(*args, **kwargs):
            return mock_redis

        with patch(
            "pecha_api.events.recitation_websocket.Redis.from_url",
            side_effect=mock_from_url,
        ):
            await broadcaster.connect()
            assert broadcaster.redis is not None

            await broadcaster.disconnect()
            mock_redis.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_wraps_refused_connection(self):
        broadcaster = RecitationBroadcaster("redis://localhost:6379/0")

        with patch(
            "pecha_api.events.recitation_websocket.Redis.from_url",
            side_effect=ConnectionRefusedError("nope"),
        ):
            with pytest.raises(ConnectionError):
                await broadcaster.connect()

    @pytest.mark.asyncio
    async def test_get_broadcaster_requires_initialization(self):
        with patch("pecha_api.events.recitation_websocket.broadcaster", None):
            with pytest.raises(RuntimeError):
                get_broadcaster()

    @pytest.mark.asyncio
    async def test_init_broadcaster_sets_global(self):
        mock_redis = AsyncMock()

        async def mock_from_url(*args, **kwargs):
            return mock_redis

        _stub_scan_iter(mock_redis, [])

        with patch(
            "pecha_api.events.recitation_websocket.Redis.from_url",
            side_effect=mock_from_url,
        ):
            created = await init_broadcaster("redis://localhost:6379/0")

        assert get_broadcaster() is created

    @pytest.mark.asyncio
    async def test_init_broadcaster_sweeps_rate_keys(self):
        mock_redis = AsyncMock()
        stale = f"recitation:event:{uuid4()}:rate"
        _stub_scan_iter(mock_redis, [stale])
        mock_redis.delete.return_value = 1

        async def mock_from_url(*args, **kwargs):
            return mock_redis

        with patch(
            "pecha_api.events.recitation_websocket.Redis.from_url",
            side_effect=mock_from_url,
        ):
            await init_broadcaster("redis://localhost:6379/0")

        mock_redis.delete.assert_awaited_once_with(stale)

    @pytest.mark.asyncio
    async def test_add_and_remove_connection(self):
        broadcaster = _broadcaster()
        event_id, user_id = uuid4(), uuid4()
        websocket = AsyncMock()

        broadcaster.add_connection(event_id, user_id, websocket)
        assert broadcaster.connections[event_id][user_id] is websocket
        assert broadcaster.get_connected_users(event_id) == {user_id: websocket}

        broadcaster.remove_connection(event_id, user_id)
        assert event_id not in broadcaster.connections


class TestRecitationPositionSnapshot:

    @pytest.mark.asyncio
    async def test_broadcast_position_snapshots_then_publishes(self):
        broadcaster = _broadcaster()
        broadcaster.redis.eval.return_value = 57
        event_id = uuid4()

        await broadcaster.broadcast_position(
            event_id=event_id,
            text_id="text-7",
            segment_id="seg-1",
            index=12,
            round_number=3,
            server_time="2026-09-14T09:30:00Z",
        )

        # One atomic script, not INCR-then-HSET: interleaved round trips let a
        # lower revision's write land last and leave the snapshot behind.
        script, key_count, *args = broadcaster.redis.eval.await_args.args
        assert "INCR" in script and "HSET" in script
        assert key_count == 2
        assert args[:2] == [position_state_key(event_id), position_revision_key(event_id)]
        assert args[2:] == ["text-7", "seg-1", "12", "3", "2026-09-14T09:30:00Z",
                            str(POSITION_TTL_SECONDS)]
        broadcaster.redis.hset.assert_not_awaited()

        channel, raw = broadcaster.redis.publish.await_args.args
        assert channel == position_channel(event_id)
        assert json.loads(raw) == {
            "type": "position",
            "event_id": str(event_id),
            "text_id": "text-7",
            "segment_id": "seg-1",
            "index": 12,
            "round_number": 3,
            "server_time": "2026-09-14T09:30:00Z",
            "revision": 57,
        }

    @pytest.mark.asyncio
    async def test_snapshot_failure_does_not_block_broadcast(self):
        broadcaster = _broadcaster()
        broadcaster.redis.eval.side_effect = Exception("redis down")

        await broadcaster.broadcast_position(
            event_id=uuid4(),
            text_id="text-7",
            segment_id="seg-1",
            index=None,
            round_number=None,
            server_time="2026-09-14T09:30:00Z",
        )

        broadcaster.redis.publish.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_position_returns_stored_frame(self):
        broadcaster = _broadcaster()
        event_id = uuid4()
        broadcaster.redis.hgetall.return_value = {
            "text_id": "text-7",
            "segment_id": "seg-9",
            "index": "4",
            "round_number": "2",
            "updated_at": "2026-09-14T09:30:00Z",
            "revision": "57",
        }

        assert await broadcaster.get_position(event_id) == {
            "type": "position",
            "event_id": str(event_id),
            "text_id": "text-7",
            "segment_id": "seg-9",
            "index": 4,
            "round_number": 2,
            "server_time": "2026-09-14T09:30:00Z",
            "revision": 57,
        }

    @pytest.mark.asyncio
    async def test_get_position_handles_blank_and_unparsable_numbers(self):
        broadcaster = _broadcaster()
        broadcaster.redis.hgetall.return_value = {
            "text_id": "text-7",
            "segment_id": "seg-9",
            "index": "",
            "round_number": "not-a-number",
            "updated_at": "2026-09-14T09:30:00Z",
        }

        position = await broadcaster.get_position(uuid4())

        assert position["index"] is None
        assert position["round_number"] is None

    @pytest.mark.asyncio
    async def test_get_position_returns_none_when_unset_or_unreadable(self):
        broadcaster = _broadcaster()

        broadcaster.redis.hgetall.return_value = {}
        assert await broadcaster.get_position(uuid4()) is None

        broadcaster.redis.hgetall.return_value = {"segment_id": ""}
        assert await broadcaster.get_position(uuid4()) is None

        broadcaster.redis.hgetall.side_effect = Exception("redis down")
        assert await broadcaster.get_position(uuid4()) is None

    @pytest.mark.asyncio
    async def test_get_position_tolerates_snapshot_without_text_id(self):
        """A hash written before text_id existed still resyncs a client; the
        text is simply unknown until the operator's next click."""
        broadcaster = _broadcaster()
        broadcaster.redis.hgetall.return_value = {
            "segment_id": "seg-9",
            "index": "4",
            "round_number": "2",
            "updated_at": "2026-09-14T09:30:00Z",
        }

        assert (await broadcaster.get_position(uuid4()))["text_id"] is None

    @pytest.mark.asyncio
    async def test_clear_position_deletes_snapshot(self):
        broadcaster = _broadcaster()
        event_id = uuid4()

        assert await broadcaster.clear_position(event_id) is True

        broadcaster.redis.delete.assert_awaited_once_with(position_state_key(event_id))

    @pytest.mark.asyncio
    async def test_clear_position_reports_failure(self):
        """The caller has to be able to tell a cleared snapshot from a stale one
        still waiting to greet the next joiner."""
        broadcaster = _broadcaster()
        broadcaster.redis.delete.side_effect = Exception("redis down")

        assert await broadcaster.clear_position(uuid4()) is False

    @pytest.mark.asyncio
    async def test_session_ended_reports_failure(self):
        broadcaster = _broadcaster()
        broadcaster.redis.publish.side_effect = Exception("redis down")

        assert await broadcaster.broadcast_session_ended(uuid4()) is False

    @pytest.mark.asyncio
    async def test_broadcast_session_ended_publishes(self):
        broadcaster = _broadcaster()
        event_id = uuid4()

        assert await broadcaster.broadcast_session_ended(event_id) is True

        channel, raw = broadcaster.redis.publish.await_args.args
        assert channel == position_channel(event_id)
        assert json.loads(raw) == {"type": "session_ended", "event_id": str(event_id)}


class TestRecitationRevision:

    @pytest.mark.asyncio
    async def test_revision_comes_from_redis_not_the_clock(self):
        """Ordering has to hold across instances, and two instances' clocks need
        not agree - only the shared counter does."""
        broadcaster = _broadcaster()
        broadcaster.redis.eval.return_value = 58

        revision = await broadcaster.save_position(
            event_id=uuid4(),
            text_id="text-7",
            segment_id="seg-1",
            index=None,
            round_number=None,
            server_time="2026-09-14T09:30:00Z",
        )

        assert revision == 58

    @pytest.mark.asyncio
    async def test_allocation_and_snapshot_are_one_atomic_step(self):
        """Two operators publishing at once must not be able to leave the
        snapshot holding the lower revision's position."""
        broadcaster = _broadcaster()
        broadcaster.redis.eval.return_value = 12

        await broadcaster.save_position(
            event_id=uuid4(),
            text_id="text-7",
            segment_id="seg-1",
            index=None,
            round_number=None,
            server_time="2026-09-14T09:30:00Z",
        )

        broadcaster.redis.eval.assert_awaited_once()
        broadcaster.redis.incr.assert_not_awaited()
        broadcaster.redis.hset.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_revision_is_none_when_redis_fails(self):
        """None means unorderable, and the reader relays rather than dropping."""
        broadcaster = _broadcaster()
        broadcaster.redis.eval.side_effect = Exception("redis down")

        assert await broadcaster.save_position(
            event_id=uuid4(),
            text_id="text-7",
            segment_id="seg-1",
            index=None,
            round_number=None,
            server_time="2026-09-14T09:30:00Z",
        ) is None

    @pytest.mark.asyncio
    async def test_ending_a_session_keeps_the_counter(self):
        """Resetting it would let a reconnecting client's old high-water mark
        swallow the next session's opening frames."""
        broadcaster = _broadcaster()
        event_id = uuid4()

        assert await broadcaster.clear_position(event_id) is True

        broadcaster.redis.delete.assert_awaited_once_with(position_state_key(event_id))

    @pytest.mark.asyncio
    async def test_get_position_tolerates_snapshot_without_revision(self):
        broadcaster = _broadcaster()
        broadcaster.redis.hgetall.return_value = {
            "text_id": "text-7",
            "segment_id": "seg-9",
            "index": "4",
            "round_number": "2",
            "updated_at": "2026-09-14T09:30:00Z",
        }

        assert (await broadcaster.get_position(uuid4()))["revision"] is None


class TestRecitationRateLimit:

    @pytest.mark.asyncio
    async def test_window_is_counted_in_one_round_trip(self):
        broadcaster = _broadcaster()
        broadcaster.redis.eval.return_value = 1
        event_id = uuid4()

        assert await broadcaster.allow_set(event_id) is True
        # The count and its expiry travel together, so no dropped EXPIRE can
        # leave the key windowless and refuse the event forever.
        broadcaster.redis.eval.assert_awaited_once_with(
            _ALLOW_SET_SCRIPT,
            1,
            position_rate_key(event_id),
            str(RATE_WINDOW_SECONDS),
        )
        broadcaster.redis.incr.assert_not_awaited()
        broadcaster.redis.expire.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_allows_at_the_ceiling(self):
        broadcaster = _broadcaster()
        broadcaster.redis.eval.return_value = MAX_SETS_PER_SECOND

        assert await broadcaster.allow_set(uuid4()) is True

    @pytest.mark.asyncio
    async def test_rejects_beyond_ceiling(self):
        broadcaster = _broadcaster()
        broadcaster.redis.eval.return_value = MAX_SETS_PER_SECOND + 1

        assert await broadcaster.allow_set(uuid4()) is False

    @pytest.mark.asyncio
    async def test_fails_open_when_redis_errors(self):
        broadcaster = _broadcaster()
        broadcaster.redis.eval.side_effect = Exception("redis down")

        assert await broadcaster.allow_set(uuid4()) is True


class TestRecitationRateKeySweep:

    @pytest.mark.asyncio
    async def test_deletes_every_matching_key_in_one_call(self):
        broadcaster = _broadcaster()
        keys = [f"recitation:event:{uuid4()}:rate" for _ in range(3)]
        _stub_scan_iter(broadcaster.redis, keys)
        broadcaster.redis.delete.return_value = len(keys)

        assert await broadcaster.clear_rate_keys() == 3
        broadcaster.redis.delete.assert_awaited_once_with(*keys)

    @pytest.mark.asyncio
    async def test_scan_is_scoped_to_rate_keys(self):
        broadcaster = _broadcaster()
        seen = {}
        _stub_scan_iter(broadcaster.redis, [], seen=seen)

        assert await broadcaster.clear_rate_keys() == 0
        # Never KEYS, and never a pattern that could reach state or revisions.
        assert seen["match"] == _RATE_KEY_PATTERN
        assert _RATE_KEY_PATTERN == "recitation:event:*:rate"
        broadcaster.redis.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_deletes_in_batches(self):
        broadcaster = _broadcaster()
        keys = [f"recitation:event:{i}:rate" for i in range(1200)]
        _stub_scan_iter(broadcaster.redis, keys)
        broadcaster.redis.delete.side_effect = [500, 500, 200]

        assert await broadcaster.clear_rate_keys() == 1200
        assert broadcaster.redis.delete.await_count == 3

    @pytest.mark.asyncio
    async def test_never_blocks_startup_when_redis_errors(self):
        broadcaster = _broadcaster()

        def boom(**kwargs):
            raise Exception("redis down")

        broadcaster.redis.scan_iter = boom

        assert await broadcaster.clear_rate_keys() == 0

    @pytest.mark.asyncio
    async def test_no_op_before_connect(self):
        broadcaster = RecitationBroadcaster("redis://localhost:6379/0")

        assert await broadcaster.clear_rate_keys() == 0
