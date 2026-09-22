import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from uuid import uuid4
from datetime import datetime
from fastapi import HTTPException
from starlette import status

from pecha_api.accumulator.accumulator_service import (
    get_all_accumulators_service,
    get_user_accumulators_service,
    create_accumulator_service,
    update_accumulator_service,
    delete_accumulator_service,
    get_accumulator_history_service,
    get_accumulator_detail_service,
    update_mala_image_service,
    get_accumulator_groups_service,
    convert_accumulator_to_dto,
    convert_accumulator_to_public_dto,
    build_preset_mantra_dto,
    generate_mala_image_presigned_url,
    resolve_accumulator_bookmark_mala_image_url,
    _create_accumulator_from_preset,
    is_user_created_accumulator,
    validate_mantra_exists,
)
from pecha_api.accumulator.accumulator_response_models import (
    AccumulatorsResponse,
    PublicAccumulatorsResponse,
    AccumulatorDTO,
    PublicAccumulatorDTO,
    PresetMantraDTO,
    CMSPresetMantraDTO,
    CreateAccumulatorRequest,
    UpdateAccumulatorRequest,
    UpdateMalaImageRequest,
    AccumulatorHistoryResponse,
    AccumulatorHistoryDTO,
    AccumulatorGroupDTO,
    AccumulatorGroupsResponse,
)
from pecha_api.accumulator.accumulator_models import Accumulator
from pecha_api.accumulator.accumulator_history_model import AccumulatorHistory
from pecha_api.accumulator.accumulator_enums import AccumulatorType
from pecha_api.mantra.mantra_model import Mantra
from pecha_api.mantra.mantra_metadata_model import MantraMetadata
from pecha_api.plans.media.media_response_models import ImageUrlModel


from pecha_api.plans.plans_enums import LanguageCode


class TestDataFactory:
    """Factory for creating test data objects."""

    @staticmethod
    def create_mock_mantra_metadata(
        mantra="Om Mani Padme Hum",
        title="The jewel in the lotus",
        pronunciation="om mani padme hum",
        language=LanguageCode.EN,
    ):
        entry = MagicMock(spec=MantraMetadata)
        entry.mantra = mantra
        entry.title = title
        entry.pronunciation = pronunciation
        entry.language = language
        return entry

    @staticmethod
    def create_mock_mantra(
        mantra_id=None,
        audio_url="audio/mantra.mp3",
        metadata_entries=None,
        mala=None,
        deity_image=None,
    ):
        mantra = MagicMock(spec=Mantra)
        mantra.id = mantra_id or uuid4()
        mantra.audio_url = audio_url
        if metadata_entries is None:
            metadata_entries = [TestDataFactory.create_mock_mantra_metadata()]
        mantra.metadata_entries = metadata_entries
        mantra.mala = mala
        mantra.deity_image = deity_image
        return mantra

    @staticmethod
    def create_mock_metadata(name="Test Accumulator", description=None, language="EN"):
        """Create a mock AccumulatorMetadata row (per-language name/description)."""
        metadata = MagicMock()
        metadata.id = uuid4()
        metadata.name = name
        metadata.description = description
        lang = MagicMock()
        lang.value = language
        metadata.language = lang
        return metadata

    @staticmethod
    def create_mock_accumulator(
        accumulator_id=None,
        user_id=None,
        group_id=None,
        parent_id=None,
        accumulator_type=AccumulatorType.USER,
        name="Test Accumulator",
        description=None,
        target_count=108,
        current_count=0,
        text_id=None,
        mantra_id=None,
        mala=None,
        metadata_entries=None,
    ):
        """Create a mock Accumulator model. name/description are placed on a
        single (EN) metadata row unless metadata_entries is given explicitly.
        The chosen mala image (relationship) lives on the accumulator."""
        accumulator = MagicMock(spec=Accumulator)
        accumulator.id = accumulator_id or uuid4()
        accumulator.user_id = user_id or uuid4()
        accumulator.group_id = group_id
        accumulator.parent_id = parent_id
        accumulator.type = accumulator_type
        accumulator.target_count = target_count
        accumulator.current_count = current_count
        accumulator.text_id = text_id
        accumulator.mantra_id = mantra_id
        accumulator.mala = mala
        accumulator.mala_image = mala.id if mala is not None else None
        if metadata_entries is None:
            metadata_entries = [
                TestDataFactory.create_mock_metadata(name=name, description=description)
            ]
        accumulator.metadata_entries = metadata_entries
        accumulator.created_at = datetime.utcnow()
        accumulator.updated_at = datetime.utcnow()
        return accumulator

    @staticmethod
    def create_mock_user(user_id=None):
        """Create a mock user."""
        user = MagicMock()
        user.id = user_id or uuid4()
        user.email = "test@example.com"
        return user

    @staticmethod
    def create_accumulator_request(preset_id=None) -> CreateAccumulatorRequest:
        """Create a CreateAccumulatorRequest referencing a preset."""
        return CreateAccumulatorRequest(parent_id=preset_id or uuid4())

    @staticmethod
    def create_update_request(
        target_count=None,
        current_count=None,
        text_id=None,
        mantra_id=None,
    ) -> UpdateAccumulatorRequest:
        """Create an UpdateAccumulatorRequest."""
        return UpdateAccumulatorRequest(
            target_count=target_count,
            current_count=current_count,
            text_id=text_id,
            mantra_id=mantra_id,
        )

    @staticmethod
    def create_mock_history(
        accumulator_id=None,
        user_id=None,
        count=10,
    ):
        """Create a mock AccumulatorHistory model."""
        history = MagicMock(spec=AccumulatorHistory)
        history.accumulator_id = accumulator_id or uuid4()
        history.user_id = user_id or uuid4()
        history.count = count
        history.created_at = datetime.utcnow()
        return history


class TestGetAllAccumulatorsService:
    """Test cases for get_all_accumulators_service function."""

    @patch('pecha_api.accumulator.accumulator_service.get_mantras_by_ids')
    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.get_all_accumulators')
    def test_get_all_accumulators_service_success(self, mock_get_all, mock_session, mock_get_mantras):
        """Test successful retrieval of all accumulators."""
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        acc1 = TestDataFactory.create_mock_accumulator(name="Acc 1")
        acc2 = TestDataFactory.create_mock_accumulator(name="Acc 2")
        mock_get_all.return_value = ([acc1, acc2], 2)
        mock_get_mantras.return_value = {}

        result = get_all_accumulators_service(skip=0, limit=20)

        assert isinstance(result, PublicAccumulatorsResponse)
        assert len(result.accumulators) == 2
        assert result.total == 2
        assert result.skip == 0
        assert result.limit == 20
        # Public DTO must not expose user_id
        assert isinstance(result.accumulators[0], PublicAccumulatorDTO)
        assert not hasattr(result.accumulators[0], "user_id")

        mock_get_all.assert_called_once_with(mock_db, 0, 20, search=None, show_recitations=False)
        mock_get_mantras.assert_called_once_with(mock_db, [])

    @patch('pecha_api.accumulator.accumulator_service.get_mantras_by_ids')
    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.get_all_accumulators')
    def test_get_all_accumulators_service_includes_mantra_detail(
        self, mock_get_all, mock_session, mock_get_mantras
    ):
        """Preset list should embed mantra detail for the requested language."""
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        mantra_id = uuid4()
        mala = MagicMock()
        mala.id = uuid4()
        mala.url = "mala-images/default.png"
        mantra = TestDataFactory.create_mock_mantra(
            mantra_id=mantra_id,
            mala=mala,
            metadata_entries=[
                TestDataFactory.create_mock_mantra_metadata(
                    mantra="Tibetan text",
                    title="Tibetan title",
                    pronunciation="tibetan pronunciation",
                    language=LanguageCode.BO,
                ),
                TestDataFactory.create_mock_mantra_metadata(
                    mantra="English text",
                    title="English title",
                    pronunciation="english pronunciation",
                    language=LanguageCode.EN,
                ),
            ],
        )
        preset = TestDataFactory.create_mock_accumulator(
            name="Preset",
            accumulator_type=AccumulatorType.PRESET,
            mantra_id=mantra_id,
        )
        mock_get_all.return_value = ([preset], 1)
        mock_get_mantras.return_value = {mantra_id: mantra}

        result = get_all_accumulators_service(skip=0, limit=20, language="bo")

        assert result.accumulators[0].mantra.id == mantra_id
        assert result.accumulators[0].mantra.mantra == "Tibetan text"
        assert result.accumulators[0].mantra.title == "Tibetan title"
        assert result.accumulators[0].mantra.pronunciation == "tibetan pronunciation"
        assert result.accumulators[0].mantra.audio_url == mantra.audio_url
        assert result.accumulators[0].mantra.mala_image_id == mala.id
        mock_get_mantras.assert_called_once_with(mock_db, [mantra_id])

    @patch('pecha_api.accumulator.accumulator_service.get_mantras_by_ids')
    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.get_all_accumulators')
    def test_get_all_accumulators_service_empty(self, mock_get_all, mock_session, mock_get_mantras):
        """Test get_all_accumulators_service when no accumulators exist."""
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        mock_get_all.return_value = ([], 0)
        mock_get_mantras.return_value = {}

        result = get_all_accumulators_service(skip=0, limit=20)

        assert len(result.accumulators) == 0
        assert result.total == 0

    @patch('pecha_api.accumulator.accumulator_service.get_mantras_by_ids')
    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.get_all_accumulators')
    def test_get_all_accumulators_service_pagination(self, mock_get_all, mock_session, mock_get_mantras):
        """Test get_all_accumulators_service with custom pagination."""
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        acc1 = TestDataFactory.create_mock_accumulator()
        mock_get_all.return_value = ([acc1], 10)
        mock_get_mantras.return_value = {}

        result = get_all_accumulators_service(skip=5, limit=1)

        assert result.skip == 5
        assert result.limit == 1
        assert result.total == 10

        mock_get_all.assert_called_once_with(mock_db, 5, 1, search=None, show_recitations=False)


