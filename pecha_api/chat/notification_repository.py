from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple
from uuid import UUID

from sqlalchemy import and_, func, or_, select, true
from sqlalchemy.orm import Session, aliased

from pecha_api.chat.models import ChatRoom, ChatRoomMember
from pecha_api.notification.notification_preference_enums import (
    NotificationChannel,
    NotificationScope,
    NotificationType,
)
from pecha_api.notification.notification_preference_models import (
    UserNotificationPreference,
)
from pecha_api.plans.groups.groups_models import author_group_joins
from pecha_api.push_devices.push_device_models import PushDeviceToken
from pecha_api.users.users_models import Users


def _normalize_platform(value) -> str:
    raw = value.value if hasattr(value, "value") else str(value)
    if "." in raw:
        raw = raw.rsplit(".", 1)[-1]
    return raw.lower()


def list_private_chat_recipient_user_ids(
    *,
    room: ChatRoom,
    sender_id: UUID,
) -> List[UUID]:
    if room.sender_id == sender_id:
        return [room.receiver_id] if room.receiver_id else []
    if room.receiver_id == sender_id:
        return [room.sender_id] if room.sender_id else []
    return []


def _preference_filtered_join(
    *,
    group_id: UUID,
    notification_type: NotificationType,
    channel: NotificationChannel,
):
    """Join `author_group_joins` to the user's preferences for one notification.

    Returns the join source plus the conditions that implement the resolution
    rule: `enabled` is most-specific-wins (a GROUP row beats a GLOBAL one,
    absent means allowed), while an unexpired `muted_until` on *either* row
    suppresses — a global snooze silences a group the user explicitly enabled.
    """
    group_pref = aliased(UserNotificationPreference)
    global_pref = aliased(UserNotificationPreference)

    source = author_group_joins.outerjoin(
        group_pref,
        and_(
            group_pref.user_id == author_group_joins.c.user_id,
            group_pref.notification_type == notification_type,
            group_pref.channel == channel,
            group_pref.scope_type == NotificationScope.GROUP,
            group_pref.scope_id == group_id,
        ),
    ).outerjoin(
        global_pref,
        and_(
            global_pref.user_id == author_group_joins.c.user_id,
            global_pref.notification_type == notification_type,
            global_pref.channel == channel,
            global_pref.scope_id.is_(None),
        ),
    )

    # An IS NULL check covers both the un-matched LEFT JOIN and the un-muted row.
    conditions = [
        func.coalesce(group_pref.enabled, global_pref.enabled, true()).is_(True),
        or_(group_pref.muted_until.is_(None), group_pref.muted_until <= func.now()),
        or_(global_pref.muted_until.is_(None), global_pref.muted_until <= func.now()),
    ]
    return source, conditions


def list_group_chat_recipient_user_ids(
    db: Session,
    *,
    group_id: UUID,
    sender_id: UUID,
    skip: int,
    limit: int,
    notification_type: Optional[NotificationType] = None,
    channel: NotificationChannel = NotificationChannel.PUSH,
) -> Tuple[List[UUID], int]:
    """Members of a group who should receive one notification, paginated.

    Preference filtering is applied to the page *and* the count, so `total`
    stays consistent with what is returned — the worker pages off `total` and
    `has_more`, which a post-filter would leave wrong. Passing no
    `notification_type` skips filtering entirely.
    """
    source = author_group_joins
    conditions = [
        author_group_joins.c.group_id == group_id,
        author_group_joins.c.user_id != sender_id,
    ]

    if notification_type is not None:
        source, preference_conditions = _preference_filtered_join(
            group_id=group_id,
            notification_type=notification_type,
            channel=channel,
        )
        conditions.extend(preference_conditions)

    base = (
        select(author_group_joins.c.user_id)
        .select_from(source)
        .where(*conditions)
        .order_by(author_group_joins.c.created_at.asc(), author_group_joins.c.user_id.asc())
    )
    total = (
        db.execute(select(func.count()).select_from(source).where(*conditions)).scalar()
        or 0
    )
    rows = db.execute(base.offset(skip).limit(limit)).all()
    return [row[0] for row in rows], int(total)


