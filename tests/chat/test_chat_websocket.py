import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from datetime import datetime, timezone as tz

from pecha_api.chat.response_models import ChatMessageDTO


def _message_dto(room_id) -> ChatMessageDTO:
    return ChatMessageDTO(
        id=uuid4(),
        room_id=room_id,
        sender_id=uuid4(),
        sender_email="sender@example.com",
        sender_name="Sender Name",
        body="Hello",
        created_at=datetime.now(tz.utc).isoformat(),
    )


class TestChatBroadcasterUnit:

    @pytest.mark.asyncio
    async def test_broadcaster_initialization(self):
        from pecha_api.chat.chat_websocket import ChatBroadcaster

        redis_url = "redis://localhost:6379/0"
        broadcaster = ChatBroadcaster(redis_url)

        assert broadcaster.redis_url == redis_url
        assert broadcaster.redis is None
        assert broadcaster.connections == {}

    @pytest.mark.asyncio
    async def test_broadcaster_connect_disconnect(self):
        from pecha_api.chat.chat_websocket import ChatBroadcaster

        broadcaster = ChatBroadcaster("redis://localhost:6379/0")
        mock_redis = AsyncMock()

        async def mock_from_url(*args, **kwargs):
            return mock_redis

        with patch("pecha_api.chat.chat_websocket.Redis.from_url", side_effect=mock_from_url):
            await broadcaster.connect()
            assert broadcaster.redis is not None

            await broadcaster.disconnect()
            mock_redis.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcaster_add_remove_connection(self):
        from pecha_api.chat.chat_websocket import ChatBroadcaster

        broadcaster = ChatBroadcaster("redis://localhost:6379/0")
        broadcaster.redis = AsyncMock()

        room_id = uuid4()
        user_id = uuid4()
        mock_ws = AsyncMock()

        await broadcaster.add_connection(room_id, user_id, "user@example.com", mock_ws)
        assert room_id in broadcaster.connections
        assert user_id in broadcaster.connections[room_id]
        broadcaster.redis.hset.assert_called_once_with(
            f"chat:room:{room_id}:presence", str(user_id), "user@example.com"
        )

        await broadcaster.remove_connection(room_id, user_id)
        assert room_id not in broadcaster.connections
        broadcaster.redis.hdel.assert_called_once_with(f"chat:room:{room_id}:presence", str(user_id))

    @pytest.mark.asyncio
    async def test_broadcaster_broadcast_presence(self):
        from pecha_api.chat.chat_websocket import ChatBroadcaster

        broadcaster = ChatBroadcaster("redis://localhost:6379/0")
        broadcaster.redis = AsyncMock()
        room_id = uuid4()
        user_id = uuid4()
        broadcaster.redis.hgetall.return_value = {str(user_id): "user@example.com"}

        await broadcaster.broadcast_presence(room_id)

        broadcaster.redis.hgetall.assert_called_once_with(f"chat:room:{room_id}:presence")
        broadcaster.redis.publish.assert_called_once()
        channel, payload = broadcaster.redis.publish.call_args.args
        assert channel == f"chat:room:{room_id}:messages"
        parsed = json.loads(payload)
        assert parsed["type"] == "presence"
        assert parsed["count"] == 1
        assert parsed["online"] == [{"user_id": str(user_id), "email": "user@example.com"}]

    @pytest.mark.asyncio
    async def test_get_connected_users_returns_dict(self):
        from pecha_api.chat.chat_websocket import ChatBroadcaster

        broadcaster = ChatBroadcaster("redis://localhost:6379/0")
        broadcaster.redis = AsyncMock()
        room_id = uuid4()
        broadcaster.redis.hgetall.return_value = {"abc": "a@example.com"}

        result = await broadcaster.get_connected_users(room_id)

        assert result == {"abc": "a@example.com"}

    @pytest.mark.asyncio
    async def test_broadcaster_broadcast_message(self):
        from pecha_api.chat.chat_websocket import ChatBroadcaster

        broadcaster = ChatBroadcaster("redis://localhost:6379/0")
        broadcaster.redis = AsyncMock()

        room_id = uuid4()
        message = _message_dto(room_id)

        await broadcaster.broadcast_message(room_id, message)

        broadcaster.redis.publish.assert_called_once()
        channel, payload = broadcaster.redis.publish.call_args.args
        assert channel == f"chat:room:{room_id}:messages"
        parsed = json.loads(payload)
        assert parsed["type"] == "message_created"
        assert parsed["message"]["body"] == "Hello"

    @pytest.mark.asyncio
    async def test_broadcaster_broadcast_typing(self):
        from pecha_api.chat.chat_websocket import ChatBroadcaster

        broadcaster = ChatBroadcaster("redis://localhost:6379/0")
        broadcaster.redis = AsyncMock()

        room_id = uuid4()
        user_id = uuid4()

        await broadcaster.broadcast_typing(room_id, user_id, "typer@example.com", is_typing=True)

        broadcaster.redis.publish.assert_called_once()
        channel, payload = broadcaster.redis.publish.call_args.args
        assert channel == f"chat:room:{room_id}:messages"
        parsed = json.loads(payload)
        assert parsed["type"] == "typing"
        assert parsed["user_id"] == str(user_id)
        assert parsed["email"] == "typer@example.com"
        assert parsed["is_typing"] is True

    def test_get_broadcaster_raises_when_not_initialized(self):
        import pecha_api.chat.chat_websocket as chat_websocket_module
        from pecha_api.chat.chat_websocket import get_broadcaster

        original = chat_websocket_module.broadcaster
        chat_websocket_module.broadcaster = None
        try:
            with pytest.raises(RuntimeError):
                get_broadcaster()
        finally:
            chat_websocket_module.broadcaster = original


