import json
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone as tz
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette import status
from starlette.websockets import WebSocketDisconnect

from pecha_api.app import api
from pecha_api.chat.response_models import ChatMessageDTO

client = TestClient(api)


class MockUser:
    def __init__(self, user_id=None, email="user@example.com"):
        self.id = user_id or uuid4()
        self.email = email


class FakePubSub:
    def __init__(self, messages=None, listen_error=None, unsubscribe_error=None):
        self.messages = messages or []
        self.listen_error = listen_error
        self.unsubscribe_error = unsubscribe_error
        self.unsubscribed = []

    def listen(self):
        return self._listen()

    async def _listen(self):
        if self.listen_error is not None:
            raise self.listen_error
        for message in self.messages:
            yield message

    async def unsubscribe(self, channel):
        self.unsubscribed.append(channel)
        if self.unsubscribe_error is not None:
            raise self.unsubscribe_error


def _message_dto(room_id=None) -> ChatMessageDTO:
    return ChatMessageDTO(
        id=uuid4(),
        room_id=room_id or uuid4(),
        sender_id=uuid4(),
        sender_email="sender@example.com",
        sender_name="Sender Name",
        body="Hello",
        created_at=datetime.now(tz.utc).isoformat(),
    )


def _ws_url(group_id=None, receiver_id=None, event_id=None, token="test-token"):
    if group_id is not None:
        return f"/chat/live?token={token}&group_id={group_id}"
    if event_id is not None:
        return f"/chat/live?token={token}&event_id={event_id}"
    if receiver_id is not None:
        return f"/chat/live?token={token}&receiver_id={receiver_id}"
    return f"/chat/live?token={token}"


@contextmanager
def _websocket_env(
    user=None,
    auth_error=None,
    broadcaster=None,
    pubsub=None,
    room=None,
    resolve_error=None,
):
    if broadcaster is None:
        broadcaster = AsyncMock()
    broadcaster.subscribe_to_room.return_value = pubsub if pubsub is not None else FakePubSub()

    resolved_room = room or MagicMock(id=uuid4())

    with ExitStack() as stack:
        mock_validate = stack.enter_context(
            patch("pecha_api.chat.views.validate_and_extract_user_details")
        )
        if auth_error is not None:
            mock_validate.side_effect = auth_error
        else:
            mock_validate.return_value = user or MockUser()

        stack.enter_context(
            patch("pecha_api.chat.views.get_broadcaster", return_value=broadcaster)
        )
        stack.enter_context(patch("pecha_api.db.database.SessionLocal"))

        mock_group = stack.enter_context(
            patch("pecha_api.chat.service.resolve_or_create_group_room", return_value=resolved_room)
        )
        mock_private = stack.enter_context(
            patch("pecha_api.chat.service.resolve_or_create_private_room", return_value=resolved_room)
        )
        if resolve_error is not None:
            mock_group.side_effect = resolve_error
            mock_private.side_effect = resolve_error

        stack.enter_context(patch("pecha_api.chat.service._require_active_member"))
        mock_send_group = stack.enter_context(
            patch("pecha_api.chat.views.send_group_message_service")
        )
        mock_send_direct = stack.enter_context(
            patch("pecha_api.chat.views.send_direct_message_service")
        )
        yield broadcaster, mock_send_group, mock_send_direct, resolved_room


