import asyncio
import json
import logging
from typing import Dict, List, Optional
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


def instance_lease_key(instance_id: str) -> str:
    return f"recitation:instance:{instance_id}"


# One id per process. A socket's presence value is "{token}|{instance id}", so a
# crashed instance's joins drop out of the count once its lease expires instead
# of sitting there until someone deletes the hash.
_INSTANCE_ID = str(uuid4())
# The heartbeat runs well inside the lease, so one stalled loop does not look
# like a crash and zero the room.
INSTANCE_LEASE_SECONDS = 45
INSTANCE_HEARTBEAT_SECONDS = 20


# Drop this socket's presence only when it is still the one recorded. A
# reconnect writes a new token first; the old socket's cleanup must not erase it.
_RELEASE_PRESENCE_SCRIPT = """
local current = redis.call('HGET', KEYS[1], ARGV[1])
if current == ARGV[2] then
    redis.call('HDEL', KEYS[1], ARGV[1])
end
return redis.call('HLEN', KEYS[1])
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
                await self.refresh_instance_lease()
            except Exception as e:
                logger.exception("Failed to refresh recitation instance lease: %s", e)

    async def mark_present(self, event_id: UUID, user_id: UUID) -> str:
        """Record this socket in the shared roster. Returns the token that
        `mark_absent` must hand back, so an older socket cannot erase a newer one.
        """
        token = f"{uuid4()}|{_INSTANCE_ID}"
        try:
            await self.redis.hset(presence_key(event_id), str(user_id), token)
        except Exception as e:
            logger.exception("Failed to mark recitation presence in Redis: %s", e)
        return token

    async def mark_absent(self, event_id: UUID, user_id: UUID, token: str) -> None:
        """Drop this socket's roster entry when it is still the current one."""
        try:
            await self.redis.eval(
                _RELEASE_PRESENCE_SCRIPT,
                1,
                presence_key(event_id),
                str(user_id),
                token,
            )
        except Exception as e:
            logger.exception("Failed to clear recitation presence in Redis: %s", e)

    async def presence_count(self, event_id: UUID) -> int:
        """People joined to this event across every live instance."""
        try:
            roster = await self.redis.hgetall(presence_key(event_id))
        except Exception as e:
            logger.exception("Failed to read recitation presence from Redis: %s", e)
            return 0
        if not roster:
            return 0

        by_instance: Dict[str, List[str]] = {}
        for user_id, value in roster.items():
            instance_id = str(value).rsplit("|", 1)[-1]
            by_instance.setdefault(instance_id, []).append(str(user_id))

        instance_ids = list(by_instance)
        try:
            alive_flags = await self.redis.mget(
                *[instance_lease_key(instance_id) for instance_id in instance_ids]
            )
        except Exception as e:
            logger.exception("Failed to read recitation instance leases: %s", e)
            return 0

        alive = {
            instance_id
            for instance_id, flag in zip(instance_ids, alive_flags)
            if flag is not None
        }
        stale = [
            user_id
            for instance_id, user_ids in by_instance.items()
            if instance_id not in alive
            for user_id in user_ids
        ]
        if stale:
            try:
                await self.redis.hdel(presence_key(event_id), *stale)
            except Exception as e:
                logger.exception("Failed to drop stale recitation presence: %s", e)
        return sum(
            len(user_ids)
            for instance_id, user_ids in by_instance.items()
            if instance_id in alive
        )

    async def broadcast_presence(self, event_id: UUID) -> None:
        """Tell every socket in the room how many people are joined."""
        count = await self.presence_count(event_id)
        payload = {
            "type": "presence",
            "event_id": str(event_id),
            "count": count,
        }
        try:
            await self.redis.publish(position_channel(event_id), json.dumps(payload))
        except Exception as e:
            logger.exception("Failed to broadcast recitation presence: %s", e)


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
