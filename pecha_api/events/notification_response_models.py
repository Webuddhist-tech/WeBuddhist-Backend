from enum import Enum
from typing import List
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class EventPushDeviceTargetDTO(BaseModel):
    id: UUID
    token: str
    platform: str


class EventNotificationRecipientDTO(BaseModel):
    user_id: UUID
    push_devices: List[EventPushDeviceTargetDTO]


class EventNotificationTargetsResponse(BaseModel):
    event_id: UUID
    group_id: UUID
    author_id: UUID
    title: str
    body: str
    recipients: List[EventNotificationRecipientDTO]
    skip: int
    limit: int
    total: int
    has_more: bool


class EventReminderTargetsResponse(BaseModel):
    event_id: UUID
    reminder_type: str
    title: str
    body: str
    recipients: List[EventNotificationRecipientDTO]
    skip: int
    limit: int
    total: int
    has_more: bool


class EventAnnouncementAudience(str, Enum):
    """Who an organizer-written notification goes to.

    Both cases are real: "bring a cushion today" belongs to the people
    attending, while "a new session has been added" belongs to the group.
    """

    PARTICIPANTS = "participants"
    GROUP = "group"


class SendEventAnnouncementRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    body: str = Field(..., min_length=1, max_length=500)
    audience: EventAnnouncementAudience = EventAnnouncementAudience.PARTICIPANTS

    @field_validator("title", "body")
    @classmethod
    def not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned


class SendEventAnnouncementResponse(BaseModel):
    event_id: UUID
    announcement_id: UUID
    audience: EventAnnouncementAudience
    sqs_message_id: str


class EventAnnouncementTargetsResponse(BaseModel):
    event_id: UUID
    audience: EventAnnouncementAudience
    recipients: List[EventNotificationRecipientDTO]
    skip: int
    limit: int
    total: int
    has_more: bool