class TestWebSocketChatConnection:

    def test_rejects_missing_group_and_receiver(self):
        with client.websocket_connect(_ws_url()) as websocket:
            message = websocket.receive_json()

        assert message["type"] == "error"
        assert message["code"] == "INVALID_PARAMS"

    def test_rejects_both_group_and_receiver(self):
        url = f"/chat/live?token=test&group_id={uuid4()}&receiver_id={uuid4()}"
        with client.websocket_connect(url) as websocket:
            message = websocket.receive_json()

        assert message["code"] == "INVALID_PARAMS"

    def test_closes_when_broadcaster_unavailable(self):
        with patch(
            "pecha_api.chat.views.get_broadcaster",
            side_effect=RuntimeError("Redis down"),
        ):
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect(_ws_url(group_id=uuid4())):
                    pass

    def test_rejects_invalid_token(self):
        auth_error = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )
        with _websocket_env(auth_error=auth_error) as (broadcaster, *_):
            with client.websocket_connect(_ws_url(group_id=uuid4(), token="bad")) as websocket:
                message = websocket.receive_json()

        assert message["type"] == "error"
        assert message["code"] == "UNAUTHORIZED"
        broadcaster.add_connection.assert_not_awaited()

    def test_closes_when_room_resolve_fails(self):
        resolve_error = HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        with _websocket_env(resolve_error=resolve_error) as (broadcaster, *_):
            with client.websocket_connect(_ws_url(group_id=uuid4())) as websocket:
                message = websocket.receive_json()

        assert message["type"] == "error"
        assert message["code"] == "Forbidden"
        broadcaster.add_connection.assert_not_awaited()

    def test_closes_when_resolve_error_detail_is_not_string(self):
        resolve_error = HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"field": "group_id"},
        )
        with _websocket_env(resolve_error=resolve_error):
            with client.websocket_connect(_ws_url(group_id=uuid4())) as websocket:
                message = websocket.receive_json()

        assert message["code"] == "ERROR"

    def test_registers_and_unregisters_group_connection(self):
        user = MockUser()
        room = MagicMock(id=uuid4())
        pubsub = FakePubSub()

        with _websocket_env(user=user, room=room, pubsub=pubsub) as (broadcaster, *_):
            with client.websocket_connect(_ws_url(group_id=uuid4())) as websocket:
                info = websocket.receive_json()

        assert info == {"type": "room_info", "room_id": str(room.id)}
        broadcaster.add_connection.assert_awaited_once()
        assert broadcaster.add_connection.await_args.args[:3] == (room.id, user.id, user.email)
        broadcaster.broadcast_presence.assert_awaited()
        broadcaster.remove_connection.assert_awaited_once_with(room.id, user.id)
        assert pubsub.unsubscribed == [f"chat:room:{room.id}:messages"]

    def test_registers_dm_connection(self):
        room = MagicMock(id=uuid4())
        with _websocket_env(room=room) as (broadcaster, *_):
            with client.websocket_connect(_ws_url(receiver_id=uuid4())) as websocket:
                info = websocket.receive_json()

        assert info["room_id"] == str(room.id)
        broadcaster.subscribe_to_room.assert_awaited_once_with(room.id)

    def test_unsubscribe_failure_is_swallowed(self):
        pubsub = FakePubSub(unsubscribe_error=RuntimeError("redis gone"))

        with _websocket_env(pubsub=pubsub):
            with client.websocket_connect(_ws_url(group_id=uuid4())) as websocket:
                websocket.receive_json()

        assert len(pubsub.unsubscribed) == 1


class TestWebSocketChatRedisStream:

    def test_forwards_published_messages_to_client(self):
        payload = json.dumps({"type": "message_created", "message": {"body": "from redis"}})
        pubsub = FakePubSub(
            messages=[
                {"type": "subscribe", "data": 1},
                {"type": "message", "data": payload},
            ]
        )

        with _websocket_env(pubsub=pubsub):
            with client.websocket_connect(_ws_url(group_id=uuid4())) as websocket:
                assert websocket.receive_json()["type"] == "room_info"
                assert websocket.receive_text() == payload

    def test_redis_listen_failure_does_not_break_connection(self):
        pubsub = FakePubSub(listen_error=RuntimeError("pubsub exploded"))

        with _websocket_env(pubsub=pubsub) as (_, mock_send_group, *_):
            with client.websocket_connect(_ws_url(group_id=uuid4())) as websocket:
                websocket.receive_json()
                websocket.send_json({"type": "ping"})
                assert websocket.receive_json()["code"] == "INVALID_MESSAGE"

        mock_send_group.assert_not_called()


