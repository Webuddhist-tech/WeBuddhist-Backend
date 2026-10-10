import json
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from pecha_api.live_control import live_control_room_state as room
from pecha_api.live_control.live_control_room_state import RoomStatePatch

MODULE = "pecha_api.live_control.live_control_room_state"
TODAY = "2026-10-10"


class FakePipeline:
    def __init__(self, redis):
        self.redis = redis
        self.ops = []

    def hdel(self, key, *fields):
        self.ops.append(("hdel", key, fields))

    def hset(self, key, mapping):
        self.ops.append(("hset", key, mapping))

    def expire(self, key, seconds):
        self.ops.append(("expire", key, seconds))

    def hgetall(self, key):
        self.ops.append(("hgetall", key, None))

    async def execute(self):
        results = []
        for op, key, arg in self.ops:
            store = self.redis.hashes.setdefault(key, {})
            if op == "hdel":
                for field in arg:
                    store.pop(field, None)
                results.append(len(arg))
            elif op == "hset":
                store.update(arg)
                results.append(len(arg))
            elif op == "expire":
                self.redis.ttl[key] = arg
                results.append(True)
            else:
                results.append(dict(store))
        return results


class FakeRedis:
    def __init__(self, hashes=None):
        self.hashes = hashes or {}
        self.ttl = {}
        self.published = []

    async def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    def pipeline(self):
        return FakePipeline(self)

    async def publish(self, channel, payload):
        self.published.append((channel, json.loads(payload)))

    async def delete(self, key):
        self.hashes.pop(key, None)


def _patched(redis, today=TODAY):
    return patch.multiple(
        MODULE,
        _event_today=lambda event_id: today,
        get_broadcaster=lambda: SimpleNamespace(redis=redis),
    )


class TestReadRoomState:

    @pytest.mark.asyncio
    async def test_an_untouched_room_has_nothing_open_and_every_return_full(self):
        event_id = uuid4()
        with _patched(FakeRedis()):
            state = await room.get_room_state(event_id)

        assert state.open_text_id is None
        assert state.on_air == {}
        assert state.return_remaining == {}
        assert state.returns_day == TODAY

    @pytest.mark.asyncio
    async def test_yesterdays_return_counts_are_not_today_s(self):
        event_id = uuid4()
        redis = FakeRedis(
            {
                room.room_state_key(event_id): {
                    "returns_day": "2026-10-09",
                    "return:praises_1": "1",
                    "open_text_id": "Zt5c",
                    "on_air:abc": "1",
                }
            }
        )
        with _patched(redis):
            state = await room.get_room_state(event_id)

        assert state.return_remaining == {}
        assert state.open_text_id == "Zt5c"
        assert state.on_air == {"abc": True}


class TestUpdateRoomState:

    @pytest.mark.asyncio
    async def test_a_taken_return_counts_down_and_every_controller_hears_it(self):
        event_id = uuid4()
        redis = FakeRedis()
        with _patched(redis):
            state = await room.update_room_state(
                event_id, uuid4(), RoomStatePatch(return_remaining={"praises_1": 2})
            )

        assert state.return_remaining == {"praises_1": 2}
        channel, frame = redis.published[-1]
        assert channel.endswith(":autoplay-state")
        assert frame["type"] == "room_state"
        assert frame["return_remaining"] == {"praises_1": 2}
        assert redis.ttl[room.room_state_key(event_id)] == room.ROOM_STATE_TTL_SECONDS

    @pytest.mark.asyncio
    async def test_on_air_is_set_for_the_controller_that_sent_it(self):
        event_id, controller_id = uuid4(), uuid4()
        redis = FakeRedis()
        with _patched(redis):
            state = await room.update_room_state(event_id, controller_id, RoomStatePatch(on_air=True))
            state = await room.update_room_state(event_id, None, RoomStatePatch(on_air=False))

        assert state.on_air == {str(controller_id): True, room.SHARED_CONTROLLER: False}

    @pytest.mark.asyncio
    async def test_reset_puts_every_return_back_to_full(self):
        event_id = uuid4()
        key = room.room_state_key(event_id)
        redis = FakeRedis({key: {"returns_day": TODAY, "return:a": "0", "return:b": "1"}})
        with _patched(redis):
            state = await room.update_room_state(event_id, None, RoomStatePatch(reset_returns=True))

        assert state.return_remaining == {}

    @pytest.mark.asyncio
    async def test_a_return_set_to_null_goes_back_to_full(self):
        event_id = uuid4()
        key = room.room_state_key(event_id)
        redis = FakeRedis({key: {"returns_day": TODAY, "return:a": "0", "return:b": "1"}})
        with _patched(redis):
            state = await room.update_room_state(
                event_id, None, RoomStatePatch(return_remaining={"a": None})
            )

        assert state.return_remaining == {"b": 1}

    @pytest.mark.asyncio
    async def test_the_first_write_after_midnight_drops_yesterdays_counts(self):
        event_id = uuid4()
        key = room.room_state_key(event_id)
        redis = FakeRedis({key: {"returns_day": "2026-10-09", "return:a": "0"}})
        with _patched(redis):
            state = await room.update_room_state(
                event_id, None, RoomStatePatch(return_remaining={"b": 2})
            )

        assert state.return_remaining == {"b": 2}
        assert "return:a" not in redis.hashes[key]

    @pytest.mark.asyncio
    async def test_the_open_text_can_be_cleared(self):
        event_id = uuid4()
        key = room.room_state_key(event_id)
        redis = FakeRedis({key: {"returns_day": TODAY, "open_text_id": "Zt5c"}})
        with _patched(redis):
            state = await room.update_room_state(event_id, None, RoomStatePatch(open_text_id=None))

        assert state.open_text_id is None

    @pytest.mark.asyncio
    async def test_leaving_open_text_out_keeps_it(self):
        event_id = uuid4()
        key = room.room_state_key(event_id)
        redis = FakeRedis({key: {"returns_day": TODAY, "open_text_id": "Zt5c"}})
        with _patched(redis):
            state = await room.update_room_state(event_id, None, RoomStatePatch(on_air=True))

        assert state.open_text_id == "Zt5c"

    @pytest.mark.asyncio
    async def test_a_count_past_21_is_refused(self):
        with _patched(FakeRedis()):
            with pytest.raises(HTTPException) as error:
                await room.update_room_state(
                    uuid4(), None, RoomStatePatch(return_remaining={"a": 22})
                )

        assert error.value.status_code == 400


class TestClearRoomState:

    @pytest.mark.asyncio
    async def test_ending_the_session_empties_the_room_and_says_so(self):
        event_id = uuid4()
        key = room.room_state_key(event_id)
        redis = FakeRedis({key: {"open_text_id": "Zt5c", "on_air:x": "1"}})
        with _patched(redis):
            assert await room.clear_room_state(event_id) is True

        assert key not in redis.hashes
        assert redis.published[-1][1]["open_text_id"] is None
