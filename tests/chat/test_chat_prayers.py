import pytest
from datetime import datetime, timedelta, timezone as tz
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException
from starlette import status

# Import the app first so the full SQLAlchemy model registry is configured
# before any ChatRoom()/ChatMessage() instantiation below triggers mapper configuration.
import pecha_api.app  # noqa: F401

from pecha_api.chat.enums import ChatMessageType
from pecha_api.chat.message_service import (
    _validate_message_type,
    list_message_prayers_service,
    pray_for_messages_service,
    unpray_message_service,
)
from pecha_api.chat.repository import PrayResult, UnreportedPrayers
from pecha_api.chat.response_models import PrayForMessagesRequest
from pecha_api.chat.service import build_message_dto
from pecha_api.prayer_intentions.prayer_intention_response_models import PrayerIntentionDTO

MODULE = "pecha_api.chat.message_service"
DISPATCH = "pecha_api.chat.notification_dispatch_service"


class MockUser:
    def __init__(self, user_id=None, email="user@example.com", firstname="Alice"):
        self.id = user_id or uuid4()
        self.email = email
        self.firstname = firstname
        self.lastname = None
        self.avatar_url = None


class MockMessage:
    def __init__(self, message_id=None, room_id=None, sender=None, message_type="PRAYER"):
        self.id = message_id or uuid4()
        self.room_id = room_id or uuid4()
        self.sender = sender or MockUser()
        self.sender_id = self.sender.id
        self.body = "Please pray for my mother"
        self.message_type = message_type
        self.created_at = datetime.now(tz.utc)
        self.deleted_at = None
        self.parent = None
        self.parent_message_id = None
        self.intention = None


class MockPrayerCount:
    def __init__(self, message_id=None, user=None, prayer_count=1, last_prayed_at=None):
        self.id = uuid4()
        self.message_id = message_id or uuid4()
        self.user = user or MockUser()
        self.user_id = self.user.id
        self.prayer_count = prayer_count
        self.first_prayed_at = datetime(2026, 9, 30, 10, 0, tzinfo=tz.utc)
        self.last_prayed_at = last_prayed_at or datetime(2026, 9, 30, 10, 5, tzinfo=tz.utc)


def _session(mock_session):
    mock_session.return_value.__enter__.return_value = MagicMock()


def _pray_result(created=(), counts=None):
    return PrayResult(created_message_ids=set(created), my_prayer_counts=counts or {})


class TestPrayerRequestPlacement:
    """A prayer request needs a congregation, so DMs reject it."""

    def test_prayer_allowed_in_a_group_room(self):
        room = MagicMock(group_id=uuid4(), event_id=None, sender_id=None, receiver_id=None)

        assert (
            _validate_message_type(room=room, message_type="PRAYER") == "PRAYER"
        )

    def test_prayer_allowed_in_an_event_room(self):
        room = MagicMock(group_id=None, event_id=uuid4(), sender_id=None, receiver_id=None)

        assert (
            _validate_message_type(room=room, message_type="PRAYER") == "PRAYER"
        )

    def test_prayer_rejected_in_a_dm(self):
        room = MagicMock(group_id=None, event_id=None, sender_id=uuid4(), receiver_id=uuid4())

        with pytest.raises(HTTPException) as exc_info:
            _validate_message_type(room=room, message_type="PRAYER")

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert exc_info.value.detail == "PRAYER_NOT_ALLOWED_IN_DM"

    def test_text_allowed_everywhere(self):
        room = MagicMock(group_id=None, event_id=None, sender_id=uuid4(), receiver_id=uuid4())

        assert _validate_message_type(room=room, message_type="TEXT") == "TEXT"

    def test_unknown_type_rejected(self):
        room = MagicMock(group_id=uuid4(), event_id=None, sender_id=None, receiver_id=None)

        with pytest.raises(HTTPException) as exc_info:
            _validate_message_type(room=room, message_type="SHOUT")

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST


class TestPrayerBatchRequestValidation:

    def test_rejects_empty_selection(self):
        with pytest.raises(ValueError):
            PrayForMessagesRequest(message_ids=[])

    def test_drops_duplicate_ids_keeping_order(self):
        first, second = uuid4(), uuid4()

        request = PrayForMessagesRequest(message_ids=[first, second, first])

        assert request.message_ids == [first, second]

    def test_accepts_ten_ids(self):
        request = PrayForMessagesRequest(message_ids=[uuid4() for _ in range(10)])

        assert len(request.message_ids) == 10

    def test_rejects_more_than_ten_ids(self):
        """Ten is the per-second prayer limit, so a larger selection could never
        pass the rate limit even at count 1."""
        with pytest.raises(ValueError):
            PrayForMessagesRequest(message_ids=[uuid4() for _ in range(11)])

    def test_count_defaults_to_one(self):
        assert PrayForMessagesRequest(message_ids=[uuid4()]).count == 1

    @pytest.mark.parametrize("count", [1, 10])
    def test_count_in_range_is_accepted(self, count):
        assert PrayForMessagesRequest(message_ids=[uuid4()], count=count).count == count

    @pytest.mark.parametrize("count", [0, -1, 11])
    def test_count_out_of_range_is_rejected(self, count):
        with pytest.raises(ValueError):
            PrayForMessagesRequest(message_ids=[uuid4()], count=count)