class TestWebSocketChatMessages:

    def test_rejects_unsupported_message_type(self):
        with _websocket_env() as (_, mock_send_group, mock_send_direct, _):
            with client.websocket_connect(_ws_url(group_id=uuid4())) as websocket:
                websocket.receive_json()
                websocket.send_json({"type": "reaction"})
                message = websocket.receive_json()

        assert message["type"] == "error"
        assert message["code"] == "INVALID_MESSAGE"
        mock_send_group.assert_not_called()
        mock_send_direct.assert_not_called()

    def test_sends_and_broadcasts_group_message(self):
        group_id = uuid4()
        user = MockUser()
        room = MagicMock(id=uuid4())
        dto = _message_dto(room.id)

        with _websocket_env(user=user, room=room) as (broadcaster, mock_send_group, _, _):
            mock_send_group.return_value = dto
            with client.websocket_connect(_ws_url(group_id=group_id)) as websocket:
                websocket.receive_json()
                websocket.send_json({"type": "message", "body": "Hello"})

        mock_send_group.assert_called_once_with(
            group_id=group_id,
            user=user,
            body="Hello",
            parent_message_id=None,
            message_type="TEXT",
        )
        broadcaster.broadcast_message.assert_awaited_once_with(room.id, dto)

    def test_sends_and_broadcasts_direct_message(self):
        receiver_id = uuid4()
        user = MockUser()
        room = MagicMock(id=uuid4())
        dto = _message_dto(room.id)

        with _websocket_env(user=user, room=room) as (broadcaster, _, mock_send_direct, _):
            mock_send_direct.return_value = dto
            with client.websocket_connect(_ws_url(receiver_id=receiver_id)) as websocket:
                websocket.receive_json()
                websocket.send_json({"type": "message", "body": "Hey"})

        mock_send_direct.assert_called_once_with(
            receiver_id=receiver_id,
            user=user,
            body="Hey",
            parent_message_id=None,
            message_type="TEXT",
        )
        broadcaster.broadcast_message.assert_awaited_once_with(room.id, dto)

    def test_reports_message_send_failure(self):
        with _websocket_env() as (broadcaster, mock_send_group, _, _):
            mock_send_group.side_effect = HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden"
            )
            with client.websocket_connect(_ws_url(group_id=uuid4())) as websocket:
                websocket.receive_json()
                websocket.send_json({"type": "message", "body": "Hello"})
                message = websocket.receive_json()

        assert message["type"] == "error"
        assert message["code"] == "Forbidden"
        broadcaster.broadcast_message.assert_not_awaited()

    def test_reports_non_string_send_failure_detail(self):
        with _websocket_env() as (_, mock_send_group, _, _):
            mock_send_group.side_effect = HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"field": "body"},
            )
            with client.websocket_connect(_ws_url(group_id=uuid4())) as websocket:
                websocket.receive_json()
                websocket.send_json({"type": "message", "body": "Hello"})
                message = websocket.receive_json()

        assert message["code"] == "ERROR"
        assert "body" in message["message"]

    def test_reports_broadcast_failure(self):
        room = MagicMock(id=uuid4())
        dto = _message_dto(room.id)

        with _websocket_env(room=room) as (broadcaster, mock_send_group, _, _):
            mock_send_group.return_value = dto
            broadcaster.broadcast_message.side_effect = RuntimeError("redis publish failed")
            with client.websocket_connect(_ws_url(group_id=uuid4())) as websocket:
                websocket.receive_json()
                websocket.send_json({"type": "message", "body": "Hello"})
                message = websocket.receive_json()

        assert message["type"] == "error"
        assert message["code"] == "BROADCAST_ERROR"
        assert "redis publish failed" in message["message"]

    def test_broadcasts_typing_indicator(self):
        user = MockUser()
        room = MagicMock(id=uuid4())

        with _websocket_env(user=user, room=room) as (broadcaster, *_):
            with client.websocket_connect(_ws_url(group_id=uuid4())) as websocket:
                websocket.receive_json()
                websocket.send_json({"type": "typing", "is_typing": True})

        broadcaster.broadcast_typing.assert_awaited_once_with(
            room.id, user.id, user.email, is_typing=True
        )

    def test_reports_typing_membership_failure(self):
        with _websocket_env() as (broadcaster, *_):
            with patch(
                "pecha_api.chat.service._require_active_member",
                side_effect=HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden"),
            ):
                with client.websocket_connect(_ws_url(group_id=uuid4())) as websocket:
                    websocket.receive_json()
                    websocket.send_json({"type": "typing", "is_typing": True})
                    message = websocket.receive_json()

        assert message["type"] == "error"
        assert message["code"] == "Forbidden"
        broadcaster.broadcast_typing.assert_not_awaited()

    def test_typing_broadcast_failure_is_logged_not_raised(self):
        with _websocket_env() as (broadcaster, *_):
            broadcaster.broadcast_typing.side_effect = RuntimeError("redis down")
            with client.websocket_connect(_ws_url(group_id=uuid4())) as websocket:
                websocket.receive_json()
                websocket.send_json({"type": "typing", "is_typing": False})
                websocket.send_json({"type": "ping"})
                assert websocket.receive_json()["code"] == "INVALID_MESSAGE"


