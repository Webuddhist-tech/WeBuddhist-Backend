import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException
from starlette import status

from pecha_api.chat.enums import ChatMessageType
from pecha_api.prayer_intentions.prayer_intention_response_models import (
    PrayerIntentionDTO,
    PrayerIntentionsResponse,
)
from pecha_api.prayer_intentions.prayer_intention_service import (
    INVALID_PRAYER_INTENTION,
    INTENTION_NOT_ALLOWED_ON_TEXT,
    PRAYER_BODY_TOO_LONG,
    PRAYER_INTENTION_REQUIRED,
    PRAYER_REQUEST_BODY_MAX_LENGTH,
    get_all_prayer_intentions_service,
    prayer_intention_to_dto,
    resolve_intention_dtos_for_slugs,
    validate_message_intention_and_body,
)


class TestPrayerIntentionDTOHelpers:
    def test_prayer_intention_to_dto(self):
        row = MagicMock(
            slug="healing",
            label="Healing",
            color="#4A78C2",
            description="For illness.",
            display_order=0,
        )

        dto = prayer_intention_to_dto(row)

        assert dto == PrayerIntentionDTO(
            slug="healing",
            label="Healing",
            color="#4A78C2",
            description="For illness.",
            display_order=0,
        )

    @patch("pecha_api.prayer_intentions.prayer_intention_service.list_prayer_intentions")
    @patch("pecha_api.prayer_intentions.prayer_intention_service.SessionLocal")
    def test_get_all_prayer_intentions_service(self, mock_session, mock_list):
        db = MagicMock()
        mock_session.return_value.__enter__.return_value = db
        row = MagicMock(
            slug="healing",
            label="Healing",
            color="#4A78C2",
            description="For illness.",
            display_order=0,
        )
        mock_list.return_value = [row]

        response = get_all_prayer_intentions_service()

        assert isinstance(response, PrayerIntentionsResponse)
        assert len(response.intentions) == 1
        assert response.intentions[0].slug == "healing"
        mock_list.assert_called_once_with(db)

    @patch(
        "pecha_api.prayer_intentions.prayer_intention_service.get_prayer_intentions_by_slugs"
    )
    def test_resolve_intention_dtos_for_slugs_empty(self, mock_get):
        assert resolve_intention_dtos_for_slugs(db=MagicMock(), slugs=[None, ""]) == {}
        mock_get.assert_not_called()

    @patch(
        "pecha_api.prayer_intentions.prayer_intention_service.get_prayer_intentions_by_slugs"
    )
    def test_resolve_intention_dtos_for_slugs_maps_rows(self, mock_get):
        db = MagicMock()
        row = MagicMock(
            slug="healing",
            label="Healing",
            color="#4A78C2",
            description="For illness.",
            display_order=0,
        )
        mock_get.return_value = {"healing": row}

        result = resolve_intention_dtos_for_slugs(db=db, slugs=["healing", None])

        assert "healing" in result
        assert result["healing"].slug == "healing"
        mock_get.assert_called_once_with(db=db, slugs=["healing"])


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

    @patch(
        "pecha_api.prayer_intentions.prayer_intention_service.get_prayer_intention_by_slug"
    )
    def test_prayer_accepts_valid_request(self, mock_get):
        db = MagicMock()
        mock_get.return_value = MagicMock()

        slug = validate_message_intention_and_body(
            db=db,
            message_type=ChatMessageType.PRAYER.value,
            body="Please pray",
            intention="healing",
        )

        assert slug == "healing"

    def test_text_rejects_body_over_4000_chars(self):
        db = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            validate_message_intention_and_body(
                db=db,
                message_type=ChatMessageType.TEXT.value,
                body="x" * 4001,
                intention=None,
            )

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert "4000" in exc_info.value.detail

    def test_other_message_type_returns_normalized_intention(self):
        db = MagicMock()

        result = validate_message_intention_and_body(
            db=db,
            message_type="CUSTOM",
            body="hello",
            intention=" Healing ",
        )

        assert result == "healing"
