import pytest
from unittest.mock import patch, call, MagicMock
from uuid import uuid4
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from starlette import status

from pecha_api.timers.timer_service import (
    get_all_timers_service,
    get_user_timers_service,
    create_timer_service,
    update_timer_service,
    delete_timer_service,
    restore_timer_service,
    convert_timer_to_dto,
    is_user_created_timer,
    record_timer_stop_service,
    get_timer_history_service
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
from pecha_api.timers.timer_model import Timer
from pecha_api.timers.timer_history_model import TimerHistory
from pecha_api.timers.timer_enums import TimerType


class TestDataFactory:
    """Factory for creating test data objects."""
    
    @staticmethod
    def create_mock_timer(
        timer_id=None,
        user_id=None,
        group_id="_default",
        timer_type=TimerType.USER,
        name="Test Timer",
        duration=300,
        description=None,
        ambient_sound_id=None,
        bell_at_start=True,
        bell_at_end=True,
        parent_preset_id=None,
        deleted_at=None
    ):
        """Create a mock Timer model."""
        timer = MagicMock(spec=Timer)
        timer.id = timer_id or uuid4()
        timer.user_id = user_id or uuid4()
        timer.group_id = uuid4() if group_id == "_default" else group_id
        timer.type = timer_type
        timer.name = name
        timer.description = description
        timer.duration = duration
        timer.ambient_sound_id = ambient_sound_id
        timer.bell_at_start = bell_at_start
        timer.bell_at_end = bell_at_end
        timer.parent_preset_id = parent_preset_id
        timer.deleted_at = deleted_at
        timer.created_at = datetime.utcnow()
        timer.updated_at = datetime.utcnow()
        return timer
    
    @staticmethod
    def create_mock_user(user_id=None):
        """Create a mock user."""
        user = MagicMock()
        user.id = user_id or uuid4()
        user.email = "test@example.com"
        return user
    
    @staticmethod
    def create_timer_request(
        group_id="_default",
        name="New Timer",
        duration=600,
        description=None,
        ambient_sound_id=None
    ) -> CreateTimerRequest:
        """Create a CreateTimerRequest."""
        return CreateTimerRequest(
            group_id=uuid4() if group_id == "_default" else group_id,
            name=name,
            description=description,
            duration=duration,
            ambient_sound_id=ambient_sound_id
        )

    @staticmethod
    def create_update_request(
        name=None,
        duration=None,
        description=None,
        ambient_sound_id=None
    ) -> UpdateTimerRequest:
        """Create an UpdateTimerRequest."""
        return UpdateTimerRequest(
            name=name,
            description=description,
            duration=duration,
            ambient_sound_id=ambient_sound_id
        )

    @staticmethod
    def create_mock_timer_history(
        history_id=None,
        timer_id=None,
        user_id=None,
        duration=600
    ):
        """Create a mock TimerHistory model."""
        history = MagicMock(spec=TimerHistory)
        history.id = history_id or uuid4()
        history.timer_id = timer_id or uuid4()
        history.user_id = user_id or uuid4()
        history.duration = duration
        history.created_at = datetime.utcnow()
        return history


class TestGetAllTimersService:
    """Test cases for get_all_timers_service function."""
    
    @patch('pecha_api.timers.timer_service.SessionLocal')
    @patch('pecha_api.timers.timer_service.get_timers_by_group')
    def test_get_all_timers_service_success(self, mock_get_timers, mock_session):
        """Test successful retrieval of all timers."""
        group_id = uuid4()
        
        # Setup mock database session
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        
        # Create mock timers
        timer1 = TestDataFactory.create_mock_timer(group_id=group_id, name="Timer 1")
        timer2 = TestDataFactory.create_mock_timer(group_id=group_id, name="Timer 2")
        
        mock_get_timers.return_value = ([timer1, timer2], 2)
        
        result = get_all_timers_service(group_id=group_id, skip=0, limit=20)
        
        assert isinstance(result, TimersResponse)
        assert len(result.timers) == 2
        assert result.total == 2
        assert result.skip == 0
        assert result.limit == 20
        
        mock_get_timers.assert_called_once_with(
            mock_db, group_id, 0, 20, user_id=None
        )
    
    @patch('pecha_api.timers.timer_service.SessionLocal')
    @patch('pecha_api.timers.timer_service.get_timers_by_group')
    def test_get_all_timers_service_empty(self, mock_get_timers, mock_session):
        """Test get_all_timers_service when no timers exist."""
        group_id = uuid4()
        
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        
        mock_get_timers.return_value = ([], 0)
        
        result = get_all_timers_service(group_id=group_id, skip=0, limit=20)
        
        assert len(result.timers) == 0
        assert result.total == 0
    
    @patch('pecha_api.timers.timer_service.SessionLocal')
    @patch('pecha_api.timers.timer_service.get_timers_by_group')
    def test_get_all_timers_service_pagination(self, mock_get_timers, mock_session):
        """Test get_all_timers_service with custom pagination."""
        group_id = uuid4()
        
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        
        timer1 = TestDataFactory.create_mock_timer(group_id=group_id)
        mock_get_timers.return_value = ([timer1], 10)
        
        result = get_all_timers_service(group_id=group_id, skip=5, limit=1)
        
        assert result.skip == 5
        assert result.limit == 1
        assert result.total == 10
        
        mock_get_timers.assert_called_once_with(
            mock_db, group_id, 5, 1, user_id=None
        )
    
    @patch('pecha_api.timers.timer_service.SessionLocal')
    @patch('pecha_api.timers.timer_service.get_timers_by_group')
    def test_get_all_timers_service_without_group_id(self, mock_get_timers, mock_session):
        """Test get_all_timers_service without group_id filter."""
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        
        timer1 = TestDataFactory.create_mock_timer(name="Timer 1")
        timer2 = TestDataFactory.create_mock_timer(name="Timer 2")
        
        mock_get_timers.return_value = ([timer1, timer2], 2)
        
        result = get_all_timers_service(group_id=None, skip=0, limit=20)
        
        assert isinstance(result, TimersResponse)
        assert len(result.timers) == 2
        assert result.total == 2
        
        mock_get_timers.assert_called_once_with(
            mock_db, None, 0, 20, user_id=None
        )

    @patch('pecha_api.timers.timer_service.SessionLocal')
    @patch('pecha_api.timers.timer_service.get_timers_by_group')
    def test_get_all_timers_service_hides_customized_presets_for_user(
        self, mock_get_timers, mock_session
    ):
        """An authenticated catalogue list is asked to drop presets the caller already copied."""
        user_id = uuid4()
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get_timers.return_value = ([], 0)

        get_all_timers_service(group_id=None, skip=0, limit=20, user_id=user_id)

        mock_get_timers.assert_called_once_with(
            mock_db, None, 0, 20, user_id=user_id
        )


class TestGetUserTimersService:
    """Test cases for get_user_timers_service function."""
    
    @patch('pecha_api.timers.timer_service.SessionLocal')
    @patch('pecha_api.timers.timer_service.get_user_timers_by_group')
    def test_get_user_timers_service_success(self, mock_get_timers, mock_session):
        """Test successful retrieval of user's timers."""
        user_id = uuid4()
        group_id = uuid4()
        
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        
        timer1 = TestDataFactory.create_mock_timer(user_id=user_id, group_id=group_id, name="My Timer 1")
        timer2 = TestDataFactory.create_mock_timer(user_id=user_id, group_id=group_id, name="My Timer 2")
        
        mock_get_timers.return_value = ([timer1, timer2], 2)
        
        result = get_user_timers_service(user_id=user_id, group_id=group_id, skip=0, limit=20)
        
        assert isinstance(result, TimersResponse)
        assert len(result.timers) == 2
        assert result.total == 2
        
        mock_get_timers.assert_called_once_with(mock_db, user_id, group_id, 0, 20)
    
    @patch('pecha_api.timers.timer_service.SessionLocal')
    @patch('pecha_api.timers.timer_service.get_user_timers_by_group')
    def test_get_user_timers_service_empty(self, mock_get_timers, mock_session):
        """Test get_user_timers_service when user has no timers."""
        user_id = uuid4()
        group_id = uuid4()
        
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        
        mock_get_timers.return_value = ([], 0)
        
        result = get_user_timers_service(user_id=user_id, group_id=group_id, skip=0, limit=20)
        
        assert len(result.timers) == 0
        assert result.total == 0
    
    @patch('pecha_api.timers.timer_service.SessionLocal')
    @patch('pecha_api.timers.timer_service.get_user_timers_by_group')
    def test_get_user_timers_service_without_group_id(self, mock_get_timers, mock_session):
        """Test get_user_timers_service without group_id filter."""
        user_id = uuid4()
        
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        
        timer1 = TestDataFactory.create_mock_timer(user_id=user_id, name="My Timer 1")
        timer2 = TestDataFactory.create_mock_timer(user_id=user_id, name="My Timer 2")
        
        mock_get_timers.return_value = ([timer1, timer2], 2)
        
        result = get_user_timers_service(user_id=user_id, group_id=None, skip=0, limit=20)
        
        assert isinstance(result, TimersResponse)
        assert len(result.timers) == 2
        assert result.total == 2
        
        mock_get_timers.assert_called_once_with(mock_db, user_id, None, 0, 20)


class TestCreateTimerService:
    """Test cases for create_timer_service function."""
    
    @patch('pecha_api.timers.timer_service.SessionLocal')
    @patch('pecha_api.timers.timer_service.save_timer')
    @patch('pecha_api.timers.timer_service.validate_and_extract_user_details')
    def test_create_timer_service_success(self, mock_validate, mock_save, mock_session):
        """Test successful creation of timer."""
        user_id = uuid4()
        group_id = uuid4()
        token = "valid_token"
        
        mock_user = TestDataFactory.create_mock_user(user_id=user_id)
        mock_validate.return_value = mock_user
        
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        
        request = TestDataFactory.create_timer_request(
            group_id=group_id,
            name="New Timer",
            duration=600
        )
        
        created_timer = TestDataFactory.create_mock_timer(
            user_id=user_id,
            group_id=group_id,
            name="New Timer",
            duration=600,
            timer_type=TimerType.USER
        )
        mock_save.return_value = created_timer
        
        result = create_timer_service(token=token, request=request)
        
        assert isinstance(result, TimerDTO)
        assert result.name == "New Timer"
        assert result.duration == 600
        assert result.type == TimerType.USER
        assert result.user_id == user_id
        
        mock_validate.assert_called_once_with(token=token)
        mock_save.assert_called_once()
    
    @patch('pecha_api.timers.timer_service.validate_and_extract_user_details')
    def test_create_timer_service_invalid_token(self, mock_validate):
        """Test create_timer_service with invalid token."""
        token = "invalid_token"
        request = TestDataFactory.create_timer_request()
        
        mock_validate.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )
        
        with pytest.raises(HTTPException) as exc_info:
            create_timer_service(token=token, request=request)
        
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    
    @patch('pecha_api.timers.timer_service.get_ambient_sound_by_id')
    @patch('pecha_api.timers.timer_service.SessionLocal')
    @patch('pecha_api.timers.timer_service.save_timer')
    @patch('pecha_api.timers.timer_service.validate_and_extract_user_details')
    def test_create_timer_service_with_optional_fields(self, mock_validate, mock_save, mock_session, mock_get_sound):
        """Test creating timer with optional fields."""
        user_id = uuid4()
        group_id = uuid4()
        ambient_sound_id = uuid4()
        token = "valid_token"

        mock_user = TestDataFactory.create_mock_user(user_id=user_id)
        mock_validate.return_value = mock_user

        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        mock_get_sound.return_value = MagicMock(id=ambient_sound_id)

        request = TestDataFactory.create_timer_request(
            group_id=group_id,
            name="Timer with Options",
            duration=300,
            description="Meditation timer",
            ambient_sound_id=ambient_sound_id
        )

        created_timer = TestDataFactory.create_mock_timer(
            user_id=user_id,
            group_id=group_id,
            name="Timer with Options",
            duration=300,
            description="Meditation timer",
            ambient_sound_id=ambient_sound_id
        )
        mock_save.return_value = created_timer

        result = create_timer_service(token=token, request=request)

        assert result.description == "Meditation timer"
        assert result.ambient_sound_id == ambient_sound_id
        mock_get_sound.assert_called_once_with(mock_db, ambient_sound_id)

    @patch('pecha_api.timers.timer_service.SessionLocal')
    @patch('pecha_api.timers.timer_service.save_timer')
    @patch('pecha_api.timers.timer_service.validate_and_extract_user_details')
    def test_create_timer_service_without_group_id(self, mock_validate, mock_save, mock_session):
        """Personal timers do not need a group."""
        user_id = uuid4()
        token = "valid_token"

        mock_user = TestDataFactory.create_mock_user(user_id=user_id)
        mock_validate.return_value = mock_user

        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        request = TestDataFactory.create_timer_request(
            group_id=None,
            name="Personal Timer",
            duration=600
        )

        created_timer = TestDataFactory.create_mock_timer(
            user_id=user_id,
            group_id=None,
            name="Personal Timer",
            duration=600,
            timer_type=TimerType.USER
        )
        mock_save.return_value = created_timer

        result = create_timer_service(token=token, request=request)

        assert result.group_id is None
        assert result.name == "Personal Timer"
        saved_timer = mock_save.call_args[0][1]
        assert saved_timer.group_id is None