class TestHiddenGroupEndsLiveSession:
    """A group hidden after a socket opened must stop that socket's live
    traffic, rather than leaving typing and presence flowing in a group the
    app can no longer reach."""

    def test_typing_stops_when_room_unreachable(self):
        with _websocket_env() as (broadcaster, *_):
            with patch(
                "pecha_api.chat.service._get_room_or_404",
                side_effect=HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Not found"
                ),
            ):
                with pytest.raises(WebSocketDisconnect):
                    with client.websocket_connect(_ws_url(group_id=uuid4())) as websocket:
                        websocket.receive_json()
                        websocket.send_json({"type": "typing", "is_typing": True})
                        assert websocket.receive_json()["type"] == "error"
                        # Session ended: nothing further is served.
                        websocket.receive_json()

            broadcaster.broadcast_typing.assert_not_awaited()

    def test_send_404_ends_session(self):
        with _websocket_env() as (_broadcaster, mock_send_group, *_):
            mock_send_group.side_effect = HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Not found"
            )
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect(_ws_url(group_id=uuid4())) as websocket:
                    websocket.receive_json()
                    websocket.send_json({"type": "message", "body": "hi"})
                    assert websocket.receive_json()["type"] == "error"
                    websocket.receive_json()

    def test_per_message_rejection_keeps_socket_open(self):
        """Regression guard: profanity and similar per-message rejections must
        not end the session."""
        with _websocket_env() as (_broadcaster, mock_send_group, *_):
            mock_send_group.side_effect = HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "INAPPROPRIATE_LANGUAGE", "message": "no"},
            )
            with client.websocket_connect(_ws_url(group_id=uuid4())) as websocket:
                websocket.receive_json()
                websocket.send_json({"type": "message", "body": "bad"})
                assert websocket.receive_json()["code"] == "INAPPROPRIATE_LANGUAGE"

                websocket.send_json({"type": "ping"})
                assert websocket.receive_json()["code"] == "INVALID_MESSAGE"


class TestRemoteEviction:
    """Hiding a group publishes room_closed, which every server holding a
    socket for that room acts on — this is what makes eviction work when more
    than one server is running."""

    def test_room_closed_event_ends_the_session(self):
        pubsub = FakePubSub(messages=[
            {"type": "message", "data": json.dumps({"type": "room_closed", "reason": "GROUP_UNPUBLISHED"})},
        ])
        with _websocket_env(pubsub=pubsub):
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect(_ws_url(group_id=uuid4())) as websocket:
                    websocket.receive_json()   # room_info
                    websocket.receive_json()   # room_closed, forwarded to the client
                    websocket.receive_json()   # session over

    def test_ordinary_events_do_not_end_the_session(self):
        """Regression guard: only room_closed evicts."""
        pubsub = FakePubSub(messages=[
            {"type": "message", "data": json.dumps({"type": "typing", "user_id": str(uuid4())})},
        ])
        with _websocket_env(pubsub=pubsub):
            with client.websocket_connect(_ws_url(group_id=uuid4())) as websocket:
                websocket.receive_json()
                assert websocket.receive_json()["type"] == "typing"

                websocket.send_json({"type": "ping"})
                assert websocket.receive_json()["code"] == "INVALID_MESSAGE"


