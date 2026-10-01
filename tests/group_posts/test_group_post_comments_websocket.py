import asyncio
import pytest
from unittest.mock import patch, AsyncMock, MagicMock, ANY
from uuid import uuid4
from datetime import datetime, timezone as tz

from pecha_api.group_posts.comment_response_models import GroupPostCommentDTO


async def _never_ending():
    """A subscription that stays open, as a real one does."""
    await asyncio.Event().wait()
    yield  # pragma: no cover


class MockUser:
    def __init__(self, user_id=None, email="user@example.com"):
        self.id = user_id or uuid4()
        self.email = email


class TestPostCommentBroadcasterUnit:
    """Unit tests for PostCommentBroadcaster class."""

    @pytest.mark.asyncio
    async def test_broadcaster_initialization(self):
        """Test broadcaster initializes correctly."""
        from pecha_api.group_posts.comment_websocket import PostCommentBroadcaster

        redis_url = "redis://localhost:6379/0"
        broadcaster = PostCommentBroadcaster(redis_url)

        assert broadcaster.redis_url == redis_url
        assert broadcaster.redis is None
        assert broadcaster.connections == {}

    @pytest.mark.asyncio
    async def test_broadcaster_connect_disconnect(self):
        """Test broadcaster connection lifecycle."""
        from pecha_api.group_posts.comment_websocket import PostCommentBroadcaster
        from unittest.mock import AsyncMock, patch

        redis_url = "redis://localhost:6379/0"
        broadcaster = PostCommentBroadcaster(redis_url)

        # Mock Redis connection with an async function that returns mock
        mock_redis = AsyncMock()

        async def mock_from_url(*args, **kwargs):
            return mock_redis

        with patch("pecha_api.group_posts.comment_websocket.Redis.from_url", side_effect=mock_from_url):
            await broadcaster.connect()
            assert broadcaster.redis is not None

            await broadcaster.disconnect()
            mock_redis.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcaster_add_remove_connection(self):
        """Test tracking WebSocket connections."""
        from pecha_api.group_posts.comment_websocket import PostCommentBroadcaster
        from unittest.mock import AsyncMock, patch

        broadcaster = PostCommentBroadcaster("redis://localhost:6379/0")
        broadcaster.redis = AsyncMock()

        post_id = uuid4()
        user_id = uuid4()
        mock_ws = AsyncMock()

        # Add connection
        await broadcaster.add_connection(post_id, user_id, mock_ws)
        assert post_id in broadcaster.connections
        assert user_id in broadcaster.connections[post_id]
        broadcaster.redis.sadd.assert_called_once()

        # Remove connection
        await broadcaster.remove_connection(post_id, user_id)
        assert post_id not in broadcaster.connections
        broadcaster.redis.srem.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcaster_broadcast_comment(self):
        """Test broadcasting comment to Redis pub/sub."""
        from pecha_api.group_posts.comment_websocket import PostCommentBroadcaster

        broadcaster = PostCommentBroadcaster("redis://localhost:6379/0")
        broadcaster.redis = AsyncMock()

        post_id = uuid4()
        now = datetime.now(tz.utc).isoformat()

        comment_dto = GroupPostCommentDTO(
            id=uuid4(),
            post_id=post_id,
            user_email="test@example.com",
            user={
                "first_name": "First",
                "last_name": "Last",
                "email": "test@example.com",
                "avatar_url": None,
            },
            text="Great post!",
            created_at=now,
            updated_at=now,
        )

        await broadcaster.broadcast_comment(post_id, comment_dto)
        broadcaster.redis.publish.assert_called_once()

        # Verify channel name and message structure
        call_args = broadcaster.redis.publish.call_args
        assert f"post:{post_id}:comments" in str(call_args)

    @pytest.mark.asyncio
    async def test_broadcaster_get_connected_users(self):
        """Test getting connected users from Redis."""
        from pecha_api.group_posts.comment_websocket import PostCommentBroadcaster

        broadcaster = PostCommentBroadcaster("redis://localhost:6379/0")
        broadcaster.redis = AsyncMock()

        post_id = uuid4()
        users = {"user1", "user2", "user3"}
        broadcaster.redis.smembers.return_value = users

        result = await broadcaster.get_connected_users(post_id)
        assert result == users
        broadcaster.redis.smembers.assert_called_once_with(f"post:{post_id}:users")


