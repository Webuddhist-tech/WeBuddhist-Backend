import logging
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session
from starlette import status

from pecha_api.events.event_model import Event
from pecha_api.events.event_repository import get_event_by_id
from pecha_api.plans.groups.groups_repository import (
    is_group_id_published,
    is_user_following_group,
    is_user_joined_group,
)
from pecha_api.plans.response_message import NOT_FOUND

logger = logging.getLogger(__name__)

NOT_ELIGIBLE = "Only joined or following members of this event's group can follow its recitation"


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


def require_subscriber(db: Session, event: Event, user_id: UUID) -> None:
    """Anyone who can see the event can follow along: same joiner/follower rule
    the event's chat room uses, so this introduces no new permission concept."""
    eligible = is_user_joined_group(
        db=db, group_id=event.group_id, user_id=user_id
    ) or is_user_following_group(db=db, group_id=event.group_id, user_id=user_id)
    if not eligible:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=NOT_ELIGIBLE)


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

    All a token-authenticated machine can be checked against: there is no user
    or Author behind a shared-secret request, so this is about the event being
    a real, reachable target - not about who is driving it.
    """
    from pecha_api.db.database import SessionLocal

    with SessionLocal() as db:
        load_live_event(db=db, event_id=event_id)


@dataclass(frozen=True)
class RecitationCaller:
    """Who is on the socket.

    `presence_id` keys the shared roster. `user_id` is the website User behind
    the token, and is what eligibility is checked against - a Studio author
    with no linked User has the first without the second.
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


def resolve_recitation_access(
    event_id: UUID, user_id: Optional[UUID], token: str
) -> bool:
    """Gate a connecting socket and say whether it may publish.

    Raises 404 for an unreachable event and 403 for an ineligible viewer;
    returns True when the caller is the operator.

    The operator check runs first, and passing it is enough on its own: CMS
    rights live on the Author, while joining or following is something the
    person does in the app, and the one driving the puja often has the former
    without the latter. Gating them on a join would lock the group's own admins
    out of their event.
    """
    from pecha_api.db.database import SessionLocal

    with SessionLocal() as db:
        event = load_live_event(db=db, event_id=event_id)
        if is_event_operator(db=db, event=event, token=token):
            return True
        if user_id is None:
            # A Studio author who cannot edit this event has no app identity to
            # check a join or a follow against.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=NOT_ELIGIBLE
            )
        require_subscriber(db=db, event=event, user_id=user_id)
        return False
