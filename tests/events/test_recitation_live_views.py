import json
from contextlib import ExitStack, contextmanager
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette import status
from starlette.websockets import WebSocketDisconnect

from pecha_api.app import api

client = TestClient(api)


class MockUser:
    def __init__(self, user_id=None, email="user@example.com"):
        self.id = user_id or uuid4()
        self.email = email


class FakePubSub:
    def __init__(self, messages=None):
        self.messages = messages or []
        self.unsubscribed = []

    def listen(self):
        return self._listen()

    async def _listen(self):
        for message in self.messages:
            yield message

    async def unsubscribe(self, channel):
        self.unsubscribed.append(channel)


def _ws_url(event_id, token="test-token"):
    return f"/events/{event_id}/recitation/live?token={token}"


def _sync(websocket):
    """Wait until the server has handled everything sent so far: the receive
    loop handles frames in order, so a pong proves the earlier frames are done."""
    websocket.send_json({"type": "ping"})
    assert websocket.receive_json() == {"type": "pong"}


@contextmanager
def _ws_env(
    user=None,
    auth_error=None,
    access_error=None,
    is_operator=True,
    broadcaster=None,
    pubsub=None,
    position=None,
    allow_set=True,
):
    if broadcaster is None:
        broadcaster = AsyncMock()
    broadcaster.subscribe_to_event.return_value = pubsub if pubsub is not None else FakePubSub()
    broadcaster.get_position.return_value = position
    broadcaster.allow_set.return_value = allow_set

    with ExitStack() as stack:
        mock_validate = stack.enter_context(
            patch("pecha_api.events.recitation_live_views.validate_and_extract_user_details")
        )
        if auth_error is not None:
            mock_validate.side_effect = auth_error
        else:
            mock_validate.return_value = user or MockUser()

        stack.enter_context(
            patch("pecha_api.events.recitation_live_views.get_broadcaster", return_value=broadcaster)
        )
        mock_access = stack.enter_context(
            patch("pecha_api.events.recitation_live_views.resolve_recitation_access")
        )
        if access_error is not None:
            mock_access.side_effect = access_error
        else:
            mock_access.return_value = is_operator

        yield broadcaster, mock_access


class TestRecitationConnection:

    def test_closes_when_broadcaster_unavailable(self):
        with patch(
            "pecha_api.events.recitation_live_views.get_broadcaster",
            side_effect=RuntimeError("Redis down"),
        ):
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect(_ws_url(uuid4())):
                    pass

    def test_rejects_invalid_token(self):
        auth_error = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )
        with _ws_env(auth_error=auth_error) as (broadcaster, _):
            with client.websocket_connect(_ws_url(uuid4(), token="bad")) as websocket:
                message = websocket.receive_json()

        assert message["type"] == "error"
        assert message["code"] == "UNAUTHORIZED"
        broadcaster.add_connection.assert_not_awaited()

    def test_rejects_ineligible_subscriber(self):
        access_error = HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        with _ws_env(access_error=access_error) as (broadcaster, _):
            with client.websocket_connect(_ws_url(uuid4())) as websocket:
                message = websocket.receive_json()

        assert message["code"] == "Forbidden"
        broadcaster.add_connection.assert_not_awaited()

    def test_closes_for_unknown_event(self):
        access_error = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
        with _ws_env(access_error=access_error):
            with client.websocket_connect(_ws_url(uuid4())) as websocket:
                message = websocket.receive_json()

        assert message["code"] == "Not found"

    def test_non_string_error_detail_falls_back_to_generic_code(self):
        access_error = HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"field": "event_id"}
        )
        with _ws_env(access_error=access_error):
            with client.websocket_connect(_ws_url(uuid4())) as websocket:
                message = websocket.receive_json()

        assert message["code"] == "ERROR"

    def test_sends_session_info_and_tracks_connection(self):
        user = MockUser()
        event_id = uuid4()
        with _ws_env(user=user, is_operator=False) as (broadcaster, _):
            with client.websocket_connect(_ws_url(event_id)) as websocket:
                message = websocket.receive_json()
                _sync(websocket)

        assert message == {
            "type": "session_info",
            "event_id": str(event_id),
            "is_operator": False,
        }
        broadcaster.add_connection.assert_awaited_once()
        broadcaster.remove_connection.assert_awaited_once_with(event_id, user.id)

    def test_late_joiner_receives_current_position(self):
        event_id = uuid4()
        position = {
            "type": "position",
            "event_id": str(event_id),
            "segment_id": "seg-7",
            "index": 12,
            "round_number": 3,
            "server_time": "2026-09-14T09:30:00Z",
        }
        with _ws_env(position=position, is_operator=False):
            with client.websocket_connect(_ws_url(event_id)) as websocket:
                websocket.receive_json()
                assert websocket.receive_json() == position

    def test_no_position_frame_before_first_set(self):
        with _ws_env(position=None, is_operator=False):
            with client.websocket_connect(_ws_url(uuid4())) as websocket:
                websocket.receive_json()
                _sync(websocket)

    def test_relays_redis_frames_to_subscriber(self):
        event_id = uuid4()
        published = {
            "type": "position",
            "event_id": str(event_id),
            "segment_id": "seg-3",
            "index": 1,
            "round_number": None,
            "server_time": "2026-09-14T09:31:00Z",
        }
        pubsub = FakePubSub([{"type": "message", "data": json.dumps(published)}])
        with _ws_env(pubsub=pubsub, is_operator=False):
            with client.websocket_connect(_ws_url(event_id)) as websocket:
                websocket.receive_json()
                assert websocket.receive_json() == published

    def test_session_ended_frame_releases_the_socket(self):
        event_id = uuid4()
        ended = {"type": "session_ended", "event_id": str(event_id)}
        pubsub = FakePubSub([{"type": "message", "data": json.dumps(ended)}])
        with _ws_env(pubsub=pubsub, is_operator=False):
            with client.websocket_connect(_ws_url(event_id)) as websocket:
                websocket.receive_json()
                assert websocket.receive_json() == ended
                with pytest.raises(WebSocketDisconnect):
                    websocket.receive_json()


