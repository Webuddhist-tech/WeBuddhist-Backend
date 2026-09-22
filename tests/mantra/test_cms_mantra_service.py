import pytest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException

from pecha_api.mantra.mantra_response_models import CreateMantraRequest, MantraMetadataInput, UpdateMantraRequest
from pecha_api.mantra.mantra_response_models import CMSMantraDTO
from pecha_api.mantra.mantra_service import create_mantra_service, update_mantra_service, upload_mantra_image
from pecha_api.plans.media.media_response_models import PlanUploadResponse, ImageUrlModel
from pecha_api.plans.plans_enums import LanguageCode


class TestCreateMantraService:
    @patch("pecha_api.mantra.mantra_service.validate_cms_author_details")
    @patch("pecha_api.mantra.mantra_service.SessionLocal")
    @patch("pecha_api.mantra.mantra_service.save_mantra")
    @patch("pecha_api.mantra.mantra_service._build_cms_mantra_dto")
    def test_create_mantra_service_success(
        self,
        mock_build_cms_dto,
        mock_save_mantra,
        mock_session,
        mock_validate_auth,
    ):
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        saved_mantra = MagicMock()
        mock_save_mantra.return_value = saved_mantra
        expected_dto = MagicMock()
        mock_build_cms_dto.return_value = expected_dto

        request = CreateMantraRequest(
            audio_url="mantras/test.mp3",
            metadata=[
                MantraMetadataInput(
                    mantra="Om mani padme hum",
                    title="Compassion mantra",
                    language=LanguageCode.EN,
                )
            ],
        )

        result = create_mantra_service(token="token", request=request)

        assert result is expected_dto
        mock_validate_auth.assert_called_once_with(token="token")
        mock_save_mantra.assert_called_once()
        mock_build_cms_dto.assert_called_once_with(saved_mantra)

    @patch("pecha_api.mantra.mantra_service.validate_cms_author_details")
    @patch("pecha_api.mantra.mantra_service.SessionLocal")
    @patch("pecha_api.mantra.mantra_service.get_mala_image_by_id")
    def test_create_mantra_service_invalid_mala_image(
        self,
        mock_get_mala,
        mock_session,
        mock_validate_auth,
    ):
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get_mala.return_value = None

        mala_id = uuid4()
        request = CreateMantraRequest(
            mala_image_id=mala_id,
            metadata=[
                MantraMetadataInput(
                    mantra="Om mani padme hum",
                    language=LanguageCode.EN,
                )
            ],
        )

        with pytest.raises(HTTPException) as exc_info:
            create_mantra_service(token="token", request=request)

        assert exc_info.value.status_code == 400
        assert str(mala_id) in exc_info.value.detail

    @patch("pecha_api.mantra.mantra_service.validate_cms_author_details")
    @patch("pecha_api.mantra.mantra_service.SessionLocal")
    @patch("pecha_api.mantra.mantra_service.save_mantra")
    def test_create_mantra_service_sets_deity_image_key(
        self,
        mock_save_mantra,
        mock_session,
        mock_validate_auth,
    ):
        """deity_image_key on the request lands on the Mantra row passed to save_mantra."""
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        def _fake_save(db, mantra, metadata):
            mantra.id = uuid4()
            mantra.metadata_entries = []
            return mantra

        mock_save_mantra.side_effect = _fake_save

        request = CreateMantraRequest(
            deity_image_key="images/mantra_images/abc/original/x.webp",
            metadata=[
                MantraMetadataInput(mantra="Om mani padme hum", language=LanguageCode.EN)
            ],
        )

        result = create_mantra_service(token="token", request=request)

        saved_mantra = mock_save_mantra.call_args[0][1]
        assert saved_mantra.deity_image == "images/mantra_images/abc/original/x.webp"
        assert isinstance(result, CMSMantraDTO)
        assert result.deity_image_key == "images/mantra_images/abc/original/x.webp"


