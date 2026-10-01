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
        # Each line on time, so the gaps are the hold times themselves.
        await engine.update_settings(event_id, lead_ms=0)

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


class TestCommandScripts:
    """The operator's commands: each makes its change and takes the lease in
    one step, wherever the runner happens to be."""

    @pytest.mark.asyncio
    async def test_seek_moves_the_plan_takes_the_lease_and_reports_the_step_left(self, redis):
        store = AutoplayStore(redis)
        event_id = uuid4()
        await store.begin(event_id, "p1", _plan_json(4), total=4, owner="A")
        await store.advance(event_id, "A", "p1", 0, "", {"step_started_ms": "1000"})

        outcome = await store.seek(event_id, "p1", 1, 0, "B")

        assert (outcome.result, outcome.previous_step, outcome.previous_started_ms) == ("moved", 0, 1000)
        state = await store.read(event_id)
        assert (state["step"], state["step_started_ms"]) == ("1", "")
        assert await redis.get(f"recitation:event:{event_id}:autoplay-lease") == "B"

    @pytest.mark.asyncio
    async def test_a_press_racing_the_plan_is_not_applied_twice(self, redis):
        store = AutoplayStore(redis)
        event_id = uuid4()
        await store.begin(event_id, "p1", _plan_json(4), total=4, owner="A")
        await store.advance(event_id, "A", "p1", 0, "", {"step": "1"})

        assert (await store.seek(event_id, "p1", 1, 0, "B")).result == "already_there"
        assert await redis.get(f"recitation:event:{event_id}:autoplay-lease") == "A"

    @pytest.mark.asyncio
    async def test_seek_is_refused_past_the_end_for_another_plan_or_once_stopped(self, redis):
        store = AutoplayStore(redis)
        event_id = uuid4()
        await store.begin(event_id, "p1", _plan_json(2), total=2, owner="A")

        assert (await store.seek(event_id, "p1", 2, None, "B")).result == "refused"
        assert (await store.seek(event_id, "p2", 1, None, "B")).result == "refused"
        await store.stop(event_id, "stopped")
        assert (await store.seek(event_id, "p1", 1, None, "B")).result == "refused"

    @pytest.mark.asyncio
    async def test_hold_takes_back_a_line_sent_early_and_resume_keeps_the_rest_of_the_line(self, redis):
        store = AutoplayStore(redis)
        event_id = uuid4()
        await store.begin(event_id, "p1", _plan_json(3), total=3, owner="A")
        await store.advance(
            event_id, "A", "p1", 0, "", {"step_started_ms": "1759300000000", "pre_sent": "1"}
        )

        held = await store.hold(event_id, "p1", 1759300000400, "B")
        assert (held.result, held.step, held.resend) == ("held", 0, True)
        state = await store.read(event_id)
        # Kept until the room is back on the line, so a failed take-back is retried.
        assert (state["held"], state["pre_sent"]) == ("1", "1")
        again = await store.hold(event_id, None, 1759300000450, "C")
        assert (again.result, again.resend) == ("already_held", True)
        assert await redis.get(f"recitation:event:{event_id}:autoplay-lease") == "C"
        assert await store.clear_early(event_id, "p1", 0, "1759300000000")
        state = await store.read(event_id)
        assert (state["pre_sent"], state["pre_sending"]) == ("", "")
        again = await store.hold(event_id, None, 1759300000500, "B")
        assert (again.result, again.resend) == ("already_held", False)

        assert await store.resume(event_id, "p1", 1759300009400, "B") == ("resumed", "p1")
        state = await store.read(event_id)
        assert state["step_started_ms"] == "1759300009000"
        assert state["held"] == ""
        assert (await store.resume(event_id, None, 1, "B"))[0] == "not_held"

    @pytest.mark.asyncio
    async def test_an_early_line_is_noted_going_then_gone_and_never_while_held(self, redis):
        store = AutoplayStore(redis)
        event_id = uuid4()
        await store.begin(event_id, "p1", _plan_json(3), total=3, owner="A")
        await store.advance(event_id, "A", "p1", 0, "", {"step_started_ms": "100"})

        assert not await store.note_early(event_id, "A", "p1", 0, "100", sent=True)
        assert await store.note_early(
            event_id, "A", "p1", 0, "100", sent=False, duration_ms=1000
        )
        state = await store.read(event_id)
        assert (state["pre_sending"], state["pre_sent"]) == ("1", "")
        assert state["fixed_duration_ms"] == "1000"
        # Held while on its way: the hold sees it.
        held = await store.hold(event_id, "p1", 200, "A")
        assert held.resend is True
        assert not await store.note_early(event_id, "A", "p1", 0, "100", sent=True)
        assert not await store.note_early(event_id, "A", "p1", 0, "100", sent=False)
        assert not await store.note_early(event_id, "B", "p1", 0, "100", sent=False)

    @pytest.mark.asyncio
    async def test_a_press_on_a_line_the_plan_has_passed_does_not_move_it_back(self, redis):
        store = AutoplayStore(redis)
        event_id = uuid4()
        await store.begin(event_id, "p1", _plan_json(4), total=4, owner="A")
        await store.advance(event_id, "A", "p1", 0, "", {"step": "3"})

        assert (await store.seek(event_id, "p1", 2, 1, "B")).result == "already_there"
        assert (await store.read(event_id))["step"] == "3"
        # A move back from the line the operator is on still goes.
        assert (await store.seek(event_id, "p1", 1, 3, "B")).result == "moved"
        assert (await store.read(event_id))["step"] == "1"

    @pytest.mark.asyncio
    async def test_renewing_keeps_the_settings_alive(self, redis):
        store = AutoplayStore(redis)
        event_id = uuid4()
        settings_key = f"recitation:event:{event_id}:autoplay-settings"
        await store.write_settings(event_id, {"tempo": "1.2500"})
        await redis.expire(settings_key, 5)
        await store.begin(event_id, "p1", _plan_json(), total=2, owner="A")

        assert await store.renew(event_id, "A")
        assert await redis.ttl(settings_key) > 5
        await redis.expire(settings_key, 5)
        assert await store.may_send(event_id, "A", "p1", 0, "")
        assert await redis.ttl(settings_key) > 5

    @pytest.mark.asyncio
    async def test_settings_outlive_the_plan(self, redis):
        store = AutoplayStore(redis)
        event_id = uuid4()
        await store.write_settings(event_id, {"tempo": "1.2500", "lead_ms": "450"})
        await store.begin(event_id, "p1", _plan_json(), total=2, owner="A")

        settings = await store.read_settings(event_id)

        assert (settings.tempo, settings.lead_ms) == (1.25, 450)
        assert await redis.ttl(f"recitation:event:{event_id}:autoplay-settings") > 0
