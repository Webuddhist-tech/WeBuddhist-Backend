from typing import Any
from unittest.mock import patch, MagicMock, AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from pecha_api.app import api
from pecha_api.accumulator.accumulator_enums import AccumulatorType
from pecha_api.accumulator.accumulator_response_models import (
    AccumulatorMetadataDTO,
    CreatePresetAccumulatorRequest,
    UpdatePresetAccumulatorRequest,
    PublicAccumulatorDTO,
    PublicAccumulatorsResponse,
)
from pecha_api.accumulator.accumulator_cms_service import (
    create_preset_accumulator_cms_service,
    update_preset_accumulator_cms_service,
    delete_preset_accumulator_cms_service,
    get_preset_accumulator_cms_service,
    list_preset_accumulators_cms_service,
    _to_public_dto,
    _validate_optional_mala_image,
)
from pecha_api.plans.plans_enums import LanguageCode

client = TestClient(api)


def _sample_public_dto(**overrides: Any) -> PublicAccumulatorDTO:
    data = {
        "id": uuid4(),
        "group_id": None,
        "type": AccumulatorType.PRESET,
        "target_count": 100000,
        "current_count": 0,
        "text_id": "OPE1A2B3C4",
        "mantra": None,
        "mala_image_id": None,
        "mala_image_url": None,
        "metadata": [
            AccumulatorMetadataDTO(
                language=LanguageCode.EN,
                name="Chenrezig Practice",
                description="Compassion practice",
            )
        ],
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": None,
    }
    data.update(overrides)
    return PublicAccumulatorDTO(**data)


class TestCmsPresetViews:
    @patch("pecha_api.accumulator.accumulator_cms_views.create_preset_accumulator_cms_service")
    def test_create_preset_success(self, mock_service):
        sample = _sample_public_dto()
        mock_service.return_value = sample
        payload = {
            "target_count": 100000,
            "text_id": sample.text_id,
            "mantra_id": str(uuid4()),
            "metadata": [
                {"language": "EN", "name": "Chenrezig Practice", "description": "Compassion practice"}
            ],
        }

        response = client.post(
            "/api/v1/cms/accumulators/presets",
            json=payload,
            headers={"Authorization": "Bearer dummy"},
        )

        assert response.status_code == 201
        assert response.json()["id"] == str(sample.id)
        mock_service.assert_called_once()

    def test_create_preset_requires_auth(self):
        response = client.post(
            "/api/v1/cms/accumulators/presets",
            json={
                "metadata": [{"language": "EN", "name": "Test"}],
            },
        )
        assert response.status_code == 403

    def test_create_preset_rejects_empty_metadata(self):
        response = client.post(
            "/api/v1/cms/accumulators/presets",
            json={"metadata": []},
            headers={"Authorization": "Bearer dummy"},
        )
        assert response.status_code == 422

    @patch("pecha_api.accumulator.accumulator_cms_views.list_preset_accumulators_cms_service")
    def test_list_presets_success(self, mock_service):
        sample = _sample_public_dto()
        mock_service.return_value = PublicAccumulatorsResponse(
            accumulators=[sample],
            total=1,
            skip=0,
            limit=20,
        )

        response = client.get(
            "/api/v1/cms/accumulators/presets?search=chen",
            headers={"Authorization": "Bearer dummy"},
        )

        assert response.status_code == 200
        assert response.json()["total"] == 1
        mock_service.assert_called_once()

    @patch("pecha_api.accumulator.accumulator_cms_views.get_preset_accumulator_cms_service")
    def test_get_preset_success(self, mock_service):
        sample = _sample_public_dto()
        mock_service.return_value = sample

        response = client.get(
            f"/api/v1/cms/accumulators/presets/{sample.id}",
            headers={"Authorization": "Bearer dummy"},
        )

        assert response.status_code == 200
        assert response.json()["id"] == str(sample.id)

    @patch("pecha_api.accumulator.accumulator_cms_views.update_preset_accumulator_cms_service")
    def test_update_preset_success(self, mock_service):
        sample = _sample_public_dto(target_count=200000)
        mock_service.return_value = sample

        response = client.put(
            f"/api/v1/cms/accumulators/presets/{sample.id}",
            json={"target_count": 200000},
            headers={"Authorization": "Bearer dummy"},
        )

        assert response.status_code == 200
        assert response.json()["target_count"] == 200000

    @patch("pecha_api.accumulator.accumulator_cms_views.delete_preset_accumulator_cms_service")
    def test_delete_preset_success(self, mock_service):
        preset_id = uuid4()
        mock_service.return_value = None

        response = client.delete(
            f"/api/v1/cms/accumulators/presets/{preset_id}",
            headers={"Authorization": "Bearer dummy"},
        )

        assert response.status_code == 204
        mock_service.assert_called_once()


