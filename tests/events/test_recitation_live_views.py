import json
from contextlib import ExitStack, contextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette import status
from starlette.websockets import WebSocketDisconnect

from pecha_api.app import api
from pecha_api.events.recitation_live_service import (
    RecitationCaller,
    resolve_recitation_access,
)

client = TestClient(api)

SERVICE = "pecha_api.events.recitation_live_service"


class MockUser:
    def __init__(self, user_id=None, email="user@example.com"):
        self.id = user_id or uuid4()
        self.email = email


class FakeSubscriber:
    """Stands in for realtime.channel_fanout.Subscriber.

    Takes pubsub-shaped messages so the cases below still read as published
    frames; filtering non-message frames is the fanout's job in production.
    Returns None once drained, which is how a subscriber reports that the
    channel stopped.
    """

    def __init__(self, messages=None, dropped=0):
        self.messages = list(messages or [])
        self._index = 0
        self._dropped = dropped

    async def get(self):
        while self._index < len(self.messages):
            message = self.messages[self._index]
            self._index += 1
            if message.get("type") == "message":
                return message["data"]
        return None

    def take_dropped(self):
        dropped = self._dropped
        self._dropped = 0
        return dropped


def _ws_url(event_id, token="test-token"):
    """`token=None` opens the socket the way a signed-out page does: no query
    parameter at all."""
    if token is None:
        return f"/events/{event_id}/recitation/live"
    return f"/events/{event_id}/recitation/live?token={token}"


def _sync(websocket):
    """Wait until the server has handled everything sent so far: the receive
    loop handles frames in order, so a pong proves the earlier frames are done."""
    websocket.send_json({"type": "ping"})
    assert websocket.receive_json() == {"type": "pong"}


