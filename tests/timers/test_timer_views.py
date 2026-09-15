import pytest
from unittest.mock import patch, MagicMock
from uuid import uuid4
from datetime import datetime
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from starlette import status

from pecha_api.timers.timer_views import (
    get_all_timers,
    get_user_timers,
    create_user_timer,
    update_user_timer,
    delete_user_timer,
    record_timer_stop,
    get_user_timer_history
)
from pecha_api.timers.timer_response_models import (
    TimersResponse,
    TimerDTO,
    CreateTimerRequest,
    UpdateTimerRequest,
    RecordTimerStopRequest,
    TimerHistoryResponse,
    TimerHistoryDTO,
    TimerSessionDTO
)
from pecha_api.timers.timer_enums import TimerType


class TestDataFactory:
    """Factory for creating test data objects."""
    
    @staticmethod
    def create_auth_credentials(token="valid_token") -> HTTPAuthorizationCredentials:
        """Create HTTPAuthorizationCredentials with specified token."""
        return HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials=token
        )
    
    @staticmethod
    def create_timer_dto(
        timer_id=None,
        user_id=None,
        group_id="_default",
        timer_type=TimerType.USER,
        name="Test Timer",
        duration=300,
        description=None,
        audio_url=None,
        image_url=None
    ) -> TimerDTO:
        """Create a TimerDTO with specified attributes."""
        return TimerDTO(
            id=timer_id or uuid4(),
            user_id=user_id or uuid4(),
            group_id=uuid4() if group_id == "_default" else group_id,
            type=timer_type,
            name=name,
            description=description,
            duration=duration,
            audio_url=audio_url,
            image_url=image_url,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
    
    @staticmethod
    def create_timers_response(timers=None, total=0, skip=0, limit=20) -> TimersResponse:
        """Create a TimersResponse with specified timers."""
        return TimersResponse(
            timers=timers or [],
            total=total,
            skip=skip,
            limit=limit
        )
    
    @staticmethod
    def create_timer_request(
        group_id="_default",
        name="New Timer",
        duration=600,
        description=None,
        audio_url=None,
        image_url=None
    ) -> CreateTimerRequest:
        """Create a CreateTimerRequest with specified attributes."""
        return CreateTimerRequest(
            group_id=uuid4() if group_id == "_default" else group_id,
            name=name,
            description=description,
            duration=duration,
            audio_url=audio_url,
            image_url=image_url
        )
    
    @staticmethod
    def create_update_request(
        name=None,
        duration=None,
        description=None,
        audio_url=None,
        image_url=None
    ) -> UpdateTimerRequest:
        """Create an UpdateTimerRequest with specified attributes."""
        return UpdateTimerRequest(
            name=name,
            description=description,
            duration=duration,
            audio_url=audio_url,
            image_url=image_url
        )


class TestGetAllTimers:
    """Test cases for get_all_timers endpoint."""
    
    @patch('pecha_api.timers.timer_views.get_all_timers_service')
    @pytest.mark.asyncio
    async def test_get_all_timers_success(self, mock_service):
        """Test successful retrieval of all timers with pagination."""
        group_id = uuid4()
        timer1 = TestDataFactory.create_timer_dto(group_id=group_id, name="Timer 1")
        timer2 = TestDataFactory.create_timer_dto(group_id=group_id, name="Timer 2")
        
        mock_response = TestDataFactory.create_timers_response(
            timers=[timer1, timer2],
            total=2,
            skip=0,
            limit=20
        )
        mock_service.return_value = mock_response
        
        result = await get_all_timers(group_id=group_id, skip=0, limit=20)
        
        assert isinstance(result, TimersResponse)
        assert len(result.timers) == 2
        assert result.total == 2
        assert result.skip == 0
        assert result.limit == 20
        assert result.timers[0].name == "Timer 1"
        assert result.timers[1].name == "Timer 2"
        
        mock_service.assert_called_once_with(group_id=group_id, skip=0, limit=20)
    
    @patch('pecha_api.timers.timer_views.get_all_timers_service')
    @pytest.mark.asyncio
    async def test_get_all_timers_empty_list(self, mock_service):
        """Test get_all_timers when no timers exist for group."""
        group_id = uuid4()
        
        mock_response = TestDataFactory.create_timers_response(
            timers=[],
            total=0,
            skip=0,
            limit=20
        )
        mock_service.return_value = mock_response
        
        result = await get_all_timers(group_id=group_id, skip=0, limit=20)
        
        assert isinstance(result, TimersResponse)
        assert len(result.timers) == 0
        assert result.total == 0
        
        mock_service.assert_called_once_with(group_id=group_id, skip=0, limit=20)
    
    @patch('pecha_api.timers.timer_views.get_all_timers_service')
    @pytest.mark.asyncio
    async def test_get_all_timers_pagination(self, mock_service):
        """Test get_all_timers with custom pagination parameters."""
        group_id = uuid4()
        timer1 = TestDataFactory.create_timer_dto(group_id=group_id)
        
        mock_response = TestDataFactory.create_timers_response(
            timers=[timer1],
            total=10,
            skip=5,
            limit=1
        )
        mock_service.return_value = mock_response
        
        result = await get_all_timers(group_id=group_id, skip=5, limit=1)
        
        assert result.skip == 5
        assert result.limit == 1
        assert result.total == 10
        
        mock_service.assert_called_once_with(group_id=group_id, skip=5, limit=1)
    
    @patch('pecha_api.timers.timer_views.get_all_timers_service')
    @pytest.mark.asyncio
    async def test_get_all_timers_without_group_id(self, mock_service):
        """Test get_all_timers without group_id filter (returns all timers)."""
        timer1 = TestDataFactory.create_timer_dto(name="Timer 1")
        timer2 = TestDataFactory.create_timer_dto(name="Timer 2")
        
        mock_response = TestDataFactory.create_timers_response(
            timers=[timer1, timer2],
            total=2,
            skip=0,
            limit=20
        )
        mock_service.return_value = mock_response
        
        result = await get_all_timers(group_id=None, skip=0, limit=20)
        
        assert isinstance(result, TimersResponse)
        assert len(result.timers) == 2
        assert result.total == 2
        
        mock_service.assert_called_once_with(group_id=None, skip=0, limit=20)


class TestGetUserTimers:
    """Test cases for get_user_timers endpoint."""
    
    @patch('pecha_api.timers.timer_views.get_user_timers_service')
    @patch('pecha_api.timers.timer_views.validate_and_extract_user_details')
    @pytest.mark.asyncio
    async def test_get_user_timers_success(self, mock_validate, mock_service):
        """Test successful retrieval of user's timers."""
        user_id = uuid4()
        group_id = uuid4()
        token = "valid_token"
        
        mock_user = MagicMock()
        mock_user.id = user_id
        mock_validate.return_value = mock_user
        
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        
        timer1 = TestDataFactory.create_timer_dto(user_id=user_id, group_id=group_id, name="My Timer 1")
        timer2 = TestDataFactory.create_timer_dto(user_id=user_id, group_id=group_id, name="My Timer 2")
        
        mock_response = TestDataFactory.create_timers_response(
            timers=[timer1, timer2],
            total=2,
            skip=0,
            limit=20
        )
        mock_service.return_value = mock_response
        
        result = await get_user_timers(
            group_id=group_id,
            skip=0,
            limit=20,
            credentials=auth_credentials
        )
        
        assert isinstance(result, TimersResponse)
        assert len(result.timers) == 2
        assert result.total == 2
        assert result.timers[0].user_id == user_id
        assert result.timers[1].user_id == user_id
        
        mock_validate.assert_called_once_with(token=token)
        mock_service.assert_called_once_with(
            user_id=user_id,
            group_id=group_id,
            skip=0,
            limit=20
        )
    
    @patch('pecha_api.timers.timer_views.get_user_timers_service')
    @patch('pecha_api.timers.timer_views.validate_and_extract_user_details')
    @pytest.mark.asyncio
    async def test_get_user_timers_empty_list(self, mock_validate, mock_service):
        """Test get_user_timers when user has no timers."""
        user_id = uuid4()
        group_id = uuid4()
        token = "valid_token"
        
        mock_user = MagicMock()
        mock_user.id = user_id
        mock_validate.return_value = mock_user
        
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        
        mock_response = TestDataFactory.create_timers_response(
            timers=[],
            total=0,
            skip=0,
            limit=20
        )
        mock_service.return_value = mock_response
        
        result = await get_user_timers(
            group_id=group_id,
            skip=0,
            limit=20,
            credentials=auth_credentials
        )
        
        assert len(result.timers) == 0
        assert result.total == 0
    
    @patch('pecha_api.timers.timer_views.get_user_timers_service')
    @patch('pecha_api.timers.timer_views.validate_and_extract_user_details')
    @pytest.mark.asyncio
    async def test_get_user_timers_without_group_id(self, mock_validate, mock_service):
        """Test get_user_timers without group_id filter (returns all user timers)."""
        user_id = uuid4()
        token = "valid_token"
        
        mock_user = MagicMock()
        mock_user.id = user_id
        mock_validate.return_value = mock_user
        
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        
        timer1 = TestDataFactory.create_timer_dto(user_id=user_id, name="My Timer 1")
        timer2 = TestDataFactory.create_timer_dto(user_id=user_id, name="My Timer 2")
        
        mock_response = TestDataFactory.create_timers_response(
            timers=[timer1, timer2],
            total=2,
            skip=0,
            limit=20
        )
        mock_service.return_value = mock_response
        
        result = await get_user_timers(
            group_id=None,
            skip=0,
            limit=20,
            credentials=auth_credentials
        )
        
        assert isinstance(result, TimersResponse)
        assert len(result.timers) == 2
        
        mock_validate.assert_called_once_with(token=token)
        mock_service.assert_called_once_with(
            user_id=user_id,
            group_id=None,
            skip=0,
            limit=20
        )
    
    @patch('pecha_api.timers.timer_views.validate_and_extract_user_details')
    @pytest.mark.asyncio
    async def test_get_user_timers_invalid_token(self, mock_validate):
        """Test get_user_timers with invalid authentication token."""
        group_id = uuid4()
        token = "invalid_token"
        
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        
        mock_validate.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )
        
        with pytest.raises(HTTPException) as exc_info:
            await get_user_timers(
                group_id=group_id,
                skip=0,
                limit=20,
                credentials=auth_credentials
            )
        
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


