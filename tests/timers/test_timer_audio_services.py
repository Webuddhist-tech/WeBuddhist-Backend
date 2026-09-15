import pytest
from unittest.mock import MagicMock, patch
from uuid import uuid4
from datetime import datetime

from fastapi import HTTPException
from starlette import status

from pecha_api.timers.timer_audio_model import TimerAudio
from pecha_api.timers.timer_audio_service import (
    convert_timer_audio_to_dto,
    create_timer_audio_service,
    delete_timer_audio_service,
    list_timer_audios_service,
    update_timer_audio_service,
)
from pecha_api.timers.timer_response_models import (
    CreateTimerAudioRequest,
    TimerAudioDTO,
    TimerAudiosResponse,
    UpdateTimerAudioRequest,
)

SERVICE = "pecha_api.timers.timer_audio_service"


def _mock_timer_audio(timer_audio_id=None, user_id=None, name="Bell"):
    timer_audio = MagicMock(spec=TimerAudio)
    timer_audio.id = timer_audio_id or uuid4()
    timer_audio.user_id = user_id or uuid4()
    timer_audio.name = name
    timer_audio.audio_s3_key = "audio/bell.mp3"
    timer_audio.image_s3_key = "images/bell.png"
    timer_audio.created_at = datetime.now()
    timer_audio.updated_at = datetime.now()
    return timer_audio


def _mock_user(user_id=None):
    user = MagicMock()
    user.id = user_id or uuid4()
    return user


class TestConvertTimerAudioToDto:
    def test_returns_none_for_none(self):
        assert convert_timer_audio_to_dto(None) is None

    @patch(f"{SERVICE}._presign", side_effect=lambda key: f"https://cdn/{key}")
    def test_presigns_both_audio_and_image(self, _mock_presign):
        timer_audio = _mock_timer_audio()

        result = convert_timer_audio_to_dto(timer_audio)

        assert isinstance(result, TimerAudioDTO)
        assert result.audio_url == "https://cdn/audio/bell.mp3"
        assert result.image_url == "https://cdn/images/bell.png"
        assert result.name == "Bell"


class TestListTimerAudiosService:
    @patch(f"{SERVICE}._presign", side_effect=lambda key: f"https://cdn/{key}")
    @patch(f"{SERVICE}.count_timer_audios")
    @patch(f"{SERVICE}.list_timer_audios")
    @patch(f"{SERVICE}.SessionLocal")
    def test_lists_audios_from_every_owner(
        self, mock_session, mock_list, mock_count, _mock_presign
    ):
        """The catalogue is shared, so audios from different users all appear."""
        mock_session.return_value.__enter__.return_value = MagicMock()
        mine, theirs = _mock_timer_audio(name="Mine"), _mock_timer_audio(name="Theirs")
        mock_list.return_value = [mine, theirs]
        mock_count.return_value = 2

        result = list_timer_audios_service(skip=0, limit=20)

        assert isinstance(result, TimerAudiosResponse)
        assert result.total == 2
        assert [audio.name for audio in result.audios] == ["Mine", "Theirs"]

    @patch(f"{SERVICE}._presign", return_value=None)
    @patch(f"{SERVICE}.count_timer_audios")
    @patch(f"{SERVICE}.list_timer_audios")
    @patch(f"{SERVICE}.SessionLocal")
    def test_passes_pagination_through(
        self, mock_session, mock_list, mock_count, _mock_presign
    ):
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_list.return_value = []
        mock_count.return_value = 0

        result = list_timer_audios_service(skip=10, limit=5)

        mock_list.assert_called_once_with(mock_db, skip=10, limit=5)
        assert result.skip == 10
        assert result.limit == 5


class TestCreateTimerAudioService:
    @patch(f"{SERVICE}._presign", side_effect=lambda key: f"https://cdn/{key}")
    @patch(f"{SERVICE}.save_timer_audio")
    @patch(f"{SERVICE}.SessionLocal")
    @patch(f"{SERVICE}.validate_and_extract_user_details")
    def test_creates_audio_owned_by_caller(
        self, mock_validate, mock_session, mock_save, _mock_presign
    ):
        user_id = uuid4()
        mock_validate.return_value = _mock_user(user_id=user_id)
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_save.return_value = _mock_timer_audio(user_id=user_id)

        request = CreateTimerAudioRequest(
            name="Bell",
            audio_s3_key="audio/bell.mp3",
            image_s3_key="images/bell.png",
        )
        result = create_timer_audio_service(token="valid", request=request)

        saved = mock_save.call_args[0][1]
        assert saved.user_id == user_id
        assert saved.audio_s3_key == "audio/bell.mp3"
        assert saved.image_s3_key == "images/bell.png"
        assert result.audio_url == "https://cdn/audio/bell.mp3"

    def test_image_key_is_required(self):
        """The pairing is enforced by the schema, not by service code."""
        with pytest.raises(Exception):
            CreateTimerAudioRequest(name="Bell", audio_s3_key="audio/bell.mp3")


