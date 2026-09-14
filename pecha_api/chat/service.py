import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session
from starlette import status

from pecha_api.chat.enums import ChatRoomKind, ChatRoomMemberRole
from pecha_api.chat.models import ChatMessage, ChatRoom, ChatRoomMember
from pecha_api.chat.repository import (
    add_member,
    count_active_members,
    count_unread_messages,
    create_room,
    get_active_member,
    get_last_message,
    get_last_messages_map,
    get_member,
    get_room_by_event_id,
    get_room_by_group_id,
    get_room_by_id,
    get_room_by_pair,
    leave_member,
    list_active_members,
    list_my_active_rooms,
    mark_read,
    update_room,
)
from pecha_api.chat.response_models import (
    ChatMessageDTO,
    ChatMessageParentDTO,
    ChatMessagePrayerUserDTO,
    ChatMessageReactionDTO,
    ChatMessageReactionUserDTO,
    ChatPeopleResponse,
    ChatPersonDTO,
    ChatRoomDTO,
    ChatRoomsResponse,
)
from pecha_api.config import get
from pecha_api.db.database import SessionLocal
from pecha_api.events.event_repository import get_event_by_id
from pecha_api.plans.groups.groups_models import AuthorGroup
from pecha_api.plans.groups.groups_repository import (
    get_group_by_id,
    is_group_id_published,
    is_group_published,
    is_user_following_group,
    is_user_joined_group,
    list_group_joiners_paginated,
)
from pecha_api.plans.response_message import FORBIDDEN, NOT_FOUND
from pecha_api.uploads.S3_utils import generate_presigned_access_url
from pecha_api.users.users_models import Users

logger = logging.getLogger(__name__)


def _isoformat(value) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _generate_presigned_url(s3_key: Optional[str]) -> Optional[str]:
    if not s3_key:
        return None
    try:
        return generate_presigned_access_url(
            bucket_name=get("AWS_BUCKET_NAME"),
            s3_key=s3_key,
        )
    except Exception:
        logger.exception(f"Failed to generate presigned URL for {s3_key}")
        return None


def _build_reaction_dtos(reactions, viewer_id: Optional[UUID]) -> list:
    """Aggregate reaction rows into per-emoji summaries (first-seen order)."""
    if not reactions:
        return []
    summaries: dict = {}
    for reaction in reactions:
        summary = summaries.setdefault(
            reaction.emoji,
            ChatMessageReactionDTO(emoji=reaction.emoji, count=0, reacted_by_me=False),
        )
        summary.count += 1
        summary.user_ids.append(reaction.user_id)
        user = getattr(reaction, "user", None)
        summary.users.append(
            ChatMessageReactionUserDTO(
                user_id=reaction.user_id,
                email=user.email if user else None,
                name=(
                    f"{user.firstname} {user.lastname or ''}".strip() or user.email
                )
                if user
                else None,
            )
        )
        if viewer_id is not None and reaction.user_id == viewer_id:
            summary.reacted_by_me = True
    return list(summaries.values())


def _sender_name(sender) -> str:
    if not sender:
        return "Unknown"
    return f"{sender.firstname} {sender.lastname or ''}".strip() or sender.email


def _build_parent_dto(message: ChatMessage) -> Optional[ChatMessageParentDTO]:
    has_parent = getattr(message, "parent_message_id", None) is not None
    parent = getattr(message, "parent", None) if has_parent else None
    if parent is None:
        return None
    is_deleted = parent.deleted_at is not None
    return ChatMessageParentDTO(
        id=parent.id,
        sender_id=parent.sender_id,
        sender_email=parent.sender.email if parent.sender else "unknown@example.com",
        sender_name=_sender_name(parent.sender),
        sender_avatar_url=_generate_presigned_url(parent.sender.avatar_url if parent.sender else None),
        body="" if is_deleted else parent.body,
        created_at=_isoformat(parent.created_at),
        deleted_at=_isoformat(parent.deleted_at),
    )


def _message_type_value(message: ChatMessage) -> str:
    """The message's type as a plain string, whether the attribute holds the
    enum member (ORM row) or already a string (mocks, freshly built rows)."""
    value = getattr(message, "message_type", None)
    if value is None:
        return "TEXT"
    return getattr(value, "value", value)