class TestCreateUserTimer:
    """Test cases for create_user_timer endpoint."""
    
    @patch('pecha_api.timers.timer_views.create_timer_service')
    @pytest.mark.asyncio
    async def test_create_user_timer_success(self, mock_service):
        """Test successful creation of user timer."""
        token = "valid_token"
        group_id = uuid4()
        
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        request = TestDataFactory.create_timer_request(
            group_id=group_id,
            name="New Timer",
            duration=600
        )
        
        created_timer = TestDataFactory.create_timer_dto(
            group_id=group_id,
            name="New Timer",
            duration=600,
            timer_type=TimerType.USER
        )
        mock_service.return_value = created_timer
        
        result = await create_user_timer(
            request=request,
            credentials=auth_credentials
        )
        
        assert isinstance(result, TimerDTO)
        assert result.name == "New Timer"
        assert result.duration == 600
        assert result.type == TimerType.USER
        
        mock_service.assert_called_once_with(token=token, request=request)
    
    @patch('pecha_api.timers.timer_views.create_timer_service')
    @pytest.mark.asyncio
    async def test_create_user_timer_invalid_token(self, mock_service):
        """Test create_user_timer with invalid authentication token."""
        token = "invalid_token"
        group_id = uuid4()
        
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        request = TestDataFactory.create_timer_request(group_id=group_id)
        
        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )
        
        with pytest.raises(HTTPException) as exc_info:
            await create_user_timer(
                request=request,
                credentials=auth_credentials
            )
        
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    
    @patch('pecha_api.timers.timer_views.create_timer_service')
    @pytest.mark.asyncio
    async def test_create_user_timer_with_audio_url(self, mock_service):
        """Test creating timer with audio URL."""
        token = "valid_token"
        group_id = uuid4()
        audio_url = "audio/timer_sounds/bell.mp3"
        
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        request = TestDataFactory.create_timer_request(
            group_id=group_id,
            name="Timer with Audio",
            duration=300,
            description="Meditation timer",
            audio_url=audio_url
        )
        
        created_timer = TestDataFactory.create_timer_dto(
            group_id=group_id,
            name="Timer with Audio",
            duration=300,
            description="Meditation timer",
            audio_url="https://presigned-url.com/audio/timer_sounds/bell.mp3"
        )
        mock_service.return_value = created_timer
        
        result = await create_user_timer(
            request=request,
            credentials=auth_credentials
        )
        
        assert result.audio_url is not None
        assert result.description == "Meditation timer"

    @patch('pecha_api.timers.timer_views.create_timer_service')
    @pytest.mark.asyncio
    async def test_create_user_timer_without_group_id(self, mock_service):
        """Test creating a personal timer with no group."""
        token = "valid_token"

        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        request = TestDataFactory.create_timer_request(
            group_id=None,
            name="Personal Timer",
            duration=600
        )

        created_timer = TestDataFactory.create_timer_dto(
            group_id=None,
            name="Personal Timer",
            duration=600,
            timer_type=TimerType.USER
        )
        mock_service.return_value = created_timer

        result = await create_user_timer(
            request=request,
            credentials=auth_credentials
        )

        assert result.group_id is None
        assert result.name == "Personal Timer"
        mock_service.assert_called_once_with(token=token, request=request)

    @patch('pecha_api.timers.timer_views.create_timer_service')
    @pytest.mark.asyncio
    async def test_create_user_timer_with_image_url(self, mock_service):
        """Test creating timer with image URL."""
        token = "valid_token"
        image_url = "images/timer_covers/bell.png"

        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        request = TestDataFactory.create_timer_request(
            group_id=None,
            name="Timer with Image",
            duration=300,
            image_url=image_url
        )

        created_timer = TestDataFactory.create_timer_dto(
            group_id=None,
            name="Timer with Image",
            duration=300,
            image_url="https://presigned-url.com/images/timer_covers/bell.png"
        )
        mock_service.return_value = created_timer

        result = await create_user_timer(
            request=request,
            credentials=auth_credentials
        )

        assert result.image_url is not None
        assert result.group_id is None


