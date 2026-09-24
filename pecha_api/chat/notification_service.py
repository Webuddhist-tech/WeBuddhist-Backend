from uuid import UUID

from fastapi import HTTPException
from starlette import status

from pecha_api.chat.enums import ChatRoomKind
from pecha_api.chat.notification_repository import (
    deactivate_push_device_token_by_id,
    filter_users_by_notification_preference,
    get_active_push_devices_by_user_ids,
    get_sender_display_name,
    list_event_chat_recipient_user_ids,
    list_group_chat_recipient_user_ids,
    list_private_chat_recipient_user_ids,
    normalize_platform,
)
from pecha_api.notification.notification_preference_enums import NotificationType
from pecha_api.chat.notification_response_models import (
    ChatNotificationRecipientDTO,
    ChatNotificationTargetsResponse,
    ChatPushDeviceTargetDTO,
    DeactivatePushDeviceResponse,
    PrayerNotificationTargetsResponse,
)
from pecha_api.chat.repository import (
    count_message_prayers,
    get_message_by_id_any_room,
    get_prayer_by_id,
)
from pecha_api.chat.service import room_kind
from pecha_api.events.event_repository import get_event_by_id
from pecha_api.config import get_int
from pecha_api.db.database import SessionLocal
from pecha_api.plans.response_message import NOT_FOUND


def _owning_group_id(*, db, room):
    """The group whose notification preferences govern this room. An event room
    carries no group_id of its own; it inherits the event's."""
    if room.group_id is not None:
        return room.group_id
    if getattr(room, "event_id", None) is None:
        return None
    event = get_event_by_id(db, room.event_id)
    return event.group_id if event else None


def _preview_body(body: str, max_length: int) -> str:
    text = " ".join(body.split())
    if len(text) <= max_length:
        return text
    return text[: max(max_length - 1, 1)].rstrip() + "…"


def _build_notification_copy(
    *,
    chat_kind: str,
    room_name: str,
    sender_name: str,
    message_body: str,
) -> tuple[str, str]:
    preview = _preview_body(
        message_body,
        max(get_int("CHAT_NOTIFICATION_PREVIEW_MAX_LENGTH"), 1),
    )
    if chat_kind == "PRIVATE":
        return sender_name, preview
    return room_name, f"{sender_name}: {preview}"


def get_chat_notification_targets(
    *,
    message_id: UUID,
    skip: int = 0,
    limit: int = 100,
) -> ChatNotificationTargetsResponse:
    if skip < 0:
        skip = 0
    if limit < 1:
        limit = 1
    if limit > 500:
        limit = 500

    with SessionLocal() as db:
        message = get_message_by_id_any_room(db=db, message_id=message_id)
        if not message or not message.room:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)

        room = message.room
        chat_kind = room_kind(room)
        sender_name = get_sender_display_name(db=db, sender_id=message.sender_id)
        title, body = _build_notification_copy(
            chat_kind=chat_kind,
            room_name=room.name,
            sender_name=sender_name,
            message_body=message.body,
        )

        if chat_kind == ChatRoomKind.PRIVATE.value:
            all_recipient_ids = list_private_chat_recipient_user_ids(
                room=room,
                sender_id=message.sender_id,
            )
            # Private chat has no group scope, so only GLOBAL rows can apply.
            all_recipient_ids = filter_users_by_notification_preference(
                db=db,
                user_ids=all_recipient_ids,
                notification_type=NotificationType.CHAT_MESSAGE,
            )
            total = len(all_recipient_ids)
            recipient_ids = all_recipient_ids[skip : skip + limit]
        elif chat_kind == ChatRoomKind.EVENT.value:
            # An event room's audience is its own membership, not the whole
            # group; preferences still scope to the group that owns the event.
            recipient_ids, total = list_event_chat_recipient_user_ids(
                db=db,
                room_id=room.id,
                sender_id=message.sender_id,
                group_id=_owning_group_id(db=db, room=room),
                skip=skip,
                limit=limit,
                notification_type=NotificationType.CHAT_MESSAGE,
            )
        else:
            recipient_ids, total = list_group_chat_recipient_user_ids(
                db=db,
                group_id=room.group_id,
                sender_id=message.sender_id,
                skip=skip,
                limit=limit,
                notification_type=NotificationType.CHAT_MESSAGE,
            )

        devices_by_user = get_active_push_devices_by_user_ids(db=db, user_ids=recipient_ids)
        recipients: list[ChatNotificationRecipientDTO] = []
        for user_id in recipient_ids:
            devices = devices_by_user.get(user_id) or []
            if not devices:
                continue
            recipients.append(
                ChatNotificationRecipientDTO(
                    user_id=user_id,
                    push_devices=[
                        ChatPushDeviceTargetDTO(
                            id=device.id,
                            token=device.token,
                            platform=normalize_platform(device.platform),
                        )
                        for device in devices
                    ],
                )
            )

        return ChatNotificationTargetsResponse(
            message_id=message.id,
            room_id=room.id,
            sender_id=message.sender_id,
            chat_kind=chat_kind,
            group_id=room.group_id,
            title=title,
            body=body,
            recipients=recipients,
            skip=skip,
            limit=limit,
            total=total,
            has_more=(skip + limit) < total,
        )


