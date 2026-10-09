from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette import status

from pecha_api.prayer_intentions.cms_service import (
    cms_create_prayer_intention_service,
    cms_list_prayer_intentions_service,
    cms_patch_prayer_intention_service,
)
from pecha_api.prayer_intentions.prayer_intention_response_models import (
    CreatePrayerIntentionRequest,
    PatchPrayerIntentionRequest,
)


@pytest.fixture
def mock_author():
    author = MagicMock()
    author.email = "author@example.com"
    return author


class TestCmsPrayerIntentionsService:
    @patch("pecha_api.prayer_intentions.cms_service.validate_cms_author_details")
    @patch("pecha_api.prayer_intentions.cms_service.SessionLocal")
    @patch("pecha_api.prayer_intentions.cms_service.list_prayer_intentions")
    @patch("pecha_api.prayer_intentions.cms_service.count_intention_event_links")
    def test_list(
        self,
        mock_count_links,
        mock_list,
        mock_session,
        mock_validate,
        mock_author,
    ):
        mock_validate.return_value = mock_author
        db = MagicMock()
        mock_session.return_value.__enter__.return_value = db
        row = MagicMock(
            id=uuid4(),
            slug="healing",
            label="Healing",
            color="#4A78C2",
            description="For illness.",
            display_order=1,
        )
        mock_list.return_value = [row]
        mock_count_links.return_value = 2

        response = cms_list_prayer_intentions_service(token="token")

        assert len(response.intentions) == 1
        assert response.intentions[0].slug == "healing"
        assert response.intentions[0].linked_event_count == 2

    @patch("pecha_api.prayer_intentions.cms_service.require_cms_write_access")
    @patch("pecha_api.prayer_intentions.cms_service.validate_cms_author_details")
    @patch("pecha_api.prayer_intentions.cms_service.SessionLocal")
    @patch("pecha_api.prayer_intentions.cms_service.create_prayer_intention")
    def test_create(
        self,
        mock_create,
        mock_session,
        mock_validate,
        mock_require_write,
        mock_author,
    ):
        mock_validate.return_value = mock_author
        db = MagicMock()
        mock_session.return_value.__enter__.return_value = db
        row = MagicMock(
            id=uuid4(),
            slug="guidance",
            label="Guidance",
            color="#111111",
            description="Seeking direction.",
            display_order=5,
        )
        mock_create.return_value = row

        dto = cms_create_prayer_intention_service(
            token="token",
            request=CreatePrayerIntentionRequest(
                slug="Guidance",
                label="Guidance",
                color="#111111",
                description="Seeking direction.",
                display_order=5,
            ),
        )

        assert dto.slug == "guidance"
        mock_require_write.assert_called_once_with(mock_author)
        mock_create.assert_called_once()

    @patch("pecha_api.prayer_intentions.cms_service.require_cms_write_access")
    @patch("pecha_api.prayer_intentions.cms_service.validate_cms_author_details")
    @patch("pecha_api.prayer_intentions.cms_service.SessionLocal")
    @patch("pecha_api.prayer_intentions.cms_service.get_prayer_intention_by_id")
    def test_patch_not_found(
        self,
        mock_get,
        mock_session,
        mock_validate,
        mock_require_write,
        mock_author,
    ):
        mock_validate.return_value = mock_author
        db = MagicMock()
        mock_session.return_value.__enter__.return_value = db
        mock_get.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            cms_patch_prayer_intention_service(
                token="token",
                intention_id=uuid4(),
                request=PatchPrayerIntentionRequest(label="Updated"),
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @patch("pecha_api.prayer_intentions.cms_service.require_cms_write_access")
    @patch("pecha_api.prayer_intentions.cms_service.validate_cms_author_details")
    @patch("pecha_api.prayer_intentions.cms_service.SessionLocal")
    @patch("pecha_api.prayer_intentions.cms_service.get_prayer_intention_by_id")
    @patch("pecha_api.prayer_intentions.cms_service.update_prayer_intention")
    @patch("pecha_api.prayer_intentions.cms_service.count_intention_event_links")
    def test_patch_updates_provided_fields(
        self,
        mock_count_links,
        mock_update,
        mock_get,
        mock_session,
        mock_validate,
        mock_require_write,
        mock_author,
    ):
        mock_validate.return_value = mock_author
        db = MagicMock()
        mock_session.return_value.__enter__.return_value = db
        existing = MagicMock(
            id=uuid4(),
            slug="healing",
            label="Healing",
            color="#4A78C2",
            description="For illness.",
            display_order=1,
        )
        updated = MagicMock(
            id=existing.id,
            slug="healing",
            label="Recovery",
            color="#4A78C2",
            description="For illness.",
            display_order=1,
        )
        mock_get.return_value = existing
        mock_update.return_value = updated
        mock_count_links.return_value = 3

        dto = cms_patch_prayer_intention_service(
            token="token",
            intention_id=existing.id,
            request=PatchPrayerIntentionRequest(label="Recovery"),
        )

        assert dto.label == "Recovery"
        assert dto.slug == "healing"
        assert dto.linked_event_count == 3
        mock_require_write.assert_called_once_with(mock_author)
        mock_update.assert_called_once_with(
            db=db,
            intention=existing,
            label="Recovery",
            color=existing.color,
            description=existing.description,
            display_order=existing.display_order,
        )

    def test_create_rejects_whitespace_only_slug(self):
        with pytest.raises(ValueError):
            CreatePrayerIntentionRequest(
                slug="   ",
                label="Healing",
                color="#111111",
                description="For illness.",
            )

    def test_patch_rejects_whitespace_only_label(self):
        with pytest.raises(ValueError):
            PatchPrayerIntentionRequest(label="   ")


def test_create_request_rejects_former_intention_names() -> None:
    import pytest
    from pydantic import ValidationError

    from pecha_api.prayer_intentions.prayer_intention_response_models import (
        CreatePrayerIntentionRequest,
    )

    for slug in ("compassion", "Gratitude", "dedication"):
        with pytest.raises(ValidationError):
            CreatePrayerIntentionRequest(
                slug=slug, label="L", color="#fff", description="d"
            )

    assert CreatePrayerIntentionRequest(
        slug="Courage", label="L", color="#fff", description="d"
    ).slug == "courage"
