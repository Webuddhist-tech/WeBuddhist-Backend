import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException
from jose import JWTError
from jose.exceptions import JWTClaimsError
from jwt import ExpiredSignatureError
from starlette import status
from uuid import uuid4, UUID
from typing import List

from pecha_api.plans.platform_enums import PlatformRole
from pecha_api.plans.authors.plan_authors_service import (
    validate_and_extract_author_details,
    get_author_details,
    update_author_info,
    get_authors,
    update_social_profiles,
    get_selected_author_details,
    get_plans_by_author,
    _get_author_details_by_id,
    _get_author_social_profile
)
from pecha_api.plans.authors.plan_authors_response_models import (
    AuthorInfoResponse,
    AuthorInfoRequest,
    SocialMediaProfile,
    AuthorsResponse,
    AuthorUpdateResponse,
    AuthorPlansResponse,
    AuthorPlanDTO,
    AuthorInfoPublicResponse,
    ImageUrlModel,
)
from pecha_api.users.users_enums import SocialProfile
from pecha_api.error_contants import ErrorConstants
import jose


class TestValidateAndExtractAuthorDetails:
    """Test cases for validate_and_extract_author_details function."""

    @patch('pecha_api.plans.authors.plan_authors_service.SessionLocal')
    @patch('pecha_api.plans.authors.plan_authors_service.find_author_by_id')
    @patch('pecha_api.plans.authors.plan_authors_service.validate_token')
    def test_validate_and_extract_author_details_success(
        self,
        mock_validate_token: MagicMock,
        mock_find_author_by_id: MagicMock,
        mock_session_local: MagicMock
    ) -> None:
        """CMS tokens resolve solely from the UUID subject."""
        token = "valid_token"
        author_id = uuid4()
        expected_author = MagicMock()
        mock_db_session = MagicMock()
        mock_session_local.return_value.__enter__.return_value = mock_db_session
        mock_validate_token.return_value = {"sub": str(author_id), "email": "stale@example.com"}
        mock_find_author_by_id.return_value = expected_author

        result = validate_and_extract_author_details(token)

        assert result == expected_author
        mock_validate_token.assert_called_once_with(token)
        mock_find_author_by_id.assert_called_once_with(db=mock_db_session, author_id=author_id)

    @patch('pecha_api.plans.authors.plan_authors_service.SessionLocal')
    @patch('pecha_api.plans.authors.plan_authors_service.find_author_by_user_id')
    @patch('pecha_api.plans.authors.plan_authors_service.resolve_user_from_payload')
    @patch('pecha_api.plans.authors.plan_authors_service.find_author_by_id')
    @patch('pecha_api.plans.authors.plan_authors_service.validate_token')
    def test_validate_and_extract_author_details_rejects_email_fallback(
        self,
        mock_validate_token: MagicMock,
        mock_find_author_by_id: MagicMock,
        mock_resolve_user_from_payload: MagicMock,
        mock_find_author_by_user_id: MagicMock,
        mock_session_local: MagicMock
    ) -> None:
        """A matching email does not bind a website User token to an Author
        unless the User has a persisted Author.user_id link."""
        token = "website_token"
        user_id = str(uuid4())
        mock_session_local.return_value.__enter__.return_value = MagicMock()
        mock_validate_token.return_value = {"sub": user_id, "email": "person@example.com"}
        mock_find_author_by_id.return_value = None
        mock_resolve_user_from_payload.return_value = MagicMock()
        mock_find_author_by_user_id.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            validate_and_extract_author_details(token)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc_info.value.detail == ErrorConstants.TOKEN_ERROR_MESSAGE

    @patch('pecha_api.plans.authors.plan_authors_service.SessionLocal')
    @patch('pecha_api.plans.authors.plan_authors_service.find_author_by_user_id')
    @patch('pecha_api.plans.authors.plan_authors_service.resolve_user_from_payload')
    @patch('pecha_api.plans.authors.plan_authors_service.find_author_by_id')
    @patch('pecha_api.plans.authors.plan_authors_service.validate_token')
    def test_validate_and_extract_author_details_rejects_phone_fallback(
        self,
        mock_validate_token: MagicMock,
        mock_find_author_by_id: MagicMock,
        mock_resolve_user_from_payload: MagicMock,
        mock_find_author_by_user_id: MagicMock,
        mock_session_local: MagicMock
    ) -> None:
        """A matching phone does not bind a website User token to an Author
        unless the User has a persisted Author.user_id link."""
        token = "website_token"
        user_id = str(uuid4())
        mock_session_local.return_value.__enter__.return_value = MagicMock()
        mock_validate_token.return_value = {"sub": user_id, "phone_number": "+15551234567"}
        mock_find_author_by_id.return_value = None
        mock_resolve_user_from_payload.return_value = MagicMock()
        mock_find_author_by_user_id.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            validate_and_extract_author_details(token)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc_info.value.detail == ErrorConstants.TOKEN_ERROR_MESSAGE

    @patch('pecha_api.plans.authors.plan_authors_service.SessionLocal')
    @patch('pecha_api.plans.authors.plan_authors_service.resolve_user_from_payload')
    @patch('pecha_api.plans.authors.plan_authors_service.find_author_by_id')
    @patch('pecha_api.plans.authors.plan_authors_service.validate_token')
    def test_validate_and_extract_author_details_website_token_no_matching_author(
        self,
        mock_validate_token: MagicMock,
        mock_find_author_by_id: MagicMock,
        mock_resolve_user_from_payload: MagicMock,
        mock_session_local: MagicMock
    ) -> None:
        """A website token whose subject is not an Author id, and whose User
        has no linked Author, is unauthorized."""
        token = "website_token"
        user_id = str(uuid4())
        mock_session_local.return_value.__enter__.return_value = MagicMock()
        mock_validate_token.return_value = {"sub": user_id, "email": "nobody@example.com"}
        mock_find_author_by_id.return_value = None
        mock_resolve_user_from_payload.side_effect = HTTPException(status_code=status.HTTP_404_NOT_FOUND)

        with pytest.raises(HTTPException) as exc_info:
            validate_and_extract_author_details(token)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc_info.value.detail == ErrorConstants.TOKEN_ERROR_MESSAGE

    @patch('pecha_api.plans.authors.plan_authors_service.SessionLocal')
    @patch('pecha_api.plans.authors.plan_authors_service.find_author_by_user_id')
    @patch('pecha_api.plans.authors.plan_authors_service.resolve_user_from_payload')
    @patch('pecha_api.plans.authors.plan_authors_service.find_author_by_id')
    @patch('pecha_api.plans.authors.plan_authors_service.validate_token')
    def test_validate_and_extract_author_details_resolves_via_linked_user(
        self,
        mock_validate_token: MagicMock,
        mock_find_author_by_id: MagicMock,
        mock_resolve_user_from_payload: MagicMock,
        mock_find_author_by_user_id: MagicMock,
        mock_session_local: MagicMock
    ) -> None:
        """A website User token resolves to an Author only through the
        persisted Author.user_id link, not through matching contact info."""
        token = "website_token"
        user_id = uuid4()
        mock_db_session = MagicMock()
        mock_session_local.return_value.__enter__.return_value = mock_db_session
        mock_validate_token.return_value = {"sub": str(user_id), "email": "person@example.com"}
        mock_find_author_by_id.return_value = None
        mock_user = MagicMock()
        mock_user.id = user_id
        mock_resolve_user_from_payload.return_value = mock_user
        expected_author = MagicMock()
        mock_find_author_by_user_id.return_value = expected_author

        result = validate_and_extract_author_details(token)

        assert result == expected_author
        mock_find_author_by_user_id.assert_called_once_with(db=mock_db_session, user_id=user_id)

    @patch('pecha_api.plans.authors.plan_authors_service.validate_token')
    def test_validate_and_extract_author_details_missing_email(
        self, 
        mock_validate_token
    ):
        """Test token validation when email is missing from payload."""
        # Arrange
        token = "token_without_email"
        mock_validate_token.return_value = {"name": "test_user"}  # No email field

        # Act & Assert
        with pytest.raises(HTTPException) as exc_info:
            validate_and_extract_author_details(token)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc_info.value.detail == ErrorConstants.TOKEN_ERROR_MESSAGE

    @patch('pecha_api.plans.authors.plan_authors_service.validate_token')
    def test_validate_and_extract_author_details_none_email(
        self, 
        mock_validate_token
    ):
        """Test token validation when email is None in payload."""
        # Arrange
        token = "token_with_none_email"
        mock_validate_token.return_value = {"email": None}

        # Act & Assert
        with pytest.raises(HTTPException) as exc_info:
            validate_and_extract_author_details(token)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc_info.value.detail == ErrorConstants.TOKEN_ERROR_MESSAGE

    @patch('pecha_api.plans.authors.plan_authors_service.validate_token')
    def test_validate_and_extract_author_details_expired_signature_error(
        self, 
        mock_validate_token
    ):
        """Test handling of ExpiredSignatureError from jwt library."""
        # Arrange
        token = "expired_token"
        mock_validate_token.side_effect = ExpiredSignatureError("Token has expired")

        # Act & Assert
        with pytest.raises(HTTPException) as exc_info:
            validate_and_extract_author_details(token)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc_info.value.detail == ErrorConstants.TOKEN_ERROR_MESSAGE

    @patch('pecha_api.plans.authors.plan_authors_service.validate_token')
    def test_validate_and_extract_author_details_jose_expired_signature_error(
        self, 
        mock_validate_token
    ):
        """Test handling of jose.ExpiredSignatureError."""
        # Arrange
        token = "expired_token"
        mock_validate_token.side_effect = jose.ExpiredSignatureError("Token has expired")

        # Act & Assert
        with pytest.raises(HTTPException) as exc_info:
            validate_and_extract_author_details(token)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc_info.value.detail == ErrorConstants.TOKEN_ERROR_MESSAGE

    @patch('pecha_api.plans.authors.plan_authors_service.validate_token')
    def test_validate_and_extract_author_details_jwt_claims_error(
        self, 
        mock_validate_token
    ):
        """Test handling of JWTClaimsError."""
        # Arrange
        token = "invalid_claims_token"
        mock_validate_token.side_effect = JWTClaimsError("Invalid claims")

        # Act & Assert
        with pytest.raises(HTTPException) as exc_info:
            validate_and_extract_author_details(token)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc_info.value.detail == ErrorConstants.TOKEN_ERROR_MESSAGE

    @patch('pecha_api.plans.authors.plan_authors_service.validate_token')
    def test_validate_and_extract_author_details_value_error(
        self, 
        mock_validate_token
    ):
        """Test handling of ValueError."""
        # Arrange
        token = "invalid_token"
        mock_validate_token.side_effect = ValueError("Invalid token format")

        # Act & Assert
        with pytest.raises(HTTPException) as exc_info:
            validate_and_extract_author_details(token)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc_info.value.detail == ErrorConstants.TOKEN_ERROR_MESSAGE

    @patch('pecha_api.plans.authors.plan_authors_service.validate_token')
    def test_validate_and_extract_author_details_jwt_error(
        self, 
        mock_validate_token
    ):
        """Test handling of JWTError."""
        # Arrange
        token = "jwt_error_token"
        mock_validate_token.side_effect = JWTError("JWT error")

        # Act & Assert
        with pytest.raises(HTTPException) as exc_info:
            validate_and_extract_author_details(token)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc_info.value.detail == ErrorConstants.TOKEN_ERROR_MESSAGE

    @patch('pecha_api.plans.authors.plan_authors_service.SessionLocal')
    @patch('pecha_api.plans.authors.plan_authors_service.find_author_by_id')
    @patch('pecha_api.plans.authors.plan_authors_service.validate_token')
    def test_validate_and_extract_author_details_database_error(
        self, 
        mock_validate_token, 
        mock_find_author_by_id, 
        mock_session_local
    ):
        """Test handling of database session error."""
        token = "valid_token"
        mock_validate_token.return_value = {"sub": str(uuid4())}
        mock_session_local.side_effect = Exception("Database connection error")

        with pytest.raises(Exception) as exc_info:
            validate_and_extract_author_details(token)

        assert str(exc_info.value) == "Database connection error"

    @patch('pecha_api.plans.authors.plan_authors_service.SessionLocal')
    @patch('pecha_api.plans.authors.plan_authors_service.resolve_user_from_payload')
    @patch('pecha_api.plans.authors.plan_authors_service.find_author_by_id')
    @patch('pecha_api.plans.authors.plan_authors_service.validate_token')
    def test_validate_and_extract_author_details_author_not_found(
        self,
        mock_validate_token,
        mock_find_author_by_id,
        mock_resolve_user_from_payload,
        mock_session_local
    ):
        """A UUID subject with no Author row and no User row is unauthorized."""
        token = "valid_token"
        author_id = uuid4()
        mock_db_session = MagicMock()
        mock_session_local.return_value.__enter__.return_value = mock_db_session
        mock_validate_token.return_value = {"sub": str(author_id)}
        mock_find_author_by_id.return_value = None
        mock_resolve_user_from_payload.side_effect = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

        with pytest.raises(HTTPException) as exc_info:
            validate_and_extract_author_details(token)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc_info.value.detail == ErrorConstants.TOKEN_ERROR_MESSAGE

    @patch('pecha_api.plans.authors.plan_authors_service.SessionLocal')
    @patch('pecha_api.plans.authors.plan_authors_service.find_author_by_user_id')
    @patch('pecha_api.plans.authors.plan_authors_service.resolve_user_from_payload')
    @patch('pecha_api.plans.authors.plan_authors_service.find_author_by_id')
    @patch('pecha_api.plans.authors.plan_authors_service.validate_token')
    def test_validate_and_extract_author_details_author_lookup_returns_none(
        self,
        mock_validate_token,
        mock_find_author_by_id,
        mock_resolve_user_from_payload,
        mock_find_author_by_user_id,
        mock_session_local
    ):
        """A well-formed token whose subject is not an Author, and whose User
        has no linked Author, is unauthorized."""
        token = "valid_token"
        mock_session_local.return_value.__enter__.return_value = MagicMock()
        mock_validate_token.return_value = {"sub": str(uuid4()), "email": "nonexistent@example.com"}
        mock_find_author_by_id.return_value = None
        mock_resolve_user_from_payload.return_value = MagicMock()
        mock_find_author_by_user_id.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            validate_and_extract_author_details(token)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc_info.value.detail == ErrorConstants.TOKEN_ERROR_MESSAGE

    @patch('pecha_api.plans.authors.plan_authors_service.SessionLocal')
    @patch('pecha_api.plans.authors.plan_authors_service.find_author_by_id')
    @patch('pecha_api.plans.authors.plan_authors_service.validate_token')
    def test_validate_and_extract_author_details_logging_debug_called(
        self, 
        mock_validate_token, 
        mock_find_author_by_id, 
        mock_session_local
    ):
        """Test that logging.debug is called for exceptions."""
        token = "invalid_token"
        mock_validate_token.side_effect = ValueError("Invalid token format")

        with patch('pecha_api.plans.authors.plan_authors_service.logging.debug') as mock_logging:
            with pytest.raises(HTTPException):
                validate_and_extract_author_details(token)
            
            mock_logging.assert_called_once_with("exception: Invalid token format")

    @patch('pecha_api.plans.authors.plan_authors_service.SessionLocal')
    @patch('pecha_api.plans.authors.plan_authors_service.find_author_by_id')
    @patch('pecha_api.plans.authors.plan_authors_service.validate_token')
    def test_validate_and_extract_author_details_database_session_context_manager(
        self, 
        mock_validate_token, 
        mock_find_author_by_id, 
        mock_session_local
    ):
        """Test that database session is properly used as context manager."""
        token = "valid_token"
        author_id = uuid4()
        expected_author = MagicMock()
        mock_db_session = MagicMock()
        mock_session_context = MagicMock()
        mock_session_context.__enter__.return_value = mock_db_session
        mock_session_local.return_value = mock_session_context
        mock_validate_token.return_value = {"sub": str(author_id)}
        mock_find_author_by_id.return_value = expected_author

        result = validate_and_extract_author_details(token)

        assert result == expected_author
        mock_session_local.assert_called_once()
        mock_session_context.__enter__.assert_called_once()
        mock_session_context.__exit__.assert_called_once()
        mock_find_author_by_id.assert_called_once_with(db=mock_db_session, author_id=author_id)


