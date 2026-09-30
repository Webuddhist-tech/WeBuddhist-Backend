"""The autoplay store's Redis scripts against a real server.

Skipped unless AUTOPLAY_TEST_REDIS_URL names a throwaway Redis (or Dragonfly):
the scripts are what keep two instances from both running one event's
autoplay, and a mock cannot say whether Lua does what it is asked.

    AUTOPLAY_TEST_REDIS_URL=redis://localhost:16379/0 pytest tests/events/test_recitation_autoplay_redis.py
"""

import asyncio
import json
import os
from uuid import uuid4

import pytest
import pytest_asyncio

from pecha_api.events import recitation_autoplay_service as service
from pecha_api.events.recitation_autoplay_service import AutoplayEngine, AutoplayStore
from pecha_api.events.recitation_live_models import AutoplayStep, SetPositionFrame

REDIS_URL = os.environ.get("AUTOPLAY_TEST_REDIS_URL")

pytestmark = pytest.mark.skipif(not REDIS_URL, reason="AUTOPLAY_TEST_REDIS_URL not set")


@pytest_asyncio.fixture
async def redis():
    from redis.asyncio import Redis

    client = await Redis.from_url(REDIS_URL, decode_responses=True)
    yield client
    async for key in client.scan_iter(match="recitation:event:*"):
        await client.delete(key)
    await client.aclose()


def _plan_json(count=2, duration=500):
    return json.dumps([
        {
            "positions": [
                {"text_id": "bo", "segment_id": f"bo-{i}", "index": i, "round_number": 1, "autoplay": True}
            ],
            "duration_ms": duration,
        }
        for i in range(count)
    ])


class TestScripts:

    @pytest.mark.asyncio
    async def test_begin_puts_the_plan_in_place_and_takes_the_lease(self, redis):
        store = AutoplayStore(redis)
        event_id = uuid4()

        await store.begin(event_id, "p1", _plan_json(), total=2, owner="A")

        state = await store.read(event_id)
        assert state["plan_id"] == "p1"
        assert state["status"] == "running"
        assert state["step"] == "0"
        assert state["step_started_ms"] == ""
        assert json.loads(await store.read_plan(event_id))[1]["duration_ms"] == 500
        assert await redis.get(f"recitation:event:{event_id}:autoplay-lease") == "A"
        assert await redis.ttl(f"recitation:event:{event_id}:autoplay") > 0

    @pytest.mark.asyncio
    async def test_advance_lands_only_for_the_holder_at_the_step_it_saw(self, redis):
        store = AutoplayStore(redis)
        event_id = uuid4()
        await store.begin(event_id, "p1", _plan_json(), total=2, owner="A")

        assert not await store.advance(event_id, "B", "p1", 0, "", {"step_started_ms": "10"})
        assert not await store.advance(event_id, "A", "p2", 0, "", {"step_started_ms": "10"})
        assert not await store.advance(event_id, "A", "p1", 1, "", {"step_started_ms": "10"})
        assert not await store.advance(event_id, "A", "p1", 0, "5", {"step_started_ms": "10"})
        assert (await store.read(event_id))["step_started_ms"] == ""

        assert await store.advance(event_id, "A", "p1", 0, "", {"step_started_ms": "10", "due_ms": ""})
        assert (await store.read(event_id))["step_started_ms"] == "10"
        # The step it saw has moved on: the same write does not land twice.
        assert not await store.advance(event_id, "A", "p1", 0, "", {"step_started_ms": "11"})

    @pytest.mark.asyncio
    async def test_nothing_lands_once_stopped(self, redis):
        store = AutoplayStore(redis)
        event_id = uuid4()
        await store.begin(event_id, "p1", _plan_json(), total=2, owner="A")

        assert await store.stop(event_id, "stopped")
        await redis.set(f"recitation:event:{event_id}:autoplay-lease", "A")

        assert not await store.advance(event_id, "A", "p1", 0, "", {"step_started_ms": "10"})
        state = await store.read(event_id)
        assert (state["status"], state["reason"]) == ("stopped", "stopped")

    @pytest.mark.asyncio
    async def test_finishing_an_old_plan_does_not_stop_the_new_one(self, redis):
        store = AutoplayStore(redis)
        event_id = uuid4()
        await store.begin(event_id, "p2", _plan_json(), total=2, owner="A")

        assert not await store.stop(event_id, "finished", plan_id="p1")
        assert (await store.read(event_id))["status"] == "running"
        assert await store.stop(event_id, "finished", plan_id="p2")
        assert await redis.get(f"recitation:event:{event_id}:autoplay-lease") is None

    @pytest.mark.asyncio
    async def test_a_stop_naming_an_owner_needs_that_owner_to_hold_the_lease(self, redis):
        store = AutoplayStore(redis)
        event_id = uuid4()
        await store.begin(event_id, "p1", _plan_json(), total=2, owner="B")

        assert not await store.stop(event_id, "finished", plan_id="p1", owner="A")
        assert (await store.read(event_id))["status"] == "running"
        assert await store.stop(event_id, "finished", plan_id="p1", owner="B")

    @pytest.mark.asyncio
    async def test_may_send_only_for_the_holder_of_the_current_plan_at_its_step(self, redis):
        store = AutoplayStore(redis)
        event_id = uuid4()
        await store.begin(event_id, "p2", _plan_json(), total=2, owner="A")

        assert not await store.may_send(event_id, "A", "p1", 0, "")
        assert not await store.may_send(event_id, "B", "p2", 0, "")
        assert not await store.may_send(event_id, "A", "p2", 1, "")
        assert await store.may_send(event_id, "A", "p2", 0, "")
        await store.stop(event_id, "stopped")
        assert not await store.may_send(event_id, "A", "p2", 0, "")

    @pytest.mark.asyncio
    async def test_renewing_keeps_the_plan_and_state_alive(self, redis):
        store = AutoplayStore(redis)
        event_id = uuid4()
        await store.begin(event_id, "p1", _plan_json(), total=2, owner="A")
        for key in ("autoplay", "autoplay-plan"):
            await redis.expire(f"recitation:event:{event_id}:{key}", 5)

        assert await store.renew(event_id, "A")

        for key in ("autoplay", "autoplay-plan"):
            assert await redis.ttl(f"recitation:event:{event_id}:{key}") > 5

    @pytest.mark.asyncio
    async def test_the_lease_is_claimed_renewed_and_released_by_its_holder_only(self, redis):
        store = AutoplayStore(redis)
        event_id = uuid4()

        assert await store.claim(event_id, "A")
        assert not await store.claim(event_id, "B")
        assert await store.renew(event_id, "A")
        assert not await store.renew(event_id, "B")
        await store.release(event_id, "B")
        assert await redis.get(f"recitation:event:{event_id}:autoplay-lease") == "A"
        await store.release(event_id, "A")
        assert await store.claim(event_id, "B")

    @pytest.mark.asyncio
    async def test_a_lapsed_lease_can_be_claimed(self, redis, monkeypatch):
        monkeypatch.setattr(service, "LEASE_MS", 200)
        store = AutoplayStore(redis)
        event_id = uuid4()
        assert await store.claim(event_id, "A")

        await asyncio.sleep(0.35)

        assert await store.claim(event_id, "B")
        assert not await store.renew(event_id, "A")

    @pytest.mark.asyncio
    async def test_running_events_are_found_on_any_instance(self, redis):
        store = AutoplayStore(redis)
        running, stopped = uuid4(), uuid4()
        await store.begin(running, "p1", _plan_json(), total=2, owner="A")
        await store.begin(stopped, "p2", _plan_json(), total=2, owner="A")
        await store.stop(stopped, "stopped")

        found = await store.running_events()

        assert running in found
        assert stopped not in found

    @pytest.mark.asyncio
    async def test_state_is_published_on_the_operator_channel(self, redis):
        store = AutoplayStore(redis)
        event_id = uuid4()
        pubsub = redis.pubsub()
        await pubsub.subscribe(f"recitation:event:{event_id}:autoplay-state")
        await pubsub.get_message(timeout=1)

        await store.publish(event_id, '{"type":"autoplay"}')

        message = None
        for _ in range(20):
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.2)
            if message:
                break
        await pubsub.aclose()
        assert message["data"] == '{"type":"autoplay"}'


