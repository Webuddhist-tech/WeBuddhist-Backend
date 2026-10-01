import pytest
from unittest.mock import patch, MagicMock
from uuid import uuid4
from datetime import datetime
from fastapi import HTTPException
from starlette import status

from pecha_api.ambient_sounds.ambient_sound_service import (
    get_all_ambient_sounds_service,
    create_ambient_sound_service,
    update_ambient_sound_service,
    delete_ambient_sound_service,
    convert_ambient_sound_to_dto,
    generate_ambient_sound_presigned_url,
)
from pecha_api.ambient_sounds.ambient_sound_model import AmbientSound


class TestDataFactory:
    @staticmethod
    def create_mock_ambient_sound(
        ambient_sound_id=None,
        name="Sea waves",
        s3_key="audio/ambient_sounds/sea-waves.mp3",
        image_s3_key=None,
        is_default=False,
        display_order=0,
    ):
        sound = MagicMock(spec=AmbientSound)
        sound.id = ambient_sound_id or uuid4()
        sound.name = name
        sound.s3_key = s3_key
        sound.image_s3_key = image_s3_key
        sound.is_default = is_default
        sound.display_order = display_order
        sound.created_at = datetime.utcnow()
        sound.updated_at = datetime.utcnow()
        return sound

    @staticmethod
    def create_mock_upload_file(filename="sound.mp3", size=1024, content_type="audio/mpeg"):
        file = MagicMock()
        file.filename = filename
        file.size = size
        file.content_type = content_type
        file.file = MagicMock()
        return file

    @staticmethod
    def create_mock_author():
        return MagicMock()


class TestGetAllAmbientSoundsService:
    @patch('pecha_api.ambient_sounds.ambient_sound_service.SessionLocal')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.list_ambient_sounds')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.generate_presigned_access_url')
    def test_get_all_ambient_sounds_service_success(self, mock_presign, mock_list, mock_session):
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        sounds = [
            TestDataFactory.create_mock_ambient_sound(name="Sea waves", display_order=0, is_default=True),
            TestDataFactory.create_mock_ambient_sound(name="Rain", display_order=1),
        ]
        mock_list.return_value = sounds
        mock_presign.return_value = "https://signed.example.com/audio.mp3"

        result = get_all_ambient_sounds_service()

        assert len(result.sounds) == 2
        assert result.sounds[0].name == "Sea waves"
        assert result.sounds[0].is_default is True
        assert result.sounds[0].url == "https://signed.example.com/audio.mp3"
        mock_list.assert_called_once_with(mock_db)


class TestConvertAmbientSoundToDto:
    @patch('pecha_api.ambient_sounds.ambient_sound_service.generate_presigned_access_url')
    def test_convert_ambient_sound_to_dto(self, mock_presign):
        mock_presign.return_value = "https://signed.example.com/rain.mp3"
        sound = TestDataFactory.create_mock_ambient_sound(name="Rain", display_order=1, is_default=False)

        dto = convert_ambient_sound_to_dto(sound)

        assert dto.id == sound.id
        assert dto.name == "Rain"
        assert dto.url == "https://signed.example.com/rain.mp3"
        assert dto.is_default is False
        assert dto.display_order == 1


class TestGenerateAmbientSoundPresignedUrl:
    def test_returns_none_for_empty_key(self):
        assert generate_ambient_sound_presigned_url(None) is None
        assert generate_ambient_sound_presigned_url("") is None

    @patch('pecha_api.ambient_sounds.ambient_sound_service.generate_presigned_access_url')
    def test_returns_none_on_exception(self, mock_presign):
        mock_presign.side_effect = Exception("boom")
        assert generate_ambient_sound_presigned_url("some/key.mp3") is None