@contextmanager
def _ws_env(
    user=None,
    caller=None,
    auth_error=None,
    access_error=None,
    event_error=None,
    is_operator=True,
    broadcaster=None,
    subscriber=None,
    position=None,
    allow_set=True,
):
    if broadcaster is None:
        broadcaster = AsyncMock()
    # Local dict bookkeeping, not I/O, so these are plain sync methods.
    broadcaster.add_connection = MagicMock()
    broadcaster.remove_connection = MagicMock()
    broadcaster.mark_present.return_value = "presence-token"
    broadcaster.presence_count.return_value = 1
    broadcaster.broadcast_presence.return_value = 1
    broadcaster.subscribe_to_event.return_value = (
        subscriber if subscriber is not None else FakeSubscriber()
    )
    broadcaster.get_position.return_value = position
    broadcaster.allow_set.return_value = allow_set

    with ExitStack() as stack:
        mock_validate = stack.enter_context(
            patch("pecha_api.events.recitation_live_views.resolve_recitation_caller")
        )
        if auth_error is not None:
            mock_validate.side_effect = auth_error
        elif caller is not None:
            mock_validate.return_value = caller
        else:
            # An app user: one identity is both the roster key and the User.
            resolved = user or MockUser()
            mock_validate.return_value = RecitationCaller(
                presence_id=resolved.id, user_id=resolved.id
            )

        stack.enter_context(
            patch("pecha_api.events.recitation_live_views.get_broadcaster", return_value=broadcaster)
        )
        # Play times are measured in the background and have their own tests.
        stack.enter_context(
            patch(
                "pecha_api.events.recitation_live_views.record_segment_play_time",
                new=AsyncMock(),
            )
        )
        mock_access = stack.enter_context(
            patch("pecha_api.events.recitation_live_views.resolve_recitation_access")
        )
        if access_error is not None:
            mock_access.side_effect = access_error
        else:
            mock_access.return_value = is_operator
        # What a socket with no token is checked against, in place of the two
        # above. Kept on the broadcaster, as the caller lookup is, so every
        # existing test keeps unpacking the same pair.
        broadcaster.live_event = stack.enter_context(
            patch("pecha_api.events.recitation_live_views.assert_live_event")
        )
        if event_error is not None:
            broadcaster.live_event.side_effect = event_error
        broadcaster.caller = mock_validate

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
                with pytest.raises(WebSocketDisconnect) as closed:
                    websocket.receive_json()

        assert message["type"] == "error"
        assert message["code"] == "UNAUTHORIZED"
        assert closed.value.code == status.WS_1008_POLICY_VIOLATION
        broadcaster.add_connection.assert_not_called()
        # Refused outright, not let in as a signed-out viewer: the client is
        # the one that decides to reconnect without its token.
        broadcaster.live_event.assert_not_called()

    def test_signed_in_non_member_can_follow(self):
        """Following a published group's puja asks for no join or follow, so a
        signed-in user in no relation to the group lands as a viewer - through
        the real access check, not a stubbed one."""
        user = MockUser()
        event_id = uuid4()
        with _ws_env(user=user) as (broadcaster, mock_access), \
             patch("pecha_api.db.database.SessionLocal"), \
             patch(f"{SERVICE}.load_live_event", return_value=MagicMock(group_id=uuid4())), \
             patch(f"{SERVICE}.is_event_operator", return_value=False):
            mock_access.side_effect = resolve_recitation_access
            with client.websocket_connect(_ws_url(event_id)) as websocket:
                message = websocket.receive_json()
                _sync(websocket)

        assert message == {
            "type": "session_info",
            "event_id": str(event_id),
            "is_operator": False,
            "count": 1,
        }
        broadcaster.mark_present.assert_awaited_once_with(event_id, user.id)

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
            "count": 1,
        }
        broadcaster.add_connection.assert_called_once()
        broadcaster.mark_present.assert_awaited_once_with(event_id, user.id)
        broadcaster.mark_absent.assert_awaited_once_with(event_id, user.id, "presence-token")
        broadcaster.remove_connection.assert_called_once_with(event_id, user.id)

    def test_studio_author_joins_without_a_website_user(self):
        """The Studio event page signs in as an Author, not an app user. It
        still has to reach the socket, or the page reports it cannot join."""
        author_id = uuid4()
        event_id = uuid4()
        caller = RecitationCaller(presence_id=author_id, user_id=None)
        with _ws_env(caller=caller, is_operator=True) as (broadcaster, mock_access):
            with client.websocket_connect(_ws_url(event_id)) as websocket:
                message = websocket.receive_json()
                _sync(websocket)

        assert message["type"] == "session_info"
        assert message["is_operator"] is True
        # Operator rights are decided by the token alone; there is no app
        # identity behind it to pass along.
        assert mock_access.call_args.kwargs == {"event_id": event_id, "token": "test-token"}
        broadcaster.mark_present.assert_awaited_once_with(event_id, author_id)
        broadcaster.remove_connection.assert_called_once_with(event_id, author_id)

    def test_late_joiner_receives_current_position(self):
        event_id = uuid4()
        position = {
            "type": "position",
            "event_id": str(event_id),
            "text_id": "text-7",
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
            "text_id": "text-7",
            "segment_id": "seg-3",
            "index": 1,
            "round_number": None,
            "server_time": "2026-09-14T09:31:00Z",
        }
        subscriber = FakeSubscriber([{"type": "message", "data": json.dumps(published)}])
        with _ws_env(subscriber=subscriber, is_operator=False):
            with client.websocket_connect(_ws_url(event_id)) as websocket:
                websocket.receive_json()
                assert websocket.receive_json() == published

    def test_join_count_is_the_one_announced_to_the_room(self):
        """session_info must quote the broadcast's own reading. A separate count
        can disagree with the number every other phone was just handed."""
        event_id = uuid4()
        with _ws_env(is_operator=False) as (broadcaster, _):
            broadcaster.broadcast_presence.return_value = 4
            broadcaster.presence_count.return_value = 99
            with client.websocket_connect(_ws_url(event_id)) as websocket:
                message = websocket.receive_json()
                _sync(websocket)

        assert message["count"] == 4
        broadcaster.broadcast_presence.assert_awaited_with(event_id)

    def test_a_dropped_frame_resyncs_the_count(self):
        """Presence shares the queue with positions, and a socket that falls
        behind has its oldest frames evicted. Losing the count that way would
        leave this client showing an old number for the rest of the puja."""
        event_id = uuid4()
        position = {
            "type": "position",
            "event_id": str(event_id),
            "text_id": "text-7",
            "segment_id": "seg-9",
            "index": 9,
            "round_number": 1,
            "server_time": "2026-09-14T09:30:05Z",
            "revision": 58,
        }
        subscriber = FakeSubscriber(
            [{"type": "message", "data": json.dumps(position)}], dropped=3
        )

        with _ws_env(subscriber=subscriber, is_operator=False) as (broadcaster, _):
            broadcaster.presence_count.return_value = 7
            with client.websocket_connect(_ws_url(event_id)) as websocket:
                websocket.receive_json()                        # session_info
                assert websocket.receive_json() == position
                assert websocket.receive_json() == {
                    "type": "presence",
                    "event_id": str(event_id),
                    "count": 7,
                }

    def test_no_resync_when_nothing_was_dropped(self):
        event_id = uuid4()
        published = {
            "type": "presence",
            "event_id": str(event_id),
            "count": 2,
        }
        subscriber = FakeSubscriber([{"type": "message", "data": json.dumps(published)}])

        with _ws_env(subscriber=subscriber, is_operator=False) as (broadcaster, _):
            with client.websocket_connect(_ws_url(event_id)) as websocket:
                websocket.receive_json()
                assert websocket.receive_json() == published
                _sync(websocket)

        broadcaster.presence_count.assert_not_awaited()

    def test_queued_frames_older_than_the_snapshot_are_dropped(self):
        """Frames published between subscribe and the snapshot read are already
        queued, and the snapshot can be newer than some of them. Relaying those
        would scroll the room backwards before it caught up."""
        event_id = uuid4()
        snapshot = {
            "type": "position",
            "event_id": str(event_id),
            "text_id": "text-7",
            "segment_id": "seg-newest",
            "index": 9,
            "round_number": 1,
            "server_time": "2026-09-14T09:30:05Z",
            "revision": 57,
        }
        stale = {**snapshot, "segment_id": "seg-older", "index": 4, "revision": 55}
        fresh = {**snapshot, "segment_id": "seg-next", "index": 10, "revision": 58}
        subscriber = FakeSubscriber([
            {"type": "message", "data": json.dumps(stale)},
            {"type": "message", "data": json.dumps(fresh)},
        ])

        with _ws_env(subscriber=subscriber, position=snapshot, is_operator=False):
            with client.websocket_connect(_ws_url(event_id)) as websocket:
                websocket.receive_json()                      # session_info
                assert websocket.receive_json() == snapshot   # connect-time position
                assert websocket.receive_json() == fresh      # stale one skipped

    def test_ordering_ignores_wall_clocks(self):
        """A frame stamped by another instance can carry an earlier clock time
        and still be newer. The revision is what decides."""
        event_id = uuid4()
        snapshot = {
            "type": "position",
            "event_id": str(event_id),
            "text_id": "text-7",
            "segment_id": "seg-1",
            "index": 1,
            "round_number": None,
            "server_time": "2026-09-14T09:30:05Z",
            "revision": 57,
        }
        # Older clock, higher revision: a skewed instance published it later.
        skewed = {**snapshot, "segment_id": "seg-2", "index": 2,
                  "server_time": "2026-09-14T09:29:59Z", "revision": 58}
        subscriber = FakeSubscriber([{"type": "message", "data": json.dumps(skewed)}])

        with _ws_env(subscriber=subscriber, position=snapshot, is_operator=False):
            with client.websocket_connect(_ws_url(event_id)) as websocket:
                websocket.receive_json()
                assert websocket.receive_json() == snapshot
                assert websocket.receive_json() == skewed

    def test_unnumbered_frames_are_relayed(self):
        """During a rolling deploy an instance may still publish without a
        revision. Unorderable is not a reason to drop the live position."""
        event_id = uuid4()
        snapshot = {
            "type": "position",
            "event_id": str(event_id),
            "text_id": "text-7",
            "segment_id": "seg-1",
            "index": 1,
            "round_number": None,
            "server_time": "2026-09-14T09:30:05Z",
            "revision": 57,
        }
        unnumbered = {**snapshot, "segment_id": "seg-2", "revision": None}
        subscriber = FakeSubscriber([{"type": "message", "data": json.dumps(unnumbered)}])

        with _ws_env(subscriber=subscriber, position=snapshot, is_operator=False):
            with client.websocket_connect(_ws_url(event_id)) as websocket:
                websocket.receive_json()
                assert websocket.receive_json() == snapshot
                assert websocket.receive_json() == unnumbered

    def test_duplicate_of_the_snapshot_is_not_relayed(self):
        """The snapshot is written before its own publish, so a connect landing
        between the two sees the same position twice."""
        event_id = uuid4()
        snapshot = {
            "type": "position",
            "event_id": str(event_id),
            "text_id": "text-7",
            "segment_id": "seg-1",
            "index": 1,
            "round_number": None,
            "server_time": "2026-09-14T09:30:05Z",
            "revision": 57,
        }
        later = {**snapshot, "segment_id": "seg-2", "revision": 58}
        subscriber = FakeSubscriber([
            {"type": "message", "data": json.dumps(snapshot)},
            {"type": "message", "data": json.dumps(later)},
        ])

        with _ws_env(subscriber=subscriber, position=snapshot, is_operator=False):
            with client.websocket_connect(_ws_url(event_id)) as websocket:
                websocket.receive_json()
                assert websocket.receive_json() == snapshot
                assert websocket.receive_json() == later

    def test_frames_relay_normally_when_no_snapshot_exists(self):
        event_id = uuid4()
        first = {
            "type": "position",
            "event_id": str(event_id),
            "text_id": "text-7",
            "segment_id": "seg-1",
            "index": 0,
            "round_number": None,
            "server_time": "2026-09-14T09:30:01Z",
            "revision": 1,
        }
        subscriber = FakeSubscriber([{"type": "message", "data": json.dumps(first)}])

        with _ws_env(subscriber=subscriber, position=None, is_operator=False):
            with client.websocket_connect(_ws_url(event_id)) as websocket:
                websocket.receive_json()
                assert websocket.receive_json() == first

    def test_session_ended_frame_releases_the_socket(self):
        event_id = uuid4()
        ended = {"type": "session_ended", "event_id": str(event_id)}
        subscriber = FakeSubscriber([{"type": "message", "data": json.dumps(ended)}])
        with _ws_env(subscriber=subscriber, is_operator=False):
            with client.websocket_connect(_ws_url(event_id)) as websocket:
                websocket.receive_json()
                assert websocket.receive_json() == ended
                with pytest.raises(WebSocketDisconnect):
                    websocket.receive_json()