def list_event_chat_recipient_user_ids(
    db: Session,
    *,
    room_id: UUID,
    sender_id: UUID,
    group_id: Optional[UUID],
    skip: int,
    limit: int,
    notification_type: Optional[NotificationType] = None,
    channel: NotificationChannel = NotificationChannel.PUSH,
) -> Tuple[List[UUID], int]:
    """Active members of an event's room who should receive one notification.

    Unlike a group room - whose audience is the group's joiners - an event
    room's audience is whoever actually joined the room, so membership is the
    source. Preferences still resolve against the group that owns the event.
    """
    conditions = [
        ChatRoomMember.room_id == room_id,
        ChatRoomMember.user_id != sender_id,
        ChatRoomMember.left_at.is_(None),
    ]
    base = (
        select(ChatRoomMember.user_id)
        .where(*conditions)
        .order_by(ChatRoomMember.joined_at.asc(), ChatRoomMember.user_id.asc())
    )
    user_ids = [row[0] for row in db.execute(base).all()]

    if notification_type is not None:
        user_ids = filter_users_by_notification_preference(
            db=db,
            user_ids=user_ids,
            notification_type=notification_type,
            channel=channel,
            scope_id=group_id,
        )

    total = len(user_ids)
    return user_ids[skip : skip + limit], total


def filter_users_by_notification_preference(
    db: Session,
    *,
    user_ids: Sequence[UUID],
    notification_type: NotificationType,
    channel: NotificationChannel = NotificationChannel.PUSH,
    scope_id: Optional[UUID] = None,
) -> List[UUID]:
    """Drop users who have opted out of a notification.

    With no `scope_id` only GLOBAL rows can apply (the private-chat path). With
    one, the same resolution rule as the group paths applies: `enabled` is
    most-specific-wins (a GROUP row beats a GLOBAL one), while an unexpired
    `muted_until` on *either* row suppresses. Order of `user_ids` is preserved.
    """
    if not user_ids:
        return []

    scope_filter = UserNotificationPreference.scope_id.is_(None)
    if scope_id is not None:
        scope_filter = or_(scope_filter, UserNotificationPreference.scope_id == scope_id)

    rows = db.execute(
        select(
            UserNotificationPreference.user_id,
            UserNotificationPreference.enabled,
            UserNotificationPreference.muted_until,
            UserNotificationPreference.scope_id,
        ).where(
            UserNotificationPreference.user_id.in_(list(user_ids)),
            UserNotificationPreference.notification_type == notification_type,
            UserNotificationPreference.channel == channel,
            scope_filter,
        )
    ).all()

    now = datetime.now(timezone.utc)
    blocked: set[UUID] = set()
    # Most-specific-wins for `enabled`: a scoped row, when present, decides.
    enabled_by_user: Dict[UUID, Tuple[bool, bool]] = {}
    for user_id, enabled, muted_until, row_scope_id in rows:
        is_scoped = row_scope_id is not None
        previous = enabled_by_user.get(user_id)
        if previous is None or (is_scoped and not previous[1]):
            enabled_by_user[user_id] = (bool(enabled), is_scoped)
        if muted_until is not None:
            if muted_until.tzinfo is None:
                muted_until = muted_until.replace(tzinfo=timezone.utc)
            if muted_until > now:
                blocked.add(user_id)

    for user_id, (enabled, _) in enabled_by_user.items():
        if not enabled:
            blocked.add(user_id)

    return [user_id for user_id in user_ids if user_id not in blocked]


def get_active_push_devices_by_user_ids(
    db: Session,
    user_ids: Sequence[UUID],
) -> Dict[UUID, List[PushDeviceToken]]:
    if not user_ids:
        return {}
    rows = (
        db.query(PushDeviceToken)
        .filter(
            PushDeviceToken.user_id.in_(list(user_ids)),
            PushDeviceToken.is_active.is_(True),
        )
        .order_by(PushDeviceToken.updated_at.desc())
        .all()
    )
    result: Dict[UUID, List[PushDeviceToken]] = defaultdict(list)
    for device in rows:
        result[device.user_id].append(device)
    return dict(result)


def deactivate_push_device_token_by_id(
    db: Session,
    push_device_id: UUID,
) -> Optional[PushDeviceToken]:
    device = (
        db.query(PushDeviceToken)
        .filter(PushDeviceToken.id == push_device_id)
        .first()
    )
    if not device:
        return None
    if not device.is_active:
        return device
    device.is_active = False
    db.commit()
    db.refresh(device)
    return device


def get_sender_display_name(db: Session, sender_id: UUID) -> str:
    user = db.query(Users).filter(Users.id == sender_id).first()
    if not user:
        return "Someone"
    return f"{user.firstname} {user.lastname or ''}".strip() or user.email


def normalize_platform(value) -> str:
    return _normalize_platform(value)
