"""CMS moderation of a group chat room's messages.

The member-facing delete endpoints stay own-messages-only (see
`message_service.delete_message_service`). This surface is the moderation
counterpart: an author who can update the group's content may delete *anyone's*
message in that group's room.
"""
from typing import NamedTuple
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session
from starlette import status

from pecha_api.chat.models import ChatRoom
from pecha_api.chat.repository import (
    get_message_by_id,
    get_room_by_group_id,
    soft_delete_message,
)
from pecha_api.db.database import SessionLocal
from pecha_api.plans.authors.plan_authors_model import Author
from pecha_api.plans.authors.plan_authors_service import validate_and_extract_author_details
from pecha_api.plans.groups.groups_repository import get_group_by_id
from pecha_api.plans.response_message import NOT_FOUND
from pecha_api.plans.shared.permissions import require_can_create_content


class CmsMessageDeletion(NamedTuple):
    """What a CMS deletion produced: the room to publish to, plus the stamp and
    actor the `message_deleted` event carries."""

    room_id: UUID
    deleted_at: str
    deleted_by: dict


def _moderator_actor(author: Author) -> dict:
    """The `deleted_by` block for a CMS deletion.

    Same shape as a member's own deletion, so a client needs no new parser -
    but `user_id` is the moderator's *author* id, not a website user id, and
    `source` marks it as a moderator action so the UI can say "removed by a
    moderator" rather than "deleted by the sender"."""
    name = f"{author.first_name} {author.last_name or ''}".strip()
    return {
        "user_id": str(author.id),
        "email": author.email,
        "name": name or author.email or "Moderator",
        "source": "CMS",
    }


def _require_group(db: Session, group_id: UUID) -> None:
    if not get_group_by_id(db=db, group_id=group_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)


def _get_group_room_or_404(db: Session, group_id: UUID) -> ChatRoom:
    """The group's chat room.

    Unlike the member-facing `_get_room_or_404`, publication is not checked: an
    unpublished group's backlog is exactly what a moderator may still need to
    clean up."""
    room = get_room_by_group_id(db=db, group_id=group_id)
    if not room:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
    return room


def cms_delete_group_chat_message_service(
    token: str,
    group_id: UUID,
    message_id: UUID,
) -> CmsMessageDeletion:
    """Soft-delete any member's message in the group's chat room.

    Gated on the same role set that lets an author update the group's content
    (OWNER / ADMIN / AUTHOR, with the super-admin bypass and the reviewer
    read-only block that `require_can_create_content` already applies). Room
    membership is deliberately not required - a moderator moderates from the
    CMS, without having to join the chat."""
    author = validate_and_extract_author_details(token=token)

    with SessionLocal() as db:
        # Group, then role, then room: the same order the other CMS group
        # services use, so a caller with no role in the group never learns
        # whether its chat room exists.
        _require_group(db=db, group_id=group_id)
        require_can_create_content(db=db, group_id=group_id, author=author)
        room = _get_group_room_or_404(db=db, group_id=group_id)

        message = get_message_by_id(db=db, message_id=message_id, room_id=room.id)
        if not message:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)

        deleted_at = soft_delete_message(db=db, message=message)
        return CmsMessageDeletion(
            room_id=room.id,
            deleted_at=deleted_at.isoformat(),
            deleted_by=_moderator_actor(author),
        )
