import asyncio
import json
from typing import Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from pecha_api.events.recitation_autoplay_service import (
    LATE_CATCH_UP_MS,
    LEASE_MS,
    AutoplayEngine,
    AutoplayStore,
)
from pecha_api.events.recitation_live_models import AutoplayStep, SetPositionFrame
from pecha_api.events.recitation_websocket import POSITION_TTL_SECONDS


class Clock:
    def __init__(self, now: int = 1_000_000) -> None:
        self.now = now

    def __call__(self) -> int:
        return self.now


class FakeStore:
    """AutoplayStore's rules without Redis: one lease per event that lapses on
    the shared clock, and writes that only land for the lease holder at the
    step it last saw."""

    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.states: Dict[UUID, Dict[str, str]] = {}
        self.plans: Dict[UUID, str] = {}
        self.leases: Dict[UUID, tuple] = {}
        self.published: List[dict] = []

    def _holder(self, event_id: UUID) -> Optional[str]:
        lease = self.leases.get(event_id)
        if lease is None or lease[1] <= self.clock():
            return None
        return lease[0]

    async def begin(self, event_id, plan_id, plan_json, total, owner):
        self.plans[event_id] = plan_json
        self.states[event_id] = {
            "plan_id": plan_id,
            "status": "running",
            "reason": "",
            "step": "0",
            "step_started_ms": "",
            "due_ms": "",
            "total": str(total),
        }
        self.leases[event_id] = (owner, self.clock() + LEASE_MS)

    async def read(self, event_id):
        state = self.states.get(event_id)
        return dict(state) if state else None

    async def read_plan(self, event_id):
        return self.plans.get(event_id)

    async def advance(self, event_id, owner, plan_id, step, step_started_ms, fields):
        state = self.states.get(event_id)
        if (
            self._holder(event_id) != owner
            or not state
            or state["plan_id"] != plan_id
            or state["status"] != "running"
            or state["step"] != str(step)
            or state["step_started_ms"] != step_started_ms
        ):
            return False
        state.update(fields)
        return True

    async def may_send(self, event_id, owner, plan_id, step, step_started_ms):
        state = self.states.get(event_id)
        if (
            self._holder(event_id) != owner
            or not state
            or state["plan_id"] != plan_id
            or state["status"] != "running"
            or state["step"] != str(step)
            or state["step_started_ms"] != step_started_ms
        ):
            return False
        self.leases[event_id] = (owner, self.clock() + LEASE_MS)
        return True

    async def stop(self, event_id, reason, plan_id=None, owner=None):
        state = self.states.get(event_id)
        if not state or (plan_id and state["plan_id"] != plan_id):
            return False
        if owner and self._holder(event_id) != owner:
            return False
        state.update({"status": "stopped", "reason": reason})
        self.leases.pop(event_id, None)
        return True

    async def claim(self, event_id, owner):
        if self._holder(event_id) is not None:
            return False
        self.leases[event_id] = (owner, self.clock() + LEASE_MS)
        return True

    async def renew(self, event_id, owner):
        if self._holder(event_id) != owner:
            return False
        self.leases[event_id] = (owner, self.clock() + LEASE_MS)
        return True

    async def release(self, event_id, owner):
        if self._holder(event_id) == owner:
            self.leases.pop(event_id, None)

    async def running_events(self):
        return [e for e, s in self.states.items() if s["status"] == "running"]

    async def publish(self, event_id, payload):
        self.published.append(json.loads(payload))


def _steps(*durations: int) -> List[AutoplayStep]:
    return [
        AutoplayStep(
            positions=[
                SetPositionFrame(text_id="en", segment_id=f"en-{i}", index=i, round_number=1),
                SetPositionFrame(text_id="bo", segment_id=f"bo-{i}", index=i, round_number=1),
            ],
            duration_ms=duration,
        )
        for i, duration in enumerate(durations)
    ]