class TestPrayForMessagesService:

    @patch(f"{MODULE}.notify_prayers_for_request")
    @patch(f"{MODULE}.get_prayer_user_ids_map")
    @patch(f"{MODULE}.get_prayer_counts_map")
    @patch(f"{MODULE}.add_prayers")
    @patch(f"{MODULE}.get_message_by_id")
    @patch(f"{MODULE}._require_active_member")
    @patch(f"{MODULE}._get_room_or_404")
    @patch(f"{MODULE}.SessionLocal")
    def test_prays_for_several_selected_requests_at_once(
        self,
        mock_session,
        _mock_room,
        _mock_member,
        mock_get_message,
        mock_add_prayers,
        mock_counts,
        mock_user_ids,
        mock_notify,
    ):
        _session(mock_session)
        room_id = uuid4()
        user = MockUser()
        first = MockMessage(room_id=room_id)
        second = MockMessage(room_id=room_id)
        mock_get_message.side_effect = lambda db, message_id, room_id: (
            first if message_id == first.id else second
        )
        mock_add_prayers.return_value = _pray_result(
            created=[first.id, second.id], counts={first.id: 1, second.id: 1}
        )
        mock_counts.return_value = {first.id: 3, second.id: 1}
        mock_user_ids.return_value = {first.id: [user.id], second.id: [user.id]}

        result = pray_for_messages_service(
            room_id=room_id, user=user, message_ids=[first.id, second.id]
        )

        assert [p.message_id for p in result.response.prayers] == [first.id, second.id]
        assert [p.prayer_count for p in result.response.prayers] == [3, 1]
        assert [p.my_prayer_count for p in result.response.prayers] == [1, 1]
        assert all(p.prayed_by_me for p in result.response.prayers)
        assert all(p.created for p in result.response.prayers)
        assert result.room_id == room_id
        assert mock_add_prayers.call_args.kwargs["count"] == 1
        assert mock_notify.call_count == 2

    @patch(f"{MODULE}.notify_prayers_for_request")
    @patch(f"{MODULE}.get_prayer_user_ids_map", return_value={})
    @patch(f"{MODULE}.get_prayer_counts_map")
    @patch(f"{MODULE}.add_prayers")
    @patch(f"{MODULE}.get_message_by_id")
    @patch(f"{MODULE}._require_active_member")
    @patch(f"{MODULE}._get_room_or_404")
    @patch(f"{MODULE}.SessionLocal")
    def test_praying_again_adds_to_my_count_and_still_runs_the_gate(
        self,
        mock_session,
        _mock_room,
        _mock_member,
        mock_get_message,
        mock_add_prayers,
        mock_counts,
        _mock_user_ids,
        mock_notify,
    ):
        """A repeat tap is no longer a no-op: the total grows, the people count
        does not, and the gate runs so the repeat can reach the requester."""
        _session(mock_session)
        message = MockMessage()
        user = MockUser()
        mock_get_message.return_value = message
        mock_add_prayers.return_value = _pray_result(counts={message.id: 20})
        mock_counts.return_value = {message.id: 7}

        result = pray_for_messages_service(
            room_id=message.room_id, user=user, message_ids=[message.id], count=10
        )

        state = result.response.prayers[0]
        assert state.created is False
        assert state.prayed_by_me is True
        assert state.prayer_count == 7
        assert state.my_prayer_count == 20
        assert mock_add_prayers.call_args.kwargs["count"] == 10
        mock_notify.assert_called_once_with(
            message_id=message.id, prayer_user_id=user.id
        )

    @patch(f"{MODULE}.notify_prayers_for_request")
    @patch(f"{MODULE}.get_prayer_user_ids_map", return_value={})
    @patch(f"{MODULE}.get_prayer_counts_map")
    @patch(f"{MODULE}.add_prayers")
    @patch(f"{MODULE}.get_message_by_id")
    @patch(f"{MODULE}._require_active_member")
    @patch(f"{MODULE}._get_room_or_404")
    @patch(f"{MODULE}.SessionLocal")
    def test_skips_ids_that_are_not_live_prayer_requests(
        self,
        mock_session,
        _mock_room,
        _mock_member,
        mock_get_message,
        mock_add_prayers,
        mock_counts,
        _mock_user_ids,
        mock_notify,
    ):
        """A request deleted between rendering and confirming must not cost the
        user the rest of their selection."""
        _session(mock_session)
        prayer = MockMessage()
        plain = MockMessage(message_type="TEXT")
        gone_id = uuid4()

        def lookup(db, message_id, room_id):
            if message_id == prayer.id:
                return prayer
            if message_id == plain.id:
                return plain
            return None

        mock_get_message.side_effect = lookup
        mock_add_prayers.return_value = _pray_result()
        mock_counts.return_value = {prayer.id: 1}

        result = pray_for_messages_service(
            room_id=prayer.room_id,
            user=MockUser(),
            message_ids=[prayer.id, plain.id, gone_id],
        )

        assert [p.message_id for p in result.response.prayers] == [prayer.id]
        assert mock_add_prayers.call_args.kwargs["message_ids"] == [prayer.id]
        assert mock_notify.call_count == 1

    @patch(f"{MODULE}.get_message_by_id", return_value=None)
    @patch(f"{MODULE}._require_active_member")
    @patch(f"{MODULE}._get_room_or_404")
    @patch(f"{MODULE}.SessionLocal")
    def test_404_when_nothing_in_the_selection_is_prayable(
        self, mock_session, _mock_room, _mock_member, _mock_get_message
    ):
        _session(mock_session)
        room_id, user, message_ids = uuid4(), MockUser(), [uuid4()]

        with pytest.raises(HTTPException) as exc_info:
            pray_for_messages_service(room_id=room_id, user=user, message_ids=message_ids)

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @patch(f"{MODULE}.notify_prayers_for_request")
    @patch(f"{MODULE}.get_prayer_user_ids_map")
    @patch(f"{MODULE}.get_prayer_counts_map")
    @patch(f"{MODULE}.add_prayers")
    @patch(f"{MODULE}.get_message_by_id")
    @patch(f"{MODULE}._require_active_member")
    @patch(f"{MODULE}._get_room_or_404")
    @patch(f"{MODULE}.SessionLocal")
    def test_broadcast_carries_count_and_user_ids_per_message(
        self,
        mock_session,
        _mock_room,
        _mock_member,
        mock_get_message,
        mock_add_prayers,
        mock_counts,
        mock_user_ids,
        _mock_notify,
    ):
        """One payload for the whole selection, and no viewer-specific state in
        it - clients derive prayed_by_me from user_ids, as they do for reactions."""
        _session(mock_session)
        message = MockMessage()
        mock_get_message.return_value = message
        mock_add_prayers.return_value = _pray_result()
        mock_counts.return_value = {message.id: 2}
        prayer_user_ids = [uuid4(), uuid4()]
        mock_user_ids.return_value = {message.id: prayer_user_ids}

        result = pray_for_messages_service(
            room_id=message.room_id, user=MockUser(), message_ids=[message.id]
        )

        assert result.broadcast == [
            {
                "message_id": str(message.id),
                "prayer_count": 2,
                "user_ids": [str(user_id) for user_id in prayer_user_ids],
            }
        ]
        assert "prayed_by_me" not in result.broadcast[0]


