from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Set, Tuple
from uuid import UUID, uuid4

from sqlalchemy import exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, selectinload

from pecha_api.plans.groups.groups_enums import AuthorGroupStatus
from pecha_api.plans.groups.groups_models import AuthorGroup, author_group_followers, author_group_joins
from pecha_api.events.event_model import Event

from pecha_api.chat.enums import ChatMessageReportSource, ChatRoomMemberRole
from pecha_api.chat.models import (
    ChatMessage,
    ChatMessagePrayer,
    ChatMessageReaction,
    ChatMessageReport,
    ChatRoom,
    ChatRoomMember,
)
from pecha_api.users.users_models import Users


def get_room_by_id(db: Session, room_id: UUID) -> Optional[ChatRoom]:
    return (
        db.query(ChatRoom)
        .filter(ChatRoom.id == room_id, ChatRoom.deleted_at.is_(None))
        .first()
    )


def get_room_by_group_id(db: Session, group_id: UUID) -> Optional[ChatRoom]:
    return (
        db.query(ChatRoom)
        .filter(ChatRoom.group_id == group_id, ChatRoom.deleted_at.is_(None))
        .first()
    )


def get_room_by_event_id(db: Session, event_id: UUID) -> Optional[ChatRoom]:
    return (
        db.query(ChatRoom)
        .filter(ChatRoom.event_id == event_id, ChatRoom.deleted_at.is_(None))
        .first()
    )


def get_room_ids_by_event_ids(
    db: Session,
    event_ids: Sequence[UUID],
) -> Dict[UUID, UUID]:
    """Room id for each event that has one, keyed by event_id.

    One query per page of events, so a list endpoint can carry the room link
    without a lookup per row. Events with no room yet are simply absent."""
    if not event_ids:
        return {}
    rows = (
        db.query(ChatRoom.event_id, ChatRoom.id)
        .filter(ChatRoom.event_id.in_(event_ids), ChatRoom.deleted_at.is_(None))
        .all()
    )
    return dict(rows)


def get_room_by_pair(db: Session, low_id: UUID, high_id: UUID) -> Optional[ChatRoom]:
    return (
        db.query(ChatRoom)
        .filter(
            ChatRoom.sender_id == low_id,
            ChatRoom.receiver_id == high_id,
            ChatRoom.deleted_at.is_(None),
        )
        .first()
    )


def create_room(db: Session, room: ChatRoom) -> ChatRoom:
    db.add(room)
    db.commit()
    db.refresh(room)
    return room


def update_room(db: Session, room: ChatRoom) -> ChatRoom:
    room.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(room)
    return room


def touch_room(db: Session, room: ChatRoom) -> None:
    room.updated_at = datetime.now(timezone.utc)
    db.commit()


def add_member(db: Session, member: ChatRoomMember) -> ChatRoomMember:
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


def get_member(db: Session, room_id: UUID, user_id: UUID) -> Optional[ChatRoomMember]:
    return (
        db.query(ChatRoomMember)
        .filter(ChatRoomMember.room_id == room_id, ChatRoomMember.user_id == user_id)
        .first()
    )


def get_active_member(db: Session, room_id: UUID, user_id: UUID) -> Optional[ChatRoomMember]:
    return (
        db.query(ChatRoomMember)
        .filter(
            ChatRoomMember.room_id == room_id,
            ChatRoomMember.user_id == user_id,
            ChatRoomMember.left_at.is_(None),
        )
        .first()
    )


def get_creator(db: Session, room_id: UUID) -> Optional[ChatRoomMember]:
    return (
        db.query(ChatRoomMember)
        .filter(
            ChatRoomMember.room_id == room_id,
            ChatRoomMember.role == ChatRoomMemberRole.CREATOR.value,
            ChatRoomMember.left_at.is_(None),
        )
        .first()
    )


