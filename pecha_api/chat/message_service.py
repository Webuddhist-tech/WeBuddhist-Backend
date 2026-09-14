from typing import Any, Dict, List, NamedTuple, Optional, Sequence
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette import status

from pecha_api.chat.enums import (
    ChatMessageReportReason,
    ChatMessageReportSource,
    ChatMessageType,
    ChatRoomKind,
)
from pecha_api.chat.models import (
    ChatMessage,
    ChatMessageReaction,
    ChatMessageReport,
    ChatRoom,
)
from pecha_api.chat.moderation_service import validate_message_content
from pecha_api.chat.notification_dispatch_service import (
    enqueue_chat_message_notification,
    enqueue_prayer_notification,
)
from pecha_api.chat.repository import (
    add_prayers_ignoring_duplicates,
    add_reaction,
    count_message_prayers,
    create_message,
    create_report,
    get_message_by_id,
    get_message_by_id_any_room,
    get_prayed_message_ids,
    get_prayer,
    get_prayer_counts_map,
    get_prayer_user_ids_map,
    get_reaction,
    get_reactions_map,
    get_recent_prayers_map,
    get_report_by_message_and_reporter,
    get_room_messages,
    list_message_prayers,
    list_message_reactions,
    remove_prayer,
    remove_reaction,
    soft_delete_message,
    touch_room,
)
from pecha_api.chat.response_models import (
    ChatMessageDTO,
    ChatMessagePrayerDTO,
    ChatMessagePrayersResponse,
    ChatMessagePrayerStateDTO,
    ChatMessageReactionDTO,
    ChatMessagesResponse,
    PrayerBatchResponse,
)
from pecha_api.chat.service import (
    _build_reaction_dtos,
    _generate_presigned_url,
    _get_room_or_404,
    _message_type_value,
    _require_active_member,
    _sender_name,
    build_message_dto,
    load_open_event,
    resolve_or_create_event_room,
    resolve_or_create_group_room,
    resolve_or_create_private_room,
    room_kind,
)
from pecha_api.db.database import SessionLocal
from pecha_api.plans.groups.groups_repository import is_group_id_published
from pecha_api.plans.response_message import NOT_FOUND
from pecha_api.users.users_models import Users

_PARENT_MESSAGE_NOT_FOUND = "PARENT_MESSAGE_NOT_FOUND"
_ALREADY_REPORTED = "ALREADY_REPORTED"
_CANNOT_REPORT_OWN_MESSAGE = "CANNOT_REPORT_OWN_MESSAGE"
_PRAYER_NOT_ALLOWED_IN_DM = "PRAYER_NOT_ALLOWED_IN_DM"
_NOT_A_PRAYER_REQUEST = "NOT_A_PRAYER_REQUEST"
_RECENT_PRAYERS_LIMIT = 3


class PrayerBatchResult(NamedTuple):
    """What a pray/unpray produced: the caller's response, the room to publish
    to, and the payload to broadcast to everyone else in it."""

    room_id: UUID
    response: PrayerBatchResponse
    broadcast: List[Dict[str, Any]]


def send_group_message_service(
    group_id: UUID,
    user: Users,
    body: str,
    parent_message_id: Optional[UUID] = None,
    message_type: str = ChatMessageType.TEXT.value,
) -> ChatMessageDTO:
    with SessionLocal() as db:
        room = resolve_or_create_group_room(
            db=db, group_id=group_id, user=user, lock_group=True
        )
        _require_active_member(db=db, room_id=room.id, user_id=user.id)
        return _persist_message(
            db=db,
            room=room,
            user=user,
            body=body,
            parent_message_id=parent_message_id,
            message_type=message_type,
        )


def send_event_message_service(
    event_id: UUID,
    user: Users,
    body: str,
    parent_message_id: Optional[UUID] = None,
    message_type: str = ChatMessageType.TEXT.value,
) -> ChatMessageDTO:
    with SessionLocal() as db:
        room = resolve_or_create_event_room(
            db=db, event_id=event_id, user=user, lock_group=True
        )
        _require_active_member(db=db, room_id=room.id, user_id=user.id)
        return _persist_message(
            db=db,
            room=room,
            user=user,
            body=body,
            parent_message_id=parent_message_id,
            message_type=message_type,
        )


