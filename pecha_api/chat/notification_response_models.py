from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ChatPushDeviceTargetDTO(BaseModel):
    id: UUID
    token: str
    platform: str


class ChatNotificationRecipientDTO(BaseModel):
    user_id: UUID
    push_devices: List[ChatPushDeviceTargetDTO]


class ChatNotificationTargetsResponse(BaseModel):
    message_id: UUID
    room_id: UUID
    sender_id: UUID
    chat_kind: str
    group_id: Optional[UUID] = None
    title: str
    body: str
    recipients: List[ChatNotificationRecipientDTO]
    skip: int
    limit: int
    total: int
    has_more: bool


class PrayerNotificationTargetsResponse(BaseModel):
    """Targets and copy for "someone prayed for your request".

    Recipients is the requester alone (never the person who prayed), so the
    pagination fields are there only to match the chat targets contract the
    worker already speaks."""
    prayer_id: UUID
    message_id: UUID
    room_id: UUID
    chat_kind: str
    group_id: Optional[UUID] = None
    event_id: Optional[UUID] = None
    requester_id: UUID
    prayer_count: int
    title: str
    body: str
    recipients: List[ChatNotificationRecipientDTO]
    skip: int
    limit: int
    total: int
    has_more: bool


class DeactivatePushDeviceRequest(BaseModel):
    push_device_id: UUID = Field(..., description="Push device token record ID to deactivate")


class DeactivatePushDeviceResponse(BaseModel):
    push_device_id: UUID
    deactivated: bool
