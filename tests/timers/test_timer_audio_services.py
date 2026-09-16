import io
import pytest
from unittest.mock import MagicMock, patch
from uuid import uuid4
from datetime import datetime

from fastapi import HTTPException
from starlette import status

from pecha_api.timers.timer_audio_enums import TimerAudioType
from pecha_api.timers.timer_audio_model import TimerAudio
from pecha_api.timers.timer_audio_service import (
    convert_timer_audio_to_dto,
    create_preset_timer_audio_service,
    create_timer_audio_service,
    delete_preset_timer_audio_service,
    delete_timer_audio_service,
    list_preset_timer_audios_service,
    list_timer_audios_service,
    update_timer_audio_service,
)
from pecha_api.timers.timer_response_models import TimerAudioDTO, TimerAudiosResponse

SERVICE = "pecha_api.timers.timer_audio_service"


def _audio(timer_audio_id=None, user_id=None, name="Bell",
           audio_type=TimerAudioType.USER, image_s3_key="images/bell.png"):
    timer_audio = MagicMock(spec=TimerAudio)
    timer_audio.id = timer_audio_id or uuid4()
    timer_audio.user_id = user_id
    timer_audio.type = audio_type
    timer_audio.name = name
    timer_audio.audio_s3_key = "audio/bell.mp3"
    timer_audio.image_s3_key = image_s3_key
    timer_audio.created_at = datetime.now()
    timer_audio.updated_at = datetime.now()
    return timer_audio


def _user(user_id=None):
    user = MagicMock()
    user.id = user_id or uuid4()
    return user


def _stamped_save(db, audio):
    """save_timer_audio() normally returns a flushed row, so timestamps exist."""
    audio.created_at = datetime.now()
    audio.updated_at = datetime.now()
    return audio


def _stamped_update(db, audio):
    """update_timer_audio() normally returns the refreshed row."""
    audio.updated_at = datetime.now()
    return audio


def _upload_file(filename="bell.mp3", content_type="image/png"):
    upload = MagicMock()
    upload.filename = filename
    upload.size = 1024
    upload.content_type = content_type
    upload.file = io.BytesIO(b"data")
    return upload


class TestConvertTimerAudioToDto:
    def test_returns_none_for_none(self):
        assert convert_timer_audio_to_dto(None) is None

    @patch(f"{SERVICE}._presign", side_effect=lambda key: f"https://cdn/{key}" if key else None)
    def test_presigns_audio_and_image(self, _presign):
        result = convert_timer_audio_to_dto(_audio(user_id=uuid4()))

        assert isinstance(result, TimerAudioDTO)
        assert result.audio_url == "https://cdn/audio/bell.mp3"
        assert result.image_url == "https://cdn/images/bell.png"

    @patch(f"{SERVICE}._presign", side_effect=lambda key: f"https://cdn/{key}" if key else None)
    def test_image_is_optional(self, _presign):
        """An audio with no cover still serialises."""
        result = convert_timer_audio_to_dto(_audio(user_id=uuid4(), image_s3_key=None))

        assert result.audio_url == "https://cdn/audio/bell.mp3"
        assert result.image_url is None

    @patch(f"{SERVICE}._presign", return_value=None)
    def test_preset_has_no_owner(self, _presign):
        result = convert_timer_audio_to_dto(
            _audio(user_id=None, audio_type=TimerAudioType.PRESET)
        )

        assert result.type == TimerAudioType.PRESET
        assert result.user_id is None