class TestDataFactory:
    """Factory class for creating test data objects."""
    
    @staticmethod
    def create_mock_author(
        author_id=None,
        first_name="John",
        last_name="Doe",
        email="john.doe@example.com",
        bio="Test bio",
        image_url="test-image.jpg",
        social_accounts=None
    ) -> MagicMock:
        """Create a mock Author object with specified attributes."""
        mock_author = MagicMock()
        mock_author.id = author_id or uuid4()
        mock_author.first_name = first_name
        mock_author.last_name = last_name
        mock_author.email = email
        mock_author.bio = bio
        mock_author.image_url = image_url
        mock_author.social_media_accounts = social_accounts or []
        return mock_author
    
    @staticmethod
    def create_mock_social_account(
        platform_name="FACEBOOK",
        profile_url="https://facebook.com/johndoe"
    ) -> MagicMock:
        """Create a mock AuthorSocialMediaAccount object."""
        mock_account = MagicMock()
        mock_account.platform_name = platform_name
        mock_account.profile_url = profile_url
        return mock_account
    
    @staticmethod
    def create_author_info_request(
        firstname="John",
        lastname="Doe",
        image_url="https://s3.amazonaws.com/bucket/test-image.jpg",
        bio="Updated bio",
        social_profiles=None
    ) -> AuthorInfoRequest:
        """Create an AuthorInfoRequest object."""
        if social_profiles is None:
            social_profiles = [
                SocialMediaProfile(
                    account=SocialProfile.FACEBOOK,
                    url="https://facebook.com/johndoe"
                )
            ]
        
        return AuthorInfoRequest(
            firstname=firstname,
            lastname=lastname,
            image_url=image_url,
            bio=bio,
            social_profiles=social_profiles
        )