class TestCreateAmbientSoundService:
    @patch('pecha_api.ambient_sounds.ambient_sound_service.require_super_admin')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.validate_cms_author_details')
    def test_create_forbidden_when_not_admin(self, mock_validate_author, mock_require_super_admin):
        mock_validate_author.return_value = TestDataFactory.create_mock_author()
        mock_require_super_admin.side_effect = HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="FORBIDDEN"
        )
        file = TestDataFactory.create_mock_upload_file()

        with pytest.raises(HTTPException) as exc_info:
            create_ambient_sound_service(
                token="author_token",
                name="Sea waves",
                display_order=0,
                is_default=False,
                file=file,
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @patch('pecha_api.ambient_sounds.ambient_sound_service.require_super_admin')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.validate_cms_author_details')
    def test_create_rejects_invalid_extension(self, mock_validate_author, mock_require_super_admin):
        mock_validate_author.return_value = TestDataFactory.create_mock_author()
        file = TestDataFactory.create_mock_upload_file(filename="sound.txt")

        with pytest.raises(HTTPException) as exc_info:
            create_ambient_sound_service(
                token="admin_token",
                name="Sea waves",
                display_order=0,
                is_default=False,
                file=file,
            )

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST

    @patch('pecha_api.ambient_sounds.ambient_sound_service.SessionLocal')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.save_ambient_sound')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.unset_other_defaults')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.upload_file')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.generate_presigned_access_url')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.validate_cms_author_details')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.require_super_admin')
    def test_create_success_unsets_other_defaults(
        self, mock_require_super_admin, mock_validate_author, mock_presign, mock_upload,
        mock_unset_defaults, mock_save, mock_session
    ):
        mock_validate_author.return_value = TestDataFactory.create_mock_author()
        mock_presign.return_value = "https://signed.example.com/sea-waves.mp3"
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        saved = TestDataFactory.create_mock_ambient_sound(name="Sea waves", is_default=True)
        mock_save.return_value = saved

        file = TestDataFactory.create_mock_upload_file(filename="sea-waves.mp3")

        result = create_ambient_sound_service(
            token="admin_token",
            name="Sea waves",
            display_order=0,
            is_default=True,
            file=file,
        )

        mock_unset_defaults.assert_called_once_with(mock_db)
        mock_upload.assert_called_once()
        mock_save.assert_called_once()
        assert result.name == "Sea waves"
        assert result.is_default is True

    @patch('pecha_api.ambient_sounds.ambient_sound_service.SessionLocal')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.save_ambient_sound')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.unset_other_defaults')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.upload_file')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.generate_presigned_access_url')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.validate_cms_author_details')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.require_super_admin')
    def test_create_success_not_default_skips_unset(
        self, mock_require_super_admin, mock_validate_author, mock_presign, mock_upload,
        mock_unset_defaults, mock_save, mock_session
    ):
        mock_validate_author.return_value = TestDataFactory.create_mock_author()
        mock_presign.return_value = "https://signed.example.com/rain.mp3"
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_save.return_value = TestDataFactory.create_mock_ambient_sound(name="Rain", is_default=False)

        file = TestDataFactory.create_mock_upload_file(filename="rain.mp3")

        create_ambient_sound_service(
            token="admin_token",
            name="Rain",
            display_order=1,
            is_default=False,
            file=file,
        )

        mock_unset_defaults.assert_not_called()


class TestUpdateAmbientSoundService:
    @patch('pecha_api.ambient_sounds.ambient_sound_service.require_super_admin')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.validate_cms_author_details')
    def test_update_forbidden_when_not_admin(self, mock_validate_author, mock_require_super_admin):
        mock_validate_author.return_value = TestDataFactory.create_mock_author()
        mock_require_super_admin.side_effect = HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="FORBIDDEN"
        )

        with pytest.raises(HTTPException) as exc_info:
            update_ambient_sound_service(
                token="author_token",
                ambient_sound_id=uuid4(),
                name="New name",
                display_order=None,
                is_default=None,
                file=None,
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @patch('pecha_api.ambient_sounds.ambient_sound_service.SessionLocal')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.get_ambient_sound_by_id')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.validate_cms_author_details')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.require_super_admin')
    def test_update_not_found(self, mock_require_super_admin, mock_validate_author, mock_get, mock_session):
        mock_validate_author.return_value = TestDataFactory.create_mock_author()
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            update_ambient_sound_service(
                token="admin_token",
                ambient_sound_id=uuid4(),
                name="New name",
                display_order=None,
                is_default=None,
                file=None,
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @patch('pecha_api.ambient_sounds.ambient_sound_service.SessionLocal')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.get_ambient_sound_by_id')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.update_ambient_sound')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.unset_other_defaults')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.generate_presigned_access_url')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.validate_cms_author_details')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.require_super_admin')
    def test_update_partial_name_only(
        self, mock_require_super_admin, mock_validate_author, mock_presign, mock_unset_defaults,
        mock_update, mock_get, mock_session
    ):
        mock_validate_author.return_value = TestDataFactory.create_mock_author()
        mock_presign.return_value = "https://signed.example.com/sound.mp3"
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        existing = TestDataFactory.create_mock_ambient_sound(name="Old name")
        mock_get.return_value = existing
        mock_update.return_value = existing

        result = update_ambient_sound_service(
            token="admin_token",
            ambient_sound_id=existing.id,
            name="New name",
            display_order=None,
            is_default=None,
            file=None,
        )

        assert existing.name == "New name"
        mock_unset_defaults.assert_not_called()
        assert result.id == existing.id

    @patch('pecha_api.ambient_sounds.ambient_sound_service.delete_file')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.SessionLocal')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.get_ambient_sound_by_id')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.update_ambient_sound')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.upload_file')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.generate_presigned_access_url')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.validate_cms_author_details')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.require_super_admin')
    def test_update_replaces_file_and_deletes_old(
        self, mock_require_super_admin, mock_validate_author, mock_presign, mock_upload,
        mock_update, mock_get, mock_session, mock_delete_file
    ):
        mock_validate_author.return_value = TestDataFactory.create_mock_author()
        mock_presign.return_value = "https://signed.example.com/new.mp3"
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        old_key = "audio/ambient_sounds/old-key.mp3"
        existing = TestDataFactory.create_mock_ambient_sound(name="Rain", s3_key=old_key)
        mock_get.return_value = existing
        mock_update.return_value = existing

        new_file = TestDataFactory.create_mock_upload_file(filename="new-rain.mp3")

        update_ambient_sound_service(
            token="admin_token",
            ambient_sound_id=existing.id,
            name=None,
            display_order=None,
            is_default=None,
            file=new_file,
        )

        mock_upload.assert_called_once()
        mock_delete_file.assert_called_once_with(old_key)


