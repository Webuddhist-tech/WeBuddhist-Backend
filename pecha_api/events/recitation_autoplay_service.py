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
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, List, Optional
from uuid import UUID, uuid4

from pecha_api.events.recitation_live_models import (
    MAX_AUTOPLAY_LEAD_MS,
    MAX_AUTOPLAY_STEP_MS,
    MAX_AUTOPLAY_TEMPO,
    MIN_AUTOPLAY_STEP_MS,
    MIN_AUTOPLAY_TEMPO,
    AutoplayStateResponse,
    AutoplayStep,
    SetPositionFrame,
)
from pecha_api.events.recitation_websocket import (
    POSITION_TTL_SECONDS,
    AutoplayGuard,
    autoplay_channel,
    autoplay_lease_key,
    autoplay_plan_key,
    autoplay_settings_key,
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
# How early each step is sent to the room unless the operator says otherwise.
# A phone shows a position the moment it lands, and it lands this much after
# it is sent on a typical connection: sent this early, it lands with the stage.
DEFAULT_LEAD_MS = 300
# How much one hand move counts towards the room's pace. The pace is the
# recorded times scaled: a press half way through a line says the room is
# reciting at about twice the recorded speed, and the pace moves this share of
# the way there, so one stray press does not lurch the whole puja.
TEMPO_LEARNING_RATE = 0.35
# What a single press may say about the pace, either way, before it is weighed.
MAX_TEMPO_OBSERVATION = 2.0

_STATE_KEY_PATTERN = "recitation:event:*:autoplay"

# False: the step went out only in part, or not at all, because its plan stopped
# being current while it was sending. Anything else: the step was published.
Emitter = Callable[[UUID, List[SetPositionFrame]], Awaitable[Optional[bool]]]
# Whether the event this plan is for still exists. None in tests, which have no
# database; production checks before every step.
LiveCheck = Callable[[UUID], Awaitable[bool]]


_send_permit: ContextVar[Optional[AutoplayGuard]] = ContextVar(
    "autoplay_send_permit", default=None
)


def current_autoplay_send_permit() -> Optional[AutoplayGuard]:
    """The plan this task is allowed to publish, while it is sending a step.

    `may_send` returning is not enough: the publish is its own await, and a
    new plan or a stopped session can land while it is in flight. The publish
    checks this again, in the same Redis step as the write.
    """
    return _send_permit.get()


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

# Renewing the lease keeps the plan, its state and the event's settings alive
# with it: a plan may run longer than their TTL, and losing the plan mid-run
# would stop the room with nobody told and nobody able to take over, while
# losing the settings would drop the room's learned pace back to the default.
_RENEW_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    redis.call('PEXPIRE', KEYS[1], ARGV[2])
    redis.call('EXPIRE', KEYS[2], ARGV[3])
    redis.call('EXPIRE', KEYS[3], ARGV[3])
    redis.call('EXPIRE', KEYS[4], ARGV[3])
    return 1
end
return 0
"""

# Asked just before a step goes out: the runner still holds the lease and its
# plan is still at the step, unsent, as it last saw it. Renews the lease and
# the TTLs on success, as _RENEW_SCRIPT does.
_MAY_SEND_SCRIPT = """
if redis.call('GET', KEYS[2]) ~= ARGV[1] then return 0 end
if redis.call('HGET', KEYS[1], 'plan_id') ~= ARGV[2] then return 0 end
if redis.call('HGET', KEYS[1], 'status') ~= 'running' then return 0 end
if redis.call('HGET', KEYS[1], 'step') ~= ARGV[3] then return 0 end
if redis.call('HGET', KEYS[1], 'step_started_ms') ~= ARGV[4] then return 0 end
redis.call('PEXPIRE', KEYS[2], ARGV[5])
redis.call('EXPIRE', KEYS[1], ARGV[6])
redis.call('EXPIRE', KEYS[3], ARGV[6])
redis.call('EXPIRE', KEYS[4], ARGV[6])
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

# The operator's commands land wherever the operator's socket is, not where the
# runner is. Each one makes its change and takes the lease for the instance it
# landed on in the same step, so that instance can act on it at once - send the
# line, take back one sent early - instead of waiting for the runner's next
# tick. The old runner's next conditional write fails, and it stops.

# A seek moves the plan to `step`, unsent. Returns {outcome, the step it was
# on, when that step went out}: 1 moved, 2 a forward press the plan has already
# reached or passed by itself (made on a line the plan has since moved on from:
# applying it would put the room back on an old line), 0 refused. A step
# already sent to the room early stays marked so it is not sent again; one
# only on its way out is not.
_SEEK_SCRIPT = """
if redis.call('HGET', KEYS[1], 'status') ~= 'running' then return {0, '', ''} end
if redis.call('HGET', KEYS[1], 'plan_id') ~= ARGV[1] then return {0, '', ''} end
if tonumber(ARGV[2]) >= tonumber(redis.call('HGET', KEYS[1], 'total') or '0') then
    return {0, '', ''}
end
local current = redis.call('HGET', KEYS[1], 'step') or '0'
local started = redis.call('HGET', KEYS[1], 'step_started_ms') or ''
if ARGV[3] ~= '' and current ~= ARGV[3]
    and tonumber(ARGV[2]) > tonumber(ARGV[3])
    and tonumber(current) >= tonumber(ARGV[2]) then
    return {2, current, started}
end
local pre_sent = redis.call('HGET', KEYS[1], 'pre_sent') or ''
if pre_sent ~= ARGV[2] then pre_sent = '' end
redis.call('HSET', KEYS[1],
    'step', ARGV[2], 'step_started_ms', '', 'due_ms', '',
    'pre_sent', pre_sent, 'pre_sending', '', 'held', '', 'held_at_ms', '')
redis.call('SET', KEYS[2], ARGV[4], 'PX', ARGV[5])
return {1, current, started}
"""

# Holds the plan on its step. Returns {outcome, plan, step, when it went out,
# resend}: 1 held, 2 already held, 0 refused. `resend` is 1 when the room may
# not be on this step: the next line went to the room early, in whole or in
# part, and the room is put back on this one; or this step was never marked
# sent, and it is sent. Neither mark is cleared until that send has landed
# (_CLEAR_EARLY_SCRIPT, or the step marked sent), so a hold whose send failed
# is retried by the next hold rather than forgotten - the runner never sends
# while held - and the lease is taken for it then too.
_HOLD_SCRIPT = """
if redis.call('HGET', KEYS[1], 'status') ~= 'running' then return {0, '', '', '', 0} end
local plan_id = redis.call('HGET', KEYS[1], 'plan_id')
if ARGV[1] ~= '' and plan_id ~= ARGV[1] then return {0, '', '', '', 0} end
local step = redis.call('HGET', KEYS[1], 'step') or '0'
local started = redis.call('HGET', KEYS[1], 'step_started_ms') or ''
local pre_sent = redis.call('HGET', KEYS[1], 'pre_sent') or ''
local pre_sending = redis.call('HGET', KEYS[1], 'pre_sending') or ''
local resend = 0
if started == '' or (pre_sent ~= '' and pre_sent ~= step)
    or (pre_sending ~= '' and pre_sending ~= step) then
    resend = 1
end
local outcome = 1
if redis.call('HGET', KEYS[1], 'held') == '1' then
    outcome = 2
else
    redis.call('HSET', KEYS[1], 'held', '1', 'held_at_ms', ARGV[2])
end
if outcome == 1 or resend == 1 then
    redis.call('SET', KEYS[2], ARGV[3], 'PX', ARGV[4])
end
return {outcome, plan_id, step, started, resend}
"""

# Notes the step after the current one going to the room early. ARGV[5] is
# 'sending' just before it goes - so a hold that lands while it is on its way
# still puts the room back - and 'sent' once all of it is out, which is what
# lets it pass without being sent again when its time comes. Refused while the
# plan is held: a held room gets no early line. ARGV[6], with 'sending', is how
# long the current step is held: fixed from then on (see _step_duration_ms).
_NOTE_EARLY_SCRIPT = """
if redis.call('GET', KEYS[2]) ~= ARGV[1] then return 0 end
if redis.call('HGET', KEYS[1], 'plan_id') ~= ARGV[2] then return 0 end
if redis.call('HGET', KEYS[1], 'status') ~= 'running' then return 0 end
if redis.call('HGET', KEYS[1], 'step') ~= ARGV[3] then return 0 end
if redis.call('HGET', KEYS[1], 'step_started_ms') ~= ARGV[4] then return 0 end
if redis.call('HGET', KEYS[1], 'held') == '1' then return 0 end
local following = tostring(tonumber(ARGV[3]) + 1)
if ARGV[5] == 'sending' then
    redis.call('HSET', KEYS[1], 'pre_sending', following, 'fixed_duration_ms', ARGV[6])
    return 1
end
if redis.call('HGET', KEYS[1], 'pre_sending') ~= following then return 0 end
redis.call('HSET', KEYS[1], 'pre_sent', following)
return 1
"""

# The room is back on the held line: the early one no longer needs taking back.
_CLEAR_EARLY_SCRIPT = """
if redis.call('HGET', KEYS[1], 'plan_id') ~= ARGV[1] then return 0 end
if redis.call('HGET', KEYS[1], 'step') ~= ARGV[2] then return 0 end
if redis.call('HGET', KEYS[1], 'step_started_ms') ~= ARGV[3] then return 0 end
redis.call('HSET', KEYS[1], 'pre_sent', '', 'pre_sending', '')
return 1
"""

# Lets a held plan go on. The step keeps what was left of its time when it was
# held: its start moves on by the length of the hold. Returns {outcome, plan}:
# 1 resumed, 2 was not held, 0 refused.
_RESUME_SCRIPT = """
if redis.call('HGET', KEYS[1], 'status') ~= 'running' then return {0, ''} end
local plan_id = redis.call('HGET', KEYS[1], 'plan_id')
if ARGV[1] ~= '' and plan_id ~= ARGV[1] then return {0, ''} end
if redis.call('HGET', KEYS[1], 'held') ~= '1' then return {2, plan_id} end
local started = redis.call('HGET', KEYS[1], 'step_started_ms') or ''
local held_at = tonumber(redis.call('HGET', KEYS[1], 'held_at_ms') or '')
if started ~= '' and held_at then
    local moved = tonumber(started) + (tonumber(ARGV[2]) - held_at)
    redis.call('HSET', KEYS[1], 'step_started_ms', string.format('%.0f', moved))
elseif started == '' then
    redis.call('HSET', KEYS[1], 'due_ms', ARGV[2])
end
redis.call('HSET', KEYS[1], 'held', '', 'held_at_ms', '')
redis.call('SET', KEYS[2], ARGV[3], 'PX', ARGV[4])
return {1, plan_id}
"""


@dataclass(frozen=True)
class SeekOutcome:
    """What a seek did: `moved`, `already_there`, or `refused`, and the step
    the plan was on before it with when that step went out."""

    result: str
    previous_step: Optional[int] = None
    previous_started_ms: Optional[int] = None


@dataclass(frozen=True)
class HoldOutcome:
    """What a hold did, and the step it holds: `held`, `already_held` or
    `refused`. `resend` says the room is to be sent the held step: the next
    line had gone to the room early, or the step itself was never sent."""

    result: str
    plan_id: Optional[str] = None
    step: int = 0
    step_started_ms: str = ""
    resend: bool = False


@dataclass(frozen=True)
class AutoplaySettings:
    tempo: float = 1.0
    lead_ms: int = DEFAULT_LEAD_MS


def _as_int(value: object) -> Optional[int]:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _settings_from(raw: Optional[Dict[str, str]]) -> AutoplaySettings:
    """Settings as stored, each falling back to its default when absent or
    unreadable - a bad value must never stop the room."""
    raw = raw or {}
    try:
        tempo = _clamp(float(raw.get("tempo") or 1.0), MIN_AUTOPLAY_TEMPO, MAX_AUTOPLAY_TEMPO)
    except (TypeError, ValueError):
        tempo = 1.0
    lead = _as_int(raw.get("lead_ms"))
    lead = DEFAULT_LEAD_MS if lead is None else int(_clamp(lead, 0, MAX_AUTOPLAY_LEAD_MS))
    return AutoplaySettings(tempo=tempo, lead_ms=lead)


def effective_duration_ms(recorded_ms: int, tempo: float) -> int:
    """How long a step is held: its recorded time at the room's pace."""
    return int(
        _clamp(round(recorded_ms * tempo), MIN_AUTOPLAY_STEP_MS, MAX_AUTOPLAY_STEP_MS)
    )


def _step_duration_ms(
    state: Dict[str, str], plan: List[dict], step: int, tempo: float
) -> int:
    """How long `step` is held: its recorded time at the room's pace - until
    the next line starts going to the room early. From then the time that send
    was timed against stands: phones already have the next line, and a pace
    raised after it would keep them there long past the lead while the stage
    and the operator wait on this one. A hold still moves the deadline, by
    moving the step's start."""
    following = str(step + 1)
    if following in (state.get("pre_sending"), state.get("pre_sent")):
        fixed = _as_int(state.get("fixed_duration_ms"))
        if fixed is not None:
            return fixed
    return effective_duration_ms(int(plan[step]["duration_ms"]), tempo)


def lead_for(duration_ms: int, lead_ms: int) -> int:
    """How early the step after one held for `duration_ms` goes to the room.
    Never more than half the line, so a short line is still on phones for at
    least half its time rather than being passed over."""
    return max(0, min(lead_ms, duration_ms // 2))


def next_tempo(tempo: float, recorded_ms: int, recited_ms: int) -> float:
    """The room's pace once a line recorded at `recorded_ms` was recited in
    `recited_ms`: moved part of the way towards what that line says."""
    observed = _clamp(
        recited_ms / max(1, recorded_ms), 1 / MAX_TEMPO_OBSERVATION, MAX_TEMPO_OBSERVATION
    )
    moved = tempo + (observed - tempo) * TEMPO_LEARNING_RATE
    return _clamp(moved, MIN_AUTOPLAY_TEMPO, MAX_AUTOPLAY_TEMPO)


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
                    # The step after this one, once it has gone to the room
                    # ahead of its time (see DEFAULT_LEAD_MS), and from just
                    # before it starts going.
                    "pre_sent": "",
                    "pre_sending": "",
                    # How long the step is held once that early line is going.
                    "fixed_duration_ms": "",
                    "held": "",
                    "held_at_ms": "",
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
                4,
                autoplay_state_key(event_id),
                autoplay_lease_key(event_id),
                autoplay_plan_key(event_id),
                autoplay_settings_key(event_id),
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
                4,
                autoplay_lease_key(event_id),
                autoplay_state_key(event_id),
                autoplay_plan_key(event_id),
                autoplay_settings_key(event_id),
                owner,
                str(LEASE_MS),
                str(POSITION_TTL_SECONDS),
            )
        )

    async def release(self, event_id: UUID, owner: str) -> None:
        await self.redis.eval(_RELEASE_SCRIPT, 1, autoplay_lease_key(event_id), owner)

    async def seek(
        self,
        event_id: UUID,
        plan_id: str,
        step: int,
        expected_step: Optional[int],
        owner: str,
    ) -> SeekOutcome:
        outcome, previous, started = await self.redis.eval(
            _SEEK_SCRIPT,
            2,
            autoplay_state_key(event_id),
            autoplay_lease_key(event_id),
            plan_id,
            str(step),
            "" if expected_step is None else str(expected_step),
            owner,
            str(LEASE_MS),
        )
        result = {1: "moved", 2: "already_there"}.get(int(outcome), "refused")
        return SeekOutcome(result, _as_int(previous), _as_int(started))

    async def hold(
        self, event_id: UUID, plan_id: Optional[str], now_ms: int, owner: str
    ) -> HoldOutcome:
        outcome, held_plan, step, started, resend = await self.redis.eval(
            _HOLD_SCRIPT,
            2,
            autoplay_state_key(event_id),
            autoplay_lease_key(event_id),
            plan_id or "",
            str(now_ms),
            owner,
            str(LEASE_MS),
        )
        result = {1: "held", 2: "already_held"}.get(int(outcome), "refused")
        return HoldOutcome(
            result=result,
            plan_id=held_plan or None,
            step=_as_int(step) or 0,
            step_started_ms=started or "",
            resend=bool(int(resend)),
        )

    async def note_early(
        self,
        event_id: UUID,
        owner: str,
        plan_id: str,
        step: int,
        step_started_ms: str,
        sent: bool,
        duration_ms: Optional[int] = None,
    ) -> bool:
        """Note the step after `step` as going (`sent` False) or gone to the
        room early. Refused unless `owner` still runs the plan at `step`,
        unheld. Going, `duration_ms` is how long `step` is held from then on."""
        return bool(
            await self.redis.eval(
                _NOTE_EARLY_SCRIPT,
                2,
                autoplay_state_key(event_id),
                autoplay_lease_key(event_id),
                owner,
                plan_id,
                str(step),
                step_started_ms,
                "sent" if sent else "sending",
                "" if duration_ms is None else str(duration_ms),
            )
        )

    async def clear_early(
        self, event_id: UUID, plan_id: str, step: int, step_started_ms: str
    ) -> bool:
        """Forget the early line once the room is back on `step`."""
        return bool(
            await self.redis.eval(
                _CLEAR_EARLY_SCRIPT,
                1,
                autoplay_state_key(event_id),
                plan_id,
                str(step),
                step_started_ms,
            )
        )

    async def resume(
        self, event_id: UUID, plan_id: Optional[str], now_ms: int, owner: str
    ) -> tuple:
        """(`resumed` | `not_held` | `refused`, the plan it is for)."""
        outcome, resumed_plan = await self.redis.eval(
            _RESUME_SCRIPT,
            2,
            autoplay_state_key(event_id),
            autoplay_lease_key(event_id),
            plan_id or "",
            str(now_ms),
            owner,
            str(LEASE_MS),
        )
        result = {1: "resumed", 2: "not_held"}.get(int(outcome), "refused")
        return result, resumed_plan or None

    async def read_settings(self, event_id: UUID) -> AutoplaySettings:
        raw = await self.redis.hgetall(autoplay_settings_key(event_id))
        return _settings_from(raw)

    async def write_settings(self, event_id: UUID, fields: Dict[str, str]) -> None:
        key = autoplay_settings_key(event_id)
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.hset(key, mapping=fields)
            pipe.expire(key, POSITION_TTL_SECONDS)
            await pipe.execute()

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
    event_id: UUID,
    state: Optional[Dict[str, str]],
    plan: Optional[List[dict]] = None,
    settings: Optional[AutoplaySettings] = None,
) -> AutoplayStateResponse:
    """The state as the controller reads it."""
    now = _now_ms()
    settings = settings or AutoplaySettings()
    if not state:
        return AutoplayStateResponse(
            event_id=event_id,
            status="stopped",
            tempo=settings.tempo,
            lead_ms=settings.lead_ms,
            server_time_ms=now,
        )
    step = int(state.get("step") or 0)
    started = state.get("step_started_ms") or ""
    duration: Optional[int] = None
    if plan is not None and 0 <= step < len(plan):
        duration = _step_duration_ms(state, plan, step, settings.tempo)
    return AutoplayStateResponse(
        event_id=event_id,
        plan_id=state.get("plan_id") or None,
        status=state.get("status") or "stopped",
        reason=state.get("reason") or None,
        step=step,
        total_steps=int(state.get("total") or 0),
        step_started_at_ms=int(started) if started else None,
        step_duration_ms=duration,
        held=state.get("held") == "1",
        held_at_ms=_as_int(state.get("held_at_ms")),
        tempo=settings.tempo,
        lead_ms=settings.lead_ms,
        server_time_ms=now,
    )