class TestGetAuthors:
    """Test cases for get_authors function."""
    
    @patch('pecha_api.plans.authors.plan_authors_service.SessionLocal')
    @patch('pecha_api.plans.authors.plan_authors_service.get_all_authors')
    @patch('pecha_api.plans.authors.plan_authors_service.generate_presigned_access_url')
    @patch('pecha_api.plans.authors.plan_authors_service.get')
    @patch('pecha_api.plans.authors.plan_authors_service._get_author_social_profile')
    @pytest.mark.asyncio
    async def test_get_authors_success(
        self,
        mock_get_social_profile,
        mock_get_config,
        mock_generate_presigned_url,
        mock_get_all_authors,
        mock_session_local
    ):
        """Test successful retrieval of all authors."""
        # Arrange
        bucket_name = "test-bucket"
        presigned_url = "https://s3.amazonaws.com/test-bucket/test-image.jpg"
        
        mock_social_account = TestDataFactory.create_mock_social_account()
        mock_authors = [
            TestDataFactory.create_mock_author(social_accounts=[mock_social_account]),
            TestDataFactory.create_mock_author(
                first_name="Jane",
                last_name="Smith",
                email="jane.smith@example.com"
            )
        ]
        
        mock_db_session = MagicMock()
        mock_session_local.return_value.__enter__.return_value = mock_db_session
        mock_get_all_authors.return_value = mock_authors
        mock_get_config.return_value = bucket_name
        mock_generate_presigned_url.return_value = presigned_url
        mock_get_social_profile.return_value = [
            SocialMediaProfile(account=SocialProfile.FACEBOOK, url="https://facebook.com/johndoe")
        ]
        
        # Act
        result = await get_authors()
        
        # Assert
        assert isinstance(result, AuthorsResponse)
        assert len(result.authors) == 2
        assert result.skip == 0
        assert result.limit == 20
        assert result.total == 2
        
        # Verify first author
        first_author = result.authors[0]
        assert first_author.id == mock_authors[0].id
        assert first_author.firstname == mock_authors[0].first_name
        assert first_author.lastname == mock_authors[0].last_name
        assert first_author.email == mock_authors[0].email
        assert first_author.bio == mock_authors[0].bio
        assert first_author.image_url == presigned_url
        
        # Verify function calls
        mock_get_all_authors.assert_called_once_with(db=mock_db_session)
        mock_get_config.assert_called_with("AWS_BUCKET_NAME")
        assert mock_generate_presigned_url.call_count == 2
    
    @patch('pecha_api.plans.authors.plan_authors_service.SessionLocal')
    @patch('pecha_api.plans.authors.plan_authors_service.get_all_authors')
    @patch('pecha_api.plans.authors.plan_authors_service.generate_presigned_access_url')
    @patch('pecha_api.plans.authors.plan_authors_service.get')
    @patch('pecha_api.plans.authors.plan_authors_service._get_author_social_profile')
    @pytest.mark.asyncio
    async def test_get_authors_empty_list(
        self,
        mock_get_social_profile,
        mock_get_config,
        mock_generate_presigned_url,
        mock_get_all_authors,
        mock_session_local
    ):
        """Test get_authors when no authors exist."""
        # Arrange
        mock_db_session = MagicMock()
        mock_session_local.return_value.__enter__.return_value = mock_db_session
        mock_get_all_authors.return_value = []
        
        # Act
        result = await get_authors()
        
        # Assert
        assert isinstance(result, AuthorsResponse)
        assert len(result.authors) == 0
        assert result.skip == 0
        assert result.limit == 20
        assert result.total == 0
        
        mock_get_all_authors.assert_called_once_with(db=mock_db_session)