def build_prayer_user_dtos(users) -> list:
    """Identity of the people who prayed, for the avatar stack."""
    if not users:
        return []
    return [
        ChatMessagePrayerUserDTO(
            user_id=user.id,
            email=user.email,
            name=_sender_name(user),
            avatar_url=_generate_presigned_url(user.avatar_url),
        )
        for user in users
    ]


def build_message_dto(
    message: ChatMessage,
    reactions=None,
    viewer_id: Optional[UUID] = None,
    prayer_count: int = 0,
    prayed_by_me: bool = False,
    recent_prayers=None,
) -> ChatMessageDTO:
    sender_email = message.sender.email if message.sender else "unknown@example.com"
    is_deleted = message.deleted_at is not None
    return ChatMessageDTO(
        id=message.id,
        room_id=message.room_id,
        sender_id=message.sender_id,
        sender_email=sender_email,
        sender_name=_sender_name(message.sender),
        sender_avatar_url=_generate_presigned_url(message.sender.avatar_url if message.sender else None),
        body="" if is_deleted else message.body,
        message_type=_message_type_value(message),
        created_at=_isoformat(message.created_at),
        deleted_at=_isoformat(message.deleted_at),
        parent=_build_parent_dto(message),
        reactions=_build_reaction_dtos(reactions, viewer_id),
        prayer_count=prayer_count,
        prayed_by_me=prayed_by_me,
        recent_prayers=build_prayer_user_dtos(recent_prayers),
    )


def room_kind(room: ChatRoom) -> str:
    """Which of the three room shapes this row is, derived from its columns."""
    if room.group_id is not None:
        return ChatRoomKind.GROUP.value
    if getattr(room, "event_id", None) is not None:
        return ChatRoomKind.EVENT.value
    return ChatRoomKind.PRIVATE.value


def build_room_dto(
    db: Session,
    room: ChatRoom,
    viewer_id: UUID,
    last_message: Optional[ChatMessage] = None,
) -> ChatRoomDTO:
    if last_message is None:
        last_message = get_last_message(db=db, room_id=room.id)

    viewer_member = get_active_member(db=db, room_id=room.id, user_id=viewer_id)
    last_read_at = viewer_member.last_read_at if viewer_member else None
    unread_count = count_unread_messages(db=db, room_id=room.id, last_read_at=last_read_at)

    other_user_id = other_user_email = other_user_name = None
    # DM rooms only: an event room has no sender/receiver pair either.
    if room_kind(room) == ChatRoomKind.PRIVATE.value:
        other_id = room.receiver_id if room.sender_id == viewer_id else room.sender_id
        other_user = db.query(Users).filter(Users.id == other_id).first()
        if other_user:
            other_user_id = other_user.id
            other_user_email = other_user.email
            other_user_name = f"{other_user.firstname} {other_user.lastname or ''}".strip()

    return ChatRoomDTO(
        id=room.id,
        group_id=room.group_id,
        event_id=getattr(room, "event_id", None),
        sender_id=room.sender_id,
        receiver_id=room.receiver_id,
        kind=room_kind(room),
        name=room.name,
        img_url=_generate_presigned_url(room.img_url),
        created_by=room.created_by,
        member_count=count_active_members(db=db, room_id=room.id),
        updated_at=_isoformat(room.updated_at),
        last_message=build_message_dto(last_message) if last_message else None,
        unread_count=unread_count,
        other_user_id=other_user_id,
        other_user_email=other_user_email,
        other_user_name=other_user_name,
    )


def _default_group_room_name(group: AuthorGroup) -> str:
    if group.metadata_entries:
        return group.metadata_entries[0].title
    return group.slug


def _is_eligible_for_group_chat(db: Session, group_id: UUID, user_id: UUID) -> bool:
    return is_user_joined_group(
        db=db, group_id=group_id, user_id=user_id
    ) or is_user_following_group(db=db, group_id=group_id, user_id=user_id)


def _require_group_chat_eligibility(db: Session, group_id: UUID, user_id: UUID) -> None:
    if not _is_eligible_for_group_chat(db=db, group_id=group_id, user_id=user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only joined or following members of this group can send messages in its chat",
        )


