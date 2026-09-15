import pytest
from unittest.mock import patch, MagicMock
from uuid import uuid4
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from starlette import status

from pecha_api.ambient_sounds.ambient_sound_views import get_all_ambient_sounds
from pecha_api.ambient_sounds.ambient_sound_cms_views import (
    create_ambient_sound,
    update_ambient_sound,
    delete_ambient_sound,
)
from pecha_api.ambient_sounds.ambient_sound_response_models import (
    AmbientSoundDTO,
    AmbientSoundsResponse,
)


def create_auth_credentials(token="valid_token") -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def create_ambient_sound_dto(name="Sea waves", is_default=True, display_order=0) -> AmbientSoundDTO:
    return AmbientSoundDTO(
        id=uuid4(),
        name=name,
        url="https://signed.example.com/audio.mp3",
        is_default=is_default,
        display_order=display_order,
    )


class TestGetAllAmbientSounds:
    @patch('pecha_api.ambient_sounds.ambient_sound_views.get_all_ambient_sounds_service')
    @pytest.mark.asyncio
    async def test_get_all_ambient_sounds_success(self, mock_service):
        expected = AmbientSoundsResponse(sounds=[create_ambient_sound_dto()])
        mock_service.return_value = expected

        result = await get_all_ambient_sounds()

        assert result == expected
        mock_service.assert_called_once_with()


class TestCreateAmbientSoundView:
    @patch('pecha_api.ambient_sounds.ambient_sound_cms_views.create_ambient_sound_service')
    @pytest.mark.asyncio
    async def test_create_ambient_sound_success(self, mock_service):
        token = "admin_token"
        auth_credentials = create_auth_credentials(token=token)
        file = MagicMock()
        expected = create_ambient_sound_dto()
        mock_service.return_value = expected

        result = await create_ambient_sound(
            credentials=auth_credentials,
            name="Sea waves",
            display_order=0,
            is_default=True,
            file=file,
        )

        assert result == expected
        mock_service.assert_called_once_with(
            token=token,
            name="Sea waves",
            display_order=0,
            is_default=True,
            file=file,
        )

    @patch('pecha_api.ambient_sounds.ambient_sound_cms_views.create_ambient_sound_service')
    @pytest.mark.asyncio
    async def test_create_ambient_sound_forbidden(self, mock_service):
        auth_credentials = create_auth_credentials(token="user_token")
        file = MagicMock()
        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )

        with pytest.raises(HTTPException) as exc_info:
            await create_ambient_sound(
                credentials=auth_credentials,
                name="Sea waves",
                display_order=0,
                is_default=True,
                file=file,
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


class TestUpdateAmbientSoundView:
    @patch('pecha_api.ambient_sounds.ambient_sound_cms_views.update_ambient_sound_service')
    @pytest.mark.asyncio
    async def test_update_ambient_sound_success(self, mock_service):
        token = "admin_token"
        ambient_sound_id = uuid4()
        auth_credentials = create_auth_credentials(token=token)
        expected = create_ambient_sound_dto(name="Renamed")
        mock_service.return_value = expected

        result = await update_ambient_sound(
            ambient_sound_id=ambient_sound_id,
            credentials=auth_credentials,
            name="Renamed",
            display_order=None,
            is_default=None,
            file=None,
        )

        assert result == expected
        mock_service.assert_called_once_with(
            token=token,
            ambient_sound_id=ambient_sound_id,
            name="Renamed",
            display_order=None,
            is_default=None,
            file=None,
        )

    @patch('pecha_api.ambient_sounds.ambient_sound_cms_views.update_ambient_sound_service')
    @pytest.mark.asyncio
    async def test_update_ambient_sound_not_found(self, mock_service):
        auth_credentials = create_auth_credentials(token="admin_token")
        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Not found", "message": "Ambient sound not found"},
        )

        with pytest.raises(HTTPException) as exc_info:
            await update_ambient_sound(
                ambient_sound_id=uuid4(),
                credentials=auth_credentials,
                name=None,
                display_order=None,
                is_default=None,
                file=None,
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


class TestDeleteAmbientSoundView:
    @patch('pecha_api.ambient_sounds.ambient_sound_cms_views.delete_ambient_sound_service')
    @pytest.mark.asyncio
    async def test_delete_ambient_sound_success(self, mock_service):
        token = "admin_token"
        ambient_sound_id = uuid4()
        auth_credentials = create_auth_credentials(token=token)
        mock_service.return_value = None

        await delete_ambient_sound(ambient_sound_id=ambient_sound_id, credentials=auth_credentials)

        mock_service.assert_called_once_with(token=token, ambient_sound_id=ambient_sound_id)
