from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, field_validator, model_serializer

from pecha_api.chat.enums import ChatMessageReportReason, ChatMessageType

MAX_PRAYER_BATCH_SIZE = 50


class ChatMessageParentDTO(BaseModel):
    """Compact DTO for the message a reply points to (the quoted message).

    A deleted parent still includes id, sender, and deleted_at so replies can
    show who was quoted; body is empty and content is not sent.
    """
    id: UUID
    sender_id: UUID
    sender_email: str
    sender_name: str
    sender_avatar_url: Optional[str] = None
    body: str
    created_at: str
    deleted_at: Optional[str] = None

    @model_serializer(mode="wrap")
    def _serialize(self, handler):
        """Omit deleted_at entirely for non-deleted parents instead of sending null."""
        data = handler(self)
        if data.get("deleted_at") is None:
            data.pop("deleted_at", None)
        return data


class ChatMessageReactionUserDTO(BaseModel):
    """Identity of one reactor, for showing who reacted."""
    user_id: UUID
    email: Optional[str] = None
    name: Optional[str] = None


class ChatMessageReactionDTO(BaseModel):
    """Aggregated reactions of one emoji on a message.

    user_ids lets a client receiving a shared broadcast (where reacted_by_me
    cannot be viewer-specific) work out its own reacted state; users carries
    the same people with display identity for who-reacted UI."""
    emoji: str
    count: int
    reacted_by_me: bool = False
    user_ids: List[UUID] = []
    users: List[ChatMessageReactionUserDTO] = []


class ChatMessagePrayerUserDTO(BaseModel):
    """Identity of one person who prayed, for showing who prayed."""
    user_id: UUID
    email: Optional[str] = None
    name: Optional[str] = None
    avatar_url: Optional[str] = None


class ChatMessageDTO(BaseModel):
    """DTO for a single chat message.

    The prayer fields describe a PRAYER message (a prayer request) and are
    omitted entirely on a TEXT message."""
    id: UUID
    room_id: UUID
    sender_id: UUID
    sender_email: str
    sender_name: str
    sender_avatar_url: Optional[str] = None
    body: str
    message_type: str = ChatMessageType.TEXT.value
    created_at: str
    deleted_at: Optional[str] = None
    parent: Optional[ChatMessageParentDTO] = None
    reactions: List[ChatMessageReactionDTO] = []
    prayer_count: int = 0
    prayed_by_me: bool = False
    recent_prayers: List[ChatMessagePrayerUserDTO] = []

    @model_serializer(mode="wrap")
    def _serialize(self, handler):
        """Omit deleted_at entirely for non-deleted messages instead of sending
        null, and the prayer fields entirely for messages that are not prayer
        requests."""
        data = handler(self)
        if data.get("deleted_at") is None:
            data.pop("deleted_at", None)
        if data.get("message_type") != ChatMessageType.PRAYER.value:
            for field in ("prayer_count", "prayed_by_me", "recent_prayers"):
                data.pop(field, None)
        return data


class ChatMessagesResponse(BaseModel):
    """Response for list messages endpoint."""
    messages: List[ChatMessageDTO]
    skip: int
    limit: int
    total: int


class ChatRoomMemberDTO(BaseModel):
    """DTO for a chat room member."""
    user_id: UUID
    email: str
    firstname: str
    lastname: Optional[str] = None
    role: str
    joined_at: str


class ChatRoomMembersResponse(BaseModel):
    """Response for list members endpoint."""
    members: List[ChatRoomMemberDTO]
    skip: int
    limit: int
    total: int


class ChatRoomDTO(BaseModel):
    """DTO for a room, presigned picture, and inbox summary fields."""
    id: UUID
    group_id: Optional[UUID] = None
    event_id: Optional[UUID] = None
    sender_id: Optional[UUID] = None
    receiver_id: Optional[UUID] = None
    kind: str
    name: str
    img_url: Optional[str] = None
    created_by: UUID
    member_count: int
    updated_at: str
    last_message: Optional[ChatMessageDTO] = None
    unread_count: int = 0
    # PRIVATE rooms only: the other participant (not the caller), so a client
    # can reconnect/DM them again without needing to already know their id.
    other_user_id: Optional[UUID] = None
    other_user_email: Optional[str] = None
    other_user_name: Optional[str] = None


class ChatRoomsResponse(BaseModel):
    """Response for list-my-rooms (inbox) endpoint."""
    rooms: List[ChatRoomDTO]
    skip: int
    limit: int
    total: int


class ChatPersonDTO(BaseModel):
    """DTO for a person the caller could start/continue a DM with."""
    user_id: UUID
    email: str
    firstname: str
    lastname: Optional[str] = None
    avatar_url: Optional[str] = None