class TestUpdateTimerService:
    """Test cases for update_timer_service function."""
    
    @patch('pecha_api.timers.timer_service.SessionLocal')
    @patch('pecha_api.timers.timer_service.get_timer_by_id')
    @patch('pecha_api.timers.timer_service.update_timer')
    @patch('pecha_api.timers.timer_service.validate_and_extract_user_details')
    def test_update_timer_service_success(self, mock_validate, mock_update, mock_get, mock_session):
        """Test successful update of timer."""
        user_id = uuid4()
        timer_id = uuid4()
        token = "valid_token"
        
        mock_user = TestDataFactory.create_mock_user(user_id=user_id)
        mock_validate.return_value = mock_user
        
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        
        existing_timer = TestDataFactory.create_mock_timer(
            timer_id=timer_id,
            user_id=user_id,
            name="Old Name",
            duration=300,
            timer_type=TimerType.USER
        )
        mock_get.return_value = existing_timer
        
        request = TestDataFactory.create_update_request(
            name="Updated Name",
            duration=900
        )
        
        # Simulate field updates
        existing_timer.name = "Updated Name"
        existing_timer.duration = 900
        mock_update.return_value = existing_timer
        
        result = update_timer_service(token=token, timer_id=timer_id, request=request)
        
        assert isinstance(result, TimerDTO)
        assert result.name == "Updated Name"
        assert result.duration == 900
        
        mock_validate.assert_called_once_with(token=token)
        mock_get.assert_called_once_with(mock_db, timer_id)
        mock_update.assert_called_once_with(mock_db, existing_timer)
    
    @patch('pecha_api.timers.timer_service.SessionLocal')
    @patch('pecha_api.timers.timer_service.get_timer_by_id')
    @patch('pecha_api.timers.timer_service.update_timer')
    @patch('pecha_api.timers.timer_service.validate_and_extract_user_details')
    def test_update_timer_service_partial_update(self, mock_validate, mock_update, mock_get, mock_session):
        """Test updating only some fields."""
        user_id = uuid4()
        timer_id = uuid4()
        token = "valid_token"
        
        mock_user = TestDataFactory.create_mock_user(user_id=user_id)
        mock_validate.return_value = mock_user
        
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        
        existing_timer = TestDataFactory.create_mock_timer(
            timer_id=timer_id,
            user_id=user_id,
            name="Original Name",
            duration=300,
            timer_type=TimerType.USER
        )
        mock_get.return_value = existing_timer
        
        # Only update name
        request = TestDataFactory.create_update_request(name="New Name")
        
        existing_timer.name = "New Name"
        mock_update.return_value = existing_timer
        
        result = update_timer_service(token=token, timer_id=timer_id, request=request)
        
        assert result.name == "New Name"
        assert result.duration == 300  # Unchanged
    
    @patch('pecha_api.timers.timer_service.SessionLocal')
    @patch('pecha_api.timers.timer_service.get_timer_by_id')
    @patch('pecha_api.timers.timer_service.validate_and_extract_user_details')
    def test_update_timer_service_not_found(self, mock_validate, mock_get, mock_session):
        """Test update_timer_service when timer doesn't exist."""
        user_id = uuid4()
        timer_id = uuid4()
        token = "valid_token"
        
        mock_user = TestDataFactory.create_mock_user(user_id=user_id)
        mock_validate.return_value = mock_user
        
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        
        mock_get.return_value = None
        
        request = TestDataFactory.create_update_request(name="Updated")
        
        with pytest.raises(HTTPException) as exc_info:
            update_timer_service(token=token, timer_id=timer_id, request=request)
        
        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    
    @patch('pecha_api.timers.timer_service.SessionLocal')
    @patch('pecha_api.timers.timer_service.get_timer_by_id')
    @patch('pecha_api.timers.timer_service.validate_and_extract_user_details')
    def test_update_timer_service_not_owner(self, mock_validate, mock_get, mock_session):
        """Test update_timer_service when user is not the owner."""
        user_id = uuid4()
        other_user_id = uuid4()
        timer_id = uuid4()
        token = "valid_token"
        
        mock_user = TestDataFactory.create_mock_user(user_id=user_id)
        mock_validate.return_value = mock_user
        
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        
        # Timer belongs to different user
        existing_timer = TestDataFactory.create_mock_timer(
            timer_id=timer_id,
            user_id=other_user_id,
            timer_type=TimerType.USER
        )
        mock_get.return_value = existing_timer
        
        request = TestDataFactory.create_update_request(name="Updated")
        
        with pytest.raises(HTTPException) as exc_info:
            update_timer_service(token=token, timer_id=timer_id, request=request)
        
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @patch('pecha_api.timers.timer_service.SessionLocal')
    @patch('pecha_api.timers.timer_service.update_timer')
    @patch('pecha_api.timers.timer_service.get_ambient_sound_by_id')
    @patch('pecha_api.timers.timer_service.get_timer_by_id')
    @patch('pecha_api.timers.timer_service.validate_and_extract_user_details')
    def test_update_timer_service_sets_the_background_sound(
        self, mock_validate, mock_get, mock_get_sound, mock_update, mock_session
    ):
        """Picking a catalogue entry stores it on the caller's own timer."""
        user_id = uuid4()
        old_sound_id = uuid4()
        new_sound_id = uuid4()

        mock_validate.return_value = TestDataFactory.create_mock_user(user_id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get_sound.return_value = MagicMock(id=new_sound_id)

        my_timer = TestDataFactory.create_mock_timer(
            user_id=user_id,
            ambient_sound_id=old_sound_id,
            timer_type=TimerType.USER
        )
        mock_get.return_value = my_timer
        mock_update.return_value = my_timer

        request = TestDataFactory.create_update_request(ambient_sound_id=new_sound_id)
        update_timer_service(token="valid_token", timer_id=my_timer.id, request=request)

        # The id is checked against the catalogue before it is stored.
        mock_get_sound.assert_called_once_with(mock_db, new_sound_id)
        assert my_timer.ambient_sound_id == new_sound_id
        mock_update.assert_called_once_with(mock_db, my_timer)

    @patch('pecha_api.timers.timer_service.SessionLocal')
    @patch('pecha_api.timers.timer_service.update_timer')
    @patch('pecha_api.timers.timer_service.get_timer_by_id')
    @patch('pecha_api.timers.timer_service.validate_and_extract_user_details')
    def test_update_timer_service_cannot_change_another_users_sound(
        self, mock_validate, mock_get, mock_update, mock_session
    ):
        """One person's background sound is not another's to change: the
        ownership check fires before the assignment, so their pick stands."""
        user_id = uuid4()
        other_user_id = uuid4()
        their_sound_id = uuid4()

        mock_validate.return_value = TestDataFactory.create_mock_user(user_id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        their_timer = TestDataFactory.create_mock_timer(
            user_id=other_user_id,
            ambient_sound_id=their_sound_id,
            timer_type=TimerType.USER
        )
        mock_get.return_value = their_timer

        request = TestDataFactory.create_update_request(ambient_sound_id=uuid4())

        with pytest.raises(HTTPException) as exc_info:
            update_timer_service(
                token="valid_token", timer_id=their_timer.id, request=request
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert their_timer.ambient_sound_id == their_sound_id
        mock_update.assert_not_called()

    @patch('pecha_api.timers.timer_service.SessionLocal')
    @patch('pecha_api.timers.timer_service.update_timer')
    @patch('pecha_api.timers.timer_service.get_timer_by_id')
    @patch('pecha_api.timers.timer_service.validate_and_extract_user_details')
    def test_update_timer_service_leaves_the_sound_alone_when_omitted(
        self, mock_validate, mock_get, mock_update, mock_session
    ):
        """Editing the name must not clear the sound the user already chose."""
        user_id = uuid4()
        chosen_sound_id = uuid4()

        mock_validate.return_value = TestDataFactory.create_mock_user(user_id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        my_timer = TestDataFactory.create_mock_timer(
            user_id=user_id,
            ambient_sound_id=chosen_sound_id,
            timer_type=TimerType.USER
        )
        mock_get.return_value = my_timer
        mock_update.return_value = my_timer

        request = UpdateTimerRequest(name="Quick sit")
        update_timer_service(token="valid_token", timer_id=my_timer.id, request=request)

        assert my_timer.ambient_sound_id == chosen_sound_id

    @patch('pecha_api.timers.timer_service.SessionLocal')
    @patch('pecha_api.timers.timer_service.save_timer')
    @patch('pecha_api.timers.timer_service.lock_timer_row')
    @patch('pecha_api.timers.timer_service._personal_copy_from_preset')
    @patch('pecha_api.timers.timer_service.get_user_timer_by_parent_preset')
    @patch('pecha_api.timers.timer_service.get_ambient_sound_by_id')
    @patch('pecha_api.timers.timer_service.get_timer_by_id')
    @patch('pecha_api.timers.timer_service.validate_and_extract_user_details')
    def test_update_timer_service_preset_creates_personal_copy(
        self, mock_validate, mock_get, mock_get_sound, mock_get_copy, mock_copy_from_preset, mock_lock, mock_save, mock_session
    ):
        """Picking a sound on a shared preset writes a personal copy, not the catalogue row."""
        user_id = uuid4()
        preset_owner_id = uuid4()
        new_sound_id = uuid4()
        token = "valid_token"

        mock_validate.return_value = TestDataFactory.create_mock_user(user_id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get_sound.return_value = MagicMock(id=new_sound_id)
        mock_get_copy.return_value = None

        preset = TestDataFactory.create_mock_timer(
            user_id=preset_owner_id,
            name="Morning sit",
            duration=900000,
            ambient_sound_id=uuid4(),
            timer_type=TimerType.PRESET
        )
        original_sound_id = preset.ambient_sound_id
        mock_get.return_value = preset

        personal_copy = TestDataFactory.create_mock_timer(
            user_id=user_id,
            name=preset.name,
            duration=preset.duration,
            ambient_sound_id=preset.ambient_sound_id,
            timer_type=TimerType.USER,
            parent_preset_id=preset.id
        )
        mock_copy_from_preset.return_value = personal_copy
        mock_save.return_value = personal_copy

        request = TestDataFactory.create_update_request(ambient_sound_id=new_sound_id)
        result = update_timer_service(token=token, timer_id=preset.id, request=request)

        assert result.type == TimerType.USER
        assert result.user_id == user_id
        assert result.parent_preset_id == preset.id
        assert result.ambient_sound_id == new_sound_id
        assert preset.ambient_sound_id == original_sound_id
        # Looked up twice: once optimistically, then again under the preset's
        # row lock, which is what stops two concurrent PUTs both inserting.
        assert mock_get_copy.call_args_list == [
            call(mock_db, user_id, preset.id),
            call(mock_db, user_id, preset.id),
        ]
        mock_lock.assert_called_once_with(mock_db, preset.id)
        mock_copy_from_preset.assert_called_once_with(user_id, preset)
        mock_save.assert_called_once_with(mock_db, personal_copy)
        assert personal_copy.ambient_sound_id == new_sound_id

    @patch('pecha_api.timers.timer_service.SessionLocal')
    @patch('pecha_api.timers.timer_service.save_timer')
    @patch('pecha_api.timers.timer_service.update_timer')
    @patch('pecha_api.timers.timer_service.lock_timer_row')
    @patch('pecha_api.timers.timer_service.get_user_timer_by_parent_preset')
    @patch('pecha_api.timers.timer_service.get_ambient_sound_by_id')
    @patch('pecha_api.timers.timer_service.get_timer_by_id')
    @patch('pecha_api.timers.timer_service.validate_and_extract_user_details')
    def test_update_timer_service_preset_race_updates_the_row_the_winner_created(
        self, mock_validate, mock_get, mock_get_sound, mock_get_copy, mock_lock, mock_update, mock_save, mock_session
    ):
        """Two PUTs customize the same preset at once. The loser's first lookup
        misses, but the re-read under the lock sees the winner's committed row,
        so it updates that instead of inserting a duplicate."""
        user_id = uuid4()
        new_sound_id = uuid4()

        mock_validate.return_value = TestDataFactory.create_mock_user(user_id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get_sound.return_value = MagicMock(id=new_sound_id)

        preset = TestDataFactory.create_mock_timer(
            user_id=uuid4(), ambient_sound_id=uuid4(), timer_type=TimerType.PRESET
        )
        mock_get.return_value = preset

        winners_copy = TestDataFactory.create_mock_timer(
            user_id=user_id,
            name=preset.name,
            duration=preset.duration,
            ambient_sound_id=preset.ambient_sound_id,
            timer_type=TimerType.USER,
            parent_preset_id=preset.id,
        )
        # Miss, then hit once the lock is held.
        mock_get_copy.side_effect = [None, winners_copy]
        mock_update.return_value = winners_copy

        request = TestDataFactory.create_update_request(ambient_sound_id=new_sound_id)
        result = update_timer_service(token="valid_token", timer_id=preset.id, request=request)

        mock_lock.assert_called_once_with(mock_db, preset.id)
        mock_save.assert_not_called()
        mock_update.assert_called_once_with(mock_db, winners_copy)
        assert result.id == winners_copy.id
        assert result.ambient_sound_id == new_sound_id

    @patch('pecha_api.timers.timer_service.SessionLocal')
    @patch('pecha_api.timers.timer_service.save_timer')
    @patch('pecha_api.timers.timer_service.update_timer')
    @patch('pecha_api.timers.timer_service.get_user_timer_by_parent_preset')
    @patch('pecha_api.timers.timer_service.get_ambient_sound_by_id')
    @patch('pecha_api.timers.timer_service.get_timer_by_id')
    @patch('pecha_api.timers.timer_service.validate_and_extract_user_details')
    def test_update_timer_service_preset_updates_existing_personal_copy(
        self, mock_validate, mock_get, mock_get_sound, mock_get_copy, mock_update, mock_save, mock_session
    ):
        """A second pick on the same preset rewrites the caller's copy, not a new row."""
        user_id = uuid4()
        new_sound_id = uuid4()
        token = "valid_token"

        mock_validate.return_value = TestDataFactory.create_mock_user(user_id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get_sound.return_value = MagicMock(id=new_sound_id)

        preset = TestDataFactory.create_mock_timer(
            user_id=uuid4(),
            ambient_sound_id=uuid4(),
            timer_type=TimerType.PRESET
        )
        original_preset_sound_id = preset.ambient_sound_id
        mock_get.return_value = preset

        personal_copy = TestDataFactory.create_mock_timer(
            user_id=user_id,
            ambient_sound_id=uuid4(),
            timer_type=TimerType.USER,
            parent_preset_id=preset.id
        )
        mock_get_copy.return_value = personal_copy
        mock_update.return_value = personal_copy

        request = TestDataFactory.create_update_request(ambient_sound_id=new_sound_id)
        result = update_timer_service(token=token, timer_id=preset.id, request=request)

        assert personal_copy.ambient_sound_id == new_sound_id
        assert result.ambient_sound_id == new_sound_id
        assert preset.ambient_sound_id == original_preset_sound_id
        mock_save.assert_not_called()
        mock_update.assert_called_once_with(mock_db, personal_copy)
    
    @patch('pecha_api.timers.timer_service.validate_and_extract_user_details')
    def test_update_timer_service_invalid_token(self, mock_validate):
        """Test update_timer_service with invalid token."""
        timer_id = uuid4()
        token = "invalid_token"
        
        mock_validate.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )
        
        request = TestDataFactory.create_update_request(name="Updated")
        
        with pytest.raises(HTTPException) as exc_info:
            update_timer_service(token=token, timer_id=timer_id, request=request)
        
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


class TestDeleteTimerService:
    """Test cases for delete_timer_service function."""
    
    @patch('pecha_api.timers.timer_service.SessionLocal')
    @patch('pecha_api.timers.timer_service.get_timer_by_id')
    @patch('pecha_api.timers.timer_service.delete_timer')
    @patch('pecha_api.timers.timer_service.validate_and_extract_user_details')
    def test_delete_timer_service_success(self, mock_validate, mock_delete, mock_get, mock_session):
        """Test successful deletion of timer."""
        user_id = uuid4()
        timer_id = uuid4()
        token = "valid_token"
        
        mock_user = TestDataFactory.create_mock_user(user_id=user_id)
        mock_validate.return_value = mock_user
        
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        
        existing_timer = TestDataFactory.create_mock_timer(
            timer_id=timer_id,
            user_id=user_id,
            timer_type=TimerType.USER
        )
        mock_get.return_value = existing_timer
        
        mock_delete.return_value = None
        
        result = delete_timer_service(token=token, timer_id=timer_id)
        
        assert result is None
        
        mock_validate.assert_called_once_with(token=token)
        mock_get.assert_called_once_with(mock_db, timer_id)
        mock_delete.assert_called_once_with(mock_db, existing_timer)
    
    @patch('pecha_api.timers.timer_service.SessionLocal')
    @patch('pecha_api.timers.timer_service.get_timer_by_id')
    @patch('pecha_api.timers.timer_service.validate_and_extract_user_details')
    def test_delete_timer_service_not_found(self, mock_validate, mock_get, mock_session):
        """Test delete_timer_service when timer doesn't exist."""
        user_id = uuid4()
        timer_id = uuid4()
        token = "valid_token"
        
        mock_user = TestDataFactory.create_mock_user(user_id=user_id)
        mock_validate.return_value = mock_user
        
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        
        mock_get.return_value = None
        
        with pytest.raises(HTTPException) as exc_info:
            delete_timer_service(token=token, timer_id=timer_id)
        
        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    
    @patch('pecha_api.timers.timer_service.SessionLocal')
    @patch('pecha_api.timers.timer_service.get_timer_by_id')
    @patch('pecha_api.timers.timer_service.validate_and_extract_user_details')
    def test_delete_timer_service_not_owner(self, mock_validate, mock_get, mock_session):
        """Test delete_timer_service when user is not the owner."""
        user_id = uuid4()
        other_user_id = uuid4()
        timer_id = uuid4()
        token = "valid_token"
        
        mock_user = TestDataFactory.create_mock_user(user_id=user_id)
        mock_validate.return_value = mock_user
        
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        
        existing_timer = TestDataFactory.create_mock_timer(
            timer_id=timer_id,
            user_id=other_user_id,
            timer_type=TimerType.USER
        )
        mock_get.return_value = existing_timer
        
        with pytest.raises(HTTPException) as exc_info:
            delete_timer_service(token=token, timer_id=timer_id)
        
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    
    @patch('pecha_api.timers.timer_service.SessionLocal')
    @patch('pecha_api.timers.timer_service.get_timer_by_id')
    @patch('pecha_api.timers.timer_service.validate_and_extract_user_details')
    def test_delete_timer_service_preset_timer(self, mock_validate, mock_get, mock_session):
        """Test delete_timer_service when trying to delete preset timer."""
        user_id = uuid4()
        timer_id = uuid4()
        token = "valid_token"
        
        mock_user = TestDataFactory.create_mock_user(user_id=user_id)
        mock_validate.return_value = mock_user
        
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        
        existing_timer = TestDataFactory.create_mock_timer(
            timer_id=timer_id,
            user_id=user_id,
            timer_type=TimerType.PRESET
        )
        mock_get.return_value = existing_timer
        
        with pytest.raises(HTTPException) as exc_info:
            delete_timer_service(token=token, timer_id=timer_id)
        
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    
    @patch('pecha_api.timers.timer_service.validate_and_extract_user_details')
    def test_delete_timer_service_invalid_token(self, mock_validate):
        """Test delete_timer_service with invalid token."""
        timer_id = uuid4()
        token = "invalid_token"

        mock_validate.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )

        with pytest.raises(HTTPException) as exc_info:
            delete_timer_service(token=token, timer_id=timer_id)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


class TestRestoreTimerService:
    """Test cases for restore_timer_service function."""

    @patch('pecha_api.timers.timer_service.SessionLocal')
    @patch('pecha_api.timers.timer_service.get_timer_by_id')
    @patch('pecha_api.timers.timer_service.update_timer')
    @patch('pecha_api.timers.timer_service.validate_and_extract_user_details')
    def test_restore_timer_service_success(self, mock_validate, mock_update, mock_get, mock_session):
        """Test successful restore of a soft-deleted timer within the retention window."""
        user_id = uuid4()
        timer_id = uuid4()
        token = "valid_token"

        mock_user = TestDataFactory.create_mock_user(user_id=user_id)
        mock_validate.return_value = mock_user

        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        existing_timer = TestDataFactory.create_mock_timer(
            timer_id=timer_id,
            user_id=user_id,
            timer_type=TimerType.USER,
            deleted_at=datetime.now(timezone.utc)
        )
        mock_get.return_value = existing_timer
        mock_update.return_value = existing_timer

        result = restore_timer_service(token=token, timer_id=timer_id)

        assert result.id == timer_id
        assert existing_timer.deleted_at is None
        mock_get.assert_called_once_with(mock_db, timer_id, include_deleted=True)
        mock_update.assert_called_once_with(mock_db, existing_timer)

    @patch('pecha_api.timers.timer_service.SessionLocal')
    @patch('pecha_api.timers.timer_service.get_timer_by_id')
    @patch('pecha_api.timers.timer_service.validate_and_extract_user_details')
    def test_restore_timer_service_not_found(self, mock_validate, mock_get, mock_session):
        """Test restore_timer_service when timer doesn't exist at all."""
        user_id = uuid4()
        timer_id = uuid4()
        token = "valid_token"

        mock_validate.return_value = TestDataFactory.create_mock_user(user_id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            restore_timer_service(token=token, timer_id=timer_id)

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @patch('pecha_api.timers.timer_service.SessionLocal')
    @patch('pecha_api.timers.timer_service.get_timer_by_id')
    @patch('pecha_api.timers.timer_service.validate_and_extract_user_details')
    def test_restore_timer_service_not_owner(self, mock_validate, mock_get, mock_session):
        """Test restore_timer_service when the caller doesn't own the timer."""
        user_id = uuid4()
        other_user_id = uuid4()
        timer_id = uuid4()
        token = "valid_token"

        mock_validate.return_value = TestDataFactory.create_mock_user(user_id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        existing_timer = TestDataFactory.create_mock_timer(
            timer_id=timer_id,
            user_id=other_user_id,
            deleted_at=datetime.now(timezone.utc)
        )
        mock_get.return_value = existing_timer

        with pytest.raises(HTTPException) as exc_info:
            restore_timer_service(token=token, timer_id=timer_id)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @patch('pecha_api.timers.timer_service.SessionLocal')
    @patch('pecha_api.timers.timer_service.get_timer_by_id')
    @patch('pecha_api.timers.timer_service.validate_and_extract_user_details')
    def test_restore_timer_service_not_deleted(self, mock_validate, mock_get, mock_session):
        """Test restore_timer_service when the timer was never deleted."""
        user_id = uuid4()
        timer_id = uuid4()
        token = "valid_token"

        mock_validate.return_value = TestDataFactory.create_mock_user(user_id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        existing_timer = TestDataFactory.create_mock_timer(
            timer_id=timer_id,
            user_id=user_id,
            deleted_at=None
        )
        mock_get.return_value = existing_timer

        with pytest.raises(HTTPException) as exc_info:
            restore_timer_service(token=token, timer_id=timer_id)

        assert exc_info.value.status_code == status.HTTP_409_CONFLICT

    @patch('pecha_api.timers.timer_service.SessionLocal')
    @patch('pecha_api.timers.timer_service.get_timer_by_id')
    @patch('pecha_api.timers.timer_service.validate_and_extract_user_details')
    def test_restore_timer_service_window_expired(self, mock_validate, mock_get, mock_session):
        """Test restore_timer_service when the retention window has passed."""
        user_id = uuid4()
        timer_id = uuid4()
        token = "valid_token"

        mock_validate.return_value = TestDataFactory.create_mock_user(user_id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        existing_timer = TestDataFactory.create_mock_timer(
            timer_id=timer_id,
            user_id=user_id,
            deleted_at=datetime.now(timezone.utc) - timedelta(days=60)
        )
        mock_get.return_value = existing_timer

        with pytest.raises(HTTPException) as exc_info:
            restore_timer_service(token=token, timer_id=timer_id)

        assert exc_info.value.status_code == status.HTTP_409_CONFLICT


class TestHelperFunctions:
    """Test cases for helper functions."""
    
    def test_convert_timer_to_dto(self):
        """Test conversion of Timer model to TimerDTO."""
        timer_id = uuid4()
        user_id = uuid4()
        group_id = uuid4()
        ambient_sound_id = uuid4()

        timer = TestDataFactory.create_mock_timer(
            timer_id=timer_id,
            user_id=user_id,
            group_id=group_id,
            name="Test Timer",
            duration=300,
            description="Test description",
            ambient_sound_id=ambient_sound_id,
            timer_type=TimerType.USER
        )

        result = convert_timer_to_dto(timer)

        assert isinstance(result, TimerDTO)
        assert result.id == timer_id
        assert result.user_id == user_id
        assert result.group_id == group_id
        assert result.name == "Test Timer"
        assert result.duration == 300
        assert result.description == "Test description"
        assert result.ambient_sound_id == ambient_sound_id
        assert result.type == TimerType.USER

    def test_convert_timer_to_dto_without_ambient_sound(self):
        """A timer with no background sound serialises with it omitted."""
        timer = TestDataFactory.create_mock_timer(timer_type=TimerType.USER)

        result = convert_timer_to_dto(timer)

        assert result.ambient_sound_id is None

    def test_convert_timer_to_dto_keeps_bells_independent(self):
        """The bells are their own flags: they do not follow the sound."""
        timer = TestDataFactory.create_mock_timer(
            timer_type=TimerType.USER,
            ambient_sound_id=None,
            bell_at_start=True,
            bell_at_end=False
        )

        result = convert_timer_to_dto(timer)

        assert result.ambient_sound_id is None
        assert result.bell_at_start is True
        assert result.bell_at_end is False

    def test_is_user_created_timer_user_type(self):
        """Test is_user_created_timer returns True for USER type."""
        timer = TestDataFactory.create_mock_timer(timer_type=TimerType.USER)
        
        result = is_user_created_timer(timer)
        
        assert result is True
    
    def test_is_user_created_timer_preset_type(self):
        """Test is_user_created_timer returns False for PRESET type."""
        timer = TestDataFactory.create_mock_timer(timer_type=TimerType.PRESET)
        
        result = is_user_created_timer(timer)
        
        assert result is False


class TestRecordTimerStopService:
    """Test cases for record_timer_stop_service function."""
    
    @patch('pecha_api.timers.timer_service.SessionLocal')
    @patch('pecha_api.timers.timer_service.get_timer_by_id')
    @patch('pecha_api.timers.timer_service.save_timer_history')
    @patch('pecha_api.timers.timer_service.validate_and_extract_user_details')
    def test_record_timer_stop_service_success(self, mock_validate, mock_save, mock_get, mock_session):
        """Test successful recording of timer stop."""
        user_id = uuid4()
        timer_id = uuid4()
        token = "valid_token"
        
        mock_user = TestDataFactory.create_mock_user(user_id=user_id)
        mock_validate.return_value = mock_user
        
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        
        existing_timer = TestDataFactory.create_mock_timer(timer_id=timer_id, name="Test Timer")
        mock_get.return_value = existing_timer

        request = RecordTimerStopRequest(timer_id=timer_id, duration=600)

        mock_save.return_value = TestDataFactory.create_mock_timer_history(
            timer_id=timer_id,
            user_id=user_id,
            duration=600
        )

        result = record_timer_stop_service(token=token, request=request)

        assert result.timer_id == timer_id
        assert result.name == "Test Timer"
        assert result.duration_ms == 600
        mock_validate.assert_called_once_with(token=token)
        mock_get.assert_called_once_with(mock_db, timer_id)
        mock_save.assert_called_once()
    
    @patch('pecha_api.timers.timer_service.SessionLocal')
    @patch('pecha_api.timers.timer_service.get_timer_by_id')
    @patch('pecha_api.timers.timer_service.validate_and_extract_user_details')
    def test_record_timer_stop_service_timer_not_found(self, mock_validate, mock_get, mock_session):
        """Test record_timer_stop_service when timer doesn't exist."""
        user_id = uuid4()
        timer_id = uuid4()
        token = "valid_token"
        
        mock_user = TestDataFactory.create_mock_user(user_id=user_id)
        mock_validate.return_value = mock_user
        
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        
        mock_get.return_value = None
        
        request = RecordTimerStopRequest(timer_id=timer_id, duration=600)
        
        with pytest.raises(HTTPException) as exc_info:
            record_timer_stop_service(token=token, request=request)
        
        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    
    @patch('pecha_api.timers.timer_service.validate_and_extract_user_details')
    def test_record_timer_stop_service_invalid_token(self, mock_validate):
        """Test record_timer_stop_service with invalid token."""
        timer_id = uuid4()
        token = "invalid_token"
        
        mock_validate.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )
        
        request = RecordTimerStopRequest(timer_id=timer_id, duration=600)
        
        with pytest.raises(HTTPException) as exc_info:
            record_timer_stop_service(token=token, request=request)
        
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


class TestGetTimerHistoryService:
    """Test cases for get_timer_history_service function."""
    
    @patch('pecha_api.timers.timer_service.SessionLocal')
    @patch('pecha_api.timers.timer_service.get_user_timer_history')
    @patch('pecha_api.timers.timer_service.validate_and_extract_user_details')
    def test_get_timer_history_service_success(self, mock_validate, mock_get_history, mock_session):
        """Test successful retrieval of timer history."""
        user_id = uuid4()
        timer_id = uuid4()
        token = "valid_token"
        
        mock_user = TestDataFactory.create_mock_user(user_id=user_id)
        mock_validate.return_value = mock_user
        
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        
        timer = TestDataFactory.create_mock_timer(
            timer_id=timer_id,
            name="Meditation Timer",
            duration=600,
            description="Daily meditation"
        )
        
        session1 = TestDataFactory.create_mock_timer_history(timer_id=timer_id, duration=600)
        session2 = TestDataFactory.create_mock_timer_history(timer_id=timer_id, duration=600)
        
        mock_get_history.return_value = ([(timer, 1200, [session1, session2])], 1)
        
        result = get_timer_history_service(token=token, skip=0, limit=20)
        
        assert isinstance(result, TimerHistoryResponse)
        assert len(result.timers) == 1
        assert result.timers[0].name == "Meditation Timer"
        assert result.timers[0].actual_duration == 600
        assert result.timers[0].total_time_spent == 1200
        assert len(result.timers[0].sessions) == 2
        assert result.total == 1
        
        mock_validate.assert_called_once_with(token=token)
        mock_get_history.assert_called_once_with(mock_db, user_id, 0, 20)
    
    @patch('pecha_api.timers.timer_service.SessionLocal')
    @patch('pecha_api.timers.timer_service.get_user_timer_history')
    @patch('pecha_api.timers.timer_service.validate_and_extract_user_details')
    def test_get_timer_history_service_empty(self, mock_validate, mock_get_history, mock_session):
        """Test get_timer_history_service when user has no history."""
        user_id = uuid4()
        token = "valid_token"
        
        mock_user = TestDataFactory.create_mock_user(user_id=user_id)
        mock_validate.return_value = mock_user
        
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        
        mock_get_history.return_value = ([], 0)
        
        result = get_timer_history_service(token=token, skip=0, limit=20)
        
        assert len(result.timers) == 0
        assert result.total == 0
    
    @patch('pecha_api.timers.timer_service.SessionLocal')
    @patch('pecha_api.timers.timer_service.get_user_timer_history')
    @patch('pecha_api.timers.timer_service.validate_and_extract_user_details')
    def test_get_timer_history_service_multiple_timers(self, mock_validate, mock_get_history, mock_session):
        """Test get_timer_history_service with multiple timers."""
        user_id = uuid4()
        token = "valid_token"
        
        mock_user = TestDataFactory.create_mock_user(user_id=user_id)
        mock_validate.return_value = mock_user
        
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        
        timer1 = TestDataFactory.create_mock_timer(name="Timer 1", duration=300)
        timer2 = TestDataFactory.create_mock_timer(name="Timer 2", duration=600)
        
        session1 = TestDataFactory.create_mock_timer_history(duration=300)
        session2 = TestDataFactory.create_mock_timer_history(duration=600)
        
        mock_get_history.return_value = ([
            (timer1, 900, [session1]),
            (timer2, 1200, [session2])
        ], 2)
        
        result = get_timer_history_service(token=token, skip=0, limit=20)
        
        assert len(result.timers) == 2
        assert result.timers[0].name == "Timer 1"
        assert result.timers[1].name == "Timer 2"
        assert result.total == 2
    
    @patch('pecha_api.timers.timer_service.validate_and_extract_user_details')
    def test_get_timer_history_service_invalid_token(self, mock_validate):
        """Test get_timer_history_service with invalid token."""
        token = "invalid_token"
        
        mock_validate.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )
        
        with pytest.raises(HTTPException) as exc_info:
            get_timer_history_service(token=token, skip=0, limit=20)
        
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