class TestUnprayMessageService:

    @patch(f"{MODULE}.get_prayer_user_ids_map", return_value={})
    @patch(f"{MODULE}.count_message_prayers", return_value=4)
    @patch(f"{MODULE}.remove_prayer_and_count")
    @patch(f"{MODULE}.get_message_by_id_any_room")
    @patch(f"{MODULE}._require_active_member")
    @patch(f"{MODULE}._get_room_or_404")
    @patch(f"{MODULE}.SessionLocal")
    def test_removes_the_callers_prayers(
        self,
        mock_session,
        _mock_room,
        _mock_member,
        mock_get_message,
        mock_remove,
        _mock_count,
        _mock_user_ids,
    ):
        _session(mock_session)
        message = MockMessage()
        user = MockUser()
        mock_get_message.return_value = message

        result = unpray_message_service(message_id=message.id, user=user)

        assert mock_remove.call_args.kwargs["message_id"] == message.id
        assert mock_remove.call_args.kwargs["user_id"] == user.id
        state = result.response.prayers[0]
        assert state.prayed_by_me is False
        assert state.my_prayer_count == 0
        assert state.prayer_count == 4
        assert result.room_id == message.room_id

    @patch(f"{MODULE}.get_message_by_id_any_room")
    @patch(f"{MODULE}._require_active_member")
    @patch(f"{MODULE}._get_room_or_404")
    @patch(f"{MODULE}.SessionLocal")
    def test_rejects_a_message_that_is_not_a_prayer_request(
        self, mock_session, _mock_room, _mock_member, mock_get_message
    ):
        _session(mock_session)
        mock_get_message.return_value = MockMessage(message_type="TEXT")
        message_id, user = uuid4(), MockUser()

        with pytest.raises(HTTPException) as exc_info:
            unpray_message_service(message_id=message_id, user=user)

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert exc_info.value.detail == "NOT_A_PRAYER_REQUEST"