class TestListTimerAudiosService:
    @patch(f"{SERVICE}._presign", return_value=None)
    @patch(f"{SERVICE}.count_visible_timer_audios", return_value=2)
    @patch(f"{SERVICE}.list_visible_timer_audios")
    @patch(f"{SERVICE}.SessionLocal")
    @patch(f"{SERVICE}.validate_and_extract_user_details")
    def test_lists_only_what_the_caller_may_see(
        self, mock_validate, mock_session, mock_list, _count, _presign
    ):
        """Presets plus the caller's own uploads: the filter is scoped by user."""
        user_id = uuid4()
        mock_validate.return_value = _user(user_id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_list.return_value = [
            _audio(user_id=None, name="Preset", audio_type=TimerAudioType.PRESET),
            _audio(user_id=user_id, name="Mine"),
        ]

        result = list_timer_audios_service(token="valid", skip=0, limit=20)

        mock_list.assert_called_once_with(mock_db, user_id=user_id, skip=0, limit=20)
        assert isinstance(result, TimerAudiosResponse)
        assert [a.name for a in result.audios] == ["Preset", "Mine"]


class TestCreateTimerAudioService:
    @patch(f"{SERVICE}._presign", return_value=None)
    @patch(f"{SERVICE}.save_timer_audio")
    @patch(f"{SERVICE}.upload_file")
    @patch(f"{SERVICE}.SessionLocal")
    @patch(f"{SERVICE}.validate_and_extract_user_details")
    def test_upload_is_owned_and_typed_user(
        self, mock_validate, mock_session, mock_upload, mock_save, _presign
    ):
        user_id = uuid4()
        mock_validate.return_value = _user(user_id=user_id)
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_save.side_effect = _stamped_save

        create_timer_audio_service(
            token="valid", name="Bell", audio_file=_upload_file(), image_file=None
        )

        saved = mock_save.call_args[0][1]
        assert saved.user_id == user_id
        assert saved.type == TimerAudioType.USER
        assert saved.name == "Bell"
        assert saved.image_s3_key is None

    @patch(f"{SERVICE}._presign", return_value=None)
    @patch(f"{SERVICE}.save_timer_audio")
    @patch(f"{SERVICE}.upload_bytes")
    @patch(f"{SERVICE}.ImageUtils")
    @patch(f"{SERVICE}.upload_file")
    @patch(f"{SERVICE}.SessionLocal")
    @patch(f"{SERVICE}.validate_and_extract_user_details")
    def test_image_is_uploaded_when_given(
        self, mock_validate, mock_session, mock_upload, mock_image_utils,
        mock_upload_bytes, mock_save, _presign
    ):
        mock_validate.return_value = _user()
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_save.side_effect = _stamped_save

        create_timer_audio_service(
            token="valid",
            name="Bell",
            audio_file=_upload_file(),
            image_file=_upload_file("cover.png"),
        )

        saved = mock_save.call_args[0][1]
        assert saved.image_s3_key.endswith(".webp")
        assert mock_upload.call_count == 1
        assert mock_upload_bytes.call_count == 1

    @patch(f"{SERVICE}.delete_file")
    @patch(f"{SERVICE}.upload_file")
    @patch(f"{SERVICE}.SessionLocal")
    @patch(f"{SERVICE}.validate_and_extract_user_details")
    def test_a_cover_that_is_not_an_image_is_rejected(
        self, mock_validate, mock_session, mock_upload, mock_delete
    ):
        """Anything that does not decode as an image never reaches the bucket,
        and the audio uploaded alongside it does not stay behind."""
        mock_validate.return_value = _user()
        mock_session.return_value.__enter__.return_value = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            create_timer_audio_service(
                token="valid",
                name="Bell",
                audio_file=_upload_file(),
                image_file=_upload_file("payload.png"),
            )

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        mock_delete.assert_called_once()

    @patch(f"{SERVICE}.validate_and_extract_user_details")
    def test_rejects_unsupported_audio_format(self, mock_validate):
        mock_validate.return_value = _user()

        with pytest.raises(HTTPException) as exc_info:
            create_timer_audio_service(
                token="valid", name="Bad", audio_file=_upload_file("virus.exe")
            )

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST

    @patch(f"{SERVICE}.delete_file")
    @patch(f"{SERVICE}.save_timer_audio", side_effect=RuntimeError("db down"))
    @patch(f"{SERVICE}.upload_bytes")
    @patch(f"{SERVICE}.ImageUtils")
    @patch(f"{SERVICE}.upload_file")
    @patch(f"{SERVICE}.SessionLocal")
    @patch(f"{SERVICE}.validate_and_extract_user_details")
    def test_uploaded_objects_are_cleaned_up_when_the_row_fails(
        self, mock_validate, mock_session, mock_upload, mock_image_utils,
        mock_upload_bytes, mock_save, mock_delete
    ):
        """Otherwise a failed create leaves orphans in the bucket."""
        mock_validate.return_value = _user()
        mock_session.return_value.__enter__.return_value = MagicMock()

        with pytest.raises(RuntimeError):
            create_timer_audio_service(
                token="valid",
                name="Bell",
                audio_file=_upload_file(),
                image_file=_upload_file("cover.png"),
            )

        assert mock_delete.call_count == 2


class TestUpdateAndDeleteOwnUpload:
    @patch(f"{SERVICE}._presign", return_value=None)
    @patch(f"{SERVICE}.update_timer_audio")
    @patch(f"{SERVICE}.get_timer_audio_by_id")
    @patch(f"{SERVICE}.SessionLocal")
    @patch(f"{SERVICE}.validate_and_extract_user_details")
    def test_owner_can_rename(
        self, mock_validate, mock_session, mock_get, mock_update, _presign
    ):
        user_id = uuid4()
        mock_validate.return_value = _user(user_id=user_id)
        mock_session.return_value.__enter__.return_value = MagicMock()
        audio = _audio(user_id=user_id)
        mock_get.return_value = audio
        mock_update.side_effect = _stamped_save

        update_timer_audio_service(token="valid", timer_audio_id=audio.id, name="Renamed")

        assert audio.name == "Renamed"

    @patch(f"{SERVICE}.get_timer_audio_by_id")
    @patch(f"{SERVICE}.SessionLocal")
    @patch(f"{SERVICE}.validate_and_extract_user_details")
    def test_another_users_upload_is_forbidden(self, mock_validate, mock_session, mock_get):
        mock_validate.return_value = _user()
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get.return_value = _audio(user_id=uuid4())

        with pytest.raises(HTTPException) as exc_info:
            update_timer_audio_service(token="valid", timer_audio_id=uuid4(), name="Nope")

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @patch(f"{SERVICE}.get_timer_audio_by_id")
    @patch(f"{SERVICE}.SessionLocal")
    @patch(f"{SERVICE}.validate_and_extract_user_details")
    def test_a_preset_cannot_be_edited_through_the_user_endpoint(
        self, mock_validate, mock_session, mock_get
    ):
        """Presets belong to Studio, so they read as missing here."""
        mock_validate.return_value = _user()
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get.return_value = _audio(user_id=None, audio_type=TimerAudioType.PRESET)

        with pytest.raises(HTTPException) as exc_info:
            update_timer_audio_service(token="valid", timer_audio_id=uuid4(), name="Nope")

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @patch(f"{SERVICE}.delete_timer_audio")
    @patch(f"{SERVICE}.get_timer_audio_by_id")
    @patch(f"{SERVICE}.SessionLocal")
    @patch(f"{SERVICE}.validate_and_extract_user_details")
    def test_owner_can_delete(self, mock_validate, mock_session, mock_get, mock_delete):
        user_id = uuid4()
        mock_validate.return_value = _user(user_id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        audio = _audio(user_id=user_id)
        mock_get.return_value = audio

        delete_timer_audio_service(token="valid", timer_audio_id=audio.id)

        mock_delete.assert_called_once_with(mock_db, audio)

    @patch(f"{SERVICE}.delete_file")
    @patch(f"{SERVICE}.delete_timer_audio")
    @patch(f"{SERVICE}.get_timer_audio_by_id")
    @patch(f"{SERVICE}.SessionLocal")
    @patch(f"{SERVICE}.validate_and_extract_user_details")
    def test_deleting_an_upload_takes_its_objects_with_it(
        self, mock_validate, mock_session, mock_get, _mock_delete_row, mock_delete_file
    ):
        """Nothing points at them once the row is gone."""
        user_id = uuid4()
        mock_validate.return_value = _user(user_id=user_id)
        mock_session.return_value.__enter__.return_value = MagicMock()
        audio = _audio(user_id=user_id)
        mock_get.return_value = audio

        delete_timer_audio_service(token="valid", timer_audio_id=audio.id)

        assert {call.args[0] for call in mock_delete_file.call_args_list} == {
            "audio/bell.mp3",
            "images/bell.png",
        }

    @patch(f"{SERVICE}.delete_file")
    @patch(f"{SERVICE}._presign", return_value=None)
    @patch(f"{SERVICE}.update_timer_audio", side_effect=_stamped_update)
    @patch(f"{SERVICE}.upload_file")
    @patch(f"{SERVICE}.get_timer_audio_by_id")
    @patch(f"{SERVICE}.SessionLocal")
    @patch(f"{SERVICE}.validate_and_extract_user_details")
    def test_replacing_the_audio_drops_the_object_it_replaced(
        self, mock_validate, mock_session, mock_get, _mock_upload,
        _mock_update, _presign, mock_delete_file
    ):
        user_id = uuid4()
        mock_validate.return_value = _user(user_id=user_id)
        mock_session.return_value.__enter__.return_value = MagicMock()
        audio = _audio(user_id=user_id)
        mock_get.return_value = audio

        update_timer_audio_service(
            token="valid", timer_audio_id=audio.id, audio_file=_upload_file()
        )

        mock_delete_file.assert_called_once_with("audio/bell.mp3")
        assert audio.audio_s3_key != "audio/bell.mp3"

    @patch(f"{SERVICE}.delete_file")
    @patch(f"{SERVICE}.update_timer_audio", side_effect=RuntimeError("db down"))
    @patch(f"{SERVICE}.upload_file")
    @patch(f"{SERVICE}.get_timer_audio_by_id")
    @patch(f"{SERVICE}.SessionLocal")
    @patch(f"{SERVICE}.validate_and_extract_user_details")
    def test_a_failed_update_drops_the_replacement_not_the_original(
        self, mock_validate, mock_session, mock_get, _mock_upload,
        _mock_update, mock_delete_file
    ):
        user_id = uuid4()
        mock_validate.return_value = _user(user_id=user_id)
        mock_session.return_value.__enter__.return_value = MagicMock()
        audio = _audio(user_id=user_id)
        mock_get.return_value = audio

        with pytest.raises(RuntimeError):
            update_timer_audio_service(
                token="valid", timer_audio_id=audio.id, audio_file=_upload_file()
            )

        deleted = {call.args[0] for call in mock_delete_file.call_args_list}
        assert "audio/bell.mp3" not in deleted
        assert len(deleted) == 1


class TestPresetCatalogue:
    @patch(f"{SERVICE}._presign", return_value=None)
    @patch(f"{SERVICE}.save_timer_audio")
    @patch(f"{SERVICE}.upload_file")
    @patch(f"{SERVICE}.SessionLocal")
    @patch(f"{SERVICE}._validate_admin")
    def test_preset_has_no_owner_and_preset_type(
        self, mock_admin, mock_session, mock_upload, mock_save, _presign
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_save.side_effect = _stamped_save

        create_preset_timer_audio_service(
            token="admin", name="Singing Bowl", audio_file=_upload_file()
        )

        saved = mock_save.call_args[0][1]
        assert saved.user_id is None
        assert saved.type == TimerAudioType.PRESET
        mock_admin.assert_called_once_with("admin")

    @patch(f"{SERVICE}._validate_admin", side_effect=HTTPException(status_code=403, detail="nope"))
    def test_non_admin_cannot_publish_a_preset(self, _mock_admin):
        with pytest.raises(HTTPException) as exc_info:
            create_preset_timer_audio_service(
                token="user", name="Sneaky", audio_file=_upload_file()
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @patch(f"{SERVICE}._presign", return_value=None)
    @patch(f"{SERVICE}.count_preset_timer_audios", return_value=1)
    @patch(f"{SERVICE}.list_preset_timer_audios")
    @patch(f"{SERVICE}.SessionLocal")
    @patch(f"{SERVICE}._validate_admin")
    def test_catalogue_lists_presets_only(
        self, _admin, mock_session, mock_list, _count, _presign
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_list.return_value = [
            _audio(user_id=None, name="Preset", audio_type=TimerAudioType.PRESET)
        ]

        result = list_preset_timer_audios_service(token="admin")

        assert [a.type for a in result.audios] == [TimerAudioType.PRESET]

    @patch(f"{SERVICE}.delete_timer_audio")
    @patch(f"{SERVICE}.get_timer_audio_by_id")
    @patch(f"{SERVICE}.SessionLocal")
    @patch(f"{SERVICE}._validate_admin")
    def test_a_user_upload_cannot_be_deleted_through_the_cms(
        self, _admin, mock_session, mock_get, mock_delete
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get.return_value = _audio(user_id=uuid4())

        with pytest.raises(HTTPException) as exc_info:
            delete_preset_timer_audio_service(token="admin", timer_audio_id=uuid4())

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
        mock_delete.assert_not_called()
