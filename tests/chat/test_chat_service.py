import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4
from datetime import datetime, timezone as tz
from fastapi import HTTPException
from starlette import status

# Import the app first so the full SQLAlchemy model registry is configured
# before any ChatRoom()/ChatRoomMember() instantiation below triggers mapper configuration.
import pecha_api.app  # noqa: F401

from pecha_api.chat.service import (
    _default_group_room_name,
    _generate_presigned_url,
    _get_room_or_404,
    _isoformat,
    _require_active_member,
    build_message_dto,
    build_room_dto,
    get_room_detail_service,
    leave_group_chat_room,
    list_group_people_service,
    list_my_rooms_service,
    mark_room_read_service,
    close_group_chat_sockets,
    resolve_or_create_group_room,
    resolve_or_create_private_room,
    update_room_profile_service,
)


class MockUser:
    def __init__(self, user_id=None, email="user@example.com", firstname="Alice", lastname=None, avatar_url=None):
        self.id = user_id or uuid4()
        self.email = email
        self.firstname = firstname
        self.lastname = lastname
        self.avatar_url = avatar_url


class MockMessage:
    def __init__(self, sender=None, sender_id=None, room_id=None, body="Hello", parent=None):
        self.id = uuid4()
        self.room_id = room_id or uuid4()
        self.sender_id = sender_id or uuid4()
        self.sender = sender or MockUser(user_id=self.sender_id)
        self.body = body
        self.created_at = datetime.now(tz.utc)
        self.deleted_at = None
        self.parent = parent
        self.parent_message_id = parent.id if parent else None


class MockGroup:
    def __init__(self, id=None, avatar_key=None, metadata_entries=None, slug="my-group"):
        self.id = id or uuid4()
        self.avatar_key = avatar_key
        self.metadata_entries = metadata_entries or []
        self.slug = slug
        # Published by default; these cases test is_public on live groups.
        self.status = "PUBLISHED"


class TestBuildMessageDTO:
    def test_uses_placeholder_email_when_sender_missing(self):
        message = MockMessage()
        message.sender = None

        dto = build_message_dto(message)

        assert dto.sender_email == "unknown@example.com"

    @patch('pecha_api.chat.service.generate_presigned_access_url')
    def test_sender_avatar_url_is_presigned(self, mock_presign):
        mock_presign.return_value = "https://s3.example.com/signed?sig=abc"
        sender = MockUser(avatar_url="avatars/user-123.png")
        message = MockMessage(sender=sender)

        dto = build_message_dto(message)

        assert mock_presign.call_args.kwargs["s3_key"] == "avatars/user-123.png"
        assert dto.sender_avatar_url == "https://s3.example.com/signed?sig=abc"

    def test_sender_avatar_url_none_when_sender_has_no_avatar(self):
        sender = MockUser(avatar_url=None)
        message = MockMessage(sender=sender)

        dto = build_message_dto(message)

        assert dto.sender_avatar_url is None

    def test_includes_parent_when_parent_exists(self):
        parent_sender = MockUser(email="parent@example.com", firstname="Bob", lastname="Smith")
        parent = MockMessage(sender=parent_sender, sender_id=parent_sender.id, body="Original")
        reply = MockMessage(body="Reply", parent=parent)

        dto = build_message_dto(reply)
        payload = dto.model_dump()

        assert dto.parent is not None
        assert dto.parent.id == parent.id
        assert dto.parent.body == "Original"
        assert dto.parent.sender_id == parent_sender.id
        assert dto.parent.sender_email == "parent@example.com"
        assert dto.parent.sender_name == "Bob Smith"
        assert dto.parent.deleted_at is None
        assert "deleted_at" not in payload["parent"]

    def test_includes_deleted_parent_without_content(self):
        deleted_at = datetime.now(tz.utc)
        parent_sender = MockUser(email="parent@example.com", firstname="Bob", lastname="Smith")
        parent = MockMessage(sender=parent_sender, sender_id=parent_sender.id, body="Secret content")
        parent.deleted_at = deleted_at
        reply = MockMessage(body="Reply", parent=parent)

        dto = build_message_dto(reply)
        payload = dto.model_dump()

        assert dto.parent is not None
        assert dto.parent.id == parent.id
        assert dto.parent.body == ""
        assert dto.parent.sender_id == parent_sender.id
        assert dto.parent.sender_email == "parent@example.com"
        assert dto.parent.sender_name == "Bob Smith"
        assert dto.parent.deleted_at == deleted_at.isoformat()
        assert payload["parent"]["deleted_at"] == deleted_at.isoformat()
        assert payload["parent"]["body"] == ""

    def test_deleted_message_clears_body_and_keeps_sender(self):
        deleted_at = datetime.now(tz.utc)
        sender = MockUser(email="alice@example.com", firstname="Alice")
        message = MockMessage(sender=sender, sender_id=sender.id, body="Secret content")
        message.deleted_at = deleted_at

        dto = build_message_dto(message)
        payload = dto.model_dump()

        assert dto.body == ""
        assert dto.sender_email == "alice@example.com"
        assert dto.sender_name == "Alice"
        assert dto.deleted_at == deleted_at.isoformat()
        assert payload["deleted_at"] == deleted_at.isoformat()


