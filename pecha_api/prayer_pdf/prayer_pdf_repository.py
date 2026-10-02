from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from pecha_api.chat.enums import ChatMessageType
from pecha_api.chat.models import ChatMessage
from pecha_api.users.users_models import Users

from .prayer_pdf_model import PrayerPdfSettings


def get_group_settings(db: Session, group_id: UUID) -> Optional[PrayerPdfSettings]:
    return (
        db.query(PrayerPdfSettings)
        .filter(
            PrayerPdfSettings.group_id == group_id,
            PrayerPdfSettings.event_id.is_(None),
        )
        .first()
    )


def get_event_settings(db: Session, event_id: UUID) -> Optional[PrayerPdfSettings]:
    return (
        db.query(PrayerPdfSettings)
        .filter(PrayerPdfSettings.event_id == event_id)
        .first()
    )


def upsert_settings(
    db: Session,
    *,
    group_id: UUID,
    event_id: Optional[UUID],
    values: Dict[str, Any],
    updated_by: Optional[str],
) -> PrayerPdfSettings:
    row = (
        get_event_settings(db, event_id)
        if event_id is not None
        else get_group_settings(db, group_id)
    )
    now = datetime.now(timezone.utc)
    if row is None:
        row = PrayerPdfSettings(
            group_id=group_id, event_id=event_id, created_at=now
        )
        db.add(row)
    for key, value in values.items():
        setattr(row, key, value)
    row.updated_at = now
    row.updated_by = updated_by
    db.commit()
    db.refresh(row)
    return row


def delete_settings(db: Session, row: PrayerPdfSettings) -> None:
    db.delete(row)
    db.commit()


def list_prayer_requests(
    db: Session,
    *,
    room_id: UUID,
    start_utc: datetime,
    end_utc: datetime,
) -> List[Tuple[ChatMessage, Users]]:
    """A room's live prayer requests posted in [start_utc, end_utc), oldest
    first, each with the person who asked."""
    return (
        db.query(ChatMessage, Users)
        .join(Users, Users.id == ChatMessage.sender_id)
        .filter(
            ChatMessage.room_id == room_id,
            ChatMessage.message_type == ChatMessageType.PRAYER.value,
            ChatMessage.deleted_at.is_(None),
            ChatMessage.created_at >= start_utc,
            ChatMessage.created_at < end_utc,
        )
        .order_by(ChatMessage.created_at.asc())
        .all()
    )
