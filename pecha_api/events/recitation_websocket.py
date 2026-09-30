import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, List, Optional, Set
from uuid import UUID, uuid4

from redis.asyncio import Redis

from pecha_api.realtime.channel_fanout import ChannelFanout, Subscriber

logger = logging.getLogger(__name__)

# A puja runs for hours; the snapshot only has to outlive the session itself.
POSITION_TTL_SECONDS = 12 * 60 * 60

# Per-event publish ceiling. An operator clicks a handful of times a minute, so
# anything near this is a stuck key or a rogue client, not a fast reader.
#
# Kept low because every accepted frame costs one WebSocket send per subscriber
# on every instance: with a thousand phones in a room, 50/s would be 50,000
# sends a second on a single event loop. The ceiling is the blast radius of a
# stuck client, not a rate anyone recites at.
MAX_SETS_PER_SECOND = 5
RATE_WINDOW_SECONDS = 1


def position_channel(event_id: UUID) -> str:
    return f"recitation:event:{event_id}:position"


def position_state_key(event_id: UUID) -> str:
    return f"recitation:event:{event_id}:state"


def position_revision_key(event_id: UUID) -> str:
    return f"recitation:event:{event_id}:rev"


def position_rate_key(event_id: UUID) -> str:
    return f"recitation:event:{event_id}:rate"


def presence_key(event_id: UUID) -> str:
    return f"recitation:event:{event_id}:presence"


def segment_mark_key(event_id: UUID) -> str:
    """Per text, the line the room last landed on and when - what a segment's
    play time is measured from once the next line arrives."""
    return f"recitation:event:{event_id}:marks"


def autoplay_state_key(event_id: UUID) -> str:
    """Where autoplay is: its plan, status, step and when the step went out."""
    return f"recitation:event:{event_id}:autoplay"


def autoplay_plan_key(event_id: UUID) -> str:
    """The steps autoplay is running, as the controller laid them out."""
    return f"recitation:event:{event_id}:autoplay-plan"


def autoplay_lease_key(event_id: UUID) -> str:
    """The instance running this event's autoplay. Exactly one does, and another
    takes over once the lease lapses - a deploy or a crash does not end it."""
    return f"recitation:event:{event_id}:autoplay-lease"


def autoplay_channel(event_id: UUID) -> str:
    """Autoplay's state as it changes, for the operator's socket only. Kept off
    the position channel so the room's phones only ever see positions."""
    return f"recitation:event:{event_id}:autoplay-state"


def segment_boundary_key(event_id: UUID) -> str:
    """The revision a session ended on. Marks at or below it belong to that
    session, so nothing is measured across the gap between two pujas."""
    return f"recitation:event:{event_id}:mark-boundary"


# Shared with the presence script, which rebuilds lease keys itself from the
# instance id stamped on each roster entry.
INSTANCE_LEASE_PREFIX = "recitation:instance:"


def instance_lease_key(instance_id: str) -> str:
    return f"{INSTANCE_LEASE_PREFIX}{instance_id}"


def presence_field(user_id: UUID, token: str) -> str:
    """One roster field per socket, not per person.

    A field per person cannot survive the same person holding two sockets: the
    second join overwrites the first, and whichever socket closes first takes
    the other's entry with it. The count is still per person - the script
    behind `presence_count` folds a person's sockets back into one - but the
    bookkeeping is per socket, so closing one leaves the others standing.
    """
    return f"{user_id}|{token}"


# One id per process, stored as each roster entry's value, so a crashed
# instance's joins drop out of the count once its lease expires instead of
# sitting there until someone deletes the hash.
_INSTANCE_ID = str(uuid4())
# The heartbeat runs well inside the lease, so one stalled loop does not look
# like a crash and zero the room.
INSTANCE_LEASE_SECONDS = 45
INSTANCE_HEARTBEAT_SECONDS = 20


