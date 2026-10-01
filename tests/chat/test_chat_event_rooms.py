import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException
from starlette import status

# Import the app first so the full SQLAlchemy model registry is configured
# before any ChatRoom()/ChatRoomMember() instantiation below triggers mapper configuration.
import pecha_api.app  # noqa: F401

from pecha_api.chat.enums import ChatRoomKind
from pecha_api.chat.service import (
    _default_event_room_name,
    _get_room_or_404,
    close_event_chat_sockets,
    join_event_chat_room,
    leave_event_chat_room,
    load_open_event,
    resolve_or_create_event_room,
    room_kind,
)

MODULE = "pecha_api.chat.service"


class MockUser:
    def __init__(self, user_id=None, email="user@example.com", firstname="Alice"):
        self.id = user_id or uuid4()
        self.email = email
        self.firstname = firstname
        self.lastname = None
        self.avatar_url = None


class MockEvent:
    def __init__(self, event_id=None, group_id=None, chat_enabled=True, name="Losar Puja"):
        self.id = event_id or uuid4()
        self.group_id = group_id or uuid4()
        self.chat_enabled = chat_enabled
        self.image_url = "events/losar.png"
        self.metadata_entries = [MagicMock(name_attr=name)]
        self.metadata_entries[0].name = name


class TestRoomKind:
    """The three shapes of ck_chat_rooms_kind_shape, derived from columns."""

    def test_group_room(self):
        room = MagicMock(group_id=uuid4(), event_id=None, sender_id=None, receiver_id=None)
        assert room_kind(room) == ChatRoomKind.GROUP.value

    def test_event_room(self):
        room = MagicMock(group_id=None, event_id=uuid4(), sender_id=None, receiver_id=None)
        assert room_kind(room) == ChatRoomKind.EVENT.value

    def test_private_room(self):
        room = MagicMock(group_id=None, event_id=None, sender_id=uuid4(), receiver_id=uuid4())
        assert room_kind(room) == ChatRoomKind.PRIVATE.value


class TestLoadOpenEvent:

    @patch(f"{MODULE}.is_group_id_published", return_value=True)
    @patch(f"{MODULE}.get_event_by_id")
    def test_returns_event_when_open(self, mock_get_event, _mock_published):
        event = MockEvent()
        mock_get_event.return_value = event

        assert load_open_event(db=MagicMock(), event_id=event.id) is event

    @patch(f"{MODULE}.is_group_id_published", return_value=True)
    @patch(f"{MODULE}.get_event_by_id", return_value=None)
    def test_404_when_event_missing(self, _mock_get_event, _mock_published):
        with pytest.raises(HTTPException) as exc_info:
            load_open_event(db=MagicMock(), event_id=uuid4())

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @patch(f"{MODULE}.is_group_id_published", return_value=True)
    @patch(f"{MODULE}.get_event_by_id")
    def test_404_when_chat_switched_off(self, mock_get_event, _mock_published):
        mock_get_event.return_value = MockEvent(chat_enabled=False)

        with pytest.raises(HTTPException) as exc_info:
            load_open_event(db=MagicMock(), event_id=uuid4())

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @patch(f"{MODULE}.is_group_id_published", return_value=False)
    @patch(f"{MODULE}.get_event_by_id")
    def test_404_when_owning_group_hidden(self, mock_get_event, _mock_published):
        mock_get_event.return_value = MockEvent()

        with pytest.raises(HTTPException) as exc_info:
            load_open_event(db=MagicMock(), event_id=uuid4())

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @patch(f"{MODULE}.is_group_id_published", return_value=True)
    @patch(f"{MODULE}.get_event_by_id")
    def test_writers_lock_the_group(self, mock_get_event, mock_published):
        mock_get_event.return_value = MockEvent()

        load_open_event(db=MagicMock(), event_id=uuid4(), for_update=True)

        assert mock_published.call_args.kwargs["for_update"] is True