class TestCmsPresetService:
    @pytest.mark.asyncio
    @patch("pecha_api.accumulator.accumulator_cms_service.validate_cms_author_details")
    @patch("pecha_api.accumulator.accumulator_cms_service.SessionLocal")
    @patch("pecha_api.accumulator.accumulator_cms_service.validate_mantra_exists")
    @patch("pecha_api.accumulator.accumulator_cms_service.save_accumulator")
    @patch("pecha_api.accumulator.accumulator_cms_service._to_public_dto")
    async def test_create_preset_service_success(
        self,
        mock_to_dto,
        mock_save,
        mock_validate_mantra,
        mock_session,
        mock_validate_auth,
    ):
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        saved = MagicMock()
        mock_save.return_value = saved
        expected = _sample_public_dto()
        mock_to_dto.return_value = expected

        text_id = "OPE1A2B3C4"
        mantra_id = uuid4()
        request = CreatePresetAccumulatorRequest(
            target_count=108000,
            text_id=text_id,
            mantra_id=mantra_id,
            metadata=[
                AccumulatorMetadataDTO(
                    language=LanguageCode.EN,
                    name="Mani Practice",
                )
            ],
        )

        result = await create_preset_accumulator_cms_service(token="token", request=request)

        assert result is expected
        mock_validate_auth.assert_called_once_with(token="token")
        mock_validate_mantra.assert_called_once_with(mock_db, mantra_id)
        mock_save.assert_called_once()
        saved_preset = mock_save.call_args.args[1]
        assert saved_preset.text_id == text_id

    @pytest.mark.asyncio
    @patch("pecha_api.accumulator.accumulator_cms_service.validate_cms_author_details")
    @patch("pecha_api.accumulator.accumulator_cms_service.SessionLocal")
    @patch("pecha_api.accumulator.accumulator_cms_service.get_preset_by_id")
    async def test_update_preset_not_found(
        self,
        mock_get_preset,
        mock_session,
        mock_validate_auth,
    ):
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get_preset.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await update_preset_accumulator_cms_service(
                token="token",
                preset_id=uuid4(),
                request=UpdatePresetAccumulatorRequest(target_count=1),
            )

        assert exc_info.value.status_code == 404

    @patch("pecha_api.accumulator.accumulator_cms_service.validate_cms_author_details")
    @patch("pecha_api.accumulator.accumulator_cms_service.SessionLocal")
    @patch("pecha_api.accumulator.accumulator_cms_service.get_preset_by_id")
    @patch("pecha_api.accumulator.accumulator_cms_service.delete_accumulator")
    def test_delete_preset_service_success(
        self,
        mock_delete,
        mock_get_preset,
        mock_session,
        mock_validate_auth,
    ):
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        preset = MagicMock()
        preset.type = AccumulatorType.PRESET
        mock_get_preset.return_value = preset

        delete_preset_accumulator_cms_service(token="token", preset_id=uuid4())

        mock_delete.assert_called_once_with(mock_db, preset)

    @patch("pecha_api.accumulator.accumulator_cms_service.validate_cms_author_details")
    @patch("pecha_api.accumulator.accumulator_cms_service.SessionLocal")
    @patch("pecha_api.accumulator.accumulator_cms_service.get_preset_by_id")
    def test_get_preset_service_not_found(
        self,
        mock_get_preset,
        mock_session,
        mock_validate_auth,
    ):
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get_preset.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            get_preset_accumulator_cms_service(token="token", preset_id=uuid4())

        assert exc_info.value.status_code == 404

    @patch("pecha_api.accumulator.accumulator_cms_service.validate_cms_author_details")
    @patch("pecha_api.accumulator.accumulator_cms_service.SessionLocal")
    @patch("pecha_api.accumulator.accumulator_cms_service.get_all_accumulators")
    @patch("pecha_api.accumulator.accumulator_cms_service.get_mantras_by_ids")
    def test_list_presets_service_success(
        self,
        mock_get_mantras,
        mock_get_all,
        mock_session,
        mock_validate_auth,
    ):
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get_all.return_value = ([], 0)
        mock_get_mantras.return_value = {}

        result = list_preset_accumulators_cms_service(token="token", skip=0, limit=20)

        assert result.total == 0
        assert result.accumulators == []
        mock_validate_auth.assert_called_once_with(token="token")

    @patch("pecha_api.accumulator.accumulator_cms_service.validate_cms_author_details")
    @patch("pecha_api.accumulator.accumulator_cms_service.SessionLocal")
    @patch("pecha_api.accumulator.accumulator_cms_service.get_preset_by_id")
    @patch("pecha_api.accumulator.accumulator_cms_service._to_public_dto")
    def test_get_preset_service_success(
        self,
        mock_to_dto,
        mock_get_preset,
        mock_session,
        mock_validate_auth,
    ):
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        preset = MagicMock()
        mock_get_preset.return_value = preset
        expected = _sample_public_dto()
        mock_to_dto.return_value = expected

        result = get_preset_accumulator_cms_service(
            token="token",
            preset_id=uuid4(),
            language="en",
        )

        assert result is expected
        mock_to_dto.assert_called_once_with(mock_db, preset, language="en")

    @pytest.mark.asyncio
    @patch("pecha_api.accumulator.accumulator_cms_service.validate_cms_author_details")
    @patch("pecha_api.accumulator.accumulator_cms_service.SessionLocal")
    @patch("pecha_api.accumulator.accumulator_cms_service.validate_mantra_exists")
    @patch("pecha_api.accumulator.accumulator_cms_service.get_mala_image_by_id")
    @patch("pecha_api.accumulator.accumulator_cms_service.get_preset_by_id")
    @patch("pecha_api.accumulator.accumulator_cms_service.update_accumulator")
    @patch("pecha_api.accumulator.accumulator_cms_service._to_public_dto")
    async def test_update_preset_service_success(
        self,
        mock_to_dto,
        mock_update,
        mock_get_preset,
        mock_get_mala,
        mock_validate_mantra,
        mock_session,
        mock_validate_auth,
    ):
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        preset = MagicMock()
        preset.type = AccumulatorType.PRESET
        preset.metadata_entries = MagicMock()
        mock_get_preset.return_value = preset
        mock_get_mala.return_value = MagicMock()
        updated = MagicMock()
        mock_update.return_value = updated
        expected = _sample_public_dto(target_count=200000)
        mock_to_dto.return_value = expected

        text_id = "OPE1A2B3C4"
        mantra_id = uuid4()
        mala_image_id = uuid4()
        request = UpdatePresetAccumulatorRequest(
            target_count=200000,
            text_id=text_id,
            mantra_id=mantra_id,
            mala_image_id=mala_image_id,
            metadata=[
                AccumulatorMetadataDTO(
                    language=LanguageCode.EN,
                    name="Updated Practice",
                    description="Updated description",
                )
            ],
        )

        result = await update_preset_accumulator_cms_service(
            token="token",
            preset_id=uuid4(),
            request=request,
        )

        assert result is expected
        assert preset.target_count == 200000
        assert preset.text_id == text_id
        assert preset.mantra_id == mantra_id
        assert preset.mala_image == mala_image_id
        mock_validate_mantra.assert_called_once_with(mock_db, mantra_id)
        mock_get_mala.assert_called_once_with(mock_db, mala_image_id)
        preset.metadata_entries.clear.assert_called_once()
        preset.metadata_entries.extend.assert_called_once()
        mock_update.assert_called_once_with(mock_db, preset)

    @pytest.mark.asyncio
    @patch("pecha_api.accumulator.accumulator_cms_service.validate_cms_author_details")
    @patch("pecha_api.accumulator.accumulator_cms_service.SessionLocal")
    @patch("pecha_api.accumulator.accumulator_cms_service.get_preset_by_id")
    async def test_update_preset_rejects_non_preset_type(
        self,
        mock_get_preset,
        mock_session,
        mock_validate_auth,
    ):
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        preset = MagicMock()
        preset.type = AccumulatorType.USER
        mock_get_preset.return_value = preset

        with pytest.raises(HTTPException) as exc_info:
            await update_preset_accumulator_cms_service(
                token="token",
                preset_id=uuid4(),
                request=UpdatePresetAccumulatorRequest(target_count=1),
            )

        assert exc_info.value.status_code == 403

    @patch("pecha_api.accumulator.accumulator_cms_service.validate_cms_author_details")
    @patch("pecha_api.accumulator.accumulator_cms_service.SessionLocal")
    @patch("pecha_api.accumulator.accumulator_cms_service.get_preset_by_id")
    def test_delete_preset_not_found(
        self,
        mock_get_preset,
        mock_session,
        mock_validate_auth,
    ):
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get_preset.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            delete_preset_accumulator_cms_service(token="token", preset_id=uuid4())

        assert exc_info.value.status_code == 404

    @patch("pecha_api.accumulator.accumulator_cms_service.validate_cms_author_details")
    @patch("pecha_api.accumulator.accumulator_cms_service.SessionLocal")
    @patch("pecha_api.accumulator.accumulator_cms_service.get_preset_by_id")
    def test_delete_preset_rejects_non_preset_type(
        self,
        mock_get_preset,
        mock_session,
        mock_validate_auth,
    ):
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        preset = MagicMock()
        preset.type = "USER"
        mock_get_preset.return_value = preset

        with pytest.raises(HTTPException) as exc_info:
            delete_preset_accumulator_cms_service(token="token", preset_id=uuid4())

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    @patch("pecha_api.accumulator.accumulator_cms_service.validate_cms_author_details")
    @patch("pecha_api.accumulator.accumulator_cms_service.SessionLocal")
    @patch("pecha_api.accumulator.accumulator_cms_service.get_mala_image_by_id")
    @patch("pecha_api.accumulator.accumulator_cms_service.save_accumulator")
    async def test_create_preset_mala_image_not_found(
        self,
        mock_save,
        mock_get_mala,
        mock_session,
        mock_validate_auth,
    ):
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get_mala.return_value = None

        request = CreatePresetAccumulatorRequest(
            mala_image_id=uuid4(),
            metadata=[
                AccumulatorMetadataDTO(language=LanguageCode.EN, name="Practice")
            ],
        )

        with pytest.raises(HTTPException) as exc_info:
            await create_preset_accumulator_cms_service(token="token", request=request)

        assert exc_info.value.status_code == 404
        mock_save.assert_not_called()

    @patch("pecha_api.accumulator.accumulator_cms_service.get_mantras_by_ids")
    @patch("pecha_api.accumulator.accumulator_cms_service.convert_accumulator_to_public_dto")
    def test_to_public_dto_loads_mantra_when_present(self, mock_convert, mock_get_mantras):
        db = MagicMock()
        mantra_id = uuid4()
        accumulator = MagicMock()
        accumulator.mantra_id = mantra_id
        mantras = {mantra_id: MagicMock()}
        mock_get_mantras.return_value = mantras
        expected = _sample_public_dto()
        mock_convert.return_value = expected

        result = _to_public_dto(db, accumulator, language="bo")

        assert result is expected
        mock_get_mantras.assert_called_once_with(db, [mantra_id])
        mock_convert.assert_called_once_with(
            accumulator,
            mantras_by_id=mantras,
            language="bo",
            include_key=True,
        )

    @patch("pecha_api.accumulator.accumulator_cms_service.get_mantras_by_ids")
    @patch("pecha_api.accumulator.accumulator_cms_service.convert_accumulator_to_public_dto")
    def test_to_public_dto_skips_mantra_lookup_when_absent(self, mock_convert, mock_get_mantras):
        db = MagicMock()
        accumulator = MagicMock()
        accumulator.mantra_id = None
        expected = _sample_public_dto()
        mock_convert.return_value = expected

        result = _to_public_dto(db, accumulator)

        assert result is expected
        mock_get_mantras.assert_not_called()
        mock_convert.assert_called_once_with(
            accumulator,
            mantras_by_id={},
            language=None,
            include_key=True,
        )

    @patch("pecha_api.accumulator.accumulator_cms_service.get_mala_image_by_id")
    def test_validate_optional_mala_image_noop_when_none(self, mock_get_mala):
        _validate_optional_mala_image(MagicMock(), None)
        mock_get_mala.assert_not_called()

    @patch("pecha_api.accumulator.accumulator_cms_service.get_mala_image_by_id")
    def test_validate_optional_mala_image_success(self, mock_get_mala):
        db = MagicMock()
        mala_id = uuid4()
        mock_get_mala.return_value = MagicMock()

        _validate_optional_mala_image(db, mala_id)

        mock_get_mala.assert_called_once_with(db, mala_id)

    def test_create_request_rejects_duplicate_metadata_languages(self):
        with pytest.raises(ValidationError, match="metadata languages must be unique"):
            CreatePresetAccumulatorRequest(
                metadata=[
                    AccumulatorMetadataDTO(language=LanguageCode.EN, name="One"),
                    AccumulatorMetadataDTO(language=LanguageCode.EN, name="Two"),
                ]
            )

    def test_create_request_rejects_empty_metadata_name(self):
        with pytest.raises(ValidationError, match="metadata name must not be empty"):
            CreatePresetAccumulatorRequest(
                metadata=[
                    AccumulatorMetadataDTO(language=LanguageCode.EN, name="   "),
                ]
            )

    def test_update_request_allows_none_metadata(self):
        request = UpdatePresetAccumulatorRequest(target_count=108)
        assert request.metadata is None

    def test_update_request_rejects_duplicate_metadata_languages(self):
        with pytest.raises(ValidationError, match="metadata languages must be unique"):
            UpdatePresetAccumulatorRequest(
                metadata=[
                    AccumulatorMetadataDTO(language=LanguageCode.EN, name="One"),
                    AccumulatorMetadataDTO(language=LanguageCode.EN, name="Two"),
                ]
            )