class Harness:
    """An engine on a fake clock whose sleeps move the clock on."""

    def __init__(self, clock=None, store=None, owner="A", emit=None):
        self.clock = clock or Clock()
        self.store = store or FakeStore(self.clock)
        self.sent: List[tuple] = []

        async def record(event_id, frames):
            self.sent.append((self.clock(), [f.segment_id for f in frames], frames))

        self.emit = emit or AsyncMock(side_effect=record)
        self.engine = AutoplayEngine(
            self.store, self.emit, owner=owner, clock=self.clock, sleep=self.sleep
        )
        self.gate: Optional[asyncio.Event] = None

    async def sleep(self, seconds: float) -> None:
        if self.gate is not None:
            await self.gate.wait()
        self.clock.now += int(seconds * 1000)
        await asyncio.sleep(0)

    async def settle(self, event_id: UUID) -> None:
        task = self.engine._runners.get(event_id)
        if task is not None:
            await asyncio.wait_for(task, timeout=5)


class TestStart:

    @pytest.mark.asyncio
    async def test_the_first_step_is_with_the_room_before_start_answers(self):
        h = Harness()
        h.gate = asyncio.Event()  # the runner waits; only start's own send counts
        event_id = uuid4()

        state = await h.engine.start(event_id, _steps(1000, 1000))

        assert [segments for _, segments, _ in h.sent] == [["en-0", "bo-0"]]
        assert state.status == "running"
        assert state.step == 0
        assert state.total_steps == 2
        assert state.step_started_at_ms == h.clock.now
        assert state.step_duration_ms == 1000
        h.engine._forget_runner(event_id)

    @pytest.mark.asyncio
    async def test_every_position_it_sends_is_marked_autoplay(self):
        """So the recorder never times the plan's own pace back into itself."""
        h = Harness()
        event_id = uuid4()
        await h.engine.start(event_id, _steps(1000))
        await h.settle(event_id)

        assert all(frame.autoplay for _, _, frames in h.sent for frame in frames)

    @pytest.mark.asyncio
    async def test_the_editions_go_out_in_the_order_given(self):
        """The event keeps the last position, so the controller puts the
        edition on screen last and it must stay last."""
        h = Harness()
        event_id = uuid4()
        await h.engine.start(event_id, _steps(1000))
        await h.settle(event_id)

        assert h.sent[0][1] == ["en-0", "bo-0"]


class TestReplanningMidLine:

    @pytest.mark.asyncio
    async def test_a_line_already_showing_is_not_sent_again_only_held_for_the_rest(self):
        """A round count changed mid-line: the new plan starts on the line the
        room is on, which keeps what is left of its time rather than starting
        it over."""
        h = Harness()
        event_id = uuid4()
        began = h.clock.now

        state = await h.engine.start(event_id, _steps(3000, 1000), first_step_elapsed_ms=2000)
        await h.settle(event_id)

        assert state.step_started_at_ms == began - 2000
        assert [(at - began, segments[1]) for at, segments, _ in h.sent] == [(1000, "bo-1")]


class TestRunning:

    @pytest.mark.asyncio
    async def test_holds_each_step_for_its_time_then_finishes(self):
        h = Harness()
        event_id = uuid4()
        began = h.clock.now

        await h.engine.start(event_id, _steps(1000, 2500, 400))
        await h.settle(event_id)

        assert [(at - began, segments[1]) for at, segments, _ in h.sent] == [
            (0, "bo-0"),
            (1000, "bo-1"),
            (3500, "bo-2"),
        ]
        state = await h.engine.state(event_id)
        assert state.status == "stopped"
        assert state.reason == "finished"

    @pytest.mark.asyncio
    async def test_each_step_starts_where_the_last_ended_not_when_the_tick_landed(self):
        """A tick that lands a little late is not added to every line after it."""
        h = Harness()
        event_id = uuid4()
        overshoot = 300

        async def sloppy_sleep(seconds):
            h.clock.now += int(seconds * 1000) + overshoot
            await asyncio.sleep(0)

        h.engine.sleep = sloppy_sleep
        began = h.clock.now
        await h.engine.start(event_id, _steps(1000, 1000, 1000))
        await h.settle(event_id)

        started = [
            json_state["step_started_at_ms"] - began
            for json_state in h.store.published
            if json_state["status"] == "running"
        ]
        assert started == [0, 1000, 2000]

    @pytest.mark.asyncio
    async def test_a_step_far_behind_starts_now_rather_than_racing_the_room(self):
        h = Harness()
        event_id = uuid4()
        # Late enough to matter, short of the lease: a longer stall loses the
        # lease, and another instance carries on instead (see TestTakingOver).
        stall = LATE_CATCH_UP_MS + 1500
        assert stall + 1000 < LEASE_MS

        async def stalled_sleep(seconds):
            h.clock.now += int(seconds * 1000) + stall
            await asyncio.sleep(0)

        h.engine.sleep = stalled_sleep
        began = h.clock.now
        await h.engine.start(event_id, _steps(1000, 1000))
        await h.settle(event_id)

        second_started = [
            s["step_started_at_ms"] for s in h.store.published if s["step"] == 1
        ][0]
        assert second_started - began == 1000 + stall

    @pytest.mark.asyncio
    async def test_every_change_is_announced_to_the_operator(self):
        h = Harness()
        event_id = uuid4()
        await h.engine.start(event_id, _steps(1000, 1000))
        await h.settle(event_id)

        assert [(s["status"], s["step"]) for s in h.store.published] == [
            ("running", 0),
            ("running", 1),
            ("stopped", 1),
        ]
        assert h.store.published[-1]["reason"] == "finished"
        assert all(s["type"] == "autoplay" for s in h.store.published)