class TestOperatorPublishing:

    def test_operator_set_broadcasts_position(self):
        event_id = uuid4()
        with _ws_env(is_operator=True) as (broadcaster, _):
            with client.websocket_connect(_ws_url(event_id)) as websocket:
                websocket.receive_json()
                websocket.send_json({
                    "type": "set",
                    "segment_id": "seg-42",
                    "index": 12,
                    "round_number": 3,
                })
                _sync(websocket)

        kwargs = broadcaster.broadcast_position.await_args.kwargs
        assert kwargs["event_id"] == event_id
        assert kwargs["segment_id"] == "seg-42"
        assert kwargs["index"] == 12
        assert kwargs["round_number"] == 3
        assert kwargs["server_time"].endswith("Z")

    def test_set_without_optional_fields_is_accepted(self):
        with _ws_env(is_operator=True) as (broadcaster, _):
            with client.websocket_connect(_ws_url(uuid4())) as websocket:
                websocket.receive_json()
                websocket.send_json({"type": "set", "segment_id": "seg-1"})
                _sync(websocket)

        kwargs = broadcaster.broadcast_position.await_args.kwargs
        assert kwargs["index"] is None
        assert kwargs["round_number"] is None

    def test_subscriber_set_is_rejected_but_socket_survives(self):
        with _ws_env(is_operator=False) as (broadcaster, _):
            with client.websocket_connect(_ws_url(uuid4())) as websocket:
                websocket.receive_json()
                websocket.send_json({"type": "set", "segment_id": "seg-1"})
                message = websocket.receive_json()
                _sync(websocket)

        assert message["type"] == "error"
        assert message["code"] == "FORBIDDEN"
        broadcaster.broadcast_position.assert_not_awaited()

    def test_invalid_set_frame_returns_validation_error(self):
        with _ws_env(is_operator=True) as (broadcaster, _):
            with client.websocket_connect(_ws_url(uuid4())) as websocket:
                websocket.receive_json()
                websocket.send_json({"type": "set", "segment_id": "   "})
                message = websocket.receive_json()
                _sync(websocket)

        assert message["code"] == "VALIDATION_ERROR"
        broadcaster.broadcast_position.assert_not_awaited()

    def test_negative_round_number_is_rejected(self):
        with _ws_env(is_operator=True) as (broadcaster, _):
            with client.websocket_connect(_ws_url(uuid4())) as websocket:
                websocket.receive_json()
                websocket.send_json({"type": "set", "segment_id": "seg-1", "round_number": 0})
                message = websocket.receive_json()
                _sync(websocket)

        assert message["code"] == "VALIDATION_ERROR"
        broadcaster.broadcast_position.assert_not_awaited()

    def test_throttled_set_is_dropped_silently(self):
        with _ws_env(is_operator=True, allow_set=False) as (broadcaster, _):
            with client.websocket_connect(_ws_url(uuid4())) as websocket:
                websocket.receive_json()
                websocket.send_json({"type": "set", "segment_id": "seg-1"})
                _sync(websocket)

        broadcaster.broadcast_position.assert_not_awaited()

    def test_broadcast_failure_reports_server_error(self):
        broadcaster = AsyncMock()
        broadcaster.allow_set.return_value = True
        broadcaster.broadcast_position.side_effect = Exception("redis down")
        with _ws_env(is_operator=True, broadcaster=broadcaster):
            with client.websocket_connect(_ws_url(uuid4())) as websocket:
                websocket.receive_json()
                websocket.send_json({"type": "set", "segment_id": "seg-1"})
                message = websocket.receive_json()

        assert message["code"] == "SERVER_ERROR"

    def test_operator_end_clears_and_broadcasts(self):
        event_id = uuid4()
        with _ws_env(is_operator=True) as (broadcaster, _):
            with client.websocket_connect(_ws_url(event_id)) as websocket:
                websocket.receive_json()
                websocket.send_json({"type": "end"})
                _sync(websocket)

        broadcaster.clear_position.assert_awaited_once_with(event_id)
        broadcaster.broadcast_session_ended.assert_awaited_once_with(event_id)

    def test_subscriber_end_is_rejected(self):
        with _ws_env(is_operator=False) as (broadcaster, _):
            with client.websocket_connect(_ws_url(uuid4())) as websocket:
                websocket.receive_json()
                websocket.send_json({"type": "end"})
                message = websocket.receive_json()

        assert message["code"] == "FORBIDDEN"
        broadcaster.broadcast_session_ended.assert_not_awaited()

    def test_unknown_frame_types_are_ignored(self):
        with _ws_env(is_operator=True) as (broadcaster, _):
            with client.websocket_connect(_ws_url(uuid4())) as websocket:
                websocket.receive_json()
                websocket.send_json({"type": "nonsense"})
                websocket.send_json([1, 2, 3])
                _sync(websocket)

        broadcaster.broadcast_position.assert_not_awaited()

    def test_unsubscribes_on_disconnect(self):
        event_id = uuid4()
        pubsub = FakePubSub()
        with _ws_env(pubsub=pubsub, is_operator=True):
            with client.websocket_connect(_ws_url(event_id)) as websocket:
                websocket.receive_json()
                _sync(websocket)

        assert pubsub.unsubscribed == [f"recitation:event:{event_id}:position"]