class TestListMessagePrayersService:

    @patch(f"{MODULE}.list_message_prayers")
    @patch(f"{MODULE}.get_message_by_id_any_room")
    @patch(f"{MODULE}._require_active_member")
    @patch(f"{MODULE}._get_room_or_404")
    @patch(f"{MODULE}.SessionLocal")
    def test_requester_sees_who_is_praying_and_how_often(
        self,
        mock_session,
        _mock_room,
        _mock_member,
        mock_get_message,
        mock_list,
    ):
        _session(mock_session)
        requester = MockUser()
        message = MockMessage(sender=requester)
        mock_get_message.return_value = message
        bob = MockUser(email="bob@example.com", firstname="Bob")
        dolma = MockUser(email="dolma@example.com", firstname="Dolma")
        recent = datetime(2026, 9, 30, 10, 25, tzinfo=tz.utc)
        mock_list.return_value = (
            [
                MockPrayerCount(message.id, dolma, prayer_count=10, last_prayed_at=recent),
                MockPrayerCount(message.id, bob, prayer_count=3),
            ],
            2,
        )

        response = list_message_prayers_service(
            message_id=message.id, user=requester, skip=0, limit=20
        )

        assert response.total == 2
        assert response.message_id == message.id
        assert [p.name for p in response.prayers] == ["Dolma", "Bob"]
        assert [p.prayer_count for p in response.prayers] == [10, 3]
        assert response.prayers[0].last_prayed_at == recent.isoformat()
        assert response.prayers[0].created_at == (
            datetime(2026, 9, 30, 10, 0, tzinfo=tz.utc).isoformat()
        )
        assert response.prayers[1].email == "bob@example.com"

    @patch(f"{MODULE}.list_message_prayers")
    @patch(f"{MODULE}.get_message_by_id_any_room")
    @patch(f"{MODULE}._require_active_member")
    @patch(f"{MODULE}._get_room_or_404")
    @patch(f"{MODULE}.SessionLocal")
    def test_another_member_sees_who_is_praying_but_not_how_often(
        self,
        mock_session,
        _mock_room,
        _mock_member,
        mock_get_message,
        mock_list,
    ):
        _session(mock_session)
        message = MockMessage()
        mock_get_message.return_value = message
        bob = MockUser(email="bob@example.com", firstname="Bob")
        mock_list.return_value = (
            [MockPrayerCount(message.id, bob, prayer_count=3)],
            1,
        )

        response = list_message_prayers_service(
            message_id=message.id, user=MockUser()
        )

        assert response.total == 1
        assert [p.name for p in response.prayers] == ["Bob"]
        assert response.prayers[0].prayer_count is None

    @patch(f"{MODULE}.list_message_prayers")
    @patch(f"{MODULE}.get_message_by_id_any_room")
    @patch(f"{MODULE}._require_active_member")
    @patch(f"{MODULE}._get_room_or_404")
    @patch(f"{MODULE}.SessionLocal")
    def test_membership_is_checked_before_authorship(
        self,
        mock_session,
        _mock_room,
        mock_member,
        mock_get_message,
        mock_list,
    ):
        """A requester who has left the room is refused by the membership gate,
        not let through because they wrote the request."""
        _session(mock_session)
        requester = MockUser()
        mock_get_message.return_value = MockMessage(sender=requester)
        mock_member.side_effect = HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="NOT_A_MEMBER"
        )

        with pytest.raises(HTTPException) as exc_info:
            list_message_prayers_service(message_id=uuid4(), user=requester)

        assert exc_info.value.detail == "NOT_A_MEMBER"
        mock_list.assert_not_called()


class TestPrayerFieldsOnMessageDTO:

    def test_prayer_fields_omitted_for_a_text_message(self):
        dto = build_message_dto(MockMessage(message_type="TEXT"))
        payload = dto.model_dump()

        assert dto.message_type == "TEXT"
        assert "prayer_count" not in payload
        assert "prayed_by_me" not in payload
        assert "my_prayer_count" not in payload
        assert "recent_prayers" not in payload
        assert "intention" not in payload

    def test_prayer_fields_present_for_a_prayer_request(self):
        praying_user = MockUser(email="bob@example.com", firstname="Bob")

        dto = build_message_dto(
            MockMessage(message_type="PRAYER"),
            prayer_count=12,
            prayed_by_me=True,
            recent_prayers=[praying_user],
            my_prayer_count=30,
        )
        payload = dto.model_dump()

        assert payload["message_type"] == "PRAYER"
        assert payload["prayer_count"] == 12
        assert payload["prayed_by_me"] is True
        assert payload["my_prayer_count"] == 30
        assert payload["recent_prayers"][0]["user_id"] == praying_user.id

    def test_intention_present_for_a_prayer_request(self):
        intention = PrayerIntentionDTO(
            slug="healing",
            label="Healing",
            color="#4A78C2",
            description="For illness and recovery.",
            display_order=0,
        )

        dto = build_message_dto(
            MockMessage(message_type="PRAYER"),
            intention=intention,
        )
        payload = dto.model_dump()

        assert payload["intention"]["slug"] == "healing"
        assert payload["intention"]["color"] == "#4A78C2"

    def test_enum_valued_message_type_serializes_as_a_string(self):
        message = MockMessage(message_type=ChatMessageType.PRAYER)

        dto = build_message_dto(message)

        assert dto.message_type == "PRAYER"

    def test_message_type_defaults_to_text_when_absent(self):
        """Rows written before the column existed read back as TEXT."""
        message = MockMessage()
        message.message_type = None

        dto = build_message_dto(message)

        assert dto.message_type == "TEXT"


def _previous_push(created_at):
    return MagicMock(created_at=created_at)


def _unreported(user_id=None, count=1, minutes_ago=0):
    return UnreportedPrayers(
        user_id=user_id or uuid4(),
        count=count,
        last_prayed_at=datetime.now(tz.utc) - timedelta(minutes=minutes_ago),
    )


