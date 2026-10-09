from unittest.mock import MagicMock, patch
from uuid import uuid4

import pecha_api.app  # noqa: F401

from pecha_api.chat.enums import ChatMessageType
from pecha_api.chat.prayer_translation_internal_service import (
    apply_prayer_translation_result_service,
)
from pecha_api.chat.prayer_translation_response_models import (
    PrayerTranslationResultRequest,
)
from pecha_api.plans.plans_enums import LanguageCode


class MockMessage:
    def __init__(self, body="Original"):
        self.id = uuid4()
        self.body = body
        self.message_type = ChatMessageType.PRAYER.value
        self.deleted_at = None


class TestApplyPrayerTranslationResultService:
    @patch("pecha_api.chat.prayer_translation_internal_service.apply_prayer_translation_result")
    @patch("pecha_api.chat.prayer_translation_internal_service.SessionLocal")
    def test_applies_when_body_matches(self, mock_session_local, mock_apply):
        message = MockMessage(body="Hello")
        mock_db = MagicMock()
        mock_session_local.return_value.__enter__.return_value = mock_db
        mock_db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = (
            message
        )

        apply_prayer_translation_result_service(
            message_id=message.id,
            request=PrayerTranslationResultRequest(
                body_at_dispatch="Hello",
                source_language="EN",
                translations={"EN": "Hello", "BO": "བོད", "ZH": "你好"},
            ),
        )

        mock_apply.assert_called_once()

    @patch("pecha_api.chat.prayer_translation_internal_service.apply_prayer_translation_result")
    @patch("pecha_api.chat.prayer_translation_internal_service.SessionLocal")
    def test_applies_iso_source_outside_en_bo_zh(self, mock_session_local, mock_apply):
        message = MockMessage(body="Bonjour")
        mock_db = MagicMock()
        mock_session_local.return_value.__enter__.return_value = mock_db
        mock_db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = (
            message
        )

        apply_prayer_translation_result_service(
            message_id=message.id,
            request=PrayerTranslationResultRequest(
                body_at_dispatch="Bonjour",
                source_language="FR",
                translations={"EN": "Hello", "BO": "བོད", "ZH": "你好"},
            ),
        )

        mock_apply.assert_called_once()
        assert mock_apply.call_args.kwargs["source_language"] == "FR"

    @patch("pecha_api.chat.prayer_translation_internal_service.mark_prayer_translations_failed")
    @patch("pecha_api.chat.prayer_translation_internal_service.apply_prayer_translation_result")
    @patch("pecha_api.chat.prayer_translation_internal_service.SessionLocal")
    def test_skips_stale_result_after_body_edit(
        self, mock_session_local, mock_apply, mock_mark_failed
    ):
        message = MockMessage(body="Edited")
        mock_db = MagicMock()
        mock_session_local.return_value.__enter__.return_value = mock_db
        mock_db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = (
            message
        )

        apply_prayer_translation_result_service(
            message_id=message.id,
            request=PrayerTranslationResultRequest(
                body_at_dispatch="Original",
                source_language="EN",
                translations={"EN": "Hi", "BO": "བོད", "ZH": "你好"},
            ),
        )

        mock_apply.assert_not_called()
        mock_mark_failed.assert_not_called()

    @patch("pecha_api.chat.prayer_translation_internal_service.mark_prayer_translations_failed")
    @patch("pecha_api.chat.prayer_translation_internal_service.SessionLocal")
    def test_marks_failed_when_worker_reports_failure(
        self, mock_session_local, mock_mark_failed
    ):
        message = MockMessage(body="Hello")
        mock_db = MagicMock()
        mock_session_local.return_value.__enter__.return_value = mock_db
        mock_db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = (
            message
        )

        apply_prayer_translation_result_service(
            message_id=message.id,
            request=PrayerTranslationResultRequest(
                body_at_dispatch="Hello",
                failed=True,
            ),
        )

        mock_mark_failed.assert_called_once()
