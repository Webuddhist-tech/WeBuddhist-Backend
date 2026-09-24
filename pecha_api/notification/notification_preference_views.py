from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette import status

from pecha_api.notification.notification_preference_enums import (
    NotificationChannel,
    NotificationType,
)
from pecha_api.notification.notification_preference_response_models import (
    EventNotificationPreferencesResponse,
    GroupNotificationPreferencesResponse,
    NotificationPreferencesResponse,
    UpdateNotificationPreferencesRequest,
)
from pecha_api.notification.notification_preference_service import (
    delete_event_notification_preferences_service,
    delete_group_notification_preferences_service,
    get_event_notification_preferences_service,
    get_group_notification_preferences_service,
    get_notification_preferences_service,
    update_event_notification_preferences_service,
    update_group_notification_preferences_service,
    update_notification_preferences_service,
)

oauth2_scheme = HTTPBearer()

notification_preference_router = APIRouter(
    prefix="/users/me",
    tags=["Notification Preferences"],
)


@notification_preference_router.get(
    "/notification-preferences",
    status_code=status.HTTP_200_OK,
    response_model=NotificationPreferencesResponse,
)
def get_notification_preferences(
    authentication_credential: Annotated[
        HTTPAuthorizationCredentials, Depends(oauth2_scheme)
    ],
    channel: Annotated[NotificationChannel, Query()] = NotificationChannel.PUSH,
) -> NotificationPreferencesResponse:
    return get_notification_preferences_service(
        token=authentication_credential.credentials,
        channel=channel,
    )


@notification_preference_router.patch(
    "/notification-preferences",
    status_code=status.HTTP_200_OK,
    response_model=NotificationPreferencesResponse,
)
def patch_notification_preferences(
    authentication_credential: Annotated[
        HTTPAuthorizationCredentials, Depends(oauth2_scheme)
    ],
    update_request: UpdateNotificationPreferencesRequest,
    channel: Annotated[NotificationChannel, Query()] = NotificationChannel.PUSH,
) -> NotificationPreferencesResponse:
    return update_notification_preferences_service(
        token=authentication_credential.credentials,
        request=update_request,
        channel=channel,
    )


@notification_preference_router.get(
    "/notification-preferences/groups/{group_id}",
    status_code=status.HTTP_200_OK,
    response_model=GroupNotificationPreferencesResponse,
)
def get_group_notification_preferences(
    group_id: UUID,
    authentication_credential: Annotated[
        HTTPAuthorizationCredentials, Depends(oauth2_scheme)
    ],
    channel: Annotated[NotificationChannel, Query()] = NotificationChannel.PUSH,
) -> GroupNotificationPreferencesResponse:
    return get_group_notification_preferences_service(
        token=authentication_credential.credentials,
        group_id=group_id,
        channel=channel,
    )


@notification_preference_router.patch(
    "/notification-preferences/groups/{group_id}",
    status_code=status.HTTP_200_OK,
    response_model=GroupNotificationPreferencesResponse,
)
def patch_group_notification_preferences(
    group_id: UUID,
    authentication_credential: Annotated[
        HTTPAuthorizationCredentials, Depends(oauth2_scheme)
    ],
    update_request: UpdateNotificationPreferencesRequest,
    channel: Annotated[NotificationChannel, Query()] = NotificationChannel.PUSH,
) -> GroupNotificationPreferencesResponse:
    return update_group_notification_preferences_service(
        token=authentication_credential.credentials,
        group_id=group_id,
        request=update_request,
        channel=channel,
    )


@notification_preference_router.delete(
    "/notification-preferences/groups/{group_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_group_notification_preferences(
    group_id: UUID,
    authentication_credential: Annotated[
        HTTPAuthorizationCredentials, Depends(oauth2_scheme)
    ],
    notification_type: Annotated[Optional[NotificationType], Query()] = None,
    channel: Annotated[NotificationChannel, Query()] = NotificationChannel.PUSH,
) -> None:
    delete_group_notification_preferences_service(
        token=authentication_credential.credentials,
        group_id=group_id,
        notification_type=notification_type,
        channel=channel,
    )


@notification_preference_router.get(
    "/notification-preferences/events/{event_id}",
    status_code=status.HTTP_200_OK,
    response_model=EventNotificationPreferencesResponse,
)
def get_event_notification_preferences(
    event_id: UUID,
    authentication_credential: Annotated[
        HTTPAuthorizationCredentials, Depends(oauth2_scheme)
    ],
    channel: Annotated[NotificationChannel, Query()] = NotificationChannel.PUSH,
) -> EventNotificationPreferencesResponse:
    return get_event_notification_preferences_service(
        token=authentication_credential.credentials,
        event_id=event_id,
        channel=channel,
    )


@notification_preference_router.patch(
    "/notification-preferences/events/{event_id}",
    status_code=status.HTTP_200_OK,
    response_model=EventNotificationPreferencesResponse,
)
def patch_event_notification_preferences(
    event_id: UUID,
    authentication_credential: Annotated[
        HTTPAuthorizationCredentials, Depends(oauth2_scheme)
    ],
    update_request: UpdateNotificationPreferencesRequest,
    channel: Annotated[NotificationChannel, Query()] = NotificationChannel.PUSH,
) -> EventNotificationPreferencesResponse:
    """Mute or un-mute a single event. Send notification_type "ALL" to
    silence everything this event can send without naming each type."""
    return update_event_notification_preferences_service(
        token=authentication_credential.credentials,
        event_id=event_id,
        request=update_request,
        channel=channel,
    )


@notification_preference_router.delete(
    "/notification-preferences/events/{event_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_event_notification_preferences(
    event_id: UUID,
    authentication_credential: Annotated[
        HTTPAuthorizationCredentials, Depends(oauth2_scheme)
    ],
    notification_type: Annotated[Optional[NotificationType], Query()] = None,
    channel: Annotated[NotificationChannel, Query()] = NotificationChannel.PUSH,
) -> None:
    """Drop the event override so the setting falls back to the global one."""
    delete_event_notification_preferences_service(
        token=authentication_credential.credentials,
        event_id=event_id,
        notification_type=notification_type,
        channel=channel,
    )
