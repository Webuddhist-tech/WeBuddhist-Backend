"""Notifications an organizer sends by hand from the CMS.

Distinct from the two automatic pushes an event already has - the one when it
is created, and the reminders before it starts. This is the organizer saying
something unplanned: a venue change, a cancellation, what to bring.

Nothing is persisted. The send is synchronous up to the queue, so the CMS
learns immediately whether it was accepted, and there is no dispatch row to
reconcile afterwards. The cost is that there is no history of what was sent -
worth revisiting if organizers start needing an outbox.
"""
import logging
from typing import List, Optional, Tuple
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session
from starlette import status

from pecha_api.chat.notification_repository import (
    get_active_push_devices_by_user_ids,
    list_group_chat_recipient_user_ids,
    normalize_platform,
)
from pecha_api.db.database import SessionLocal
from pecha_api.notification.notification_preference_enums import NotificationType
from pecha_api.plans.authors.plan_authors_service import validate_cms_author_details
from pecha_api.plans.response_message import NOT_FOUND
from pecha_api.users.users_repository import get_user_by_email

from .event_model import Event
from .event_participant_repository import get_event_participants_paginated
from .event_repository import get_event_by_id
from .notification_response_models import (
    EventAnnouncementAudience,
    EventAnnouncementTargetsResponse,
    EventNotificationRecipientDTO,
    EventPushDeviceTargetDTO,
    SendEventAnnouncementRequest,
    SendEventAnnouncementResponse,
)
from .notification_sqs_client import (
    build_event_announcement_event_body,
    is_event_notification_sqs_configured,
    send_event_notification_message,
)

logger = logging.getLogger(__name__)

NOTIFICATIONS_DISABLED = (
    "Notifications are turned off for this event. Turn them on to send one."
)
QUEUE_UNAVAILABLE = "Notifications are not deliverable right now; try again later."


def send_event_announcement(
    token: str,
    event_id: UUID,
    request: SendEventAnnouncementRequest,
) -> SendEventAnnouncementResponse:
    """Queue one organizer-written push for an event.

    Raises rather than failing quietly: unlike the automatic sends, someone is
    watching this one happen and needs to know whether it went.
    """
    # Imported here rather than at module scope: event_service imports this
    # module's siblings, and the permission helper lives in event_service.
    from .event_service import _require_can_edit_event

    author = validate_cms_author_details(token=token)

    with SessionLocal() as db:
        event = get_event_by_id(db, event_id)
        if not event:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)

        _require_can_edit_event(db, event.group_id, author)

        if not event.notifications_enabled:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=NOTIFICATIONS_DISABLED,
            )

    if not is_event_notification_sqs_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=QUEUE_UNAVAILABLE,
        )

    # Identifies this one send for the whole pipeline: it is what keeps a
    # redelivered SQS message from pushing the same announcement twice, and
    # two sends of identical text are deliberately two announcements.
    announcement_id = uuid4()

    try:
        sqs_message_id = send_event_notification_message(
            build_event_announcement_event_body(
                event_id=str(event_id),
                announcement_id=str(announcement_id),
                audience=request.audience.value,
                title=request.title,
                body=request.body,
            )
        )
    except Exception as exc:
        logger.exception("Failed to enqueue announcement for event %s", event_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=QUEUE_UNAVAILABLE,
        ) from exc

    logger.info(
        "Queued announcement %s for event %s to %s",
        announcement_id,
        event_id,
        request.audience.value,
    )
    return SendEventAnnouncementResponse(
        event_id=event_id,
        announcement_id=announcement_id,
        audience=request.audience,
        sqs_message_id=sqs_message_id,
    )


def _recipient_ids(
    db: Session,
    *,
    event: Event,
    audience: EventAnnouncementAudience,
    skip: int,
    limit: int,
) -> Tuple[List[UUID], int]:
    """Who the announcement reaches, already filtered by preference.

    Both branches resolve a mute on this specific event, so the per-event
    opt-out works whichever audience the organizer picked. EVENT is the type
    both are filtered on: an announcement is something the event is saying,
    not a reminder, so silencing reminders does not silence it.
    """
    if audience == EventAnnouncementAudience.PARTICIPANTS:
        rows, total = get_event_participants_paginated(
            db=db,
            event_id=event.id,
            skip=skip,
            limit=limit,
            notification_type=NotificationType.EVENT,
        )
        return [row[0].id for row in rows], total

    author = get_user_by_email(db, event.created_by)
    if not author:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)

    return list_group_chat_recipient_user_ids(
        db=db,
        group_id=event.group_id,
        sender_id=author.id,
        skip=skip,
        limit=limit,
        notification_type=NotificationType.EVENT,
        event_id=event.id,
    )


def get_event_announcement_targets(
    *,
    event_id: UUID,
    audience: EventAnnouncementAudience,
    skip: int = 0,
    limit: int = 100,
) -> EventAnnouncementTargetsResponse:
    """Devices the worker should push this announcement to.

    The copy is not returned: it travels in the queue message, written by the
    organizer, so there is nothing here to build it from.
    """
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

        # Checked again at delivery time, not just at send time: the organizer
        # may have switched notifications off in the seconds between queueing
        # the announcement and the worker picking it up.
        if not event.notifications_enabled:
            return EventAnnouncementTargetsResponse(
                event_id=event_id,
                audience=audience,
                recipients=[],
                skip=skip,
                limit=limit,
                total=0,
                has_more=False,
            )

        recipient_ids, total = _recipient_ids(
            db, event=event, audience=audience, skip=skip, limit=limit
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

        return EventAnnouncementTargetsResponse(
            event_id=event.id,
            audience=audience,
            recipients=recipients,
            skip=skip,
            limit=limit,
            total=total,
            has_more=(skip + limit) < total,
        )