class TestUpdateUserTimer:
    """Test cases for update_user_timer endpoint."""
    
    @patch('pecha_api.timers.timer_views.update_timer_service')
    @pytest.mark.asyncio
    async def test_update_user_timer_success(self, mock_service):
        """Test successful update of user timer."""
        token = "valid_token"
        timer_id = uuid4()
        
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        request = TestDataFactory.create_update_request(
            name="Updated Timer",
            duration=900
        )
        
        updated_timer = TestDataFactory.create_timer_dto(
            timer_id=timer_id,
            name="Updated Timer",
            duration=900
        )
        mock_service.return_value = updated_timer
        
        result = await update_user_timer(
            timer_id=timer_id,
            request=request,
            credentials=auth_credentials
        )
        
        assert isinstance(result, TimerDTO)
        assert result.name == "Updated Timer"
        assert result.duration == 900
        
        mock_service.assert_called_once_with(
            token=token,
            timer_id=timer_id,
            request=request
        )
    
    @patch('pecha_api.timers.timer_views.update_timer_service')
    @pytest.mark.asyncio
    async def test_update_user_timer_not_found(self, mock_service):
        """Test update_user_timer when timer doesn't exist."""
        token = "valid_token"
        timer_id = uuid4()
        
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        request = TestDataFactory.create_update_request(name="Updated")
        
        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "NOT_FOUND", "message": "Timer not found"}
        )
        
        with pytest.raises(HTTPException) as exc_info:
            await update_user_timer(
                timer_id=timer_id,
                request=request,
                credentials=auth_credentials
            )
        
        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    
    @patch('pecha_api.timers.timer_views.update_timer_service')
    @pytest.mark.asyncio
    async def test_update_user_timer_forbidden(self, mock_service):
        """Test update_user_timer when user is not the owner."""
        token = "valid_token"
        timer_id = uuid4()
        
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        request = TestDataFactory.create_update_request(name="Updated")
        
        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "FORBIDDEN", "message": "You don't have permission to update this timer"}
        )
        
        with pytest.raises(HTTPException) as exc_info:
            await update_user_timer(
                timer_id=timer_id,
                request=request,
                credentials=auth_credentials
            )
        
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    
    @patch('pecha_api.timers.timer_views.update_timer_service')
    @pytest.mark.asyncio
    async def test_update_user_timer_preset_forbidden(self, mock_service):
        """Test update_user_timer when trying to update preset timer."""
        token = "valid_token"
        timer_id = uuid4()
        
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        request = TestDataFactory.create_update_request(name="Updated")
        
        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "FORBIDDEN", "message": "Only user-created timers can be updated"}
        )
        
        with pytest.raises(HTTPException) as exc_info:
            await update_user_timer(
                timer_id=timer_id,
                request=request,
                credentials=auth_credentials
            )
        
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    
    @patch('pecha_api.timers.timer_views.update_timer_service')
    @pytest.mark.asyncio
    async def test_update_user_timer_invalid_token(self, mock_service):
        """Test update_user_timer with invalid authentication token."""
        token = "invalid_token"
        timer_id = uuid4()
        
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        request = TestDataFactory.create_update_request(name="Updated")
        
        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )
        
        with pytest.raises(HTTPException) as exc_info:
            await update_user_timer(
                timer_id=timer_id,
                request=request,
                credentials=auth_credentials
            )
        
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


