from unittest.mock import patch
from uuid import uuid4
from datetime import datetime, timezone as tz

from fastapi import HTTPException
from starlette import status

from pecha_api.chat.cms_service import CmsMessageDeletion


def get_client():
    from pecha_api.app import api
    from fastapi.testclient import TestClient
    return TestClient(api)


AUTH_HEADERS = {"Authorization": "Bearer test-token"}


def _url(group_id, message_id):
    return f"/cms/author/groups/{group_id}/chat/messages/{message_id}"


class TestCmsDeleteGroupChatMessage:

    @patch('pecha_api.chat.cms_views._broadcast_message_deleted_safe')
    @patch('pecha_api.chat.cms_views.cms_delete_group_chat_message_service')
    def test_deletes_and_broadcasts(self, mock_service, mock_broadcast):
        client = get_client()
        room_id = uuid4()
        group_id = uuid4()
        message_id = uuid4()
        deleted_at = datetime.now(tz.utc).isoformat()
        deleted_by = {
            "user_id": str(uuid4()),
            "name": "Tenzin Kunsang",
            "source": "CMS",
        }
        mock_service.return_value = CmsMessageDeletion(
            room_id=room_id, deleted_at=deleted_at, deleted_by=deleted_by
        )

        response = client.delete(_url(group_id, message_id), headers=AUTH_HEADERS)

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert mock_service.call_args.kwargs["group_id"] == group_id
        assert mock_service.call_args.kwargs["message_id"] == message_id
        # The event goes to the room the service resolved from the group.
        mock_broadcast.assert_awaited_once()
        assert mock_broadcast.call_args.kwargs == {
            "room_id": room_id,
            "message_id": message_id,
            "deleted_by": deleted_by,
            "deleted_at": deleted_at,
        }

    @patch('pecha_api.chat.cms_views._broadcast_message_deleted_safe')
    @patch('pecha_api.chat.cms_views.cms_delete_group_chat_message_service')
    def test_forbidden_is_surfaced(self, mock_service, mock_broadcast):
        client = get_client()
        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="NO_GROUP_MEMBERSHIP"
        )

        response = client.delete(_url(uuid4(), uuid4()), headers=AUTH_HEADERS)

        assert response.status_code == status.HTTP_403_FORBIDDEN
        mock_broadcast.assert_not_called()

    def test_requires_a_token(self):
        client = get_client()

        response = client.delete(_url(uuid4(), uuid4()))

        assert response.status_code == status.HTTP_403_FORBIDDEN