class TestAnonymousViewer:
    """A signed-out page follows a published group's puja with no token at
    all: it is counted in the room and lands on the live line like anyone
    else, but never drives it."""

    def test_connects_without_a_token_and_lands_on_the_live_line(self):
        event_id = uuid4()
        position = {
            "type": "position",
            "event_id": str(event_id),
            "text_id": "text-7",
            "segment_id": "seg-7",
            "index": 12,
            "round_number": 3,
            "server_time": "2026-09-14T09:30:00Z",
            "revision": 57,
        }
        with _ws_env(position=position) as (broadcaster, mock_access):
            with client.websocket_connect(_ws_url(event_id, token=None)) as websocket:
                info = websocket.receive_json()
                current = websocket.receive_json()
                _sync(websocket)

        assert info == {
            "type": "session_info",
            "event_id": str(event_id),
            "is_operator": False,
            "count": 1,
        }
        assert current == position
        broadcaster.live_event.assert_called_once_with(event_id=event_id)
        # No session, so nothing to resolve a person or operator rights from.
        broadcaster.caller.assert_not_called()
        mock_access.assert_not_called()
        # Counted in the room, announced, and released on close, under one id.
        broadcaster.mark_present.assert_awaited_once()
        presence_event, presence_id = broadcaster.mark_present.await_args.args
        assert presence_event == event_id
        broadcaster.broadcast_presence.assert_awaited_with(event_id)
        broadcaster.mark_absent.assert_awaited_once_with(event_id, presence_id, "presence-token")
        broadcaster.remove_connection.assert_called_once_with(event_id, presence_id)
        # A viewer never hears where autoplay is.
        broadcaster.subscribe_to_autoplay.assert_not_awaited()

    def test_an_empty_token_is_a_signed_out_viewer(self):
        """A page with no session may still send the parameter, just empty."""
        with _ws_env() as (broadcaster, mock_access):
            with client.websocket_connect(_ws_url(uuid4(), token="")) as websocket:
                info = websocket.receive_json()
                _sync(websocket)

        assert info["is_operator"] is False
        broadcaster.caller.assert_not_called()
        mock_access.assert_not_called()
        broadcaster.mark_present.assert_awaited_once()

    def test_each_anonymous_socket_is_its_own_person(self):
        """Nothing ties two signed-out sockets together, so sharing a roster
        slot would undercount the room."""
        event_id = uuid4()
        with _ws_env() as (broadcaster, _):
            for _ in range(2):
                with client.websocket_connect(_ws_url(event_id, token=None)) as websocket:
                    websocket.receive_json()
                    _sync(websocket)

        first, second = (call.args[1] for call in broadcaster.mark_present.await_args_list)
        assert first != second

    def test_refused_for_a_missing_or_unpublished_event(self):
        detail = "Not found"
        event_error = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
        with _ws_env(event_error=event_error) as (broadcaster, _):
            with client.websocket_connect(_ws_url(uuid4(), token=None)) as websocket:
                message = websocket.receive_json()
                with pytest.raises(WebSocketDisconnect) as closed:
                    websocket.receive_json()

        assert message == {"type": "error", "code": detail, "message": detail}
        assert closed.value.code == status.WS_1008_POLICY_VIOLATION
        broadcaster.add_connection.assert_not_called()
        broadcaster.mark_present.assert_not_awaited()
        broadcaster.mark_absent.assert_not_awaited()

    def test_set_and_end_are_refused(self):
        with _ws_env() as (broadcaster, _):
            with client.websocket_connect(_ws_url(uuid4(), token=None)) as websocket:
                websocket.receive_json()
                websocket.send_json({"type": "set", "text_id": "text-7", "segment_id": "seg-1"})
                refused_set = websocket.receive_json()
                websocket.send_json({"type": "end"})
                refused_end = websocket.receive_json()
                _sync(websocket)

        assert refused_set["type"] == "error" and refused_set["code"] == "FORBIDDEN"
        assert refused_end["type"] == "error" and refused_end["code"] == "FORBIDDEN"
        broadcaster.allow_set.assert_not_awaited()
        broadcaster.broadcast_position.assert_not_awaited()
        broadcaster.clear_position.assert_not_awaited()
        broadcaster.broadcast_session_ended.assert_not_awaited()