# Counting the room has to be one step with pruning the entries it decided were
# dead, and - for the broadcast - with publishing the number it arrived at.
#
# Split across round trips, both halves go wrong. The prune deletes by a value
# it read earlier, so a socket that reconnected in between loses its brand new
# entry and stops being counted. And two joins racing each other can read 1 and
# 2, then publish in the other order, leaving every phone in the room showing
# the older number until somebody else joins or leaves. Redis runs a script
# start to finish with nothing in between, so neither gap exists.
#
# Fields are "{user id}|{socket token}" and values are the instance holding the
# socket. Sockets are what expire; people are what get counted, so the fold
# back to one entry per person happens here.
_PRESENCE_COUNT_BODY = """
local roster = redis.call('HGETALL', KEYS[1])
local lease_prefix = ARGV[1]
local alive = {}
local people = {}
local stale = {}
for i = 1, #roster, 2 do
    local field = roster[i]
    local instance = roster[i + 1]
    local live = alive[instance]
    if live == nil then
        live = redis.call('EXISTS', lease_prefix .. instance) == 1
        alive[instance] = live
    end
    if live then
        people[string.match(field, '^(.*)|[^|]*$') or field] = true
    else
        stale[#stale + 1] = field
    end
end
local cursor = 1
while cursor <= #stale do
    local last = math.min(cursor + 199, #stale)
    redis.call('HDEL', KEYS[1], unpack(stale, cursor, last))
    cursor = last + 1
end
local count = 0
for _ in pairs(people) do
    count = count + 1
end
"""

_PRESENCE_COUNT_SCRIPT = _PRESENCE_COUNT_BODY + """
return count
"""

# ARGV[2] is the event id, interpolated into the frame here rather than passed
# as a finished payload, because the count is only known once the script runs.
_PRESENCE_BROADCAST_SCRIPT = _PRESENCE_COUNT_BODY + """
redis.call('PUBLISH', KEYS[2],
    '{"type":"presence","event_id":"' .. ARGV[2] .. '","count":' .. count .. '}')
return count
"""


# Matches every key position_rate_key can produce, for the startup sweep.
_RATE_KEY_PATTERN = "recitation:event:*:rate"
# Deleted in chunks so a long-lived keyspace does not arrive as one huge DEL.
_RATE_KEY_DELETE_BATCH = 500


# Allocating the revision and writing the snapshot have to be one step. As two
# round trips they interleave: with two operators publishing at once, the lower
# revision's write can land last and leave the snapshot holding an older
# position than the counter claims, so the next viewer to connect starts behind
# the room and stays there until the next click. Redis runs a script
# atomically, so nothing can come between the INCR and the HSET.
_SAVE_POSITION_SCRIPT = """
local revision = redis.call('INCR', KEYS[2])
redis.call('HSET', KEYS[1],
    'text_id', ARGV[1],
    'segment_id', ARGV[2],
    'index', ARGV[3],
    'round_number', ARGV[4],
    'updated_at', ARGV[5],
    'revision', revision)
redis.call('EXPIRE', KEYS[1], ARGV[6])
redis.call('EXPIRE', KEYS[2], ARGV[6])
return revision
"""

# Swaps a text's mark for the newer one and hands back the old, in one step.
# Marks are `<revision>|<accepted at ms>|<autoplay 0/1>|<run>|<line>` and lead
# with the revision they were accepted under, so a mark that arrives late -
# background work is not ordered - never overwrites a newer one and is never
# measured against it.
#
# The same line sent twice in the same run - the controller re-sends the
# edition on screen behind its followers - keeps the first mark: the line
# started when the room first reached it, not when it was repeated. The same
# line under a new run is the room coming back to the text, and starts afresh.
#
# Whether the text stayed with the room between two marks is not judged here:
# the run each mark carries says so, and the caller compares them.
#
# The session boundary is a revision, not a deletion, because ending a session
# and writing a mark are both background work and cannot be ordered against
# each other. A mark from the session that just ended is at or below it and is
# neither written nor measured; the next session's marks are above it and a
# late-running end can no longer erase them.
_SWAP_SEGMENT_MARK_SCRIPT = """
local revision = tonumber(ARGV[2])
local boundary = tonumber(redis.call('GET', KEYS[2]) or '0')
if revision <= boundary then
    return false
end
local previous = redis.call('HGET', KEYS[1], ARGV[1])
if previous then
    local stored_revision, stored_run, stored_line = string.match(previous, '^(%d+)|%d+|%d|([^|]*)|(.*)$')
    stored_revision = tonumber(stored_revision)
    if stored_revision and stored_revision >= revision then
        return false
    end
    if stored_line == ARGV[5] and stored_run == ARGV[6] then
        return false
    end
    if not stored_revision or stored_revision <= boundary then
        previous = false
    end
end
redis.call('HSET', KEYS[1], ARGV[1], ARGV[3])
redis.call('EXPIRE', KEYS[1], ARGV[4])
return previous
"""

