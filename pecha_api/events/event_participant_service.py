import logging
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from starlette import status

from pecha_api.config import get
from pecha_api.db.database import SessionLocal
from pecha_api.uploads.S3_utils import generate_presigned_access_url
from pecha_api.plans.authors.plan_authors_service import validate_cms_author_details
from pecha_api.plans.shared.permissions import require_can_read_group_content
from pecha_api.users.users_models import Users
from pecha_api.users.users_service import validate_and_extract_user_details

from .event_repository import get_event_by_id
from .event_response_models import EventParticipantDTO, EventParticipantsResponse
from .event_participant_repository import (
    get_event_participants_paginated,
    remove_event_participant,
    upsert_event_participant,
)


def _safe_avatar_url(user: Users) -> Optional[str]:
    if not user.avatar_url:
        return None
    try:
        return generate_presigned_access_url(
            bucket_name=get("AWS_BUCKET_NAME"),
            s3_key=user.avatar_url,
        )
    except Exception:
        logging.exception(f"Failed to generate avatar URL for user {user.id}")
        return None


def _fullname(user: Users) -> Optional[str]:
    parts = [part for part in (user.firstname, user.lastname) if part]
    return " ".join(parts) or None


def _participant_to_dto(user: Users, created_at) -> EventParticipantDTO:
    return EventParticipantDTO(
        user_id=user.id,
        username=user.username,
        fullname=_fullname(user),
        avatar_url=_safe_avatar_url(user),
        created_at=created_at,
    )


def _get_event_or_404(db, event_id: UUID):
    event = get_event_by_id(db, event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Event with id '{event_id}' not found",
        )
    return event


def _participants_response(
    db, event_id: UUID, skip: int, limit: int
) -> EventParticipantsResponse:
    rows, total = get_event_participants_paginated(
        db, event_id=event_id, skip=skip, limit=limit
    )
    return EventParticipantsResponse(
        participants=[
            _participant_to_dto(user, created_at) for user, created_at in rows
        ],
        skip=skip,
        limit=limit,
        total=total,
    )


def join_event_service(token: str, event_id: UUID) -> None:
    """Join an event. Idempotent: joining again is a no-op.

    Also puts the user into the event's chat room when one exists, so the room
    shows up in their inbox before they ever type in it."""
    current_user = validate_and_extract_user_details(token=token)

    with SessionLocal() as db:
        _get_event_or_404(db, event_id)
        upsert_event_participant(db=db, event_id=event_id, user_id=current_user.id)
        try:
            # Deferred: chat imports events at module level, so events cannot
            # import chat back at module level.
            from pecha_api.chat.service import join_event_chat_room

            join_event_chat_room(db=db, event_id=event_id, user=current_user)
        except Exception:
            # The RSVP is the user's actual intent; a chat-room hiccup must not
            # undo it. The room is joined again on their first message anyway.
            logging.exception(
                f"Failed to add user {current_user.id} to chat room for event {event_id}"
            )


def leave_event_service(token: str, event_id: UUID) -> None:
    """Leave an event. 404 when the caller had not joined.

    Also drops the event's chat room from their inbox."""
    current_user = validate_and_extract_user_details(token=token)

    with SessionLocal() as db:
        _get_event_or_404(db, event_id)
        removed = remove_event_participant(
            db=db, event_id=event_id, user_id=current_user.id
        )
        if not removed:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"You have not joined event '{event_id}'",
            )
        try:
            from pecha_api.chat.service import leave_event_chat_room

            leave_event_chat_room(db=db, event_id=event_id, user_id=current_user.id)
        except Exception:
            logging.exception(
                f"Failed to remove user {current_user.id} from chat room for event {event_id}"
            )


def get_event_participants_service(
    event_id: UUID,
    skip: int = 0,
    limit: int = 20,
) -> EventParticipantsResponse:
    with SessionLocal() as db:
        _get_event_or_404(db, event_id)
        return _participants_response(db, event_id=event_id, skip=skip, limit=limit)


def get_cms_event_participants_service(
    token: str,
    event_id: UUID,
    skip: int = 0,
    limit: int = 20,
) -> EventParticipantsResponse:
    current_author = validate_cms_author_details(token=token)

    with SessionLocal() as db:
        event = _get_event_or_404(db, event_id)
        require_can_read_group_content(
            db=db, group_id=event.group_id, author=current_author
        )
        return _participants_response(db, event_id=event_id, skip=skip, limit=limit)