def send_direct_message_service(
    receiver_id: UUID,
    user: Users,
    body: str,
    parent_message_id: Optional[UUID] = None,
    message_type: str = ChatMessageType.TEXT.value,
) -> ChatMessageDTO:
    with SessionLocal() as db:
        room = resolve_or_create_private_room(db=db, user=user, receiver_id=receiver_id)
        return _persist_message(
            db=db,
            room=room,
            user=user,
            body=body,
            parent_message_id=parent_message_id,
            message_type=message_type,
        )


def _resolve_parent_message(
    db: Session, room: ChatRoom, parent_message_id: Optional[UUID]
) -> Optional[ChatMessage]:
    """A reply's parent must be an existing, non-deleted message in the same room."""
    if parent_message_id is None:
        return None
    parent = get_message_by_id(db=db, message_id=parent_message_id, room_id=room.id)
    if not parent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_PARENT_MESSAGE_NOT_FOUND,
        )
    return parent


def _validate_message_type(room: ChatRoom, message_type: str) -> str:
    """A prayer request belongs to a room with a congregation. In a DM there is
    nobody to pray for it, so v1 rejects it rather than creating a request that
    only one other person can ever see."""
    if message_type not in (ChatMessageType.TEXT.value, ChatMessageType.PRAYER.value):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="message_type must be TEXT or PRAYER",
        )
    if (
        message_type == ChatMessageType.PRAYER.value
        and room_kind(room) == ChatRoomKind.PRIVATE.value
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_PRAYER_NOT_ALLOWED_IN_DM,
        )
    return message_type


def _persist_message(
    db: Session,
    room: ChatRoom,
    user: Users,
    body: str,
    parent_message_id: Optional[UUID] = None,
    message_type: str = ChatMessageType.TEXT.value,
) -> ChatMessageDTO:
    message_type = _validate_message_type(room=room, message_type=message_type)
    validate_message_content(db=db, room=room, user=user, body=body)
    parent = _resolve_parent_message(db=db, room=room, parent_message_id=parent_message_id)
    message = ChatMessage(
        room_id=room.id,
        sender_id=user.id,
        body=body,
        message_type=message_type,
        parent_message_id=parent.id if parent else None,
    )
    # Must sit in the same transaction as the INSERT: room creation and
    # touch_room commit, releasing any lock taken earlier. create_message
    # commits just below, so this is the lock that holds until the row lands.
    if room.group_id is not None and not is_group_id_published(
        db=db, group_id=room.group_id, for_update=True
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
    # Same lock for an event room, whose publication gate hangs off the event.
    if room.event_id is not None:
        load_open_event(db=db, event_id=room.event_id, for_update=True)
    message = create_message(db=db, message=message)
    message.sender = user
    touch_room(db=db, room=room)
    dto = build_message_dto(message, viewer_id=user.id)
    enqueue_chat_message_notification(message.id)
    return dto


def _prayer_message_ids(messages: Sequence[ChatMessage]) -> List[UUID]:
    return [
        message.id
        for message in messages
        if _message_type_value(message) == ChatMessageType.PRAYER.value
    ]


def list_room_messages_service(
    room_id: UUID,
    user: Users,
    skip: int = 0,
    limit: int = 20,
    message_type: Optional[str] = None,
) -> ChatMessagesResponse:
    with SessionLocal() as db:
        _get_room_or_404(db=db, room_id=room_id)
        _require_active_member(db=db, room_id=room_id, user_id=user.id)

        messages, total = get_room_messages(
            db=db,
            room_id=room_id,
            skip=skip,
            limit=limit,
            message_type=message_type,
        )
        reactions_map = get_reactions_map(
            db=db, message_ids=[message.id for message in messages]
        )
        # Prayer state is only fetched for the prayer requests on this page, so
        # an ordinary chat history costs nothing extra.
        prayer_ids = _prayer_message_ids(messages)
        prayer_counts = get_prayer_counts_map(db=db, message_ids=prayer_ids)
        prayed_by_me = get_prayed_message_ids(
            db=db, message_ids=prayer_ids, user_id=user.id
        )
        recent_prayers = get_recent_prayers_map(
            db=db, message_ids=prayer_ids, per_message=_RECENT_PRAYERS_LIMIT
        )
        return ChatMessagesResponse(
            messages=[
                build_message_dto(
                    message,
                    reactions=reactions_map.get(message.id),
                    viewer_id=user.id,
                    prayer_count=prayer_counts.get(message.id, 0),
                    prayed_by_me=message.id in prayed_by_me,
                    recent_prayers=recent_prayers.get(message.id),
                )
                for message in messages
            ],
            skip=skip,
            limit=limit,
            total=total,
        )


def delete_message_service(room_id: UUID, message_id: UUID, user: Users) -> str:
    """Soft-delete the message and return its deleted_at, so the caller can
    broadcast a matching timestamp to the room."""
    with SessionLocal() as db:
        _get_room_or_404(db=db, room_id=room_id)
        _require_active_member(db=db, room_id=room_id, user_id=user.id)

        message = get_message_by_id(db=db, message_id=message_id, room_id=room_id)
        if not message:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)

        if message.sender_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only delete your own messages",
            )

        deleted_at = soft_delete_message(db=db, message=message)
        return deleted_at.isoformat()


