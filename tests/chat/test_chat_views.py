from unittest.mock import patch, MagicMock
from uuid import uuid4
from datetime import datetime, timezone as tz

from fastapi import HTTPException
from starlette import status

from pecha_api.chat.response_models import (
    ChatMessageDTO,
    ChatMessagesResponse,
    ChatPeopleResponse,
    ChatPersonDTO,
    ChatRoomDTO,
    ChatRoomMembersResponse,
    ChatRoomsResponse,
)


def get_client():
    from pecha_api.app import api
    from fastapi.testclient import TestClient
    return TestClient(api)


AUTH_HEADERS = {"Authorization": "Bearer test-token"}


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


def _room_dto(room_id=None) -> ChatRoomDTO:
    return ChatRoomDTO(
        id=room_id or uuid4(),
        group_id=uuid4(),
        kind="GROUP",
        name="My Group Chat",
        img_url=None,
        created_by=uuid4(),
        member_count=1,
        updated_at=datetime.now(tz.utc).isoformat(),
        last_message=None,
        unread_count=0,
    )


class TestListMyRooms:

    @patch('pecha_api.chat.views.list_my_rooms_service')
    @patch('pecha_api.chat.views.validate_and_extract_user_details')
    def test_list_rooms(self, mock_validate, mock_service):
        client = get_client()
        mock_validate.return_value = MagicMock()
        mock_service.return_value = ChatRoomsResponse(rooms=[_room_dto()], skip=0, limit=20, total=1)

        response = client.get("/chat/rooms", headers=AUTH_HEADERS)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["total"] == 1

    def test_requires_auth(self):
        client = get_client()

        response = client.get("/chat/rooms")

        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestSendGroupMessage:

    @patch('pecha_api.chat.views.send_group_message_service')
    @patch('pecha_api.chat.views.validate_and_extract_user_details')
    def test_send_message_creates_or_reuses_room(self, mock_validate, mock_service):
        client = get_client()
        group_id = uuid4()
        mock_validate.return_value = MagicMock()
        mock_service.return_value = _message_dto()

        response = client.post(
            f"/chat/groups/{group_id}/messages",
            headers=AUTH_HEADERS,
            json={"body": "Hello group"},
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["body"] == "Hello"

    @patch('pecha_api.chat.views.send_group_message_service')
    @patch('pecha_api.chat.views.validate_and_extract_user_details')
    def test_rejects_blank_body(self, mock_validate, mock_service):
        client = get_client()

        response = client.post(
            f"/chat/groups/{uuid4()}/messages",
            headers=AUTH_HEADERS,
            json={"body": "   "},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        mock_service.assert_not_called()

    @patch('pecha_api.chat.views.send_group_message_service')
    @patch('pecha_api.chat.views.validate_and_extract_user_details')
    def test_propagates_forbidden_from_service(self, mock_validate, mock_service):
        client = get_client()
        mock_validate.return_value = MagicMock()
        mock_service.side_effect = HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

        response = client.post(
            f"/chat/groups/{uuid4()}/messages",
            headers=AUTH_HEADERS,
            json={"body": "Hello"},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestListGroupPeople:

    @patch('pecha_api.chat.views.list_group_people_service')
    @patch('pecha_api.chat.views.validate_and_extract_user_details')
    def test_list_people(self, mock_validate, mock_service):
        client = get_client()
        mock_validate.return_value = MagicMock()
        mock_service.return_value = ChatPeopleResponse(
            people=[ChatPersonDTO(user_id=uuid4(), email="bob@example.com", firstname="Bob", lastname="Smith")],
            skip=0,
            limit=50,
            total=1,
        )

        response = client.get(f"/chat/groups/{uuid4()}/people", headers=AUTH_HEADERS)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["total"] == 1
        assert response.json()["people"][0]["email"] == "bob@example.com"

    def test_requires_auth(self):
        client = get_client()

        response = client.get(f"/chat/groups/{uuid4()}/people")

        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestSendDirectMessage:

    @patch('pecha_api.chat.views.send_direct_message_service')
    @patch('pecha_api.chat.views.validate_and_extract_user_details')
    def test_send_dm(self, mock_validate, mock_service):
        client = get_client()
        mock_validate.return_value = MagicMock()
        mock_service.return_value = _message_dto()

        response = client.post(
            f"/chat/users/{uuid4()}/messages",
            headers=AUTH_HEADERS,
            json={"body": "Hey there"},
        )

        assert response.status_code == status.HTTP_201_CREATED


class TestRoomMembers:

    @patch('pecha_api.chat.views.add_room_members_service')
    @patch('pecha_api.chat.views.validate_and_extract_user_details')
    def test_add_members(self, mock_validate, mock_service):
        client = get_client()
        mock_validate.return_value = MagicMock()
        mock_service.return_value = ChatRoomMembersResponse(members=[], skip=0, limit=1000, total=0)

        response = client.post(
            f"/chat/rooms/{uuid4()}/members",
            headers=AUTH_HEADERS,
            json={"user_ids": [str(uuid4())]},
        )

        assert response.status_code == status.HTTP_200_OK

    @patch('pecha_api.chat.views.remove_room_member_service')
    @patch('pecha_api.chat.views.validate_and_extract_user_details')
    def test_remove_member(self, mock_validate, mock_service):
        client = get_client()
        mock_validate.return_value = MagicMock()
        mock_service.return_value = None

        response = client.delete(
            f"/chat/rooms/{uuid4()}/members/{uuid4()}",
            headers=AUTH_HEADERS,
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT


class TestRoomMessages:

    @patch('pecha_api.chat.views.list_room_messages_service')
    @patch('pecha_api.chat.views.validate_and_extract_user_details')
    def test_list_messages(self, mock_validate, mock_service):
        client = get_client()
        mock_validate.return_value = MagicMock()
        mock_service.return_value = ChatMessagesResponse(messages=[_message_dto()], skip=0, limit=20, total=1)

        response = client.get(f"/chat/rooms/{uuid4()}/messages", headers=AUTH_HEADERS)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["total"] == 1

    @patch('pecha_api.chat.views.delete_message_service')
    @patch('pecha_api.chat.views.validate_and_extract_user_details')
    def test_delete_message(self, mock_validate, mock_service):
        client = get_client()
        mock_validate.return_value = MagicMock()
        mock_service.return_value = datetime.now(tz.utc).isoformat()

        response = client.delete(
            f"/chat/rooms/{uuid4()}/messages/{uuid4()}",
            headers=AUTH_HEADERS,
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT

    @patch('pecha_api.chat.views.get_broadcaster')
    @patch('pecha_api.chat.views.delete_message_service')
    @patch('pecha_api.chat.views.validate_and_extract_user_details')
    def test_delete_message_broadcasts_deletion(self, mock_validate, mock_service, mock_get_broadcaster):
        from unittest.mock import AsyncMock

        client = get_client()
        user = MagicMock()
        user.id = uuid4()
        user.email = "sender@example.com"
        user.firstname = "Sender"
        user.lastname = "Name"
        mock_validate.return_value = user
        deleted_at = datetime.now(tz.utc).isoformat()
        mock_service.return_value = deleted_at
        broadcaster = MagicMock()
        broadcaster.broadcast_message_deleted = AsyncMock()
        mock_get_broadcaster.return_value = broadcaster
        room_id, message_id = uuid4(), uuid4()

        response = client.delete(
            f"/chat/rooms/{room_id}/messages/{message_id}",
            headers=AUTH_HEADERS,
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        broadcaster.broadcast_message_deleted.assert_awaited_once_with(
            room_id=room_id,
            message_id=message_id,
            deleted_by={"user_id": str(user.id), "email": user.email, "name": "Sender Name"},
            deleted_at=deleted_at,
        )

    @patch('pecha_api.chat.views.get_broadcaster')
    @patch('pecha_api.chat.views.delete_message_service')
    @patch('pecha_api.chat.views.validate_and_extract_user_details')
    def test_delete_message_broadcast_failure_does_not_fail_request(
        self, mock_validate, mock_service, mock_get_broadcaster
    ):
        client = get_client()
        mock_validate.return_value = MagicMock()
        mock_service.return_value = datetime.now(tz.utc).isoformat()
        mock_get_broadcaster.side_effect = RuntimeError("redis down")

        response = client.delete(
            f"/chat/rooms/{uuid4()}/messages/{uuid4()}",
            headers=AUTH_HEADERS,
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT


class TestBulkDeleteMessages:

    @patch('pecha_api.chat.views.get_broadcaster')
    @patch('pecha_api.chat.views.delete_messages_service')
    @patch('pecha_api.chat.views.validate_and_extract_user_details')
    def test_bulk_delete_messages(self, mock_validate, mock_service, mock_get_broadcaster):
        from unittest.mock import AsyncMock
        from pecha_api.chat.message_service import BulkDeleteResult

        client = get_client()
        user = MagicMock()
        user.id = uuid4()
        user.email = "sender@example.com"
        user.firstname = "Sender"
        user.lastname = "Name"
        mock_validate.return_value = user
        room_id = uuid4()
        message_ids = [uuid4(), uuid4()]
        deleted_at = datetime.now(tz.utc).isoformat()
        mock_service.return_value = BulkDeleteResult(message_ids=message_ids, deleted_at=deleted_at)
        broadcaster = MagicMock()
        broadcaster.broadcast_message_deleted = AsyncMock()
        mock_get_broadcaster.return_value = broadcaster

        response = client.request(
            "DELETE",
            f"/chat/rooms/{room_id}/messages",
            headers=AUTH_HEADERS,
            json={"message_ids": [str(message_id) for message_id in message_ids]},
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert mock_service.call_args.kwargs["message_ids"] == message_ids
        # One message_deleted event per message, so clients grey each out live.
        assert broadcaster.broadcast_message_deleted.await_count == 2
        for message_id, call in zip(message_ids, broadcaster.broadcast_message_deleted.await_args_list):
            assert call.kwargs == {
                "room_id": room_id,
                "message_id": message_id,
                "deleted_by": {"user_id": str(user.id), "email": user.email, "name": "Sender Name"},
                "deleted_at": deleted_at,
            }

    @patch('pecha_api.chat.views.delete_messages_service')
    @patch('pecha_api.chat.views.validate_and_extract_user_details')
    def test_bulk_delete_rejects_other_users_messages(self, mock_validate, mock_service):
        client = get_client()
        mock_validate.return_value = MagicMock()
        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="message_ids include other users' messages: abc",
        )

        response = client.request(
            "DELETE",
            f"/chat/rooms/{uuid4()}/messages",
            headers=AUTH_HEADERS,
            json={"message_ids": [str(uuid4())]},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "other users" in response.json()["detail"]

    @patch('pecha_api.chat.views.delete_messages_service')
    @patch('pecha_api.chat.views.validate_and_extract_user_details')
    def test_bulk_delete_rejects_empty_selection(self, mock_validate, mock_service):
        client = get_client()
        mock_validate.return_value = MagicMock()

        response = client.request(
            "DELETE",
            f"/chat/rooms/{uuid4()}/messages",
            headers=AUTH_HEADERS,
            json={"message_ids": []},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        mock_service.assert_not_called()

    @patch('pecha_api.chat.views.get_broadcaster')
    @patch('pecha_api.chat.views.delete_messages_service')
    @patch('pecha_api.chat.views.validate_and_extract_user_details')
    def test_bulk_delete_broadcast_failure_does_not_fail_request(
        self, mock_validate, mock_service, mock_get_broadcaster
    ):
        from pecha_api.chat.message_service import BulkDeleteResult

        client = get_client()
        mock_validate.return_value = MagicMock()
        mock_service.return_value = BulkDeleteResult(
            message_ids=[uuid4()], deleted_at=datetime.now(tz.utc).isoformat()
        )
        mock_get_broadcaster.side_effect = RuntimeError("redis down")

        response = client.request(
            "DELETE",
            f"/chat/rooms/{uuid4()}/messages",
            headers=AUTH_HEADERS,
            json={"message_ids": [str(uuid4())]},
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT


class TestRoomDetailAndProfile:

    @patch('pecha_api.chat.views.get_room_detail_service')
    @patch('pecha_api.chat.views.validate_and_extract_user_details')
    def test_get_room_detail(self, mock_validate, mock_service):
        client = get_client()
        room = _room_dto()
        mock_validate.return_value = MagicMock()
        mock_service.return_value = room

        response = client.get(f"/chat/rooms/{room.id}", headers=AUTH_HEADERS)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["id"] == str(room.id)

    @patch('pecha_api.chat.views.update_room_profile_service')
    @patch('pecha_api.chat.views.validate_and_extract_user_details')
    def test_update_room_profile(self, mock_validate, mock_service):
        client = get_client()
        room = _room_dto()
        mock_validate.return_value = MagicMock()
        mock_service.return_value = room

        response = client.patch(
            f"/chat/rooms/{room.id}",
            headers=AUTH_HEADERS,
            json={"name": "Renamed"},
        )

        assert response.status_code == status.HTTP_200_OK
        mock_service.assert_called_once()

    @patch('pecha_api.chat.views.mark_room_read_service')
    @patch('pecha_api.chat.views.validate_and_extract_user_details')
    def test_mark_room_read(self, mock_validate, mock_service):
        client = get_client()
        mock_validate.return_value = MagicMock()
        mock_service.return_value = None

        response = client.post(f"/chat/rooms/{uuid4()}/read", headers=AUTH_HEADERS)

        assert response.status_code == status.HTTP_204_NO_CONTENT

    @patch('pecha_api.chat.views.list_room_members_service')
    @patch('pecha_api.chat.views.validate_and_extract_user_details')
    def test_list_room_members(self, mock_validate, mock_service):
        client = get_client()
        mock_validate.return_value = MagicMock()
        mock_service.return_value = ChatRoomMembersResponse(members=[], skip=0, limit=20, total=0)

        response = client.get(f"/chat/rooms/{uuid4()}/members", headers=AUTH_HEADERS)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["total"] == 0


class TestMessageReactions:

    @patch('pecha_api.chat.views.add_message_reaction_service')
    @patch('pecha_api.chat.views.validate_and_extract_user_details')
    def test_add_reaction(self, mock_validate, mock_service):
        from pecha_api.chat.response_models import ChatMessageReactionDTO
        client = get_client()
        mock_validate.return_value = MagicMock()
        mock_service.return_value = [
            ChatMessageReactionDTO(emoji="🙏", count=2, reacted_by_me=True)
        ]

        response = client.post(
            f"/chat/rooms/{uuid4()}/messages/{uuid4()}/reactions",
            json={"emoji": "🙏"},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data[0]["emoji"] == "🙏"
        assert data[0]["count"] == 2
        assert data[0]["reacted_by_me"] is True

    @patch('pecha_api.chat.views.validate_and_extract_user_details')
    def test_add_reaction_empty_emoji_rejected(self, mock_validate):
        client = get_client()
        mock_validate.return_value = MagicMock()

        response = client.post(
            f"/chat/rooms/{uuid4()}/messages/{uuid4()}/reactions",
            json={"emoji": "   "},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    @patch('pecha_api.chat.views.remove_message_reaction_service')
    @patch('pecha_api.chat.views.validate_and_extract_user_details')
    def test_remove_reaction(self, mock_validate, mock_service):
        client = get_client()
        mock_validate.return_value = MagicMock()
        mock_service.return_value = []

        response = client.delete(
            f"/chat/rooms/{uuid4()}/messages/{uuid4()}/reactions/🙏",
            headers=AUTH_HEADERS,
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []


class TestReportMessage:

    @patch('pecha_api.chat.views.report_message_service')
    @patch('pecha_api.chat.views.validate_and_extract_user_details')
    def test_report_message(self, mock_validate, mock_service):
        client = get_client()
        mock_validate.return_value = MagicMock()
        mock_service.return_value = None

        response = client.post(
            f"/chat/rooms/{uuid4()}/messages/{uuid4()}/report",
            json={"reason": "SPAM", "description": "Repeated ads"},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_service.assert_called_once()

    @patch('pecha_api.chat.views.validate_and_extract_user_details')
    def test_report_invalid_reason_rejected(self, mock_validate):
        client = get_client()
        mock_validate.return_value = MagicMock()

        response = client.post(
            f"/chat/rooms/{uuid4()}/messages/{uuid4()}/report",
            json={"reason": "NOT_A_REASON"},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


class TestSendReplyViaRest:

    @patch('pecha_api.chat.views.send_group_message_service')
    @patch('pecha_api.chat.views.validate_and_extract_user_details')
    def test_send_group_reply_passes_parent(self, mock_validate, mock_service):
        client = get_client()
        mock_validate.return_value = MagicMock()
        parent_id = uuid4()
        mock_service.return_value = _message_dto()

        response = client.post(
            f"/chat/groups/{uuid4()}/messages",
            json={"body": "A reply", "parent_message_id": str(parent_id)},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert mock_service.call_args.kwargs["parent_message_id"] == parent_id