def _steps(count, duration):
    return [
        AutoplayStep(
            positions=[SetPositionFrame(text_id="bo", segment_id=f"bo-{i}", index=i, round_number=1)],
            duration_ms=duration,
        )
        for i in range(count)
    ]


class TestEngineOnRedis:

    @pytest.mark.asyncio
    async def test_runs_a_plan_through_on_real_time(self, redis):
        sent = []

        async def emit(event_id, frames):
            sent.append((asyncio.get_running_loop().time(), frames[0].segment_id))

        engine = AutoplayEngine(AutoplayStore(redis), emit, owner="A")
        event_id = uuid4()

        await engine.start(event_id, _steps(3, 300))
        await asyncio.wait_for(engine._runners[event_id], timeout=5)

        assert [segment for _, segment in sent] == ["bo-0", "bo-1", "bo-2"]
        gaps = [round((b - a) * 1000) for (a, _), (b, _) in zip(sent, sent[1:])]
        assert all(280 <= gap <= 450 for gap in gaps), gaps
        state = await engine.state(event_id)
        assert (state.status, state.reason) == ("stopped", "finished")

    @pytest.mark.asyncio
    async def test_a_second_instance_takes_over_when_the_first_goes_away(self, redis, monkeypatch):
        monkeypatch.setattr(service, "LEASE_MS", 600)
        sent = []

        async def emit(event_id, frames):
            sent.append(frames[0].segment_id)

        first = AutoplayEngine(AutoplayStore(redis), emit, owner="A")
        second = AutoplayEngine(AutoplayStore(redis), emit, owner="B")
        event_id = uuid4()

        await first.start(event_id, _steps(3, 1000))
        # A dies: its runner stops and its lease is left to lapse.
        first._forget_runner(event_id)
        await asyncio.sleep(0.05)
        await second.adopt_orphans()
        assert event_id not in second._runners, "took over while A's lease was alive"

        await asyncio.sleep(0.7)
        await second.adopt_orphans()
        assert event_id in second._runners
        await asyncio.wait_for(second._runners[event_id], timeout=6)

        # Nothing skipped, nothing sent twice.
        assert sent == ["bo-0", "bo-1", "bo-2"]
        assert (await second.state(event_id)).reason == "finished"

    @pytest.mark.asyncio
    async def test_a_new_plan_from_another_instance_stops_the_old_runner(self, redis):
        sent = []

        async def emit(event_id, frames):
            sent.append(frames[0].segment_id)

        first = AutoplayEngine(AutoplayStore(redis), emit, owner="A")
        second = AutoplayEngine(AutoplayStore(redis), emit, owner="B")
        event_id = uuid4()

        await first.start(event_id, _steps(3, 400))
        replacement = _steps(1, 300)
        replacement[0].positions[0].segment_id = "bo-chosen"
        await second.start(event_id, replacement)

        await asyncio.wait_for(second._runners[event_id], timeout=5)
        old = first._runners.get(event_id)
        if old is not None:
            await asyncio.wait_for(old, timeout=5)
        await asyncio.sleep(0.5)

        assert sent == ["bo-0", "bo-chosen"]
