import pytest
from unittest.mock import patch, MagicMock
from uuid import uuid4
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from starlette import status
from pecha_api.plans.users.recitation.user_recitations_views import (
    create_user_recitation, 
    get_user_recitations,
    update_recitation_order
)
from pecha_api.plans.users.recitation.user_recitations_views import create_user_recitation, get_user_recitations, delete_user_recitation
from pecha_api.plans.users.recitation.user_recitations_response_models import (
    CreateUserRecitationRequest,
    UserRecitationsResponse,
    UserRecitationDTO,
    UpdateRecitationOrderRequest,
    RecitationOrderItem
)

from pecha_api.error_contants import ErrorConstants


class TestDataFactory:
    
    @staticmethod
    def create_auth_credentials(token="valid_token") -> HTTPAuthorizationCredentials:
        """Create HTTPAuthorizationCredentials with specified token."""
        return HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials=token
        )

    @staticmethod
    def create_user_recitation_request(text_id=None) -> CreateUserRecitationRequest:
        """Create a CreateUserRecitationRequest with specified text_id."""
        return CreateUserRecitationRequest(
            text_id=text_id or uuid4()
        )

    @staticmethod
    def create_user_recitations_response(recitations=None) -> UserRecitationsResponse:
        """Create a UserRecitationsResponse with specified recitations."""
        return UserRecitationsResponse(
            recitations=recitations or []
        )

    @staticmethod
    def create_user_recitation_dto(title="Test Text", text_id=None, image_url=None, language="bo", display_order=1) -> UserRecitationDTO:
        """Create a UserRecitationDTO with specified attributes."""
        return UserRecitationDTO(
            title=title,
            text_id=str(text_id or uuid4()),
            image_url=image_url,
            language=language,
            display_order=display_order
        )

    @staticmethod
    def create_update_recitation_order_request(recitations=None) -> UpdateRecitationOrderRequest:
        """Create an UpdateRecitationOrderRequest with specified recitations."""
        if recitations is None:
            recitations = [
                RecitationOrderItem(id=uuid4(), display_order=1),
                RecitationOrderItem(id=uuid4(), display_order=2)
            ]
        return UpdateRecitationOrderRequest(recitations=recitations)


class TestCreateUserRecitationView:

    @patch('pecha_api.plans.users.recitation.user_recitations_views.create_user_recitation_service')
    @pytest.mark.asyncio
    async def test_create_user_recitation_success(
        self,
        mock_service
    ):
        text_id = uuid4()
        token = "valid_token"
        
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        request = TestDataFactory.create_user_recitation_request(text_id=text_id)
        
        mock_service.return_value = None
        
        result = await create_user_recitation(
            authentication_credential=auth_credentials,
            create_user_recitation_request=request
        )
        
        assert result is None
        mock_service.assert_awaited_once_with(
            token=token,
            create_user_recitation_request=request
        )

    @patch('pecha_api.plans.users.recitation.user_recitations_views.create_user_recitation_service')
    @pytest.mark.asyncio
    async def test_create_user_recitation_text_not_found(
        self,
        mock_service
    ):
        text_id = uuid4()
        token = "valid_token"
        
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        request = TestDataFactory.create_user_recitation_request(text_id=text_id)
        
        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorConstants.TEXT_NOT_FOUND_MESSAGE
        )
        
        with pytest.raises(HTTPException) as exc_info:
            await create_user_recitation(
                authentication_credential=auth_credentials,
                create_user_recitation_request=request
            )
        
        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
        assert exc_info.value.detail == ErrorConstants.TEXT_NOT_FOUND_MESSAGE
        mock_service.assert_awaited_once_with(
            token=token,
            create_user_recitation_request=request
        )