async def _never_ending():
    """A subscription that stays open, as a real one does."""
    await asyncio.Event().wait()
    yield  # pragma: no cover


class TestChatBroadcasterFailures:

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
        from pecha_api.chat.chat_websocket import ChatBroadcaster

        broadcaster = ChatBroadcaster("redis://localhost:6379/0")

        with patch(
            "pecha_api.chat.chat_websocket.Redis.from_url",
            side_effect=redis_error,
        ):
            with pytest.raises(expected_error):
                await broadcaster.connect()

        assert broadcaster.redis is None

    @pytest.mark.asyncio
    async def test_disconnect_without_connection_is_a_noop(self):
        from pecha_api.chat.chat_websocket import ChatBroadcaster

        broadcaster = ChatBroadcaster("redis://localhost:6379/0")

        await broadcaster.disconnect()

        assert broadcaster.redis is None

    @pytest.mark.asyncio
    async def test_add_connection_survives_redis_failure(self):
        from pecha_api.chat.chat_websocket import ChatBroadcaster

        broadcaster = ChatBroadcaster("redis://localhost:6379/0")
        broadcaster.redis = AsyncMock()
        broadcaster.redis.hset.side_effect = RuntimeError("redis down")

        room_id, user_id = uuid4(), uuid4()
        await broadcaster.add_connection(room_id, user_id, "user@example.com", AsyncMock())

        assert broadcaster.connections[room_id][user_id] is not None

    @pytest.mark.asyncio
    async def test_remove_connection_survives_redis_failure(self):
        from pecha_api.chat.chat_websocket import ChatBroadcaster

        broadcaster = ChatBroadcaster("redis://localhost:6379/0")
        broadcaster.redis = AsyncMock()
        broadcaster.redis.hdel.side_effect = RuntimeError("redis down")

        room_id, user_id = uuid4(), uuid4()
        broadcaster.connections[room_id] = {user_id: AsyncMock(), uuid4(): AsyncMock()}

        await broadcaster.remove_connection(room_id, user_id)

        assert user_id not in broadcaster.connections[room_id]

    @pytest.mark.asyncio
    async def test_remove_connection_for_unknown_room_is_a_noop(self):
        from pecha_api.chat.chat_websocket import ChatBroadcaster

        broadcaster = ChatBroadcaster("redis://localhost:6379/0")
        broadcaster.redis = AsyncMock()

        await broadcaster.remove_connection(uuid4(), uuid4())

        assert broadcaster.connections == {}

    @pytest.mark.asyncio
    async def test_broadcast_message_reraises_redis_failure(self):
        from pecha_api.chat.chat_websocket import ChatBroadcaster

        broadcaster = ChatBroadcaster("redis://localhost:6379/0")
        broadcaster.redis = AsyncMock()
        broadcaster.redis.publish.side_effect = RuntimeError("publish failed")

        with pytest.raises(RuntimeError, match="publish failed"):
            await broadcaster.broadcast_message(uuid4(), _message_dto(uuid4()))

    @pytest.mark.asyncio
    async def test_broadcast_typing_survives_redis_failure(self):
        from pecha_api.chat.chat_websocket import ChatBroadcaster

        broadcaster = ChatBroadcaster("redis://localhost:6379/0")
        broadcaster.redis = AsyncMock()
        broadcaster.redis.publish.side_effect = RuntimeError("publish failed")

        await broadcaster.broadcast_typing(uuid4(), uuid4(), "a@example.com", True)

    @pytest.mark.asyncio
    async def test_broadcast_presence_survives_redis_failure(self):
        from pecha_api.chat.chat_websocket import ChatBroadcaster

        broadcaster = ChatBroadcaster("redis://localhost:6379/0")
        broadcaster.redis = AsyncMock()
        broadcaster.redis.hgetall.return_value = {}
        broadcaster.redis.publish.side_effect = RuntimeError("publish failed")

        await broadcaster.broadcast_presence(uuid4())

    @pytest.mark.asyncio
    async def test_room_subscription_is_shared_and_released_once_empty(self):
        """Two sockets in a room share one Redis subscription, and the last one
        to leave closes it. Opening one per socket - or closing it without
        aclose() - leaks a Redis connection per client until Redis refuses new
        ones at maxclients."""
        from pecha_api.chat.chat_websocket import ChatBroadcaster
        from pecha_api.realtime.channel_fanout import ChannelFanout
        from unittest.mock import MagicMock

        broadcaster = ChatBroadcaster("redis://localhost:6379/0")
        pubsub = MagicMock()
        pubsub.subscribe = AsyncMock()
        pubsub.unsubscribe = AsyncMock()
        pubsub.aclose = AsyncMock()
        pubsub.listen = lambda: _never_ending()
        redis = MagicMock()
        redis.pubsub.return_value = pubsub
        broadcaster.redis = redis
        broadcaster.fanout = ChannelFanout(redis)

        room_id = uuid4()
        channel = f"chat:room:{room_id}:messages"

        first = await broadcaster.subscribe_to_room(room_id)
        second = await broadcaster.subscribe_to_room(room_id)

        pubsub.subscribe.assert_awaited_once_with(channel)
        assert redis.pubsub.call_count == 1

        await broadcaster.unsubscribe_from_room(room_id, first)
        pubsub.aclose.assert_not_awaited()

        await broadcaster.unsubscribe_from_room(room_id, second)
        pubsub.unsubscribe.assert_awaited_once_with(channel)
        # The call that actually hands the connection back to the pool.
        pubsub.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_connected_users_returns_empty_on_redis_failure(self):
        from pecha_api.chat.chat_websocket import ChatBroadcaster

        broadcaster = ChatBroadcaster("redis://localhost:6379/0")
        broadcaster.redis = AsyncMock()
        broadcaster.redis.hgetall.side_effect = RuntimeError("redis down")

        assert await broadcaster.get_connected_users(uuid4()) == {}