class TestGetAuthorDetails:
    """Test cases for get_author_details function."""
    
    @patch('pecha_api.plans.authors.plan_authors_service.generate_presigned_access_url')
    @patch('pecha_api.plans.authors.plan_authors_service.get')
    @patch('pecha_api.plans.authors.plan_authors_service._get_author_social_profile')
    @patch('pecha_api.plans.authors.plan_authors_service.build_author_access_context', return_value={
        'platform_role': PlatformRole.CREATOR,
        'is_verified': True,
        'is_active': True,
        'has_group': True,
        'can_create_content': True,
    })
    @patch('pecha_api.plans.authors.plan_authors_service.validate_and_extract_author_details')
    @pytest.mark.asyncio
    async def test_get_author_details_success(
        self,
        mock_validate_and_extract,
        mock_build_author_access_context,
        mock_get_social_profile,
        mock_get_config,
        mock_generate_presigned_url,
    ):
        """Test successful retrieval of author details."""
        # Arrange
        token = "valid_token"
        bucket_name = "test-bucket"
        presigned_url = "https://s3.amazonaws.com/test-bucket/test-image.jpg"
        
        mock_social_account = TestDataFactory.create_mock_social_account()
        mock_author = TestDataFactory.create_mock_author(
            social_accounts=[mock_social_account]
        )
        social_profiles = [
            SocialMediaProfile(account=SocialProfile.FACEBOOK, url="https://facebook.com/johndoe")
        ]
        
        mock_validate_and_extract.return_value = mock_author
        mock_get_social_profile.return_value = social_profiles
        mock_get_config.return_value = bucket_name
        mock_generate_presigned_url.return_value = presigned_url
        
        # Act
        result = await get_author_details(token)
        
        # Assert
        assert isinstance(result, AuthorInfoResponse)
        assert result.id == mock_author.id
        assert result.firstname == mock_author.first_name
        assert result.lastname == mock_author.last_name
        assert result.email == mock_author.email
        assert result.bio == mock_author.bio
        assert result.image_url == presigned_url
        assert result.social_profiles == social_profiles
        
        # Verify function calls
        mock_validate_and_extract.assert_called_once_with(token=token)
        mock_get_social_profile.assert_called_once_with(author=mock_author)
        mock_get_config.assert_called_once_with("AWS_BUCKET_NAME")
        mock_generate_presigned_url.assert_called_once_with(
            bucket_name=bucket_name,
            s3_key=mock_author.image_url
        )


