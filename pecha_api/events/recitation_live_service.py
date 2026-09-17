import logging
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

    try:
        _require_can_edit_event(db=db, group_id=event.group_id, author=author)
        return True
    except HTTPException:
        return False


def resolve_recitation_access(event_id: UUID, user_id: UUID, token: str) -> bool:
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
        require_subscriber(db=db, event=event, user_id=user_id)
        return False