class AutoplayCommandRefused(Exception):
    """An operator command found no plan to act on: none running, or not the
    plan it named."""


class AutoplayEngine:
    """This instance's share of autoplay: the runners it holds the lease for."""

    def __init__(
        self,
        store: AutoplayStore,
        emit: Emitter,
        owner: Optional[str] = None,
        clock: Callable[[], int] = _now_ms,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        is_live: Optional[LiveCheck] = None,
    ) -> None:
        self.store = store
        self.emit = emit
        self.owner = owner or str(uuid4())
        self.clock = clock
        self.sleep = sleep
        self.is_live = is_live
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
        # The old runner goes before the new plan is in place. A step already
        # inside its send is not that runner's next line: the publish itself
        # refuses it once this plan is no longer current. If the new plan is
        # not saved, the old one is still the plan: its runner comes back
        # rather than leaving it stalled until the lease lapses.
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
            # A newer plan may have taken the runner while the first step was
            # still sending. Spawning over it would drop that plan's runner.
            await self._spawn_if_current(event_id, plan_id)
            return await self.state(event_id)
        except Exception:
            # Only this plan: another request may already have replaced it,
            # and that one succeeded.
            await self._finish(event_id, plan_id, "failed")
            raise

    async def stop(self, event_id: UUID, reason: str = "stopped") -> AutoplayStateResponse:
        """Stop the plan wherever it runs. Raises if the stop could not be
        recorded: a runner on another instance may then still be sending.

        A pause leaves the room on the line the operator sees. If the next one
        had already gone to the room early, the room is put back first; a
        session that is ending is about to be cleared, so it is not. If the
        room could not be put back, this raises with the plan left held, not
        stopped: a retry holds again, and resends."""
        if reason != "ended":
            try:
                await self._hold_here(event_id, None)
            except Exception as e:
                logger.exception("Could not take back an early line for event %s: %s", event_id, e)
                raise
        # The runner this stop is about. A new plan can start while the stop
        # waits on Redis; its runner is not this stop's to cancel, or the plan
        # stays marked running with nobody advancing it until its lease lapses.
        stopping = self._runners.get(event_id)
        try:
            await self.store.stop(event_id, reason)
        finally:
            if self._runners.get(event_id) is stopping:
                self._forget_runner(event_id)
        state = await self.state(event_id)
        await self._announce(event_id, state)
        return state

    async def state(self, event_id: UUID) -> AutoplayStateResponse:
        state = await self.store.read(event_id)
        plan = await self._plan_for(event_id, state.get("plan_id") if state else None)
        settings = await self.store.read_settings(event_id)
        return _state_response(event_id, state, plan, settings)

    async def seek(
        self,
        event_id: UUID,
        plan_id: str,
        step: int,
        expected_step: Optional[int] = None,
    ) -> AutoplayStateResponse:
        """Move the running plan to `step` and send it to the room now.

        The hand move of a running plan: no new plan is made or sent, so it
        reaches the room in the time one line does. A move to the step after
        `expected_step` is the operator ending that line, and the room's pace
        is learned from how long it actually took. Raises `AutoplayCommandRefused`
        when the plan is not running or is not `plan_id`.
        """
        plan = await self._plan_for(event_id, plan_id)
        if not plan or step >= len(plan):
            raise AutoplayCommandRefused("That plan is not running")
        pressed_at = self.clock()
        outcome = await self.store.seek(event_id, plan_id, step, expected_step, self.owner)
        if outcome.result == "refused":
            raise AutoplayCommandRefused("That plan is not running")
        if outcome.result == "already_there":
            return await self.state(event_id)

        # This instance holds the lease now: whichever runner had it stops at
        # its next write, and the one here gives way to the one spawned below.
        self._forget_runner(event_id)
        try:
            state = await self.store.read(event_id) or {}
            # Not sent is not a failed seek: the plan was replaced or stopped,
            # or a hold took the lease first and sends this line itself
            # (_show_held_step). Either way the state below is the room's.
            await self._send_step(
                event_id,
                plan_id,
                plan,
                step,
                "",
                self.clock(),
                already_sent=state.get("pre_sent") == str(step),
            )
        except Exception:
            await self._finish(event_id, plan_id, "failed")
            raise
        # The room has its line; only now is the pace worked out, so learning
        # it never holds the line back.
        if (
            expected_step is not None
            and step == expected_step + 1
            and outcome.previous_step == expected_step
            and outcome.previous_started_ms is not None
        ):
            await self._learn_pace(
                event_id,
                int(plan[expected_step]["duration_ms"]),
                pressed_at - outcome.previous_started_ms,
            )
        try:
            await self._spawn_if_current(event_id, plan_id)
        except Exception:
            await self._finish(event_id, plan_id, "failed")
            raise
        return await self.state(event_id)

    async def hold(self, event_id: UUID, plan_id: Optional[str] = None) -> AutoplayStateResponse:
        """Keep the room on its line until `resume`: the line is still being
        recited, past its recorded time."""
        outcome = await self._hold_here(event_id, plan_id)
        if outcome.result == "refused":
            raise AutoplayCommandRefused("No plan is running")
        state = await self.state(event_id)
        await self._announce(event_id, state)
        return state

    async def resume(self, event_id: UUID, plan_id: Optional[str] = None) -> AutoplayStateResponse:
        """Let a held plan go on, the line keeping what was left of its time."""
        result, resumed_plan = await self.store.resume(
            event_id, plan_id, self.clock(), self.owner
        )
        if result == "refused":
            raise AutoplayCommandRefused("No plan is running")
        if result == "resumed" and resumed_plan:
            self._forget_runner(event_id)
            await self._spawn_if_current(event_id, resumed_plan)
        state = await self.state(event_id)
        await self._announce(event_id, state)
        return state

    async def update_settings(
        self,
        event_id: UUID,
        lead_ms: Optional[int] = None,
        tempo: Optional[float] = None,
    ) -> AutoplayStateResponse:
        """Set the lead, or set the pace outright (1.0 resets it). The runner
        reads them on every tick, so a running plan takes them up at once."""
        fields: Dict[str, str] = {}
        if lead_ms is not None:
            fields["lead_ms"] = str(int(_clamp(lead_ms, 0, MAX_AUTOPLAY_LEAD_MS)))
        if tempo is not None:
            fields["tempo"] = f"{_clamp(tempo, MIN_AUTOPLAY_TEMPO, MAX_AUTOPLAY_TEMPO):.4f}"
        if fields:
            await self.store.write_settings(event_id, fields)
        state = await self.state(event_id)
        await self._announce(event_id, state)
        return state

    async def _hold_here(self, event_id: UUID, plan_id: Optional[str]) -> HoldOutcome:
        """Hold the plan with this instance as its runner, and put the room
        back on the held line if the next one had already gone out early."""
        outcome = await self.store.hold(event_id, plan_id, self.clock(), self.owner)
        if outcome.result == "refused" or not outcome.plan_id:
            return outcome
        if outcome.result == "already_held" and not outcome.resend:
            return outcome
        # Held now, or held before with a send that never landed: either way
        # this instance has the lease.
        self._forget_runner(event_id)
        if outcome.resend:
            await self._show_held_step(event_id, outcome)
        await self._spawn_if_current(event_id, outcome.plan_id)
        return outcome

    async def _show_held_step(self, event_id: UUID, outcome: HoldOutcome) -> None:
        """Put the room on the step the plan is held on, when it is not.

        Either the next line went out early, and the room is put back. Or the
        plan had moved on to this step and not yet sent it - a seek, or the
        runner moving on - when the hold took the lease from under that send,
        which is then refused. Then the step is sent here, held from now:
        otherwise the room stays on the line before while the stage and the
        operator are on this one, until the plan is resumed.

        A send that fails raises, leaving the step unmarked: the next hold is
        told to send it again (_HOLD_SCRIPT).
        """
        plan = await self._plan_for(event_id, outcome.plan_id)
        if not plan or not 0 <= outcome.step < len(plan):
            return
        if not outcome.step_started_ms:
            state = await self.store.read(event_id) or {}
            # False: another command took the plan or the lease while this was
            # sending - a seek, a stop, or a later hold that sends it itself.
            await self._send_step(
                event_id,
                outcome.plan_id,
                plan,
                outcome.step,
                "",
                self.clock(),
                already_sent=state.get("pre_sent") == str(outcome.step),
            )
            return
        emitted = await self._emit_step(
            event_id,
            plan,
            outcome.step,
            AutoplayGuard(
                owner=self.owner,
                plan_id=outcome.plan_id,
                step=outcome.step,
                step_started_ms=outcome.step_started_ms,
            ),
        )
        # False: the plan moved on while this was sending, and the room is
        # wherever that move put it.
        if emitted is not False:
            await self.store.clear_early(
                event_id, outcome.plan_id, outcome.step, outcome.step_started_ms
            )

    async def _learn_pace(self, event_id: UUID, recorded_ms: int, recited_ms: int) -> None:
        """Fold one line's actual time into the room's pace. Never worth failing
        a move over."""
        if recited_ms < MIN_AUTOPLAY_STEP_MS:
            # A double press, not a line recited.
            return
        try:
            settings = await self.store.read_settings(event_id)
            tempo = next_tempo(settings.tempo, recorded_ms, recited_ms)
            await self.store.write_settings(event_id, {"tempo": f"{tempo:.4f}"})
        except Exception as e:
            logger.exception("Failed to learn the room's pace for event %s: %s", event_id, e)

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

    async def _spawn_if_current(self, event_id: UUID, plan_id: str) -> None:
        """Start this plan's runner unless a newer one is already running here."""
        if self._running_here(event_id):
            return
        state = await self.store.read(event_id)
        if self._running_here(event_id):
            return
        if not state or state.get("plan_id") != plan_id or state.get("status") != "running":
            return
        self._spawn(event_id, plan_id)

    async def _still_live(self, event_id: UUID) -> bool:
        """True when no check was given, or the event is still there.

        A deleted event would otherwise be recited through to the end of the
        plan: the runner only looks at the plan it saved, and that plan does
        not know the event is gone.
        """
        if self.is_live is None:
            return True
        return await self.is_live(event_id)

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
            # Woken at least three times a lease, so it is renewed long before
            # it could lapse under a runner that is still here.
            tick = min(TICK_SECONDS, LEASE_MS / 3000)

            if state.get("held") == "1":
                # The operator has the room on this line until they resume.
                await self.sleep(tick)
                if not await self.store.renew(event_id, self.owner):
                    return
                continue

            if not started:
                # Moved on to, but not sent yet: this runner advanced to it, or
                # took over from one that stopped in between. A deleted event
                # stops here, before another line goes out.
                if not await self._still_live(event_id):
                    await self._finish(event_id, plan_id, "ended", owner=self.owner)
                    return
                due = state.get("due_ms") or ""
                start_at = int(due) if due else self.clock()
                if not await self._send_step(
                    event_id,
                    plan_id,
                    plan,
                    step,
                    "",
                    start_at,
                    already_sent=state.get("pre_sent") == str(step),
                ):
                    return
                continue

            settings = await self.store.read_settings(event_id)
            duration = _step_duration_ms(state, plan, step, settings.tempo)
            deadline = int(started) + duration
            following = step + 1
            # Phones show a line the moment it lands, so the next one is sent
            # ahead of its time to land with the stage. The stage, and the
            # operator, still move on at the deadline itself.
            lead = lead_for(duration, settings.lead_ms) if following < len(plan) else 0
            pending_early = lead > 0 and state.get("pre_sent") != str(following)
            now = self.clock()
            if pending_early and deadline - lead <= now < deadline:
                if not await self._send_early(event_id, plan_id, plan, step, started, duration):
                    return
                continue
            if now < deadline:
                wake = deadline - now
                if pending_early:
                    wake = min(wake, deadline - lead - now)
                await self.sleep(min(tick, max(0, wake) / 1000))
                if not await self.store.renew(event_id, self.owner):
                    return
                continue

            if not await self._still_live(event_id):
                await self._finish(event_id, plan_id, "ended", owner=self.owner)
                return
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
        already_sent: bool = False,
    ) -> bool:
        """Send one step to the room and mark it sent.

        Sent first, marked after: an instance that dies in between leaves the
        step unmarked, and whoever takes over sends it again - the room shown
        the same line twice, never a line skipped. Just before sending, the
        runner checks it still holds the lease and its plan is still at this
        step, unsent. That check does not cover the send itself, which is its
        own await: the permit goes with the positions, and the publish lands
        only while the same plan is still current. A send that lost its plan
        on the way reports False and is not marked sent.

        `already_sent` is a step that went to the room ahead of its time: it
        is only marked, which is what moves the operator and the stage on.
        """
        if not await self.store.may_send(
            event_id, self.owner, plan_id, step, expected_started
        ):
            return False
        if not already_sent:
            emitted = await self._emit_step(
                event_id,
                plan,
                step,
                AutoplayGuard(
                    owner=self.owner,
                    plan_id=plan_id,
                    step=step,
                    step_started_ms=expected_started,
                ),
            )
            if emitted is False:
                return False
        marked = await self.store.advance(
            event_id,
            self.owner,
            plan_id,
            step,
            expected_started,
            {"step_started_ms": str(start_at), "due_ms": "", "pre_sent": "", "pre_sending": ""},
        )
        if marked:
            await self._announce(event_id, await self.state(event_id))
        return marked

    async def _send_early(
        self,
        event_id: UUID,
        plan_id: str,
        plan: List[dict],
        step: int,
        started: str,
        duration_ms: int,
    ) -> bool:
        """Send the step after `step` to the room ahead of its time, and note
        it went, so it is not sent again when its time comes. Sent under the
        current step's permit: the plan must still be on that step, as it was
        when the send was decided.

        Noted as going before it is sent and as gone after, so a hold landing
        anywhere in between sees it and puts the room back, and one landing
        first stops it going at all. Going, `step` keeps `duration_ms`, the
        time this send was timed against, whatever the pace does next."""
        if not await self.store.may_send(event_id, self.owner, plan_id, step, started):
            return False
        if not await self.store.note_early(
            event_id, self.owner, plan_id, step, started, sent=False, duration_ms=duration_ms
        ):
            return False
        following = step + 1
        emitted = await self._emit_step(
            event_id,
            plan,
            following,
            AutoplayGuard(
                owner=self.owner,
                plan_id=plan_id,
                step=step,
                step_started_ms=started,
                early=True,
            ),
        )
        if emitted is False:
            return False
        return await self.store.note_early(
            event_id, self.owner, plan_id, step, started, sent=True
        )

    async def _emit_step(
        self, event_id: UUID, plan: List[dict], step: int, guard: AutoplayGuard
    ) -> Optional[bool]:
        """Send `step`'s positions to the room, only while `guard` holds."""
        positions = [SetPositionFrame.model_validate(p) for p in plan[step]["positions"]]
        token = _send_permit.set(guard)
        try:
            return await self.emit(event_id, positions)
        finally:
            _send_permit.reset(token)

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


async def _event_is_live(event_id: UUID) -> bool:
    """False only when the event is gone.

    A database hiccup is not a deletion: stopping the room over one would end
    a puja that is still on.
    """
    from fastapi import HTTPException
    from starlette.concurrency import run_in_threadpool

    from pecha_api.events.recitation_live_service import assert_live_event

    try:
        await run_in_threadpool(assert_live_event, event_id=event_id)
    except HTTPException as error:
        if error.status_code == 404:
            return False
        logger.exception("Could not confirm event %s is still live: %s", event_id, error)
        return True
    except Exception as error:
        logger.exception("Could not confirm event %s is still live: %s", event_id, error)
        return True
    return True


async def init_autoplay(redis: object, emit: Emitter) -> AutoplayEngine:
    global engine
    engine = AutoplayEngine(AutoplayStore(redis), emit, is_live=_event_is_live)
    engine.start_supervisor()
    return engine


async def shutdown_autoplay() -> None:
    global engine
    if engine is not None:
        await engine.shutdown()
        engine = None
