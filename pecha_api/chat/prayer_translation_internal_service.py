from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session
from starlette import status

from pecha_api.chat.enums import ChatMessageType
from pecha_api.chat.models import ChatMessage
from pecha_api.chat.prayer_translation_payload import parse_prayer_translation_payload
from pecha_api.chat.repository import (
    apply_prayer_translation_result,
    get_message_by_id_any_room,
    mark_prayer_translations_failed,
)
from pecha_api.chat.service import _message_type_value
from pecha_api.plans.response_message import NOT_FOUND
from pecha_api.chat.prayer_translation_response_models import (
    PrayerTranslationPayloadResponse,
    PrayerTranslationResultRequest,
)
from pecha_api.db.database import SessionLocal

def _prayer_message_for_translation_apply(
    db: Session, message_id: UUID, body_at_start: str
) -> ChatMessage | None:
    message = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.id == message_id,
            ChatMessage.deleted_at.is_(None),
        )
        .with_for_update()
        .first()
    )
    if not message or _message_type_value(message) != ChatMessageType.PRAYER.value:
        return None
    if message.body != body_at_start:
        return None
    return message


def get_prayer_translation_payload_service(message_id: UUID) -> PrayerTranslationPayloadResponse:
    with SessionLocal() as db:
        message = get_message_by_id_any_room(db=db, message_id=message_id)
        if not message or message.deleted_at is not None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
        if _message_type_value(message) != ChatMessageType.PRAYER.value:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
        return PrayerTranslationPayloadResponse(message_id=message.id, body=message.body)


def apply_prayer_translation_result_service(
    message_id: UUID, request: PrayerTranslationResultRequest
) -> None:
    with SessionLocal() as db:
        message = _prayer_message_for_translation_apply(
            db=db, message_id=message_id, body_at_start=request.body_at_dispatch
        )
        if message is None:
            return

        if request.failed:
            mark_prayer_translations_failed(db=db, message_id=message_id)
            return

        parsed = parse_prayer_translation_payload(
            {
                "source_language": request.source_language,
                "translations": request.translations or {},
            }
        )
        if parsed is None:
            mark_prayer_translations_failed(db=db, message_id=message_id)
            return

        source_language, translations = parsed
        apply_prayer_translation_result(
            db=db,
            message=message,
            source_language=source_language,
            translations=translations,
        )