def _ensure_membership(
    db: Session,
    room: ChatRoom,
    user: Users,
    require_eligibility,
) -> None:
    """Make the caller an active member of an existing room: add them as a
    MEMBER, or clear the left_at of a member who had left. Eligibility is only
    re-checked for someone who is not already in the room."""
    member = get_member(db=db, room_id=room.id, user_id=user.id)
    if member is not None and member.left_at is None:
        return
    require_eligibility()
    if member is None:
        add_member(
            db=db,
            member=ChatRoomMember(
                room_id=room.id,
                user_id=user.id,
                role=ChatRoomMemberRole.MEMBER.value,
            ),
        )
    else:
        member.left_at = None
        db.commit()


def resolve_or_create_group_room(
    db: Session,
    group_id: UUID,
    user: Users,
    lock_group: bool = False,
) -> ChatRoom:
    """Get the group's chat room, auto-creating it (with the caller as CREATOR)
    on the first message if the caller is a joiner/follower of the group. Any
    other joiner/follower is auto-added (or re-activated) as a MEMBER the
    first time they reach an already-existing room."""
    # Before the existing-room shortcut, so a room created while the group was
    # live stops serving once it is hidden. Writers pass lock_group=True to keep
    # a concurrent hide out of the gap before their commit.
    if not is_group_id_published(db=db, group_id=group_id, for_update=lock_group):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)

    room = get_room_by_group_id(db=db, group_id=group_id)
    if room is not None:
        _ensure_membership(
            db=db,
            room=room,
            user=user,
            require_eligibility=lambda: _require_group_chat_eligibility(
                db=db, group_id=group_id, user_id=user.id
            ),
        )
        return room

    _require_group_chat_eligibility(db=db, group_id=group_id, user_id=user.id)

    # Full object needed here for the room's name and avatar.
    group = get_group_by_id(db=db, group_id=group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)

    room = ChatRoom(
        group_id=group_id,
        name=_default_group_room_name(group),
        img_url=group.avatar_key,
        created_by=user.id,
    )
    room = create_room(db=db, room=room)
    add_member(
        db=db,
        member=ChatRoomMember(
            room_id=room.id,
            user_id=user.id,
            role=ChatRoomMemberRole.CREATOR.value,
        ),
    )
    return room


def _default_event_room_name(event) -> str:
    if event.metadata_entries:
        return event.metadata_entries[0].name
    return "Event chat"


def load_open_event(db: Session, event_id: UUID, for_update: bool = False):
    """The event behind an event room, or 404.

    An event room serves requests only while the event exists, its chat has not
    been switched off in the CMS, and the owning group is still published.
    Writers pass for_update=True so a concurrent hide cannot slip into the gap
    before their commit."""
    event = get_event_by_id(db, event_id)
    if event is None or event.chat_enabled is False:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
    if not is_group_id_published(db=db, group_id=event.group_id, for_update=for_update):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
    return event


def _require_event_chat_eligibility(db: Session, event, user_id: UUID) -> None:
    """Anyone who can see the event can talk in its room: the event's chat
    reuses the owning group's joiner/follower rule, so RSVP is not required."""
    if not _is_eligible_for_group_chat(db=db, group_id=event.group_id, user_id=user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only joined or following members of this event's group can send messages in its chat",
        )


def resolve_or_create_event_room(
    db: Session,
    event_id: UUID,
    user: Users,
    lock_group: bool = False,
) -> ChatRoom:
    """Get the event's chat room, auto-creating it (with the caller as CREATOR)
    on the first message if the caller is a joiner/follower of the event's
    group. Mirrors resolve_or_create_group_room, including auto-adding any
    other eligible user who reaches an already-existing room.

    Recurring events compute their occurrences rather than storing them, so one
    room per event row serves every occurrence."""
    event = load_open_event(db=db, event_id=event_id, for_update=lock_group)

    # Checked unconditionally, even for an already-active member: unlike a
    # group room (whose membership is explicitly closed out by
    # leave_group_chat_room the moment the user leaves/unfollows), an event's
    # owning group can also change out from under a standing membership when
    # the event is moved to a different group in the CMS. A stale membership
    # row must not keep granting access in either case.
    _require_event_chat_eligibility(db=db, event=event, user_id=user.id)

    room = get_room_by_event_id(db=db, event_id=event_id)
    if room is not None:
        _ensure_membership(
            db=db,
            room=room,
            user=user,
            require_eligibility=lambda: None,
        )
        return room

    room = ChatRoom(
        event_id=event_id,
        name=_default_event_room_name(event),
        img_url=event.image_url,
        created_by=user.id,
    )
    room = create_room(db=db, room=room)
    add_member(
        db=db,
        member=ChatRoomMember(
            room_id=room.id,
            user_id=user.id,
            role=ChatRoomMemberRole.CREATOR.value,
        ),
    )
    return room