# Taking the boundary from the shared counter is what makes it a boundary: the
# revision is handed out by the same INCR every position uses, so no position
# can ever land on it, and every position still to come is above it.
_END_SEGMENT_MARKS_SCRIPT = """
local revision = redis.call('INCR', KEYS[1])
redis.call('SET', KEYS[2], revision, 'EX', ARGV[1])
return revision
"""

# Counting the window and stamping its expiry have to be one step. As two round
# trips the EXPIRE can be lost - a connection blip, a restart, a client-side
# retry of an INCR that already landed - and the key is then immortal: the
# counter only ever sees 1 once, so nothing reapplies the TTL and every later
# request for that event is refused forever. The TTL branch heals a key already
# stuck that way instead of waiting for someone to delete it by hand.
_ALLOW_SET_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
elseif redis.call('TTL', KEYS[1]) < 0 then
    redis.call('SET', KEYS[1], 1, 'EX', ARGV[1])
    count = 1
end
return count
"""


class RecitationBroadcaster:
    """Manages WebSocket connections and Redis pub/sub for live recitation
    position, plus the current-position snapshot each new subscriber is sent.

    Unlike chat, which is a stream of events, a recitation has exactly one
    interesting value: which text the operator is in, and where. That value is
    mirrored into a Redis hash on every set, so a phone joining 40 minutes in -
    or an instance restarted by a deploy - lands on the live line instead of
    waiting for the operator's next click.

    Who is in the room is the other shared value. Each join is a field in a
    Redis hash, stamped with this process, so a count taken on any instance is
    the whole room and not just the sockets that process happens to hold.
    """

    def __init__(self, redis_url: str) -> None:
        self.redis_url = redis_url
        self.redis: Optional[Redis] = None
        # One Redis subscription per event, shared by every socket watching
        # it on this instance.
        self.fanout: Optional[ChannelFanout] = None
        # Track local WebSocket connections: {event_id: {user_id: websocket}}
        self.connections: Dict[UUID, Dict[UUID, object]] = {}
        # Roster fields this process owns: {event_id: {presence field}}. One per
        # live socket, reasserted by the heartbeat so a lapsed lease cannot
        # retire a socket that is still sitting there.
        self._roster: Dict[UUID, Set[str]] = {}
        # Held across a field's local removal and its Redis delete, and across
        # the heartbeat's snapshot and rewrite of an event's fields, so the two
        # cannot overlap. See `_reassert_presence` for what that would cost.
        # One lock per event, so a slow Redis write for one room never holds up
        # a close in another; refcounted so idle events do not leak a lock.
        self._roster_locks: Dict[UUID, asyncio.Lock] = {}
        self._roster_lock_refs: Dict[UUID, int] = {}
        self._heartbeat_task: Optional[asyncio.Task] = None

    async def connect(self) -> None:
        """Initialize Redis connection."""
        try:
            self.redis = await Redis.from_url(
                self.redis_url, decode_responses=True, socket_keepalive=True
            )
            # A position is last-write-wins, so a socket that falls behind
            # wants the newest frame, not a backlog of stale ones.
            self.fanout = ChannelFanout(self.redis, queue_maxsize=64, drop_oldest=True)
            # Claim the lease before serving, so the first join is already
            # countable. A failure here is logged, not fatal: the puja still
            # runs, and the heartbeat retries.
            try:
                await self.refresh_instance_lease()
            except Exception as lease_error:
                logger.exception(
                    "Failed to claim recitation instance lease: %s", lease_error
                )
            self._heartbeat_task = asyncio.create_task(self._run_instance_heartbeat())
            logger.info("✅ Redis connection established for recitation broadcaster")
        except ConnectionRefusedError as e:
            error_msg = (
                f"❌ Redis connection refused at {self.redis_url}\n"
                f"   Make sure Redis/Dragonfly is running on the configured host:port"
            )
            logger.error(error_msg)
            raise ConnectionError(error_msg) from e
        except TimeoutError as e:
            error_msg = (
                f"❌ Redis connection timeout at {self.redis_url}\n"
                f"   Redis may be unresponsive or the server is unreachable"
            )
            logger.error(error_msg)
            raise TimeoutError(error_msg) from e
        except Exception as e:
            error_msg = (
                f"❌ Failed to connect to Redis: {type(e).__name__}\n"
                f"   URL: {self.redis_url}\n"
                f"   Error: {str(e)}"
            )
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e

    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self._heartbeat_task is not None:
            task = self._heartbeat_task
            self._heartbeat_task = None
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if self.fanout:
            await self.fanout.aclose()
        if self.redis:
            await self.redis.close()
            logger.info("Redis connection closed for recitation broadcaster")

    def add_connection(self, event_id: UUID, user_id: UUID, ws: object) -> None:
        """Track a local WebSocket connection.

        The fleet-wide roster lives in Redis (`mark_present`); this dict is
        only the sockets this process is holding.
        """
        if event_id not in self.connections:
            self.connections[event_id] = {}
        self.connections[event_id][user_id] = ws

    def remove_connection(self, event_id: UUID, user_id: UUID) -> None:
        """Drop a local WebSocket connection."""
        if event_id in self.connections:
            self.connections[event_id].pop(user_id, None)
            if not self.connections[event_id]:
                del self.connections[event_id]

    async def subscribe_to_event(self, event_id: UUID) -> Subscriber:
        """Attach to the position stream for an event.

        Shares the instance's single subscription for this event, so a
        thousand phones in the room cost one Redis connection, not a
        thousand. Release it with `unsubscribe_from_event`.
        """
        return await self.fanout.subscribe(position_channel(event_id))

    async def unsubscribe_from_event(self, event_id: UUID, subscriber: Subscriber) -> None:
        """Detach a socket; the last one out closes the Redis subscription."""
        await self.fanout.unsubscribe(position_channel(event_id), subscriber)

    async def subscribe_to_autoplay(self, event_id: UUID) -> Subscriber:
        """Attach the operator's socket to autoplay's state as it changes."""
        return await self.fanout.subscribe(autoplay_channel(event_id))

    async def unsubscribe_from_autoplay(self, event_id: UUID, subscriber: Subscriber) -> None:
        await self.fanout.unsubscribe(autoplay_channel(event_id), subscriber)

    async def save_position(
        self,
        event_id: UUID,
        text_id: str,
        segment_id: str,
        index: Optional[int],
        round_number: Optional[int],
        server_time: str,
    ) -> Optional[int]:
        """Take the next revision and mirror the position into Redis, atomically.

        Returns the revision the position was stored under, or None when Redis
        could not be written: the caller still broadcasts, and an unnumbered
        frame is relayed rather than dropped, so a snapshot failure costs
        resync-on-connect but never the live position.

        Ordering cannot come from `server_time` - that is stamped by whichever
        instance served the operator's socket, and two instances' clocks need
        not agree. The counter in the shared store is the only value every
        instance agrees on.
        """
        try:
            revision = await self.redis.eval(
                _SAVE_POSITION_SCRIPT,
                2,
                position_state_key(event_id),
                position_revision_key(event_id),
                text_id,
                segment_id,
                "" if index is None else str(index),
                "" if round_number is None else str(round_number),
                server_time,
                str(POSITION_TTL_SECONDS),
            )
            return int(revision)
        except Exception as e:
            logger.exception("Failed to save recitation position to Redis: %s", e)
            return None

    async def get_position(self, event_id: UUID) -> Optional[dict]:
        """The current position for an event, or None when nothing has been set
        (or the snapshot has expired)."""
        try:
            state = await self.redis.hgetall(position_state_key(event_id))
        except Exception as e:
            logger.exception("Failed to read recitation position from Redis: %s", e)
            return None

        if not state or not state.get("segment_id"):
            return None

        def _as_int(value: Optional[str]) -> Optional[int]:
            if value is None or value == "":
                return None
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        return {
            "type": "position",
            "event_id": str(event_id),
            "text_id": state.get("text_id") or None,
            "segment_id": state["segment_id"],
            "index": _as_int(state.get("index")),
            "round_number": _as_int(state.get("round_number")),
            "server_time": state.get("updated_at"),
            "revision": _as_int(state.get("revision")),
        }

    async def clear_position(self, event_id: UUID) -> bool:
        """Forget the position when the operator ends the session, so the next
        puja on the same event does not start mid-liturgy.

        Returns whether the snapshot was actually cleared, so a caller that can
        report failure - and retry - is not told the session ended when a stale
        position is still sitting in Redis waiting to greet the next joiner.

        The revision counter is deliberately left alone: it must keep rising
        across sessions, or a reconnecting client holding the old high-water
        mark would discard the new session's opening frames.
        """
        try:
            await self.redis.delete(position_state_key(event_id))
            return True
        except Exception as e:
            logger.exception("Failed to clear recitation position in Redis: %s", e)
            return False

    async def broadcast_position(
        self,
        event_id: UUID,
        text_id: str,
        segment_id: str,
        index: Optional[int],
        round_number: Optional[int],
        server_time: str,
    ) -> Optional[int]:
        """Snapshot under a fresh revision, then publish via Redis pub/sub.

        Returns the revision the position was stored under (None when the
        snapshot could not be written), so an HTTP caller can be told where its
        click landed in the ordering.
        """
        revision = await self.save_position(
            event_id=event_id,
            text_id=text_id,
            segment_id=segment_id,
            index=index,
            round_number=round_number,
            server_time=server_time,
        )

        payload = {
            "type": "position",
            "event_id": str(event_id),
            "text_id": text_id,
            "segment_id": segment_id,
            "index": index,
            "round_number": round_number,
            "server_time": server_time,
            "revision": revision,
        }

        try:
            await self.redis.publish(position_channel(event_id), json.dumps(payload))
        except Exception as e:
            logger.exception("Failed to broadcast recitation position to Redis: %s", e)
            raise

        return revision

    async def swap_segment_mark(
        self,
        event_id: UUID,
        text_id: str,
        mark: str,
        revision: int,
        line: str,
        run: Optional[str] = None,
    ) -> Optional[str]:
        """Record `mark` as where `text_id` now stands and return the mark it
        replaced.

        `mark` is `"<revision>|<accepted at ms>|<autoplay 0/1>|<run>|<line>"`,
        where `line` names the line itself. None when there was nothing before
        it, when a newer mark is already stored, when the same line is already
        marked under the same `run`, when the mark or the one before it belongs to a session that has
        ended, or when Redis could not be reached - in every case there is nothing to measure, and
        play times are never worth failing over.
        """
        try:
            previous = await self.redis.eval(
                _SWAP_SEGMENT_MARK_SCRIPT,
                2,
                segment_mark_key(event_id),
                segment_boundary_key(event_id),
                text_id,
                str(revision),
                mark,
                str(POSITION_TTL_SECONDS),
                line,
                run or "",
            )
        except Exception as e:
            logger.exception("Failed to swap recitation segment mark in Redis: %s", e)
            return None
        return previous or None

    async def close_segment_marks(self, event_id: UUID) -> None:
        """Close the session's marks so the gap before the next session is not
        taken for a line that took hours to recite.

        The marks are not deleted. This runs as background work alongside the
        mark writes it has to shut out, and the two cannot be ordered: a delete
        that ran late would take the next session's first mark with it, and one
        that ran early would leave the mark it came to remove. Recording the
        revision the session ended on settles both, whenever it lands.
        """
        try:
            await self.redis.eval(
                _END_SEGMENT_MARKS_SCRIPT,
                2,
                position_revision_key(event_id),
                segment_boundary_key(event_id),
                str(POSITION_TTL_SECONDS),
            )
        except Exception as e:
            logger.exception("Failed to close recitation segment marks in Redis: %s", e)

    async def broadcast_session_ended(self, event_id: UUID) -> bool:
        """Tell every server holding a socket for this event that the operator
        closed the puja, so clients stop auto-scrolling and release.

        Returns whether the notice was published. A silent failure here leaves
        the room following a puja that is over, which the caller should be able
        to see and retry.
        """
        payload = {"type": "session_ended", "event_id": str(event_id)}
        try:
            await self.redis.publish(position_channel(event_id), json.dumps(payload))
            return True
        except Exception as e:
            logger.exception("Failed to broadcast recitation session end to Redis: %s", e)
            return False

    async def allow_set(self, event_id: UUID) -> bool:
        """Fleet-wide throttle for operator publishes: at most
        MAX_SETS_PER_SECOND per event, counted in a one-second Redis window.

        Runs as a script so the count and its window can never come apart; see
        _ALLOW_SET_SCRIPT for what splitting them costs.

        Fails open - if Redis cannot answer, the puja keeps running rather than
        going silent over a rate counter.
        """
        try:
            count = await self.redis.eval(
                _ALLOW_SET_SCRIPT,
                1,
                position_rate_key(event_id),
                str(RATE_WINDOW_SECONDS),
            )
            return int(count) <= MAX_SETS_PER_SECOND
        except Exception as e:
            logger.exception("Failed to check recitation rate limit in Redis: %s", e)
            return True

    async def clear_rate_keys(self) -> int:
        """Drop every per-event throttle counter. Returns how many went.

        Run at startup, so a redeploy always begins on clean windows. The
        script behind allow_set already re-arms a key that lost its TTL, so
        this is a backstop rather than the cure - but it is also the only thing
        that collects counters belonging to events that have since ended.

        SCAN, never KEYS: the pattern is walked incrementally instead of
        blocking the server for the length of the keyspace. A rolling deploy
        can land here mid-puja, which at worst lets one extra window through
        for a live event - cheaper than leaving a counter nobody can reset.

        Swallows its own failures: a missed sweep costs nothing now that the
        counters heal themselves, and it must never be the reason an instance
        refuses to start.
        """
        if self.redis is None:
            return 0

        deleted = 0
        batch: List[str] = []
        try:
            async for key in self.redis.scan_iter(match=_RATE_KEY_PATTERN, count=100):
                batch.append(key)
                if len(batch) >= _RATE_KEY_DELETE_BATCH:
                    deleted += await self.redis.delete(*batch)
                    batch = []
            if batch:
                deleted += await self.redis.delete(*batch)
        except Exception as e:
            logger.exception("Failed to clear recitation rate keys in Redis: %s", e)
            return deleted

        if deleted:
            logger.info("Cleared %d stale recitation rate key(s) on startup", deleted)
        return deleted

    def get_connected_users(self, event_id: UUID) -> Dict[UUID, object]:
        """Sockets this server holds for an event.

        The number of people in the room is `presence_count`: it reads the
        Redis roster, which every instance writes, and skips joins whose
        server lease has expired.
        """
        return self.connections.get(event_id, {})

    async def refresh_instance_lease(self) -> None:
        """Keep this process visible to the presence count."""
        await self.redis.set(
            instance_lease_key(_INSTANCE_ID), "1", ex=INSTANCE_LEASE_SECONDS
        )

    async def _run_instance_heartbeat(self) -> None:
        while True:
            await asyncio.sleep(INSTANCE_HEARTBEAT_SECONDS)
            try:
                # Lease first, roster second. The other order leaves the
                # rewritten entries pointing at an instance that is still
                # expired, and a count landing between the two prunes them
                # again.
                await self.refresh_instance_lease()
            except Exception as e:
                logger.exception("Failed to refresh recitation instance lease: %s", e)
                continue
            await self._reassert_presence()

    @asynccontextmanager
    async def _roster_lock(self, event_id: UUID) -> AsyncIterator[None]:
        """Hold this event's roster lock."""
        lock = self._roster_locks.get(event_id)
        if lock is None:
            lock = self._roster_locks[event_id] = asyncio.Lock()
        self._roster_lock_refs[event_id] = self._roster_lock_refs.get(event_id, 0) + 1
        try:
            async with lock:
                yield
        finally:
            remaining = self._roster_lock_refs[event_id] - 1
            if remaining:
                self._roster_lock_refs[event_id] = remaining
            else:
                self._roster_lock_refs.pop(event_id, None)
                self._roster_locks.pop(event_id, None)

    async def mark_present(self, event_id: UUID, user_id: UUID) -> str:
        """Record this socket in the shared roster. Returns the token that
        `mark_absent` must hand back, so one socket cannot erase another's entry.

        The field is remembered locally too, because the heartbeat reasserts it:
        a count taken while this instance's lease had lapsed would prune the
        entry even though the socket never went anywhere.
        """
        token = str(uuid4())
        field = presence_field(user_id, token)
        self._roster.setdefault(event_id, set()).add(field)
        try:
            await self.redis.hset(presence_key(event_id), field, _INSTANCE_ID)
        except Exception as e:
            # Left in `_roster` on purpose: the next heartbeat writes it again.
            logger.exception("Failed to mark recitation presence in Redis: %s", e)
        return token

    async def mark_absent(self, event_id: UUID, user_id: UUID, token: str) -> None:
        """Drop this socket's roster entry.

        The field names the socket, not the person, so this can only ever remove
        the entry this socket wrote - never one belonging to another of the same
        person's sockets, and never one a reconnect has since written.
        """
        field = presence_field(user_id, token)
        async with self._roster_lock(event_id):
            fields = self._roster.get(event_id)
            if fields is not None:
                # Forgotten before the delete, so a failed delete is not undone
                # by the heartbeat putting it straight back.
                fields.discard(field)
                if not fields:
                    self._roster.pop(event_id, None)
            try:
                await self.redis.hdel(presence_key(event_id), field)
            except Exception as e:
                logger.exception("Failed to clear recitation presence in Redis: %s", e)

    async def _reassert_presence(self) -> None:
        """Rewrite every roster entry this instance is holding sockets for.

        A lease can lapse while the sockets under it are perfectly healthy - a
        Redis blip, an event loop stalled past the lease - and the next count
        prunes their entries as if the process had died. Reclaiming the lease
        does not bring them back, so the room would read low until every one of
        those people reconnected. Writing them again on each heartbeat makes
        that window one heartbeat wide instead of the rest of the session.

        Reading the fields and writing them back is one step, under the roster
        lock, because a socket closing in between is worse than one counted a
        heartbeat late. An entry snapshotted before `mark_absent` dropped it and
        written after its HDEL landed is gone from `_roster` but alive in Redis,
        stamped with an instance whose lease this process keeps renewing - so no
        later heartbeat rewrites it, no count ever prunes it, and it pads the
        room until the process stops. The lock is per event and covers one
        write, not the whole sweep, so a close waits on at most a single command
        for its own event and never on another event's.
        """
        for event_id in list(self._roster):
            async with self._roster_lock(event_id):
                fields = self._roster.get(event_id)
                if not fields:
                    continue
                mapping = {field: _INSTANCE_ID for field in fields}
                try:
                    await self.redis.hset(presence_key(event_id), mapping=mapping)
                except Exception as e:
                    logger.exception(
                        "Failed to reassert recitation presence for event %s: %s",
                        event_id,
                        e,
                    )

    async def presence_count(self, event_id: UUID) -> int:
        """People joined to this event across every live instance."""
        try:
            count = await self.redis.eval(
                _PRESENCE_COUNT_SCRIPT,
                1,
                presence_key(event_id),
                INSTANCE_LEASE_PREFIX,
            )
        except Exception as e:
            logger.exception("Failed to read recitation presence from Redis: %s", e)
            return 0
        return int(count)

    async def broadcast_presence(self, event_id: UUID) -> int:
        """Tell every socket in the room how many people are joined.

        Returns the count that was published, so a caller that also has to
        report it - the joining socket's session_info - quotes the same number
        the room was just given instead of taking its own reading.
        """
        try:
            count = await self.redis.eval(
                _PRESENCE_BROADCAST_SCRIPT,
                2,
                presence_key(event_id),
                position_channel(event_id),
                INSTANCE_LEASE_PREFIX,
                str(event_id),
            )
        except Exception as e:
            logger.exception("Failed to broadcast recitation presence: %s", e)
            return 0
        return int(count)


# Global broadcaster instance (initialized in app startup)
broadcaster: Optional[RecitationBroadcaster] = None


def get_broadcaster() -> RecitationBroadcaster:
    """Get the global broadcaster instance."""
    if broadcaster is None:
        error_msg = (
            "❌ Recitation broadcaster not initialized.\n"
            "   - Make sure Redis/Dragonfly is running\n"
            "   - Check REDIS_URL configuration\n"
            "   - App startup failed - check server logs for Redis connection errors"
        )
        raise RuntimeError(error_msg)
    if broadcaster.redis is None:
        error_msg = (
            "❌ Redis connection lost.\n"
            "   - Redis/Dragonfly may have crashed\n"
            "   - Network connection may be down\n"
            "   - Restart Redis and restart the application"
        )
        raise RuntimeError(error_msg)
    return broadcaster


async def init_broadcaster(redis_url: str) -> RecitationBroadcaster:
    """Initialize the global broadcaster instance."""
    global broadcaster
    broadcaster = RecitationBroadcaster(redis_url)
    await broadcaster.connect()
    # A redeploy is the one moment every instance agrees is a fresh start, so
    # it is where stale throttle counters go.
    await broadcaster.clear_rate_keys()
    return broadcaster