@patch(f"{DISPATCH}.get_int", return_value=1140)
@patch(f"{DISPATCH}.create_prayer_notification")
@patch(f"{DISPATCH}.claim_unreported_prayers")
@patch(f"{DISPATCH}.get_last_prayer_notification")
@patch(f"{DISPATCH}.lock_prayer_request")
@patch(f"{DISPATCH}.SessionLocal")
class TestPrayerNotificationGate:
    """At most one prayer-received push per request per interval, reporting
    exactly the prayers no earlier push has reported."""

    def _run(self, mock_session, prayer_user_id):
        from pecha_api.chat.notification_dispatch_service import (
            _create_prayer_notification_if_due,
        )

        _session(mock_session)
        return _create_prayer_notification_if_due(
            message_id=uuid4(), prayer_user_id=prayer_user_id
        )

    def test_first_push_reports_the_first_prayer(
        self, mock_session, mock_lock, mock_last, mock_claim, mock_create, _get_int
    ):
        mock_lock.return_value = MockMessage()
        mock_last.return_value = None
        kunsang = _unreported(count=1)
        mock_claim.return_value = [kunsang]
        notification_id = uuid4()
        mock_create.return_value = MagicMock(id=notification_id)

        assert self._run(mock_session, kunsang.user_id) == notification_id

        kwargs = mock_create.call_args.kwargs
        assert kwargs["people_count"] == 1
        assert kwargs["prayer_total"] == 1
        assert kwargs["latest_user_id"] == kunsang.user_id

    def test_inside_the_interval_nothing_is_claimed_or_recorded(
        self, mock_session, mock_lock, mock_last, mock_claim, mock_create, _get_int
    ):
        mock_lock.return_value = MockMessage()
        mock_last.return_value = _previous_push(datetime.now(tz.utc) - timedelta(minutes=5))

        assert self._run(mock_session, uuid4()) is None

        mock_claim.assert_not_called()
        mock_create.assert_not_called()

    def test_after_the_interval_reports_everything_unreported(
        self, mock_session, mock_lock, mock_last, mock_claim, mock_create, _get_int
    ):
        """The RFC example: 9 others and Kunsang add 100 inside the interval,
        then Dolma prays 10 at 10:25 - 11 people, 110 prayers."""
        mock_lock.return_value = MockMessage()
        mock_last.return_value = _previous_push(datetime.now(tz.utc) - timedelta(minutes=25))
        dolma = _unreported(count=10, minutes_ago=0)
        others = [_unreported(count=10, minutes_ago=10) for _ in range(10)]
        mock_claim.return_value = others + [dolma]
        mock_create.return_value = MagicMock(id=uuid4())

        self._run(mock_session, dolma.user_id)

        kwargs = mock_create.call_args.kwargs
        assert kwargs["people_count"] == 11
        assert kwargs["prayer_total"] == 110
        assert kwargs["latest_user_id"] == dolma.user_id

    def test_an_unpray_does_not_hide_new_prayers(
        self, mock_session, mock_lock, mock_last, mock_claim, mock_create, _get_int
    ):
        """Someone reported earlier unprays (their row is gone); another person
        prays three times. The push says three, not a difference of totals."""
        mock_lock.return_value = MockMessage()
        mock_last.return_value = _previous_push(datetime.now(tz.utc) - timedelta(hours=1))
        mock_claim.return_value = [_unreported(count=3)]
        mock_create.return_value = MagicMock(id=uuid4())

        self._run(mock_session, uuid4())

        assert mock_create.call_args.kwargs["people_count"] == 1
        assert mock_create.call_args.kwargs["prayer_total"] == 3

    def test_the_requesters_own_unreported_prayers_are_not_counted(
        self, mock_session, mock_lock, mock_last, mock_claim, mock_create, _get_int
    ):
        message = MockMessage()
        mock_lock.return_value = message
        mock_last.return_value = None
        tenzin = _unreported(count=2, minutes_ago=5)
        mock_claim.return_value = [
            tenzin,
            _unreported(user_id=message.sender_id, count=10, minutes_ago=0),
        ]
        mock_create.return_value = MagicMock(id=uuid4())

        self._run(mock_session, tenzin.user_id)

        kwargs = mock_create.call_args.kwargs
        assert kwargs["people_count"] == 1
        assert kwargs["prayer_total"] == 2
        assert kwargs["latest_user_id"] == tenzin.user_id

    def test_the_requester_praying_raises_nothing(
        self, mock_session, mock_lock, mock_last, mock_claim, mock_create, _get_int
    ):
        message = MockMessage()
        mock_lock.return_value = message

        assert self._run(mock_session, message.sender_id) is None

        mock_last.assert_not_called()
        mock_create.assert_not_called()

    def test_nothing_unreported_raises_nothing_and_commits_nothing(
        self, mock_session, mock_lock, mock_last, mock_claim, mock_create, _get_int
    ):
        """Backfilled prayers start with nothing unreported, so they never show
        up as new."""
        mock_lock.return_value = MockMessage()
        mock_last.return_value = None
        mock_claim.return_value = []

        assert self._run(mock_session, uuid4()) is None
        mock_create.assert_not_called()
        mock_session.return_value.__enter__.return_value.commit.assert_not_called()

    def test_a_deleted_request_raises_nothing(
        self, mock_session, mock_lock, mock_last, mock_claim, mock_create, _get_int
    ):
        mock_lock.return_value = None

        assert self._run(mock_session, uuid4()) is None
        mock_create.assert_not_called()

    def test_interval_zero_pushes_every_time(
        self, mock_session, mock_lock, mock_last, mock_claim, mock_create, mock_get_int
    ):
        mock_get_int.return_value = 0
        mock_lock.return_value = MockMessage()
        mock_last.return_value = _previous_push(datetime.now(tz.utc))
        mock_claim.return_value = [_unreported(count=1)]
        mock_create.return_value = MagicMock(id=uuid4())

        assert self._run(mock_session, uuid4()) is not None
        assert mock_create.call_args.kwargs["prayer_total"] == 1

    def test_the_sweep_records_held_prayers_without_a_prayer_user(
        self, mock_session, mock_lock, mock_last, mock_claim, mock_create, _get_int
    ):
        """Nobody prayed again after the interval; the dispatcher collects
        what was held."""
        mock_lock.return_value = MockMessage()
        mock_last.return_value = _previous_push(datetime.now(tz.utc) - timedelta(minutes=20))
        pema, sonam = _unreported(count=1, minutes_ago=15), _unreported(count=2, minutes_ago=10)
        mock_claim.return_value = [pema, sonam]
        notification_id = uuid4()
        mock_create.return_value = MagicMock(id=notification_id)

        assert self._run(mock_session, None) == notification_id

        kwargs = mock_create.call_args.kwargs
        assert kwargs["people_count"] == 2
        assert kwargs["prayer_total"] == 3
        assert kwargs["latest_user_id"] == sonam.user_id

    def test_the_request_is_locked_before_the_last_push_is_read(
        self, mock_session, mock_lock, mock_last, mock_claim, mock_create, _get_int
    ):
        """Two concurrent pray calls must not both find the interval open."""
        order = []
        mock_lock.side_effect = lambda **_: order.append("lock") or MockMessage()
        mock_last.side_effect = lambda **_: order.append("last") or None
        mock_claim.side_effect = lambda **_: order.append("claim") or [_unreported()]
        mock_create.return_value = MagicMock(id=uuid4())

        self._run(mock_session, uuid4())

        assert order == ["lock", "last", "claim"]


