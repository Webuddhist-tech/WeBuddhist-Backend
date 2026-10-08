from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pecha_api.app  # noqa: F401

from pecha_api.chat.enums import ChatMessageType
from pecha_api.chat.prayer_translation_service import (
    build_translation_view,
    ensure_translations_for_message,
)
from pecha_api.chat.response_models import ChatMessageTranslationDTO
from pecha_api.chat.service import build_message_dto
from pecha_api.plans.plans_enums import LanguageCode


class MockTranslation:
    def __init__(self, status="pending", body=None):
        self.status = status
        self.body = body


class MockMessage:
    def __init__(self, source_language=None, body="བོད་ཡིག"):
        self.id = uuid4()
        self.room_id = uuid4()
        self.sender_id = uuid4()
        self.sender = MagicMock(email="a@b.com", firstname="A", lastname=None, avatar_url=None)
        self.body = body
        self.message_type = ChatMessageType.PRAYER.value
        self.source_language = source_language
        self.created_at = datetime.now(timezone.utc)
        self.deleted_at = None
        self.parent = None
        self.intention = None
        self.is_edited = False


class TestBuildTranslationView:
    def test_can_translate_when_source_differs_from_target(self):
        message = MockMessage(source_language=LanguageCode.BO)
        row = MockTranslation(status="ready", body="English text")

        view = build_translation_view(
            message=message, row=row, target_language=LanguageCode.EN
        )

        assert view["can_translate"] is True
        assert view["source_language"] == "BO"
        assert view["translation"]["status"] == "ready"
        assert view["translation"]["body"] == "English text"

    def test_cannot_translate_when_source_matches_target(self):
        message = MockMessage(source_language=LanguageCode.EN)

        view = build_translation_view(
            message=message, row=None, target_language=LanguageCode.EN
        )

        assert view["can_translate"] is False
        assert view["translation"] is None


class TestChatMessageDtoSerialization:
    def test_text_message_omits_translation_fields(self):
        message = MockMessage()
        message.message_type = ChatMessageType.TEXT.value
        dto = build_message_dto(
            message,
            source_language="BO",
            translation=ChatMessageTranslationDTO(
                target_language="EN", status="ready", body="Hi"
            ),
            can_translate=True,
        )
        payload = dto.model_dump()
        assert "source_language" not in payload
        assert "translation" not in payload
        assert "can_translate" not in payload

    def test_prayer_message_keeps_original_body(self):
        message = MockMessage(source_language=LanguageCode.BO)
        dto = build_message_dto(
            message,
            source_language="BO",
            translation=ChatMessageTranslationDTO(
                target_language="EN", status="ready", body="Translated"
            ),
            can_translate=True,
        )
        payload = dto.model_dump()
        assert payload["body"] == message.body
        assert payload["translation"]["body"] == "Translated"

    def test_deleted_prayer_hides_translation_fields(self):
        message = MockMessage(source_language=LanguageCode.ZH)
        message.deleted_at = datetime.now(timezone.utc)
        dto = build_message_dto(
            message,
            source_language="ZH",
            translation=ChatMessageTranslationDTO(
                target_language="EN", status="ready", body="Secret translation"
            ),
            can_translate=True,
        )
        payload = dto.model_dump()
        assert payload["body"] == ""
        assert payload.get("source_language") is None
        assert payload.get("translation") is None
        assert payload.get("can_translate") is False


class TestEnsureTranslationsForMessage:
    @patch("pecha_api.chat.prayer_translation_service.apply_prayer_translation_result")
    @patch("pecha_api.chat.prayer_translation_service.translate_prayer_request")
    @patch("pecha_api.chat.prayer_translation_service.get_message_by_id_any_room")
    @patch("pecha_api.chat.prayer_translation_service.SessionLocal")
    def test_calls_gemini_and_persists(
        self, mock_session_local, mock_get_message, mock_translate, mock_apply
    ):
        message = MockMessage(body="Please pray")
        message.message_type = ChatMessageType.PRAYER.value
        mock_db = MagicMock()
        mock_session_local.return_value.__enter__.return_value = mock_db
        mock_get_message.return_value = message
        mock_db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = (
            message
        )
        mock_translate.return_value = (
            LanguageCode.EN,
            {LanguageCode.BO: "བོད", LanguageCode.ZH: "中文"},
        )

        ensure_translations_for_message(message.id)

        mock_translate.assert_called_once_with("Please pray")
        mock_apply.assert_called_once()

    @patch("pecha_api.chat.prayer_translation_service.apply_prayer_translation_result")
    @patch("pecha_api.chat.prayer_translation_service.translate_prayer_request")
    @patch("pecha_api.chat.prayer_translation_service.get_message_by_id_any_room")
    @patch("pecha_api.chat.prayer_translation_service.SessionLocal")
    def test_skips_stale_gemini_result_after_body_edit(
        self, mock_session_local, mock_get_message, mock_translate, mock_apply
    ):
        message = MockMessage(body="Original")
        message.message_type = ChatMessageType.PRAYER.value
        edited = MockMessage(body="Edited")
        edited.message_type = ChatMessageType.PRAYER.value
        mock_db = MagicMock()
        mock_session_local.return_value.__enter__.return_value = mock_db
        mock_get_message.return_value = message
        mock_db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = (
            edited
        )
        mock_translate.return_value = (
            LanguageCode.EN,
            {LanguageCode.BO: "བོད", LanguageCode.ZH: "中文"},
        )

        ensure_translations_for_message(message.id)

        mock_translate.assert_called_once_with("Original")
        mock_apply.assert_not_called()

    @patch("pecha_api.chat.prayer_translation_service.mark_prayer_translations_failed")
    @patch("pecha_api.chat.prayer_translation_service.translate_prayer_request")
    @patch("pecha_api.chat.prayer_translation_service.get_message_by_id_any_room")
    @patch("pecha_api.chat.prayer_translation_service.SessionLocal")
    def test_skips_stale_gemini_failure_after_body_edit(
        self, mock_session_local, mock_get_message, mock_translate, mock_mark_failed
    ):
        message = MockMessage(body="Original")
        message.message_type = ChatMessageType.PRAYER.value
        edited = MockMessage(body="Edited")
        edited.message_type = ChatMessageType.PRAYER.value
        mock_db = MagicMock()
        mock_session_local.return_value.__enter__.return_value = mock_db
        mock_get_message.return_value = message
        mock_db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = (
            edited
        )
        mock_translate.return_value = None

        ensure_translations_for_message(message.id)

        mock_translate.assert_called_once_with("Original")
        mock_mark_failed.assert_not_called()