class TestDeleteUserTimer:
    """Test cases for delete_user_timer endpoint."""
    
    @patch('pecha_api.timers.timer_views.delete_timer_service')
    @pytest.mark.asyncio
    async def test_delete_user_timer_success(self, mock_service):
        """Test successful deletion of user timer."""
        token = "valid_token"
        timer_id = uuid4()
        
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        
        mock_service.return_value = None
        
        result = await delete_user_timer(
            timer_id=timer_id,
            credentials=auth_credentials
        )
        
        assert result is None
        mock_service.assert_called_once_with(token=token, timer_id=timer_id)
    
    @patch('pecha_api.timers.timer_views.delete_timer_service')
    @pytest.mark.asyncio
    async def test_delete_user_timer_not_found(self, mock_service):
        """Test delete_user_timer when timer doesn't exist."""
        token = "valid_token"
        timer_id = uuid4()
        
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        
        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "NOT_FOUND", "message": "Timer not found"}
        )
        
        with pytest.raises(HTTPException) as exc_info:
            await delete_user_timer(
                timer_id=timer_id,
                credentials=auth_credentials
            )
        
        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    
    @patch('pecha_api.timers.timer_views.delete_timer_service')
    @pytest.mark.asyncio
    async def test_delete_user_timer_forbidden(self, mock_service):
        """Test delete_user_timer when user is not the owner."""
        token = "valid_token"
        timer_id = uuid4()
        
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        
        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "FORBIDDEN", "message": "You don't have permission to delete this timer"}
        )
        
        with pytest.raises(HTTPException) as exc_info:
            await delete_user_timer(
                timer_id=timer_id,
                credentials=auth_credentials
            )
        
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    
    @patch('pecha_api.timers.timer_views.delete_timer_service')
    @pytest.mark.asyncio
    async def test_delete_user_timer_preset_forbidden(self, mock_service):
        """Test delete_user_timer when trying to delete preset timer."""
        token = "valid_token"
        timer_id = uuid4()
        
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        
        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "FORBIDDEN", "message": "Only user-created timers can be deleted"}
        )
        
        with pytest.raises(HTTPException) as exc_info:
            await delete_user_timer(
                timer_id=timer_id,
                credentials=auth_credentials
            )
        
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    
    @patch('pecha_api.timers.timer_views.delete_timer_service')
    @pytest.mark.asyncio
    async def test_delete_user_timer_invalid_token(self, mock_service):
        """Test delete_user_timer with invalid authentication token."""
        token = "invalid_token"
        timer_id = uuid4()
        
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        
        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )
        
        with pytest.raises(HTTPException) as exc_info:
            await delete_user_timer(
                timer_id=timer_id,
                credentials=auth_credentials
            )
        
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