class TestDeleteAmbientSoundService:
    @patch('pecha_api.ambient_sounds.ambient_sound_service.require_super_admin')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.validate_cms_author_details')
    def test_delete_forbidden_when_not_admin(self, mock_validate_author, mock_require_super_admin):
        mock_validate_author.return_value = TestDataFactory.create_mock_author()
        mock_require_super_admin.side_effect = HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="FORBIDDEN"
        )

        with pytest.raises(HTTPException) as exc_info:
            delete_ambient_sound_service(token="author_token", ambient_sound_id=uuid4())

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @patch('pecha_api.ambient_sounds.ambient_sound_service.SessionLocal')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.get_ambient_sound_by_id')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.validate_cms_author_details')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.require_super_admin')
    def test_delete_not_found(self, mock_require_super_admin, mock_validate_author, mock_get, mock_session):
        mock_validate_author.return_value = TestDataFactory.create_mock_author()
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            delete_ambient_sound_service(token="admin_token", ambient_sound_id=uuid4())

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @patch('pecha_api.ambient_sounds.ambient_sound_service.delete_file')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.SessionLocal')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.get_ambient_sound_by_id')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.delete_ambient_sound')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.validate_cms_author_details')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.require_super_admin')
    def test_delete_success(
        self, mock_require_super_admin, mock_validate_author, mock_delete_repo, mock_get,
        mock_session, mock_delete_file
    ):
        mock_validate_author.return_value = TestDataFactory.create_mock_author()
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        s3_key = "audio/ambient_sounds/rain.mp3"
        existing = TestDataFactory.create_mock_ambient_sound(s3_key=s3_key)
        mock_get.return_value = existing

        delete_ambient_sound_service(token="admin_token", ambient_sound_id=existing.id)

        mock_delete_repo.assert_called_once_with(mock_db, existing)
        # No cover on this row, so only the audio object goes.
        mock_delete_file.assert_called_once_with(s3_key)

    @patch('pecha_api.ambient_sounds.ambient_sound_service.delete_file')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.SessionLocal')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.get_ambient_sound_by_id')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.delete_ambient_sound')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.validate_cms_author_details')
    @patch('pecha_api.ambient_sounds.ambient_sound_service.require_super_admin')
    def test_delete_also_removes_the_cover(
        self, mock_require_super_admin, mock_validate_author, mock_delete_repo, mock_get,
        mock_session, mock_delete_file
    ):
        """The cover belongs to the sound, so it goes with it."""
        mock_validate_author.return_value = TestDataFactory.create_mock_author()
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        s3_key = "audio/ambient_sounds/rain.mp3"
        image_s3_key = "images/ambient_sounds/rain.webp"
        existing = TestDataFactory.create_mock_ambient_sound(
            s3_key=s3_key, image_s3_key=image_s3_key
        )
        mock_get.return_value = existing

        delete_ambient_sound_service(token="admin_token", ambient_sound_id=existing.id)

        assert mock_delete_file.call_count == 2
        deleted = {call.args[0] for call in mock_delete_file.call_args_list}
        assert deleted == {s3_key, image_s3_key}