class TestGetUserAccumulatorsService:
    """Test cases for get_user_accumulators_service function."""

    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.get_user_accumulators')
    def test_get_user_accumulators_service_success(self, mock_get_user, mock_session):
        """Test successful retrieval of user's accumulators."""
        user_id = uuid4()
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        acc1 = TestDataFactory.create_mock_accumulator(user_id=user_id, name="My Acc 1")
        acc2 = TestDataFactory.create_mock_accumulator(user_id=user_id, name="My Acc 2")
        mock_get_user.return_value = ([acc1, acc2], 2)

        result = get_user_accumulators_service(user_id=user_id, skip=0, limit=20)

        assert isinstance(result, AccumulatorsResponse)
        assert len(result.accumulators) == 2
        assert result.total == 2
        assert result.accumulators[0].user_id == user_id

        mock_get_user.assert_called_once_with(mock_db, user_id, 0, 20)

    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.get_user_accumulators')
    def test_get_user_accumulators_service_empty(self, mock_get_user, mock_session):
        """Test get_user_accumulators_service when user has no accumulators."""
        user_id = uuid4()
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        mock_get_user.return_value = ([], 0)

        result = get_user_accumulators_service(user_id=user_id, skip=0, limit=20)

        assert len(result.accumulators) == 0
        assert result.total == 0

    @patch('pecha_api.accumulator.accumulator_service.get_mantras_by_ids')
    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.get_user_accumulators')
    def test_get_user_accumulators_service_batches_mantras_once(
        self, mock_get_user, mock_session, mock_get_mantras
    ):
        """Mantras for the whole page are fetched in a single batched call,
        not once per accumulator, and deity_image flows through to each DTO."""
        user_id = uuid4()
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        mantra_id = uuid4()
        mantra = TestDataFactory.create_mock_mantra(mantra_id=mantra_id)
        acc1 = TestDataFactory.create_mock_accumulator(user_id=user_id, mantra_id=mantra_id)
        acc2 = TestDataFactory.create_mock_accumulator(user_id=user_id, mantra_id=mantra_id)
        mock_get_user.return_value = ([acc1, acc2], 2)
        mock_get_mantras.return_value = {mantra_id: mantra}

        result = get_user_accumulators_service(user_id=user_id, skip=0, limit=20)

        mock_get_mantras.assert_called_once_with(mock_db, [mantra_id, mantra_id])
        assert len(result.accumulators) == 2


