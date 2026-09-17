import json
import logging
from typing import Dict, Optional
from uuid import UUID

from redis.asyncio import Redis
from redis.asyncio.client import PubSub

logger = logging.getLogger(__name__)

# A puja runs for hours; the snapshot only has to outlive the session itself.
POSITION_TTL_SECONDS = 12 * 60 * 60

# Per-event publish ceiling. An operator clicks a handful of times a minute, so
# anything near this is a stuck key or a rogue client, not a fast reader.
MAX_SETS_PER_SECOND = 10


def position_channel(event_id: UUID) -> str:
    return f"recitation:event:{event_id}:position"


def position_state_key(event_id: UUID) -> str:
    return f"recitation:event:{event_id}:state"


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
        # Track local WebSocket connections: {event_id: {user_id: websocket}}
        self.connections: Dict[UUID, Dict[UUID, object]] = {}

    async def connect(self) -> None:
        """Initialize Redis connection."""
        try:
            self.redis = await Redis.from_url(
                self.redis_url, decode_responses=True, socket_keepalive=True
            )
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
        if self.redis:
            await self.redis.close()
            logger.info("Redis connection closed for recitation broadcaster")

    async def add_connection(self, event_id: UUID, user_id: UUID, ws: object) -> None:
        """Track a local WebSocket connection."""
        if event_id not in self.connections:
            self.connections[event_id] = {}
        self.connections[event_id][user_id] = ws

    async def remove_connection(self, event_id: UUID, user_id: UUID) -> None:
        """Drop a local WebSocket connection."""
        if event_id in self.connections:
            self.connections[event_id].pop(user_id, None)
            if not self.connections[event_id]:
                del self.connections[event_id]

    async def subscribe_to_event(self, event_id: UUID) -> PubSub:
        """Subscribe to the position stream for an event."""
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(position_channel(event_id))
        return pubsub

    async def save_position(
        self,
        event_id: UUID,
        text_id: str,
        segment_id: str,
        index: Optional[int],
        round_number: Optional[int],
        server_time: str,
    ) -> None:
        """Mirror the current position into Redis so connects and redeploys can
        resync. Best-effort: a snapshot failure must not swallow the broadcast,
        which is what the people in the room are actually waiting on."""
        key = position_state_key(event_id)
        try:
            await self.redis.hset(
                key,
                mapping={
                    "text_id": text_id,
                    "segment_id": segment_id,
                    "index": "" if index is None else str(index),
                    "round_number": "" if round_number is None else str(round_number),
                    "updated_at": server_time,
                },
            )
            await self.redis.expire(key, POSITION_TTL_SECONDS)
        except Exception as e:
            logger.error(f"Failed to save recitation position to Redis: {e}")

    async def get_position(self, event_id: UUID) -> Optional[dict]:
        """The current position for an event, or None when nothing has been set
        (or the snapshot has expired)."""
        try:
            state = await self.redis.hgetall(position_state_key(event_id))
        except Exception as e:
            logger.error(f"Failed to read recitation position from Redis: {e}")
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
        }

    async def clear_position(self, event_id: UUID) -> None:
        """Forget the position when the operator ends the session, so the next
        puja on the same event does not start mid-liturgy."""
        try:
            await self.redis.delete(position_state_key(event_id))
        except Exception as e:
            logger.error(f"Failed to clear recitation position in Redis: {e}")

    async def broadcast_position(
        self,
        event_id: UUID,
        text_id: str,
        segment_id: str,
        index: Optional[int],
        round_number: Optional[int],
        server_time: str,
    ) -> None:
        """Snapshot, then publish the position to every server via Redis pub/sub."""
        await self.save_position(
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
        }

        try:
            await self.redis.publish(position_channel(event_id), json.dumps(payload))
        except Exception as e:
            logger.error(f"Failed to broadcast recitation position to Redis: {e}")
            raise

    async def broadcast_session_ended(self, event_id: UUID) -> None:
        """Tell every server holding a socket for this event that the operator
        closed the puja, so clients stop auto-scrolling and release."""
        payload = {"type": "session_ended", "event_id": str(event_id)}
        try:
            await self.redis.publish(position_channel(event_id), json.dumps(payload))
        except Exception as e:
            logger.error(f"Failed to broadcast recitation session end to Redis: {e}")

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
            logger.error(f"Failed to check recitation rate limit in Redis: {e}")
            return True

    async def get_connected_users(self, event_id: UUID) -> Dict[UUID, object]:
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