class TestChatBroadcasterLifecycle:

    def test_get_broadcaster_raises_when_redis_connection_is_lost(self):
        from pecha_api.chat import chat_websocket

        disconnected = chat_websocket.ChatBroadcaster("redis://localhost:6379/0")

        with patch.object(chat_websocket, "broadcaster", disconnected):
            with pytest.raises(RuntimeError, match="Redis connection lost"):
                chat_websocket.get_broadcaster()

    def test_get_broadcaster_returns_connected_instance(self):
        from pecha_api.chat import chat_websocket

        connected = chat_websocket.ChatBroadcaster("redis://localhost:6379/0")
        connected.redis = AsyncMock()

        with patch.object(chat_websocket, "broadcaster", connected):
            assert chat_websocket.get_broadcaster() is connected

    @pytest.mark.asyncio
    async def test_init_broadcaster_connects_and_sets_the_global(self):
        from pecha_api.chat import chat_websocket
        from unittest.mock import MagicMock

        instance = MagicMock()
        instance.connect = AsyncMock()

        with patch.object(chat_websocket, "broadcaster", None), patch.object(
            chat_websocket, "ChatBroadcaster", return_value=instance
        ) as mock_cls:
            result = await chat_websocket.init_broadcaster("redis://localhost:6379/0")

            assert result is instance
            assert chat_websocket.broadcaster is instance
            mock_cls.assert_called_once_with("redis://localhost:6379/0")
            instance.connect.assert_awaited_once()

        assert chat_websocket.broadcaster is None