def _get_room_message_or_404(
    db: Session, room_id: UUID, message_id: UUID, user: Users
) -> ChatMessage:
    _get_room_or_404(db=db, room_id=room_id)
    _require_active_member(db=db, room_id=room_id, user_id=user.id)
    message = get_message_by_id(db=db, message_id=message_id, room_id=room_id)
    if not message:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
    return message


def add_message_reaction_service(
    room_id: UUID,
    message_id: UUID,
    user: Users,
    emoji: str,
) -> List[ChatMessageReactionDTO]:
    """Add an emoji reaction to a message (idempotent). Returns the message's
    updated reaction summary."""
    with SessionLocal() as db:
        message = _get_room_message_or_404(
            db=db, room_id=room_id, message_id=message_id, user=user
        )

        existing = get_reaction(db=db, message_id=message.id, user_id=user.id, emoji=emoji)
        if not existing:
            try:
                add_reaction(
                    db=db,
                    reaction=ChatMessageReaction(
                        message_id=message.id,
                        user_id=user.id,
                        emoji=emoji,
                    ),
                )
            except IntegrityError:
                # Concurrent duplicate - the reaction already exists, which is fine
                db.rollback()

        reactions = list_message_reactions(db=db, message_id=message.id)
        return _build_reaction_dtos(reactions, viewer_id=user.id)


def remove_message_reaction_service(
    room_id: UUID,
    message_id: UUID,
    user: Users,
    emoji: str,
) -> List[ChatMessageReactionDTO]:
    """Remove the caller's emoji reaction from a message (idempotent). Returns
    the message's updated reaction summary."""
    with SessionLocal() as db:
        message = _get_room_message_or_404(
            db=db, room_id=room_id, message_id=message_id, user=user
        )

        existing = get_reaction(db=db, message_id=message.id, user_id=user.id, emoji=emoji)
        if existing:
            remove_reaction(db=db, reaction=existing)

        reactions = list_message_reactions(db=db, message_id=message.id)
        return _build_reaction_dtos(reactions, viewer_id=user.id)


def report_message_service(
    room_id: UUID,
    message_id: UUID,
    user: Users,
    reason: ChatMessageReportReason,
    description: Optional[str] = None,
) -> None:
    """Report a message for moderation. One report per user per message."""
    with SessionLocal() as db:
        message = _get_room_message_or_404(
            db=db, room_id=room_id, message_id=message_id, user=user
        )

        if message.sender_id == user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_CANNOT_REPORT_OWN_MESSAGE,
            )

        existing = get_report_by_message_and_reporter(
            db=db, message_id=message.id, reporter_id=user.id
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_ALREADY_REPORTED,
            )

        try:
            create_report(
                db=db,
                report=ChatMessageReport(
                    message_id=message.id,
                    reporter_id=user.id,
                    reported_user_id=message.sender_id,
                    room_id=message.room_id,
                    source=ChatMessageReportSource.MANUAL.value,
                    reason=reason.value,
                    description=description,
                ),
            )
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_ALREADY_REPORTED,
            )


def _resolve_prayer_request(
    db: Session, message_id: UUID, user: Users
) -> ChatMessage:
    """The prayer request behind a /chat/messages/{id}/prayers route.

    Carries the same room gate as every other message route: the room must be
    reachable and the caller an active member of it."""
    message = get_message_by_id_any_room(db=db, message_id=message_id)
    if not message:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
    _get_room_or_404(db=db, room_id=message.room_id)
    _require_active_member(db=db, room_id=message.room_id, user_id=user.id)
    if _message_type_value(message) != ChatMessageType.PRAYER.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_NOT_A_PRAYER_REQUEST,
        )
    return message