class TestChangingCourse:

    @pytest.mark.asyncio
    async def test_a_new_plan_replaces_the_one_running(self):
        """A hand move mid-autoplay is a new plan from the chosen line."""
        h = Harness()
        h.gate = asyncio.Event()
        event_id = uuid4()
        await h.engine.start(event_id, _steps(1000, 1000, 1000))

        replacement = _steps(700)
        replacement[0].positions[1].segment_id = "bo-chosen"
        await h.engine.start(event_id, replacement)
        h.gate.set()
        await h.settle(event_id)

        assert [segments[1] for _, segments, _ in h.sent] == ["bo-0", "bo-chosen"]
        assert (await h.engine.state(event_id)).reason == "finished"

    @pytest.mark.asyncio
    async def test_stopping_sends_nothing_more(self):
        h = Harness()
        h.gate = asyncio.Event()
        event_id = uuid4()
        await h.engine.start(event_id, _steps(1000, 1000))

        state = await h.engine.stop(event_id)
        h.gate.set()
        await asyncio.sleep(0)

        assert len(h.sent) == 1
        assert state.status == "stopped"
        assert state.reason == "stopped"
        assert h.store.published[-1]["reason"] == "stopped"
        assert event_id not in h.engine._runners

    @pytest.mark.asyncio
    async def test_a_failed_send_stops_it_and_says_so(self):
        clock = Clock()
        calls = {"n": 0}

        async def flaky(event_id, frames):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("redis down")

        h = Harness(clock=clock, emit=AsyncMock(side_effect=flaky))
        event_id = uuid4()
        await h.engine.start(event_id, _steps(1000, 1000, 1000))
        await h.settle(event_id)

        state = await h.engine.state(event_id)
        assert state.status == "stopped"
        assert state.reason == "failed"
        assert calls["n"] == 2

    @pytest.mark.asyncio
    async def test_a_replaced_plan_sends_nothing_more_even_on_the_same_instance(self):
        h = Harness()
        h.gate = asyncio.Event()
        event_id = uuid4()
        old = await h.engine.start(event_id, _steps(1000, 1000))
        old_plan = h.engine._plans[event_id][1]
        await h.engine.start(event_id, _steps(1000, 1000))
        sent = len(h.sent)

        # The old runner, resuming with the same lease owner, tries its next line.
        assert not await h.engine._send_step(
            event_id, old.plan_id, old_plan, 1, "", h.clock()
        )
        assert len(h.sent) == sent
        h.engine._forget_runner(event_id)

    @pytest.mark.asyncio
    async def test_a_failed_start_stops_only_its_own_plan(self):
        clock = Clock()
        store = FakeStore(clock)
        release = asyncio.Event()

        async def fail(event_id, frames):
            await release.wait()
            raise RuntimeError("redis down")

        a = Harness(clock=clock, store=store, owner="A", emit=AsyncMock(side_effect=fail))
        b = Harness(clock=clock, store=store, owner="B")
        b.gate = asyncio.Event()
        event_id = uuid4()

        failing = asyncio.create_task(a.engine.start(event_id, _steps(1000, 1000)))
        while not a.emit.await_count:
            await asyncio.sleep(0)
        newer = await b.engine.start(event_id, _steps(1000, 1000))
        release.set()
        with pytest.raises(RuntimeError):
            await failing

        state = store.states[event_id]
        assert (state["plan_id"], state["status"]) == (newer.plan_id, "running")
        b.engine._forget_runner(event_id)

    @pytest.mark.asyncio
    async def test_a_start_that_fails_is_stopped_and_says_so(self):
        h = Harness(emit=AsyncMock(side_effect=RuntimeError("redis down")))
        event_id = uuid4()

        with pytest.raises(RuntimeError):
            await h.engine.start(event_id, _steps(1000, 1000))

        state = await h.engine.state(event_id)
        assert (state.status, state.reason) == ("stopped", "failed")
        assert event_id not in h.engine._runners

    @pytest.mark.asyncio
    async def test_a_stop_redis_refused_still_stops_the_runner_here_and_raises(self):
        h = Harness()
        h.gate = asyncio.Event()
        event_id = uuid4()
        await h.engine.start(event_id, _steps(1000, 1000))
        h.store.stop = AsyncMock(side_effect=RuntimeError("redis down"))

        with pytest.raises(RuntimeError):
            await h.engine.stop(event_id)

        assert event_id not in h.engine._runners