class TestNotifyPrayersForRequest:

    @patch(f"{DISPATCH}._create_prayer_notification_if_due")
    @patch(f"{DISPATCH}.is_prayer_notification_sqs_configured", return_value=False)
    def test_no_queue_records_no_push(self, _configured, mock_gate):
        from pecha_api.chat.notification_dispatch_service import notify_prayers_for_request

        assert notify_prayers_for_request(uuid4(), uuid4()) is None
        mock_gate.assert_not_called()

    @patch(f"{DISPATCH}.get_int", return_value=0)
    @patch(f"{DISPATCH}.claim_prayer_notification_for_dispatch", return_value=True)
    @patch(f"{DISPATCH}.mark_prayer_notification_dispatched")
    @patch(f"{DISPATCH}.SessionLocal")
    @patch(f"{DISPATCH}.send_prayer_notification_message", return_value="sqs-1")
    @patch(f"{DISPATCH}._create_prayer_notification_if_due")
    @patch(f"{DISPATCH}.is_prayer_notification_sqs_configured", return_value=True)
    def test_sends_the_notification_id_as_prayer_id(
        self, _configured, mock_gate, mock_send, mock_session, mock_mark, mock_claim, _gap
    ):
        """With no gap configured the push is claimed and sent straight away."""
        from pecha_api.chat.notification_dispatch_service import notify_prayers_for_request

        _session(mock_session)
        notification_id = uuid4()
        mock_gate.return_value = notification_id

        assert notify_prayers_for_request(uuid4(), uuid4()) == "sqs-1"

        assert mock_claim.call_args.kwargs["notification_id"] == notification_id
        body = mock_send.call_args.args[0]
        assert body["event_type"] == "PRAYER_RECEIVED"
        assert body["prayer_id"] == str(notification_id)
        assert mock_mark.call_args.kwargs["notification_id"] == notification_id
        assert mock_mark.call_args.kwargs["sqs_message_id"] == "sqs-1"

    @patch(f"{DISPATCH}.get_int", return_value=120)
    @patch(f"{DISPATCH}.claim_prayer_notification_for_dispatch")
    @patch(f"{DISPATCH}.send_prayer_notification_message")
    @patch(f"{DISPATCH}._create_prayer_notification_if_due")
    @patch(f"{DISPATCH}.is_prayer_notification_sqs_configured", return_value=True)
    def test_with_a_gap_the_push_is_recorded_and_left_for_the_dispatcher(
        self, _configured, mock_gate, mock_send, mock_claim, _gap
    ):
        """The person who prayed often posts their own request next; sending
        now would land on top of it."""
        from pecha_api.chat.notification_dispatch_service import notify_prayers_for_request

        mock_gate.return_value = uuid4()

        assert notify_prayers_for_request(uuid4(), uuid4()) is None
        mock_gate.assert_called_once()
        mock_claim.assert_not_called()
        mock_send.assert_not_called()

    @patch(f"{DISPATCH}.get_int", return_value=0)
    @patch(f"{DISPATCH}.claim_prayer_notification_for_dispatch", return_value=False)
    @patch(f"{DISPATCH}.SessionLocal")
    @patch(f"{DISPATCH}.send_prayer_notification_message")
    @patch(f"{DISPATCH}._create_prayer_notification_if_due")
    @patch(f"{DISPATCH}.is_prayer_notification_sqs_configured", return_value=True)
    def test_a_push_claimed_elsewhere_is_not_sent_twice(
        self, _configured, mock_gate, mock_send, mock_session, _claim, _gap
    ):
        from pecha_api.chat.notification_dispatch_service import notify_prayers_for_request

        _session(mock_session)
        mock_gate.return_value = uuid4()

        assert notify_prayers_for_request(uuid4(), uuid4()) is None
        mock_send.assert_not_called()

    @patch(f"{DISPATCH}.send_prayer_notification_message")
    @patch(f"{DISPATCH}._create_prayer_notification_if_due", return_value=None)
    @patch(f"{DISPATCH}.is_prayer_notification_sqs_configured", return_value=True)
    def test_held_by_the_interval_sends_nothing(self, _configured, _gate, mock_send):
        from pecha_api.chat.notification_dispatch_service import notify_prayers_for_request

        assert notify_prayers_for_request(uuid4(), uuid4()) is None
        mock_send.assert_not_called()

    @patch(f"{DISPATCH}._create_prayer_notification_if_due", side_effect=RuntimeError)
    @patch(f"{DISPATCH}.is_prayer_notification_sqs_configured", return_value=True)
    def test_never_raises(self, _configured, _gate):
        from pecha_api.chat.notification_dispatch_service import notify_prayers_for_request

        assert notify_prayers_for_request(uuid4(), uuid4()) is None

    @patch(f"{DISPATCH}.get_int", return_value=0)
    @patch(f"{DISPATCH}.claim_prayer_notification_for_dispatch", return_value=True)
    @patch(f"{DISPATCH}.SessionLocal")
    @patch(f"{DISPATCH}.mark_prayer_notification_dispatched")
    @patch(f"{DISPATCH}.send_prayer_notification_message", side_effect=RuntimeError)
    @patch(f"{DISPATCH}._create_prayer_notification_if_due")
    @patch(f"{DISPATCH}.is_prayer_notification_sqs_configured", return_value=True)
    def test_a_failed_send_leaves_the_row_for_reconcile(
        self, _configured, mock_gate, _send, mock_mark, mock_session, _claim, _gap
    ):
        from pecha_api.chat.notification_dispatch_service import notify_prayers_for_request

        _session(mock_session)
        mock_gate.return_value = uuid4()

        assert notify_prayers_for_request(uuid4(), uuid4()) is None
        mock_mark.assert_not_called()


