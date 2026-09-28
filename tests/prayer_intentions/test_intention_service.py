import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException
from starlette import status

from pecha_api.chat.enums import ChatMessageType
from pecha_api.prayer_intentions.prayer_intention_service import (
    INVALID_PRAYER_INTENTION,
    INTENTION_NOT_ALLOWED_ON_TEXT,
    PRAYER_BODY_TOO_LONG,
    PRAYER_INTENTION_REQUIRED,
    PRAYER_REQUEST_BODY_MAX_LENGTH,
    validate_message_intention_and_body,
)


class TestValidateMessageIntentionAndBody:
    def test_text_rejects_intention(self):
        db = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            validate_message_intention_and_body(
                db=db,
                message_type=ChatMessageType.TEXT.value,
                body="hello",
                intention="healing",
            )

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert exc_info.value.detail == INTENTION_NOT_ALLOWED_ON_TEXT

    def test_text_allows_no_intention(self):
        db = MagicMock()

        assert (
            validate_message_intention_and_body(
                db=db,
                message_type=ChatMessageType.TEXT.value,
                body="hello",
                intention=None,
            )
            is None
        )

    @patch(
        "pecha_api.prayer_intentions.prayer_intention_service.get_prayer_intention_by_slug"
    )
    def test_prayer_requires_intention(self, mock_get):
        db = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            validate_message_intention_and_body(
                db=db,
                message_type=ChatMessageType.PRAYER.value,
                body="Please pray",
                intention=None,
            )

        assert exc_info.value.detail == PRAYER_INTENTION_REQUIRED
        mock_get.assert_not_called()

    @patch(
        "pecha_api.prayer_intentions.prayer_intention_service.get_prayer_intention_by_slug"
    )
    def test_prayer_rejects_unknown_slug(self, mock_get):
        db = MagicMock()
        mock_get.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            validate_message_intention_and_body(
                db=db,
                message_type=ChatMessageType.PRAYER.value,
                body="Please pray",
                intention="unknown",
            )

        assert exc_info.value.detail == INVALID_PRAYER_INTENTION

    @patch(
        "pecha_api.prayer_intentions.prayer_intention_service.get_prayer_intention_by_slug"
    )
    def test_prayer_rejects_long_body(self, mock_get):
        db = MagicMock()
        mock_get.return_value = MagicMock()

        body = "x" * (PRAYER_REQUEST_BODY_MAX_LENGTH + 1)
        with pytest.raises(HTTPException) as exc_info:
            validate_message_intention_and_body(
                db=db,
                message_type=ChatMessageType.PRAYER.value,
                body=body,
                intention="healing",
            )

        assert exc_info.value.detail == PRAYER_BODY_TOO_LONG
        mock_get.assert_not_called()

    @patch(
        "pecha_api.prayer_intentions.prayer_intention_service.get_prayer_intention_by_slug"
    )
    def test_prayer_normalises_intention_slug(self, mock_get):
        db = MagicMock()
        mock_get.return_value = MagicMock()

        slug = validate_message_intention_and_body(
            db=db,
            message_type=ChatMessageType.PRAYER.value,
            body="Please pray",
            intention=" Healing ",
        )

        assert slug == "healing"
        mock_get.assert_called_once_with(db=db, slug="healing")
