"""Autoplay, run by the backend.

The controller lays the puja out as a plan - each step one line in every
edition being followed, with how long the room holds it - and hands it over.
From then on the backend is the clock: it sends each step to the room, holds it
for its time, and moves on, whatever the operator's phone is doing. A phone
that locks, sleeps or loses its signal no longer stalls the room.

The plan is the controller's. Where the Returns go, which rounds, which lines
are yigchung and passed over - all of that is already worked out in it, so
nothing here knows what a Return is. A change of plan (a hand move, a new round
count) is a new plan sent in its place.

Exactly one instance runs an event's autoplay, by holding a short lease in
Redis. The plan, the step and when that step went out are kept there too, so
when the holder goes away - a deploy, a crash - another instance takes the
lease over and carries on from the same step, holding it only for what is left
of its time.
"""

import asyncio
import json
import logging
import time
from typing import Awaitable, Callable, Dict, List, Optional
from uuid import UUID, uuid4

from pecha_api.events.recitation_live_models import (
    AutoplayStateResponse,
    AutoplayStep,
    SetPositionFrame,
)
from pecha_api.events.recitation_websocket import (
    POSITION_TTL_SECONDS,
    autoplay_channel,
    autoplay_lease_key,
    autoplay_plan_key,
    autoplay_state_key,
)

logger = logging.getLogger(__name__)

# The lease is short so a dead holder is replaced quickly; the runner renews it
# at least once a tick, well inside it.
LEASE_MS = 5000
TICK_SECONDS = 1.0
# How often each instance looks for autoplay nobody is running.
SUPERVISOR_INTERVAL_SECONDS = 2.0
# A step that goes out this late still starts where the last one ended, so a
# slow tick is not added to every line after it. Any later - an instance that
# was stalled, a takeover after a crash - and it starts now, rather than racing
# the room through the lines it missed.
LATE_CATCH_UP_MS = 1000

_STATE_KEY_PATTERN = "recitation:event:*:autoplay"

Emitter = Callable[[UUID, List[SetPositionFrame]], Awaitable[None]]


def _now_ms() -> int:
    return int(time.time() * 1000)


# Every change the runner makes is conditional on it still holding the lease
# and the plan still being the one it is running, checked in the same step as
# the write. A runner whose lease was taken over, or whose plan was replaced
# while it slept, can then never move the state on behind the new owner's back.
_ADVANCE_SCRIPT = """
if redis.call('GET', KEYS[2]) ~= ARGV[1] then return 0 end
if redis.call('HGET', KEYS[1], 'plan_id') ~= ARGV[2] then return 0 end
if redis.call('HGET', KEYS[1], 'status') ~= 'running' then return 0 end
if redis.call('HGET', KEYS[1], 'step') ~= ARGV[3] then return 0 end
if redis.call('HGET', KEYS[1], 'step_started_ms') ~= ARGV[4] then return 0 end
for i = 5, #ARGV, 2 do
    redis.call('HSET', KEYS[1], ARGV[i], ARGV[i + 1])
end
return 1
"""

# Renewing the lease keeps the plan and its state alive with it: a plan may
# run longer than their TTL, and losing them mid-run would stop the room with
# nobody told and nobody able to take over.
_RENEW_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    redis.call('PEXPIRE', KEYS[1], ARGV[2])
    redis.call('EXPIRE', KEYS[2], ARGV[3])
    redis.call('EXPIRE', KEYS[3], ARGV[3])
    return 1
