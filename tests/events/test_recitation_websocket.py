import asyncio
import json
import re
from typing import Any, AsyncIterator, Dict, Iterable, List, Optional
from unittest.mock import AsyncMock, call, patch
from uuid import uuid4

import pytest

from pecha_api.events.recitation_websocket import (
    INSTANCE_LEASE_PREFIX,
    MAX_SETS_PER_SECOND,
    POSITION_TTL_SECONDS,
    RATE_WINDOW_SECONDS,
    RecitationBroadcaster,
    _ALLOW_SET_SCRIPT,
    _INSTANCE_ID,
    _PRESENCE_BROADCAST_SCRIPT,
    _PRESENCE_COUNT_SCRIPT,
    _RATE_KEY_PATTERN,
    get_broadcaster,
    init_broadcaster,
    instance_lease_key,
    position_channel,
    position_rate_key,
    position_revision_key,
    position_state_key,
    presence_field,
    presence_key,
)


def _broadcaster() -> RecitationBroadcaster:
    broadcaster = RecitationBroadcaster("redis://localhost:6379/0")
    broadcaster.redis = AsyncMock()
    _stub_scan_iter(broadcaster.redis, [])
    return broadcaster


def _stub_scan_iter(
    redis: Any,
    keys: Iterable[str],
    seen: Optional[Dict[str, Any]] = None,
) -> None:
    """AsyncMock returns a coroutine; scan_iter has to be an async iterator."""

    def scan_iter(**kwargs: Any) -> AsyncIterator[str]:
        if seen is not None:
            seen.update(kwargs)

        async def _iter() -> AsyncIterator[str]:
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
        await created.disconnect()

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
        await get_broadcaster().disconnect()

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