class TestUpdateSocialProfiles:
    """Test cases for update_social_profiles function."""
    
    def test_update_social_profiles_add_new_profile(self):
        """Test adding new social media profiles."""
        # Arrange
        author_id = uuid4()
        mock_author = TestDataFactory.create_mock_author(author_id=author_id)
        mock_author.social_media_accounts = []
        
        social_profiles = [
            SocialMediaProfile(
                account=SocialProfile.FACEBOOK,
                url="https://facebook.com/johndoe"
            )
        ]
        
        # Act
        update_social_profiles(mock_author, social_profiles)
        
        # Assert
        assert len(mock_author.social_media_accounts) == 1
        new_account = mock_author.social_media_accounts[0]
        assert new_account.author_id == author_id
        assert new_account.platform_name == "FACEBOOK"
        assert new_account.profile_url == "https://facebook.com/johndoe"
    
    def test_update_social_profiles_update_existing_profile(self):
        """Test updating existing social media profiles."""
        # Arrange
        author_id = uuid4()
        existing_account = TestDataFactory.create_mock_social_account(
            platform_name="FACEBOOK",
            profile_url="https://facebook.com/oldjohndoe"
        )
        mock_author = TestDataFactory.create_mock_author(
            author_id=author_id,
            social_accounts=[existing_account]
        )
        
        social_profiles = [
            SocialMediaProfile(
                account=SocialProfile.FACEBOOK,
                url="https://facebook.com/newjohndoe"
            )
        ]
        
        # Act
        update_social_profiles(mock_author, social_profiles)
        
        # Assert
        assert len(mock_author.social_media_accounts) == 1
        existing_account.profile_url = "https://facebook.com/newjohndoe"
    
    def test_update_social_profiles_empty_list(self):
        """Test update_social_profiles with empty social profiles list."""
        # Arrange
        mock_author = TestDataFactory.create_mock_author()
        mock_author.social_media_accounts = []
        
        # Act
        update_social_profiles(mock_author, [])
        
        # Assert
        assert len(mock_author.social_media_accounts) == 0
    
    def test_update_social_profiles_none_list(self):
        """Passing None should raise a TypeError under current implementation."""
        # Arrange
        mock_author = TestDataFactory.create_mock_author()
        mock_author.social_media_accounts = []
        
        # Act & Assert
        with pytest.raises(TypeError):
            update_social_profiles(mock_author, None)

    def test_update_social_profiles_delete_missing_profiles(self):
        """Profiles not present in incoming list must be removed from author."""
        # Arrange
        author_id = uuid4()
        existing_fb = TestDataFactory.create_mock_social_account(
            platform_name="FACEBOOK",
            profile_url="https://facebook.com/old"
        )
        existing_x = TestDataFactory.create_mock_social_account(
            platform_name="X_COM",
            profile_url="https://x.com/old"
        )
        mock_author = TestDataFactory.create_mock_author(
            author_id=author_id,
            social_accounts=[existing_fb, existing_x]
        )

        # Only keep FACEBOOK, drop X_COM
        social_profiles = [
            SocialMediaProfile(account=SocialProfile.FACEBOOK, url="https://facebook.com/new")
        ]

        # Act
        update_social_profiles(mock_author, social_profiles)

        # Assert
        assert len(mock_author.social_media_accounts) == 1
        remaining = mock_author.social_media_accounts[0]
        assert remaining.platform_name == "FACEBOOK"
        assert remaining.profile_url == "https://facebook.com/new"