class TestCreateAccumulatorService:
    """Test cases for create_accumulator_service function (preset -> user copy)."""

    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.get_mantra_mala_image_id')
    @patch('pecha_api.accumulator.accumulator_service.commit_accumulator')
    @patch('pecha_api.accumulator.accumulator_service.add_accumulator')
    @patch('pecha_api.accumulator.accumulator_service.get_user_accumulator_by_parent')
    @patch('pecha_api.accumulator.accumulator_service.get_preset_by_id')
    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    def test_create_accumulator_service_success(
        self, mock_validate, mock_get_preset, mock_get_by_parent, mock_add, mock_commit, mock_get_mantra_mala, mock_session
    ):
        """First tap (no existing accumulator for the preset) creates a new row
        whose parent_id links back to the preset."""
        user_id = uuid4()
        preset_id = uuid4()
        group_id = uuid4()
        mantra_id = uuid4()
        token = "valid_token"

        mock_validate.return_value = TestDataFactory.create_mock_user(user_id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get_mantra_mala.return_value = None

        preset = TestDataFactory.create_mock_accumulator(
            accumulator_id=preset_id,
            user_id=None,
            group_id=group_id,
            accumulator_type=AccumulatorType.PRESET,
            name="Refuge Prayer",
            target_count=111111,
            mantra_id=mantra_id,
        )
        mock_get_preset.return_value = preset
        mock_get_by_parent.return_value = None  # nothing exists yet -> create

        request = TestDataFactory.create_accumulator_request(preset_id=preset_id)

        # commit stamps server-side timestamps (as the DB would) and echoes the row.
        def _commit(_db, accumulator):
            accumulator.created_at = datetime.utcnow()
            accumulator.updated_at = datetime.utcnow()
            return accumulator
        mock_commit.side_effect = _commit

        result = create_accumulator_service(token=token, request=request)

        assert isinstance(result, AccumulatorDTO)
        assert result.metadata[0].name == "Refuge Prayer"
        assert result.target_count == 111111
        assert result.type == AccumulatorType.USER
        assert result.user_id == user_id
        assert result.group_id == group_id
        assert result.parent_id == preset_id
        assert result.current_count == 0

        mock_validate.assert_called_once_with(token=token)
        mock_get_preset.assert_called_once_with(mock_db, preset_id)
        mock_get_by_parent.assert_called_once_with(mock_db, user_id, preset_id)
        mock_add.assert_called_once()
        mock_commit.assert_called_once()

    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.add_accumulator')
    @patch('pecha_api.accumulator.accumulator_service.get_user_accumulator_by_parent')
    @patch('pecha_api.accumulator.accumulator_service.get_preset_by_id')
    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    def test_create_accumulator_service_rejects_duplicate(
        self, mock_validate, mock_get_preset, mock_get_by_parent, mock_add, mock_session
    ):
        """Tapping a preset the user already created an accumulator from is
        rejected with 409: no second row, no reset."""
        user_id = uuid4()
        preset_id = uuid4()
        token = "valid_token"

        mock_validate.return_value = TestDataFactory.create_mock_user(user_id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        mock_get_preset.return_value = TestDataFactory.create_mock_accumulator(
            accumulator_id=preset_id, accumulator_type=AccumulatorType.PRESET
        )
        existing = TestDataFactory.create_mock_accumulator(
            user_id=user_id, accumulator_type=AccumulatorType.USER,
            parent_id=preset_id, current_count=540,
        )
        mock_get_by_parent.return_value = existing

        request = TestDataFactory.create_accumulator_request(preset_id=preset_id)

        with pytest.raises(HTTPException) as exc_info:
            create_accumulator_service(token=token, request=request)

        assert exc_info.value.status_code == status.HTTP_409_CONFLICT
        assert existing.current_count == 540  # untouched, no reset
        mock_get_by_parent.assert_called_once_with(mock_db, user_id, preset_id)
        mock_add.assert_not_called()       # no new accumulator created

    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.get_mantra_mala_image_id')
    @patch('pecha_api.accumulator.accumulator_service.add_history_row')
    @patch('pecha_api.accumulator.accumulator_service.commit_accumulator')
    @patch('pecha_api.accumulator.accumulator_service.add_accumulator')
    @patch('pecha_api.accumulator.accumulator_service.get_user_accumulator_by_parent')
    @patch('pecha_api.accumulator.accumulator_service.get_preset_by_id')
    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    def test_create_accumulator_service_no_history_on_create(
        self, mock_validate, mock_get_preset, mock_get_by_parent, mock_add, mock_commit, mock_add_history, mock_get_mantra_mala, mock_session
    ):
        """Creating from a preset starts at count 0 and writes no history row."""
        user_id = uuid4()
        preset_id = uuid4()
        token = "valid_token"

        mock_validate.return_value = TestDataFactory.create_mock_user(user_id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get_mantra_mala.return_value = None
        mock_get_preset.return_value = TestDataFactory.create_mock_accumulator(
            accumulator_id=preset_id, accumulator_type=AccumulatorType.PRESET
        )
        mock_get_by_parent.return_value = None

        def _commit(_db, accumulator):
            accumulator.created_at = datetime.utcnow()
            accumulator.updated_at = datetime.utcnow()
            return accumulator
        mock_commit.side_effect = _commit

        request = TestDataFactory.create_accumulator_request(preset_id=preset_id)
        create_accumulator_service(token=token, request=request)

        mock_add_history.assert_not_called()

    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.get_mantra_mala_image_id')
    @patch('pecha_api.accumulator.accumulator_service.commit_accumulator')
    @patch('pecha_api.accumulator.accumulator_service.add_accumulator')
    @patch('pecha_api.accumulator.accumulator_service.get_user_accumulator_by_parent')
    @patch('pecha_api.accumulator.accumulator_service.get_preset_by_id')
    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    def test_create_accumulator_service_mantra_mala_image_default(
        self, mock_validate, mock_get_preset, mock_get_by_parent, mock_add, mock_commit, mock_get_mantra_mala, mock_session
    ):
        """The new accumulator's mala image defaults to the preset mantra's
        mala image, overriding the preset's own mala image."""
        user_id = uuid4()
        preset_id = uuid4()
        mantra_id = uuid4()
        preset_mala = MagicMock(); preset_mala.id = uuid4()
        mantra_mala_id = uuid4()
        token = "valid_token"

        mock_validate.return_value = TestDataFactory.create_mock_user(user_id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get_mantra_mala.return_value = mantra_mala_id

        preset = TestDataFactory.create_mock_accumulator(
            accumulator_id=preset_id,
            accumulator_type=AccumulatorType.PRESET,
            mantra_id=mantra_id,
            mala=preset_mala,
        )
        mock_get_preset.return_value = preset
        mock_get_by_parent.return_value = None

        captured = {}
        def _add(_db, accumulator):
            captured["accumulator"] = accumulator
            return accumulator
        mock_add.side_effect = _add

        def _commit(_db, accumulator):
            accumulator.created_at = datetime.utcnow()
            accumulator.updated_at = datetime.utcnow()
            return accumulator
        mock_commit.side_effect = _commit

        request = TestDataFactory.create_accumulator_request(preset_id=preset_id)
        create_accumulator_service(token=token, request=request)

        mock_get_mantra_mala.assert_called_once_with(mock_db, mantra_id)
        assert captured["accumulator"].mala_image == mantra_mala_id  # mantra default wins

    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.get_mantra_mala_image_id')
    @patch('pecha_api.accumulator.accumulator_service.commit_accumulator')
    @patch('pecha_api.accumulator.accumulator_service.add_accumulator')
    @patch('pecha_api.accumulator.accumulator_service.get_user_accumulator_by_parent')
    @patch('pecha_api.accumulator.accumulator_service.get_preset_by_id')
    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    def test_create_accumulator_service_falls_back_to_preset_mala_image(
        self, mock_validate, mock_get_preset, mock_get_by_parent, mock_add, mock_commit, mock_get_mantra_mala, mock_session
    ):
        """When the mantra has no mala image, the new accumulator keeps the
        preset's own mala image."""
        user_id = uuid4()
        preset_id = uuid4()
        mantra_id = uuid4()
        preset_mala = MagicMock(); preset_mala.id = uuid4()
        token = "valid_token"

        mock_validate.return_value = TestDataFactory.create_mock_user(user_id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get_mantra_mala.return_value = None  # mantra has no default

        preset = TestDataFactory.create_mock_accumulator(
            accumulator_id=preset_id,
            accumulator_type=AccumulatorType.PRESET,
            mantra_id=mantra_id,
            mala=preset_mala,
        )
        mock_get_preset.return_value = preset
        mock_get_by_parent.return_value = None

        captured = {}
        def _add(_db, accumulator):
            captured["accumulator"] = accumulator
            return accumulator
        mock_add.side_effect = _add

        def _commit(_db, accumulator):
            accumulator.created_at = datetime.utcnow()
            accumulator.updated_at = datetime.utcnow()
            return accumulator
        mock_commit.side_effect = _commit

        request = TestDataFactory.create_accumulator_request(preset_id=preset_id)
        create_accumulator_service(token=token, request=request)

        assert captured["accumulator"].mala_image == preset_mala.id  # preset value retained

    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.get_preset_by_id')
    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    def test_create_accumulator_service_preset_not_found(
        self, mock_validate, mock_get_preset, mock_session
    ):
        """A preset_id that matches no preset raises 404."""
        token = "valid_token"
        mock_validate.return_value = TestDataFactory.create_mock_user()
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get_preset.return_value = None

        request = TestDataFactory.create_accumulator_request(preset_id=uuid4())

        with pytest.raises(HTTPException) as exc_info:
            create_accumulator_service(token=token, request=request)

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    def test_create_accumulator_service_invalid_token(self, mock_validate):
        """Test create_accumulator_service with invalid token."""
        mock_validate.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        )

        request = TestDataFactory.create_accumulator_request()

        with pytest.raises(HTTPException) as exc_info:
            create_accumulator_service(token="invalid_token", request=request)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


class TestUpdateAccumulatorService:
    """Test cases for update_accumulator_service function."""

    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.update_accumulator')
    @patch('pecha_api.accumulator.accumulator_service.get_accumulator_by_id')
    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    @pytest.mark.asyncio
    async def test_update_accumulator_service_success(self, mock_validate, mock_get, mock_update, mock_session):
        """Test successful update of accumulator."""
        user_id = uuid4()
        accumulator_id = uuid4()
        token = "valid_token"

        mock_validate.return_value = TestDataFactory.create_mock_user(user_id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        existing = TestDataFactory.create_mock_accumulator(
            accumulator_id=accumulator_id, user_id=user_id, name="Old Name"
        )
        mock_get.return_value = existing
        mock_update.return_value = existing

        request = TestDataFactory.create_update_request(target_count=200)

        result = await update_accumulator_service(token=token, accumulator_id=accumulator_id, request=request)

        assert isinstance(result, AccumulatorDTO)
        assert existing.target_count == 200
        mock_get.assert_called_once_with(mock_db, accumulator_id)
        mock_update.assert_called_once_with(mock_db, existing)

    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.add_history_row')
    @patch('pecha_api.accumulator.accumulator_service.update_accumulator')
    @patch('pecha_api.accumulator.accumulator_service.get_accumulator_by_id')
    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    @pytest.mark.asyncio
    async def test_update_accumulator_service_records_positive_delta(
        self, mock_validate, mock_get, mock_update, mock_add_history, mock_session
    ):
        """Increasing current_count records the delta in history."""
        user_id = uuid4()
        accumulator_id = uuid4()
        token = "valid_token"

        mock_validate.return_value = TestDataFactory.create_mock_user(user_id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        existing = TestDataFactory.create_mock_accumulator(
            accumulator_id=accumulator_id, user_id=user_id, current_count=100
        )
        mock_get.return_value = existing
        mock_update.return_value = existing

        request = TestDataFactory.create_update_request(current_count=150)

        await update_accumulator_service(token=token, accumulator_id=accumulator_id, request=request)

        assert existing.current_count == 150
        mock_add_history.assert_called_once()
        _, kwargs = mock_add_history.call_args
        assert kwargs["count"] == 50

    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.add_history_row')
    @patch('pecha_api.accumulator.accumulator_service.update_accumulator')
    @patch('pecha_api.accumulator.accumulator_service.get_accumulator_by_id')
    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    @pytest.mark.asyncio
    async def test_update_accumulator_service_no_history_on_decrease(
        self, mock_validate, mock_get, mock_update, mock_add_history, mock_session
    ):
        """Decreasing current_count updates the value but records no history."""
        user_id = uuid4()
        accumulator_id = uuid4()
        token = "valid_token"

        mock_validate.return_value = TestDataFactory.create_mock_user(user_id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        existing = TestDataFactory.create_mock_accumulator(
            accumulator_id=accumulator_id, user_id=user_id, current_count=100
        )
        mock_get.return_value = existing
        mock_update.return_value = existing

        request = TestDataFactory.create_update_request(current_count=40)

        await update_accumulator_service(token=token, accumulator_id=accumulator_id, request=request)

        assert existing.current_count == 40
        mock_add_history.assert_not_called()

    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.get_accumulator_by_id')
    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    @pytest.mark.asyncio
    async def test_update_accumulator_service_not_found(self, mock_validate, mock_get, mock_session):
        """Test update_accumulator_service when accumulator doesn't exist."""
        token = "valid_token"
        mock_validate.return_value = TestDataFactory.create_mock_user()
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get.return_value = None

        request = TestDataFactory.create_update_request()

        with pytest.raises(HTTPException) as exc_info:
            await update_accumulator_service(token=token, accumulator_id=uuid4(), request=request)

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.get_accumulator_by_id')
    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    @pytest.mark.asyncio
    async def test_update_accumulator_service_not_owner(self, mock_validate, mock_get, mock_session):
        """Test update_accumulator_service when user is not the owner."""
        token = "valid_token"
        mock_validate.return_value = TestDataFactory.create_mock_user(user_id=uuid4())
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get.return_value = TestDataFactory.create_mock_accumulator(user_id=uuid4())

        request = TestDataFactory.create_update_request()

        with pytest.raises(HTTPException) as exc_info:
            await update_accumulator_service(token=token, accumulator_id=uuid4(), request=request)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @patch('pecha_api.accumulator.accumulator_service.TextUtils.validate_text_exists', new_callable=AsyncMock)
    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.update_accumulator')
    @patch('pecha_api.accumulator.accumulator_service.get_accumulator_by_id')
    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    @pytest.mark.asyncio
    async def test_update_accumulator_service_updates_text_id(
        self, mock_validate, mock_get, mock_update, mock_session, mock_validate_text
    ):
        """Test update_accumulator_service updates text_id after validation."""
        user_id = uuid4()
        accumulator_id = uuid4()
        text_id = uuid4()
        token = "valid_token"

        mock_validate.return_value = TestDataFactory.create_mock_user(user_id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_validate_text.return_value = None

        existing = TestDataFactory.create_mock_accumulator(
            accumulator_id=accumulator_id, user_id=user_id
        )
        mock_get.return_value = existing
        mock_update.return_value = existing

        request = TestDataFactory.create_update_request(text_id=text_id)
        await update_accumulator_service(token=token, accumulator_id=accumulator_id, request=request)

        assert existing.text_id == str(text_id)
        mock_validate_text.assert_awaited_once_with(text_id=str(text_id))

    @patch('pecha_api.accumulator.accumulator_service.validate_mantra_exists')
    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.update_accumulator')
    @patch('pecha_api.accumulator.accumulator_service.get_accumulator_by_id')
    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    @pytest.mark.asyncio
    async def test_update_accumulator_service_updates_mantra_id(
        self, mock_validate, mock_get, mock_update, mock_session, mock_validate_mantra
    ):
        """Test update_accumulator_service updates mantra_id after validation."""
        user_id = uuid4()
        accumulator_id = uuid4()
        mantra_id = uuid4()
        token = "valid_token"

        mock_validate.return_value = TestDataFactory.create_mock_user(user_id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        existing = TestDataFactory.create_mock_accumulator(
            accumulator_id=accumulator_id, user_id=user_id
        )
        mock_get.return_value = existing
        mock_update.return_value = existing

        request = TestDataFactory.create_update_request(mantra_id=mantra_id)
        await update_accumulator_service(token=token, accumulator_id=accumulator_id, request=request)

        assert existing.mantra_id == mantra_id
        mock_validate_mantra.assert_called_once_with(mock_db, mantra_id)

    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.get_accumulator_by_id')
    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    @pytest.mark.asyncio
    async def test_update_accumulator_service_preset_forbidden(self, mock_validate, mock_get, mock_session):
        """Test update_accumulator_service when trying to update a preset accumulator."""
        user_id = uuid4()
        token = "valid_token"
        mock_validate.return_value = TestDataFactory.create_mock_user(user_id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get.return_value = TestDataFactory.create_mock_accumulator(
            user_id=user_id, accumulator_type=AccumulatorType.PRESET
        )

        request = TestDataFactory.create_update_request()

        with pytest.raises(HTTPException) as exc_info:
            await update_accumulator_service(token=token, accumulator_id=uuid4(), request=request)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    @pytest.mark.asyncio
    async def test_update_accumulator_service_invalid_token(self, mock_validate):
        """Test update_accumulator_service with invalid token."""
        mock_validate.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        )

        request = TestDataFactory.create_update_request()

        with pytest.raises(HTTPException) as exc_info:
            await update_accumulator_service(token="invalid_token", accumulator_id=uuid4(), request=request)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


class TestUpdateMalaImageService:
    """Test cases for update_mala_image_service (one image per accumulator,
    no language)."""

    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.update_accumulator')
    @patch('pecha_api.accumulator.accumulator_service.get_mala_image_by_id')
    @patch('pecha_api.accumulator.accumulator_service.get_accumulator_by_id')
    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    def test_update_mala_image_service_success(
        self, mock_validate, mock_get_accumulator, mock_get_mala, mock_update, mock_session
    ):
        """Sets the chosen mala image directly on the accumulator."""
        user_id = uuid4()
        accumulator_id = uuid4()
        mala_id = uuid4()
        token = "valid_token"

        mock_validate.return_value = TestDataFactory.create_mock_user(user_id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        accumulator = TestDataFactory.create_mock_accumulator(
            accumulator_id=accumulator_id, user_id=user_id
        )
        mock_get_accumulator.return_value = accumulator
        mala = MagicMock(); mala.id = mala_id; mala.url = "accumulator/mala/x.png"
        mock_get_mala.return_value = mala
        accumulator.mala = mala  # so the returned DTO reflects the new image
        mock_update.side_effect = lambda _db, acc: acc

        request = UpdateMalaImageRequest(mala_image_id=mala_id)
        result = update_mala_image_service(token=token, accumulator_id=accumulator_id, request=request)

        assert accumulator.mala_image == mala_id  # written on the accumulator
        assert result.mala_image_id == mala_id
        mock_update.assert_called_once()

    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.get_accumulator_by_id')
    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    def test_update_mala_image_service_accumulator_not_found(
        self, mock_validate, mock_get_accumulator, mock_session
    ):
        mock_validate.return_value = TestDataFactory.create_mock_user()
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get_accumulator.return_value = None

        request = UpdateMalaImageRequest(mala_image_id=uuid4())
        with pytest.raises(HTTPException) as exc_info:
            update_mala_image_service(token="valid_token", accumulator_id=uuid4(), request=request)

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.get_accumulator_by_id')
    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    def test_update_mala_image_service_forbidden_for_other_user(
        self, mock_validate, mock_get_accumulator, mock_session
    ):
        mock_validate.return_value = TestDataFactory.create_mock_user(user_id=uuid4())
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get_accumulator.return_value = TestDataFactory.create_mock_accumulator(
            user_id=uuid4()  # different owner
        )

        request = UpdateMalaImageRequest(mala_image_id=uuid4())
        with pytest.raises(HTTPException) as exc_info:
            update_mala_image_service(token="valid_token", accumulator_id=uuid4(), request=request)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.get_mala_image_by_id')
    @patch('pecha_api.accumulator.accumulator_service.get_accumulator_by_id')
    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    def test_update_mala_image_service_mala_not_found(
        self, mock_validate, mock_get_accumulator, mock_get_mala, mock_session
    ):
        user_id = uuid4()
        mock_validate.return_value = TestDataFactory.create_mock_user(user_id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get_accumulator.return_value = TestDataFactory.create_mock_accumulator(user_id=user_id)
        mock_get_mala.return_value = None  # catalog miss

        request = UpdateMalaImageRequest(mala_image_id=uuid4())
        with pytest.raises(HTTPException) as exc_info:
            update_mala_image_service(token="valid_token", accumulator_id=uuid4(), request=request)

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


class TestDeleteAccumulatorService:
    """Test cases for delete_accumulator_service function."""

    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.delete_accumulator')
    @patch('pecha_api.accumulator.accumulator_service.get_accumulator_by_id')
    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    def test_delete_accumulator_service_success(self, mock_validate, mock_get, mock_delete, mock_session):
        """Test successful deletion of accumulator."""
        user_id = uuid4()
        accumulator_id = uuid4()
        token = "valid_token"

        mock_validate.return_value = TestDataFactory.create_mock_user(user_id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        existing = TestDataFactory.create_mock_accumulator(accumulator_id=accumulator_id, user_id=user_id)
        mock_get.return_value = existing

        result = delete_accumulator_service(token=token, accumulator_id=accumulator_id)

        assert result is None
        mock_get.assert_called_once_with(mock_db, accumulator_id)
        mock_delete.assert_called_once_with(mock_db, existing)

    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.get_accumulator_by_id')
    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    def test_delete_accumulator_service_not_found(self, mock_validate, mock_get, mock_session):
        """Test delete_accumulator_service when accumulator doesn't exist."""
        token = "valid_token"
        mock_validate.return_value = TestDataFactory.create_mock_user()
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            delete_accumulator_service(token=token, accumulator_id=uuid4())

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.get_accumulator_by_id')
    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    def test_delete_accumulator_service_not_owner(self, mock_validate, mock_get, mock_session):
        """Test delete_accumulator_service when user is not the owner."""
        token = "valid_token"
        mock_validate.return_value = TestDataFactory.create_mock_user(user_id=uuid4())
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get.return_value = TestDataFactory.create_mock_accumulator(user_id=uuid4())

        with pytest.raises(HTTPException) as exc_info:
            delete_accumulator_service(token=token, accumulator_id=uuid4())

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.get_accumulator_by_id')
    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    def test_delete_accumulator_service_preset_forbidden(self, mock_validate, mock_get, mock_session):
        """Test delete_accumulator_service when trying to delete a preset accumulator."""
        user_id = uuid4()
        token = "valid_token"
        mock_validate.return_value = TestDataFactory.create_mock_user(user_id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get.return_value = TestDataFactory.create_mock_accumulator(
            user_id=user_id, accumulator_type=AccumulatorType.PRESET
        )

        with pytest.raises(HTTPException) as exc_info:
            delete_accumulator_service(token=token, accumulator_id=uuid4())

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    def test_delete_accumulator_service_invalid_token(self, mock_validate):
        """Test delete_accumulator_service with invalid token."""
        mock_validate.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        )

        with pytest.raises(HTTPException) as exc_info:
            delete_accumulator_service(token="invalid_token", accumulator_id=uuid4())

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


class TestGetAccumulatorHistoryService:
    """Test cases for get_accumulator_history_service function."""

    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.get_user_accumulator_history')
    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    def test_get_accumulator_history_service_success(self, mock_validate, mock_get_history, mock_session):
        """Test successful retrieval of accumulator history."""
        user_id = uuid4()
        accumulator_id = uuid4()
        token = "valid_token"

        mock_validate.return_value = TestDataFactory.create_mock_user(user_id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        accumulator = TestDataFactory.create_mock_accumulator(
            accumulator_id=accumulator_id, name="Mani", current_count=300
        )
        session1 = TestDataFactory.create_mock_history(accumulator_id=accumulator_id, count=100)
        session2 = TestDataFactory.create_mock_history(accumulator_id=accumulator_id, count=200)

        mock_get_history.return_value = ([(accumulator, 300, [session1, session2])], 1)

        result = get_accumulator_history_service(token=token, skip=0, limit=20)

        assert isinstance(result, AccumulatorHistoryResponse)
        assert len(result.accumulators) == 1
        assert result.accumulators[0].metadata[0].name == "Mani"
        assert result.accumulators[0].total_counted == 300
        assert len(result.accumulators[0].sessions) == 2
        assert result.total == 1

        mock_validate.assert_called_once_with(token=token)
        mock_get_history.assert_called_once_with(mock_db, user_id, 0, 20)

    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.get_user_accumulator_history')
    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    def test_get_accumulator_history_service_empty(self, mock_validate, mock_get_history, mock_session):
        """Test get_accumulator_history_service when user has no history."""
        token = "valid_token"
        mock_validate.return_value = TestDataFactory.create_mock_user()
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get_history.return_value = ([], 0)

        result = get_accumulator_history_service(token=token, skip=0, limit=20)

        assert len(result.accumulators) == 0
        assert result.total == 0

    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    def test_get_accumulator_history_service_invalid_token(self, mock_validate):
        """Test get_accumulator_history_service with invalid token."""
        mock_validate.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        )

        with pytest.raises(HTTPException) as exc_info:
            get_accumulator_history_service(token="invalid_token", skip=0, limit=20)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    @patch('pecha_api.mantra.mantra_service.resolve_deity_image')
    @patch('pecha_api.accumulator.accumulator_service.get_mantras_by_ids')
    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.get_user_accumulator_history')
    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    def test_get_accumulator_history_service_batches_mantras_and_includes_deity_image(
        self, mock_validate, mock_get_history, mock_session, mock_get_mantras, mock_resolve
    ):
        """History rows batch their mantra lookup once (mirroring the preset-side
        pattern) instead of querying per row, and deity_image is populated."""
        mock_validate.return_value = TestDataFactory.create_mock_user()
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        mantra_id = uuid4()
        mantra = TestDataFactory.create_mock_mantra(mantra_id=mantra_id)
        accumulator = TestDataFactory.create_mock_accumulator(mantra_id=mantra_id)
        session = TestDataFactory.create_mock_history(accumulator_id=accumulator.id)
        mock_get_history.return_value = ([(accumulator, 10, [session])], 1)
        mock_get_mantras.return_value = {mantra_id: mantra}
        expected_image = ImageUrlModel(thumbnail="t", medium="m", original="o")
        mock_resolve.return_value = expected_image

        result = get_accumulator_history_service(token="token", skip=0, limit=20)

        mock_get_mantras.assert_called_once_with(mock_db, [mantra_id])
        assert result.accumulators[0].deity_image is expected_image


class TestGetAccumulatorDetailService:
    """Test cases for get_accumulator_detail_service."""

    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.get_accumulator_with_history')
    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    def test_get_accumulator_detail_service_success(self, mock_validate, mock_get_history, mock_session):
        """Return history when the user already has an accumulator for the preset."""
        token = "valid_token"
        user_id = uuid4()
        parent_id = uuid4()
        mock_validate.return_value = TestDataFactory.create_mock_user(user_id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        accumulator = TestDataFactory.create_mock_accumulator(
            user_id=user_id,
            parent_id=parent_id,
            current_count=50,
        )
        sessions = [TestDataFactory.create_mock_history(accumulator_id=accumulator.id, user_id=user_id)]
        mock_get_history.return_value = (accumulator, 50, sessions)

        result = get_accumulator_detail_service(token=token, parent_id=parent_id)

        assert isinstance(result, AccumulatorHistoryDTO)
        assert result.accumulator_id == accumulator.id
        assert result.parent_id == parent_id
        assert result.current_count == 50
        assert result.total_counted == 50
        assert len(result.sessions) == 1
        mock_get_history.assert_called_once_with(mock_db, user_id, parent_id)

    @patch('pecha_api.accumulator.accumulator_service._create_accumulator_from_preset')
    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.get_accumulator_with_history')
    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    def test_get_accumulator_detail_service_creates_when_missing(
        self, mock_validate, mock_get_history, mock_session, mock_create
    ):
        """Auto-create from preset when the user has no accumulator yet."""
        token = "valid_token"
        user_id = uuid4()
        parent_id = uuid4()
        mock_validate.return_value = TestDataFactory.create_mock_user(user_id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get_history.return_value = None

        created = TestDataFactory.create_mock_accumulator(
            user_id=user_id,
            parent_id=parent_id,
            current_count=0,
        )
        mock_create.return_value = created

        result = get_accumulator_detail_service(token=token, parent_id=parent_id)

        assert isinstance(result, AccumulatorHistoryDTO)
        assert result.accumulator_id == created.id
        assert result.parent_id == parent_id
        assert result.current_count == 0
        assert result.total_counted == 0
        assert result.sessions == []
        mock_create.assert_called_once_with(mock_db, user_id, parent_id)

    @patch('pecha_api.accumulator.accumulator_service._create_accumulator_from_preset')
    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.get_accumulator_with_history')
    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    def test_get_accumulator_detail_service_preset_not_found(
        self, mock_validate, mock_get_history, mock_session, mock_create
    ):
        """Still returns 404 when the preset itself does not exist."""
        token = "valid_token"
        mock_validate.return_value = TestDataFactory.create_mock_user()
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get_history.return_value = None
        mock_create.side_effect = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "NOT_FOUND", "message": "Preset accumulator not found"},
        )

        with pytest.raises(HTTPException) as exc_info:
            get_accumulator_detail_service(token=token, parent_id=uuid4())

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @patch('pecha_api.mantra.mantra_service.resolve_deity_image')
    @patch('pecha_api.accumulator.accumulator_service.get_mantras_by_ids')
    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.get_accumulator_with_history')
    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    def test_get_accumulator_detail_service_includes_deity_image(
        self, mock_validate, mock_get_history, mock_session, mock_get_mantras, mock_resolve
    ):
        """The linked mantra's deity image is resolved for the single-row detail response."""
        user_id = uuid4()
        parent_id = uuid4()
        mantra_id = uuid4()
        mock_validate.return_value = TestDataFactory.create_mock_user(user_id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        mantra = TestDataFactory.create_mock_mantra(mantra_id=mantra_id)
        accumulator = TestDataFactory.create_mock_accumulator(
            user_id=user_id, parent_id=parent_id, mantra_id=mantra_id
        )
        mock_get_history.return_value = (accumulator, 50, [])
        mock_get_mantras.return_value = {mantra_id: mantra}
        expected_image = ImageUrlModel(thumbnail="t", medium="m", original="o")
        mock_resolve.return_value = expected_image

        result = get_accumulator_detail_service(token="token", parent_id=parent_id)

        mock_get_mantras.assert_called_once_with(mock_db, [mantra_id])
        assert result.deity_image is expected_image


class TestHelperFunctions:
    """Test cases for helper/conversion functions."""

    def test_convert_accumulator_to_dto(self):
        """Test conversion of Accumulator model to AccumulatorDTO."""
        accumulator_id = uuid4()
        user_id = uuid4()
        accumulator = TestDataFactory.create_mock_accumulator(
            accumulator_id=accumulator_id,
            user_id=user_id,
            name="Mani",
            description="Compassion mantra",
            target_count=108,
            current_count=42,
        )

        result = convert_accumulator_to_dto(accumulator)

        assert isinstance(result, AccumulatorDTO)
        assert result.id == accumulator_id
        assert result.user_id == user_id
        assert result.metadata[0].name == "Mani"
        assert result.metadata[0].description == "Compassion mantra"
        assert result.target_count == 108
        assert result.current_count == 42
        assert result.type == AccumulatorType.USER

    def test_convert_accumulator_to_dto_none_current_count_defaults_zero(self):
        """A None current_count should be coerced to 0 in the DTO."""
        accumulator = TestDataFactory.create_mock_accumulator(current_count=None)

        result = convert_accumulator_to_dto(accumulator)

        assert result.current_count == 0

    def test_convert_accumulator_to_dto_preset_allows_null_user_id(self):
        """Preset accumulators have no user_id and should still convert."""
        accumulator = TestDataFactory.create_mock_accumulator(
            accumulator_type=AccumulatorType.PRESET,
        )
        accumulator.user_id = None

        result = convert_accumulator_to_dto(accumulator)

        assert isinstance(result, AccumulatorDTO)
        assert result.user_id is None
        assert result.type == AccumulatorType.PRESET

    def test_convert_accumulator_to_public_dto_omits_user_id(self):
        """Public DTO should not carry user_id and exposes the row id as id."""
        accumulator = TestDataFactory.create_mock_accumulator()

        result = convert_accumulator_to_public_dto(accumulator)

        assert isinstance(result, PublicAccumulatorDTO)
        assert not hasattr(result, "user_id")
        assert not hasattr(result, "preset_id")
        assert not hasattr(result, "mantra_id")
        assert result.id == accumulator.id
        assert result.mantra is None

    def test_build_preset_mantra_dto_defaults_to_english(self):
        """Without a language filter, English metadata is preferred."""
        mantra = TestDataFactory.create_mock_mantra(
            metadata_entries=[
                TestDataFactory.create_mock_mantra_metadata(
                    mantra="BO text", language=LanguageCode.BO
                ),
                TestDataFactory.create_mock_mantra_metadata(
                    mantra="EN text", language=LanguageCode.EN
                ),
            ],
        )

        result = build_preset_mantra_dto(mantra, language=None)

        assert result is not None
        assert result.mantra == "EN text"

    def test_build_preset_mantra_dto_returns_none_without_metadata(self):
        """No metadata entries yields no mantra detail."""
        mantra = TestDataFactory.create_mock_mantra(metadata_entries=[])

        assert build_preset_mantra_dto(mantra, language="en") is None

    def test_build_preset_mantra_dto_falls_back_to_english_when_language_missing(self):
        """Requested language with no matching metadata falls back to English."""
        mantra = TestDataFactory.create_mock_mantra(
            metadata_entries=[
                TestDataFactory.create_mock_mantra_metadata(
                    mantra="EN text", language=LanguageCode.EN
                )
            ],
        )

        result = build_preset_mantra_dto(mantra, language="bo")

        assert result is not None
        assert result.mantra == "EN text"

    def test_build_preset_mantra_dto_falls_back_to_english_for_unlisted_language(self):
        """A language outside the enum (e.g. Ladakhi) still resolves to English."""
        mantra = TestDataFactory.create_mock_mantra(
            metadata_entries=[
                TestDataFactory.create_mock_mantra_metadata(
                    mantra="EN text", language=LanguageCode.EN
                ),
                TestDataFactory.create_mock_mantra_metadata(
                    mantra="BO text", language=LanguageCode.BO
                ),
            ],
        )

        result = build_preset_mantra_dto(mantra, language="la")

        assert result is not None
        assert result.mantra == "EN text"

    def test_build_preset_mantra_dto_returns_none_when_no_match_and_no_english(self):
        """With neither the requested language nor English available, yield None."""
        mantra = TestDataFactory.create_mock_mantra(
            metadata_entries=[
                TestDataFactory.create_mock_mantra_metadata(language=LanguageCode.BO)
            ],
        )

        assert build_preset_mantra_dto(mantra, language="zh") is None

    def test_build_preset_mantra_dto_falls_back_to_first_metadata(self):
        """Without English metadata, the first entry is used."""
        mantra = TestDataFactory.create_mock_mantra(
            metadata_entries=[
                TestDataFactory.create_mock_mantra_metadata(
                    mantra="BO text", language=LanguageCode.BO
                ),
            ],
        )

        result = build_preset_mantra_dto(mantra, language=None)

        assert result is not None
        assert result.mantra == "BO text"

    def test_convert_accumulator_to_public_dto_includes_mantra_detail(self):
        """Public DTO embeds mantra detail when mantra data is available."""
        mantra_id = uuid4()
        mantra = TestDataFactory.create_mock_mantra(mantra_id=mantra_id)
        accumulator = TestDataFactory.create_mock_accumulator(mantra_id=mantra_id)

        result = convert_accumulator_to_public_dto(
            accumulator,
            mantras_by_id={mantra_id: mantra},
            language="en",
        )

        assert result.mantra is not None
        assert result.mantra.id == mantra_id
        assert result.mantra.mantra == "Om Mani Padme Hum"

    @patch('pecha_api.accumulator.accumulator_service.generate_presigned_access_url')
    @patch('pecha_api.accumulator.accumulator_service.get')
    def test_generate_mala_image_presigned_url_success(self, mock_get, mock_presign):
        """Presigned URL is returned for a valid mala image key."""
        mock_get.return_value = "test-bucket"
        mock_presign.return_value = "https://signed-url"

        assert generate_mala_image_presigned_url("mala-images/default.png") == "https://signed-url"

    def test_generate_mala_image_presigned_url_none_for_empty_url(self):
        """Empty mala image url returns None without calling S3."""
        assert generate_mala_image_presigned_url(None) is None

    @patch('pecha_api.mantra.mantra_service.resolve_deity_image')
    def test_build_preset_mantra_dto_includes_deity_image(self, mock_resolve):
        """The resolved deity image (from the mantra, not the accumulator) is included."""
        expected_image = ImageUrlModel(thumbnail="t", medium="m", original="o")
        mock_resolve.return_value = expected_image
        mantra = TestDataFactory.create_mock_mantra(deity_image="images/mantra_images/x/original/y.webp")

        result = build_preset_mantra_dto(mantra, language=None)

        assert result.deity_image is expected_image
        assert not hasattr(result, "deity_image_key")
        mock_resolve.assert_called_once_with(mantra)

    @patch('pecha_api.mantra.mantra_service.resolve_deity_image')
    def test_build_preset_mantra_dto_include_key_true_returns_cms_variant(self, mock_resolve):
        """CMS callers (include_key=True) get the raw key alongside the resolved image."""
        mock_resolve.return_value = None
        mantra = TestDataFactory.create_mock_mantra(deity_image="images/mantra_images/x/original/y.webp")

        result = build_preset_mantra_dto(mantra, language=None, include_key=True)

        assert isinstance(result, CMSPresetMantraDTO)
        assert result.deity_image_key == "images/mantra_images/x/original/y.webp"

    def test_build_preset_mantra_dto_include_key_false_is_plain_dto(self):
        """Public callers (default) never get the raw key attribute."""
        mantra = TestDataFactory.create_mock_mantra()

        result = build_preset_mantra_dto(mantra, language=None)

        assert type(result) is PresetMantraDTO


class TestConvertAccumulatorToDtoDeityImage:
    """convert_accumulator_to_dto/convert_accumulators_to_dtos resolve deity_image
    from a pre-batched mantras_by_id map, matching the preset-side pattern."""

    @patch('pecha_api.mantra.mantra_service.resolve_deity_image')
    def test_convert_accumulator_to_dto_resolves_deity_image_from_map(self, mock_resolve):
        expected_image = ImageUrlModel(thumbnail="t", medium="m", original="o")
        mock_resolve.return_value = expected_image
        mantra_id = uuid4()
        mantra = TestDataFactory.create_mock_mantra(mantra_id=mantra_id)
        accumulator = TestDataFactory.create_mock_accumulator(mantra_id=mantra_id)

        result = convert_accumulator_to_dto(accumulator, mantras_by_id={mantra_id: mantra})

        assert result.deity_image is expected_image
        mock_resolve.assert_called_once_with(mantra)

    def test_convert_accumulator_to_dto_no_mantras_by_id_is_none(self):
        """Without a mantras_by_id map (e.g. delete/list paths that don't need it),
        deity_image degrades to None instead of raising."""
        accumulator = TestDataFactory.create_mock_accumulator(mantra_id=uuid4())

        result = convert_accumulator_to_dto(accumulator)

        assert result.deity_image is None

    def test_convert_accumulator_to_dto_mantra_not_in_map_is_none(self):
        accumulator = TestDataFactory.create_mock_accumulator(mantra_id=uuid4())

        result = convert_accumulator_to_dto(accumulator, mantras_by_id={})

        assert result.deity_image is None

    @patch('pecha_api.accumulator.accumulator_service.generate_presigned_access_url', side_effect=Exception("s3 down"))
    @patch('pecha_api.accumulator.accumulator_service.get', return_value="test-bucket")
    def test_generate_mala_image_presigned_url_handles_errors(self, _mock_get, _mock_presign):
        """S3 failures are swallowed and return None."""
        assert generate_mala_image_presigned_url("mala-images/default.png") is None

    @patch(
        "pecha_api.accumulator.accumulator_service.generate_mala_image_presigned_url",
        side_effect=lambda url: f"https://signed/{url}",
    )
    @patch("pecha_api.accumulator.accumulator_service.get_mantra_by_id")
    def test_resolve_accumulator_bookmark_mala_image_url_preset_uses_mantra(
        self, mock_get_mantra, _mock_presign
    ):
        """Preset bookmark images prefer the mantra mala over the accumulator mala."""
        mantra_id = uuid4()
        mantra_mala = MagicMock()
        mantra_mala.url = "mantra-mala.png"
        accumulator_mala = MagicMock()
        accumulator_mala.url = "accumulator-mala.png"

        preset = TestDataFactory.create_mock_accumulator(
            accumulator_type=AccumulatorType.PRESET,
            mantra_id=mantra_id,
            mala=accumulator_mala,
        )
        mock_get_mantra.return_value = TestDataFactory.create_mock_mantra(
            mantra_id=mantra_id,
            mala=mantra_mala,
        )
        mock_db = MagicMock()

        result = resolve_accumulator_bookmark_mala_image_url(mock_db, preset)

        assert result == "https://signed/mantra-mala.png"
        mock_get_mantra.assert_called_once_with(mock_db, mantra_id)

    @patch(
        "pecha_api.accumulator.accumulator_service.generate_mala_image_presigned_url",
        side_effect=lambda url: f"https://signed/{url}",
    )
    def test_resolve_accumulator_bookmark_mala_image_url_user_uses_accumulator(
        self, _mock_presign
    ):
        """User accumulator bookmark images use the accumulator's chosen mala."""
        accumulator_mala = MagicMock()
        accumulator_mala.url = "user-mala.png"
        accumulator = TestDataFactory.create_mock_accumulator(
            accumulator_type=AccumulatorType.USER,
            mala=accumulator_mala,
        )

        result = resolve_accumulator_bookmark_mala_image_url(MagicMock(), accumulator)

        assert result == "https://signed/user-mala.png"

    @patch('pecha_api.accumulator.accumulator_service.commit_accumulator')
    @patch('pecha_api.accumulator.accumulator_service.add_accumulator')
    @patch('pecha_api.accumulator.accumulator_service.get_mantra_mala_image_id', return_value=None)
    @patch('pecha_api.accumulator.accumulator_service.get_user_accumulator_by_parent')
    @patch('pecha_api.accumulator.accumulator_service.get_preset_by_id')
    def test_create_accumulator_from_preset_raises_when_duplicate(
        self, mock_get_preset, mock_get_by_parent, _mock_mala, _mock_add, _mock_commit
    ):
        """Shared create helper rejects duplicate preset accumulators."""
        user_id = uuid4()
        preset_id = uuid4()
        mock_get_preset.return_value = TestDataFactory.create_mock_accumulator(
            accumulator_id=preset_id, accumulator_type=AccumulatorType.PRESET
        )
        mock_get_by_parent.return_value = TestDataFactory.create_mock_accumulator(
            user_id=user_id, parent_id=preset_id
        )

        with pytest.raises(HTTPException) as exc_info:
            _create_accumulator_from_preset(MagicMock(), user_id, preset_id)

        assert exc_info.value.status_code == status.HTTP_409_CONFLICT

    def test_is_user_created_accumulator_user_type(self):
        """is_user_created_accumulator returns True for USER type."""
        accumulator = TestDataFactory.create_mock_accumulator(accumulator_type=AccumulatorType.USER)
        assert is_user_created_accumulator(accumulator) is True

    def test_is_user_created_accumulator_preset_type(self):
        """is_user_created_accumulator returns False for PRESET type."""
        accumulator = TestDataFactory.create_mock_accumulator(accumulator_type=AccumulatorType.PRESET)
        assert is_user_created_accumulator(accumulator) is False

    @patch('pecha_api.accumulator.accumulator_service.mantra_exists')
    def test_validate_mantra_exists_found(self, mock_mantra_exists):
        """validate_mantra_exists is a no-op when the mantra exists."""
        mock_mantra_exists.return_value = True
        # Should not raise
        validate_mantra_exists(MagicMock(), uuid4())

    @patch('pecha_api.accumulator.accumulator_service.mantra_exists')
    def test_validate_mantra_exists_not_found(self, mock_mantra_exists):
        """validate_mantra_exists raises 404 when the mantra is missing."""
        mock_mantra_exists.return_value = False

        with pytest.raises(HTTPException) as exc_info:
            validate_mantra_exists(MagicMock(), uuid4())

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


class TestGetAccumulatorGroupsService:
    """Test cases for get_accumulator_groups_service function."""

    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.get_groups_by_accumulator_id')
    @patch('pecha_api.accumulator.accumulator_service.get_accumulator_by_id')
    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    def test_get_accumulator_groups_service_success(
        self, mock_validate, mock_get_accumulator, mock_get_groups, mock_session
    ):
        """Test successful retrieval of groups associated with an accumulator."""
        user_id = uuid4()
        accumulator_id = uuid4()
        group_id_1 = uuid4()
        group_id_2 = uuid4()
        token = "valid_token"

        mock_validate.return_value = TestDataFactory.create_mock_user(user_id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        # Mock accumulator exists
        accumulator = TestDataFactory.create_mock_accumulator(accumulator_id=accumulator_id)
        mock_get_accumulator.return_value = accumulator

        # Mock group accumulators with user counts
        from pecha_api.accumulator.accumulator_repository import GroupAccumulatorWithUserCount
        
        group_acc_1 = MagicMock()
        group_acc_1.id = uuid4()
        group_acc_1.group_id = group_id_1
        group_acc_1.title = "Group Practice 1"
        group_acc_1.target_count = 100000
        group_acc_1.start_date = datetime(2024, 1, 1)
        group_acc_1.end_date = datetime(2024, 12, 31)
        group_acc_1.created_at = datetime.utcnow()
        group_acc_1.image_key = None

        group_acc_2 = MagicMock()
        group_acc_2.id = uuid4()
        group_acc_2.group_id = group_id_2
        group_acc_2.title = "Group Practice 2"
        group_acc_2.target_count = 50000
        group_acc_2.start_date = datetime(2024, 6, 1)
        group_acc_2.end_date = datetime(2024, 11, 30)
        group_acc_2.created_at = datetime.utcnow()
        group_acc_2.image_key = None

        item_1 = GroupAccumulatorWithUserCount(group_acc_1, 1234, is_joined=True)
        item_2 = GroupAccumulatorWithUserCount(group_acc_2, 567, is_joined=False)

        mock_get_groups.return_value = ([item_1, item_2], 2)

        result = get_accumulator_groups_service(
            token=token,
            accumulator_id=accumulator_id,
            skip=0,
            limit=20
        )

        assert isinstance(result, AccumulatorGroupsResponse)
        assert len(result.groups) == 2
        assert result.total == 2
        assert result.skip == 0
        assert result.limit == 20

        # Verify first group
        assert result.groups[0].group_id == group_id_1
        assert result.groups[0].title == "Group Practice 1"
        assert result.groups[0].target_count == 100000
        assert result.groups[0].user_total_count == 1234
        assert result.groups[0].is_joined is True
        assert result.groups[0].image is None

        # Verify second group
        assert result.groups[1].group_id == group_id_2
        assert result.groups[1].title == "Group Practice 2"
        assert result.groups[1].target_count == 50000
        assert result.groups[1].user_total_count == 567
        assert result.groups[1].is_joined is False
        assert result.groups[1].image is None

        mock_validate.assert_called_once_with(token=token)
        mock_get_accumulator.assert_called_once_with(mock_db, accumulator_id)
        mock_get_groups.assert_called_once_with(
            db=mock_db,
            accumulator_id=accumulator_id,
            user_id=user_id,
            skip=0,
            limit=20,
            joined_only=False,
        )

    @patch('pecha_api.accumulator.accumulator_service.get_image_url')
    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.get_groups_by_accumulator_id')
    @patch('pecha_api.accumulator.accumulator_service.get_accumulator_by_id')
    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    def test_get_accumulator_groups_service_returns_image_url(
        self, mock_validate, mock_get_accumulator, mock_get_groups, mock_session, mock_get_image_url
    ):
        """Test group accumulator image is returned as presigned URL, not raw key."""
        from pecha_api.accumulator.accumulator_repository import GroupAccumulatorWithUserCount
        from pecha_api.plans.media.media_response_models import ImageUrlModel

        user_id = uuid4()
        accumulator_id = uuid4()
        group_id = uuid4()
        token = "valid_token"
        image_key = "groups/abc123/cover.jpg"
        image_model = ImageUrlModel(
            thumbnail="https://example.com/thumb.jpg",
            medium="https://example.com/medium.jpg",
            original="https://example.com/original.jpg",
        )

        mock_validate.return_value = TestDataFactory.create_mock_user(user_id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get_accumulator.return_value = TestDataFactory.create_mock_accumulator(
            accumulator_id=accumulator_id
        )
        mock_get_image_url.return_value = image_model

        group_acc = MagicMock()
        group_acc.id = uuid4()
        group_acc.group_id = group_id
        group_acc.title = "Group Practice"
        group_acc.target_count = 100000
        group_acc.start_date = None
        group_acc.end_date = None
        group_acc.created_at = datetime.utcnow()
        group_acc.image_key = image_key

        mock_get_groups.return_value = (
            [GroupAccumulatorWithUserCount(group_acc, 100, is_joined=True)],
            1,
        )

        result = get_accumulator_groups_service(
            token=token,
            accumulator_id=accumulator_id,
            skip=0,
            limit=20,
        )

        mock_get_image_url.assert_called_once_with(image_key)
        assert result.groups[0].image == image_model
        assert "image_key" not in AccumulatorGroupDTO.model_fields

    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.get_groups_by_accumulator_id')
    @patch('pecha_api.accumulator.accumulator_service.get_accumulator_by_id')
    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    def test_get_accumulator_groups_service_empty(
        self, mock_validate, mock_get_accumulator, mock_get_groups, mock_session
    ):
        """Test get_accumulator_groups_service when no groups use the accumulator."""
        user_id = uuid4()
        accumulator_id = uuid4()
        token = "valid_token"

        mock_validate.return_value = TestDataFactory.create_mock_user(user_id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        accumulator = TestDataFactory.create_mock_accumulator(accumulator_id=accumulator_id)
        mock_get_accumulator.return_value = accumulator
        mock_get_groups.return_value = ([], 0)

        result = get_accumulator_groups_service(
            token=token,
            accumulator_id=accumulator_id,
            skip=0,
            limit=20
        )

        assert isinstance(result, AccumulatorGroupsResponse)
        assert len(result.groups) == 0
        assert result.total == 0

    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.get_groups_by_accumulator_id')
    @patch('pecha_api.accumulator.accumulator_service.get_accumulator_by_id')
    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    def test_get_accumulator_groups_service_user_with_zero_count(
        self, mock_validate, mock_get_accumulator, mock_get_groups, mock_session
    ):
        """Test when user has not contributed to any group yet."""
        user_id = uuid4()
        accumulator_id = uuid4()
        token = "valid_token"

        mock_validate.return_value = TestDataFactory.create_mock_user(user_id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        accumulator = TestDataFactory.create_mock_accumulator(accumulator_id=accumulator_id)
        mock_get_accumulator.return_value = accumulator

        from pecha_api.accumulator.accumulator_repository import GroupAccumulatorWithUserCount
        
        group_acc = MagicMock()
        group_acc.id = uuid4()
        group_acc.group_id = uuid4()
        group_acc.title = "Group Practice"
        group_acc.target_count = 100000
        group_acc.start_date = datetime(2024, 1, 1)
        group_acc.end_date = datetime(2024, 12, 31)
        group_acc.created_at = datetime.utcnow()
        group_acc.image_key = None

        item = GroupAccumulatorWithUserCount(group_acc, 0)  # Zero count
        mock_get_groups.return_value = ([item], 1)

        result = get_accumulator_groups_service(
            token=token,
            accumulator_id=accumulator_id,
            skip=0,
            limit=20
        )

        assert len(result.groups) == 1
        assert result.groups[0].user_total_count == 0

    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.get_groups_by_accumulator_id')
    @patch('pecha_api.accumulator.accumulator_service.get_accumulator_by_id')
    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    def test_get_accumulator_groups_service_pagination(
        self, mock_validate, mock_get_accumulator, mock_get_groups, mock_session
    ):
        """Test get_accumulator_groups_service with custom pagination."""
        user_id = uuid4()
        accumulator_id = uuid4()
        token = "valid_token"

        mock_validate.return_value = TestDataFactory.create_mock_user(user_id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        accumulator = TestDataFactory.create_mock_accumulator(accumulator_id=accumulator_id)
        mock_get_accumulator.return_value = accumulator

        from pecha_api.accumulator.accumulator_repository import GroupAccumulatorWithUserCount
        
        group_acc = MagicMock()
        group_acc.id = uuid4()
        group_acc.group_id = uuid4()
        group_acc.title = "Group Practice"
        group_acc.target_count = 100000
        group_acc.start_date = datetime(2024, 1, 1)
        group_acc.end_date = datetime(2024, 12, 31)
        group_acc.created_at = datetime.utcnow()
        group_acc.image_key = None

        item = GroupAccumulatorWithUserCount(group_acc, 500)
        mock_get_groups.return_value = ([item], 10)

        result = get_accumulator_groups_service(
            token=token,
            accumulator_id=accumulator_id,
            skip=5,
            limit=1
        )

        assert result.skip == 5
        assert result.limit == 1
        assert result.total == 10
        assert len(result.groups) == 1

        mock_get_groups.assert_called_once_with(
            db=mock_db,
            accumulator_id=accumulator_id,
            user_id=user_id,
            skip=5,
            limit=1,
            joined_only=False,
        )

    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.get_groups_by_accumulator_id')
    @patch('pecha_api.accumulator.accumulator_service.get_accumulator_by_id')
    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    def test_get_accumulator_groups_service_joined_only(
        self, mock_validate, mock_get_accumulator, mock_get_groups, mock_session
    ):
        """Test get_accumulator_groups_service passes joined_only to repository."""
        user_id = uuid4()
        accumulator_id = uuid4()
        token = "valid_token"

        mock_validate.return_value = TestDataFactory.create_mock_user(user_id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        accumulator = TestDataFactory.create_mock_accumulator(accumulator_id=accumulator_id)
        mock_get_accumulator.return_value = accumulator
        mock_get_groups.return_value = ([], 0)

        get_accumulator_groups_service(
            token=token,
            accumulator_id=accumulator_id,
            skip=0,
            limit=20,
            joined_only=True,
        )

        mock_get_groups.assert_called_once_with(
            db=mock_db,
            accumulator_id=accumulator_id,
            user_id=user_id,
            skip=0,
            limit=20,
            joined_only=True,
        )

    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.get_accumulator_by_id')
    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    def test_get_accumulator_groups_service_accumulator_not_found(
        self, mock_validate, mock_get_accumulator, mock_session
    ):
        """Test get_accumulator_groups_service when accumulator doesn't exist."""
        user_id = uuid4()
        accumulator_id = uuid4()
        token = "valid_token"

        mock_validate.return_value = TestDataFactory.create_mock_user(user_id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        mock_get_accumulator.return_value = None  # Accumulator not found

        with pytest.raises(HTTPException) as exc_info:
            get_accumulator_groups_service(
                token=token,
                accumulator_id=accumulator_id,
                skip=0,
                limit=20
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
        mock_get_accumulator.assert_called_once_with(mock_db, accumulator_id)

    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    def test_get_accumulator_groups_service_invalid_token(self, mock_validate):
        """Test get_accumulator_groups_service with invalid authentication token."""
        token = "invalid_token"
        accumulator_id = uuid4()

        mock_validate.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        )

        with pytest.raises(HTTPException) as exc_info:
            get_accumulator_groups_service(
                token=token,
                accumulator_id=accumulator_id,
                skip=0,
                limit=20
            )

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        mock_validate.assert_called_once_with(token=token)

    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.get_groups_by_accumulator_id')
    @patch('pecha_api.accumulator.accumulator_service.get_accumulator_by_id')
    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    def test_get_accumulator_groups_service_with_optional_fields_none(
        self, mock_validate, mock_get_accumulator, mock_get_groups, mock_session
    ):
        """Test with groups having optional fields as None."""
        user_id = uuid4()
        accumulator_id = uuid4()
        token = "valid_token"

        mock_validate.return_value = TestDataFactory.create_mock_user(user_id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        accumulator = TestDataFactory.create_mock_accumulator(accumulator_id=accumulator_id)
        mock_get_accumulator.return_value = accumulator

        from pecha_api.accumulator.accumulator_repository import GroupAccumulatorWithUserCount
        
        group_acc = MagicMock()
        group_acc.id = uuid4()
        group_acc.group_id = uuid4()
        group_acc.title = None  # Optional
        group_acc.target_count = None  # Optional
        group_acc.start_date = None  # Optional
        group_acc.end_date = None  # Optional
        group_acc.created_at = datetime.utcnow()
        group_acc.image_key = None

        item = GroupAccumulatorWithUserCount(group_acc, 100)
        mock_get_groups.return_value = ([item], 1)

        result = get_accumulator_groups_service(
            token=token,
            accumulator_id=accumulator_id,
            skip=0,
            limit=20
        )

        assert len(result.groups) == 1
        assert result.groups[0].title is None
        assert result.groups[0].target_count is None
        assert result.groups[0].start_date is None
        assert result.groups[0].end_date is None
        assert result.groups[0].user_total_count == 100

    @patch('pecha_api.accumulator.accumulator_service.SessionLocal')
    @patch('pecha_api.accumulator.accumulator_service.get_groups_by_accumulator_id')
    @patch('pecha_api.accumulator.accumulator_service.get_accumulator_by_id')
    @patch('pecha_api.accumulator.accumulator_service.validate_and_extract_user_details')
    def test_get_accumulator_groups_service_large_user_count(
        self, mock_validate, mock_get_accumulator, mock_get_groups, mock_session
    ):
        """Test with large user contribution counts."""
        user_id = uuid4()
        accumulator_id = uuid4()
        token = "valid_token"

        mock_validate.return_value = TestDataFactory.create_mock_user(user_id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        accumulator = TestDataFactory.create_mock_accumulator(accumulator_id=accumulator_id)
        mock_get_accumulator.return_value = accumulator

        from pecha_api.accumulator.accumulator_repository import GroupAccumulatorWithUserCount
        
        group_acc = MagicMock()
        group_acc.id = uuid4()
        group_acc.group_id = uuid4()
        group_acc.title = "High Volume Practice"
        group_acc.target_count = 1000000
        group_acc.start_date = datetime(2024, 1, 1)
        group_acc.end_date = datetime(2024, 12, 31)
        group_acc.created_at = datetime.utcnow()
        group_acc.image_key = None

        item = GroupAccumulatorWithUserCount(group_acc, 999999)  # Large count
        mock_get_groups.return_value = ([item], 1)

        result = get_accumulator_groups_service(
            token=token,
            accumulator_id=accumulator_id,
            skip=0,
            limit=20
        )

        assert result.groups[0].user_total_count == 999999
        assert result.groups[0].target_count == 1000000