def deactivate_push_device_service(*, push_device_id: UUID) -> DeactivatePushDeviceResponse:
    with SessionLocal() as db:
        device = deactivate_push_device_token_by_id(db=db, push_device_id=push_device_id)
        if not device:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
        return DeactivatePushDeviceResponse(
            push_device_id=device.id,
            deactivated=not device.is_active,
        )


def _build_prayer_notification_copy(
    *,
    room_name: str,
    prayer_count: int,
    latest_prayer_name: str,
) -> tuple[str, str]:
    """Copy reads from the live count, not from one prayer, because prayers
    inside the coalesce window are deliberately folded into a single push."""
    if prayer_count <= 1:
        return room_name, f"{latest_prayer_name} prayed for your request"
    return room_name, f"{prayer_count} people are praying for your request"


def get_prayer_notification_targets(
    *,
    prayer_id: UUID,
    skip: int = 0,
    limit: int = 100,
) -> PrayerNotificationTargetsResponse:
    if skip < 0:
        skip = 0
    if limit < 1:
        limit = 1
    if limit > 500:
        limit = 500

    with SessionLocal() as db:
        prayer = get_prayer_by_id(db=db, prayer_id=prayer_id)
        if not prayer:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)

        message = get_message_by_id_any_room(db=db, message_id=prayer.message_id)
        if not message or not message.room:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)

        room = message.room
        chat_kind = room_kind(room)
        group_id = _owning_group_id(db=db, room=room)

        prayer_count = count_message_prayers(db=db, message_id=message.id)
        title, body = _build_prayer_notification_copy(
            room_name=room.name,
            prayer_count=prayer_count,
            latest_prayer_name=get_sender_display_name(db=db, sender_id=prayer.user_id),
        )

        # The requester alone, and never for their own prayer.
        recipient_ids = (
            [] if message.sender_id == prayer.user_id else [message.sender_id]
        )
        recipient_ids = filter_users_by_notification_preference(
            db=db,
            user_ids=recipient_ids,
            notification_type=NotificationType.PRAYER_RECEIVED,
            scope_id=group_id,
        )
        total = len(recipient_ids)
        recipient_ids = recipient_ids[skip : skip + limit]

        devices_by_user = get_active_push_devices_by_user_ids(db=db, user_ids=recipient_ids)
        recipients: list[ChatNotificationRecipientDTO] = []
        for user_id in recipient_ids:
            devices = devices_by_user.get(user_id) or []
            if not devices:
                continue
            recipients.append(
                ChatNotificationRecipientDTO(
                    user_id=user_id,
                    push_devices=[
                        ChatPushDeviceTargetDTO(
                            id=device.id,
                            token=device.token,
                            platform=normalize_platform(device.platform),
                        )
                        for device in devices
                    ],
                )
            )

        return PrayerNotificationTargetsResponse(
            prayer_id=prayer.id,
            message_id=message.id,
            room_id=room.id,
            chat_kind=chat_kind,
            group_id=group_id,
            event_id=room.event_id,
            requester_id=message.sender_id,
            prayer_count=prayer_count,
            title=title,
            body=body,
            recipients=recipients,
            skip=skip,
            limit=limit,
            total=total,
            has_more=(skip + limit) < total,
        )