class TestUpdateAuthorInfo:
    """Test cases for update_author_info function."""
    
    @patch('pecha_api.plans.authors.plan_authors_service.SessionLocal')
    @patch('pecha_api.plans.authors.plan_authors_service.update_author')
    @patch('pecha_api.plans.authors.plan_authors_service.update_social_profiles')
    @patch('pecha_api.plans.authors.plan_authors_service.Utils.extract_s3_key')
    @patch('pecha_api.plans.authors.plan_authors_service.validate_and_extract_author_details')
    @patch('pecha_api.plans.authors.plan_authors_service.generate_presigned_access_url')
    @patch('pecha_api.plans.authors.plan_authors_service.get')
    @pytest.mark.asyncio
    async def test_update_author_info_success(
        self,
        mock_get_config,
        mock_generate_presigned_url,
        mock_validate_and_extract,
        mock_extract_s3_key,
        mock_update_social_profiles,
        mock_update_author,
        mock_session_local
    ):
        """Test successful author info update."""
        # Arrange
        token = "valid_token"
        s3_key = "test-image.jpg"
        bucket_name = "test-bucket"
        presigned_url = "https://s3.amazonaws.com/test-bucket/test-image.jpg"
        
        mock_author = TestDataFactory.create_mock_author()
        updated_author = TestDataFactory.create_mock_author(
            first_name="Updated John",
            last_name="Updated Doe"
        )
        author_info_request = TestDataFactory.create_author_info_request()
        
        mock_db_session = MagicMock()
        mock_session_local.return_value.__enter__.return_value = mock_db_session
        mock_validate_and_extract.return_value = mock_author
        mock_extract_s3_key.return_value = s3_key
        mock_update_author.return_value = updated_author
        mock_get_config.return_value = bucket_name
        mock_generate_presigned_url.return_value = presigned_url
        
        # Act
        result = await update_author_info(token, author_info_request)
        
        # Assert
        assert isinstance(result, AuthorUpdateResponse)
        assert result.id == updated_author.id
        assert result.firstname == updated_author.first_name
        assert result.lastname == updated_author.last_name
        assert result.email == updated_author.email
        assert result.bio == updated_author.bio
        assert result.image_key == s3_key
        assert result.image_url == presigned_url
        assert mock_author.first_name == author_info_request.firstname
        assert mock_author.last_name == author_info_request.lastname
        assert mock_author.bio == author_info_request.bio
        assert mock_author.image_url == s3_key
        
        # Verify function calls
        mock_validate_and_extract.assert_called_once_with(token=token)
        mock_extract_s3_key.assert_called_once_with(presigned_url=author_info_request.image_url)
        mock_db_session.add.assert_called_once_with(mock_author)
        mock_update_social_profiles.assert_called_once_with(
            author=mock_author,
            social_profiles=author_info_request.social_profiles
        )
        mock_update_author.assert_called_once_with(db=mock_db_session, author=mock_author)
        mock_get_config.assert_called_once_with("AWS_BUCKET_NAME")
        mock_generate_presigned_url.assert_called_once_with(bucket_name=bucket_name, s3_key=updated_author.image_url)
    
    @patch('pecha_api.plans.authors.plan_authors_service.SessionLocal')
    @patch('pecha_api.plans.authors.plan_authors_service.update_author')
    @patch('pecha_api.plans.authors.plan_authors_service.update_social_profiles')
    @patch('pecha_api.plans.authors.plan_authors_service.Utils.extract_s3_key')
    @patch('pecha_api.plans.authors.plan_authors_service.validate_and_extract_author_details')
    @patch('pecha_api.plans.authors.plan_authors_service.logging.error')
    @pytest.mark.asyncio
    async def test_update_author_info_database_error(
        self,
        mock_logging_error,
        mock_validate_and_extract,
        mock_extract_s3_key,
        mock_update_social_profiles,
        mock_update_author,
        mock_session_local
    ):
        """Test update_author_info when database operation fails."""
        # Arrange
        token = "valid_token"
        s3_key = "test-image.jpg"
        
        mock_author = TestDataFactory.create_mock_author()
        author_info_request = TestDataFactory.create_author_info_request()
        
        mock_db_session = MagicMock()
        mock_session_local.return_value.__enter__.return_value = mock_db_session
        mock_validate_and_extract.return_value = mock_author
        mock_extract_s3_key.return_value = s3_key
        mock_update_author.side_effect = Exception("Database error")
        
        # Act & Assert
        with pytest.raises(HTTPException) as exc_info:
            await update_author_info(token, author_info_request)
        
        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Internal Server Error"
        
        # Verify rollback was called
        mock_db_session.rollback.assert_called_once()
        mock_logging_error.assert_called_once_with("Failed to update user info: Database error")


