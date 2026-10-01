import pytest
from unittest.mock import MagicMock, patch
from uuid import uuid4
from fastapi import HTTPException
from starlette import status

from pecha_api.chat.enums import ChatMessageType
from pecha_api.prayer_intentions.prayer_intention_response_models import (
    PrayerIntentionDTO,
    PrayerIntentionsResponse,
)
from pecha_api.prayer_intentions.prayer_intention_service import (
    INTENTION_NOT_ALLOWED_FOR_EVENT,
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
    @patch(
        "pecha_api.prayer_intentions.prayer_intention_service.get_prayer_intention_by_slug"
    )
    def test_resolve_intention_dtos_for_slugs_maps_legacy_slug(
        self, mock_get_by_slug, mock_get_batch
    ):
        db = MagicMock()
        row = MagicMock(
            slug="love",
            label="Love",
            color="#C8503D",
            description="Relationships.",
            display_order=3,
        )
        mock_get_by_slug.side_effect = lambda *, slug, **_kwargs: (
            row if slug == "love" else None
        )
        mock_get_batch.return_value = {"love": row}

        result = resolve_intention_dtos_for_slugs(db=db, slugs=["compassion"])

        assert result["compassion"].slug == "love"
        mock_get_batch.assert_called_once_with(db=db, slugs=["love"])

    @patch(
        "pecha_api.prayer_intentions.prayer_intention_service.get_prayer_intentions_by_slugs"
    )
    @patch(
        "pecha_api.prayer_intentions.prayer_intention_service.get_prayer_intention_by_slug"
    )
    def test_resolve_intention_dtos_for_slugs_maps_stored_new_slug_on_legacy_catalog(
        self, mock_get_by_slug, mock_get_batch
    ):
        db = MagicMock()
        row = MagicMock(
            slug="dedication",
            label="Dedication",
            color="#FFFFFF",
            description="To dedicate merit.",
            display_order=4,
        )
        mock_get_by_slug.side_effect = lambda *, slug, **_kwargs: (
            row if slug == "dedication" else None
        )
        mock_get_batch.return_value = {"dedication": row}

        result = resolve_intention_dtos_for_slugs(db=db, slugs=["peace"])

        assert result["peace"].slug == "dedication"
        mock_get_batch.assert_called_once_with(db=db, slugs=["dedication"])

    @patch(
        "pecha_api.prayer_intentions.prayer_intention_service.get_prayer_intentions_by_slugs"
    )
    @patch(
        "pecha_api.prayer_intentions.prayer_intention_service.get_prayer_intention_by_slug"
    )
    def test_resolve_intention_dtos_for_slugs_maps_rows(
        self, mock_get_by_slug, mock_get_batch
    ):
        db = MagicMock()
        row = MagicMock(
            slug="healing",
            label="Healing",
            color="#4A78C2",
            description="For illness.",
            display_order=0,
        )
        mock_get_by_slug.side_effect = lambda *, slug, **_kwargs: (
            row if slug == "healing" else None
        )
        mock_get_batch.return_value = {"healing": row}

        result = resolve_intention_dtos_for_slugs(db=db, slugs=["healing", None])

        assert "healing" in result
        assert result["healing"].slug == "healing"
        mock_get_batch.assert_called_once_with(db=db, slugs=["healing"])


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

    @patch(
        "pecha_api.prayer_intentions.prayer_intention_service.get_prayer_intention_by_slug"
    )
    def test_prayer_accepts_legacy_slug_and_stores_catalog_slug(self, mock_get):
        db = MagicMock()
        mock_get.side_effect = lambda *, slug, **_kwargs: (
            MagicMock() if slug == "love" else None
        )

        slug = validate_message_intention_and_body(
            db=db,
            message_type=ChatMessageType.PRAYER.value,
            body="Please pray",
            intention="compassion",
        )

        assert slug == "love"

    @patch(
        "pecha_api.prayer_intentions.prayer_intention_service.get_prayer_intention_by_slug"
    )
    def test_prayer_accepts_new_slug_on_downgraded_catalog(self, mock_get):
        db = MagicMock()
        mock_get.side_effect = lambda *, slug, **_kwargs: (
            MagicMock() if slug == "dedication" else None
        )

        slug = validate_message_intention_and_body(
            db=db,
            message_type=ChatMessageType.PRAYER.value,
            body="Please pray",
            intention="peace",
        )

        assert slug == "dedication"

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

    @patch(
        "pecha_api.prayer_intentions.prayer_intention_service.get_event_allowed_slugs"
    )
    @patch(
        "pecha_api.prayer_intentions.prayer_intention_service.get_prayer_intention_by_slug"
    )
    def test_prayer_rejects_intention_not_allowed_for_event(
        self, mock_get_by_slug, mock_allowed
    ):
        db = MagicMock()
        mock_get_by_slug.return_value = MagicMock()
        mock_allowed.return_value = {"healing"}

        with pytest.raises(HTTPException) as exc_info:
            validate_message_intention_and_body(
                db=db,
                message_type=ChatMessageType.PRAYER.value,
                body="Please pray",
                intention="peace",
                event_id=uuid4(),
            )

        assert exc_info.value.detail == INTENTION_NOT_ALLOWED_FOR_EVENT

    @patch(
        "pecha_api.prayer_intentions.prayer_intention_service.get_event_allowed_slugs"
    )
    @patch(
        "pecha_api.prayer_intentions.prayer_intention_service.get_prayer_intention_by_slug"
    )
    def test_prayer_allows_intention_when_event_unrestricted(
        self, mock_get_by_slug, mock_allowed
    ):
        db = MagicMock()
        mock_get_by_slug.return_value = MagicMock()
        mock_allowed.return_value = None

        slug = validate_message_intention_and_body(
            db=db,
            message_type=ChatMessageType.PRAYER.value,
            body="Please pray",
            intention="peace",
            event_id=uuid4(),
        )

        assert slug == "peace"


class TestGetAllPrayerIntentionsForEvent:
    @patch("pecha_api.prayer_intentions.prayer_intention_service.SessionLocal")
    @patch(
        "pecha_api.prayer_intentions.prayer_intention_service.list_prayer_intentions_for_event"
    )
    @patch("pecha_api.events.event_repository.get_event_by_id")
    def test_restricted_event_returns_linked_rows_only(
        self, mock_get_event, mock_list_for_event, mock_session
    ):
        event_id = uuid4()
        db = MagicMock()
        mock_session.return_value.__enter__.return_value = db
        mock_get_event.return_value = MagicMock()
        healing = MagicMock(
            slug="healing",
            label="Healing",
            color="#4A78C2",
            description="",
            display_order=0,
        )
        mock_list_for_event.return_value = [healing]

        response = get_all_prayer_intentions_service(event_id=event_id)

        assert len(response.intentions) == 1
        assert response.intentions[0].slug == "healing"
        mock_get_event.assert_called_once_with(db=db, event_id=event_id)
        mock_list_for_event.assert_called_once_with(db=db, event_id=event_id)

    @patch("pecha_api.prayer_intentions.prayer_intention_service.SessionLocal")
    @patch("pecha_api.prayer_intentions.prayer_intention_service.list_prayer_intentions")
    @patch(
        "pecha_api.prayer_intentions.prayer_intention_service.list_prayer_intentions_for_event"
    )
    @patch("pecha_api.events.event_repository.get_event_by_id")
    def test_unrestricted_event_falls_back_to_full_catalog(
        self, mock_get_event, mock_list_for_event, mock_list_all, mock_session
    ):
        event_id = uuid4()
        db = MagicMock()
        mock_session.return_value.__enter__.return_value = db
        mock_get_event.return_value = MagicMock()
        mock_list_for_event.return_value = []
        peace = MagicMock(
            slug="peace",
            label="Peace",
            color="#FFFFFF",
            description="",
            display_order=0,
        )
        mock_list_all.return_value = [peace]

        response = get_all_prayer_intentions_service(event_id=event_id)

        assert response.intentions[0].slug == "peace"
        mock_list_all.assert_called_once_with(db)

    @patch("pecha_api.prayer_intentions.prayer_intention_service.SessionLocal")
    @patch("pecha_api.events.event_repository.get_event_by_id")
    def test_unknown_event_returns_404(self, mock_get_event, mock_session):
        event_id = uuid4()
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get_event.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            get_all_prayer_intentions_service(event_id=event_id)

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