class TestPostCommentBroadcasterFailures:
    """Redis is treated as best-effort for tracking, but fatal for publishing."""

    @pytest.mark.parametrize(
        "redis_error, expected_error",
        [
            (ConnectionRefusedError("refused"), ConnectionError),
            (TimeoutError("timed out"), TimeoutError),
            (ValueError("bad url"), RuntimeError),
        ],
    )
    @pytest.mark.asyncio
    async def test_connect_wraps_redis_errors(self, redis_error, expected_error):
        from pecha_api.group_posts.comment_websocket import PostCommentBroadcaster

        broadcaster = PostCommentBroadcaster("redis://localhost:6379/0")

        with patch(
            "pecha_api.group_posts.comment_websocket.Redis.from_url",
            side_effect=redis_error,
        ):
            with pytest.raises(expected_error):
                await broadcaster.connect()

        assert broadcaster.redis is None

    @pytest.mark.asyncio
    async def test_disconnect_without_connection_is_a_noop(self):
        from pecha_api.group_posts.comment_websocket import PostCommentBroadcaster

        broadcaster = PostCommentBroadcaster("redis://localhost:6379/0")

        await broadcaster.disconnect()

        assert broadcaster.redis is None

    @pytest.mark.asyncio
    async def test_add_connection_survives_redis_failure(self):
        from pecha_api.group_posts.comment_websocket import PostCommentBroadcaster

        broadcaster = PostCommentBroadcaster("redis://localhost:6379/0")
        broadcaster.redis = AsyncMock()
        broadcaster.redis.sadd.side_effect = RuntimeError("redis down")

        post_id, user_id = uuid4(), uuid4()
        await broadcaster.add_connection(post_id, user_id, AsyncMock())

        assert broadcaster.connections[post_id][user_id] is not None

    @pytest.mark.asyncio
    async def test_remove_connection_survives_redis_failure(self):
        from pecha_api.group_posts.comment_websocket import PostCommentBroadcaster

        broadcaster = PostCommentBroadcaster("redis://localhost:6379/0")
        broadcaster.redis = AsyncMock()
        broadcaster.redis.srem.side_effect = RuntimeError("redis down")

        post_id, user_id = uuid4(), uuid4()
        broadcaster.connections[post_id] = {user_id: AsyncMock(), uuid4(): AsyncMock()}

        await broadcaster.remove_connection(post_id, user_id)

        assert user_id not in broadcaster.connections[post_id]

    @pytest.mark.asyncio
    async def test_remove_connection_for_unknown_post_is_a_noop(self):
        from pecha_api.group_posts.comment_websocket import PostCommentBroadcaster

        broadcaster = PostCommentBroadcaster("redis://localhost:6379/0")
        broadcaster.redis = AsyncMock()

        await broadcaster.remove_connection(uuid4(), uuid4())

        assert broadcaster.connections == {}

    @pytest.mark.asyncio
    async def test_broadcast_comment_reraises_redis_failure(self):
        from pecha_api.group_posts.comment_websocket import PostCommentBroadcaster

        broadcaster = PostCommentBroadcaster("redis://localhost:6379/0")
        broadcaster.redis = AsyncMock()
        broadcaster.redis.publish.side_effect = RuntimeError("publish failed")

        post_id = uuid4()
        now = datetime.now(tz.utc).isoformat()
        comment = GroupPostCommentDTO(
            id=uuid4(),
            post_id=post_id,
            user_email="test@example.com",
            user={
                "first_name": "First",
                "last_name": "Last",
                "email": "test@example.com",
                "avatar_url": None,
            },
            text="Great post!",
            created_at=now,
            updated_at=now,
        )

        with pytest.raises(RuntimeError, match="publish failed"):
            await broadcaster.broadcast_comment(post_id, comment)

    @pytest.mark.asyncio
    async def test_post_subscription_is_shared_and_released_once_empty(self):
        """Watchers of one post share a single Redis subscription, and the last
        one out closes it. One per socket - or a close without aclose() - leaks
        a Redis connection per client until Redis refuses new ones."""
        from pecha_api.group_posts.comment_websocket import PostCommentBroadcaster
        from pecha_api.realtime.channel_fanout import ChannelFanout

        broadcaster = PostCommentBroadcaster("redis://localhost:6379/0")
        pubsub = MagicMock()
        pubsub.subscribe = AsyncMock()
        pubsub.unsubscribe = AsyncMock()
        pubsub.aclose = AsyncMock()
        pubsub.listen = lambda: _never_ending()
        redis = MagicMock()
        redis.pubsub.return_value = pubsub
        broadcaster.redis = redis
        broadcaster.fanout = ChannelFanout(redis)

        post_id = uuid4()
        channel = f"post:{post_id}:comments"

        first = await broadcaster.subscribe_to_post(post_id)
        second = await broadcaster.subscribe_to_post(post_id)

        pubsub.subscribe.assert_awaited_once_with(channel)
        assert redis.pubsub.call_count == 1

        await broadcaster.unsubscribe_from_post(post_id, first)
        pubsub.aclose.assert_not_awaited()

        await broadcaster.unsubscribe_from_post(post_id, second)
        pubsub.unsubscribe.assert_awaited_once_with(channel)
        # The call that actually hands the connection back to the pool.
        pubsub.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_connected_users_returns_empty_set_on_redis_failure(self):
        from pecha_api.group_posts.comment_websocket import PostCommentBroadcaster

        broadcaster = PostCommentBroadcaster("redis://localhost:6379/0")
        broadcaster.redis = AsyncMock()
        broadcaster.redis.smembers.side_effect = RuntimeError("redis down")

        assert await broadcaster.get_connected_users(uuid4()) == set()