class TestGetUserRecitationsView:

    @patch('pecha_api.plans.users.recitation.user_recitations_views.get_user_recitations_service')
    @pytest.mark.asyncio
    async def test_get_user_recitations_success(
        self,
        mock_service
    ):
        """Test successful retrieval of user recitations with multiple texts."""
        token = "valid_token"
        text_id_1 = uuid4()
        text_id_2 = uuid4()
        
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        
        recitations = [
            TestDataFactory.create_user_recitation_dto(
                title="Heart Sutra",
                text_id=text_id_1
            ),
            TestDataFactory.create_user_recitation_dto(
                title="Diamond Sutra",
                text_id=text_id_2
            )
        ]
        mock_response = TestDataFactory.create_user_recitations_response(recitations=recitations)
        mock_service.return_value = mock_response
        
        result = await get_user_recitations(authentication_credential=auth_credentials)
        
        assert isinstance(result, UserRecitationsResponse)
        assert len(result.recitations) == 2
        assert result.recitations[0].title == "Heart Sutra"
        assert result.recitations[0].text_id == str(text_id_1)
        assert result.recitations[1].title == "Diamond Sutra"
        assert result.recitations[1].text_id == str(text_id_2)
        
        mock_service.assert_awaited_once_with(
            token=token,
        )

    @patch('pecha_api.plans.users.recitation.user_recitations_views.get_user_recitations_service')
    @pytest.mark.asyncio
    async def test_get_user_recitations_empty_list(
        self,
        mock_service
    ):
        token = "valid_token"
        
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        
        mock_response = TestDataFactory.create_user_recitations_response(recitations=[])
        mock_service.return_value = mock_response
        
        result = await get_user_recitations(authentication_credential=auth_credentials)
        
        assert isinstance(result, UserRecitationsResponse)
        assert len(result.recitations) == 0
        assert result.recitations == []
        
        mock_service.assert_awaited_once_with(
            token=token,
        )

    @patch('pecha_api.plans.users.recitation.user_recitations_views.get_user_recitations_service')
    @pytest.mark.asyncio
    async def test_get_user_recitations_single_recitation(
        self,
        mock_service
    ):
        token = "valid_token"
        text_id = uuid4()
        
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        
        recitations = [
            TestDataFactory.create_user_recitation_dto(
                title="Lotus Sutra",
                text_id=text_id
            )
        ]
        mock_response = TestDataFactory.create_user_recitations_response(recitations=recitations)
        mock_service.return_value = mock_response
        
        result = await get_user_recitations(authentication_credential=auth_credentials)
        
        assert isinstance(result, UserRecitationsResponse)
        assert len(result.recitations) == 1
        assert result.recitations[0].title == "Lotus Sutra"
        assert result.recitations[0].text_id == str(text_id)
        
        mock_service.assert_awaited_once_with(
            token=token,
        )

    @patch('pecha_api.plans.users.recitation.user_recitations_views.get_user_recitations_service')
    @pytest.mark.asyncio
    async def test_get_user_recitations_invalid_token(
        self,
        mock_service
    ):
        """Test get_user_recitations with invalid authentication token."""
        token = "invalid_token"
        
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        
        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )
        
        with pytest.raises(HTTPException) as exc_info:
            await get_user_recitations(authentication_credential=auth_credentials)
        
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc_info.value.detail == "Invalid authentication credentials"
        
        mock_service.assert_awaited_once_with(
            token=token,
        )

    @patch('pecha_api.plans.users.recitation.user_recitations_views.get_user_recitations_service')
    @pytest.mark.asyncio
    async def test_get_user_recitations_database_error(
        self,
        mock_service
    ):
        """Test get_user_recitations when database error occurs."""
        token = "valid_token"
        
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        
        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database connection error"
        )
        
        with pytest.raises(HTTPException) as exc_info:
            await get_user_recitations(authentication_credential=auth_credentials)
        
        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert exc_info.value.detail == "Database connection error"


class TestDeleteUserRecitationView:
    """Test cases for delete_user_recitation view function."""

    @patch('pecha_api.plans.users.recitation.user_recitations_views.delete_user_recitation_service')
    @pytest.mark.asyncio
    async def test_delete_user_recitation_success(
        self,
        mock_service
    ):
        """Test successful deletion of user recitation via view."""
        text_id = uuid4()
        token = "valid_token"
        
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        
        mock_service.return_value = None
        
        result = await delete_user_recitation(
            text_id=text_id,
            authentication_credential=auth_credentials
        )
        
        assert result is None
        mock_service.assert_awaited_once_with(
            token=token,
            text_id=text_id
        )