def join_event_chat_room(db: Session, event_id: UUID, user: Users) -> None:
    """Put an RSVPing user into the event's room so it shows up in their inbox
    before they ever type. No-op when no room exists yet - the first message
    creates it - or when the caller is not eligible for the group's chat."""
    room = get_room_by_event_id(db=db, event_id=event_id)
    if room is None:
        return
    event = get_event_by_id(db, event_id)
    if event is None:
        return
    if not _is_eligible_for_group_chat(db=db, group_id=event.group_id, user_id=user.id):
        return
    _ensure_membership(db=db, room=room, user=user, require_eligibility=lambda: None)


def leave_event_chat_room(db: Session, event_id: UUID, user_id: UUID) -> None:
    """Mark the caller as having left the event's chat room, so un-RSVPing
    drops it from their inbox. No-op if there is no room or they were not in it."""
    room = get_room_by_event_id(db=db, event_id=event_id)
    if room is None:
        return
    member = get_active_member(db=db, room_id=room.id, user_id=user_id)
    if member is not None:
        leave_member(db=db, member=member)


def resolve_or_create_private_room(db: Session, user: Users, receiver_id: UUID) -> ChatRoom:
    """Get the DM room between user and receiver_id, auto-creating it (with
    both as MEMBER) on the first message. Normalizes the pair so either
    direction resolves to the same room."""
    if receiver_id == user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot start a chat with yourself",
        )

    other = db.query(Users).filter(Users.id == receiver_id).first()
    if not other:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)

    low_id, high_id = sorted([user.id, receiver_id])
    room = get_room_by_pair(db=db, low_id=low_id, high_id=high_id)
    if room is not None:
        return room

    room = ChatRoom(
        sender_id=low_id,
        receiver_id=high_id,
        name=f"{user.firstname} & {other.firstname}",
        created_by=user.id,
    )
    room = create_room(db=db, room=room)
    for member_user_id in (low_id, high_id):
        add_member(
            db=db,
            member=ChatRoomMember(
                room_id=room.id,
                user_id=member_user_id,
                role=ChatRoomMemberRole.MEMBER.value,
            ),
        )
    return room


def leave_group_chat_room(db: Session, group_id: UUID, user_id: UUID) -> None:
    """Mark the caller as having left the group's chat room, if one exists and
    they were an active member. Called whenever a user's group membership ends
    so the chat room list (list_my_active_rooms) stops showing it. No-op if
    the group has no room yet or the user was never in it."""
    room = get_room_by_group_id(db=db, group_id=group_id)
    if room is None:
        return
    member = get_active_member(db=db, room_id=room.id, user_id=user_id)
    if member is not None:
        leave_member(db=db, member=member)


def _get_room_or_404(db: Session, room_id: UUID) -> ChatRoom:
    room = get_room_by_id(db=db, room_id=room_id)
    if not room:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
    # Every room-id route resolves through here, so one gate closes detail,
    # history, reactions, prayers, reports and member ops. DM rooms have no
    # group_id and no event_id.
    if room.group_id is not None and not is_group_id_published(
        db=db, group_id=room.group_id
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
    if getattr(room, "event_id", None) is not None:
        # Raises 404 for a deleted event, a chat switched off in the CMS, or an
        # unpublished owning group.
        load_open_event(db=db, event_id=room.event_id)
    return room


async def close_event_chat_sockets(event_id: UUID, reason: str) -> None:
    """Drop live sockets for an event whose chat is no longer reachable.

    Best-effort, like close_group_chat_sockets: a Redis failure must not fail
    the CMS write that triggered it."""
    try:
        with SessionLocal() as db:
            room = get_room_by_event_id(db=db, event_id=event_id)
        if room is None:
            return
        from pecha_api.chat.chat_websocket import get_broadcaster

        await get_broadcaster().broadcast_room_closed(room_id=room.id, reason=reason)
    except Exception:
        logger.exception(f"Failed to close chat sockets for event {event_id}")


async def close_group_chat_sockets(group_id: UUID) -> None:
    """Drop live chat sockets for a group that is no longer published.

    Best-effort: a Redis failure must not fail the hide. Worst case the socket
    survives to its next frame, where the request-layer gate ends it.
    """
    try:
        with SessionLocal() as db:
            room = get_room_by_group_id(db=db, group_id=group_id)
        if room is None:
            return
        from pecha_api.chat.chat_websocket import get_broadcaster

        await get_broadcaster().broadcast_room_closed(
            room_id=room.id, reason="GROUP_UNPUBLISHED"
        )
    except Exception:
        logger.exception(f"Failed to close chat sockets for group {group_id}")


def _require_active_member(db: Session, room_id: UUID, user_id: UUID) -> ChatRoomMember:
    member = get_active_member(db=db, room_id=room_id, user_id=user_id)
    if not member:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=FORBIDDEN)
    return member