class ChatPeopleResponse(BaseModel):
    """Response for the group-people (DM candidates) endpoint."""
    people: List[ChatPersonDTO]
    skip: int
    limit: int
    total: int


class AdminChatReportUserDTO(BaseModel):
    """Identity of a user involved in a moderation report."""
    user_id: UUID
    email: Optional[str] = None
    firstname: Optional[str] = None
    lastname: Optional[str] = None


class AdminChatMessageReportDTO(BaseModel):
    """One moderation report, for the CMS admin reports screen.

    reporter is None for AUTOMATIC (system-generated) reports; message_text
    carries the reported content even when the message itself was never
    stored (profanity rejections) or has been deleted since."""
    id: UUID
    source: str
    reason: str
    description: Optional[str] = None
    message_id: Optional[UUID] = None
    message_text: Optional[str] = None
    # Absent when the message was never stored (a profanity rejection).
    message_type: Optional[str] = None
    room_id: Optional[UUID] = None
    room_name: Optional[str] = None
    room_kind: Optional[str] = None
    reporter: Optional[AdminChatReportUserDTO] = None
    reported_user: Optional[AdminChatReportUserDTO] = None
    created_at: str
    resolved_at: Optional[str] = None


class AdminChatMessageReportsResponse(BaseModel):
    """Response for the CMS admin list-reports endpoint."""
    reports: List[AdminChatMessageReportDTO]
    skip: int
    limit: int
    total: int


class SendChatMessageRequest(BaseModel):
    """Request to send a message to a room (group, event or DM). Pass
    parent_message_id to send it as a reply to that message, and
    message_type=PRAYER to post it as a prayer request."""
    body: str
    message_type: ChatMessageType = ChatMessageType.TEXT
    parent_message_id: Optional[UUID] = None

    @field_validator("body")
    @classmethod
    def validate_body(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Message body must not be empty")
        if len(value) > 4000:
            raise ValueError("Message body must not exceed 4000 characters")
        return value


class PrayForMessagesRequest(BaseModel):
    """Request to pray for one or several selected prayer requests at once.

    The multi-select action: the client sends the ids the user ticked."""
    message_ids: List[UUID]

    @field_validator("message_ids")
    @classmethod
    def validate_message_ids(cls, value: List[UUID]) -> List[UUID]:
        if not value:
            raise ValueError("message_ids must not be empty")
        # Preserve the client's order while dropping repeats, so a duplicate id
        # cannot inflate the response with two entries for one message.
        deduped = list(dict.fromkeys(value))
        if len(deduped) > MAX_PRAYER_BATCH_SIZE:
            raise ValueError(
                f"message_ids must not exceed {MAX_PRAYER_BATCH_SIZE} messages"
            )
        return deduped


class ChatMessagePrayerStateDTO(BaseModel):
    """One prayer request's state after a batch pray. `created` is False when
    the caller had already prayed for it."""
    message_id: UUID
    prayer_count: int
    prayed_by_me: bool
    created: bool


class PrayerBatchResponse(BaseModel):
    """Response for the batch pray endpoint, one entry per requested message."""
    prayers: List[ChatMessagePrayerStateDTO]


class ChatMessagePrayerDTO(BaseModel):
    """One person who prayed for a request, and when."""
    user_id: UUID
    email: Optional[str] = None
    name: Optional[str] = None
    avatar_url: Optional[str] = None
    created_at: str


class ChatMessagePrayersResponse(BaseModel):
    """Response for the who-prayed endpoint."""
    message_id: UUID
    prayers: List[ChatMessagePrayerDTO]
    skip: int
    limit: int
    total: int


class AddChatMessageReactionRequest(BaseModel):
    """Request to add an emoji reaction to a message."""
    emoji: str

    @field_validator("emoji")
    @classmethod
    def validate_emoji(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("emoji must not be empty")
        if len(value) > 16:
            raise ValueError("emoji must not exceed 16 characters")
        return value


class ReportChatMessageRequest(BaseModel):
    """Request to report a message for moderation."""
    reason: ChatMessageReportReason
    description: Optional[str] = None

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        value = value.strip()
        if not value:
            return None
        if len(value) > 1000:
            raise ValueError("description must not exceed 1000 characters")
        return value


class UpdateChatRoomRequest(BaseModel):
    """Request to update room name / picture."""
    name: Optional[str] = None
    img_url: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("name must not be empty")
        if len(value) > 255:
            raise ValueError("name must not exceed 255 characters")
        return value


class AddChatRoomMembersRequest(BaseModel):
    """Request to add members to a group chat room."""
    user_ids: List[UUID]

    @field_validator("user_ids")
    @classmethod
    def validate_user_ids(cls, value: List[UUID]) -> List[UUID]:
        if not value:
            raise ValueError("user_ids must not be empty")
        return value
