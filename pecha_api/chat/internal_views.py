from uuid import UUID

from fastapi import APIRouter, Depends, Query
from starlette import status

from pecha_api.chat.notification_response_models import (
    ChatNotificationTargetsResponse,
    DeactivatePushDeviceRequest,
    DeactivatePushDeviceResponse,
    PrayerNotificationTargetsResponse,
)
from pecha_api.chat.notification_service import (
    deactivate_push_device_service,
    get_chat_notification_targets,
    get_prayer_notification_targets,
)
from pecha_api.routines.routine_notifications.dependencies import verify_dispatch_token

internal_chat_notifications_router = APIRouter(
    prefix="/internal",
    tags=["Internal"],
)


@internal_chat_notifications_router.get(
    "/chat-notification-targets/{message_id}",
    status_code=status.HTTP_200_OK,
)
def chat_notification_targets(
    message_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    _: None = Depends(verify_dispatch_token),
) -> ChatNotificationTargetsResponse:
    return get_chat_notification_targets(message_id=message_id, skip=skip, limit=limit)


@internal_chat_notifications_router.get(
    "/prayer-notification-targets/{prayer_id}",
    status_code=status.HTTP_200_OK,
)
def prayer_notification_targets(
    prayer_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    _: None = Depends(verify_dispatch_token),
) -> PrayerNotificationTargetsResponse:
    return get_prayer_notification_targets(prayer_id=prayer_id, skip=skip, limit=limit)


@internal_chat_notifications_router.post(
    "/push-devices/deactivate",
    status_code=status.HTTP_200_OK,
)
def deactivate_push_device(
    payload: DeactivatePushDeviceRequest,
    _: None = Depends(verify_dispatch_token),
) -> DeactivatePushDeviceResponse:
    return deactivate_push_device_service(push_device_id=payload.push_device_id)