def get_room_detail_service(room_id: UUID, user: Users) -> ChatRoomDTO:
    with SessionLocal() as db:
        room = _get_room_or_404(db=db, room_id=room_id)
        _require_active_member(db=db, room_id=room_id, user_id=user.id)
        return build_room_dto(db=db, room=room, viewer_id=user.id)


def get_event_room_service(event_id: UUID, user: Users) -> ChatRoomDTO:
    """The event's chat room, created on first use, with the caller joined.

    Lets a client open an event's room (and start receiving it in their inbox)
    without having to post a message first."""
    with SessionLocal() as db:
        room = resolve_or_create_event_room(db=db, event_id=event_id, user=user)
        return build_room_dto(db=db, room=room, viewer_id=user.id)


def list_my_rooms_service(user: Users, skip: int = 0, limit: int = 20) -> ChatRoomsResponse:
    with SessionLocal() as db:
        rooms, total = list_my_active_rooms(db=db, user_id=user.id, skip=skip, limit=limit)
        last_messages = get_last_messages_map(db=db, room_ids=[room.id for room in rooms])
        return ChatRoomsResponse(
            rooms=[
                build_room_dto(
                    db=db,
                    room=room,
                    viewer_id=user.id,
                    last_message=last_messages.get(room.id),
                )
                for room in rooms
            ],
            skip=skip,
            limit=limit,
            total=total,
        )


def update_room_profile_service(
    room_id: UUID,
    user: Users,
    name: Optional[str],
    img_url: Optional[str],
) -> ChatRoomDTO:
    with SessionLocal() as db:
        room = _get_room_or_404(db=db, room_id=room_id)
        member = _require_active_member(db=db, room_id=room_id, user_id=user.id)

        # Group and event rooms: creator only. DMs: either participant.
        if (
            room_kind(room) != ChatRoomKind.PRIVATE.value
            and member.role != ChatRoomMemberRole.CREATOR.value
        ):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=FORBIDDEN)

        if name is not None:
            room.name = name
        if img_url is not None:
            room.img_url = img_url

        room = update_room(db=db, room=room)
        return build_room_dto(db=db, room=room, viewer_id=user.id)


def mark_room_read_service(room_id: UUID, user: Users) -> None:
    with SessionLocal() as db:
        _get_room_or_404(db=db, room_id=room_id)
        member = _require_active_member(db=db, room_id=room_id, user_id=user.id)
        mark_read(db=db, member=member)


def list_group_people_service(
    group_id: UUID,
    user: Users,
    skip: int = 0,
    limit: int = 50,
) -> ChatPeopleResponse:
    """List a group's joiners as DM candidates (excluding the caller), so a
    client can start a direct chat without already knowing a user_id."""
    with SessionLocal() as db:
        group = get_group_by_id(db=db, group_id=group_id)
        if not group or not is_group_published(group):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)

        users, total = list_group_joiners_paginated(db=db, group_id=group_id, skip=skip, limit=limit)
        return ChatPeopleResponse(
            people=[
                ChatPersonDTO(
                    user_id=joiner.id,
                    email=joiner.email,
                    firstname=joiner.firstname,
                    lastname=joiner.lastname,
                    avatar_url=joiner.avatar_url,
                )
                for joiner in users
                if joiner.id != user.id
            ],
            skip=skip,
            limit=limit,
            total=total,
        )