def _due(minutes_ago=3, requester_id=None):
    from pecha_api.chat.repository import DuePrayerNotification

    return DuePrayerNotification(
        id=uuid4(),
        requester_id=requester_id or uuid4(),
        created_at=datetime.now(tz.utc) - timedelta(minutes=minutes_ago),
    )


def _settings(gap=120, max_hold=900, batch=50):
    values = {
        "PRAYER_NOTIFICATION_GAP_SECONDS": gap,
        "PRAYER_NOTIFICATION_MAX_HOLD_SECONDS": max_hold,
        "CHAT_NOTIFICATION_DISPATCH_RECONCILE_BATCH_SIZE": batch,
    }
    return lambda key: values[key]


@patch(f"{DISPATCH}._record_held_prayer_notifications", return_value=0)
@patch(f"{DISPATCH}._claim_and_send_prayer_notification", return_value="sqs-3")
@patch(f"{DISPATCH}.last_prayer_request_push_to_user", return_value=None)
@patch(f"{DISPATCH}.list_due_prayer_notifications")
@patch(f"{DISPATCH}.SessionLocal")
@patch(f"{DISPATCH}.is_prayer_notification_sqs_configured", return_value=True)
class TestDispatchDuePrayerNotifications:
    """"Someone prayed for you" and "X is requesting a prayer" never arrive
    together: the prayer-received push waits for a quiet gap."""

    def _run(self, mock_session, **settings):
        from pecha_api.chat.notification_dispatch_service import (
            dispatch_due_prayer_notifications,
        )

        _session(mock_session)
        with patch(f"{DISPATCH}.get_int", side_effect=_settings(**settings)):
            return dispatch_due_prayer_notifications()

    def test_only_pushes_older_than_the_gap_are_listed(
        self, _configured, mock_session, mock_list, _last, _send, _record
    ):
        mock_list.return_value = []

        before = datetime.now(tz.utc)
        self._run(mock_session, gap=120)
        after = datetime.now(tz.utc)

        created_before = mock_list.call_args.kwargs["created_before"]
        gap = timedelta(seconds=120)
        assert before - gap <= created_before <= after - gap

    def test_sends_when_the_requester_had_no_recent_prayer_request_push(
        self, _configured, mock_session, mock_list, mock_last, mock_send, _record
    ):
        due = _due()
        mock_list.return_value = [due]

        assert self._run(mock_session) == 1

        mock_send.assert_called_once_with(due.id)
        assert mock_last.call_args.kwargs["user_id"] == due.requester_id

    def test_holds_while_a_prayer_request_push_just_reached_the_requester(
        self, _configured, mock_session, mock_list, mock_last, mock_send, _record
    ):
        """Tenzin prayed for Kunsang's request, then posted a request too.
        Kunsang hears Tenzin's request now and the prayer later."""
        mock_list.return_value = [_due(minutes_ago=3)]
        mock_last.return_value = datetime.now(tz.utc) - timedelta(seconds=30)

        assert self._run(mock_session) == 0
        mock_send.assert_not_called()

    def test_held_no_longer_than_the_max_hold(
        self, _configured, mock_session, mock_list, mock_last, mock_send, _record
    ):
        mock_list.return_value = [_due(minutes_ago=16)]
        mock_last.return_value = datetime.now(tz.utc) - timedelta(seconds=30)

        assert self._run(mock_session, max_hold=900) == 1
        mock_send.assert_called_once()

    def test_a_failed_check_sends_rather_than_holds(
        self, _configured, mock_session, mock_list, mock_last, mock_send, _record
    ):
        mock_list.return_value = [_due()]
        mock_last.side_effect = RuntimeError

        assert self._run(mock_session) == 1

    def test_one_held_push_does_not_block_another_requesters(
        self, _configured, mock_session, mock_list, mock_last, mock_send, _record
    ):
        busy, quiet = _due(), _due()
        mock_list.return_value = [busy, quiet]
        recent = datetime.now(tz.utc) - timedelta(seconds=10)
        mock_last.side_effect = lambda **kwargs: (
            recent if kwargs["user_id"] == busy.requester_id else None
        )

        assert self._run(mock_session) == 1
        mock_send.assert_called_once_with(quiet.id)

    def test_gap_zero_sends_without_checking(
        self, _configured, mock_session, mock_list, mock_last, mock_send, _record
    ):
        mock_list.return_value = [_due(minutes_ago=0)]

        assert self._run(mock_session, gap=0) == 1
        mock_last.assert_not_called()

    def test_no_queue_does_nothing(
        self, mock_configured, mock_session, mock_list, _last, mock_send, _record
    ):
        mock_configured.return_value = False

        assert self._run(mock_session) == 0
        mock_list.assert_not_called()

    def test_held_prayers_are_recorded_before_due_pushes_are_listed(
        self, _configured, mock_session, mock_list, _last, _send, mock_record
    ):
        """A push recorded by the sweep goes through the same gap as any other."""
        order = []
        mock_record.side_effect = lambda: order.append("record") or 0
        mock_list.side_effect = lambda **_: order.append("list") or []

        self._run(mock_session)

        assert order == ["record", "list"]

    def test_no_queue_records_nothing(
        self, mock_configured, mock_session, mock_list, _last, _send, mock_record
    ):
        mock_configured.return_value = False

        self._run(mock_session)

        mock_record.assert_not_called()


