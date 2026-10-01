from datetime import datetime, timezone
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
    notify_prayers_for_request,
)
from pecha_api.chat.repository import (
    add_prayers,
    add_reaction,
    count_message_prayers,
    create_message,
    create_report,
    get_message_by_id,
    get_message_by_id_any_room,
    get_messages_by_ids,
    get_my_prayer_counts_map,
    get_prayed_message_ids,
    get_prayer_counts_map,
    get_prayer_user_ids_map,
    get_reaction,
    get_reactions_map,
    get_recent_prayers_map,
    get_report_by_message_and_reporter,
    get_room_by_id,
    get_room_messages,
    list_message_prayers,
    list_message_reactions,
    remove_prayer_and_count,
    remove_reaction,
    resolve_open_reports_for_message,
    soft_delete_message,
    soft_delete_messages,
    touch_room,
    update_message,
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
from pecha_api.prayer_intentions.prayer_intention_service import (
    resolve_intention_dtos_for_slugs,
    validate_message_intention_and_body,
)
from pecha_api.users.users_models import Users
from pecha_api.events.events_cache_service import schedule_invalidate_event_detail_caches

_PARENT_MESSAGE_NOT_FOUND = "PARENT_MESSAGE_NOT_FOUND"
_ALREADY_REPORTED = "ALREADY_REPORTED"
_CANNOT_REPORT_OWN_MESSAGE = "CANNOT_REPORT_OWN_MESSAGE"
_PRAYER_NOT_ALLOWED_IN_DM = "PRAYER_NOT_ALLOWED_IN_DM"
_NOT_A_PRAYER_REQUEST = "NOT_A_PRAYER_REQUEST"
_NOT_OWN_MESSAGES = "message_ids include other users' messages"
_NOTHING_TO_EDIT = "Provide body or intention to edit"
_RECENT_PRAYERS_LIMIT = 3


class PrayerBatchResult(NamedTuple):
    """What a pray/unpray produced: the caller's response, the room to publish
    to, and the payload to broadcast to everyone else in it."""

    room_id: UUID
    response: PrayerBatchResponse
    broadcast: List[Dict[str, Any]]


class BulkDeleteResult(NamedTuple):
    """What a bulk delete produced: the messages that were deleted and the one
    timestamp they all carry, so the caller can broadcast a matching event per
    message."""

    message_ids: List[UUID]
    deleted_at: str


def send_group_message_service(
    group_id: UUID,
    user: Users,
    body: str,
    parent_message_id: Optional[UUID] = None,
    message_type: str = ChatMessageType.TEXT.value,
    intention: Optional[str] = None,
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
            intention=intention,
        )


def send_event_message_service(
    event_id: UUID,
    user: Users,
    body: str,
    parent_message_id: Optional[UUID] = None,
    message_type: str = ChatMessageType.TEXT.value,
    intention: Optional[str] = None,
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
            intention=intention,
        )


def send_direct_message_service(
    receiver_id: UUID,
    user: Users,
    body: str,
    parent_message_id: Optional[UUID] = None,
    message_type: str = ChatMessageType.TEXT.value,
    intention: Optional[str] = None,
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
            intention=intention,
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
    intention: Optional[str] = None,
) -> ChatMessageDTO:
    message_type = _validate_message_type(room=room, message_type=message_type)
    body = body.strip()
    if not body:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message body must not be empty",
        )
    stored_intention = validate_message_intention_and_body(
        db=db,
        message_type=message_type,
        body=body,
        intention=intention,
        event_id=getattr(room, "event_id", None),
    )
    validate_message_content(db=db, room=room, user=user, body=body)
    parent = _resolve_parent_message(db=db, room=room, parent_message_id=parent_message_id)
    message = ChatMessage(
        room_id=room.id,
        sender_id=user.id,
        body=body,
        message_type=message_type,
        parent_message_id=parent.id if parent else None,
        intention=stored_intention,
    )
    # Must sit in the same transaction as the INSERT: room creation and
    # touch_room commit, releasing any lock taken earlier. create_message
    # commits just below, so this is the lock that holds until the row lands.
    _lock_room_publication(db=db, room=room)
    message = create_message(db=db, message=message)
    message.sender = user
    touch_room(db=db, room=room)
    intention_dto = None
    if stored_intention:
        intention_map = resolve_intention_dtos_for_slugs(db=db, slugs=[stored_intention])
        intention_dto = intention_map.get(stored_intention)
    dto = build_message_dto(
        message, viewer_id=user.id, intention=intention_dto
    )
    # The type and room are already in hand, so an ordinary message costs no
    # extra read for the dispatcher to learn it is not a prayer request.
    enqueue_chat_message_notification(
        message.id, message_type=message_type, room_id=room.id
    )
    _schedule_event_prayer_count_cache_refresh(room=room, message_type=message_type)
    return dto