class TestBroadcasterLifecycle:

    def test_get_broadcaster_raises_when_not_initialized(self):
        from pecha_api.group_posts import comment_websocket

        with patch.object(comment_websocket, "broadcaster", None):
            with pytest.raises(RuntimeError, match="not initialized"):
                comment_websocket.get_broadcaster()

    def test_get_broadcaster_raises_when_redis_connection_is_lost(self):
        from pecha_api.group_posts import comment_websocket

        disconnected = comment_websocket.PostCommentBroadcaster("redis://localhost:6379/0")

        with patch.object(comment_websocket, "broadcaster", disconnected):
            with pytest.raises(RuntimeError, match="Redis connection lost"):
                comment_websocket.get_broadcaster()

    def test_get_broadcaster_returns_connected_instance(self):
        from pecha_api.group_posts import comment_websocket

        connected = comment_websocket.PostCommentBroadcaster("redis://localhost:6379/0")
        connected.redis = AsyncMock()

        with patch.object(comment_websocket, "broadcaster", connected):
            assert comment_websocket.get_broadcaster() is connected

    @pytest.mark.asyncio
    async def test_init_broadcaster_connects_and_sets_the_global(self):
        from pecha_api.group_posts import comment_websocket

        instance = MagicMock()
        instance.connect = AsyncMock()

        with patch.object(comment_websocket, "broadcaster", None), patch.object(
            comment_websocket, "PostCommentBroadcaster", return_value=instance
        ) as mock_cls:
            result = await comment_websocket.init_broadcaster("redis://localhost:6379/0")

            assert result is instance
            assert comment_websocket.broadcaster is instance
            mock_cls.assert_called_once_with("redis://localhost:6379/0")
            instance.connect.assert_awaited_once()

        assert comment_websocket.broadcaster is None