class TestGetSelectedAuthorDetails:
    """Test cases for get_selected_author_details function."""
    
    @patch('pecha_api.plans.authors.plan_authors_service.generate_presigned_access_url')
    @patch('pecha_api.plans.authors.plan_authors_service.get')
    @patch('pecha_api.plans.authors.plan_authors_service._get_author_social_profile')
    @patch('pecha_api.plans.authors.plan_authors_service._get_author_details_by_id')
    @pytest.mark.asyncio
    async def test_get_selected_author_details_success(
        self,
        mock_get_author_by_id,
        mock_get_social_profile,
        mock_get_config,
        mock_generate_presigned_url
    ):
        """Test successful retrieval of selected author details."""
        # Arrange
        author_id = uuid4()
        bucket_name = "test-bucket"
        presigned_url = "https://s3.amazonaws.com/test-bucket/test-image.jpg"
        
        mock_author = TestDataFactory.create_mock_author(author_id=author_id)
        social_profiles = [
            SocialMediaProfile(account=SocialProfile.FACEBOOK, url="https://facebook.com/johndoe")
        ]
        
        mock_get_author_by_id.return_value = mock_author
        mock_get_social_profile.return_value = social_profiles
        mock_get_config.return_value = bucket_name
        mock_generate_presigned_url.return_value = presigned_url
        
        # Act
        result = await get_selected_author_details(author_id)
        
        # Assert
        assert isinstance(result, AuthorInfoPublicResponse)
        assert result.id == mock_author.id
        assert result.firstname == mock_author.first_name
        assert result.lastname == mock_author.last_name
        assert result.email == mock_author.email
        assert result.bio == mock_author.bio
        assert isinstance(result.image, ImageUrlModel)
        assert result.image.thumbnail == presigned_url
        assert result.image.medium == presigned_url
        assert result.image.original == presigned_url
        assert result.social_profiles == social_profiles
        
        # Verify function calls
        mock_get_author_by_id.assert_called_once_with(author_id=author_id)
        mock_get_social_profile.assert_called_once_with(author=mock_author)


class TestGetPlansByAuthor:
    """Test cases for get_plans_by_author function."""
    
    @patch('pecha_api.plans.authors.plan_authors_service._get_author_details_by_id')
    @patch('pecha_api.plans.authors.plan_authors_service.get_published_plans_by_author_id')
    @patch('pecha_api.plans.authors.plan_authors_service.generate_presigned_access_url')
    @patch('pecha_api.plans.authors.plan_authors_service.get')
    @pytest.mark.asyncio
    async def test_get_plans_by_author_success(
        self,
        mock_get_config,
        mock_generate_presigned_url,
        mock_get_published_plans,
        mock_get_author_by_id,
    ):
        """Test successful retrieval of plans by author."""
        # Arrange
        author_id = uuid4()
        bucket_name = "test-bucket"
        presigned_url = "https://s3.amazonaws.com/test-bucket/p1.jpg"

        mock_get_author_by_id.return_value = TestDataFactory.create_mock_author(author_id=author_id)
        plan_obj = MagicMock()
        plan_obj.id = uuid4()
        plan_obj.title = "Plan 1"
        plan_obj.description = "Desc"
        plan_obj.language = "en"
        plan_obj.image_url = "p1.jpg"
        aggregate = MagicMock()
        aggregate.plan = plan_obj
        aggregate.total_days = 10
        aggregate.subscription_count = 3
        mock_get_published_plans.return_value = ([aggregate], 1)
        mock_get_config.return_value = bucket_name
        mock_generate_presigned_url.return_value = presigned_url
        
        # Act
        result = await get_plans_by_author(author_id, skip=0, limit=20)
        
        # Assert
        assert isinstance(result, AuthorPlansResponse)
        assert result.skip == 0
        assert result.limit == 20
        assert result.total == 1
        assert len(result.plans) == 1
        assert result.plans[0].id == plan_obj.id
        assert result.plans[0].title == "Plan 1"
        assert result.plans[0].description == "Desc"
        assert result.plans[0].language == "en"
        assert result.plans[0].total_days == 10
        assert result.plans[0].subscription_count == 3
        assert isinstance(result.plans[0].image, ImageUrlModel)
        assert result.plans[0].image.thumbnail == presigned_url
        assert result.plans[0].image.medium == presigned_url
        assert result.plans[0].image.original == presigned_url
        mock_get_published_plans.assert_called_once()
        kwargs = mock_get_published_plans.call_args.kwargs
        assert kwargs["author_id"] == author_id
        assert kwargs["skip"] == 0
        assert kwargs["limit"] == 20
    
    @patch('pecha_api.plans.authors.plan_authors_service._get_author_details_by_id')
    @patch('pecha_api.plans.authors.plan_authors_service.get_published_plans_by_author_id')
    @patch('pecha_api.plans.authors.plan_authors_service.generate_presigned_access_url')
    @patch('pecha_api.plans.authors.plan_authors_service.get')
    @pytest.mark.asyncio
    async def test_get_plans_by_author_pagination(
        self,
        mock_get_config,
        mock_generate_presigned_url,
        mock_get_published_plans,
        mock_get_author_by_id,
    ):
        """Test pagination in get_plans_by_author."""
        # Arrange
        author_id = uuid4()
        mock_get_author_by_id.return_value = TestDataFactory.create_mock_author(author_id=author_id)

        # Repository returns paginated slice and total
        plan_a = MagicMock()
        plan_a.id = uuid4()
        plan_a.title = "A"
        plan_a.description = "DA"
        plan_a.language = "en"
        plan_a.image_url = "a.jpg"
        aggregate_a = MagicMock()
        aggregate_a.plan = plan_a
        aggregate_a.total_days = 7
        aggregate_a.subscription_count = 2

        plan_b = MagicMock()
        plan_b.id = uuid4()
        plan_b.title = "B"
        plan_b.description = "DB"
        plan_b.language = "en"
        plan_b.image_url = "b.jpg"
        aggregate_b = MagicMock()
        aggregate_b.plan = plan_b
        aggregate_b.total_days = 8
        aggregate_b.subscription_count = 4

        mock_get_published_plans.return_value = ([aggregate_a, aggregate_b], 5)
        mock_get_config.return_value = "bucket"
        # Need 6 URLs: 3 for plan_a (thumbnail, medium, original) and 3 for plan_b
        mock_generate_presigned_url.side_effect = [
            "url-a-thumb", "url-a-med", "url-a-orig",
            "url-b-thumb", "url-b-med", "url-b-orig"
        ]
        
        # Act
        result = await get_plans_by_author(author_id, skip=2, limit=2)
        
        # Assert
        assert isinstance(result, AuthorPlansResponse)
        assert result.skip == 2
        assert result.limit == 2
        assert result.total == 5
        assert len(result.plans) == 2
        
        # Check plan A
        assert result.plans[0].id == plan_a.id
        assert result.plans[0].title == "A"
        assert result.plans[0].description == "DA"
        assert result.plans[0].language == "en"
        assert result.plans[0].total_days == 7
        assert result.plans[0].subscription_count == 2
        assert isinstance(result.plans[0].image, ImageUrlModel)
        assert result.plans[0].image.thumbnail == "url-a-thumb"
        assert result.plans[0].image.medium == "url-a-med"
        assert result.plans[0].image.original == "url-a-orig"
        
        # Check plan B
        assert result.plans[1].id == plan_b.id
        assert result.plans[1].title == "B"
        assert result.plans[1].description == "DB"
        assert result.plans[1].language == "en"
        assert result.plans[1].total_days == 8
        assert result.plans[1].subscription_count == 4
        assert isinstance(result.plans[1].image, ImageUrlModel)
        assert result.plans[1].image.thumbnail == "url-b-thumb"
        assert result.plans[1].image.medium == "url-b-med"
        assert result.plans[1].image.original == "url-b-orig"


