from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from starlette import status

from pecha_api.chat.cms_service import cms_delete_group_chat_message_service
from pecha_api.chat.views import _broadcast_message_deleted_safe
from pecha_api.plans.auth.cms_auth_deps import get_cms_author_token

cms_group_chat_router = APIRouter(
    prefix="/cms/author/groups/{group_id}/chat",
    tags=["CMS Group Chat"],
)


@cms_group_chat_router.delete(
    "/messages/{message_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def cms_delete_group_chat_message(
    group_id: UUID,
    message_id: UUID,
    token: Annotated[str, Depends(get_cms_author_token)] = "",
):
    """Soft-delete any member's message in the group's chat room (moderation).

    Unlike the member-facing DELETE /chat/rooms/{room_id}/messages/{message_id},
    which only ever deletes the caller's own message, this deletes a message
    regardless of who sent it - for an author who can update this group's
    content. Broadcasts the same `message_deleted` event, so connected clients
    grey the message out live."""
    deletion = cms_delete_group_chat_message_service(
        token=token,
        group_id=group_id,
        message_id=message_id,
    )
    await _broadcast_message_deleted_safe(
        room_id=deletion.room_id,
        message_id=message_id,
        deleted_by=deletion.deleted_by,
        deleted_at=deletion.deleted_at,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