class TestRecordTimerStop:
    """Test cases for record_timer_stop endpoint."""
    
    @patch('pecha_api.timers.timer_views.record_timer_stop_service')
    @pytest.mark.asyncio
    async def test_record_timer_stop_success(self, mock_service):
        """Test successful recording of timer stop."""
        token = "valid_token"
        timer_id = uuid4()
        
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        request = RecordTimerStopRequest(timer_id=timer_id, duration=600)
        
        mock_service.return_value = None
        
        result = await record_timer_stop(request=request, credentials=auth_credentials)
        
        assert result == {"message": "Timer session recorded successfully"}
        mock_service.assert_called_once_with(token=token, request=request)
    
    @patch('pecha_api.timers.timer_views.record_timer_stop_service')
    @pytest.mark.asyncio
    async def test_record_timer_stop_timer_not_found(self, mock_service):
        """Test record_timer_stop when timer doesn't exist."""
        token = "valid_token"
        timer_id = uuid4()
        
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        request = RecordTimerStopRequest(timer_id=timer_id, duration=600)
        
        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "NOT_FOUND", "message": "Timer not found"}
        )
        
        with pytest.raises(HTTPException) as exc_info:
            await record_timer_stop(request=request, credentials=auth_credentials)
        
        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    
    @patch('pecha_api.timers.timer_views.record_timer_stop_service')
    @pytest.mark.asyncio
    async def test_record_timer_stop_invalid_token(self, mock_service):
        """Test record_timer_stop with invalid authentication token."""
        token = "invalid_token"
        timer_id = uuid4()
        
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        request = RecordTimerStopRequest(timer_id=timer_id, duration=600)
        
        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )
        
        with pytest.raises(HTTPException) as exc_info:
            await record_timer_stop(request=request, credentials=auth_credentials)
        
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