@patch(f"{DISPATCH}._create_prayer_notification_if_due")
@patch(f"{DISPATCH}.list_prayer_requests_with_held_prayers")
@patch(f"{DISPATCH}.SessionLocal")
class TestRecordHeldPrayerNotifications:
    """Prayers the interval held are reported once it passes, even when nobody
    prays for the request again."""

    def _run(self, mock_session, interval=900):
        from pecha_api.chat.notification_dispatch_service import (
            _record_held_prayer_notifications,
        )

        _session(mock_session)
        values = {
            "PRAYER_RECEIVED_NOTIFICATION_INTERVAL_SECONDS": interval,
            "CHAT_NOTIFICATION_DISPATCH_RECONCILE_BATCH_SIZE": 50,
        }
        with patch(f"{DISPATCH}.get_int", side_effect=lambda key: values[key]):
            return _record_held_prayer_notifications()

    def test_lists_requests_whose_last_push_is_older_than_the_interval(
        self, mock_session, mock_list, _create
    ):
        mock_list.return_value = []

        before = datetime.now(tz.utc)
        self._run(mock_session, interval=900)
        after = datetime.now(tz.utc)

        kwargs = mock_list.call_args.kwargs
        interval = timedelta(seconds=900)
        assert before - interval <= kwargs["last_push_before"] <= after - interval
        assert kwargs["limit"] == 50

    def test_records_a_push_for_each_due_request(self, mock_session, mock_list, mock_create):
        first, second = uuid4(), uuid4()
        mock_list.return_value = [first, second]
        mock_create.side_effect = [uuid4(), None]

        assert self._run(mock_session) == 1

        assert [call.kwargs for call in mock_create.call_args_list] == [
            {"message_id": first},
            {"message_id": second},
        ]

    def test_one_failure_does_not_stop_the_rest(self, mock_session, mock_list, mock_create):
        mock_list.return_value = [uuid4(), uuid4()]
        mock_create.side_effect = [RuntimeError, uuid4()]

        assert self._run(mock_session) == 1

    def test_a_failed_listing_records_nothing(self, mock_session, mock_list, mock_create):
        mock_list.side_effect = RuntimeError

        assert self._run(mock_session) == 0
        mock_create.assert_not_called()


class TestReconcilePrayerNotifications:

    @patch(f"{DISPATCH}._send_prayer_notification", return_value="sqs-2")
    @patch(f"{DISPATCH}.list_undispatched_prayer_notifications")
    @patch(f"{DISPATCH}.get_int", return_value=60)
    @patch(f"{DISPATCH}.SessionLocal")
    @patch(f"{DISPATCH}.is_prayer_notification_sqs_configured", return_value=True)
    def test_resends_unsent_pushes_without_re_gating(
        self, _configured, mock_session, _get_int, mock_list, mock_send
    ):
        from pecha_api.chat.notification_dispatch_service import (
            reconcile_undispatched_prayer_notifications,
        )

        _session(mock_session)
        rows = [MagicMock(id=uuid4()), MagicMock(id=uuid4())]
        mock_list.return_value = rows

        assert reconcile_undispatched_prayer_notifications() == 2
        assert [call.args[0] for call in mock_send.call_args_list] == [
            row.id for row in rows
        ]

    @patch(f"{DISPATCH}.list_undispatched_prayer_notifications")
    @patch(f"{DISPATCH}.is_prayer_notification_sqs_configured", return_value=False)
    def test_no_queue_does_nothing(self, _configured, mock_list):
        from pecha_api.chat.notification_dispatch_service import (
            reconcile_undispatched_prayer_notifications,
        )

        assert reconcile_undispatched_prayer_notifications() == 0
        mock_list.assert_not_called()