class TestGetAuthorDetailsById:
    """Test cases for _get_author_details_by_id function."""
    
    @patch('pecha_api.plans.authors.plan_authors_service.SessionLocal')
    @patch('pecha_api.plans.authors.plan_authors_service.get_author_by_id')
    @pytest.mark.asyncio
    async def test_get_author_details_by_id_success(
        self,
        mock_get_author_by_id,
        mock_session_local
    ):
        """Test successful retrieval of author by ID."""
        # Arrange
        author_id = uuid4()
        mock_author = TestDataFactory.create_mock_author(author_id=author_id)
        
        mock_db_session = MagicMock()
        mock_session_local.return_value.__enter__.return_value = mock_db_session
        mock_get_author_by_id.return_value = mock_author
        
        # Act
        result = await _get_author_details_by_id(author_id)
        
        # Assert
        assert result == mock_author
        mock_get_author_by_id.assert_called_once_with(db=mock_db_session, author_id=author_id)


class TestGetAuthorSocialProfile:
    """Test cases for _get_author_social_profile function."""
    
    @patch('pecha_api.plans.authors.plan_authors_service.get_social_profile')
    def test_get_author_social_profile_success(
        self,
        mock_get_social_profile
    ):
        """Test successful conversion of author social profiles."""
        # Arrange
        mock_social_accounts = [
            TestDataFactory.create_mock_social_account("FACEBOOK", "https://facebook.com/johndoe"),
            TestDataFactory.create_mock_social_account("X_COM", "https://x.com/johndoe")
        ]
        mock_author = TestDataFactory.create_mock_author(social_accounts=mock_social_accounts)
        
        mock_get_social_profile.side_effect = [SocialProfile.FACEBOOK, SocialProfile.X_COM]
        
        # Act
        result = _get_author_social_profile(mock_author)
        
        # Assert
        assert len(result) == 2
        
        assert result[0].account == SocialProfile.FACEBOOK
        assert result[0].url == "https://facebook.com/johndoe"
        
        assert result[1].account == SocialProfile.X_COM
        assert result[1].url == "https://x.com/johndoe"
        
        # Verify function calls
        assert mock_get_social_profile.call_count == 2
        mock_get_social_profile.assert_any_call(value="FACEBOOK")
        mock_get_social_profile.assert_any_call(value="X_COM")
    
    @patch('pecha_api.plans.authors.plan_authors_service.get_social_profile')
    def test_get_author_social_profile_empty(
        self,
        mock_get_social_profile
    ):
        """Test _get_author_social_profile with no social accounts."""
        # Arrange
        mock_author = TestDataFactory.create_mock_author(social_accounts=[])
        
        # Act
        result = _get_author_social_profile(mock_author)
        
        # Assert
        assert len(result) == 0
        mock_get_social_profile.assert_not_called()