class TestUpdateTimerAudioService:
    @patch(f"{SERVICE}._presign", return_value=None)
    @patch(f"{SERVICE}.update_timer_audio")
    @patch(f"{SERVICE}.get_timer_audio_by_id")
    @patch(f"{SERVICE}.SessionLocal")
    @patch(f"{SERVICE}.validate_and_extract_user_details")
    def test_owner_can_update(
        self, mock_validate, mock_session, mock_get, mock_update, _mock_presign
    ):
        user_id = uuid4()
        mock_validate.return_value = _mock_user(user_id=user_id)
        mock_session.return_value.__enter__.return_value = MagicMock()
        timer_audio = _mock_timer_audio(user_id=user_id)
        mock_get.return_value = timer_audio
        mock_update.return_value = timer_audio

        update_timer_audio_service(
            token="valid",
            timer_audio_id=timer_audio.id,
            request=UpdateTimerAudioRequest(name="Renamed"),
        )

        assert timer_audio.name == "Renamed"

    @patch(f"{SERVICE}.get_timer_audio_by_id")
    @patch(f"{SERVICE}.SessionLocal")
    @patch(f"{SERVICE}.validate_and_extract_user_details")
    def test_non_owner_is_forbidden(self, mock_validate, mock_session, mock_get):
        mock_validate.return_value = _mock_user()
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get.return_value = _mock_timer_audio(user_id=uuid4())

        with pytest.raises(HTTPException) as exc_info:
            update_timer_audio_service(
                token="valid",
                timer_audio_id=uuid4(),
                request=UpdateTimerAudioRequest(name="Hijacked"),
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @patch(f"{SERVICE}.get_timer_audio_by_id", return_value=None)
    @patch(f"{SERVICE}.SessionLocal")
    @patch(f"{SERVICE}.validate_and_extract_user_details")
    def test_missing_audio_is_not_found(self, mock_validate, mock_session, _mock_get):
        mock_validate.return_value = _mock_user()
        mock_session.return_value.__enter__.return_value = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            update_timer_audio_service(
                token="valid",
                timer_audio_id=uuid4(),
                request=UpdateTimerAudioRequest(name="Nope"),
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @patch(f"{SERVICE}._presign", return_value=None)
    @patch(f"{SERVICE}.update_timer_audio")
    @patch(f"{SERVICE}.get_timer_audio_by_id")
    @patch(f"{SERVICE}.SessionLocal")
    @patch(f"{SERVICE}.validate_and_extract_user_details")
    def test_keys_are_left_alone_when_omitted(
        self, mock_validate, mock_session, mock_get, mock_update, _mock_presign
    ):
        """Both keys are NOT NULL, so omitting them must not clear them."""
        user_id = uuid4()
        mock_validate.return_value = _mock_user(user_id=user_id)
        mock_session.return_value.__enter__.return_value = MagicMock()
        timer_audio = _mock_timer_audio(user_id=user_id)
        mock_get.return_value = timer_audio
        mock_update.return_value = timer_audio

        update_timer_audio_service(
            token="valid",
            timer_audio_id=timer_audio.id,
            request=UpdateTimerAudioRequest(name="Renamed"),
        )

        assert timer_audio.audio_s3_key == "audio/bell.mp3"
        assert timer_audio.image_s3_key == "images/bell.png"


class TestDeleteTimerAudioService:
    @patch(f"{SERVICE}.delete_timer_audio")
    @patch(f"{SERVICE}.get_timer_audio_by_id")
    @patch(f"{SERVICE}.SessionLocal")
    @patch(f"{SERVICE}.validate_and_extract_user_details")
    def test_owner_can_delete(self, mock_validate, mock_session, mock_get, mock_delete):
        user_id = uuid4()
        mock_validate.return_value = _mock_user(user_id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        timer_audio = _mock_timer_audio(user_id=user_id)
        mock_get.return_value = timer_audio

        delete_timer_audio_service(token="valid", timer_audio_id=timer_audio.id)

        mock_delete.assert_called_once_with(mock_db, timer_audio)

    @patch(f"{SERVICE}.delete_timer_audio")
    @patch(f"{SERVICE}.get_timer_audio_by_id")
    @patch(f"{SERVICE}.SessionLocal")
    @patch(f"{SERVICE}.validate_and_extract_user_details")
    def test_non_owner_cannot_delete(
        self, mock_validate, mock_session, mock_get, mock_delete
    ):
        mock_validate.return_value = _mock_user()
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get.return_value = _mock_timer_audio(user_id=uuid4())

        with pytest.raises(HTTPException) as exc_info:
            delete_timer_audio_service(token="valid", timer_audio_id=uuid4())

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        mock_delete.assert_not_called()
