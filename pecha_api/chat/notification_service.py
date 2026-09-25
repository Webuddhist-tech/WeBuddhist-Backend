from datetime import datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session
from starlette import status

from pecha_api.chat.enums import ChatMessageType, ChatRoomKind
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
    count_suppressed_prayer_requests,
    get_message_by_id_any_room,
    get_prayer_by_id,
    last_dispatched_prayer_request,
)
from pecha_api.chat.service import (
    _generate_presigned_url,
    _message_type_value,
    room_kind,
)
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


def _count_held_prayer_requests(
    *,
    db: Session,
    room_id: UUID,
    message_id: UUID,
    created_at: datetime,
) -> int:
    """How many prayer requests the interval held since the last push that went out.

    `exclude_message_id` matters on both calls. By the time the worker asks for
    targets the backend has usually already stamped this message with its real
    SQS id, so without the exclusion the "last sent push" would be this very
    message, `since` would be roughly now, and the count would always be zero.

    The window closes at this request's own `created_at`, so a request
    suppressed while the worker is building this push belongs to the next one
    rather than being counted here and again there.
    """
    last_sent = last_dispatched_prayer_request(
        db=db,
        room_id=room_id,
        exclude_message_id=message_id,
    )
    return count_suppressed_prayer_requests(
        db=db,
        room_id=room_id,
        since=last_sent.created_at if last_sent else None,
        until=created_at,
        exclude_message_id=message_id,
    )


def _held_prayer_request_suffix(held_count: int) -> str:
    """What the interval skipped, as words on the end of the body.

    The held requests are not listed and their senders are not named: the room
    shows each one in full. This is only how many notifications did not fire.
    """
    if held_count < 1:
        return ""
    if held_count == 1:
        return " · +1 other prayer request"
    return f" · +{held_count} other prayer requests"


def _build_notification_copy(
    *,
    chat_kind: str,
    room_name: str,
    sender_name: str,
    message_body: str,
    message_type: str = ChatMessageType.TEXT.value,
    has_image: bool = False,
    held_count: int = 0,
) -> tuple[str, str]:
    preview = _preview_body(
        message_body,
        max(get_int("CHAT_NOTIFICATION_PREVIEW_MAX_LENGTH"), 1),
    )
    if message_type == ChatMessageType.PRAYER.value:
        # A prayer request leads with the person asking and what they asked
        # for. The room name buys nothing beside that - as long as the room's
        # image is there to say which sangha this came from. Rooms without an
        # image, and images that could not be signed, keep the name instead:
        # a prayer from an unidentified group is a stranger's prayer.
        title = f"{sender_name} is requesting a prayer 🙏"
        body = preview if has_image else f"{room_name}: {preview}"
        # After the preview was truncated, so the cap applies to the request
        # text and never to the count. A long request is what gets the ellipsis.
        return title, f"{body}{_held_prayer_request_suffix(held_count)}"
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
        message_type = _message_type_value(message)
        sender_name = get_sender_display_name(db=db, sender_id=message.sender_id)
        # Only a prayer request carries the room's image: it replaces the room
        # name the copy drops. Ordinary chat keeps its unchanged look. Resolved
        # before the copy is built, because whether the image is actually there
        # decides whether the copy can afford to drop the name.
        image_url = (
            _generate_presigned_url(room.img_url)
            if message_type == ChatMessageType.PRAYER.value
            else None
        )
        # Counted at read time, so the number matches the rows that exist when
        # the worker asks for targets rather than when the event was enqueued.
        held_count = (
            _count_held_prayer_requests(
                db=db,
                room_id=room.id,
                message_id=message.id,
                created_at=message.created_at,
            )
            if message_type == ChatMessageType.PRAYER.value
            else 0
        )
        title, body = _build_notification_copy(
            chat_kind=chat_kind,
            room_name=room.name,
            sender_name=sender_name,
            message_body=message.body,
            message_type=message_type,
            held_count=held_count,
            # Empty string too: the signer returns one for an unusable key.
            has_image=bool(image_url),
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
            message_type=message_type,
            image_url=image_url,
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
