from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import and_, delete, exists, func, or_, select, true
from sqlalchemy.orm import Session, aliased

from pecha_api.notification.notification_preference_enums import (
    NotificationChannel,
    NotificationScope,
    NotificationType,
)
from pecha_api.notification.notification_preference_models import (
    UserNotificationPreference,
)

PreferenceKey = Tuple[NotificationType, Optional[UUID]]


def list_preferences_for_user(
    db: Session,
    *,
    user_id: UUID,
    channel: NotificationChannel,
    scope_id: Optional[UUID] = None,
) -> List[UserNotificationPreference]:
    """Rows for one user on one channel.

    With `scope_id` set, narrows to that group's rows plus the global ones —
    exactly what resolving a single group needs. Without it, returns every row,
    which the global endpoint splits into globals and override summaries.
    """
    conditions = [
        UserNotificationPreference.user_id == user_id,
        UserNotificationPreference.channel == channel,
    ]
    if scope_id is not None:
        conditions.append(
            (UserNotificationPreference.scope_id == scope_id)
            | UserNotificationPreference.scope_id.is_(None)
        )

    return list(db.execute(select(UserNotificationPreference).where(*conditions)).scalars())


def index_by_key(
    rows: List[UserNotificationPreference],
) -> Dict[PreferenceKey, UserNotificationPreference]:
    return {(row.notification_type, row.scope_id): row for row in rows}


def global_preference_blocks(
    user_id_column,
    *,
    notification_type: NotificationType,
    channel: NotificationChannel = NotificationChannel.PUSH,
):
    """A correlated EXISTS that is true when a GLOBAL row suppresses delivery.

    Types with no group scope - `EVENT_REMINDER`, `SERIES` - resolve against
    the GLOBAL row alone, so the whole of the resolution rule collapses to a
    single NOT EXISTS that drops into any recipient query holding a user id
    column, ahead of its pagination and inside its count. Group-scoped types
    still need the two-join form in
    `chat/notification_repository._preference_filtered_join`, where a GROUP
    row can override the global one.
    """
    return exists().where(
        UserNotificationPreference.user_id == user_id_column,
        UserNotificationPreference.notification_type == notification_type,
        UserNotificationPreference.channel == channel,
        UserNotificationPreference.scope_id.is_(None),
        or_(
            UserNotificationPreference.enabled.is_(False),
            and_(
                UserNotificationPreference.muted_until.isnot(None),
                UserNotificationPreference.muted_until > func.now(),
            ),
        ),
    )


def scoped_preference_filter(
    user_id_column,
    *,
    notification_type: NotificationType,
    channel: NotificationChannel,
    scope_type: NotificationScope,
    scope_id: UUID,
):
    """Join targets and conditions resolving one scope against the global row.

    Returns (join_targets, conditions): each join target is an (alias,
    onclause) pair the caller outer-joins onto a query already selecting a
    user id column, and the conditions implement the resolution rule -
    `enabled` is most-specific-wins (a scoped row beats the global one, absent
    means allowed), while an unexpired `muted_until` on *either* row
    suppresses, so a global snooze still silences a scope the user explicitly
    enabled.

    A correlated EXISTS cannot express this: "scoped row says yes" has to
    override "global row says no", which needs both rows in hand at once.
    """
    scoped = aliased(UserNotificationPreference)
    global_row = aliased(UserNotificationPreference)

    join_targets = [
        (
            scoped,
            and_(
                scoped.user_id == user_id_column,
                scoped.notification_type == notification_type,
                scoped.channel == channel,
                scoped.scope_type == scope_type,
                scoped.scope_id == scope_id,
            ),
        ),
        (
            global_row,
            and_(
                global_row.user_id == user_id_column,
                global_row.notification_type == notification_type,
                global_row.channel == channel,
                global_row.scope_id.is_(None),
            ),
        ),
    ]

    # An IS NULL check covers both the un-matched LEFT JOIN and the un-muted row.
    conditions = [
        func.coalesce(scoped.enabled, global_row.enabled, true()).is_(True),
        or_(scoped.muted_until.is_(None), scoped.muted_until <= func.now()),
        or_(global_row.muted_until.is_(None), global_row.muted_until <= func.now()),
    ]
    return join_targets, conditions


def get_preference(
    db: Session,
    *,
    user_id: UUID,
    notification_type: NotificationType,
    channel: NotificationChannel,
    scope_id: Optional[UUID],
) -> Optional[UserNotificationPreference]:
    scope_filter = (
        UserNotificationPreference.scope_id.is_(None)
        if scope_id is None
        else UserNotificationPreference.scope_id == scope_id
    )
    return db.execute(
        select(UserNotificationPreference).where(
            UserNotificationPreference.user_id == user_id,
            UserNotificationPreference.notification_type == notification_type,
            UserNotificationPreference.channel == channel,
            scope_filter,
        )
    ).scalar_one_or_none()


def upsert_preference(
    db: Session,
    *,
    user_id: UUID,
    notification_type: NotificationType,
    channel: NotificationChannel,
    scope_id: Optional[UUID],
    scope_type: Optional[NotificationScope] = None,
    enabled: Optional[bool] = None,
    muted_until: Optional[datetime] = None,
    set_enabled: bool = False,
    set_muted_until: bool = False,
) -> UserNotificationPreference:
    """Merge one preference.

    `set_enabled` / `set_muted_until` say whether the client actually sent that
    field. A field that was not sent is left untouched on an existing row and
    falls back to its default on a new one.
    """
    existing = get_preference(
        db=db,
        user_id=user_id,
        notification_type=notification_type,
        channel=channel,
        scope_id=scope_id,
    )

    if existing is not None:
        if set_enabled:
            existing.enabled = bool(enabled)
        if set_muted_until:
            existing.muted_until = muted_until
        existing.updated_at = datetime.now(timezone.utc)
        db.add(existing)
        return existing

    preference = UserNotificationPreference(
        user_id=user_id,
        notification_type=notification_type,
        channel=channel,
        scope_type=(
            NotificationScope.GLOBAL
            if scope_id is None
            else (scope_type or NotificationScope.GROUP)
        ),
        scope_id=scope_id,
        enabled=bool(enabled) if set_enabled else True,
        muted_until=muted_until if set_muted_until else None,
    )
    db.add(preference)
    return preference


def delete_scoped_preferences(
    db: Session,
    *,
    user_id: UUID,
    scope_id: UUID,
    channel: NotificationChannel,
    notification_type: Optional[NotificationType] = None,
) -> int:
    conditions = [
        UserNotificationPreference.user_id == user_id,
        UserNotificationPreference.channel == channel,
        UserNotificationPreference.scope_id == scope_id,
    ]
    if notification_type is not None:
        conditions.append(UserNotificationPreference.notification_type == notification_type)

    result = db.execute(delete(UserNotificationPreference).where(*conditions))
    db.commit()
    return int(result.rowcount or 0)