end
return 0
"""

# Asked just before a step goes out: the runner still holds the lease and its
# plan is still at the step, unsent, as it last saw it. Renews the lease and
# the plan's TTL on success, as _RENEW_SCRIPT does.
_MAY_SEND_SCRIPT = """
if redis.call('GET', KEYS[2]) ~= ARGV[1] then return 0 end
if redis.call('HGET', KEYS[1], 'plan_id') ~= ARGV[2] then return 0 end
if redis.call('HGET', KEYS[1], 'status') ~= 'running' then return 0 end
if redis.call('HGET', KEYS[1], 'step') ~= ARGV[3] then return 0 end
if redis.call('HGET', KEYS[1], 'step_started_ms') ~= ARGV[4] then return 0 end
redis.call('PEXPIRE', KEYS[2], ARGV[5])
redis.call('EXPIRE', KEYS[1], ARGV[6])
redis.call('EXPIRE', KEYS[3], ARGV[6])
return 1
"""

# Stopping is conditional on the plan too when a plan is named: a runner that
# finishes an old plan must not stop the new one that replaced it. When an
# owner is named it must still hold the lease: a runner that stalled past its
# lease must not stop the instance that took the plan over.
_STOP_SCRIPT = """
if redis.call('EXISTS', KEYS[1]) == 0 then return 0 end
if ARGV[1] ~= '' and redis.call('HGET', KEYS[1], 'plan_id') ~= ARGV[1] then return 0 end
if ARGV[3] ~= '' and redis.call('GET', KEYS[2]) ~= ARGV[3] then return 0 end
redis.call('HSET', KEYS[1], 'status', 'stopped', 'reason', ARGV[2])
redis.call('DEL', KEYS[2])
return 1
"""

_RELEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


class AutoplayStore:
    """Autoplay's shared state in Redis: the plan, the step, the lease."""

    def __init__(self, redis: object) -> None:
        self.redis = redis

    async def begin(
        self, event_id: UUID, plan_id: str, plan_json: str, total: int, owner: str
    ) -> None:
        """Put a new plan in place at its first step, not yet sent, and take the
        lease for `owner` outright: whoever ran the old plan stops at its next
        conditional write."""
        state_key = autoplay_state_key(event_id)
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.set(autoplay_plan_key(event_id), plan_json, ex=POSITION_TTL_SECONDS)
            pipe.delete(state_key)
            pipe.hset(
                state_key,
                mapping={
                    "plan_id": plan_id,
                    "status": "running",
                    "reason": "",
                    "step": "0",
                    "step_started_ms": "",
                    "due_ms": "",
                    "total": str(total),
                },
            )
            pipe.expire(state_key, POSITION_TTL_SECONDS)
            pipe.set(autoplay_lease_key(event_id), owner, px=LEASE_MS)
            await pipe.execute()

    async def read(self, event_id: UUID) -> Optional[Dict[str, str]]:
        state = await self.redis.hgetall(autoplay_state_key(event_id))
        return state or None

    async def read_plan(self, event_id: UUID) -> Optional[str]:
        return await self.redis.get(autoplay_plan_key(event_id))

    async def advance(
        self,
        event_id: UUID,
        owner: str,
        plan_id: str,
        step: int,
        step_started_ms: str,
        fields: Dict[str, str],
    ) -> bool:
        """Write `fields` only if `owner` still holds the lease and the plan is
        still at `step` as the runner last saw it."""
        args: List[str] = [owner, plan_id, str(step), step_started_ms]
        for name, value in fields.items():
            args.extend([name, value])
        done = await self.redis.eval(
            _ADVANCE_SCRIPT,
            2,
            autoplay_state_key(event_id),
            autoplay_lease_key(event_id),
            *args,
        )
        return bool(done)

    async def may_send(
        self,
        event_id: UUID,
        owner: str,
        plan_id: str,
        step: int,
        step_started_ms: str,
    ) -> bool:
        """Whether `owner` may send `step` of `plan_id` now; renews its lease
        if so."""
        return bool(
            await self.redis.eval(
                _MAY_SEND_SCRIPT,
                3,
                autoplay_state_key(event_id),
                autoplay_lease_key(event_id),
                autoplay_plan_key(event_id),
                owner,
                plan_id,
                str(step),
                step_started_ms,
                str(LEASE_MS),
                str(POSITION_TTL_SECONDS),
            )
        )

    async def stop(
        self,
        event_id: UUID,
        reason: str,
        plan_id: Optional[str] = None,
        owner: Optional[str] = None,
    ) -> bool:
        done = await self.redis.eval(
            _STOP_SCRIPT,
            2,
            autoplay_state_key(event_id),
            autoplay_lease_key(event_id),
            plan_id or "",
            reason,
            owner or "",
        )
        return bool(done)

    async def claim(self, event_id: UUID, owner: str) -> bool:
        """Take the lease if nobody holds it."""
        return bool(
            await self.redis.set(autoplay_lease_key(event_id), owner, nx=True, px=LEASE_MS)
        )

    async def renew(self, event_id: UUID, owner: str) -> bool:
        return bool(
            await self.redis.eval(
                _RENEW_SCRIPT,
                3,
                autoplay_lease_key(event_id),
                autoplay_state_key(event_id),
                autoplay_plan_key(event_id),
                owner,
                str(LEASE_MS),
                str(POSITION_TTL_SECONDS),
            )
        )

    async def release(self, event_id: UUID, owner: str) -> None:
        await self.redis.eval(_RELEASE_SCRIPT, 1, autoplay_lease_key(event_id), owner)

    async def running_events(self) -> List[UUID]:
        """Events whose autoplay is running, on whichever instance."""
        found: List[UUID] = []
        async for key in self.redis.scan_iter(match=_STATE_KEY_PATTERN, count=100):
            if await self.redis.hget(key, "status") != "running":
                continue
            try:
                found.append(UUID(key.split(":")[2]))
            except (IndexError, ValueError):
                continue
        return found

    async def publish(self, event_id: UUID, payload: str) -> None:
        await self.redis.publish(autoplay_channel(event_id), payload)


