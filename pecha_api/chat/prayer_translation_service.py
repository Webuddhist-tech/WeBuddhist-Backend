"""Generate and cache Gemini translations for prayer request messages."""

from __future__ import annotations

import logging
import threading
from typing import Dict, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from pecha_api import config
from pecha_api.chat.enums import ChatMessageType
from pecha_api.chat.models import ChatMessage, ChatMessageTranslation
from pecha_api.chat.service import _message_type_value
from pecha_api.chat.repository import (
    apply_prayer_translation_result,
    get_message_by_id_any_room,
    list_message_ids_needing_translation,
    mark_prayer_translations_failed,
    reset_prayer_translations,
)
from pecha_api.db.database import SessionLocal
from pecha_api.external_clients.gemini_client import translate_prayer_request
from pecha_api.plans.plans_enums import LanguageCode
from pecha_api.users.user_metadata_repository import get_user_metadata_by_user_id

logger = logging.getLogger(__name__)


def resolve_translation_language_for_user(
    db: Session, user_id: UUID, requested: Optional[LanguageCode]
) -> LanguageCode:
    if requested is not None:
        return requested
    metadata = get_user_metadata_by_user_id(db=db, user_id=user_id)
    if metadata and metadata.language in (
        LanguageCode.EN,
        LanguageCode.BO,
        LanguageCode.ZH,
    ):
        return metadata.language
    return LanguageCode.EN


def prepare_prayer_translations(message_id: UUID) -> None:
    """Seed pending translation rows after a prayer body is stored or edited."""
    with SessionLocal() as db:
        message = get_message_by_id_any_room(db=db, message_id=message_id)
        if not message or message.deleted_at is not None:
            return
        if _message_type_value(message) != ChatMessageType.PRAYER.value:
            return
        reset_prayer_translations(db=db, message=message)


def schedule_ensure_prayer_translations(message_id: UUID) -> None:
    """Run Gemini translation off the request/WebSocket thread after persist."""
    threading.Thread(
        target=ensure_translations_for_message,
        args=(message_id,),
        daemon=True,
        name=f"prayer-translation-{message_id}",
    ).start()


def ensure_translations_for_message(message_id: UUID) -> None:
    """Run Gemini and persist translations for one prayer message."""
    with SessionLocal() as db:
        message = get_message_by_id_any_room(db=db, message_id=message_id)
        if not message or message.deleted_at is not None:
            return
        if _message_type_value(message) != ChatMessageType.PRAYER.value:
            return
        body_at_start = message.body

    result = translate_prayer_request(body_at_start)
    if result is None:
        with SessionLocal() as db:
            mark_prayer_translations_failed(db=db, message_id=message_id)
        return

    source_language, translations = result
    with SessionLocal() as db:
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
            return
        if message.body != body_at_start:
            return
        apply_prayer_translation_result(
            db=db,
            message=message,
            source_language=source_language,
            translations=translations,
        )


def reconcile_pending_prayer_translations() -> None:
    """Retry prayer translations stuck in pending or failed."""
    batch_size = max(config.get_int("PRAYER_TRANSLATION_RECONCILE_BATCH_SIZE"), 1)
    with SessionLocal() as db:
        message_ids = list_message_ids_needing_translation(db=db, limit=batch_size)
    for message_id in message_ids:
        try:
            ensure_translations_for_message(message_id)
        except Exception:
            logger.exception(
                "Failed to reconcile prayer translation for message %s", message_id
            )


def build_translation_view(
    message: ChatMessage,
    row: Optional[ChatMessageTranslation],
    target_language: LanguageCode,
) -> Dict[str, object]:
    """Fields for ChatMessageDTO prayer translation metadata."""
    source = getattr(message, "source_language", None)
    source_value = (
        source.value if source is not None and hasattr(source, "value") else None
    )
    target_value = target_language.value
    can_translate = source_value is None or source_value != target_value

    translation_block: Optional[Dict[str, object]] = None
    if can_translate:
        status = row.status if row is not None else "pending"
        translation_block = {
            "target_language": target_value,
            "status": status,
        }
        if row is not None and row.body and status == "ready":
            translation_block["body"] = row.body

    return {
        "source_language": source_value,
        "translation": translation_block,
        "can_translate": can_translate,
    }
