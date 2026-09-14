import json
import logging
from typing import Dict, Optional
from uuid import UUID

from redis.asyncio import Redis

from pecha_api.chat.response_models import ChatMessageDTO

logger = logging.getLogger(__name__)


class ChatBroadcaster:
    """Manages WebSocket connections and Redis pub/sub for real-time chat rooms."""

    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self.redis: Optional[Redis] = None
        # Track local WebSocket connections: {room_id: {user_id: websocket}}
        self.connections: Dict[UUID, Dict[UUID, object]] = {}

    async def connect(self) -> None:
        """Initialize Redis connection."""
        try:
            self.redis = await Redis.from_url(
                self.redis_url, decode_responses=True, socket_keepalive=True
            )
            logger.info("✅ Redis connection established for chat broadcaster")
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
            logger.info("Redis connection closed for chat broadcaster")

    async def add_connection(self, room_id: UUID, user_id: UUID, email: str, ws: object) -> None:
        """Track local WebSocket connection and mark presence in Redis."""
        if room_id not in self.connections:
            self.connections[room_id] = {}
        self.connections[room_id][user_id] = ws

        try:
            await self.redis.hset(f"chat:room:{room_id}:presence", str(user_id), email)
        except Exception as e:
            logger.error(f"Failed to add presence to Redis: {e}")

    async def remove_connection(self, room_id: UUID, user_id: UUID) -> None:
        """Remove local WebSocket connection and cleanup presence in Redis."""
        if room_id in self.connections:
            self.connections[room_id].pop(user_id, None)
            if not self.connections[room_id]:
                del self.connections[room_id]

        try:
            await self.redis.hdel(f"chat:room:{room_id}:presence", str(user_id))
        except Exception as e:
            logger.error(f"Failed to remove presence from Redis: {e}")

    async def broadcast_message(
        self,
        room_id: UUID,
        message: ChatMessageDTO,
    ) -> None:
        """Publish a chat message to all servers via Redis pub/sub."""
        channel = f"chat:room:{room_id}:messages"
        payload = {
            "type": "message_created",
            "message": message.model_dump(mode="json"),
        }

        try:
            await self.redis.publish(channel, json.dumps(payload))
        except Exception as e:
            logger.error(f"Failed to broadcast message to Redis: {e}")
            raise

    async def broadcast_reactions(
        self,
        room_id: UUID,
        message_id: UUID,
        reactions: list,
    ) -> None:
        """Publish a message's updated reaction summary to the room.

        reacted_by_me is viewer-specific, so it is forced False here; clients
        must derive their own state from each summary's user_ids."""
        channel = f"chat:room:{room_id}:messages"
        payload = {
            "type": "reactions_updated",
            "message_id": str(message_id),
            "reactions": [
                {**reaction.model_dump(mode="json"), "reacted_by_me": False}
                for reaction in reactions
            ],
        }

        try:
            await self.redis.publish(channel, json.dumps(payload))
        except Exception as e:
            logger.error(f"Failed to broadcast reactions to Redis: {e}")
            raise

    async def broadcast_prayers(
        self,
        room_id: UUID,
        prayers: list,
    ) -> None:
        """Publish updated prayer counts for one or more prayer requests.

        A batch pray sends one payload for every message the user selected, so
        praying for twenty requests is one publish, not twenty. prayed_by_me is
        viewer-specific and cannot travel in a shared broadcast; clients derive
        their own state from each entry's user_ids, as they do for reactions."""
        channel = f"chat:room:{room_id}:messages"
        payload = {
            "type": "prayers_updated",
            "prayers": prayers,
        }

        try:
            await self.redis.publish(channel, json.dumps(payload))
        except Exception as e:
            logger.error(f"Failed to broadcast prayers to Redis: {e}")
            raise

    async def broadcast_message_deleted(
        self,
        room_id: UUID,
        message_id: UUID,
        deleted_by: dict,
        deleted_at: str,
    ) -> None:
        """Publish a message deletion to the room, so every connected client
        can grey it out live (WhatsApp-style) instead of waiting for the next
        history fetch."""
        channel = f"chat:room:{room_id}:messages"
        payload = {
            "type": "message_deleted",
            "message_id": str(message_id),
            "deleted_by": deleted_by,
            "deleted_at": deleted_at,
        }

        try:
            await self.redis.publish(channel, json.dumps(payload))
        except Exception as e:
            logger.error(f"Failed to broadcast message deletion to Redis: {e}")
            raise

    async def broadcast_typing(
        self,
        room_id: UUID,
        user_id: UUID,
        email: str,
        is_typing: bool,
    ) -> None:
        """Publish an ephemeral typing-indicator event (not persisted)."""
        channel = f"chat:room:{room_id}:messages"
        payload = {
            "type": "typing",
            "user_id": str(user_id),
            "email": email,
            "is_typing": is_typing,
        }

        try:
            await self.redis.publish(channel, json.dumps(payload))
        except Exception as e:
            logger.error(f"Failed to broadcast typing indicator to Redis: {e}")

    async def broadcast_room_closed(self, room_id: UUID, reason: str) -> None:
        """Tell every server holding a socket for this room to drop it.

        Connections live in each server's memory, so Redis is what carries the
        eviction across the fleet. Best-effort: a publish failure must not fail
        the hide, which is already gated at the request layer.
        """
        channel = f"chat:room:{room_id}:messages"
        payload = {"type": "room_closed", "reason": reason}

        try:
            await self.redis.publish(channel, json.dumps(payload))
        except Exception as e:
            logger.error(f"Failed to broadcast room close to Redis: {e}")

    async def broadcast_presence(self, room_id: UUID) -> None:
        """Publish the current online roster for a room (not persisted)."""
        online = await self.get_connected_users(room_id)
        channel = f"chat:room:{room_id}:messages"
        payload = {
            "type": "presence",
            "count": len(online),
            "online": [{"user_id": user_id, "email": email} for user_id, email in online.items()],
        }

        try:
            await self.redis.publish(channel, json.dumps(payload))
        except Exception as e:
            logger.error(f"Failed to broadcast presence to Redis: {e}")

    async def subscribe_to_room(self, room_id: UUID):
        """Subscribe to the message stream for a room."""
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(f"chat:room:{room_id}:messages")
        return pubsub

    async def get_connected_users(self, room_id: UUID) -> Dict[str, str]:
        """Get all users connected to a room (across all servers) as {user_id: email}."""
        try:
            return await self.redis.hgetall(f"chat:room:{room_id}:presence")
        except Exception as e:
            logger.error(f"Failed to get connected users from Redis: {e}")
            return {}


# Global broadcaster instance (initialized in app startup)
broadcaster: Optional[ChatBroadcaster] = None


def get_broadcaster() -> ChatBroadcaster:
    """Get the global broadcaster instance."""
    if broadcaster is None:
        error_msg = (
            "❌ Chat broadcaster not initialized.\n"
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


async def init_broadcaster(redis_url: str) -> ChatBroadcaster:
    """Initialize the global broadcaster instance."""
    global broadcaster
    broadcaster = ChatBroadcaster(redis_url)
    await broadcaster.connect()
    return broadcaster