class TestUpdateRecitationOrderView:
    """Test cases for update_recitation_order view function."""

    @patch('pecha_api.plans.users.recitation.user_recitations_views.update_recitation_order_service')
    @pytest.mark.asyncio
    async def test_update_recitation_order_success(
        self,
        mock_service
    ):
        """Test successful update of recitation order."""
        token = "valid_token"
        recitation_id_1 = uuid4()
        recitation_id_2 = uuid4()
        recitation_id_3 = uuid4()
        
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        
        recitations = [
            RecitationOrderItem(text_id=recitation_id_1, display_order=1),
            RecitationOrderItem(text_id=recitation_id_2, display_order=2),
            RecitationOrderItem(text_id=recitation_id_3, display_order=3)
        ]
        update_order_request = UpdateRecitationOrderRequest(recitations=recitations)
        
        mock_service.return_value = None
        
        result = await update_recitation_order(
            authentication_credential=auth_credentials,
            update_order_request=update_order_request
        )
        
        assert result is None
        mock_service.assert_awaited_once_with(
            token=token,
            update_order_request=update_order_request
        )
        

    @patch('pecha_api.plans.users.recitation.user_recitations_views.update_recitation_order_service')
    @pytest.mark.asyncio
    async def test_update_recitation_order_move_up(
        self,
        mock_service
    ):
        """Test moving a recitation up in the order (from position 5 to position 2)."""
        token = "valid_token"
        recitation_ids = [uuid4() for _ in range(5)]
        
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        
        recitations = [
            RecitationOrderItem(text_id=recitation_ids[0], display_order=1),
            RecitationOrderItem(text_id=recitation_ids[4], display_order=2), 
            RecitationOrderItem(text_id=recitation_ids[1], display_order=3),
            RecitationOrderItem(text_id=recitation_ids[2], display_order=4),
            RecitationOrderItem(text_id=recitation_ids[3], display_order=5)
        ]
        update_order_request = UpdateRecitationOrderRequest(recitations=recitations)
        
        mock_service.return_value = None
        
        result = await update_recitation_order(
            authentication_credential=auth_credentials,
            update_order_request=update_order_request
        )
        
        assert result is None
        mock_service.assert_awaited_once_with(
            token=token,
            update_order_request=update_order_request
        )

    @patch('pecha_api.plans.users.recitation.user_recitations_views.update_recitation_order_service')
    @pytest.mark.asyncio
    async def test_update_recitation_order_move_down(
        self,
        mock_service
    ):
        """Test moving a recitation down in the order (from position 2 to position 5)."""
        token = "valid_token"
        recitation_ids = [uuid4() for _ in range(5)]
        
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        
        recitations = [
            RecitationOrderItem(text_id=recitation_ids[0], display_order=1),
            RecitationOrderItem(text_id=recitation_ids[2], display_order=2),
            RecitationOrderItem(text_id=recitation_ids[3], display_order=3),
            RecitationOrderItem(text_id=recitation_ids[4], display_order=4),
            RecitationOrderItem(text_id=recitation_ids[1], display_order=5)
        ]
        update_order_request = UpdateRecitationOrderRequest(recitations=recitations)
        
        mock_service.return_value = None
        
        result = await update_recitation_order(
            authentication_credential=auth_credentials,
            update_order_request=update_order_request
        )
        
        assert result is None
        mock_service.assert_awaited_once_with(
            token=token,
            update_order_request=update_order_request
        )

    @patch('pecha_api.plans.users.recitation.user_recitations_views.update_recitation_order_service')
    @pytest.mark.asyncio
    async def test_update_recitation_order_to_first_position(
        self,
        mock_service
    ):
        """Test moving a recitation to the first position."""
        token = "valid_token"
        recitation_ids = [uuid4() for _ in range(3)]
        
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        
        recitations = [
            RecitationOrderItem(text_id=recitation_ids[2], display_order=1),
            RecitationOrderItem(text_id=recitation_ids[0], display_order=2),
            RecitationOrderItem(text_id=recitation_ids[1], display_order=3)
        ]
        update_order_request = UpdateRecitationOrderRequest(recitations=recitations)
        
        mock_service.return_value = None
        
        result = await update_recitation_order(
            authentication_credential=auth_credentials,
            update_order_request=update_order_request
        )
        
        assert result is None
        mock_service.assert_awaited_once_with(
            token=token,
            update_order_request=update_order_request
        )
    
    @patch('pecha_api.plans.users.recitation.user_recitations_views.delete_user_recitation_service')
    @pytest.mark.asyncio
    async def test_delete_user_recitation_not_found(
        self,
        mock_service
    ):
        """Test delete_user_recitation when recitation does not exist."""
        text_id = uuid4()
        token = "valid_token"
        
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        
        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "NOT_FOUND",
                "message": f"Recitation with ID {text_id} not found for this user"
            }
        )
        
        with pytest.raises(HTTPException) as exc_info:
            await delete_user_recitation(
                text_id=text_id,
                authentication_credential=auth_credentials
            )
        
        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
        assert exc_info.value.detail["error"] == "NOT_FOUND"
        mock_service.assert_awaited_once_with(
            token=token,
            text_id=text_id
        )

    @patch('pecha_api.plans.users.recitation.user_recitations_views.delete_user_recitation_service')
    @pytest.mark.asyncio
    async def test_delete_user_recitation_invalid_token(
        self,
        mock_service
    ):
        """Test delete_user_recitation with invalid authentication token."""
        text_id = uuid4()
        token = "invalid_token"
        
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        
        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )
        
        with pytest.raises(HTTPException) as exc_info:
            await delete_user_recitation(
                text_id=text_id,
                authentication_credential=auth_credentials
            )
        
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc_info.value.detail == "Invalid authentication credentials"
        
        mock_service.assert_awaited_once_with(
            token=token,
            text_id=text_id
        )

    @patch('pecha_api.plans.users.recitation.user_recitations_views.update_recitation_order_service')
    @pytest.mark.asyncio
    async def test_update_recitation_order_empty_list(
        self,
        mock_service
    ):
        """Test update_recitation_order with empty recitations list."""
        token = "valid_token"
        
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        update_order_request = UpdateRecitationOrderRequest(recitations=[])
        
        mock_service.return_value = None
        
        result = await update_recitation_order(
            authentication_credential=auth_credentials,
            update_order_request=update_order_request
        )
        
        assert result is None
        mock_service.assert_awaited_once_with(
            token=token,
            update_order_request=update_order_request
        )
    @patch('pecha_api.plans.users.recitation.user_recitations_views.delete_user_recitation_service')
    @pytest.mark.asyncio
    async def test_delete_user_recitation_database_error(
        self,
        mock_service
    ):
        """Test delete_user_recitation when database error occurs."""
        text_id = uuid4()
        token = "valid_token"
        
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        
        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "BAD_REQUEST",
                "message": "Database integrity error: constraint violation"
            }
        )
        
        with pytest.raises(HTTPException) as exc_info:
            await delete_user_recitation(
                text_id=text_id,
                authentication_credential=auth_credentials
            )
        
        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert exc_info.value.detail["error"] == "BAD_REQUEST"
        mock_service.assert_awaited_once_with(
            token=token,
            text_id=text_id
        )