def _state_response(
    event_id: UUID, state: Optional[Dict[str, str]], plan: Optional[List[dict]] = None
) -> AutoplayStateResponse:
    """The state as the controller reads it."""
    now = _now_ms()
    if not state:
        return AutoplayStateResponse(event_id=event_id, status="stopped", server_time_ms=now)
    step = int(state.get("step") or 0)
    started = state.get("step_started_ms") or ""
    duration: Optional[int] = None
    if plan is not None and 0 <= step < len(plan):
        duration = int(plan[step]["duration_ms"])
    return AutoplayStateResponse(
        event_id=event_id,
        plan_id=state.get("plan_id") or None,
        status=state.get("status") or "stopped",
        reason=state.get("reason") or None,
        step=step,
        total_steps=int(state.get("total") or 0),
        step_started_at_ms=int(started) if started else None,
        step_duration_ms=duration,
        server_time_ms=now,
    )


class AutoplayEngine:
    """This instance's share of autoplay: the runners it holds the lease for."""

    def __init__(
        self,
        store: AutoplayStore,
        emit: Emitter,
        owner: Optional[str] = None,
        clock: Callable[[], int] = _now_ms,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.store = store
        self.emit = emit
        self.owner = owner or str(uuid4())
        self.clock = clock
        self.sleep = sleep
        self._runners: Dict[UUID, asyncio.Task] = {}
        # The plan each of those runners is running.
        self._runner_plans: Dict[UUID, str] = {}
        self._plans: Dict[UUID, tuple] = {}
        self._supervisor: Optional[asyncio.Task] = None

    # Commands ---------------------------------------------------------------

    async def start(
        self,
        event_id: UUID,
        steps: List[AutoplayStep],
        first_step_elapsed_ms: Optional[int] = None,
    ) -> AutoplayStateResponse:
        """Run `steps` from the first, replacing whatever plan was running. The
        first step goes out before this returns, so the controller is answered
        with the room already on it - unless `first_step_elapsed_ms` says the
        room is on it already, when it is only held for what is left."""
        plan = [
            {
                "positions": [
                    position.model_copy(update={"autoplay": True}).model_dump(mode="json")
                    for position in step.positions
                ],
                "duration_ms": step.duration_ms,
            }
            for step in steps
        ]
        plan_id = uuid4().hex
        # The old runner goes before the new plan is in place, so no line of
        # the old plan can go out after the first of the new one. If the new
        # plan is not saved, the old one is still the plan: its runner comes
        # back rather than leaving it stalled until the lease lapses.
        replaced = self._runner_plans.get(event_id) if self._running_here(event_id) else None
        self._forget_runner(event_id)
        try:
            await self.store.begin(
                event_id, plan_id, json.dumps(plan), total=len(plan), owner=self.owner
            )
        except Exception:
            # Unless another start got in while this one waited: its runner
            # is the one to keep, and it must stay the one tracked here.
            if replaced is not None and not self._running_here(event_id):
                self._spawn(event_id, replaced)
            raise
        try:
            self._plans[event_id] = (plan_id, plan)
            if first_step_elapsed_ms is None:
                await self._send_step(event_id, plan_id, plan, 0, "", self.clock())
            else:
                started = self.clock() - first_step_elapsed_ms
                if await self.store.advance(
                    event_id, self.owner, plan_id, 0, "", {"step_started_ms": str(started)}
                ):
                    await self._announce(event_id, await self.state(event_id))
            self._spawn(event_id, plan_id)
            return await self.state(event_id)
        except Exception:
            # Only this plan: another request may already have replaced it,
            # and that one succeeded.
            await self._finish(event_id, plan_id, "failed")
            raise

    async def stop(self, event_id: UUID, reason: str = "stopped") -> AutoplayStateResponse:
        """Stop the plan wherever it runs. Raises if the stop could not be
        recorded: a runner on another instance may then still be sending."""
        try:
            await self.store.stop(event_id, reason)
        finally:
            self._forget_runner(event_id)
        state = await self.state(event_id)
        await self._announce(event_id, state)
        return state

    async def state(self, event_id: UUID) -> AutoplayStateResponse:
        state = await self.store.read(event_id)
        plan = await self._plan_for(event_id, state.get("plan_id") if state else None)
        return _state_response(event_id, state, plan)

    # Lifecycle --------------------------------------------------------------

    def start_supervisor(self) -> None:
        if self._supervisor is None:
            self._supervisor = asyncio.create_task(self._supervise())

    async def shutdown(self) -> None:
        """Leave: runners stop, and their leases are handed back so another
        instance takes the autoplay over at once rather than when they lapse."""
        if self._supervisor is not None:
            self._supervisor.cancel()
            await asyncio.gather(self._supervisor, return_exceptions=True)
            self._supervisor = None
        events = list(self._runners)
        for event_id in events:
            self._forget_runner(event_id)
        for event_id in events:
            try:
                await self.store.release(event_id, self.owner)
            except Exception as e:
                logger.exception("Failed to release autoplay lease: %s", e)

    async def _supervise(self) -> None:
        while True:
            try:
                await self.adopt_orphans()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.exception("Autoplay supervisor failed a pass: %s", e)
            await self.sleep(SUPERVISOR_INTERVAL_SECONDS)

    async def adopt_orphans(self) -> None:
        """Take over any running autoplay whose holder has gone away."""
        for event_id in await self.store.running_events():
            if self._running_here(event_id):
                continue
            if not await self.store.claim(event_id, self.owner):
                continue
            state = await self.store.read(event_id)
            if not state or state.get("status") != "running":
                await self.store.release(event_id, self.owner)
                continue
            logger.info("Taking over autoplay for event %s", event_id)
            self._spawn(event_id, state["plan_id"])

    # The runner -------------------------------------------------------------

    def _running_here(self, event_id: UUID) -> bool:
        task = self._runners.get(event_id)
        return task is not None and not task.done()

    def _spawn(self, event_id: UUID, plan_id: str) -> None:
        task = asyncio.create_task(self._run(event_id, plan_id))
        self._runners[event_id] = task
        self._runner_plans[event_id] = plan_id

        def _done(finished: asyncio.Task) -> None:
            if self._runners.get(event_id) is finished:
                del self._runners[event_id]
                self._runner_plans.pop(event_id, None)

        task.add_done_callback(_done)

    def _forget_runner(self, event_id: UUID) -> None:
        task = self._runners.pop(event_id, None)
        self._runner_plans.pop(event_id, None)
        if task is not None and not task.done():
            task.cancel()

    async def _plan_for(self, event_id: UUID, plan_id: Optional[str]) -> Optional[List[dict]]:
        if not plan_id:
            return None
        held = self._plans.get(event_id)
        if held and held[0] == plan_id:
            return held[1]
        raw = await self.store.read_plan(event_id)
        if not raw:
            return None
        try:
            plan = json.loads(raw)
        except ValueError:
            return None
        self._plans[event_id] = (plan_id, plan)
        return plan

    async def _run(self, event_id: UUID, plan_id: str) -> None:
        try:
            await self._run_plan(event_id, plan_id)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("Autoplay for event %s failed: %s", event_id, e)
            await self._finish(event_id, plan_id, "failed", owner=self.owner)

    async def _run_plan(self, event_id: UUID, plan_id: str) -> None:
        while True:
            state = await self.store.read(event_id)
            if not state or state.get("plan_id") != plan_id or state.get("status") != "running":
                return
            plan = await self._plan_for(event_id, plan_id)
            if not plan:
                await self._finish(event_id, plan_id, "failed", owner=self.owner)
                return
            step = int(state.get("step") or 0)
            started = state.get("step_started_ms") or ""

            if not started:
                # Moved on to, but not sent yet: this runner advanced to it, or
                # took over from one that stopped in between.
                due = state.get("due_ms") or ""
                start_at = int(due) if due else self.clock()
                if not await self._send_step(event_id, plan_id, plan, step, "", start_at):
                    return
                continue

            deadline = int(started) + int(plan[step]["duration_ms"])
            now = self.clock()
            if now < deadline:
                # Woken at least three times a lease, so it is renewed long
                # before it could lapse under a runner that is still here.
                tick = min(TICK_SECONDS, LEASE_MS / 3000)
                await self.sleep(min(tick, (deadline - now) / 1000))
                if not await self.store.renew(event_id, self.owner):
                    return
                continue

            following = step + 1
            if following >= len(plan):
                await self._finish(event_id, plan_id, "finished", owner=self.owner)
                return
            # Where this step ended, unless far late: see LATE_CATCH_UP_MS.
            due = deadline if now - deadline < LATE_CATCH_UP_MS else now
            moved = await self.store.advance(
                event_id,
                self.owner,
                plan_id,
                step,
                started,
                {"step": str(following), "step_started_ms": "", "due_ms": str(due)},
            )
            if not moved:
                return

    async def _send_step(
        self,
        event_id: UUID,
        plan_id: str,
        plan: List[dict],
        step: int,
        expected_started: str,
        start_at: int,
    ) -> bool:
        """Send one step to the room and mark it sent.

        Sent first, marked after: an instance that dies in between leaves the
        step unmarked, and whoever takes over sends it again - the room shown
        the same line twice, never a line skipped. Just before sending, the
        runner checks it still holds the lease and its plan is still at this
        step, unsent, so a runner whose plan was replaced or stopped does not
        send at all.
        """
        if not await self.store.may_send(
            event_id, self.owner, plan_id, step, expected_started
        ):
            return False
        positions = [SetPositionFrame.model_validate(p) for p in plan[step]["positions"]]
        await self.emit(event_id, positions)
        marked = await self.store.advance(
            event_id,
            self.owner,
            plan_id,
            step,
            expected_started,
            {"step_started_ms": str(start_at), "due_ms": ""},
        )
        if marked:
            await self._announce(event_id, await self.state(event_id))
        return marked

    async def _finish(
        self, event_id: UUID, plan_id: str, reason: str, owner: Optional[str] = None
    ) -> None:
        try:
            if await self.store.stop(event_id, reason, plan_id=plan_id, owner=owner):
                await self._announce(event_id, await self.state(event_id))
        except Exception as e:
            logger.exception("Failed to stop autoplay for event %s: %s", event_id, e)

    async def _announce(self, event_id: UUID, state: AutoplayStateResponse) -> None:
        try:
            await self.store.publish(event_id, state.model_dump_json())
        except Exception as e:
            # The operator's screen misses one update; the next one corrects it.
            logger.exception("Failed to publish autoplay state: %s", e)


engine: Optional[AutoplayEngine] = None


def get_autoplay_engine() -> AutoplayEngine:
    if engine is None:
        raise RuntimeError("Recitation autoplay is not initialized")
    return engine


async def init_autoplay(redis: object, emit: Emitter) -> AutoplayEngine:
    global engine
    engine = AutoplayEngine(AutoplayStore(redis), emit)
    engine.start_supervisor()
    return engine


async def shutdown_autoplay() -> None:
    global engine
    if engine is not None:
        await engine.shutdown()
        engine = None
