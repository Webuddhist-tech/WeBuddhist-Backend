import asyncio
import json
from typing import Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from fastapi import HTTPException

from pecha_api.events.recitation_autoplay_service import (
    LATE_CATCH_UP_MS,
    LEASE_MS,
    AutoplayCommandRefused,
    AutoplayEngine,
    AutoplayStore,
    HoldOutcome,
    SeekOutcome,
    _event_is_live,
    _settings_from,
    current_autoplay_send_permit,
    effective_duration_ms,
    lead_for,
    next_tempo,
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

    def __init__(self, clock: Clock, lead_ms: int = 0) -> None:
        self.clock = clock
        self.states: Dict[UUID, Dict[str, str]] = {}
        self.plans: Dict[UUID, str] = {}
        self.leases: Dict[UUID, tuple] = {}
        self.published: List[dict] = []
        # No lead unless a test asks for one, so the timing tests read in
        # whole steps; the lead has tests of its own.
        self.settings: Dict[UUID, Dict[str, str]] = {}
        self.default_lead_ms = lead_ms

    async def read_settings(self, event_id):
        raw = {"lead_ms": str(self.default_lead_ms), **self.settings.get(event_id, {})}
        return _settings_from(raw)

    async def write_settings(self, event_id, fields):
        self.settings.setdefault(event_id, {}).update(fields)

    def _running(self, event_id, plan_id):
        state = self.states.get(event_id)
        if not state or state["status"] != "running":
            return None
        if plan_id and state["plan_id"] != plan_id:
            return None
        return state

    async def seek(self, event_id, plan_id, step, expected_step, owner):
        state = self._running(event_id, plan_id)
        if state is None or step >= int(state["total"]):
            return SeekOutcome("refused")
        current, started = state["step"], state["step_started_ms"]
        previous = (int(current), int(started) if started else None)
        if (
            expected_step is not None
            and current != str(expected_step)
            and step > expected_step
            and int(current) >= step
        ):
            return SeekOutcome("already_there", *previous)
        state.update({
            "step": str(step),
            "step_started_ms": "",
            "due_ms": "",
            "pre_sent": state.get("pre_sent", "") if state.get("pre_sent") == str(step) else "",
            "pre_sending": "",
            "held": "",
            "held_at_ms": "",
        })
        self.leases[event_id] = (owner, self.clock() + LEASE_MS)
        return SeekOutcome("moved", *previous)

    async def hold(self, event_id, plan_id, now_ms, owner):
        state = self._running(event_id, plan_id)
        if state is None:
            return HoldOutcome("refused")
        step, started = int(state["step"]), state["step_started_ms"]
        marks = (state.get("pre_sent", ""), state.get("pre_sending", ""))
        resend = not started or any(m and m != state["step"] for m in marks)
        result = "already_held" if state.get("held") == "1" else "held"
        if result == "held":
            state.update({"held": "1", "held_at_ms": str(now_ms)})
        if result == "held" or resend:
            self.leases[event_id] = (owner, self.clock() + LEASE_MS)
        return HoldOutcome(result, state["plan_id"], step, started, resend)

    async def note_early(
        self, event_id, owner, plan_id, step, step_started_ms, sent, duration_ms=None
    ):
        state = self.states.get(event_id)
        if (
            self._holder(event_id) != owner
            or not state
            or state["plan_id"] != plan_id
            or state["status"] != "running"
            or state["step"] != str(step)
            or state["step_started_ms"] != step_started_ms
            or state.get("held") == "1"
        ):
            return False
        following = str(step + 1)
        if not sent:
            state["pre_sending"] = following
            state["fixed_duration_ms"] = "" if duration_ms is None else str(duration_ms)
            return True
        if state.get("pre_sending") != following:
            return False
        state["pre_sent"] = following
        return True

    async def clear_early(self, event_id, plan_id, step, step_started_ms):
        state = self.states.get(event_id)
        if (
            not state
            or state["plan_id"] != plan_id
            or state["step"] != str(step)
            or state["step_started_ms"] != step_started_ms
        ):
            return False
        state.update({"pre_sent": "", "pre_sending": ""})
        return True

    async def resume(self, event_id, plan_id, now_ms, owner):
        state = self._running(event_id, plan_id)
        if state is None:
            return "refused", None
        if state.get("held") != "1":
            return "not_held", state["plan_id"]
        started = state["step_started_ms"]
        if started:
            state["step_started_ms"] = str(int(started) + now_ms - int(state["held_at_ms"]))
        else:
            state["due_ms"] = str(now_ms)
        state.update({"held": "", "held_at_ms": ""})
        self.leases[event_id] = (owner, self.clock() + LEASE_MS)
        return "resumed", state["plan_id"]

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
    async def test_a_step_being_sent_names_the_plan_it_may_publish_for(self):
        """The check before the send does not cover the send. The permit is
        what the publish re-checks, and it is gone once the send returns."""
        seen = {}

        async def capture(event_id, frames):
            seen["permit"] = current_autoplay_send_permit()

        h = Harness(emit=AsyncMock(side_effect=capture))
        h.gate = asyncio.Event()
        event_id = uuid4()
        state = await h.engine.start(event_id, _steps(1000))

        assert seen["permit"].plan_id == state.plan_id
        assert seen["permit"].step == 0
        assert seen["permit"].step_started_ms == ""
        assert current_autoplay_send_permit() is None
        h.engine._forget_runner(event_id)

    @pytest.mark.asyncio
    async def test_a_step_that_loses_its_plan_while_sending_is_not_marked_sent(self):
        async def superseded(event_id, frames):
            return False

        h = Harness(emit=AsyncMock(side_effect=superseded))
        h.gate = asyncio.Event()
        event_id = uuid4()
        await h.engine.start(event_id, _steps(1000))

        assert h.store.states[event_id]["step_started_ms"] == ""
        h.engine._forget_runner(event_id)

    @pytest.mark.asyncio
    async def test_a_superseded_start_does_not_replace_the_newer_runner(self):
        release = asyncio.Event()
        sent = []

        async def emit(event_id, frames):
            if not sent:
                sent.append("blocked")
                await release.wait()
                return False
            sent.append(frames[0].segment_id)

        h = Harness(emit=AsyncMock(side_effect=emit))
        h.gate = asyncio.Event()
        event_id = uuid4()
        first = asyncio.create_task(h.engine.start(event_id, _steps(1000, 1000)))
        while not h.emit.await_count:
            await asyncio.sleep(0)
        newer = await h.engine.start(event_id, _steps(700))
        release.set()
        await first

        assert h.engine._runner_plans[event_id] == newer.plan_id
        assert h.engine._running_here(event_id)
        h.engine._forget_runner(event_id)

    @pytest.mark.asyncio
    async def test_a_deleted_event_is_not_played_on(self):
        h = Harness()
        h.gate = asyncio.Event()
        event_id = uuid4()
        await h.engine.start(event_id, _steps(1000, 1000))

        async def gone(event_id):
            return False

        h.engine.is_live = gone
        h.gate.set()
        await h.settle(event_id)

        assert [segments[1] for _, segments, _ in h.sent] == ["bo-0"]
        state = await h.engine.state(event_id)
        assert (state.status, state.reason) == ("stopped", "ended")

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
    async def test_a_new_plan_redis_refused_leaves_the_old_one_running(self):
        h = Harness()
        h.gate = asyncio.Event()
        event_id = uuid4()
        old = await h.engine.start(event_id, _steps(1000, 1000))
        h.store.begin = AsyncMock(side_effect=RuntimeError("redis down"))

        with pytest.raises(RuntimeError):
            await h.engine.start(event_id, _steps(1000, 1000))

        assert h.engine._running_here(event_id)
        assert h.engine._runner_plans[event_id] == old.plan_id
        h.gate.set()
        await h.settle(event_id)
        assert [segments[1] for _, segments, _ in h.sent] == ["bo-0", "bo-1"]
        assert (await h.engine.state(event_id)).reason == "finished"

    @pytest.mark.asyncio
    async def test_a_failed_save_does_not_restore_the_old_runner_over_a_newer_one(self):
        h = Harness()
        h.gate = asyncio.Event()
        event_id = uuid4()
        await h.engine.start(event_id, _steps(1000, 1000))
        real_begin = h.store.begin
        release = asyncio.Event()

        async def slow_then_fail(*args, **kwargs):
            await release.wait()
            raise RuntimeError("redis down")

        h.store.begin = AsyncMock(side_effect=slow_then_fail)
        failing = asyncio.create_task(h.engine.start(event_id, _steps(1000, 1000)))
        while not h.store.begin.await_count:
            await asyncio.sleep(0)
        h.store.begin = real_begin
        newer = await h.engine.start(event_id, _steps(1000, 1000))
        release.set()
        with pytest.raises(RuntimeError):
            await failing

        assert h.engine._runner_plans[event_id] == newer.plan_id
        h.engine._forget_runner(event_id)

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

    @pytest.mark.asyncio
    async def test_a_stop_does_not_cancel_a_plan_started_while_it_waited(self):
        h = Harness()
        h.gate = asyncio.Event()
        event_id = uuid4()
        await h.engine.start(event_id, _steps(1000, 1000))
        in_stop = asyncio.Event()
        let_stop_finish = asyncio.Event()
        real_stop = h.store.stop

        async def slow_stop(*args, **kwargs):
            in_stop.set()
            await let_stop_finish.wait()
            return await real_stop(*args, **kwargs)

        h.store.stop = slow_stop
        stopping = asyncio.create_task(h.engine.stop(event_id))
        await in_stop.wait()

        # A new plan starts, and its runner is tracked, while the stop waits.
        h.store.stop = real_stop
        newer = await h.engine.start(event_id, _steps(1000, 1000))
        runner = h.engine._runners[event_id]
        h.store.stop = slow_stop
        let_stop_finish.set()
        await stopping

        assert h.engine._runners.get(event_id) is runner
        assert not runner.cancelled()
        assert h.engine._runner_plans[event_id] == newer.plan_id
        # Its stored state too: the stop was for the old plan only.
        assert h.store.states[event_id]["plan_id"] == newer.plan_id
        assert h.store.states[event_id]["status"] == "running"
        assert h.store._holder(event_id) == h.engine.owner
        h.engine._forget_runner(event_id)


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


class TestEventStillLive:

    @pytest.mark.asyncio
    async def test_a_missing_event_is_not_live(self):
        with patch(
            "pecha_api.events.recitation_live_service.assert_live_event",
            side_effect=HTTPException(status_code=404),
        ):
            assert await _event_is_live(uuid4()) is False

    @pytest.mark.asyncio
    async def test_a_database_error_does_not_look_like_a_deleted_event(self):
        with patch(
            "pecha_api.events.recitation_live_service.assert_live_event",
            side_effect=RuntimeError("db down"),
        ):
            assert await _event_is_live(uuid4()) is True


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
    async def test_renewing_the_lease_keeps_the_plan_state_and_settings_alive(self):
        redis = self._redis()
        event_id = uuid4()

        await AutoplayStore(redis).renew(event_id, "A")

        args = redis.eval.await_args.args
        assert args[1] == 4
        assert list(args[2:6]) == [
            f"recitation:event:{event_id}:autoplay-lease",
            f"recitation:event:{event_id}:autoplay",
            f"recitation:event:{event_id}:autoplay-plan",
            f"recitation:event:{event_id}:autoplay-settings",
        ]
        assert list(args[6:]) == ["A", str(LEASE_MS), str(POSITION_TTL_SECONDS)]

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


def _plan_id(h: Harness, event_id: UUID) -> str:
    return h.store.states[event_id]["plan_id"]


def _sent(h: Harness, began: int) -> List[tuple]:
    """(when, the edition on screen) for every step that went to the room."""
    return [(at - began, segments[-1]) for at, segments, _ in h.sent]


def _with_lead(lead_ms: int) -> Harness:
    h = Harness()
    h.store = FakeStore(h.clock, lead_ms=lead_ms)
    h.engine.store = h.store
    return h


class _Paused:
    """Stops the runner where a test wants it, by holding its sleeps."""

    def __init__(self, h: Harness, until) -> None:
        self.h = h
        self.until = until
        self.gate = asyncio.Event()
        h.engine.sleep = self.sleep

    async def sleep(self, seconds: float) -> None:
        if self.until():
            await self.gate.wait()
        self.h.clock.now += int(seconds * 1000)
        await asyncio.sleep(0)


async def _yield(times: int = 20) -> None:
    for _ in range(times):
        await asyncio.sleep(0)


class TestSendingAhead:
    """Phones show a line the moment it lands, and cannot be changed, so the
    room is sent each line a little ahead of its time to land with the stage."""

    @pytest.mark.asyncio
    async def test_each_line_goes_to_the_room_early_and_to_the_operator_on_time(self):
        h = _with_lead(300)
        event_id = uuid4()
        began = h.clock.now

        await h.engine.start(event_id, _steps(1000, 1000, 1000))
        await h.settle(event_id)

        assert _sent(h, began) == [(0, "bo-0"), (700, "bo-1"), (1700, "bo-2")]
        started = [
            s["step_started_at_ms"] - began for s in h.store.published if s["status"] == "running"
        ]
        assert started == [0, 1000, 2000]

    @pytest.mark.asyncio
    async def test_a_line_sent_early_is_not_sent_again_when_its_time_comes(self):
        h = _with_lead(300)
        event_id = uuid4()

        await h.engine.start(event_id, _steps(1000, 1000))
        await h.settle(event_id)

        assert [segments[-1] for _, segments, _ in h.sent] == ["bo-0", "bo-1"]

    @pytest.mark.asyncio
    async def test_a_short_line_keeps_at_least_half_its_time_on_phones(self):
        h = _with_lead(600)
        event_id = uuid4()
        began = h.clock.now

        await h.engine.start(event_id, _steps(400, 1000))
        await h.settle(event_id)

        assert _sent(h, began) == [(0, "bo-0"), (200, "bo-1")]

    @pytest.mark.asyncio
    async def test_a_pace_raised_after_the_next_line_went_early_does_not_hold_the_stage_back(self):
        """Phones already have the next line: the stage moves on when that send
        was timed for, not later by the new pace, which starts with the next
        line instead."""
        h = _with_lead(300)
        event_id = uuid4()
        began = h.clock.now
        paused = _Paused(h, until=lambda: h.store.states[event_id].get("pre_sent") == "1")
        await h.engine.start(event_id, _steps(1000, 1000))
        await _yield()

        during = await h.engine.update_settings(event_id, tempo=1.6)
        paused.until = lambda: False
        paused.gate.set()
        await h.settle(event_id)

        assert during.step_duration_ms == 1000
        assert _sent(h, began) == [(0, "bo-0"), (700, "bo-1")]
        next_line = [
            s for s in h.store.published if s["status"] == "running" and s["step"] == 1
        ]
        assert next_line[0]["step_started_at_ms"] - began == 1000
        assert next_line[0]["step_duration_ms"] == 1600

    @pytest.mark.asyncio
    async def test_no_lead_sends_each_line_on_time(self):
        h = Harness()
        event_id = uuid4()
        began = h.clock.now

        await h.engine.start(event_id, _steps(1000, 1000))
        await h.settle(event_id)

        assert _sent(h, began) == [(0, "bo-0"), (1000, "bo-1")]


class TestSeek:

    @pytest.mark.asyncio
    async def test_a_hand_move_goes_to_the_room_at_once_without_a_new_plan(self):
        h = Harness()
        h.gate = asyncio.Event()
        event_id = uuid4()
        began = h.clock.now
        await h.engine.start(event_id, _steps(1000, 1000, 1000, 1000))
        plan_id = _plan_id(h, event_id)

        h.clock.now += 200
        state = await h.engine.seek(event_id, plan_id, 2)

        assert _sent(h, began) == [(0, "bo-0"), (200, "bo-2")]
        assert state.plan_id == plan_id
        assert state.step == 2
        assert state.step_started_at_ms == h.clock.now
        h.engine._forget_runner(event_id)

    @pytest.mark.asyncio
    async def test_the_plan_carries_on_from_the_line_moved_to(self):
        h = Harness()
        event_id = uuid4()
        began = h.clock.now
        paused = _Paused(h, until=lambda: h.clock.now - began >= 300)
        await h.engine.start(event_id, _steps(1000, 1000, 1000))
        await _yield()

        await h.engine.seek(event_id, _plan_id(h, event_id), 1, expected_step=0)
        paused.until = lambda: False
        paused.gate.set()
        await h.settle(event_id)

        assert [segments[-1] for _, segments, _ in h.sent] == ["bo-0", "bo-1", "bo-2"]
        assert (await h.engine.state(event_id)).reason == "finished"

    @pytest.mark.asyncio
    async def test_a_press_that_races_the_plan_moving_on_by_itself_is_not_applied_twice(self):
        h = Harness()
        h.gate = asyncio.Event()
        event_id = uuid4()
        await h.engine.start(event_id, _steps(1000, 1000, 1000))
        plan_id = _plan_id(h, event_id)
        # The plan reached line 1 on its own while the press was on its way.
        h.store.states[event_id].update({"step": "1", "step_started_ms": str(h.clock.now)})

        state = await h.engine.seek(event_id, plan_id, 1, expected_step=0)

        assert state.step == 1
        assert len(h.sent) == 1
        h.engine._forget_runner(event_id)

    @pytest.mark.asyncio
    async def test_a_line_already_sent_early_is_not_sent_again_by_a_seek_to_it(self):
        h = _with_lead(300)
        event_id = uuid4()
        paused = _Paused(h, until=lambda: h.store.states[event_id].get("pre_sent") == "1")
        await h.engine.start(event_id, _steps(1000, 1000, 1000))
        await _yield()

        await h.engine.seek(event_id, _plan_id(h, event_id), 1, expected_step=0)

        assert [segments[-1] for _, segments, _ in h.sent] == ["bo-0", "bo-1"]
        assert h.store.states[event_id]["step"] == "1"
        assert h.store.states[event_id]["step_started_ms"] != ""
        h.engine._forget_runner(event_id)
        paused.gate.set()

    @pytest.mark.asyncio
    async def test_a_seek_for_a_plan_that_is_not_running_is_refused(self):
        h = Harness()
        h.gate = asyncio.Event()
        event_id = uuid4()
        await h.engine.start(event_id, _steps(1000, 1000))
        plan_id = _plan_id(h, event_id)

        with pytest.raises(AutoplayCommandRefused):
            await h.engine.seek(event_id, "another-plan", 1)
        with pytest.raises(AutoplayCommandRefused):
            await h.engine.seek(uuid4(), plan_id, 1)
        assert len(h.sent) == 1
        h.engine._forget_runner(event_id)

    @pytest.mark.asyncio
    async def test_a_step_past_the_end_of_the_plan_is_refused(self):
        h = Harness()
        h.gate = asyncio.Event()
        event_id = uuid4()
        await h.engine.start(event_id, _steps(1000, 1000))
        plan_id = _plan_id(h, event_id)

        with pytest.raises(AutoplayCommandRefused):
            await h.engine.seek(event_id, plan_id, 2)
        h.engine._forget_runner(event_id)


class TestLearningThePace:

    @pytest.mark.asyncio
    async def test_ending_a_line_early_speeds_up_the_rest_of_the_plan(self):
        h = Harness()
        h.gate = asyncio.Event()
        event_id = uuid4()
        await h.engine.start(event_id, _steps(1000, 1000, 1000))

        h.clock.now += 500
        state = await h.engine.seek(event_id, _plan_id(h, event_id), 1, expected_step=0)

        assert state.tempo == pytest.approx(next_tempo(1.0, 1000, 500))
        assert state.tempo < 1.0
        assert state.step_duration_ms == effective_duration_ms(1000, state.tempo)
        h.engine._forget_runner(event_id)

    @pytest.mark.asyncio
    async def test_the_line_goes_out_before_the_pace_is_worked_out(self):
        """Learning the pace costs Redis round trips; the room is not kept
        waiting on them."""
        h = Harness()
        h.gate = asyncio.Event()
        event_id = uuid4()
        await h.engine.start(event_id, _steps(1000, 1000, 1000))
        lines_out_when_learned = []
        write = h.store.write_settings

        async def recording_write(event, fields):
            lines_out_when_learned.append(len(h.sent))
            await write(event, fields)

        h.store.write_settings = recording_write
        h.clock.now += 500
        await h.engine.seek(event_id, _plan_id(h, event_id), 1, expected_step=0)

        assert lines_out_when_learned == [2]
        h.engine._forget_runner(event_id)

    @pytest.mark.asyncio
    async def test_a_line_held_past_its_time_slows_the_rest_of_the_plan(self):
        h = Harness()
        h.gate = asyncio.Event()
        event_id = uuid4()
        await h.engine.start(event_id, _steps(1000, 1000, 1000))
        plan_id = _plan_id(h, event_id)

        h.clock.now += 900
        await h.engine.hold(event_id, plan_id)
        h.clock.now += 600
        state = await h.engine.seek(event_id, plan_id, 1, expected_step=0)

        assert state.tempo == pytest.approx(next_tempo(1.0, 1000, 1500))
        assert state.tempo > 1.0
        assert state.held is False
        h.engine._forget_runner(event_id)

    @pytest.mark.asyncio
    async def test_a_press_on_a_line_the_plan_has_passed_does_not_move_it_back(self):
        """The operator's screen was behind: they ended line 1 after the plan
        had already reached line 3 by itself."""
        h = Harness()
        h.gate = asyncio.Event()
        event_id = uuid4()
        await h.engine.start(event_id, _steps(1000, 1000, 1000, 1000))
        plan_id = _plan_id(h, event_id)
        await h.engine.seek(event_id, plan_id, 3)
        sent_before = len(h.sent)

        state = await h.engine.seek(event_id, plan_id, 2, expected_step=1)

        assert state.step == 3
        assert len(h.sent) == sent_before
        h.engine._forget_runner(event_id)

    @pytest.mark.asyncio
    async def test_a_deliberate_move_back_is_still_applied(self):
        h = Harness()
        h.gate = asyncio.Event()
        event_id = uuid4()
        await h.engine.start(event_id, _steps(1000, 1000, 1000, 1000))
        plan_id = _plan_id(h, event_id)
        await h.engine.seek(event_id, plan_id, 3)

        state = await h.engine.seek(event_id, plan_id, 1, expected_step=3)

        assert state.step == 1
        assert h.sent[-1][1][-1] == "bo-1"
        h.engine._forget_runner(event_id)

    @pytest.mark.asyncio
    async def test_a_jump_elsewhere_says_nothing_about_the_pace(self):
        h = Harness()
        h.gate = asyncio.Event()
        event_id = uuid4()
        await h.engine.start(event_id, _steps(1000, 1000, 1000))

        h.clock.now += 200
        state = await h.engine.seek(event_id, _plan_id(h, event_id), 2, expected_step=0)

        assert state.tempo == 1.0
        h.engine._forget_runner(event_id)

    @pytest.mark.asyncio
    async def test_a_double_press_says_nothing_about_the_pace(self):
        h = Harness()
        h.gate = asyncio.Event()
        event_id = uuid4()
        await h.engine.start(event_id, _steps(1000, 1000, 1000))

        h.clock.now += 50
        state = await h.engine.seek(event_id, _plan_id(h, event_id), 1, expected_step=0)

        assert state.tempo == 1.0
        h.engine._forget_runner(event_id)

    @pytest.mark.asyncio
    async def test_the_pace_stretches_every_line_the_runner_holds(self):
        h = Harness()
        event_id = uuid4()
        h.store.settings[event_id] = {"tempo": "1.5"}
        began = h.clock.now

        await h.engine.start(event_id, _steps(1000, 1000))
        await h.settle(event_id)

        assert _sent(h, began) == [(0, "bo-0"), (1500, "bo-1")]

    @pytest.mark.asyncio
    async def test_the_pace_can_be_set_and_reset_by_hand(self):
        h = Harness()
        event_id = uuid4()

        state = await h.engine.update_settings(event_id, tempo=1.3, lead_ms=500)
        assert (state.tempo, state.lead_ms) == (pytest.approx(1.3), 500)
        state = await h.engine.update_settings(event_id, tempo=1.0)
        assert (state.tempo, state.lead_ms) == (1.0, 500)
        assert h.store.published[-1]["tempo"] == 1.0


class TestHolding:

    @pytest.mark.asyncio
    async def test_a_held_line_keeps_what_was_left_of_its_time(self):
        h = Harness()
        event_id = uuid4()
        began = h.clock.now
        paused = _Paused(h, until=lambda: True)
        await h.engine.start(event_id, _steps(1000, 1000))
        plan_id = _plan_id(h, event_id)

        h.clock.now += 400
        held = await h.engine.hold(event_id, plan_id)
        h.clock.now += 2000
        resumed = await h.engine.resume(event_id, plan_id)
        paused.until = lambda: False
        paused.gate.set()
        await h.settle(event_id)

        assert held.held is True
        assert held.held_at_ms == began + 400
        assert resumed.held is False
        assert resumed.step_started_at_ms == began + 2000
        assert _sent(h, began) == [(0, "bo-0"), (3000, "bo-1")]

    @pytest.mark.asyncio
    async def test_a_held_plan_does_not_move_on(self):
        h = Harness()
        event_id = uuid4()
        await h.engine.start(event_id, _steps(1000, 1000))
        await h.engine.hold(event_id)

        await _yield(200)

        assert h.clock.now > 1_000_000 + 5000
        assert len(h.sent) == 1
        assert (await h.engine.state(event_id)).held is True
        h.engine._forget_runner(event_id)

    @pytest.mark.asyncio
    async def test_holding_takes_back_a_line_sent_early(self):
        """The room had been sent the next line ahead of its time; the operator
        holds this one, so the room is put back on it."""
        h = _with_lead(300)
        event_id = uuid4()
        began = h.clock.now
        paused = _Paused(h, until=lambda: h.store.states[event_id].get("pre_sent") == "1")
        await h.engine.start(event_id, _steps(1000, 1000))
        await _yield()

        h.clock.now = began + 800
        paused.until = lambda: True
        state = await h.engine.hold(event_id)

        assert _sent(h, began) == [(0, "bo-0"), (700, "bo-1"), (800, "bo-0")]
        assert state.step == 0
        assert h.store.states[event_id]["pre_sent"] == ""
        h.engine._forget_runner(event_id)
        paused.gate.set()

    @pytest.mark.asyncio
    async def test_pausing_takes_back_a_line_sent_early(self):
        h = _with_lead(300)
        event_id = uuid4()
        began = h.clock.now
        paused = _Paused(h, until=lambda: h.store.states[event_id].get("pre_sent") == "1")
        await h.engine.start(event_id, _steps(1000, 1000))
        await _yield()

        h.clock.now = began + 800
        paused.until = lambda: True
        state = await h.engine.stop(event_id)

        assert [segments[-1] for _, segments, _ in h.sent] == ["bo-0", "bo-1", "bo-0"]
        assert state.status == "stopped"
        paused.gate.set()

    @pytest.mark.asyncio
    async def test_ending_the_session_does_not_put_the_room_back(self):
        h = _with_lead(300)
        event_id = uuid4()
        paused = _Paused(h, until=lambda: h.store.states[event_id].get("pre_sent") == "1")
        await h.engine.start(event_id, _steps(1000, 1000))
        await _yield()

        await h.engine.stop(event_id, reason="ended")

        assert [segments[-1] for _, segments, _ in h.sent] == ["bo-0", "bo-1"]
        paused.gate.set()

    @pytest.mark.asyncio
    async def test_holding_while_the_early_line_is_on_its_way_still_takes_it_back(self):
        """The early line is out but not yet noted as sent when the hold lands:
        the hold must still see it and put the room back."""
        h = _with_lead(300)
        event_id = uuid4()
        began = h.clock.now
        out = asyncio.Event()
        stuck = asyncio.Event()

        async def record(_, frames):
            h.sent.append((h.clock(), [f.segment_id for f in frames], frames))
            if frames[-1].segment_id == "bo-1" and not out.is_set():
                out.set()
                await stuck.wait()

        h.emit.side_effect = record
        await h.engine.start(event_id, _steps(1000, 1000))
        await asyncio.wait_for(out.wait(), timeout=5)

        state = await h.engine.hold(event_id)

        assert _sent(h, began)[-2:] == [(700, "bo-1"), (700, "bo-0")]
        assert state.held is True
        assert h.store.states[event_id]["pre_sent"] == ""
        assert h.store.states[event_id]["pre_sending"] == ""
        h.engine._forget_runner(event_id)

    @pytest.mark.asyncio
    async def test_a_hold_between_a_seek_and_its_send_holds_the_room_on_the_new_line(self):
        """The seek has moved the plan but not sent the line when a hold lands
        on another instance. The hold takes the lease, so the seek's send is
        refused: the hold sends the line itself rather than holding the stage
        on the new line and phones on the old one."""
        clock = Clock()
        store = FakeStore(clock)
        first = Harness(clock=clock, store=store, owner="A")
        second = Harness(clock=clock, store=store, owner="B")
        first_paused = _Paused(first, until=lambda: True)
        second_paused = _Paused(second, until=lambda: True)
        event_id = uuid4()
        began = clock.now
        await first.engine.start(event_id, _steps(1000, 1000, 1000))
        plan_id = _plan_id(first, event_id)
        seek = store.seek

        async def seek_then_hold(*args):
            outcome = await seek(*args)
            await second.engine.hold(event_id, plan_id)
            return outcome

        store.seek = seek_then_hold
        clock.now += 200
        state = await first.engine.seek(event_id, plan_id, 2)

        assert _sent(first, began) == [(0, "bo-0")]
        assert _sent(second, began) == [(200, "bo-2")]
        assert state.step == 2
        assert state.held is True
        assert state.step_started_at_ms == began + 200
        first.engine._forget_runner(event_id)
        second.engine._forget_runner(event_id)
        first_paused.gate.set()
        second_paused.gate.set()

    @pytest.mark.asyncio
    async def test_a_held_line_whose_send_failed_is_sent_by_the_next_hold(self):
        """The hold lands on a line the plan has moved to but not sent, and
        sending it fails. The runner never sends while held, so the next hold
        must send it rather than find the plan already held and stop there."""
        h = Harness()
        paused = _Paused(h, until=lambda: True)
        failing = {"on": False}

        async def record(_, frames):
            if failing["on"]:
                failing["on"] = False
                raise RuntimeError("redis went away")
            h.sent.append((h.clock(), [f.segment_id for f in frames], frames))

        h.emit.side_effect = record
        event_id = uuid4()
        began = h.clock.now
        await h.engine.start(event_id, _steps(1000, 1000, 1000))
        plan_id = _plan_id(h, event_id)
        await h.store.seek(event_id, plan_id, 1, None, "B")

        h.clock.now += 200
        failing["on"] = True
        with pytest.raises(RuntimeError):
            await h.engine.hold(event_id, plan_id)

        assert _sent(h, began) == [(0, "bo-0")]
        assert h.store.states[event_id]["held"] == "1"
        assert h.store.states[event_id]["step_started_ms"] == ""

        h.clock.now += 100
        state = await h.engine.hold(event_id, plan_id)

        assert _sent(h, began) == [(0, "bo-0"), (300, "bo-1")]
        assert state.step == 1
        assert state.held is True
        assert state.step_started_at_ms == began + 300
        h.engine._forget_runner(event_id)
        paused.gate.set()

    @pytest.mark.asyncio
    async def test_a_hold_that_lands_first_stops_the_early_line_going(self):
        h = _with_lead(300)
        event_id = uuid4()
        await h.engine.start(event_id, _steps(1000, 1000))
        plan_id = _plan_id(h, event_id)
        started = h.store.states[event_id]["step_started_ms"]
        await h.store.hold(event_id, plan_id, h.clock(), "A")

        plan = h.engine._plans[event_id][1]
        sent = await h.engine._send_early(event_id, plan_id, plan, 0, started, 1000)

        assert sent is False
        assert [segments[-1] for _, segments, _ in h.sent] == ["bo-0"]
        h.engine._forget_runner(event_id)

    @pytest.mark.asyncio
    async def test_a_pause_whose_take_back_fails_is_not_reported_and_can_be_retried(self):
        h = _with_lead(300)
        event_id = uuid4()
        began = h.clock.now
        paused = _Paused(h, until=lambda: h.store.states[event_id].get("pre_sent") == "1")
        failing = {"on": False}

        async def record(_, frames):
            if failing["on"]:
                failing["on"] = False
                raise RuntimeError("redis went away")
            h.sent.append((h.clock(), [f.segment_id for f in frames], frames))

        h.emit.side_effect = record
        await h.engine.start(event_id, _steps(1000, 1000))
        await _yield()

        h.clock.now = began + 800
        paused.until = lambda: True
        failing["on"] = True
        with pytest.raises(RuntimeError):
            await h.engine.stop(event_id)

        assert h.store.states[event_id]["status"] == "running"
        assert h.store.states[event_id]["held"] == "1"
        assert _sent(h, began) == [(0, "bo-0"), (700, "bo-1")]

        state = await h.engine.stop(event_id)

        assert state.status == "stopped"
        assert _sent(h, began) == [(0, "bo-0"), (700, "bo-1"), (800, "bo-0")]
        paused.gate.set()

    @pytest.mark.asyncio
    async def test_holding_or_resuming_with_no_plan_is_refused(self):
        h = Harness()
        with pytest.raises(AutoplayCommandRefused):
            await h.engine.hold(uuid4())
        with pytest.raises(AutoplayCommandRefused):
            await h.engine.resume(uuid4())


class TestPaceAndLeadArithmetic:

    def test_one_press_moves_the_pace_only_part_of_the_way(self):
        assert next_tempo(1.0, 1000, 500) == pytest.approx(0.825)
        assert next_tempo(1.0, 1000, 1000) == 1.0

    def test_a_wild_press_is_capped_before_it_is_weighed(self):
        assert next_tempo(1.0, 1000, 60_000) == pytest.approx(1.35)

    def test_the_pace_stays_within_its_bounds(self):
        tempo = 1.0
        for _ in range(50):
            tempo = next_tempo(tempo, 1000, 100)
        assert tempo == pytest.approx(0.6)

    def test_a_held_line_is_never_shorter_than_a_line_can_be_recited(self):
        assert effective_duration_ms(400, 0.6) == 300

    def test_the_lead_is_never_more_than_half_the_line(self):
        assert lead_for(1000, 300) == 300
        assert lead_for(400, 300) == 200
        assert lead_for(1000, 0) == 0

    def test_unreadable_settings_fall_back_to_their_defaults(self):
        settings = _settings_from({"tempo": "fast", "lead_ms": "soon"})
        assert settings.tempo == 1.0
        assert settings.lead_ms == 300
        assert _settings_from({"tempo": "9", "lead_ms": "99999"}).tempo == 1.6
        assert _settings_from({"lead_ms": "99999"}).lead_ms == 2000


class TestCommandScripts:
    """The store hands each command to Redis as one script, so the change and
    taking the lease cannot come apart."""

    @staticmethod
    def _redis(result):
        redis = MagicMock()
        redis.eval = AsyncMock(return_value=result)
        return redis

    @pytest.mark.asyncio
    async def test_seek_names_the_plan_step_and_the_step_the_operator_saw(self):
        redis = self._redis([1, "3", "1234"])
        event_id = uuid4()

        outcome = await AutoplayStore(redis).seek(event_id, "plan-1", 4, 3, "A")

        assert outcome == SeekOutcome("moved", 3, 1234)
        args = redis.eval.await_args.args
        assert list(args[2:4]) == [
            f"recitation:event:{event_id}:autoplay",
            f"recitation:event:{event_id}:autoplay-lease",
        ]
        assert list(args[4:]) == ["plan-1", "4", "3", "A", str(LEASE_MS)]

    @pytest.mark.asyncio
    async def test_a_refused_seek_reads_as_refused(self):
        outcome = await AutoplayStore(self._redis([0, "", ""])).seek(uuid4(), "p", 1, None, "A")
        assert outcome.result == "refused"

    @pytest.mark.asyncio
    async def test_hold_reports_whether_the_room_must_be_put_back(self):
        redis = self._redis([1, "plan-1", "2", "999", 1])

        outcome = await AutoplayStore(redis).hold(uuid4(), None, 5000, "A")

        assert outcome == HoldOutcome("held", "plan-1", 2, "999", True)
        assert list(redis.eval.await_args.args[4:]) == ["", "5000", "A", str(LEASE_MS)]

    @pytest.mark.asyncio
    async def test_resume_reports_the_plan(self):
        redis = self._redis([1, "plan-1"])
        assert await AutoplayStore(redis).resume(uuid4(), "plan-1", 5000, "A") == (
            "resumed",
            "plan-1",
        )

    @pytest.mark.asyncio
    async def test_settings_are_kept_apart_from_the_plan(self):
        redis = MagicMock()
        redis.hgetall = AsyncMock(return_value={"tempo": "1.2", "lead_ms": "450"})
        event_id = uuid4()

        settings = await AutoplayStore(redis).read_settings(event_id)

        redis.hgetall.assert_awaited_once_with(f"recitation:event:{event_id}:autoplay-settings")
        assert (settings.tempo, settings.lead_ms) == (1.2, 450)