class TestTakingOver:

    @pytest.mark.asyncio
    async def test_another_instance_carries_on_once_the_holder_goes_away(self):
        """A deploy or a crash: the lease lapses and the next instance picks the
        plan up at the same step, holding it only for what is left of its time."""
        clock = Clock()
        store = FakeStore(clock)
        first = Harness(clock=clock, store=store, owner="A")
        first.gate = asyncio.Event()
        event_id = uuid4()
        began = clock.now
        await first.engine.start(event_id, _steps(10_000, 1000))
        # Instance A goes away without handing anything back.
        first.engine._forget_runner(event_id)
        clock.now += LEASE_MS + 1

        second = Harness(clock=clock, store=store, owner="B")
        await second.engine.adopt_orphans()
        await second.settle(event_id)

        # B did not send step 0 again - it was already out - and sent step 1
        # when step 0's time ran out, measured from when A sent it.
        assert [segments[1] for _, segments, _ in second.sent] == ["bo-1"]
        assert second.sent[0][0] - began == 10_000
        assert (await second.engine.state(event_id)).reason == "finished"

    @pytest.mark.asyncio
    async def test_a_step_that_was_never_marked_is_sent_again_not_skipped(self):
        clock = Clock()
        store = FakeStore(clock)
        event_id = uuid4()
        plan = json.dumps([
            {"positions": [p.model_dump(mode="json") for p in step.positions], "duration_ms": 500}
            for step in _steps(500, 500)
        ])
        await store.begin(event_id, "plan-1", plan, total=2, owner="A")
        # A moved on to step 1 and died before its send was marked.
        store.states[event_id].update({"step": "1", "due_ms": str(clock.now)})
        clock.now += LEASE_MS + 1

        h = Harness(clock=clock, store=store, owner="B")
        await h.engine.adopt_orphans()
        await h.settle(event_id)

        assert [segments[1] for _, segments, _ in h.sent] == ["bo-1"]

    @pytest.mark.asyncio
    async def test_nobody_takes_over_while_the_holder_is_alive(self):
        clock = Clock()
        store = FakeStore(clock)
        first = Harness(clock=clock, store=store, owner="A")
        first.gate = asyncio.Event()
        event_id = uuid4()
        await first.engine.start(event_id, _steps(10_000, 1000))

        second = Harness(clock=clock, store=store, owner="B")
        await second.engine.adopt_orphans()

        assert event_id not in second.engine._runners
        first.engine._forget_runner(event_id)

    @pytest.mark.asyncio
    async def test_a_runner_that_lost_its_lease_sends_nothing(self):
        clock = Clock()
        store = FakeStore(clock)
        h = Harness(clock=clock, store=store, owner="A")
        event_id = uuid4()
        await h.engine.start(event_id, _steps(1000, 1000))
        # Someone else holds it now.
        store.leases[event_id] = ("B", clock.now + 60_000)
        await h.settle(event_id)

        assert len(h.sent) == 1

    @pytest.mark.asyncio
    async def test_a_stalled_runner_finishing_does_not_stop_the_one_that_took_over(self):
        clock = Clock()
        store = FakeStore(clock)
        a = Harness(clock=clock, store=store, owner="A")
        a.gate = asyncio.Event()
        event_id = uuid4()
        started = await a.engine.start(event_id, _steps(1000))
        a.engine._forget_runner(event_id)
        # A stalls past its lease and B takes the plan over.
        clock.now += LEASE_MS + 1
        assert await store.claim(event_id, "B")

        await a.engine._finish(event_id, started.plan_id, "finished", owner="A")

        assert store.states[event_id]["status"] == "running"

    @pytest.mark.asyncio
    async def test_leaving_hands_the_lease_back(self):
        h = Harness()
        h.gate = asyncio.Event()
        event_id = uuid4()
        await h.engine.start(event_id, _steps(10_000, 1000))

        await h.engine.shutdown()

        assert event_id not in h.store.leases
        # Still running: another instance takes it from here.
        assert h.store.states[event_id]["status"] == "running"