class MockRoom:
    def __init__(self, id=None, group_id=None, sender_id=None, receiver_id=None, name="Room", created_by=None):
        self.id = id or uuid4()
        self.group_id = group_id
        self.sender_id = sender_id
        self.receiver_id = receiver_id
        self.name = name
        self.img_url = None
        self.created_by = created_by or uuid4()
        self.updated_at = datetime.now(tz.utc)


class TestBuildRoomDTO:

    @patch('pecha_api.chat.service.count_unread_messages')
    @patch('pecha_api.chat.service.get_active_member')
    @patch('pecha_api.chat.service.count_active_members')
    @patch('pecha_api.chat.service.get_last_message')
    def test_group_room_has_no_other_user_fields(
        self, mock_last_message, mock_count_active, mock_get_active, mock_unread
    ):
        room = MockRoom(group_id=uuid4())
        mock_last_message.return_value = None
        mock_count_active.return_value = 2
        mock_get_active.return_value = None
        mock_unread.return_value = 0

        dto = build_room_dto(db=MagicMock(), room=room, viewer_id=uuid4())

        assert dto.kind == "GROUP"
        assert dto.other_user_id is None
        assert dto.other_user_email is None

    @patch('pecha_api.chat.service.count_unread_messages')
    @patch('pecha_api.chat.service.get_active_member')
    @patch('pecha_api.chat.service.count_active_members')
    @patch('pecha_api.chat.service.get_last_message')
    def test_private_room_resolves_other_participant(
        self, mock_last_message, mock_count_active, mock_get_active, mock_unread
    ):
        viewer_id = uuid4()
        other_id = uuid4()
        room = MockRoom(sender_id=viewer_id, receiver_id=other_id)
        mock_last_message.return_value = None
        mock_count_active.return_value = 2
        mock_get_active.return_value = None
        mock_unread.return_value = 0

        other_user = MockUser(user_id=other_id, email="other@example.com", firstname="Bob")
        other_user.lastname = "Smith"
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = other_user

        dto = build_room_dto(db=mock_db, room=room, viewer_id=viewer_id)

        assert dto.kind == "PRIVATE"
        assert dto.other_user_id == other_id
        assert dto.other_user_email == "other@example.com"
        assert dto.other_user_name == "Bob Smith"


class TestListGroupPeopleService:

    @patch('pecha_api.chat.service.list_group_joiners_paginated')
    @patch('pecha_api.chat.service.get_group_by_id')
    @patch('pecha_api.chat.service.SessionLocal')
    def test_excludes_caller_from_results(self, mock_session, mock_get_group, mock_list_joiners):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get_group.return_value = MockGroup()
        caller = MockUser()
        other = MockUser(email="other@example.com", firstname="Bob")
        other.lastname = "Smith"
        other.avatar_url = None
        mock_list_joiners.return_value = ([caller, other], 2)

        result = list_group_people_service(group_id=uuid4(), user=caller, skip=0, limit=50)

        assert result.total == 2
        assert len(result.people) == 1
        assert result.people[0].email == "other@example.com"

    @patch('pecha_api.chat.service.get_group_by_id')
    @patch('pecha_api.chat.service.SessionLocal')
    def test_group_not_found(self, mock_session, mock_get_group):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get_group.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            list_group_people_service(group_id=uuid4(), user=MockUser(), skip=0, limit=50)

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


