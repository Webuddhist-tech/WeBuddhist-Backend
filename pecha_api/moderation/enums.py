import enum


class GroupReportKind(str, enum.Enum):
    """Which queue a report came from.

    Chat reports and post/comment reports live in separate tables; this is the
    discriminator the combined group queue filters and labels them by.
    """

    CHAT_MESSAGE = "CHAT_MESSAGE"
    POST = "POST"
    COMMENT = "COMMENT"
