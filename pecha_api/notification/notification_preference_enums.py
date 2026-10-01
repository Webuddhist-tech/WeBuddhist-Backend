import enum

from sqlalchemy import Enum


class NotificationType(enum.Enum):
    CHAT_MESSAGE = "CHAT_MESSAGE"
    GROUP_POST = "GROUP_POST"
    EVENT = "EVENT"
    EVENT_REMINDER = "EVENT_REMINDER"
    ACCUMULATION = "ACCUMULATION"
    SERIES = "SERIES"
    GROUP_INVITE = "GROUP_INVITE"
    GROUP_JOIN_REQUEST = "GROUP_JOIN_REQUEST"
    VERSE_OF_DAY = "VERSE_OF_DAY"
    ROUTINE_REMINDER = "ROUTINE_REMINDER"
    PRAYER_RECEIVED = "PRAYER_RECEIVED"


class NotificationChannel(enum.Enum):
    PUSH = "PUSH"
    IN_APP = "IN_APP"
    EMAIL = "EMAIL"


class NotificationScope(enum.Enum):
    GLOBAL = "GLOBAL"
    GROUP = "GROUP"
    EVENT = "EVENT"


class PreferenceSource(enum.Enum):
    """Where a resolved `enabled` value came from. Not persisted."""

    EVENT = "EVENT"
    GROUP = "GROUP"
    GLOBAL = "GLOBAL"
    DEFAULT = "DEFAULT"


NotificationTypeEnum = Enum(NotificationType, name="notification_type")
NotificationChannelEnum = Enum(NotificationChannel, name="notification_channel")
NotificationScopeEnum = Enum(NotificationScope, name="notification_scope")

# Sugar accepted on PATCH bodies; expanded by the service, never stored.
ALL_TYPES = "ALL"

# Types that accept an EVENT-scoped override: everything an event can send.
# This is the proportionate opt-out - without it the only way to escape one
# talkative event is to silence that notification type for every event.
EVENT_SCOPED_TYPES = frozenset(
    {
        NotificationType.EVENT,
        NotificationType.EVENT_REMINDER,
    }
)

# Types that accept a GROUP-scoped override.
GROUP_SCOPED_TYPES = frozenset(
    {
        NotificationType.CHAT_MESSAGE,
        NotificationType.GROUP_POST,
        NotificationType.EVENT,
        NotificationType.ACCUMULATION,
        NotificationType.PRAYER_RECEIVED,
    }
)

# Transactional types with no user-facing toggle: a user who asked to join a
# group expects to hear the answer.
NON_TOGGLEABLE_TYPES = frozenset(
    {
        NotificationType.GROUP_INVITE,
        NotificationType.GROUP_JOIN_REQUEST,
    }
)

# Types exposed as toggles in v1, in the order clients should render them.
V1_TOGGLEABLE_TYPES = (
    NotificationType.CHAT_MESSAGE,
    NotificationType.GROUP_POST,
    NotificationType.EVENT,
    NotificationType.EVENT_REMINDER,
    NotificationType.ACCUMULATION,
    NotificationType.SERIES,
    NotificationType.PRAYER_RECEIVED,
)

# Event-scoped subset of the above, in render order. Muting one event
# silences both what it announces and what it reminds about.
V1_EVENT_TOGGLEABLE_TYPES = tuple(
    notification_type
    for notification_type in V1_TOGGLEABLE_TYPES
    if notification_type in EVENT_SCOPED_TYPES
)

# Group-scoped subset of the above, in render order.
V1_GROUP_TOGGLEABLE_TYPES = tuple(
    notification_type
    for notification_type in V1_TOGGLEABLE_TYPES
    if notification_type in GROUP_SCOPED_TYPES
)
