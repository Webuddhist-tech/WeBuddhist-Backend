import logging
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session
from starlette import status

from pecha_api.events.event_model import Event
from pecha_api.events.event_repository import get_event_by_id
from pecha_api.plans.groups.groups_repository import is_group_id_published
from pecha_api.plans.response_message import NOT_FOUND

logger = logging.getLogger(__name__)


def load_live_event(db: Session, event_id: UUID) -> Event:
    """The event behind a recitation session, or 404.

    Deliberately not `chat.service.load_open_event`: that one also requires
    `chat_enabled`, and a puja can be streamed with its chat switched off.
    """
    event = get_event_by_id(db, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
    if not is_group_id_published(db=db, group_id=event.group_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
    return event


def is_event_operator(db: Session, event: Event, token: str) -> bool:
    """True when the caller may drive this event's recitation.

    v1 operator == whoever may edit the event in the CMS (group owner, admin or
    author, plus super admins), so there is no second permission model to keep
    in step. The same token is re-resolved as an Author here: the socket
    authenticates as an app user, and `validate_and_extract_author_details`
    already maps a website user back to their Author row when one is linked.
    """
    # Imported here: event_service pulls in most of the events package, and the
    # websocket module is imported from app startup.
    from pecha_api.events.event_service import _require_can_edit_event
    from pecha_api.plans.authors.plan_authors_service import (
        validate_and_extract_author_details,
    )

    try:
        author = validate_and_extract_author_details(token=token)
    except HTTPException:
        return False
    except Exception:
        logger.exception("Failed to resolve author for recitation operator check")
        return False
    if not author.is_active:
        # A deactivated author can still hold an unexpired token; CMS rights
        # end with the account, not with the token.
        return False

    try:
        _require_can_edit_event(db=db, group_id=event.group_id, author=author)
        return True
    except HTTPException:
        return False


def assert_live_event(event_id: UUID) -> None:
    """404 unless the event exists and its group is published.

    All that can be checked when there is nobody behind the socket or request:
    a machine holding the shared secret has no user or Author, and neither has
    a signed-out viewer. So this is about the event being a real, reachable
    target - not about who is driving it or watching it.
    """
    from pecha_api.db.database import SessionLocal

    with SessionLocal() as db:
        load_live_event(db=db, event_id=event_id)


@dataclass(frozen=True)
class RecitationCaller:
    """Who is on the socket.

    `presence_id` keys the shared roster. `user_id` is the website User behind
    the token - a Studio author with no linked User has the first without the
    second.
    """

    presence_id: UUID
    user_id: Optional[UUID]


def resolve_recitation_caller(token: str) -> RecitationCaller:
    """The identity behind a connecting socket, from the app or from Studio.

    Two token shapes reach this socket. The app sends a website User token,
    whose `sub` is a Users id. Studio sends a CMS token, whose `sub` is an
    Author id, so user resolution rejects it outright - even though the
    operator check below is written for precisely that caller. Accepting only
    the first kept every author off their own event's socket.

    Raises 401 when the token resolves to neither.
    """
    # Imported here for the same reason as in `is_event_operator`: the authors
    # service pulls in most of the plans package.
    from pecha_api.plans.authors.plan_authors_service import (
        validate_and_extract_author_details,
    )
    from pecha_api.users.users_service import validate_and_extract_user_details

    try:
        user = validate_and_extract_user_details(token=token)
        return RecitationCaller(presence_id=user.id, user_id=user.id)
    except HTTPException:
        pass

    author = validate_and_extract_author_details(token=token)
    if not author.is_active:
        # Same token-outlives-account gap as the operator check above.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    # A linked User keeps one person to one roster slot whether they are
    # following along in the app or driving the puja from Studio.
    linked_user_id = author.user_id
    return RecitationCaller(
        presence_id=linked_user_id or author.id,
        user_id=linked_user_id,
    )


def resolve_recitation_access(event_id: UUID, token: str) -> bool:
    """Gate a signed-in socket and say whether it may publish.

    Raises 404 for an unreachable event; otherwise returns True when the caller
    is the operator, and False for everyone else, who may follow along.

    Following asks for no join or follow of the event's group: a published
    group's puja is open to anyone who can reach the event, signed out
    included, and holding someone to more for having signed in would be
    backwards. All that is still decided here is who drives the room - CMS
    rights on the event, which live on the Author and so are checked against
    the token alone.
    """
    from pecha_api.db.database import SessionLocal

    with SessionLocal() as db:
        event = load_live_event(db=db, event_id=event_id)
        return is_event_operator(db=db, event=event, token=token)
