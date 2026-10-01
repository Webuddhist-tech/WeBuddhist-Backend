import enum

from sqlalchemy import Enum


class GroupPostStatus(enum.Enum):
    PUBLISHED = "PUBLISHED"
    HIDDEN = "HIDDEN"


GroupPostStatusEnum = Enum(
    GroupPostStatus,
    name="group_post_status",
)


class GroupPostMediaType(enum.Enum):
    IMAGE = "IMAGE"
    VIDEO = "VIDEO"
    AUDIO = "AUDIO"


GroupPostMediaTypeEnum = Enum(
    GroupPostMediaType,
    name="group_post_media_type",
)


class GroupPostReportTargetType(enum.Enum):
    """What a report points at. A COMMENT report still carries the post it
    belongs to, so a group's queue can be built from post_id alone."""

    POST = "POST"
    COMMENT = "COMMENT"


class GroupPostReportReason(enum.Enum):
    """Mirrors ChatMessageReportReason so a group's combined moderation queue
    reads one vocabulary across chat and posts."""

    SPAM = "SPAM"
    HARASSMENT = "HARASSMENT"
    HATE_SPEECH = "HATE_SPEECH"
    INAPPROPRIATE = "INAPPROPRIATE"
    INAPPROPRIATE_LANGUAGE = "INAPPROPRIATE_LANGUAGE"
    OTHER = "OTHER"
