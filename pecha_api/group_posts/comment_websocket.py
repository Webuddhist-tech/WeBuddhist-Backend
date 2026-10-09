import asyncio
import json
import logging
from typing import Dict, Optional
from uuid import UUID

from redis.asyncio import Redis
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

from pecha_api.group_posts.comment_response_models import GroupPostCommentDTO
from pecha_api.realtime.channel_fanout import ChannelFanout, Subscriber

logger = logging.getLogger(__name__)


def post_channel(post_id: UUID) -> str:
    return f"post:{post_id}:comments"


class PostCommentBroadcaster:
    """Manages WebSocket connections and Redis pub/sub for real-time comments."""

    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self.redis: Optional[Redis] = None
        # One Redis subscription per post, shared by every socket watching
        # it on this instance.
        self.fanout: Optional[ChannelFanout] = None
        # Track local WebSocket connections: {post_id: {user_id: websocket}}
        self.connections: Dict[UUID, Dict[UUID, object]] = {}

    async def connect(self) -> None:
        """Initialize Redis connection."""
        try:
            self.redis = await Redis.from_url(
                self.redis_url, decode_responses=True, socket_keepalive=True
            )
            self.fanout = ChannelFanout(self.redis)
            logger.info("✅ Redis connection established for comment broadcaster")
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
            logger.info("Redis connection closed for comment broadcaster")

    async def add_connection(self, post_id: UUID, user_id: UUID, ws: object) -> None:
        """Track local WebSocket connection and mark in Redis."""
        if post_id not in self.connections:
            self.connections[post_id] = {}
        self.connections[post_id][user_id] = ws

        # Track in Redis: post:{post_id}:users = set of user_ids connected on this server
        try:
            await self.redis.sadd(f"post:{post_id}:users", str(user_id))
        except Exception as e:
            logger.exception("Failed to add connection to Redis: %s", e)

    async def remove_connection(self, post_id: UUID, user_id: UUID) -> None:
        """Remove local WebSocket connection and cleanup Redis tracking."""
        if post_id in self.connections:
            self.connections[post_id].pop(user_id, None)
            if not self.connections[post_id]:
                del self.connections[post_id]

        # Cleanup Redis tracking
        try:
            await self.redis.srem(f"post:{post_id}:users", str(user_id))
        except Exception as e:
            logger.exception("Failed to remove connection from Redis: %s", e)

    async def broadcast_comment(
        self,
        post_id: UUID,
        comment: GroupPostCommentDTO,
    ) -> None:
        """Publish comment to all servers via Redis pub/sub."""
        channel = post_channel(post_id)
        message = {
            "type": "comment_created",
            "comment": comment.model_dump(mode="json"),
        }

        try:
            # Publish to Redis: all servers subscribe to this channel
            await self.redis.publish(channel, json.dumps(message))
        except Exception as e:
            logger.exception("Failed to broadcast comment to Redis: %s", e)
            raise

    async def subscribe_to_post(self, post_id: UUID) -> Subscriber:
        """Attach to the comment stream for a post.

        Shares this instance's single subscription for the post. Release it
        with `unsubscribe_from_post`.
        """
        return await self.fanout.subscribe(post_channel(post_id))

    async def unsubscribe_from_post(self, post_id: UUID, subscriber: Subscriber) -> None:
        """Detach a socket; the last one out closes the Redis subscription."""
        await self.fanout.unsubscribe(post_channel(post_id), subscriber)

    async def get_connected_users(self, post_id: UUID) -> set:
        """Get all users connected to a post (across all servers)."""
        try:
            return await self.redis.smembers(f"post:{post_id}:users")
        except Exception as e:
            logger.exception("Failed to get connected users from Redis: %s", e)
            return set()


# Global broadcaster instance (initialized in app startup)
broadcaster: Optional[PostCommentBroadcaster] = None


def get_broadcaster() -> PostCommentBroadcaster:
    """Get the global broadcaster instance."""
    if broadcaster is None:
        error_msg = (
            "❌ Comment broadcaster not initialized.\n"
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


async def init_broadcaster(redis_url: str) -> PostCommentBroadcaster:
    """Initialize the global broadcaster instance."""
    global broadcaster
    broadcaster = PostCommentBroadcaster(redis_url)
    await broadcaster.connect()
    return broadcaster