class TestRecitationPresence:

    @pytest.mark.asyncio
    async def test_mark_present_records_this_instance(self):
        broadcaster = _broadcaster()
        event_id, user_id = uuid4(), uuid4()

        token = await broadcaster.mark_present(event_id, user_id)

        field = presence_field(user_id, token)
        broadcaster.redis.hset.assert_awaited_once_with(
            presence_key(event_id), field, _INSTANCE_ID
        )
        assert broadcaster._roster[event_id] == {field}

    @pytest.mark.asyncio
    async def test_a_second_socket_does_not_displace_the_first(self):
        """Two tabs, one person: closing the newer one must leave the older
        counted, which a field per person cannot do."""
        broadcaster = _broadcaster()
        event_id, user_id = uuid4(), uuid4()

        first = await broadcaster.mark_present(event_id, user_id)
        second = await broadcaster.mark_present(event_id, user_id)

        assert first != second
        assert broadcaster._roster[event_id] == {
            presence_field(user_id, first),
            presence_field(user_id, second),
        }

        await broadcaster.mark_absent(event_id, user_id, second)

        broadcaster.redis.hdel.assert_awaited_once_with(
            presence_key(event_id), presence_field(user_id, second)
        )
        assert broadcaster._roster[event_id] == {presence_field(user_id, first)}

    @pytest.mark.asyncio
    async def test_mark_absent_targets_only_this_socket(self):
        broadcaster = _broadcaster()
        event_id, user_id = uuid4(), uuid4()

        await broadcaster.mark_absent(event_id, user_id, "token-1")

        broadcaster.redis.hdel.assert_awaited_once_with(
            presence_key(event_id), f"{user_id}|token-1"
        )

    @pytest.mark.asyncio
    async def test_mark_absent_forgets_the_field_before_deleting_it(self):
        """A failed delete must not be undone by the heartbeat writing it back."""
        broadcaster = _broadcaster()
        event_id, user_id = uuid4(), uuid4()
        token = await broadcaster.mark_present(event_id, user_id)
        broadcaster.redis.hdel.side_effect = Exception("redis down")

        await broadcaster.mark_absent(event_id, user_id, token)

        assert event_id not in broadcaster._roster

    @pytest.mark.asyncio
    async def test_presence_count_runs_the_counting_script(self):
        broadcaster = _broadcaster()
        event_id = uuid4()
        broadcaster.redis.eval.return_value = 2

        count = await broadcaster.presence_count(event_id)

        assert count == 2
        broadcaster.redis.eval.assert_awaited_once_with(
            _PRESENCE_COUNT_SCRIPT,
            1,
            presence_key(event_id),
            INSTANCE_LEASE_PREFIX,
        )

    @pytest.mark.asyncio
    async def test_presence_count_is_zero_when_redis_fails(self):
        broadcaster = _broadcaster()
        broadcaster.redis.eval.side_effect = Exception("redis down")

        assert await broadcaster.presence_count(uuid4()) == 0

    @pytest.mark.asyncio
    async def test_broadcast_presence_counts_and_publishes_atomically(self):
        broadcaster = _broadcaster()
        event_id = uuid4()
        broadcaster.redis.eval.return_value = 1

        count = await broadcaster.broadcast_presence(event_id)

        assert count == 1
        broadcaster.redis.eval.assert_awaited_once_with(
            _PRESENCE_BROADCAST_SCRIPT,
            2,
            presence_key(event_id),
            position_channel(event_id),
            INSTANCE_LEASE_PREFIX,
            str(event_id),
        )
        # The count the room is told is the one this reading produced, so a
        # slower concurrent join cannot publish a staler number afterwards.
        broadcaster.redis.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_broadcast_presence_is_zero_when_redis_fails(self):
        broadcaster = _broadcaster()
        broadcaster.redis.eval.side_effect = Exception("redis down")

        assert await broadcaster.broadcast_presence(uuid4()) == 0

    @pytest.mark.asyncio
    async def test_heartbeat_rewrites_the_roster_after_the_lease(self):
        """A lapsed lease gets this instance's sockets pruned; they have to come
        back without the people behind them reconnecting."""
        broadcaster = _broadcaster()
        event_id, user_id = uuid4(), uuid4()
        token = await broadcaster.mark_present(event_id, user_id)
        broadcaster.redis.hset.reset_mock()

        await broadcaster.refresh_instance_lease()
        await broadcaster._reassert_presence()

        broadcaster.redis.hset.assert_awaited_once_with(
            presence_key(event_id),
            mapping={presence_field(user_id, token): _INSTANCE_ID},
        )

    @pytest.mark.asyncio
    async def test_a_failed_join_is_rewritten_by_the_heartbeat(self):
        broadcaster = _broadcaster()
        event_id, user_id = uuid4(), uuid4()
        broadcaster.redis.hset.side_effect = Exception("redis down")

        token = await broadcaster.mark_present(event_id, user_id)

        broadcaster.redis.hset.side_effect = None
        broadcaster.redis.hset.reset_mock()
        await broadcaster._reassert_presence()

        broadcaster.redis.hset.assert_awaited_once_with(
            presence_key(event_id),
            mapping={presence_field(user_id, token): _INSTANCE_ID},
        )

    @pytest.mark.asyncio
    async def test_a_socket_closing_mid_heartbeat_is_not_resurrected(self):
        """A close landing while the heartbeat's write is in flight must win.

        An entry rewritten after its own HDEL is untracked locally but live in
        Redis under a lease this process keeps renewing: nothing prunes it, and
        the room counts the person who left for as long as the process runs.
        """
        broadcaster = _broadcaster()
        event_id, user_id = uuid4(), uuid4()
        token = await broadcaster.mark_present(event_id, user_id)
        field = presence_field(user_id, token)

        # Stand in for the Redis hash, so the assertion is what the room would
        # be counted from rather than which calls happened to be made.
        roster: Dict[str, str] = {field: _INSTANCE_ID}
        writing = asyncio.Event()
        finish_write = asyncio.Event()

        async def hset(key: str, *args: Any, mapping: Optional[Dict[str, str]] = None):
            writing.set()
            await finish_write.wait()
            roster.update(mapping or {})

        async def hdel(key: str, *fields: str):
            for stale in fields:
                roster.pop(stale, None)

        broadcaster.redis.hset = hset
        broadcaster.redis.hdel = hdel

        heartbeat = asyncio.create_task(broadcaster._reassert_presence())
        await writing.wait()
        closing = asyncio.create_task(
            broadcaster.mark_absent(event_id, user_id, token)
        )
        # Let the close get as far as it can while the write is outstanding.
        await asyncio.sleep(0)
        finish_write.set()
        await asyncio.gather(heartbeat, closing)

        assert roster == {}
        assert event_id not in broadcaster._roster


    @pytest.mark.asyncio
    async def test_a_stalled_write_for_one_event_does_not_block_another(self):
        """The heartbeat's lock is per event: a close in another room must not
        wait on a Redis write that has stalled for this one."""
        broadcaster = _broadcaster()
        stalled_event, other_event = uuid4(), uuid4()
        user_id = uuid4()
        await broadcaster.mark_present(stalled_event, uuid4())
        token = await broadcaster.mark_present(other_event, user_id)
        # The sweep reaches the stalled event first and sits on its write.
        assert list(broadcaster._roster)[0] == stalled_event

        writing = asyncio.Event()
        finish_write = asyncio.Event()

        async def hset(key: str, *args: Any, mapping: Optional[Dict[str, str]] = None):
            writing.set()
            await finish_write.wait()

        broadcaster.redis.hset = hset
        broadcaster.redis.hdel = AsyncMock()

        heartbeat = asyncio.create_task(broadcaster._reassert_presence())
        await writing.wait()
        await asyncio.wait_for(
            broadcaster.mark_absent(other_event, user_id, token), timeout=1
        )
        broadcaster.redis.hdel.assert_awaited_once()

        finish_write.set()
        await heartbeat
        assert broadcaster._roster_locks == {}

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