class TestResolveOrCreateGroupRoom:

    @patch('pecha_api.chat.service.add_member')
    @patch('pecha_api.chat.service.create_room')
    @patch('pecha_api.chat.service.is_user_following_group')
    @patch('pecha_api.chat.service.is_user_joined_group')
    @patch('pecha_api.chat.service.get_group_by_id')
    @patch('pecha_api.chat.service.is_group_id_published', return_value=True)
    @patch('pecha_api.chat.service.get_room_by_group_id')
    def test_creates_room_and_creator_membership_on_first_message(
        self, mock_get_room, _mock_published, mock_get_group, mock_joined, mock_following,
        mock_create_room, mock_add_member,
    ):
        group_id = uuid4()
        user = MockUser()
        mock_get_room.return_value = None
        mock_get_group.return_value = MockGroup(id=group_id)
        mock_joined.return_value = True
        mock_following.return_value = False

        created_room = MagicMock(id=uuid4(), group_id=group_id)
        mock_create_room.return_value = created_room

        result = resolve_or_create_group_room(db=MagicMock(), group_id=group_id, user=user)

        assert result is created_room
        mock_add_member.assert_called_once()
        member_arg = mock_add_member.call_args.kwargs["member"]
        assert member_arg.role == "CREATOR"
        assert member_arg.user_id == user.id

    @patch('pecha_api.chat.service.is_group_id_published', return_value=True)
    @patch('pecha_api.chat.service.get_room_by_group_id')
    def test_reuses_existing_room(self, mock_get_room, _mock_published):
        existing_room = MagicMock()
        mock_get_room.return_value = existing_room

        result = resolve_or_create_group_room(db=MagicMock(), group_id=uuid4(), user=MockUser())

        assert result is existing_room

    @patch('pecha_api.chat.service.is_group_id_published', return_value=False)
    @patch('pecha_api.chat.service.get_room_by_group_id')
    def test_existing_room_rejected_when_group_hidden(self, mock_get_room, _mock_published):
        """A room created while the group was live must stop serving once the
        group is hidden, so members cannot keep messaging through it."""
        mock_get_room.return_value = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            resolve_or_create_group_room(db=MagicMock(), group_id=uuid4(), user=MockUser())

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @patch('pecha_api.chat.service.is_user_following_group')
    @patch('pecha_api.chat.service.is_user_joined_group')
    @patch('pecha_api.chat.service.get_group_by_id')
    @patch('pecha_api.chat.service.is_group_id_published', return_value=True)
    @patch('pecha_api.chat.service.get_room_by_group_id')
    def test_ineligible_user_forbidden(
        self, mock_get_room, _mock_published, mock_get_group, mock_joined, mock_following
    ):
        mock_get_room.return_value = None
        mock_get_group.return_value = MockGroup()
        mock_joined.return_value = False
        mock_following.return_value = False

        with pytest.raises(HTTPException) as exc_info:
            resolve_or_create_group_room(db=MagicMock(), group_id=uuid4(), user=MockUser())

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @patch('pecha_api.chat.service.get_group_by_id')
    @patch('pecha_api.chat.service.get_room_by_group_id')
    def test_group_not_found(self, mock_get_room, mock_get_group):
        mock_get_room.return_value = None
        mock_get_group.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            resolve_or_create_group_room(db=MagicMock(), group_id=uuid4(), user=MockUser())

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


class TestLeaveGroupChatRoom:

    @patch('pecha_api.chat.service.leave_member')
    @patch('pecha_api.chat.service.get_active_member')
    @patch('pecha_api.chat.service.get_room_by_group_id')
    def test_marks_active_member_as_left(self, mock_get_room, mock_get_active_member, mock_leave_member):
        room = MagicMock(id=uuid4())
        member = MagicMock()
        mock_get_room.return_value = room
        mock_get_active_member.return_value = member
        db = MagicMock()
        user_id = uuid4()

        leave_group_chat_room(db=db, group_id=uuid4(), user_id=user_id)

        mock_get_active_member.assert_called_once_with(db=db, room_id=room.id, user_id=user_id)
        mock_leave_member.assert_called_once_with(db=db, member=member)

    @patch('pecha_api.chat.service.leave_member')
    @patch('pecha_api.chat.service.get_active_member')
    @patch('pecha_api.chat.service.get_room_by_group_id')
    def test_noop_when_no_room(self, mock_get_room, mock_get_active_member, mock_leave_member):
        mock_get_room.return_value = None

        leave_group_chat_room(db=MagicMock(), group_id=uuid4(), user_id=uuid4())

        mock_get_active_member.assert_not_called()
        mock_leave_member.assert_not_called()

    @patch('pecha_api.chat.service.leave_member')
    @patch('pecha_api.chat.service.get_active_member')
    @patch('pecha_api.chat.service.get_room_by_group_id')
    def test_noop_when_user_not_an_active_member(self, mock_get_room, mock_get_active_member, mock_leave_member):
        mock_get_room.return_value = MagicMock(id=uuid4())
        mock_get_active_member.return_value = None

        leave_group_chat_room(db=MagicMock(), group_id=uuid4(), user_id=uuid4())

        mock_leave_member.assert_not_called()