def list_active_members(
    db: Session,
    room_id: UUID,
    skip: int = 0,
    limit: int = 20,
) -> Tuple[List[ChatRoomMember], int]:
    query = (
        db.query(ChatRoomMember)
        .options(selectinload(ChatRoomMember.user))
        .filter(ChatRoomMember.room_id == room_id, ChatRoomMember.left_at.is_(None))
    )
    total = query.count()
    members = query.order_by(ChatRoomMember.joined_at.asc()).offset(skip).limit(limit).all()
    return members, total


def count_active_members(db: Session, room_id: UUID) -> int:
    return (
        db.query(func.count(ChatRoomMember.id))
        .filter(ChatRoomMember.room_id == room_id, ChatRoomMember.left_at.is_(None))
        .scalar()
        or 0
    )


def leave_member(db: Session, member: ChatRoomMember) -> None:
    member.left_at = datetime.now(timezone.utc)
    db.commit()


def mark_read(db: Session, member: ChatRoomMember) -> None:
    member.last_read_at = datetime.now(timezone.utc)
    db.commit()


def list_my_active_rooms(
    db: Session,
    user_id: UUID,
    skip: int = 0,
    limit: int = 20,
) -> Tuple[List[ChatRoom], int]:
    query = (
        db.query(ChatRoom)
        .join(ChatRoomMember, ChatRoomMember.room_id == ChatRoom.id)
        .filter(
            ChatRoomMember.user_id == user_id,
            ChatRoomMember.left_at.is_(None),
            ChatRoom.deleted_at.is_(None),
            # Hide rooms whose group is no longer published. DM rooms have no
            # group_id and are unaffected. correlate() is required so the
            # subquery references the outer chat_rooms row instead of joining
            # its own copy (which would match any published group).
            or_(
                ChatRoom.group_id.is_(None),
                exists(
                    select(1)
                    .select_from(AuthorGroup)
                    .where(
                        AuthorGroup.id == ChatRoom.group_id,
                        AuthorGroup.status == AuthorGroupStatus.PUBLISHED,
                    )
                    .correlate(ChatRoom)
                ),
            ),
            # Chat access tracks live join/follow status, not just the
            # ChatRoomMember row (which flows that end membership, like
            # leave_group/unfollow_group, may not always have gotten around
            # to closing out - see leave_group_chat_room). Checked here too
            # so the list is correct even for rows left over from before that
            # existed. DM rooms have no group_id and are unaffected.
            or_(
                ChatRoom.group_id.is_(None),
                exists(
                    select(1)
                    .select_from(author_group_joins)
                    .where(
                        author_group_joins.c.group_id == ChatRoom.group_id,
                        author_group_joins.c.user_id == user_id,
                    )
                    .correlate(ChatRoom)
                ),
                exists(
                    select(1)
                    .select_from(author_group_followers)
                    .where(
                        author_group_followers.c.group_id == ChatRoom.group_id,
                        author_group_followers.c.user_id == user_id,
                    )
                    .correlate(ChatRoom)
                ),
            ),
            # Same two gates for event rooms, which carry event_id instead of
            # group_id: the owning group must still be published and still have
            # this user, and the event's chat must not have been switched off.
            or_(
                ChatRoom.event_id.is_(None),
                exists(
                    select(1)
                    .select_from(Event)
                    .join(AuthorGroup, AuthorGroup.id == Event.group_id)
                    .where(
                        Event.id == ChatRoom.event_id,
                        Event.chat_enabled.is_(True),
                        AuthorGroup.status == AuthorGroupStatus.PUBLISHED,
                    )
                    .correlate(ChatRoom)
                ),
            ),
            or_(
                ChatRoom.event_id.is_(None),
                exists(
                    select(1)
                    .select_from(Event)
                    .join(
                        author_group_joins,
                        author_group_joins.c.group_id == Event.group_id,
                    )
                    .where(
                        Event.id == ChatRoom.event_id,
                        author_group_joins.c.user_id == user_id,
                    )
                    .correlate(ChatRoom)
                ),
                exists(
                    select(1)
                    .select_from(Event)
                    .join(
                        author_group_followers,
                        author_group_followers.c.group_id == Event.group_id,
                    )
                    .where(
                        Event.id == ChatRoom.event_id,
                        author_group_followers.c.user_id == user_id,
                    )
                    .correlate(ChatRoom)
                ),
            ),
        )
    )
    total = query.count()
    rooms = (
        query.order_by(ChatRoom.updated_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return rooms, total


def create_message(db: Session, message: ChatMessage) -> ChatMessage:
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def get_room_messages(
    db: Session,
    room_id: UUID,
    skip: int = 0,
    limit: int = 20,
    message_type: Optional[str] = None,
) -> Tuple[List[ChatMessage], int]:
    query = (
        db.query(ChatMessage)
        .filter(ChatMessage.room_id == room_id)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
    )
    if message_type is not None:
        query = query.filter(ChatMessage.message_type == message_type)
    total = query.count()
    messages = (
        query.options(
            selectinload(ChatMessage.sender),
            selectinload(ChatMessage.parent).selectinload(ChatMessage.sender),
        )
        .offset(skip)
        .limit(limit)
        .all()
    )
    return messages, total


def get_message_by_id(db: Session, message_id: UUID, room_id: UUID) -> Optional[ChatMessage]:
    return (
        db.query(ChatMessage)
        .filter(
            ChatMessage.id == message_id,
            ChatMessage.room_id == room_id,
            ChatMessage.deleted_at.is_(None),
        )
        .first()
    )


def soft_delete_message(db: Session, message: ChatMessage) -> datetime:
    deleted_at = datetime.now(timezone.utc)
    message.deleted_at = deleted_at
    db.commit()
    return deleted_at


def mark_message_notification_dispatched(
    db: Session,
    message_id: UUID,
    sqs_message_id: str,
) -> Optional[ChatMessage]:
    message = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.id == message_id,
            ChatMessage.deleted_at.is_(None),
        )
        .first()
    )
    if not message:
        return None
    message.notification_sqs_message_id = sqs_message_id
    message.notification_dispatched_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(message)
    return message