class TestGetUserRecitationsService:
    @pytest.mark.asyncio
    @patch("pecha_api.plans.users.recitation.user_recitations_services.get_texts_by_edition_or_text_ids")
    @patch("pecha_api.plans.users.recitation.user_recitations_services.get_image_url_map_by_text_ids")
    @patch("pecha_api.plans.users.recitation.user_recitations_services.get_user_recitations_by_user_id")
    @patch("pecha_api.plans.users.recitation.user_recitations_services.SessionLocal")
    @patch("pecha_api.plans.users.recitation.user_recitations_services.validate_and_extract_user_details")
    async def test_returns_bookmarked_recitations_only(
        self,
        mock_validate,
        mock_session_local,
        mock_get_user_recitations,
        mock_image_map,
        mock_get_texts,
    ):
        from types import SimpleNamespace
        from pecha_api.plans.users.recitation.user_recitations_services import (
            get_user_recitations_service,
        )

        user_id = uuid4()
        text_id = uuid4()
        mock_validate.return_value = SimpleNamespace(id=user_id)
        mock_session_local.return_value.__enter__.return_value = MagicMock()
        mock_session_local.return_value.__exit__.return_value = None
        mock_get_user_recitations.return_value = [
            SimpleNamespace(text_id=str(text_id), display_order=1)
        ]
        mock_get_texts.return_value = {
            str(text_id): SimpleNamespace(title="Heart Sutra", language="bo")
        }
        mock_image_map.return_value = {str(text_id): "https://example.com/text.jpg"}

        result = await get_user_recitations_service(token="valid_token")

        assert len(result.recitations) == 1
        assert result.recitations[0].title == "Heart Sutra"
        assert result.recitations[0].text_id == str(text_id)

    @pytest.mark.asyncio
    @patch("pecha_api.plans.users.recitation.user_recitations_services.get_texts_by_edition_or_text_ids")
    @patch("pecha_api.plans.users.recitation.user_recitations_services.get_image_url_map_by_text_ids")
    @patch("pecha_api.plans.users.recitation.user_recitations_services.get_user_recitations_by_user_id")
    @patch("pecha_api.plans.users.recitation.user_recitations_services.SessionLocal")
    @patch("pecha_api.plans.users.recitation.user_recitations_services.validate_and_extract_user_details")
    async def test_resolves_openpecha_edition_ids(
        self,
        mock_validate,
        mock_session_local,
        mock_get_user_recitations,
        mock_image_map,
        mock_get_texts,
    ):
        from types import SimpleNamespace
        from pecha_api.plans.users.recitation.user_recitations_services import (
            get_user_recitations_service,
        )

        edition_id = "KyaWXQG9NpDdBPnBMroGD"
        mock_validate.return_value = SimpleNamespace(id=uuid4())
        mock_session_local.return_value.__enter__.return_value = MagicMock()
        mock_get_user_recitations.return_value = [
            SimpleNamespace(text_id=edition_id, display_order=1)
        ]
        mock_get_texts.return_value = {
            edition_id: SimpleNamespace(title="Refuge", language="zh")
        }
        mock_image_map.return_value = {}

        result = await get_user_recitations_service(token="valid_token")

        mock_get_texts.assert_awaited_once_with([edition_id])
        assert [r.text_id for r in result.recitations] == [edition_id]
        assert result.recitations[0].title == "Refuge"


