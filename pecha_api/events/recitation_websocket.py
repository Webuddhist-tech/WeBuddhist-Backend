import json
import logging
from typing import Dict, Optional
from uuid import UUID

from redis.asyncio import Redis

from pecha_api.realtime.channel_fanout import ChannelFanout, Subscriber

logger = logging.getLogger(__name__)

# A puja runs for hours; the snapshot only has to outlive the session itself.
POSITION_TTL_SECONDS = 12 * 60 * 60

# Per-event publish ceiling. An operator clicks a handful of times a minute, so
# anything near this is a stuck key or a rogue client, not a fast reader.
MAX_SETS_PER_SECOND = 50


def position_channel(event_id: UUID) -> str:
    return f"recitation:event:{event_id}:position"


def position_state_key(event_id: UUID) -> str:
    return f"recitation:event:{event_id}:state"


def position_revision_key(event_id: UUID) -> str:
    return f"recitation:event:{event_id}:rev"


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


class RecitationBroadcaster:
    """Manages WebSocket connections and Redis pub/sub for live recitation
    position, plus the current-position snapshot each new subscriber is sent.

    Unlike chat, which is a stream of events, a recitation has exactly one
    interesting value: which text the operator is in, and where. That value is
    mirrored into a Redis hash on every set, so a phone joining 40 minutes in -
    or an instance restarted by a deploy - lands on the live line instead of
    waiting for the operator's next click.
    """

    def __init__(self, redis_url: str) -> None:
        self.redis_url = redis_url
        self.redis: Optional[Redis] = None
        # One Redis subscription per event, shared by every socket watching
        # it on this instance.
        self.fanout: Optional[ChannelFanout] = None
        # Track local WebSocket connections: {event_id: {user_id: websocket}}
        self.connections: Dict[UUID, Dict[UUID, object]] = {}

    async def connect(self) -> None:
        """Initialize Redis connection."""
        try:
            self.redis = await Redis.from_url(
                self.redis_url, decode_responses=True, socket_keepalive=True
            )
            # A position is last-write-wins, so a socket that falls behind
            # wants the newest frame, not a backlog of stale ones.
            self.fanout = ChannelFanout(self.redis, queue_maxsize=64, drop_oldest=True)
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
        if self.fanout:
            await self.fanout.aclose()
        if self.redis:
            await self.redis.close()
            logger.info("Redis connection closed for recitation broadcaster")

    def add_connection(self, event_id: UUID, user_id: UUID, ws: object) -> None:
        """Track a local WebSocket connection.

        Plain dict bookkeeping: unlike chat, a recitation keeps no presence
        in Redis, so there is nothing here to await.
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

        Fails open - if Redis cannot answer, the puja keeps running rather than
        going silent over a rate counter.
        """
        key = f"recitation:event:{event_id}:rate"
        try:
            count = await self.redis.incr(key)
            if count == 1:
                await self.redis.expire(key, 1)
            return count <= MAX_SETS_PER_SECOND
        except Exception as e:
            logger.exception("Failed to check recitation rate limit in Redis: %s", e)
            return True

    def get_connected_users(self, event_id: UUID) -> Dict[UUID, object]:
        """Sockets this server holds for an event (local only - position is the
        shared state here, not presence)."""
        return self.connections.get(event_id, {})


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
    return broadcaster