class TestResolveOrCreateEventRoom:

    @patch(f"{MODULE}.add_member")
    @patch(f"{MODULE}.create_room")
    @patch(f"{MODULE}._is_eligible_for_group_chat", return_value=True)
    @patch(f"{MODULE}.get_room_by_event_id", return_value=None)
    @patch(f"{MODULE}.is_group_id_published", return_value=True)
    @patch(f"{MODULE}.get_event_by_id")
    def test_creates_room_named_after_the_event(
        self,
        mock_get_event,
        _mock_published,
        _mock_get_room,
        _mock_eligible,
        mock_create_room,
        mock_add_member,
    ):
        event = MockEvent(name="Losar Puja")
        mock_get_event.return_value = event
        user = MockUser()
        mock_create_room.side_effect = lambda db, room: room

        room = resolve_or_create_event_room(db=MagicMock(), event_id=event.id, user=user)

        assert room.event_id == event.id
        assert room.group_id is None
        assert room.name == "Losar Puja"
        assert room.created_by == user.id
        # Creator on first use, exactly like a group room.
        assert mock_add_member.call_args.kwargs["member"].role == "CREATOR"

    @patch(f"{MODULE}._is_eligible_for_group_chat", return_value=False)
    @patch(f"{MODULE}.get_room_by_event_id", return_value=None)
    @patch(f"{MODULE}.is_group_id_published", return_value=True)
    @patch(f"{MODULE}.get_event_by_id")
    def test_forbidden_when_not_in_the_events_group(
        self, mock_get_event, _mock_published, _mock_get_room, _mock_eligible
    ):
        mock_get_event.return_value = MockEvent()

        with pytest.raises(HTTPException) as exc_info:
            resolve_or_create_event_room(
                db=MagicMock(), event_id=uuid4(), user=MockUser()
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @patch(f"{MODULE}.add_member")
    @patch(f"{MODULE}.get_member", return_value=None)
    @patch(f"{MODULE}._is_eligible_for_group_chat", return_value=True)
    @patch(f"{MODULE}.get_room_by_event_id")
    @patch(f"{MODULE}.is_group_id_published", return_value=True)
    @patch(f"{MODULE}.get_event_by_id")
    def test_existing_room_auto_adds_an_eligible_newcomer(
        self,
        mock_get_event,
        _mock_published,
        mock_get_room,
        _mock_eligible,
        _mock_get_member,
        mock_add_member,
    ):
        event = MockEvent()
        mock_get_event.return_value = event
        existing = MagicMock(id=uuid4(), event_id=event.id)
        mock_get_room.return_value = existing

        room = resolve_or_create_event_room(
            db=MagicMock(), event_id=event.id, user=MockUser()
        )

        assert room is existing
        assert mock_add_member.call_args.kwargs["member"].role == "MEMBER"

    @patch(f"{MODULE}.add_member")
    @patch(f"{MODULE}.get_member")
    @patch(f"{MODULE}._is_eligible_for_group_chat", return_value=True)
    @patch(f"{MODULE}.get_room_by_event_id")
    @patch(f"{MODULE}.is_group_id_published", return_value=True)
    @patch(f"{MODULE}.get_event_by_id")
    def test_returning_member_is_reactivated_not_duplicated(
        self,
        mock_get_event,
        _mock_published,
        mock_get_room,
        _mock_eligible,
        mock_get_member,
        mock_add_member,
    ):
        event = MockEvent()
        mock_get_event.return_value = event
        mock_get_room.return_value = MagicMock(id=uuid4(), event_id=event.id)
        member = MagicMock(left_at="2026-01-01T00:00:00Z")
        mock_get_member.return_value = member

        resolve_or_create_event_room(db=MagicMock(), event_id=event.id, user=MockUser())

        assert member.left_at is None
        mock_add_member.assert_not_called()

    @patch(f"{MODULE}.get_member")
    @patch(f"{MODULE}._is_eligible_for_group_chat", return_value=False)
    @patch(f"{MODULE}.get_room_by_event_id")
    @patch(f"{MODULE}.is_group_id_published", return_value=True)
    @patch(f"{MODULE}.get_event_by_id")
    def test_forbidden_for_a_stale_active_member_no_longer_eligible(
        self,
        mock_get_event,
        _mock_published,
        mock_get_room,
        _mock_eligible,
        mock_get_member,
    ):
        """An already-active ChatRoomMember row (left over from before the
        caller left/unfollowed the owning group, or from before the event was
        moved to a different group) must not keep granting access - eligibility
        is re-verified against the event's current group on every call."""
        event = MockEvent()
        mock_get_event.return_value = event
        mock_get_room.return_value = MagicMock(id=uuid4(), event_id=event.id)
        mock_get_member.return_value = MagicMock(left_at=None)

        with pytest.raises(HTTPException) as exc_info:
            resolve_or_create_event_room(
                db=MagicMock(), event_id=event.id, user=MockUser()
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        mock_get_member.assert_not_called()


class TestEventRoomGate:
    """Every room-id route resolves through _get_room_or_404."""

    @patch(f"{MODULE}.load_open_event")
    @patch(f"{MODULE}.get_room_by_id")
    def test_event_room_consults_the_event(self, mock_get_room, mock_load_event):
        room = MagicMock(group_id=None, event_id=uuid4())
        mock_get_room.return_value = room

        assert _get_room_or_404(db=MagicMock(), room_id=uuid4()) is room
        assert mock_load_event.call_args.kwargs["event_id"] == room.event_id

    @patch(f"{MODULE}.get_room_by_id")
    def test_event_room_404s_when_chat_disabled(self, mock_get_room):
        mock_get_room.return_value = MagicMock(group_id=None, event_id=uuid4())

        with patch(
            f"{MODULE}.load_open_event",
            side_effect=HTTPException(status_code=404, detail="NOT_FOUND"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                _get_room_or_404(db=MagicMock(), room_id=uuid4())

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


class TestRsvpHooks:

    @patch(f"{MODULE}.add_member")
    @patch(f"{MODULE}.get_member", return_value=None)
    @patch(f"{MODULE}._is_eligible_for_group_chat", return_value=True)
    @patch(f"{MODULE}.get_event_by_id")
    @patch(f"{MODULE}.get_room_by_event_id")
    def test_join_adds_the_rsvping_user_to_an_existing_room(
        self,
        mock_get_room,
        mock_get_event,
        _mock_eligible,
        _mock_get_member,
        mock_add_member,
    ):
        mock_get_room.return_value = MagicMock(id=uuid4())
        mock_get_event.return_value = MockEvent()

        join_event_chat_room(db=MagicMock(), event_id=uuid4(), user=MockUser())

        mock_add_member.assert_called_once()

    @patch(f"{MODULE}.add_member")
    @patch(f"{MODULE}.get_room_by_event_id", return_value=None)
    def test_join_is_a_noop_before_the_room_exists(self, _mock_get_room, mock_add_member):
        """The room is created lazily by the first message; RSVPing early just
        has nothing to join yet."""
        join_event_chat_room(db=MagicMock(), event_id=uuid4(), user=MockUser())

        mock_add_member.assert_not_called()

    @patch(f"{MODULE}.leave_member")
    @patch(f"{MODULE}.get_active_member")
    @patch(f"{MODULE}.get_room_by_event_id")
    def test_leave_drops_the_room_from_the_inbox(
        self, mock_get_room, mock_get_active, mock_leave
    ):
        mock_get_room.return_value = MagicMock(id=uuid4())
        member = MagicMock()
        mock_get_active.return_value = member

        leave_event_chat_room(db=MagicMock(), event_id=uuid4(), user_id=uuid4())

        assert mock_leave.call_args.kwargs["member"] is member


class TestCloseEventChatSockets:

    @patch("pecha_api.chat.chat_websocket.get_broadcaster")
    @patch(f"{MODULE}.get_room_by_event_id")
    @patch(f"{MODULE}.SessionLocal")
    def test_publishes_room_closed(self, mock_session, mock_get_room, mock_broadcaster):
        import asyncio

        mock_session.return_value.__enter__.return_value = MagicMock()
        room = MagicMock(id=uuid4())
        mock_get_room.return_value = room
        broadcaster = AsyncMock()
        mock_broadcaster.return_value = broadcaster

        asyncio.run(
            close_event_chat_sockets(event_id=uuid4(), reason="EVENT_CHAT_DISABLED")
        )

        assert broadcaster.broadcast_room_closed.call_args.kwargs["reason"] == (
            "EVENT_CHAT_DISABLED"
        )

    @patch(f"{MODULE}.get_room_by_event_id", return_value=None)
    @patch(f"{MODULE}.SessionLocal")
    def test_noop_when_no_room(self, mock_session, _mock_get_room):
        import asyncio

        mock_session.return_value.__enter__.return_value = MagicMock()

        # No room, no broadcaster call, and no exception.
        asyncio.run(close_event_chat_sockets(event_id=uuid4(), reason="X"))


class TestDefaultEventRoomName:

    def test_uses_the_events_metadata_name(self):
        event = MockEvent(name="Monlam Prayer Festival")
        assert _default_event_room_name(event) == "Monlam Prayer Festival"

    def test_falls_back_when_event_has_no_metadata(self):
        event = MockEvent()
        event.metadata_entries = []
        assert _default_event_room_name(event) == "Event chat"