class TestGetUserTimerHistory:
    """Test cases for get_user_timer_history endpoint."""
    
    @patch('pecha_api.timers.timer_views.get_timer_history_service')
    @pytest.mark.asyncio
    async def test_get_user_timer_history_success(self, mock_service):
        """Test successful retrieval of user's timer history."""
        token = "valid_token"
        timer_id = uuid4()
        
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        
        mock_response = TimerHistoryResponse(
            timers=[
                TimerHistoryDTO(
                    timer_id=timer_id,
                    name="Meditation Timer",
                    description="Daily meditation",
                    actual_duration=600,
                    total_time_spent=3600,
                    sessions=[
                        TimerSessionDTO(duration=600, created_at=datetime.utcnow()),
                        TimerSessionDTO(duration=600, created_at=datetime.utcnow())
                    ]
                )
            ],
            total=1,
            skip=0,
            limit=20
        )
        mock_service.return_value = mock_response
        
        result = await get_user_timer_history(
            credentials=auth_credentials,
            skip=0,
            limit=20
        )
        
        assert isinstance(result, TimerHistoryResponse)
        assert len(result.timers) == 1
        assert result.timers[0].name == "Meditation Timer"
        assert result.timers[0].total_time_spent == 3600
        assert len(result.timers[0].sessions) == 2
        
        mock_service.assert_called_once_with(token=token, skip=0, limit=20)
    
    @patch('pecha_api.timers.timer_views.get_timer_history_service')
    @pytest.mark.asyncio
    async def test_get_user_timer_history_empty(self, mock_service):
        """Test get_user_timer_history when user has no history."""
        token = "valid_token"
        
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        
        mock_response = TimerHistoryResponse(
            timers=[],
            total=0,
            skip=0,
            limit=20
        )
        mock_service.return_value = mock_response
        
        result = await get_user_timer_history(
            credentials=auth_credentials,
            skip=0,
            limit=20
        )
        
        assert len(result.timers) == 0
        assert result.total == 0
    
    @patch('pecha_api.timers.timer_views.get_timer_history_service')
    @pytest.mark.asyncio
    async def test_get_user_timer_history_pagination(self, mock_service):
        """Test get_user_timer_history with custom pagination."""
        token = "valid_token"
        timer_id = uuid4()
        
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        
        mock_response = TimerHistoryResponse(
            timers=[
                TimerHistoryDTO(
                    timer_id=timer_id,
                    name="Timer",
                    actual_duration=300,
                    total_time_spent=900,
                    sessions=[]
                )
            ],
            total=10,
            skip=5,
            limit=1
        )
        mock_service.return_value = mock_response
        
        result = await get_user_timer_history(
            credentials=auth_credentials,
            skip=5,
            limit=1
        )
        
        assert result.skip == 5
        assert result.limit == 1
        assert result.total == 10
        
        mock_service.assert_called_once_with(token=token, skip=5, limit=1)
    
    @patch('pecha_api.timers.timer_views.get_timer_history_service')
    @pytest.mark.asyncio
    async def test_get_user_timer_history_invalid_token(self, mock_service):
        """Test get_user_timer_history with invalid authentication token."""
        token = "invalid_token"
        
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        
        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )
        
        with pytest.raises(HTTPException) as exc_info:
            await get_user_timer_history(
                credentials=auth_credentials,
                skip=0,
                limit=20
            )
        
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
