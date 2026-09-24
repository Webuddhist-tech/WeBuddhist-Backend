from uuid import UUID

from fastapi import HTTPException
from starlette import status

from pecha_api.chat.notification_repository import (
    get_active_push_devices_by_user_ids,
    list_group_chat_recipient_user_ids,
    normalize_platform,
)
from pecha_api.config import get_int
from pecha_api.db.database import SessionLocal
from pecha_api.events.event_metadata_model import EventMetadata
from pecha_api.events.event_repository import get_event_by_id
from pecha_api.events.notification_response_models import (
    EventNotificationRecipientDTO,
    EventNotificationTargetsResponse,
    EventPushDeviceTargetDTO,
)
from pecha_api.group_posts.notification_repository import (
    get_group_notification_title,
    get_user_by_email,
)
from pecha_api.notification.notification_preference_enums import NotificationType
from pecha_api.plans.response_message import NOT_FOUND


def _preview_body(body: str, max_length: int) -> str:
    text = " ".join(body.split())
    if len(text) <= max_length:
        return text
    return text[: max(max_length - 1, 1)].rstrip() + "…"


def _get_event_name(db, event_id: UUID) -> str:
    entries = (
        db.query(EventMetadata)
        .filter(EventMetadata.event_id == event_id)
        .all()
    )
    for entry in entries:
        language = entry.language
        lang_value = language.value if hasattr(language, "value") else str(language)
        if lang_value.upper() == "EN":
            return entry.name
    if entries:
        return entries[0].name
    return "New event"


def _build_notification_copy(*, event_name: str) -> str:
    return _preview_body(
        event_name,
        max(get_int("EVENT_NOTIFICATION_PREVIEW_MAX_LENGTH"), 1),
    )


def get_event_notification_targets(
    *,
    event_id: UUID,
    skip: int = 0,
    limit: int = 100,
) -> EventNotificationTargetsResponse:
    if skip < 0:
        skip = 0
    if limit < 1:
        limit = 1
    if limit > 500:
        limit = 500

    with SessionLocal() as db:
        event = get_event_by_id(db, event_id)
        if not event:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)

        author = get_user_by_email(db, event.created_by)
        if not author:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)

        title = get_group_notification_title(db, event.group_id)
        event_name = _get_event_name(db, event.id)
        body = _build_notification_copy(event_name=event_name)

        recipient_ids, total = list_group_chat_recipient_user_ids(
            db=db,
            group_id=event.group_id,
            sender_id=author.id,
            skip=skip,
            limit=limit,
            notification_type=NotificationType.EVENT,
            # Group-wide audience, but someone who muted this one event is
            # still entitled not to hear about it.
            event_id=event.id,
        )

        devices_by_user = get_active_push_devices_by_user_ids(db=db, user_ids=recipient_ids)
        recipients: list[EventNotificationRecipientDTO] = []
        for user_id in recipient_ids:
            devices = devices_by_user.get(user_id) or []
            if not devices:
                continue
            recipients.append(
                EventNotificationRecipientDTO(
                    user_id=user_id,
                    push_devices=[
                        EventPushDeviceTargetDTO(
                            id=device.id,
                            token=device.token,
                            platform=normalize_platform(device.platform),
                        )
                        for device in devices
                    ],
                )
            )

        return EventNotificationTargetsResponse(
            event_id=event.id,
            group_id=event.group_id,
            author_id=author.id,
            title=title,
            body=body,
            recipients=recipients,
            skip=skip,
            limit=limit,
            total=total,
            has_more=(skip + limit) < total,
        )