def _lock_room_publication(db: Session, room: ChatRoom) -> None:
    """Lock and recheck the room's publication gate in the caller's
    transaction, so a write cannot land in a group that was just unpublished
    or an event chat that was just closed. 404 when the gate is shut."""
    if room.group_id is not None and not is_group_id_published(
        db=db, group_id=room.group_id, for_update=True
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
    # Same lock for an event room, whose publication gate hangs off the event.
    if room.event_id is not None:
        load_open_event(db=db, event_id=room.event_id, for_update=True)


def _schedule_event_prayer_count_cache_refresh(
    room: ChatRoom, message_type: str
) -> None:
    """Event detail caches `prayer_request_count`; refresh when PRAYER rows change."""
    if message_type != ChatMessageType.PRAYER.value:
        return
    if room.event_id is None:
        return
    schedule_invalidate_event_detail_caches(room.event_id)


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
        my_prayer_counts = get_my_prayer_counts_map(
            db=db, message_ids=prayer_ids, user_id=user.id
        )
        recent_prayers = get_recent_prayers_map(
            db=db, message_ids=prayer_ids, per_message=_RECENT_PRAYERS_LIMIT
        )
        intention_slugs = [
            message.intention for message in messages if message.intention
        ]
        intention_dtos = resolve_intention_dtos_for_slugs(db=db, slugs=intention_slugs)
        return ChatMessagesResponse(
            messages=[
                build_message_dto(
                    message,
                    reactions=reactions_map.get(message.id),
                    viewer_id=user.id,
                    prayer_count=prayer_counts.get(message.id, 0),
                    prayed_by_me=message.id in prayed_by_me,
                    recent_prayers=recent_prayers.get(message.id),
                    intention=intention_dtos.get(message.intention)
                    if message.intention
                    else None,
                    my_prayer_count=my_prayer_counts.get(message.id, 0),
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

        room = get_room_by_id(db=db, room_id=room_id)
        message_type = _message_type_value(message)
        deleted_at = soft_delete_message(db=db, message=message)
        if room is not None:
            _schedule_event_prayer_count_cache_refresh(
                room=room, message_type=message_type
            )
        return deleted_at.isoformat()


def moderator_delete_message(db: Session, message: ChatMessage) -> datetime:
    """Soft-delete any member's message on a moderator's behalf and close the
    open reports against it in the same commit. The caller has already checked
    the moderator may act on this message's room."""
    room = message.room
    message_type = _message_type_value(message)
    deleted_at = datetime.now(timezone.utc)
    message.deleted_at = deleted_at
    resolve_open_reports_for_message(
        db=db, message_id=message.id, resolved_at=deleted_at
    )
    db.commit()
    if room is not None:
        _schedule_event_prayer_count_cache_refresh(
            room=room, message_type=message_type
        )
    return deleted_at


def edit_message_service(
    room_id: UUID,
    message_id: UUID,
    user: Users,
    body: Optional[str] = None,
    intention: Optional[str] = None,
) -> ChatMessageDTO:
    """Edit the body and/or intention of the caller's own message.

    A field left out keeps its current value. The result goes through the same
    intention and moderation checks as a new message, and the row is marked
    is_edited. An edit that changes nothing leaves the flag untouched."""
    if body is None and intention is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=_NOTHING_TO_EDIT
        )
    with SessionLocal() as db:
        room = _get_room_or_404(db=db, room_id=room_id)
        _require_active_member(db=db, room_id=room_id, user_id=user.id)

        message = get_message_by_id(db=db, message_id=message_id, room_id=room_id)
        if not message:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
        if message.sender_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only edit your own messages",
            )

        message_type = _message_type_value(message)
        new_body = body.strip() if body is not None else message.body
        if not new_body:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Message body must not be empty",
            )
        stored_intention = validate_message_intention_and_body(
            db=db,
            message_type=message_type,
            body=new_body,
            intention=intention if intention is not None else message.intention,
            event_id=getattr(room, "event_id", None),
        )
        if new_body != message.body or stored_intention != message.intention:
            validate_message_content(db=db, room=room, user=user, body=new_body)
            # Held until update_message commits, as for a new message.
            _lock_room_publication(db=db, room=room)
            message = update_message(
                db=db, message=message, body=new_body, intention=stored_intention
            )

        reactions = list_message_reactions(db=db, message_id=message.id)
        prayer_kwargs: Dict[str, Any] = {}
        if message_type == ChatMessageType.PRAYER.value:
            prayer_ids = [message.id]
            prayer_kwargs = {
                "prayer_count": get_prayer_counts_map(
                    db=db, message_ids=prayer_ids
                ).get(message.id, 0),
                "prayed_by_me": message.id
                in get_prayed_message_ids(db=db, message_ids=prayer_ids, user_id=user.id),
                "my_prayer_count": get_my_prayer_counts_map(
                    db=db, message_ids=prayer_ids, user_id=user.id
                ).get(message.id, 0),
                "recent_prayers": get_recent_prayers_map(
                    db=db, message_ids=prayer_ids, per_message=_RECENT_PRAYERS_LIMIT
                ).get(message.id),
                "intention": resolve_intention_dtos_for_slugs(
                    db=db, slugs=[stored_intention]
                ).get(stored_intention)
                if stored_intention
                else None,
            }
        return build_message_dto(
            message, reactions=reactions, viewer_id=user.id, **prayer_kwargs
        )


def delete_messages_service(
    room_id: UUID, message_ids: Sequence[UUID], user: Users
) -> BulkDeleteResult:
    """Soft-delete several of the caller's own messages in one action.

    All or nothing, deliberately: if the selection contains a message the
    caller did not send, or one that is no longer a live message in this room,
    nothing is deleted and the caller is told which ids were the problem -
    silently deleting the rest would leave them guessing what survived."""
    with SessionLocal() as db:
        _get_room_or_404(db=db, room_id=room_id)
        _require_active_member(db=db, room_id=room_id, user_id=user.id)

        messages = get_messages_by_ids(db=db, message_ids=message_ids, room_id=room_id)
        found = {message.id: message for message in messages}

        missing = [message_id for message_id in message_ids if message_id not in found]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"{NOT_FOUND}: {', '.join(str(message_id) for message_id in missing)}",
            )

        not_own = [
            message_id
            for message_id in message_ids
            if found[message_id].sender_id != user.id
        ]
        if not_own:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"{_NOT_OWN_MESSAGES}: {', '.join(str(message_id) for message_id in not_own)}",
            )

        ordered = [found[message_id] for message_id in message_ids]
        room = get_room_by_id(db=db, room_id=room_id)
        affects_prayer_count = any(
            _message_type_value(message) == ChatMessageType.PRAYER.value
            for message in ordered
        )
        deleted_at = soft_delete_messages(db=db, messages=ordered)
        if room is not None and affects_prayer_count:
            _schedule_event_prayer_count_cache_refresh(
                room=room,
                message_type=ChatMessageType.PRAYER.value,
            )
        return BulkDeleteResult(
            message_ids=[message.id for message in ordered],
            deleted_at=deleted_at.isoformat(),
        )


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
    count: int = 1,
) -> PrayerBatchResult:
    """Pray `count` times for each of one or several selected prayer requests.

    Praying again for the same request adds to the caller's running total; the
    people count only moves on a first prayer. Ids that are not live prayer
    requests in this room are skipped rather than failing the whole batch, so a
    request deleted between rendering and confirming does not lose the rest of
    the selection.
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

        result = add_prayers(
            db=db, message_ids=valid_ids, user_id=user.id, count=count
        )

        counts = get_prayer_counts_map(db=db, message_ids=valid_ids)
        response = PrayerBatchResponse(
            prayers=[
                ChatMessagePrayerStateDTO(
                    message_id=message_id,
                    prayer_count=counts.get(message_id, 0),
                    prayed_by_me=True,
                    my_prayer_count=result.my_prayer_counts.get(message_id, 0),
                    created=message_id in result.created_message_ids,
                )
                for message_id in valid_ids
            ]
        )
        broadcast = _prayer_broadcast_entries(db=db, message_ids=valid_ids)

    # After the session closes: the prayers are already committed, so a
    # notification failure cannot cost the user their prayer. Every call runs
    # the gate, not just a first prayer: repeat prayers are what the push sums.
    for message_id in valid_ids:
        notify_prayers_for_request(message_id=message_id, prayer_user_id=user.id)

    return PrayerBatchResult(room_id=room_id, response=response, broadcast=broadcast)


def unpray_message_service(message_id: UUID, user: Users) -> PrayerBatchResult:
    """Take back the caller's prayer for one request (idempotent)."""
    with SessionLocal() as db:
        message = _resolve_prayer_request(db=db, message_id=message_id, user=user)

        remove_prayer_and_count(db=db, message_id=message.id, user_id=user.id)

        response = PrayerBatchResponse(
            prayers=[
                ChatMessagePrayerStateDTO(
                    message_id=message.id,
                    prayer_count=count_message_prayers(db=db, message_id=message.id),
                    prayed_by_me=False,
                    my_prayer_count=0,
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
    """Who is praying for this request and how many times each, most recently
    prayed first. Any member may see who is praying; only the person who
    posted the request sees how many times each prayed."""
    with SessionLocal() as db:
        message = _resolve_prayer_request(db=db, message_id=message_id, user=user)
        is_requester = message.sender_id == user.id
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
                    prayer_count=int(prayer.prayer_count) if is_requester else None,
                    created_at=prayer.first_prayed_at.isoformat(),
                    last_prayed_at=prayer.last_prayed_at.isoformat(),
                )
                for prayer in prayers
            ],
            skip=skip,
            limit=limit,
            total=total,
        )