class TestWebSocketEventRoomsAndPrayers:
    """The socket's third room kind, and the PRAYER message type."""

    def test_rejects_group_and_event_together(self):
        url = f"/chat/live?token=test&group_id={uuid4()}&event_id={uuid4()}"
        with client.websocket_connect(url) as websocket:
            message = websocket.receive_json()

        assert message["code"] == "INVALID_PARAMS"

    def test_connects_to_an_event_room(self):
        event_id = uuid4()
        user = MockUser()
        room = MagicMock(id=uuid4())

        with _websocket_env(user=user, room=room):
            with patch(
                "pecha_api.chat.service.resolve_or_create_event_room",
                return_value=room,
            ) as mock_resolve:
                with client.websocket_connect(_ws_url(event_id=event_id)) as websocket:
                    message = websocket.receive_json()

        assert message["type"] == "room_info"
        assert message["room_id"] == str(room.id)
        assert mock_resolve.call_args.kwargs["event_id"] == event_id

    def test_sends_an_event_message(self):
        event_id = uuid4()
        user = MockUser()
        room = MagicMock(id=uuid4())
        dto = _message_dto(room.id)

        with _websocket_env(user=user, room=room) as (broadcaster, _, _, _):
            with patch(
                "pecha_api.chat.service.resolve_or_create_event_room",
                return_value=room,
            ), patch(
                "pecha_api.chat.views.send_event_message_service",
                return_value=dto,
            ) as mock_send_event:
                with client.websocket_connect(_ws_url(event_id=event_id)) as websocket:
                    websocket.receive_json()
                    websocket.send_json({"type": "message", "body": "Tashi delek"})

        mock_send_event.assert_called_once_with(
            event_id=event_id,
            user=user,
            body="Tashi delek",
            parent_message_id=None,
            message_type="TEXT",
        )
        broadcaster.broadcast_message.assert_awaited_once_with(room.id, dto)

    def test_sends_a_prayer_request(self):
        group_id = uuid4()
        user = MockUser()
        room = MagicMock(id=uuid4())
        dto = _message_dto(room.id)

        with _websocket_env(user=user, room=room) as (_, mock_send_group, _, _):
            mock_send_group.return_value = dto
            with client.websocket_connect(_ws_url(group_id=group_id)) as websocket:
                websocket.receive_json()
                websocket.send_json(
                    {
                        "type": "message",
                        "body": "Please pray for my mother",
                        "message_type": "PRAYER",
                    }
                )

        assert mock_send_group.call_args.kwargs["message_type"] == "PRAYER"

    def test_message_type_is_normalised_to_upper_case(self):
        group_id = uuid4()
        room = MagicMock(id=uuid4())
        dto = _message_dto(room.id)

        with _websocket_env(room=room) as (_, mock_send_group, _, _):
            mock_send_group.return_value = dto
            with client.websocket_connect(_ws_url(group_id=group_id)) as websocket:
                websocket.receive_json()
                websocket.send_json(
                    {"type": "message", "body": "hi", "message_type": "prayer"}
                )

        assert mock_send_group.call_args.kwargs["message_type"] == "PRAYER"

    def test_rejected_message_type_keeps_the_socket_usable(self):
        """A per-message rejection must not end the session, the way a
        profanity rejection does not."""
        group_id = uuid4()
        room = MagicMock(id=uuid4())

        with _websocket_env(room=room) as (_, mock_send_group, _, _):
            mock_send_group.side_effect = HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="PRAYER_NOT_ALLOWED_IN_DM",
            )
            with client.websocket_connect(_ws_url(group_id=group_id)) as websocket:
                websocket.receive_json()
                websocket.send_json(
                    {"type": "message", "body": "hi", "message_type": "PRAYER"}
                )
                error = websocket.receive_json()
                # Still open: a second frame is still served.
                websocket.send_json({"type": "typing", "is_typing": True})

        assert error["type"] == "error"
        assert error["code"] == "PRAYER_NOT_ALLOWED_IN_DM"