class TestUpdateMantraService:
    @patch("pecha_api.mantra.mantra_service.validate_cms_author_details")
    @patch("pecha_api.mantra.mantra_service.SessionLocal")
    @patch("pecha_api.mantra.mantra_service.get_mantra_by_id")
    def test_update_mantra_service_sets_key(self, mock_get_mantra, mock_session, mock_validate_auth):
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mantra_id = uuid4()

        mantra = MagicMock()
        mantra.id = mantra_id
        mantra.metadata_entries = []
        mantra.mala = None
        mantra.audio_url = None
        mock_get_mantra.side_effect = [mantra, mantra]

        request = UpdateMantraRequest(deity_image_key="images/mantra_images/x/original/y.webp")
        result = update_mantra_service(token="token", mantra_id=mantra_id, request=request)

        assert mantra.deity_image == "images/mantra_images/x/original/y.webp"
        assert isinstance(result, CMSMantraDTO)
        mock_validate_auth.assert_called_once_with(token="token")
        mock_db.commit.assert_called_once()

    @patch("pecha_api.mantra.mantra_service.validate_cms_author_details")
    @patch("pecha_api.mantra.mantra_service.SessionLocal")
    @patch("pecha_api.mantra.mantra_service.get_mantra_by_id")
    def test_update_mantra_service_clears_key(self, mock_get_mantra, mock_session, mock_validate_auth):
        """Passing deity_image_key: null clears a previously set image."""
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mantra_id = uuid4()

        mantra = MagicMock()
        mantra.id = mantra_id
        mantra.metadata_entries = []
        mantra.mala = None
        mantra.audio_url = None
        mantra.deity_image = "images/mantra_images/x/original/old.webp"
        mock_get_mantra.side_effect = [mantra, mantra]

        request = UpdateMantraRequest(deity_image_key=None)
        update_mantra_service(token="token", mantra_id=mantra_id, request=request)

        assert mantra.deity_image is None

    @patch("pecha_api.mantra.mantra_service.validate_cms_author_details")
    @patch("pecha_api.mantra.mantra_service.SessionLocal")
    @patch("pecha_api.mantra.mantra_service.get_mantra_by_id")
    def test_update_mantra_service_not_found(self, mock_get_mantra, mock_session, mock_validate_auth):
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get_mantra.return_value = None

        request = UpdateMantraRequest(deity_image_key="some-key")

        with pytest.raises(HTTPException) as exc_info:
            update_mantra_service(token="token", mantra_id=uuid4(), request=request)

        assert exc_info.value.status_code == 404


class TestUploadMantraImage:
    @patch("pecha_api.mantra.mantra_service.prepare_image_upload")
    @patch("pecha_api.mantra.mantra_service.validate_file")
    @patch("pecha_api.mantra.mantra_service.SessionLocal")
    @patch("pecha_api.mantra.mantra_service.get_mantra_by_id")
    @patch("pecha_api.mantra.mantra_service.validate_cms_author_details")
    def test_upload_mantra_image_success(
        self, mock_validate_auth, mock_get_mantra, mock_session, mock_validate_file, mock_prepare_upload
    ):
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mantra_id = uuid4()
        mock_get_mantra.return_value = MagicMock(id=mantra_id)

        expected_image = ImageUrlModel(thumbnail="t", medium="m", original="o")
        mock_prepare_upload.return_value = (expected_image, "images/mantra_images/x/original/y.webp")

        fake_file = MagicMock()
        result = upload_mantra_image(token="token", mantra_id=mantra_id, file=fake_file)

        assert isinstance(result, PlanUploadResponse)
        assert result.image is expected_image
        assert result.key == "images/mantra_images/x/original/y.webp"
        assert result.path.startswith(f"images/mantra_images/{mantra_id}/")
        mock_validate_auth.assert_called_once_with(token="token")
        mock_validate_file.assert_called_once_with(fake_file)

    @patch("pecha_api.mantra.mantra_service.validate_file")
    @patch("pecha_api.mantra.mantra_service.SessionLocal")
    @patch("pecha_api.mantra.mantra_service.get_mantra_by_id")
    @patch("pecha_api.mantra.mantra_service.validate_cms_author_details")
    def test_upload_mantra_image_mantra_not_found(
        self, mock_validate_auth, mock_get_mantra, mock_session, mock_validate_file
    ):
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get_mantra.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            upload_mantra_image(token="token", mantra_id=uuid4(), file=MagicMock())

        assert exc_info.value.status_code == 404

    @patch("pecha_api.mantra.mantra_service.validate_cms_author_details")
    def test_upload_mantra_image_rejects_inactive_author(self, mock_validate_auth):
        """Upload must use the same active-author check as create/update, not
        just token validation - an inactive author should be rejected here too."""
        mock_validate_auth.side_effect = HTTPException(
            status_code=403,
            detail="Author is not active",
        )

        with pytest.raises(HTTPException) as exc_info:
            upload_mantra_image(token="token", mantra_id=uuid4(), file=MagicMock())

        assert exc_info.value.status_code == 403
