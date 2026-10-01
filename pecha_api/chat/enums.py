import enum

from sqlalchemy import Enum


class ChatRoomMemberRole(enum.Enum):
    CREATOR = "CREATOR"
    MEMBER = "MEMBER"


ChatRoomMemberRoleEnum = Enum(
    ChatRoomMemberRole,
    name="chat_room_member_role",
)


class ChatRoomKind(str, enum.Enum):
    """Which of the three `ck_chat_rooms_kind_shape` arms a room satisfies.

    Derived from the room's columns rather than stored: `group_id` for a
    group's room, `event_id` for an event's room, the sender/receiver pair
    for a DM."""

    GROUP = "GROUP"
    EVENT = "EVENT"
    PRIVATE = "PRIVATE"


class ChatMessageType(enum.Enum):
    """What a message is. TEXT is ordinary chat; PRAYER marks the message as a
    prayer request other members can pray for."""

    TEXT = "TEXT"
    PRAYER = "PRAYER"


ChatMessageTypeEnum = Enum(
    ChatMessageType,
    name="chat_message_type",
)


class ChatMessageReportReason(enum.Enum):
    SPAM = "SPAM"
    HARASSMENT = "HARASSMENT"
    HATE_SPEECH = "HATE_SPEECH"
    INAPPROPRIATE = "INAPPROPRIATE"
    INAPPROPRIATE_LANGUAGE = "INAPPROPRIATE_LANGUAGE"
    OTHER = "OTHER"


class ChatMessageReportSource(enum.Enum):
    MANUAL = "MANUAL"
    AUTOMATIC = "AUTOMATIC"