def list_undispatched_chat_notification_messages(
    db: Session,
    *,
    older_than: datetime,
    limit: int,
) -> List[ChatMessage]:
    return (
        db.query(ChatMessage)
        .filter(
            ChatMessage.deleted_at.is_(None),
            ChatMessage.notification_sqs_message_id.is_(None),
            ChatMessage.created_at <= older_than,
        )
        .order_by(ChatMessage.created_at.asc())
        .limit(limit)
        .all()
    )


def get_message_by_id_any_room(db: Session, message_id: UUID) -> Optional[ChatMessage]:
    return (
        db.query(ChatMessage)
        .options(
            selectinload(ChatMessage.sender),
            selectinload(ChatMessage.room),
        )
        .filter(
            ChatMessage.id == message_id,
            ChatMessage.deleted_at.is_(None),
        )
        .first()
    )


def get_last_message(db: Session, room_id: UUID) -> Optional[ChatMessage]:
    return (
        db.query(ChatMessage)
        .options(selectinload(ChatMessage.sender))
        .filter(ChatMessage.room_id == room_id, ChatMessage.deleted_at.is_(None))
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .first()
    )


def get_last_messages_map(db: Session, room_ids: Sequence[UUID]) -> Dict[UUID, ChatMessage]:
    if not room_ids:
        return {}
    messages = (
        db.query(ChatMessage)
        .options(selectinload(ChatMessage.sender))
        .filter(ChatMessage.room_id.in_(room_ids), ChatMessage.deleted_at.is_(None))
        .order_by(ChatMessage.room_id, ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .all()
    )
    result: Dict[UUID, ChatMessage] = {}
    for message in messages:
        if message.room_id not in result:
            result[message.room_id] = message
    return result


def get_reaction(
    db: Session,
    message_id: UUID,
    user_id: UUID,
    emoji: str,
) -> Optional[ChatMessageReaction]:
    return (
        db.query(ChatMessageReaction)
        .filter(
            ChatMessageReaction.message_id == message_id,
            ChatMessageReaction.user_id == user_id,
            ChatMessageReaction.emoji == emoji,
        )
        .first()
    )


def add_reaction(db: Session, reaction: ChatMessageReaction) -> ChatMessageReaction:
    db.add(reaction)
    db.commit()
    db.refresh(reaction)
    return reaction


def remove_reaction(db: Session, reaction: ChatMessageReaction) -> None:
    db.delete(reaction)
    db.commit()


def list_message_reactions(db: Session, message_id: UUID) -> List[ChatMessageReaction]:
    return (
        db.query(ChatMessageReaction)
        .options(selectinload(ChatMessageReaction.user))
        .filter(ChatMessageReaction.message_id == message_id)
        .order_by(ChatMessageReaction.created_at.asc())
        .all()
    )


def get_reactions_map(
    db: Session,
    message_ids: Sequence[UUID],
) -> Dict[UUID, List[ChatMessageReaction]]:
    """Reactions for many messages at once, keyed by message_id."""
    if not message_ids:
        return {}
    reactions = (
        db.query(ChatMessageReaction)
        .options(selectinload(ChatMessageReaction.user))
        .filter(ChatMessageReaction.message_id.in_(message_ids))
        .order_by(ChatMessageReaction.created_at.asc())
        .all()
    )
    result: Dict[UUID, List[ChatMessageReaction]] = {}
    for reaction in reactions:
        result.setdefault(reaction.message_id, []).append(reaction)
    return result


def get_prayer(
    db: Session,
    message_id: UUID,
    user_id: UUID,
) -> Optional[ChatMessagePrayer]:
    return (
        db.query(ChatMessagePrayer)
        .filter(
            ChatMessagePrayer.message_id == message_id,
            ChatMessagePrayer.user_id == user_id,
        )
        .first()
    )


def get_prayer_by_id(db: Session, prayer_id: UUID) -> Optional[ChatMessagePrayer]:
    return (
        db.query(ChatMessagePrayer)
        .filter(ChatMessagePrayer.id == prayer_id)
        .first()
    )


def add_prayer(db: Session, prayer: ChatMessagePrayer) -> ChatMessagePrayer:
    db.add(prayer)
    db.commit()
    db.refresh(prayer)
    return prayer


def add_prayers_ignoring_duplicates(
    db: Session,
    message_ids: Sequence[UUID],
    user_id: UUID,
) -> List[Tuple[UUID, UUID]]:
    """Pray for several messages at once, in one statement and one commit.

    Rows the user already has are left alone (the uniqueness constraint is what
    makes the batch endpoint idempotent). Returns (message_id, prayer_id) for
    the prayers actually created, so only those raise a notification."""
    if not message_ids:
        return []
    statement = (
        pg_insert(ChatMessagePrayer.__table__)
        .values(
            [
                {"id": uuid4(), "message_id": message_id, "user_id": user_id}
                for message_id in message_ids
            ]
        )
        .on_conflict_do_nothing(constraint="uq_chat_message_prayers_message_user")
        .returning(
            ChatMessagePrayer.__table__.c.message_id,
            ChatMessagePrayer.__table__.c.id,
        )
    )
    created = [(row[0], row[1]) for row in db.execute(statement).all()]
    db.commit()
    return created


def remove_prayer(db: Session, prayer: ChatMessagePrayer) -> None:
    db.delete(prayer)
    db.commit()


def count_message_prayers(db: Session, message_id: UUID) -> int:
    return (
        db.query(func.count(ChatMessagePrayer.id))
        .filter(ChatMessagePrayer.message_id == message_id)
        .scalar()
        or 0
    )


def get_prayer_counts_map(
    db: Session,
    message_ids: Sequence[UUID],
) -> Dict[UUID, int]:
    """Prayer counts for many messages at once, keyed by message_id.

    One grouped query per page of messages, so the prayers table stays the
    source of truth with no denormalised counter to drift."""
    if not message_ids:
        return {}
    rows = (
        db.query(ChatMessagePrayer.message_id, func.count(ChatMessagePrayer.id))
        .filter(ChatMessagePrayer.message_id.in_(message_ids))
        .group_by(ChatMessagePrayer.message_id)
        .all()
    )
    return dict(rows)


def get_prayed_message_ids(
    db: Session,
    message_ids: Sequence[UUID],
    user_id: UUID,
) -> Set[UUID]:
    """Which of these messages the viewer has already prayed for."""
    if not message_ids:
        return set()
    rows = (
        db.query(ChatMessagePrayer.message_id)
        .filter(
            ChatMessagePrayer.message_id.in_(message_ids),
            ChatMessagePrayer.user_id == user_id,
        )
        .all()
    )
    return {row[0] for row in rows}


def get_prayer_user_ids_map(
    db: Session,
    message_ids: Sequence[UUID],
) -> Dict[UUID, List[UUID]]:
    """Everyone who prayed for each message, keyed by message_id.

    Feeds the prayers_updated broadcast, where each client works out its own
    prayed_by_me from the shared payload (reactions do the same)."""
    if not message_ids:
        return {}
    rows = (
        db.query(ChatMessagePrayer.message_id, ChatMessagePrayer.user_id)
        .filter(ChatMessagePrayer.message_id.in_(message_ids))
        .order_by(ChatMessagePrayer.created_at.asc())
        .all()
    )
    result: Dict[UUID, List[UUID]] = {}
    for message_id, user_id in rows:
        result.setdefault(message_id, []).append(user_id)
    return result


def get_recent_prayers_map(
    db: Session,
    message_ids: Sequence[UUID],
    per_message: int = 3,
) -> Dict[UUID, List[Users]]:
    """The most recent few people who prayed for each message (avatar stack).

    Ranked in one query rather than one query per message; the full roster
    comes from list_message_prayers."""
    if not message_ids or per_message < 1:
        return {}
    ranked = (
        db.query(
            ChatMessagePrayer.message_id.label("message_id"),
            ChatMessagePrayer.user_id.label("user_id"),
            func.row_number()
            .over(
                partition_by=ChatMessagePrayer.message_id,
                order_by=ChatMessagePrayer.created_at.desc(),
            )
            .label("rank"),
        )
        .filter(ChatMessagePrayer.message_id.in_(message_ids))
        .subquery()
    )
    rows = (
        db.query(ranked.c.message_id, Users)
        .join(Users, Users.id == ranked.c.user_id)
        .filter(ranked.c.rank <= per_message)
        .order_by(ranked.c.message_id, ranked.c.rank)
        .all()
    )
    result: Dict[UUID, List[Users]] = {}
    for message_id, user in rows:
        result.setdefault(message_id, []).append(user)
    return result


def list_message_prayers(
    db: Session,
    message_id: UUID,
    skip: int = 0,
    limit: int = 20,
) -> Tuple[List[ChatMessagePrayer], int]:
    """Who prayed for one request, newest first."""
    query = db.query(ChatMessagePrayer).filter(
        ChatMessagePrayer.message_id == message_id
    )
    total = query.with_entities(func.count(ChatMessagePrayer.id)).scalar() or 0
    prayers = (
        query.options(selectinload(ChatMessagePrayer.user))
        .order_by(ChatMessagePrayer.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return prayers, total


# Written to notification_sqs_message_id for a prayer that deliberately did not
# raise a push (self-pray, or one already covered by a recent notification for
# the same request). Excluded from has_dispatched_prayer_since below so a
# suppressed prayer never counts as an actual dispatch for coalescing.
SUPPRESSED_SQS_MESSAGE_ID = "SUPPRESSED"


def has_dispatched_prayer_since(
    db: Session,
    *,
    message_id: UUID,
    since: datetime,
    exclude_prayer_id: Optional[UUID] = None,
) -> bool:
    """Whether this request already had a prayer notification actually sent
    (not merely suppressed) recently.

    Backs coalescing: ten people praying in the same window is one push, not ten."""
    query = db.query(ChatMessagePrayer.id).filter(
        ChatMessagePrayer.message_id == message_id,
        ChatMessagePrayer.notification_dispatched_at.isnot(None),
        ChatMessagePrayer.notification_dispatched_at >= since,
        ChatMessagePrayer.notification_sqs_message_id.isnot(None),
        ChatMessagePrayer.notification_sqs_message_id != SUPPRESSED_SQS_MESSAGE_ID,
    )
    if exclude_prayer_id is not None:
        query = query.filter(ChatMessagePrayer.id != exclude_prayer_id)
    return db.query(query.exists()).scalar() or False


def mark_prayer_notification_dispatched(
    db: Session,
    prayer_id: UUID,
    sqs_message_id: str,
) -> Optional[ChatMessagePrayer]:
    prayer = get_prayer_by_id(db=db, prayer_id=prayer_id)
    if not prayer:
        return None
    prayer.notification_sqs_message_id = sqs_message_id
    prayer.notification_dispatched_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(prayer)
    return prayer


def list_undispatched_prayer_notifications(
    db: Session,
    *,
    older_than: datetime,
    limit: int,
) -> List[ChatMessagePrayer]:
    return (
        db.query(ChatMessagePrayer)
        .filter(
            ChatMessagePrayer.notification_sqs_message_id.is_(None),
            ChatMessagePrayer.created_at <= older_than,
        )
        .order_by(ChatMessagePrayer.created_at.asc())
        .limit(limit)
        .all()
    )


def get_report_by_message_and_reporter(
    db: Session,
    message_id: UUID,
    reporter_id: UUID,
) -> Optional[ChatMessageReport]:
    return (
        db.query(ChatMessageReport)
        .filter(
            ChatMessageReport.message_id == message_id,
            ChatMessageReport.reporter_id == reporter_id,
        )
        .first()
    )


def list_reports(
    db: Session,
    skip: int = 0,
    limit: int = 20,
    source: Optional[str] = None,
    reason: Optional[str] = None,
    resolved: Optional[bool] = None,
) -> Tuple[List[ChatMessageReport], int]:
    """Paginated moderation reports, newest first, with the people and
    message context eagerly loaded for display."""
    query = db.query(ChatMessageReport)
    if source:
        query = query.filter(ChatMessageReport.source == source)
    if reason:
        query = query.filter(ChatMessageReport.reason == reason)
    if resolved is True:
        query = query.filter(ChatMessageReport.resolved_at.isnot(None))
    elif resolved is False:
        query = query.filter(ChatMessageReport.resolved_at.is_(None))
    total = query.with_entities(func.count(ChatMessageReport.id)).scalar() or 0
    reports = (
        query.options(
            selectinload(ChatMessageReport.reporter),
            selectinload(ChatMessageReport.reported_user),
            selectinload(ChatMessageReport.room),
            selectinload(ChatMessageReport.message).selectinload(ChatMessage.sender),
            selectinload(ChatMessageReport.message).selectinload(ChatMessage.room),
        )
        .order_by(ChatMessageReport.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return reports, total


def get_unresolved_automatic_report(
    db: Session,
    room_id: UUID,
    reported_user_id: UUID,
    message_text: str,
) -> Optional[ChatMessageReport]:
    """An open system-generated report for the same rejected content, used to
    keep retried sends of the same message from piling up duplicate reports."""
    return (
        db.query(ChatMessageReport)
        .filter(
            ChatMessageReport.source == ChatMessageReportSource.AUTOMATIC.value,
            ChatMessageReport.room_id == room_id,
            ChatMessageReport.reported_user_id == reported_user_id,
            ChatMessageReport.message_text == message_text,
            ChatMessageReport.resolved_at.is_(None),
        )
        .first()
    )


def create_report(db: Session, report: ChatMessageReport) -> ChatMessageReport:
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


def count_unread_messages(
    db: Session,
    room_id: UUID,
    last_read_at: Optional[datetime],
) -> int:
    query = db.query(func.count(ChatMessage.id)).filter(
        ChatMessage.room_id == room_id,
        ChatMessage.deleted_at.is_(None),
    )
    if last_read_at is not None:
        query = query.filter(ChatMessage.created_at > last_read_at)
    return query.scalar() or 0