def _translate_allow_set_script(script: str) -> str:
    """Turn the rate-limit Lua into Python so a test can run the script itself.

    The translation is mechanical (calls, indexes, if/elseif/end). A broken
    expiry or recovery branch in the script changes what this executes.
    """
    indent = 0
    lines: List[str] = []
    for raw in script.strip().splitlines():
        line = raw.strip()
        if not line:
            continue
        line = line.replace("local ", "")
        line = line.replace("redis.call(", "redis_call(")
        line = line.replace("KEYS[1]", "keys[0]")
        line = line.replace("ARGV[1]", "argv[0]")
        line = re.sub(r"^elseif\b", "elif", line)
        if line.endswith(" then"):
            line = line[: -len(" then")] + ":"
        if line in ("elif",) or line.startswith("elif "):
            indent -= 1
        if line == "end":
            indent -= 1
            continue
        lines.append("    " * indent + line)
        if line.startswith("if ") or line.startswith("elif "):
            indent += 1
    if indent != 0:
        raise AssertionError(f"script translation left indent {indent}")
    return "\n".join(lines)


class _ScriptRedis:
    """INCR / EXPIRE / TTL / SET, enough for `_ALLOW_SET_SCRIPT`."""

    def __init__(self) -> None:
        self.values: Dict[str, int] = {}
        self.ttl: Dict[str, int] = {}

    def redis_call(self, command: str, *args: Any) -> Any:
        command = command.upper()
        key = args[0]
        if command == "INCR":
            self.values[key] = int(self.values.get(key, 0)) + 1
            self.ttl.setdefault(key, -1)
            return self.values[key]
        if command == "EXPIRE":
            if key not in self.values:
                return 0
            self.ttl[key] = int(args[1])
            return 1
        if command == "TTL":
            if key not in self.values:
                return -2
            return self.ttl.get(key, -1)
        if command == "SET":
            self.values[key] = int(args[1])
            if len(args) >= 4 and str(args[2]).upper() == "EX":
                self.ttl[key] = int(args[3])
            else:
                self.ttl[key] = -1
            return "OK"
        raise AssertionError(f"unexpected redis command {command}")

    def drop_ttl(self, key: str) -> None:
        """A key that exists with no expiry: Redis reports TTL < 0."""
        self.ttl[key] = -1

    async def eval(self, script: str, numkeys: int, *keys_and_args: str) -> int:
        keys = list(keys_and_args[:numkeys])
        argv = list(keys_and_args[numkeys:])
        body = _translate_allow_set_script(script)
        namespace: Dict[str, Any] = {
            "keys": keys,
            "argv": argv,
            "redis_call": self.redis_call,
        }
        exec(f"def _run():\n{textwrap_indent(body)}\n", namespace)
        result = namespace["_run"]()
        return int(result)


def textwrap_indent(body: str) -> str:
    return "\n".join(f"    {line}" for line in body.splitlines())


class TestAllowSetScript:

    @pytest.mark.asyncio
    async def test_first_hit_expires_and_a_missing_ttl_is_reset(self):
        redis = _ScriptRedis()
        key = "recitation:event:demo:rate"
        window = str(RATE_WINDOW_SECONDS)

        assert await redis.eval(_ALLOW_SET_SCRIPT, 1, key, window) == 1
        assert redis.ttl[key] == RATE_WINDOW_SECONDS

        assert await redis.eval(_ALLOW_SET_SCRIPT, 1, key, window) == 2
        assert redis.ttl[key] == RATE_WINDOW_SECONDS

        redis.drop_ttl(key)
        assert await redis.eval(_ALLOW_SET_SCRIPT, 1, key, window) == 1
        assert redis.values[key] == 1
        assert redis.ttl[key] == RATE_WINDOW_SECONDS

    @pytest.mark.asyncio
    async def test_allow_set_uses_the_script_against_that_redis(self):
        broadcaster = RecitationBroadcaster("redis://localhost:6379/0")
        broadcaster.redis = _ScriptRedis()
        event_id = uuid4()

        for _ in range(MAX_SETS_PER_SECOND):
            assert await broadcaster.allow_set(event_id) is True
        assert await broadcaster.allow_set(event_id) is False