class TestOperatorPublishing:

    def test_operator_set_broadcasts_position(self):
        event_id = uuid4()
        with _ws_env(is_operator=True) as (broadcaster, _):
            with client.websocket_connect(_ws_url(event_id)) as websocket:
                websocket.receive_json()
                websocket.send_json({
                    "type": "set",
                    "text_id": "text-7",
                    "segment_id": "seg-42",
                    "index": 12,
                    "round_number": 3,
                })
                _sync(websocket)

        kwargs = broadcaster.broadcast_position.await_args.kwargs
        assert kwargs["event_id"] == event_id
        assert kwargs["text_id"] == "text-7"
        assert kwargs["segment_id"] == "seg-42"
        assert kwargs["index"] == 12
        assert kwargs["round_number"] == 3
        assert kwargs["server_time"].endswith("Z")

    def test_operator_set_measures_play_time_in_the_background(self):
        event_id = uuid4()
        record = AsyncMock()
        with _ws_env(is_operator=True) as (broadcaster, _):
            broadcaster.broadcast_position.return_value = 57
            with patch("pecha_api.events.recitation_live_views.record_segment_play_time", new=record):
                with client.websocket_connect(_ws_url(event_id)) as websocket:
                    websocket.receive_json()
                    websocket.send_json({
                        "type": "set",
                        "text_id": "text-7",
                        "segment_id": "seg-42",
                        "index": 12,
                        "round_number": 3,
                        "elapsed_ms": 2_750,
                    })
                    _sync(websocket)

        kwargs = record.await_args.kwargs
        assert kwargs["broadcaster"] is broadcaster
        assert kwargs["event_id"] == event_id
        assert kwargs["text_id"] == "text-7"
        assert kwargs["segment_id"] == "seg-42"
        assert kwargs["index"] == 12
        assert kwargs["round_number"] == 3
        assert kwargs["revision"] == 57
        assert isinstance(kwargs["accepted_at_ms"], int)
        # The socket route carries the hold too: a controller on either route is
        # timed by its own clock, not by when its frames arrived.
        assert kwargs["elapsed_ms"] == 2_750

    def test_set_without_optional_fields_is_accepted(self):
        with _ws_env(is_operator=True) as (broadcaster, _):
            with client.websocket_connect(_ws_url(uuid4())) as websocket:
                websocket.receive_json()
                websocket.send_json({"type": "set", "text_id": "text-7", "segment_id": "seg-1"})
                _sync(websocket)

        kwargs = broadcaster.broadcast_position.await_args.kwargs
        assert kwargs["index"] is None
        assert kwargs["round_number"] is None

    def test_subscriber_set_is_rejected_but_socket_survives(self):
        with _ws_env(is_operator=False) as (broadcaster, _):
            with client.websocket_connect(_ws_url(uuid4())) as websocket:
                websocket.receive_json()
                websocket.send_json({"type": "set", "text_id": "text-7", "segment_id": "seg-1"})
                message = websocket.receive_json()
                _sync(websocket)

        assert message["type"] == "error"
        assert message["code"] == "FORBIDDEN"
        broadcaster.broadcast_position.assert_not_awaited()

    def test_invalid_set_frame_returns_validation_error(self):
        with _ws_env(is_operator=True) as (broadcaster, _):
            with client.websocket_connect(_ws_url(uuid4())) as websocket:
                websocket.receive_json()
                websocket.send_json({"type": "set", "text_id": "text-7", "segment_id": "   "})
                message = websocket.receive_json()
                _sync(websocket)

        assert message["code"] == "VALIDATION_ERROR"
        broadcaster.broadcast_position.assert_not_awaited()

    def test_negative_round_number_is_rejected(self):
        with _ws_env(is_operator=True) as (broadcaster, _):
            with client.websocket_connect(_ws_url(uuid4())) as websocket:
                websocket.receive_json()
                websocket.send_json({"type": "set", "text_id": "text-7", "segment_id": "seg-1", "round_number": 0})
                message = websocket.receive_json()
                _sync(websocket)

        assert message["code"] == "VALIDATION_ERROR"
        broadcaster.broadcast_position.assert_not_awaited()

    def test_set_without_text_id_is_rejected(self):
        """The event's collection holds several texts, so a position that does
        not say which one it belongs to is not resolvable by a client."""
        with _ws_env(is_operator=True) as (broadcaster, _):
            with client.websocket_connect(_ws_url(uuid4())) as websocket:
                websocket.receive_json()
                websocket.send_json({"type": "set", "segment_id": "seg-1"})
                message = websocket.receive_json()
                _sync(websocket)

        assert message["code"] == "VALIDATION_ERROR"
        broadcaster.broadcast_position.assert_not_awaited()

    def test_blank_text_id_is_rejected(self):
        with _ws_env(is_operator=True) as (broadcaster, _):
            with client.websocket_connect(_ws_url(uuid4())) as websocket:
                websocket.receive_json()
                websocket.send_json({"type": "set", "text_id": "  ", "segment_id": "seg-1"})
                message = websocket.receive_json()
                _sync(websocket)

        assert message["code"] == "VALIDATION_ERROR"
        broadcaster.broadcast_position.assert_not_awaited()

    def test_operator_moving_to_the_next_text_is_broadcast(self):
        """Sequential recitations: the operator finishes one liturgy and starts
        the next on the same socket, and the text change rides along."""
        with _ws_env(is_operator=True) as (broadcaster, _):
            with client.websocket_connect(_ws_url(uuid4())) as websocket:
                websocket.receive_json()
                websocket.send_json({"type": "set", "text_id": "text-a", "segment_id": "seg-9"})
                websocket.send_json({"type": "set", "text_id": "text-b", "segment_id": "seg-1"})
                _sync(websocket)

        texts = [call.kwargs["text_id"] for call in broadcaster.broadcast_position.await_args_list]
        assert texts == ["text-a", "text-b"]

    def test_throttled_set_is_dropped_silently(self):
        with _ws_env(is_operator=True, allow_set=False) as (broadcaster, _):
            with client.websocket_connect(_ws_url(uuid4())) as websocket:
                websocket.receive_json()
                websocket.send_json({"type": "set", "text_id": "text-7", "segment_id": "seg-1"})
                _sync(websocket)

        broadcaster.broadcast_position.assert_not_awaited()

    def test_broadcast_failure_reports_server_error(self):
        broadcaster = AsyncMock()
        broadcaster.allow_set.return_value = True
        broadcaster.broadcast_position.side_effect = Exception("redis down")
        with _ws_env(is_operator=True, broadcaster=broadcaster):
            with client.websocket_connect(_ws_url(uuid4())) as websocket:
                websocket.receive_json()
                websocket.send_json({"type": "set", "text_id": "text-7", "segment_id": "seg-1"})
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

    def test_operator_is_told_when_ending_fails(self):
        broadcaster = AsyncMock()
        broadcaster.clear_position.return_value = True
        broadcaster.broadcast_session_ended.return_value = False
        with _ws_env(is_operator=True, broadcaster=broadcaster):
            with client.websocket_connect(_ws_url(uuid4())) as websocket:
                websocket.receive_json()
                websocket.send_json({"type": "end"})
                message = websocket.receive_json()

        assert message["type"] == "error"
        assert message["code"] == "SERVER_ERROR"

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

    def test_releases_subscription_on_disconnect(self):
        """The socket must hand its slot back: the event's Redis subscription
        is shared, and it is only closed once the last watcher lets go."""
        event_id = uuid4()
        subscriber = FakeSubscriber()
        with _ws_env(subscriber=subscriber, is_operator=True) as (broadcaster, _):
            with client.websocket_connect(_ws_url(event_id)) as websocket:
                websocket.receive_json()
                _sync(websocket)

        broadcaster.unsubscribe_from_event.assert_awaited_once_with(event_id, subscriber)