class TestState:

    @pytest.mark.asyncio
    async def test_nothing_started_reads_as_stopped(self):
        h = Harness()
        state = await h.engine.state(uuid4())
        assert state.status == "stopped"
        assert state.plan_id is None
        assert state.total_steps == 0


class TestAutoplayStore:
    """The Redis side: what each command asks of Redis. The conditional rules
    themselves are the FakeStore's above."""

    def _redis(self):
        redis = MagicMock()
        redis.eval = AsyncMock(return_value=1)
        redis.set = AsyncMock(return_value=True)
        redis.publish = AsyncMock()
        return redis

    @pytest.mark.asyncio
    async def test_advance_names_the_holder_plan_and_step_it_expects(self):
        redis = self._redis()
        event_id = uuid4()

        done = await AutoplayStore(redis).advance(
            event_id, "A", "plan-1", 3, "1234", {"step": "4", "step_started_ms": ""}
        )

        assert done is True
        args = redis.eval.await_args.args
        assert args[1] == 2
        assert args[2] == f"recitation:event:{event_id}:autoplay"
        assert args[3] == f"recitation:event:{event_id}:autoplay-lease"
        assert list(args[4:]) == ["A", "plan-1", "3", "1234", "step", "4", "step_started_ms", ""]

    @pytest.mark.asyncio
    async def test_renewing_the_lease_keeps_the_plan_and_state_alive(self):
        redis = self._redis()
        event_id = uuid4()

        await AutoplayStore(redis).renew(event_id, "A")

        args = redis.eval.await_args.args
        assert args[1] == 3
        assert list(args[2:5]) == [
            f"recitation:event:{event_id}:autoplay-lease",
            f"recitation:event:{event_id}:autoplay",
            f"recitation:event:{event_id}:autoplay-plan",
        ]
        assert list(args[5:]) == ["A", str(LEASE_MS), str(POSITION_TTL_SECONDS)]

    @pytest.mark.asyncio
    async def test_claim_only_takes_a_free_lease(self):
        redis = self._redis()
        event_id = uuid4()

        await AutoplayStore(redis).claim(event_id, "B")

        redis.set.assert_awaited_once_with(
            f"recitation:event:{event_id}:autoplay-lease", "B", nx=True, px=LEASE_MS
        )

    @pytest.mark.asyncio
    async def test_state_goes_to_the_operator_channel_not_the_room(self):
        redis = self._redis()
        event_id = uuid4()

        await AutoplayStore(redis).publish(event_id, "{}")

        redis.publish.assert_awaited_once_with(
            f"recitation:event:{event_id}:autoplay-state", "{}"
        )