class TestResolveOrCreatePrivateRoom:

    @patch('pecha_api.chat.service.add_member')
    @patch('pecha_api.chat.service.create_room')
    @patch('pecha_api.chat.service.get_room_by_pair')
    def test_creates_normalized_pair_room_on_first_message(
        self, mock_get_pair, mock_create_room, mock_add_member
    ):
        user_a = MockUser(user_id=uuid4())
        user_b_id = uuid4()
        other = MockUser(user_id=user_b_id)
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = other
        mock_get_pair.return_value = None
        created_room = MagicMock(id=uuid4())
        mock_create_room.return_value = created_room

        result = resolve_or_create_private_room(db=mock_db, user=user_a, receiver_id=user_b_id)

        assert result is created_room
        low_id, high_id = sorted([user_a.id, user_b_id])
        mock_get_pair.assert_called_once_with(db=mock_db, low_id=low_id, high_id=high_id)
        assert mock_add_member.call_count == 2

    @patch('pecha_api.chat.service.get_room_by_pair')
    def test_reuses_existing_room_regardless_of_direction(self, mock_get_pair):
        user_a = MockUser(user_id=uuid4())
        user_b_id = uuid4()
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = MockUser(user_id=user_b_id)
        existing_room = MagicMock()
        mock_get_pair.return_value = existing_room

        result = resolve_or_create_private_room(db=mock_db, user=user_a, receiver_id=user_b_id)

        assert result is existing_room

    def test_cannot_dm_self(self):
        user = MockUser()

        with pytest.raises(HTTPException) as exc_info:
            resolve_or_create_private_room(db=MagicMock(), user=user, receiver_id=user.id)

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST

    def test_receiver_not_found(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            resolve_or_create_private_room(db=mock_db, user=MockUser(), receiver_id=uuid4())

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


class TestHelpers:

    def test_isoformat_none(self):
        assert _isoformat(None) is None

    def test_isoformat_datetime(self):
        value = datetime.now(tz.utc)
        assert _isoformat(value) == value.isoformat()

    def test_isoformat_fallback_str(self):
        assert _isoformat(123) == "123"

    def test_generate_presigned_url_none_key(self):
        assert _generate_presigned_url(None) is None

    @patch('pecha_api.chat.service.generate_presigned_access_url', return_value="https://signed")
    @patch('pecha_api.chat.service.get', return_value="bucket")
    def test_generate_presigned_url_success(self, mock_get, mock_presign):
        assert _generate_presigned_url("path/key.jpg") == "https://signed"
        mock_presign.assert_called_once()

    @patch('pecha_api.chat.service.generate_presigned_access_url', side_effect=RuntimeError("aws"))
    @patch('pecha_api.chat.service.get', return_value="bucket")
    def test_generate_presigned_url_failure_returns_none(self, mock_get, mock_presign):
        assert _generate_presigned_url("path/key.jpg") is None

    def test_default_group_room_name_uses_metadata_title(self):
        group = MockGroup(metadata_entries=[MagicMock(title="Sangha Chat")])
        assert _default_group_room_name(group) == "Sangha Chat"

    def test_default_group_room_name_falls_back_to_slug(self):
        group = MockGroup(metadata_entries=[], slug="fallback-slug")
        assert _default_group_room_name(group) == "fallback-slug"

    @patch('pecha_api.chat.service.get_room_by_id')
    def test_get_room_or_404_raises(self, mock_get):
        mock_get.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            _get_room_or_404(db=MagicMock(), room_id=uuid4())
        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @patch('pecha_api.chat.service.get_room_by_id')
    def test_get_room_or_404_returns_room(self, mock_get):
        room = MockRoom()
        mock_get.return_value = room
        assert _get_room_or_404(db=MagicMock(), room_id=room.id) is room

    @patch('pecha_api.chat.service.get_active_member')
    def test_require_active_member_raises(self, mock_get):
        mock_get.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            _require_active_member(db=MagicMock(), room_id=uuid4(), user_id=uuid4())
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @patch('pecha_api.chat.service.get_active_member')
    def test_require_active_member_returns_member(self, mock_get):
        member = MagicMock()
        mock_get.return_value = member
        assert _require_active_member(db=MagicMock(), room_id=uuid4(), user_id=uuid4()) is member



class TestRoomServices:

    @patch('pecha_api.chat.service.build_room_dto')
    @patch('pecha_api.chat.service._require_active_member')
    @patch('pecha_api.chat.service._get_room_or_404')
    @patch('pecha_api.chat.service.SessionLocal')
    def test_get_room_detail_service(self, mock_session, mock_get_room, mock_require, mock_build):
        mock_session.return_value.__enter__.return_value = MagicMock()
        room = MockRoom()
        mock_get_room.return_value = room
        mock_build.return_value = MagicMock()

        result = get_room_detail_service(room_id=room.id, user=MockUser())

        assert result is mock_build.return_value
        mock_require.assert_called_once()

    @patch('pecha_api.chat.service.build_room_dto')
    @patch('pecha_api.chat.service.get_last_messages_map')
    @patch('pecha_api.chat.service.list_my_active_rooms')
    @patch('pecha_api.chat.service.SessionLocal')
    def test_list_my_rooms_service(self, mock_session, mock_list, mock_last, mock_build):
        from pecha_api.chat.response_models import ChatRoomDTO

        mock_session.return_value.__enter__.return_value = MagicMock()
        room = MockRoom()
        mock_list.return_value = ([room], 1)
        mock_last.return_value = {}
        mock_build.return_value = ChatRoomDTO(
            id=room.id,
            kind="GROUP",
            name=room.name,
            created_by=room.created_by,
            member_count=1,
            updated_at=room.updated_at.isoformat(),
            unread_count=0,
        )

        result = list_my_rooms_service(user=MockUser(), skip=0, limit=20)

        assert result.total == 1
        assert len(result.rooms) == 1


    @patch('pecha_api.chat.service.build_room_dto')
    @patch('pecha_api.chat.service.update_room')
    @patch('pecha_api.chat.service._require_active_member')
    @patch('pecha_api.chat.service._get_room_or_404')
    @patch('pecha_api.chat.service.SessionLocal')
    def test_update_room_profile_as_creator(
        self, mock_session, mock_get_room, mock_require, mock_update, mock_build
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        room = MockRoom(group_id=uuid4())
        mock_get_room.return_value = room
        mock_require.return_value = MagicMock(role="CREATOR")
        mock_update.return_value = room
        mock_build.return_value = MagicMock()

        update_room_profile_service(
            room_id=room.id, user=MockUser(), name="New", img_url="key.jpg"
        )

        assert room.name == "New"
        assert room.img_url == "key.jpg"
        mock_update.assert_called_once()

    @patch('pecha_api.chat.service._require_active_member')
    @patch('pecha_api.chat.service._get_room_or_404')
    @patch('pecha_api.chat.service.SessionLocal')
    def test_update_group_room_profile_non_creator_forbidden(
        self, mock_session, mock_get_room, mock_require
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        room = MockRoom(group_id=uuid4())
        mock_get_room.return_value = room
        mock_require.return_value = MagicMock(role="MEMBER")

        with pytest.raises(HTTPException) as exc_info:
            update_room_profile_service(
                room_id=room.id, user=MockUser(), name="Nope", img_url=None
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @patch('pecha_api.chat.service.mark_read')
    @patch('pecha_api.chat.service._require_active_member')
    @patch('pecha_api.chat.service._get_room_or_404')
    @patch('pecha_api.chat.service.SessionLocal')
    def test_mark_room_read_service(self, mock_session, mock_get_room, mock_require, mock_mark):
        mock_session.return_value.__enter__.return_value = MagicMock()
        member = MagicMock()
        mock_require.return_value = member

        mark_room_read_service(room_id=uuid4(), user=MockUser())

        mock_mark.assert_called_once_with(db=mock_session.return_value.__enter__.return_value, member=member)


class TestGroupRoomStatusLocking:

    @patch('pecha_api.chat.service.get_room_by_group_id')
    @patch('pecha_api.chat.service.is_group_id_published', return_value=True)
    def test_lock_group_requests_row_lock(self, mock_published, mock_get_room):
        """The message-send path locks the group row so a concurrent hide
        cannot land between the status check and the commit."""
        mock_get_room.return_value = MagicMock()

        resolve_or_create_group_room(
            db=MagicMock(), group_id=uuid4(), user=MockUser(), lock_group=True
        )

        assert mock_published.call_args.kwargs["for_update"] is True

    @patch('pecha_api.chat.service.get_room_by_group_id')
    @patch('pecha_api.chat.service.is_group_id_published', return_value=True)
    def test_read_only_path_does_not_lock(self, mock_published, mock_get_room):
        mock_get_room.return_value = MagicMock()

        resolve_or_create_group_room(db=MagicMock(), group_id=uuid4(), user=MockUser())

        assert mock_published.call_args.kwargs["for_update"] is False


class TestRoomIdRoutesRespectGroupStatus:

    @patch('pecha_api.chat.service.is_group_id_published', return_value=False)
    @patch('pecha_api.chat.service.get_room_by_id')
    def test_group_room_404s_when_group_hidden(self, mock_get_room, _mock_published):
        """Every room-id route resolves through _get_room_or_404, so detail,
        history, reactions, reports and member ops close together."""
        mock_get_room.return_value = MagicMock(group_id=uuid4())

        with pytest.raises(HTTPException) as exc_info:
            _get_room_or_404(db=MagicMock(), room_id=uuid4())

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @patch('pecha_api.chat.service.is_group_id_published')
    @patch('pecha_api.chat.service.get_room_by_id')
    def test_dm_room_skips_the_group_check(self, mock_get_room, mock_published):
        """DM rooms have no group_id and no event_id, so they must never
        consult group status."""
        room = MagicMock(group_id=None, event_id=None)
        mock_get_room.return_value = room

        assert _get_room_or_404(db=MagicMock(), room_id=uuid4()) is room
        mock_published.assert_not_called()


class TestCloseGroupChatSockets:

    @patch('pecha_api.chat.chat_websocket.get_broadcaster')
    @patch('pecha_api.chat.service.get_room_by_group_id')
    @patch('pecha_api.chat.service.SessionLocal')
    def test_publishes_room_closed_for_the_groups_room(
        self, mock_session, mock_get_room, mock_get_broadcaster
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        room = MagicMock(id=uuid4())
        mock_get_room.return_value = room
        broadcaster = AsyncMock()
        mock_get_broadcaster.return_value = broadcaster

        asyncio.run(close_group_chat_sockets(group_id=uuid4()))

        broadcaster.broadcast_room_closed.assert_awaited_once()
        assert broadcaster.broadcast_room_closed.await_args.kwargs["room_id"] == room.id

    @patch('pecha_api.chat.chat_websocket.get_broadcaster')
    @patch('pecha_api.chat.service.get_room_by_group_id', return_value=None)
    @patch('pecha_api.chat.service.SessionLocal')
    def test_no_room_means_nothing_to_close(
        self, mock_session, _mock_get_room, mock_get_broadcaster
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()

        asyncio.run(close_group_chat_sockets(group_id=uuid4()))

        mock_get_broadcaster.assert_not_called()

    @patch('pecha_api.chat.chat_websocket.get_broadcaster')
    @patch('pecha_api.chat.service.get_room_by_group_id')
    @patch('pecha_api.chat.service.SessionLocal')
    def test_broadcast_failure_never_fails_the_hide(
        self, mock_session, mock_get_room, mock_get_broadcaster
    ):
        """The room is already gated at the request layer, so a Redis outage
        must not stop a coordinator hiding their group."""
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get_room.return_value = MagicMock(id=uuid4())
        mock_get_broadcaster.side_effect = RuntimeError("redis down")

        asyncio.run(close_group_chat_sockets(group_id=uuid4()))
