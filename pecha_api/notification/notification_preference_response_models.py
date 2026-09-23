from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from pecha_api.notification.notification_preference_enums import (
    ALL_TYPES,
    NotificationChannel,
    NotificationType,
    PreferenceSource,
)


class NotificationPreferenceUpdateDTO(BaseModel):
    """One entry of a sparse PATCH body.

    `enabled` and `muted_until` are only applied when the client actually sent
    them: an absent key leaves the stored value alone, while an explicit null
    `muted_until` lifts a snooze. That distinction is read off
    `model_fields_set`, so a plain `None` default is not enough to tell the two
    apart.
    """

    notification_type: str
    enabled: Optional[bool] = None
    muted_until: Optional[datetime] = None

    @field_validator("notification_type")
    @classmethod
    def _validate_notification_type(cls, value: str) -> str:
        candidate = value.strip().upper()
        if candidate == ALL_TYPES:
            return candidate
        if candidate not in NotificationType.__members__:
            raise ValueError(f"unknown notification_type: {value}")
        return candidate

    @property
    def is_all_types(self) -> bool:
        return self.notification_type == ALL_TYPES

    @property
    def sets_enabled(self) -> bool:
        return "enabled" in self.model_fields_set

    @property
    def sets_muted_until(self) -> bool:
        return "muted_until" in self.model_fields_set


class UpdateNotificationPreferencesRequest(BaseModel):
    preferences: List[NotificationPreferenceUpdateDTO] = Field(min_length=1)


class EffectivePreferenceDTO(BaseModel):
    notification_type: NotificationType
    enabled: bool
    muted_until: Optional[datetime] = None
    source: PreferenceSource


class GroupOverrideSummaryDTO(BaseModel):
    group_id: UUID
    group_title: str
    overridden_types: List[NotificationType]
    muted_until: Optional[datetime] = None


class NotificationPreferencesResponse(BaseModel):
    channel: NotificationChannel
    preferences: List[EffectivePreferenceDTO]
    group_overrides: List[GroupOverrideSummaryDTO]


class GroupNotificationPreferencesResponse(BaseModel):
    group_id: UUID
    channel: NotificationChannel
    preferences: List[EffectivePreferenceDTO]


class EventNotificationPreferencesResponse(BaseModel):
    event_id: UUID
    channel: NotificationChannel
    preferences: List[EffectivePreferenceDTO]