def _prayer_broadcast_entries(
    db: Session, message_ids: Sequence[UUID]
) -> List[Dict[str, Any]]:
    """One prayers_updated entry per affected message. prayed_by_me cannot be
    viewer-specific in a shared broadcast, so each client derives its own from
    user_ids - the same contract as reactions."""
    user_ids_map = get_prayer_user_ids_map(db=db, message_ids=message_ids)
    return [
        {
            "message_id": str(message_id),
            "prayer_count": len(user_ids_map.get(message_id, [])),
            "user_ids": [str(user_id) for user_id in user_ids_map.get(message_id, [])],
        }
        for message_id in message_ids
    ]


def pray_for_messages_service(
    room_id: UUID,
    user: Users,
    message_ids: Sequence[UUID],
) -> PrayerBatchResult:
    """Pray for one or several selected prayer requests in one action.

    Idempotent: praying again for the same request is a no-op that still
    reports the current state. Ids that are not live prayer requests in this
    room are skipped rather than failing the whole batch, so a request deleted
    between rendering and confirming does not lose the rest of the selection.
    """
    with SessionLocal() as db:
        _get_room_or_404(db=db, room_id=room_id)
        _require_active_member(db=db, room_id=room_id, user_id=user.id)

        valid_ids: List[UUID] = []
        for message_id in message_ids:
            message = get_message_by_id(db=db, message_id=message_id, room_id=room_id)
            if message is None:
                continue
            if _message_type_value(message) != ChatMessageType.PRAYER.value:
                continue
            valid_ids.append(message.id)

        if not valid_ids:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=_NOT_A_PRAYER_REQUEST,
            )

        created = add_prayers_ignoring_duplicates(
            db=db, message_ids=valid_ids, user_id=user.id
        )
        created_by_message = dict(created)

        counts = get_prayer_counts_map(db=db, message_ids=valid_ids)
        response = PrayerBatchResponse(
            prayers=[
                ChatMessagePrayerStateDTO(
                    message_id=message_id,
                    prayer_count=counts.get(message_id, 0),
                    prayed_by_me=True,
                    created=message_id in created_by_message,
                )
                for message_id in valid_ids
            ]
        )
        broadcast = _prayer_broadcast_entries(db=db, message_ids=valid_ids)

    # After the session closes: the prayers are already committed, so a
    # notification failure cannot cost the user their prayer.
    for _, prayer_id in created:
        enqueue_prayer_notification(prayer_id)

    return PrayerBatchResult(room_id=room_id, response=response, broadcast=broadcast)


def unpray_message_service(message_id: UUID, user: Users) -> PrayerBatchResult:
    """Take back the caller's prayer for one request (idempotent)."""
    with SessionLocal() as db:
        message = _resolve_prayer_request(db=db, message_id=message_id, user=user)

        existing = get_prayer(db=db, message_id=message.id, user_id=user.id)
        if existing is not None:
            remove_prayer(db=db, prayer=existing)

        response = PrayerBatchResponse(
            prayers=[
                ChatMessagePrayerStateDTO(
                    message_id=message.id,
                    prayer_count=count_message_prayers(db=db, message_id=message.id),
                    prayed_by_me=False,
                    created=False,
                )
            ]
        )
        broadcast = _prayer_broadcast_entries(db=db, message_ids=[message.id])
        return PrayerBatchResult(
            room_id=message.room_id, response=response, broadcast=broadcast
        )


def list_message_prayers_service(
    message_id: UUID,
    user: Users,
    skip: int = 0,
    limit: int = 20,
) -> ChatMessagePrayersResponse:
    """Who prayed for this request, newest first."""
    with SessionLocal() as db:
        message = _resolve_prayer_request(db=db, message_id=message_id, user=user)
        prayers, total = list_message_prayers(
            db=db, message_id=message.id, skip=skip, limit=limit
        )
        return ChatMessagePrayersResponse(
            message_id=message.id,
            prayers=[
                ChatMessagePrayerDTO(
                    user_id=prayer.user_id,
                    email=prayer.user.email if prayer.user else None,
                    name=_sender_name(prayer.user) if prayer.user else None,
                    avatar_url=_generate_presigned_url(
                        prayer.user.avatar_url if prayer.user else None
                    ),
                    created_at=prayer.created_at.isoformat(),
                )
                for prayer in prayers
            ],
            skip=skip,
            limit=limit,
            total=total,
        )
