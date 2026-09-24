from uuid import UUID

from fastapi import HTTPException
from starlette import status

from pecha_api.chat.notification_repository import (
    get_active_push_devices_by_user_ids,
    list_group_chat_recipient_user_ids,
    normalize_platform,
)
from pecha_api.notification.notification_preference_enums import NotificationType
from pecha_api.config import get_int
from pecha_api.db.database import SessionLocal
from pecha_api.group_posts.enums import GroupPostStatus
from pecha_api.group_posts.notification_repository import (
    get_group_notification_title,
    get_user_by_email,
)
from pecha_api.group_posts.notification_response_models import (
    GroupPostNotificationRecipientDTO,
    GroupPostNotificationTargetsResponse,
    GroupPostPushDeviceTargetDTO,
)
from pecha_api.group_posts.repository import get_post_by_id_only
from pecha_api.plans.response_message import NOT_FOUND


def _preview_body(body: str, max_length: int) -> str:
    text = " ".join(body.split())
    if len(text) <= max_length:
        return text
    return text[: max(max_length - 1, 1)].rstrip() + "…"


def _build_notification_copy(*, caption: str | None) -> str:
    if not caption or not caption.strip():
        return "New post"
    return _preview_body(
        caption,
        max(get_int("GROUP_POST_NOTIFICATION_PREVIEW_MAX_LENGTH"), 1),
    )


def get_group_post_notification_targets(
    *,
    post_id: UUID,
    skip: int = 0,
    limit: int = 100,
) -> GroupPostNotificationTargetsResponse:
    if skip < 0:
        skip = 0
    if limit < 1:
        limit = 1
    if limit > 500:
        limit = 500

    with SessionLocal() as db:
        post = get_post_by_id_only(db=db, post_id=post_id)
        if not post:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)

        author = get_user_by_email(db, post.created_by)
        if not author:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)

        if post.status != GroupPostStatus.PUBLISHED:
            return GroupPostNotificationTargetsResponse(
                post_id=post.id,
                group_id=post.group_id,
                author_id=author.id,
                title="",
                body="",
                recipients=[],
                skip=skip,
                limit=limit,
                total=0,
                has_more=False,
            )

        title = get_group_notification_title(db, post.group_id)
        body = _build_notification_copy(caption=post.caption)

        recipient_ids, total = list_group_chat_recipient_user_ids(
            db=db,
            group_id=post.group_id,
            sender_id=author.id,
            skip=skip,
            limit=limit,
            notification_type=NotificationType.GROUP_POST,
        )

        devices_by_user = get_active_push_devices_by_user_ids(db=db, user_ids=recipient_ids)
        recipients: list[GroupPostNotificationRecipientDTO] = []
        for user_id in recipient_ids:
            devices = devices_by_user.get(user_id) or []
            if not devices:
                continue
            recipients.append(
                GroupPostNotificationRecipientDTO(
                    user_id=user_id,
                    push_devices=[
                        GroupPostPushDeviceTargetDTO(
                            id=device.id,
                            token=device.token,
                            platform=normalize_platform(device.platform),
                        )
                        for device in devices
                    ],
                )
            )

        return GroupPostNotificationTargetsResponse(
            post_id=post.id,
            group_id=post.group_id,
            author_id=author.id,
            title=title,
            body=body,
            recipients=recipients,
            skip=skip,
            limit=limit,
            total=total,
            has_more=(skip + limit) < total,
        )