class TestCreateUserRecitationService:
    @pytest.mark.asyncio
    @patch("pecha_api.plans.users.recitation.user_recitations_services.save_user_recitation")
    @patch("pecha_api.plans.users.recitation.user_recitations_services.get_max_display_order_for_user", return_value=2)
    @patch("pecha_api.plans.users.recitation.user_recitations_services.ensure_text_or_edition_exists")
    @patch("pecha_api.plans.users.recitation.user_recitations_services.SessionLocal")
    @patch("pecha_api.plans.users.recitation.user_recitations_services.validate_and_extract_user_details")
    async def test_saves_an_openpecha_edition_id(
        self, mock_validate, mock_session_local, mock_ensure, _max_order, mock_save,
    ):
        from types import SimpleNamespace
        from pecha_api.plans.users.recitation.user_recitations_response_models import (
            CreateUserRecitationRequest,
        )
        from pecha_api.plans.users.recitation.user_recitations_services import (
            create_user_recitation_service,
        )

        mock_validate.return_value = SimpleNamespace(id=uuid4())
        mock_session_local.return_value.__enter__.return_value = MagicMock()

        await create_user_recitation_service(
            token="valid_token",
            create_user_recitation_request=CreateUserRecitationRequest(text_id="KyaWXQG9NpDdBPnBMroGD"),
        )

        mock_ensure.assert_awaited_once_with("KyaWXQG9NpDdBPnBMroGD")
        saved = mock_save.call_args.kwargs["user_recitations"]
        assert saved.text_id == "KyaWXQG9NpDdBPnBMroGD"
        assert saved.display_order == 3

    @pytest.mark.asyncio
    @patch("pecha_api.plans.users.recitation.user_recitations_services.save_user_recitation")
    @patch(
        "pecha_api.plans.users.recitation.user_recitations_services.ensure_text_or_edition_exists",
        side_effect=HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Text not found"),
    )
    @patch("pecha_api.plans.users.recitation.user_recitations_services.SessionLocal")
    @patch("pecha_api.plans.users.recitation.user_recitations_services.validate_and_extract_user_details")
    async def test_does_not_save_an_unknown_id(
        self, mock_validate, mock_session_local, _ensure, mock_save,
    ):
        from types import SimpleNamespace
        from pecha_api.plans.users.recitation.user_recitations_response_models import (
            CreateUserRecitationRequest,
        )
        from pecha_api.plans.users.recitation.user_recitations_services import (
            create_user_recitation_service,
        )

        mock_validate.return_value = SimpleNamespace(id=uuid4())
        mock_session_local.return_value.__enter__.return_value = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await create_user_recitation_service(
                token="valid_token",
                create_user_recitation_request=CreateUserRecitationRequest(text_id="unknown"),
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
        mock_save.assert_not_called()
